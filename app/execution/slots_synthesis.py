"""Add ``__slots__`` to a project's own class whose instance-attribute set is
PROVABLY CLOSED — never extended dynamically anywhere in the project.

``__slots__ = ("x", "y", ...)`` drops a class's per-instance ``__dict__`` and
fixes the attribute set to exactly the slotted names: smaller per-instance memory,
and a typo-attribute (``inst.colour = 1`` on a ``color`` class) becomes a loud
``AttributeError`` instead of a silent new attribute. When a class's instance
attributes are ONLY ever the ones its ``__init__`` (or ``@dataclass`` field list)
declares — never an off-field attribute set anywhere — slotting it is a
storage-only, value-preserving improvement: a linter only FLAGS the opportunity,
but :func:`add_slots` WRITES it, deterministically and for free. This is the
structural DUAL of freeze-dataclass — pre-anticipated at ``freeze_dataclass.py:43``,
which records that its whole-project mutated-attribute scan "is a clean, reusable
whole-project over-approximation — a future ``add-slots`` objective (``__slots__``
also requires no never-mutated-field violations) reuses it unchanged."

SOUNDNESS — the whole point. ``__slots__`` changes ONLY the storage mechanism, not
any observable VALUE, FOR a class whose attribute set is closed. The single failure
mode — an attribute STORE to a name not in ``__slots__`` now raising
``AttributeError`` at runtime — is closed STATICALLY by requiring the declared slot
tuple to be a SUPERSET of every attribute name ever stored on ANY instance of this
class anywhere in the project. That obligation is discharged by reusing
:func:`app.execution.freeze_dataclass.mutated_attribute_names` (the conservative
whole-project STORE / ``del`` / literal-``setattr`` over-approximation) over
:func:`app.execution.freeze_dataclass.all_module_sources` — the tests-INCLUSIVE
source set: a mock/fake that sets an off-slot attribute IS a real ``AttributeError``
under ``__slots__`` the pytest suite cannot fully cover, exactly the seal-final-method
reasoning. If ANY stored attribute name across the project is NOT in the proven field
set, the class is REFUSED (an honest no-op). Because the scan is name-only and
whole-project, this is deliberately conservative — a same-named attribute stored on an
UNRELATED object also refuses (soundness over recall) — so the objective fires only on
a class whose closed attribute vocabulary is provable. The slot tuple is built from the
proven instance-attribute set (the ``__init__`` ``self.<p> = <p>`` copies, or a
``@dataclass``'s field list) in SOURCE ORDER; it never invents a field (honest
under-claim).

A class is slotted ONLY when ALL of these hold (otherwise an honest no-op):

  - it has NO base other than the implicit ``object`` and no class keywords — a
    non-slotted base reintroduces ``__dict__`` (defeating the change) and
    ``__slots__`` + inheritance is subtle;
  - it does NOT already declare ``__slots__`` (idempotent: a second run sees it and
    is a byte-identical no-op);
  - NO class-level attribute name equals a would-be slot name — a slot name carrying
    a class-body default is a ``ValueError`` at class creation;
  - it is NOT a ``Protocol`` / ``ABC`` (``ABCMeta`` metaclass) / ``Enum`` family
    class — slots there are meaningless / harmful;
  - its instance-attribute set is statically ENUMERABLE — a boilerplate ``__init__``
    of ``self.<p> = <p>`` copies, or a ``@dataclass``; a ``**kwargs`` capture or a
    non-literal ``setattr`` / ``__dict__`` write defeats enumeration and refuses;
  - the proven field set is NON-EMPTY (nothing to slot);
  - the field set is a SUPERSET of the whole-project mutated-attribute set (the
    closed-attribute proof above);
  - (``refuse_public``) the class is NOT on the module's PUBLIC surface — external
    code Apex cannot see may set dynamic attributes on a published class.

The slot line is spliced at the class-body indent (after a leading docstring) via
:func:`app.execution.dataclass_rewrite._class_indent` /
``_leading_docstring_lines``; classes are processed in REVERSE source order so
earlier line spans stay valid, and :func:`app.execution.dataclass_rewrite.rejoin_guarded`
re-``ast.parse``s the result so a malformed splice is NEVER landed. NO version gate
(``__slots__`` is ancient). Deterministic (pure AST walk + line splice, no
clock/random/network; source-order-stable), stdlib-only, zero-token, idempotent.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import (
    _class_body_names,
    _class_indent,
    _find_init,
    _init_params,
    _is_pure_param_copy,
    _leading_docstring_lines,
    rejoin_guarded,
)
from app.execution.freeze_dataclass import (
    _class_only_object_base,
    dataclass_field_names,
    is_public_name,
    mutated_attribute_names,
)

__all__ = [
    "add_slots",
    "slottable_classes",
]

# Base / metaclass names whose presence means the class's attribute set is meant to
# be extension-driven (a Protocol/ABC implementer, or an Enum's member machinery) —
# slotting it is meaningless or harmful. Matched by the final ``.attr`` of a
# base/keyword value (a conservative over-approximation, soundness over recall),
# mirroring ``final_method._is_abstract_base_class``.
_ABSTRACT_BASE_NAMES = frozenset({
    "Protocol", "ABC", "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
_ABCMETA_NAMES = frozenset({"ABCMeta", "EnumMeta", "EnumType"})


def _is_dataclass_decorated(cls: ast.ClassDef) -> bool:
    """True when ``cls`` carries a ``@dataclass`` / ``@dataclasses.dataclass``
    decorator (bare or called) by NAME SHAPE — enough to choose the dataclass
    field-list extraction path. Provenance is not needed here: the slot set is
    proven sound by the whole-project closed-attribute scan regardless of which
    ``dataclass`` it is."""
    for dec in cls.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Name) and func.id == "dataclass":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "dataclass":
            return True
    return False


def _base_attr_name(base: ast.expr) -> str | None:
    """The bare name a base / metaclass value contributes: a ``Name``'s ``id``, a
    dotted ``Attribute``'s final ``.attr``, or a subscripted base's head name."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Subscript):
        return _base_attr_name(base.value)
    return None


def _is_abstract_or_enum(cls: ast.ClassDef) -> bool:
    """True when ``cls`` is a ``Protocol`` / ``ABC`` / ``Enum`` family class (by a
    base name) or carries an ``ABCMeta`` / ``EnumMeta`` ``metaclass=`` — a class
    whose attribute set is extension-driven, so slotting it is wrong."""
    for base in cls.bases:
        if _base_attr_name(base) in _ABSTRACT_BASE_NAMES:
            return True
    for kw in cls.keywords:
        if kw.arg == "metaclass" and _base_attr_name(kw.value) in _ABCMETA_NAMES:
            return True
    return False


def _init_field_names(init: ast.FunctionDef) -> list[str] | None:
    """The proven instance-attribute set from a plain ``__init__``: the ordered
    ``self.<p> = <p>`` pure-parameter copies, in source order, or ``None`` when the
    signature is one we cannot enumerate.

    Reuses ``dataclass_rewrite._init_params`` for the enumerability gate (``None`` on
    ``*args`` / ``**kwargs``, keyword-only / positional-only params, or a missing
    leading ``self``) and ``_is_pure_param_copy`` for the field test: only a plain
    ``self.<p> = <p>`` copy of a positional parameter contributes a field name. Other
    statements (validation, a computed ``self.x = f(...)``) are not field names — and
    any attribute they STORE is caught by the whole-project closed-attribute superset
    gate, which refuses the class."""
    params = _init_params(init)
    if params is None:
        return None  # an unrepresentable signature — the attribute set is not enumerable
    names: list[str] = []
    for param in params:
        if any(_is_pure_param_copy(stmt, param.arg) for stmt in init.body):
            names.append(param.arg)
    return names


def _field_names(cls: ast.ClassDef) -> list[str] | None:
    """The proven instance-attribute set for ``cls`` in source order, or ``None``
    when it cannot be enumerated.

    A ``@dataclass`` uses its declared field list
    (``freeze_dataclass.dataclass_field_names``, ClassVar-skipping). A plain class
    uses its boilerplate-``__init__`` pure-parameter copies (:func:`_init_field_names`);
    with no ``__init__`` a plain class has no enumerable instance attributes
    (``[]`` — the empty-field-set gate then refuses it)."""
    if _is_dataclass_decorated(cls):
        return dataclass_field_names(cls)
    init = _find_init(cls)
    if init is None:
        return []  # no constructor to read fields from — empty set → refused
    return _init_field_names(init)


def _is_nonliteral_setattr(call: ast.Call) -> bool:
    """True for a builtin ``setattr(<expr>, <name>, <value>)`` whose ``<name>`` is
    NOT a string literal — a computed attribute the static scan cannot enumerate."""
    func = call.func
    if not (isinstance(func, ast.Name) and func.id == "setattr"):
        return False
    if len(call.args) < 2:
        return False
    name_arg = call.args[1]
    return not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str))


def _is_dict_attr_store(node: ast.AST) -> bool:
    """True for a ``<expr>.__dict__[...] = ...`` write — a dynamic attribute store
    bypassing the declared field set."""
    if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)):
        return False
    value = node.value
    return isinstance(value, ast.Attribute) and value.attr == "__dict__"


def _has_dynamic_attr_store(cls: ast.ClassDef) -> bool:
    """True when ``cls``'s body uses a DYNAMIC attribute-store mechanism the static
    field enumeration cannot see — a ``setattr(<expr>, <non-literal>, ...)`` call (a
    computed attribute name) or a ``<expr>.__dict__[...] = ...`` write.

    Either makes the instance-attribute set unknowable, so the class is refused
    rather than slotted (a dynamic off-slot store would ``AttributeError`` under
    ``__slots__``). A literal ``setattr(o, "name", v)`` is NOT dynamic — its name is
    captured by the whole-project mutation scan — so it does not trip this gate."""
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and _is_nonliteral_setattr(node):
            return True
        if _is_dict_attr_store(node):
            return True
    return False


def _class_declares_slots(cls: ast.ClassDef) -> bool:
    """True when ``cls`` already binds ``__slots__`` in its body (the idempotency
    guard — a second run sees it and refuses). Reuses ``_class_body_names``."""
    return any("__slots__" in _class_body_names(stmt) for stmt in cls.body)


def _class_body_default_names(stmt: ast.stmt) -> list[str]:
    """The class-body names a single statement binds WITH A VALUE (a real default) —
    a plain ``x = ...`` ``Assign`` target, or an ``x: T = ...`` ``AnnAssign`` WITH a
    value. A BARE annotation ``x: T`` (no value) binds no class attribute, so it is
    excluded: that is the ``@dataclass`` field-declaration form, which does NOT clash
    with a slot of the same name. Reuses ``_class_body_names`` for the Assign case."""
    if isinstance(stmt, ast.AnnAssign):
        if stmt.value is None or not isinstance(stmt.target, ast.Name):
            return []
        return [stmt.target.id]
    if isinstance(stmt, ast.Assign):
        return _class_body_names(stmt)
    return []


def _class_attr_collides(cls: ast.ClassDef, fields: list[str]) -> bool:
    """True when a class-level attribute carrying a VALUE (a default) has the same
    name as a would-be slot — a slot name with a class-body default raises
    ``ValueError`` ("'x' in __slots__ conflicts with class variable") at class
    creation, so the class is refused. A bare field annotation (``x: int``, the
    ``@dataclass`` field form) is NOT a default and does not collide (see
    :func:`_class_body_default_names`)."""
    field_set = set(fields)
    for stmt in cls.body:
        if any(name in field_set for name in _class_body_default_names(stmt)):
            return True
    return False


class _ModuleContext(NamedTuple):
    """The per-module facts the slottability gate needs beyond the class itself: the
    module's raw ``source`` and physical ``lines`` (for the public-surface check and
    the splice), whether to apply the public-surface ``refuse_public`` gate (set by
    the objective; off for in-isolation reasoning), and the whole-project ``mutated``
    attribute-name over-approximation the closed-attribute proof reads."""

    source: str
    lines: list[str]
    refuse_public: bool
    mutated: set[str]


def _whole_project_mutated(sources: list[str]) -> set[str]:
    """Union of ``freeze_dataclass.mutated_attribute_names`` over every source — the
    whole-project attribute-store over-approximation the closed-attribute proof
    reads (every ``<expr>.<attr> =`` / ``+=`` / ``del`` / literal ``setattr``)."""
    mutated: set[str] = set()
    for src in sources:
        mutated |= mutated_attribute_names(src)
    return mutated


def _slot_fields(cls: ast.ClassDef, ctx: _ModuleContext) -> list[str] | None:
    """The slot field list to declare on ``cls``, in source order, or ``None`` when
    ``cls`` fails ANY soundness gate (an honest no-op).

    Gates (all must hold): no base other than ``object`` and no class keywords; not
    already ``__slots__``-declared; not a ``Protocol`` / ``ABC`` / ``Enum`` family
    class; (when ``ctx.refuse_public``) not on the module's public surface; no
    dynamic attribute-store mechanism; an enumerable, NON-EMPTY field set; no
    class-attr / slot-name collision; and the field set is a SUPERSET of the
    whole-project mutated-attribute set (the closed-attribute proof — ANY stored
    name outside the fields refuses)."""
    if not _class_only_object_base(cls):
        return None
    if _class_declares_slots(cls):
        return None
    if _is_abstract_or_enum(cls):
        return None
    if ctx.refuse_public and is_public_name(cls.name, ctx.source):
        return None
    if _has_dynamic_attr_store(cls):
        return None
    fields = _field_names(cls)
    if not fields:
        return None  # not enumerable / no instance attributes — nothing to slot
    if _class_attr_collides(cls, fields):
        return None
    if ctx.mutated - set(fields):
        return None  # a stored attr outside the field set — not a closed set
    return fields


def _slot_line(cls: ast.ClassDef, fields: list[str], lines: list[str]) -> str:
    """The ``__slots__ = (...)`` source line for ``cls`` at its body indent. The
    names are repr'd (single-quoted string literals) in source order, with a
    trailing comma so a single-field tuple stays a tuple."""
    indent = _class_indent(cls, lines)
    names = ", ".join(repr(name) for name in fields)
    return f"{indent}__slots__ = ({names},)"


def _slot_insertion_index(cls: ast.ClassDef, lines: list[str]) -> int:
    """The 0-based line index to splice the slot line at: the top of ``cls``'s body,
    AFTER a leading docstring (so the docstring stays ``__doc__``). Reuses
    ``dataclass_rewrite._leading_docstring_lines``."""
    body_first = cls.body[0].lineno - 1
    _doc_lines, body_start = _leading_docstring_lines(cls, lines, body_first)
    return body_start


def _collect_slot_edits(
    tree: ast.Module, ctx: _ModuleContext
) -> list[tuple[int, str]]:
    """The ``(insert_index, slot_line)`` splice for every slottable top-level class
    in ``tree``, in source order."""
    edits: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = _slot_fields(node, ctx)
        if fields is None:
            continue
        index = _slot_insertion_index(node, ctx.lines)
        edits.append((index, _slot_line(node, fields, ctx.lines)))
    return edits


def slottable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that are slottable when
    ``source`` is considered IN ISOLATION (single-module scan).

    Convenience for tests / single-file reasoning: uses ``source`` itself as the
    whole project, so the closed-attribute scan sees only this module. Sorted by
    source order. Returns ``[]`` on a syntax error. The objective's real plan uses
    the WHOLE project (tests included), which can only ADD refusals (more attribute
    stores), never remove them."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    ctx = _ModuleContext(
        source=source, lines=source.splitlines(), refuse_public=False,
        mutated=_whole_project_mutated([source]))
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _slot_fields(node, ctx) is not None:
            out.append(node.name)
    return out


def add_slots(
    source: str,
    project_sources: list[str] | None = None,
    *,
    refuse_public: bool = False,
) -> str | None:
    """Add ``__slots__`` to every slottable class in ``source``, or ``None`` when
    nothing changes.

    ``project_sources`` is the whole-project source set the closed-attribute
    over-approximation scans (it MUST include ``source`` itself); when ``None``,
    ``source`` is scanned in isolation (the conservative single-module floor). When
    ``refuse_public`` is set (the objective sets it — the file reaching it is a real
    importable module), a PUBLIC-surface class is REFUSED: external code Apex cannot
    see may set dynamic attributes on a published class. Classes are spliced in
    REVERSE source order so earlier line spans stay valid. Deterministic and
    idempotent (a class already declaring ``__slots__`` is not re-touched); the
    result is re-``ast.parse``d before return, so a malformed splice yields ``None``
    rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    scan_sources = [source] if project_sources is None else project_sources
    ctx = _ModuleContext(
        source=source, lines=source.splitlines(), refuse_public=refuse_public,
        mutated=_whole_project_mutated(scan_sources))

    edits = _collect_slot_edits(tree, ctx)
    if not edits:
        return None

    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so indices stay valid
    out_lines = list(ctx.lines)
    for index, slot_line in edits:
        out_lines[index:index] = [slot_line]
    return rejoin_guarded(source, out_lines)
