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
any observable VALUE, FOR a class whose attribute set is closed. The primary failure
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

A bare ``__slots__`` tuple (without ``__weakref__`` / ``__dict__`` in it) ALSO drops
two instance facilities, so it silently breaks two READ paths the store scan never
sees: (1) ``weakref.ref(inst)`` / ``weakref.proxy(inst)`` / a ``WeakValueDictionary`` /
``WeakKeyDictionary`` / ``WeakSet`` / ``WeakMethod`` raises ``TypeError`` ("cannot
create weak reference") with no ``__weakref__`` slot; (2) ``vars(inst)`` /
``inst.__dict__`` READ raises ``AttributeError`` / ``TypeError`` with no ``__dict__``.
So two more whole-project signals are computed in the SAME walk over the project
sources: ``project_weakrefs`` (any ``weakref.ref`` / ``proxy`` call or weakref-container
construction, matched on the trailing name so ``import weakref as wr`` / ``from weakref
import ref`` aliases count) and ``project_dict_reads`` (any ``<expr>.__dict__`` LOAD —
NOT the ``__dict__[...] =`` store, already covered — or a bare ``vars(...)`` call). The
name-only scan cannot prove THIS class's instances do not flow to such a site, so the
mere PRESENCE of EITHER signal anywhere in the project REFUSES slotting — the same
recall sacrifice the store scan already makes for a same-named store.

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
  - NO project source takes a WEAK REFERENCE (``weakref.ref`` / ``proxy`` / a
    ``Weak*`` container) — a missing ``__weakref__`` slot makes that a ``TypeError``;
  - NO project source READS an instance ``__dict__`` (``inst.__dict__`` LOAD or
    ``vars(inst)``) — a missing ``__dict__`` slot makes that an ``AttributeError`` /
    ``TypeError`` (the ``__dict__[...] =`` store is caught by the enumerability gate);
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

# A ``weakref.ref(inst)`` / ``weakref.proxy(inst)`` CALL takes a weak reference to its
# argument — which raises ``TypeError`` ("cannot create weak reference") on an instance
# of a class whose ``__slots__`` omits ``__weakref__``. Matched by the call's trailing
# name so ``import weakref as wr`` / ``from weakref import ref`` alias spellings count.
_WEAKREF_CALL_NAMES = frozenset({"ref", "proxy"})
# The weakref CONTAINERS — constructing any of these (a ``Name`` / ``Attribute`` whose
# trailing token is one of these) implies instances are weak-referenced as keys/values,
# the same missing-``__weakref__``-slot hazard. Matched on the trailing token too.
_WEAKREF_CONTAINER_NAMES = frozenset(
    {"WeakValueDictionary", "WeakKeyDictionary", "WeakSet", "WeakMethod"})
# Every ``weakref`` export whose call / construction takes a weak reference — the union
# of the call and container names. A module-level ``from weakref import <name> as <x>``
# binds the LOCAL token ``x`` to one of these, which the trailing-name scan alone MISSES
# (``r(inst)`` from ``from weakref import ref as r`` reads as a bare ``r`` ∉ these sets),
# so the alias map below re-canonicalises it — the exact clone of the runtime-skip
# ``from pytest import skip as s`` hole closed in ``stub_synthesis._collect_skip_aliases``.
_WEAKREF_CANONICALS = _WEAKREF_CALL_NAMES | _WEAKREF_CONTAINER_NAMES
# Modules whose ``ref`` / ``proxy`` / ``Weak*`` exports we trust as the genuine weak-ref
# surface (so a ``from somethingelse import ref`` of an UNRELATED ``ref`` is not mistaken
# for a weak reference). Mirrors ``stub_synthesis._SKIP_IMPORT_MODULES``.
_WEAKREF_IMPORT_MODULES = frozenset({"weakref"})

# The builtin ``vars(inst)`` returns ``inst.__dict__``; a ``from builtins import vars as
# v`` rebinds it to a LOCAL token (``v(inst)``), again invisible to a bare-name match, so
# the same alias resolution applies to the ``__dict__``-read scan.
_DICT_READ_CANONICALS = frozenset({"vars"})
_DICT_READ_IMPORT_MODULES = frozenset({"builtins"})


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


def _call_trailing_name(call: ast.Call) -> str | None:
    """The trailing token of a call's ``func`` — an ``Attribute``'s final ``.attr``
    (``weakref.ref(...)`` -> ``ref``) or a bare ``Name``'s ``id`` (``ref(...)`` from
    ``from weakref import ref`` -> ``ref``). Matching the trailing token (not the dotted
    head) is what makes the scan tolerant of ``import weakref as wr`` alias spellings."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _trailing_name(node: ast.expr) -> str | None:
    """The trailing token of a referenced value — an ``Attribute``'s final ``.attr`` or
    a ``Name``'s ``id`` — used to spot a weakref CONTAINER spelling (``weakref.WeakSet``
    or a ``from weakref import WeakSet`` bare ``WeakSet``) regardless of alias."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _collect_import_aliases(
    tree: ast.Module, modules: frozenset[str], canonicals: frozenset[str]
) -> set[str]:
    """The LOCAL names a module's top-level imports bind to any export in ``canonicals``
    that comes from a trusted ``modules`` source — so a ``from weakref import ref as r``
    (``ImportFrom``, module ``weakref``, export ``ref`` ∈ ``canonicals``) yields ``{"r"}``.
    An ``import weakref.ref as x`` style ``ast.Import`` whose dotted TAIL is a canonical
    contributes its ``asname`` too. Mirrors ``stub_synthesis._collect_skip_aliases`` (and
    the import-walking in ``type_annotations._module_bound_names``): only a trusted-module
    export is aliased, so a same-named export of an UNRELATED module is never resolved.

    A bare ``import weakref`` / ``import weakref as wr`` binds the MODULE, not a constructor,
    so it contributes NO local alias — the ``wr.ref`` attribute form already reads through
    the trailing-name heuristic and needs no entry (the attribute path stays unchanged)."""
    out: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            if stmt.module not in modules:
                continue
            for alias in stmt.names:
                if alias.name in canonicals:
                    out.add(alias.asname or alias.name)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                tail = alias.name.rsplit(".", 1)[-1]
                if alias.asname and tail in canonicals:
                    out.add(alias.asname)
    return out


def _call_is_weakref(call: ast.Call, aliases: set[str]) -> bool:
    """True when ``call``'s callee resolves to a weak-ref constructor: its trailing token
    is a known weak-ref call name (``weakref.ref`` / a non-aliased ``from weakref import
    ref``), OR a BARE-``Name`` callee whose id is a module-level ``from``-import ALIAS of
    one (``from weakref import ref as r`` -> ``r(inst)``). The trailing-token branch keeps
    the attribute form (``wr.ref``) and the un-renamed bare form working unchanged."""
    name = _call_trailing_name(call)
    if name in _WEAKREF_CALL_NAMES:
        return True
    return isinstance(call.func, ast.Name) and call.func.id in aliases


def _ref_is_weakref_container(node: ast.expr, aliases: set[str]) -> bool:
    """True when ``node`` references a weakref CONTAINER type: its trailing token is a
    known container name (``weakref.WeakSet`` / a non-aliased ``from weakref import
    WeakSet``), OR a BARE ``Name`` aliased to one at module level (``WeakSet as W``)."""
    if _trailing_name(node) in _WEAKREF_CONTAINER_NAMES:
        return True
    return isinstance(node, ast.Name) and node.id in aliases


def _source_weakrefs(source: str) -> bool:
    """True when ``source`` takes a WEAK REFERENCE to anything: a ``weakref.ref(...)`` /
    ``weakref.proxy(...)`` CALL (trailing name in :data:`_WEAKREF_CALL_NAMES`, OR a bare
    callee that is a module-level ``from weakref import ref as r`` ALIAS), or a reference
    to a weakref CONTAINER type (``WeakValueDictionary`` / ``WeakKeyDictionary`` /
    ``WeakSet`` / ``WeakMethod``, by trailing token OR by ``... as W`` alias) — its
    construction implies weak-referenced instances.

    The module-level import aliases are resolved FIRST (:func:`_collect_import_aliases`):
    a from-import rename binds a LOCAL token a trailing-name scan alone misses (``r(inst)``
    reads as bare ``r``), the exact clone of the runtime-skip ``from pytest import skip as
    s`` hole. A class whose instances flow to such a site needs a ``__weakref__`` slot; a
    name-only project-wide scan cannot prove they do NOT, so its mere PRESENCE refuses
    slotting (soundness over recall — the same conservatism the closed-attribute store scan
    keeps). Returns ``False`` on a syntax error (an unparseable module contributes no
    signal — the per-module parse is the same gate the store scan uses)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    aliases = _collect_import_aliases(
        tree, _WEAKREF_IMPORT_MODULES, _WEAKREF_CANONICALS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_is_weakref(node, aliases):
            return True
        if _ref_is_weakref_container(node, aliases):
            return True
    return False


def _store_subscript_dict_bases(tree: ast.AST) -> set[int]:
    """The ``id()``s of the ``<expr>.__dict__`` ``Attribute`` nodes that are the
    subscripted base of a ``<expr>.__dict__[...] = ...`` STORE.

    In ``inst.__dict__['z'] = 1`` the ``.__dict__`` attribute is itself a ``Load`` (the
    dict is loaded, then subscript-stored), so an unfiltered "``__dict__`` Load" scan
    would mistake that store for a READ. Pre-collecting these base nodes lets
    :func:`_source_dict_reads` exclude them by identity — the store is already refused by
    :func:`_is_dict_attr_store` via the dynamic-store gate."""
    bases: set[int] = set()
    for node in ast.walk(tree):
        if _is_dict_attr_store(node):
            bases.add(id(node.value))  # type: ignore[attr-defined]
    return bases


def _is_vars_call(node: ast.AST, aliases: set[str]) -> bool:
    """True for a call to the builtin ``vars`` by a bare ``Name`` — ``vars(inst)``, which
    returns ``inst.__dict__`` and so raises ``TypeError`` on a ``__dict__``-less
    ``__slots__`` instance — including a ``from builtins import vars as v`` rename whose
    LOCAL token ``v`` is in ``aliases`` (``v(inst)``). A dotted ``mod.vars(...)`` is NOT the
    builtin and does not match (no instance ``__dict__`` is read)."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return False
    return node.func.id == "vars" or node.func.id in aliases


def _is_getattr_dict_read(node: ast.AST) -> bool:
    """True for a ``getattr(<expr>, "__dict__"[, ...])`` call — the builtin ``getattr`` by
    a bare ``Name`` whose 2nd argument is the string literal ``"__dict__"``. This reads the
    instance ``__dict__`` exactly as ``inst.__dict__`` does (raising on a ``__dict__``-less
    ``__slots__`` instance), but as a CALL it slips past the ``.__dict__`` attribute scan —
    so it is matched here. A non-literal 2nd arg (a computed name) is conservatively NOT
    matched by this specific shape; the field-enumeration gate covers dynamic access."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2):
        return False
    name_arg = node.args[1]
    return isinstance(name_arg, ast.Constant) and name_arg.value == "__dict__"


def _source_dict_reads(source: str) -> bool:
    """True when ``source`` READS instance ``__dict__`` / calls ``vars(...)``: an
    ``<expr>.__dict__`` attribute LOAD (excluding the ``__dict__[...] =`` store base), a
    call to the builtin ``vars`` (bare ``Name`` or a ``from builtins import vars as v``
    ALIAS), or a ``getattr(<expr>, "__dict__")`` call (the CALL form that bypasses the
    attribute scan).

    All raise ``AttributeError`` / ``TypeError`` on a ``__slots__`` instance that lacks a
    ``__dict__``, so a class whose instances flow to any is silently broken by slotting. As
    with the weakref scan, module-level import aliases are resolved first so a ``vars``
    rename is not missed, and the name-only project-wide check cannot prove the class's
    instances do NOT reach the site, so its PRESENCE refuses slotting. The ``__dict__[...]
    =`` store is intentionally NOT matched here (already handled by the dynamic-store gate).
    Returns ``False`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    aliases = _collect_import_aliases(
        tree, _DICT_READ_IMPORT_MODULES, _DICT_READ_CANONICALS)
    store_bases = _store_subscript_dict_bases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "__dict__" \
                and isinstance(node.ctx, ast.Load) and id(node) not in store_bases:
            return True
        if _is_vars_call(node, aliases) or _is_getattr_dict_read(node):
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
    the objective; off for in-isolation reasoning), the whole-project ``mutated``
    attribute-name over-approximation the closed-attribute proof reads, and two
    whole-project READ signals that ``__slots__`` (without ``__weakref__`` / ``__dict__``
    in the tuple) silently breaks: ``project_weakrefs`` (any instance is weak-referenced
    anywhere) and ``project_dict_reads`` (any instance ``__dict__`` / ``vars()`` is READ
    anywhere). Either present -> refuse (the same recall sacrifice as same-named stores:
    a name-only scan cannot prove THIS class's instances do not flow to the site)."""

    source: str
    lines: list[str]
    refuse_public: bool
    mutated: set[str]
    project_weakrefs: bool
    project_dict_reads: bool


def _whole_project_mutated(sources: list[str]) -> set[str]:
    """Union of ``freeze_dataclass.mutated_attribute_names`` over every source — the
    whole-project attribute-store over-approximation the closed-attribute proof
    reads (every ``<expr>.<attr> =`` / ``+=`` / ``del`` / literal ``setattr``)."""
    mutated: set[str] = set()
    for src in sources:
        mutated |= mutated_attribute_names(src)
    return mutated


def _whole_project_weakrefs(sources: list[str]) -> bool:
    """True when ANY project source takes a weak reference (a ``weakref.ref`` /
    ``proxy`` call or a weakref-container construction) — the same walk that feeds
    :func:`_whole_project_mutated`, surfacing the missing-``__weakref__`` READ hazard."""
    return any(_source_weakrefs(src) for src in sources)


def _whole_project_dict_reads(sources: list[str]) -> bool:
    """True when ANY project source READS instance ``__dict__`` / calls ``vars(...)`` —
    the missing-``__dict__`` READ hazard, computed over the same source set as
    :func:`_whole_project_mutated`."""
    return any(_source_dict_reads(src) for src in sources)


def _build_context(
    source: str, scan_sources: list[str], *, refuse_public: bool
) -> _ModuleContext:
    """Assemble the :class:`_ModuleContext` for ``source`` from ``scan_sources`` (the
    whole-project source set). One walk-set computes all three project-wide signals —
    the mutated-attribute over-approximation plus the weakref and ``__dict__``-read READ
    hazards — so both builders share one construction path and stay in lockstep."""
    return _ModuleContext(
        source=source, lines=source.splitlines(), refuse_public=refuse_public,
        mutated=_whole_project_mutated(scan_sources),
        project_weakrefs=_whole_project_weakrefs(scan_sources),
        project_dict_reads=_whole_project_dict_reads(scan_sources))


def _slot_fields(cls: ast.ClassDef, ctx: _ModuleContext) -> list[str] | None:
    """The slot field list to declare on ``cls``, in source order, or ``None`` when
    ``cls`` fails ANY soundness gate (an honest no-op).

    Gates (all must hold): no base other than ``object`` and no class keywords; not
    already ``__slots__``-declared; not a ``Protocol`` / ``ABC`` / ``Enum`` family
    class; no whole-project weakref / ``__dict__``-or-``vars()``-READ signal (either
    would silently break under a ``__slots__`` lacking ``__weakref__`` / ``__dict__``);
    (when ``ctx.refuse_public``) not on the module's public surface; no dynamic
    attribute-store mechanism; an enumerable, NON-EMPTY field set; no class-attr /
    slot-name collision; and the field set is a SUPERSET of the whole-project
    mutated-attribute set (the closed-attribute proof — ANY stored name outside the
    fields refuses)."""
    if not _class_only_object_base(cls):
        return None
    if _class_declares_slots(cls):
        return None
    if _is_abstract_or_enum(cls):
        return None
    if ctx.project_weakrefs or ctx.project_dict_reads:
        return None  # a weakref / __dict__-READ site anywhere -> slotting silently breaks it
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
    ctx = _build_context(source, [source], refuse_public=False)
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
    ctx = _build_context(source, scan_sources, refuse_public=refuse_public)

    edits = _collect_slot_edits(tree, ctx)
    if not edits:
        return None

    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so indices stay valid
    out_lines = list(ctx.lines)
    for index, slot_line in edits:
        out_lines[index:index] = [slot_line]
    return rejoin_guarded(source, out_lines)
