"""Synthesize the canonical ``__repr__`` / ``__eq__`` / ``__hash__`` over a class's
PROVEN field set — the sibling of dataclassify for classes that CANNOT become
``@dataclass``.

``dataclassify`` (``dataclass_rewrite.rewrite_dataclasses``) converts a class whose
``__init__`` is PURE ``self.x = x`` boilerplate into a ``@dataclass`` — but it refuses
the moment the class has a base, an extra method, or any ``__init__`` statement beyond
the copies, because then the generated constructor would not reproduce the hand-written
one. Such a class still carries the SAME pure-copy fields and still deserves the value
semantics ``@dataclass`` would have given it for free. :func:`synthesize_dunders` LANDS
exactly that: into a regular (non-``@dataclass``) top-level class whose ``__init__``
contains pure ``self.<p> = <p>`` copies (TOLERATING a base, extra methods, and other
``__init__`` statements — only the provable copy SUBSET is read as the field set) and
that is MISSING ``__repr__`` and/or ``__eq__``, it splices the canonical TOTAL dunders
over that proven field set:

  - ``__repr__`` -> ``f"{type(self).__name__}(x={self.x!r}, y={self.y!r})"`` (the exact
    shape ``@dataclass`` emits — ``repr()`` only, no control flow);
  - ``__eq__`` -> an ``isinstance(other, type(self))`` guard returning
    ``NotImplemented`` on a type mismatch (so the reflected ``other.__eq__`` still runs),
    else a field-tuple ``==`` (``(self.x, self.y) == (other.x, other.y)``);
  - ``__hash__`` -> ``hash((self.x, self.y))`` — emitted ONLY when ``__eq__`` is NEWLY
    added, to PRESERVE hashability (defining ``__eq__`` alone sets ``__hash__`` to
    ``None`` — unhashable — so the consistent ``hash`` over the SAME field tuple keeps
    the class hashable, mirroring ``dataclass_rewrite``'s ``eq=``/hash reasoning).

Honest under-claim: it generates ONLY the canonical forms ``@dataclass`` itself emits
(already trusted across the codebase via ``dataclassify``) over a field set it can PROVE,
and never invents a field.

The field set is the SUBSET of ``__init__`` statements that are exactly
``self.<p> = <p>`` pure-parameter copies (``dataclass_rewrite._assignment_target_name`` +
``_is_pure_param_copy``), read off the non-self positional parameters
(``dataclass_rewrite._init_params`` — so a ``*args`` / ``**kwargs`` / keyword-only /
positional-only signature, whose attribute set is not enumerable, REFUSES). A class
whose provable copy subset is EMPTY is refused (nothing to range a dunder over).

INHERITED-CONTRACT GATE (the load-bearing soundness rail). Adding ``__eq__`` to a class
that INHERITS an ``__eq__`` would silently OVERRIDE the inherited equality contract — an
observable behaviour change a green suite can miss. So when the class has a base,
:func:`synthesize_dunders` resolves the base BY NAME within ``project_sources`` and
REFUSES adding ``__eq__`` if any resolvable base (transitively) defines ``__eq__``, OR if
the base is external / un-resolvable (cannot be proven safe — refuse on uncertainty).
``__repr__`` carries no such inherited contract (overriding a repr only changes the
debug string), so it is still added; ``__hash__`` rides with a newly-added ``__eq__`` and
so is gated by the same refusal.

A dunder already DEFINED on the class itself — as a method (sync/async) or a class-body
binding (``__eq__ = ...``) — is left untouched (idempotent: a second run sees the spliced
dunders and is a byte-identical no-op), reusing the ``dataclass_rewrite._class_defines_eq``
shape generalized to ``__repr__`` / ``__hash__``. An already-``@dataclass``-decorated
class is out of scope (``dataclassify`` / freeze own it) and refused.

Methods are spliced at the class-body indent (``dataclass_rewrite._class_indent``) at the
END of the class body; classes are processed in REVERSE source order so earlier line
spans stay valid, and ``dataclass_rewrite.rejoin_guarded`` re-``ast.parse``s the result so
a malformed splice is NEVER landed. Deterministic (pure AST walk + line splice over the
source bytes plus the project bytes, source-order-stable, no clock / random / network),
stdlib-only, zero-token, idempotent.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import (
    _class_body_names,
    _class_indent,
    _find_init,
    rejoin_guarded,
)
from app.execution.slots_synthesis import _init_field_names

__all__ = [
    "synthesize_dunders",
    "synthesizable_classes",
]


def _is_dataclass_decorated(cls: ast.ClassDef) -> bool:
    """True when ``cls`` carries a ``@dataclass`` / ``@dataclasses.dataclass``
    decorator (bare or called) by NAME SHAPE — such a class is out of scope here
    (``dataclassify`` / freeze own its value semantics), so it is refused. Mirrors
    ``slots_synthesis._is_dataclass_decorated``."""
    for dec in cls.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Name) and func.id == "dataclass":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "dataclass":
            return True
    return False


def _proven_fields(cls: ast.ClassDef) -> list[str] | None:
    """The ordered field set the dunders range over — the SUBSET of ``__init__``
    statements that are exactly ``self.<p> = <p>`` pure-parameter copies, in source
    order — or ``None`` when ``cls`` has no usable ``__init__`` / an unenumerable
    signature.

    TOLERATES (unlike ``dataclassify``) a base class, extra methods, and ``__init__``
    statements beyond the copies: only the provable copy subset is collected. The
    enumerable-``__init__`` pure-copy extraction is shared VERBATIM with add-slots —
    delegated to ``slots_synthesis._init_field_names`` (which reuses
    ``dataclass_rewrite._init_params`` for the enumerability gate — ``None`` on
    ``*args`` / ``**kwargs`` / keyword-only / positional-only / missing ``self`` — and
    ``_is_pure_param_copy`` for the per-statement field test). An EMPTY proven subset is
    returned as ``[]`` — the caller refuses it (nothing to range a dunder over)."""
    init = _find_init(cls)
    if init is None:
        return None  # no constructor to read fields from
    return _init_field_names(init)


def _class_defines_dunder(cls: ast.ClassDef, name: str) -> bool:
    """True when ``cls`` defines ``name`` ITSELF — as a method (sync/async) or a
    class-body binding (``name = ...``). The generalized form of
    ``dataclass_rewrite._class_defines_eq`` (which hard-codes ``__eq__``), used as the
    presence/idempotency guard for ``__repr__`` / ``__eq__`` / ``__hash__``: a dunder
    already present is left untouched (never overwrite a hand-written one)."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            stmt.name == name
        ):
            return True
        if name in _class_body_names(stmt):
            return True
    return False


def _base_name(base: ast.expr) -> str | None:
    """The bare class name a BASE expression contributes: a ``Name``'s ``id``, a dotted
    ``Attribute``'s final ``.attr`` (``pkg.C`` -> ``"C"``), or a subscripted base's head
    name (``Foo[int]`` -> ``"Foo"``). Any other base form (a call, etc.) contributes
    ``None``. Mirrors ``freeze_dataclass._base_name``."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Subscript):
        return _base_name(base.value)
    return None


def _classes_by_name(sources: list[str]) -> dict[str, ast.ClassDef]:
    """Every top-level ``ClassDef`` across ``sources``, keyed by name (LAST definition
    wins on a duplicate name — an over-approximation that only ADDS refusals). The
    by-name index the inherited-``__eq__`` base scan resolves bases against; a source
    that does not parse contributes nothing."""
    index: dict[str, ast.ClassDef] = {}
    for src in sources:
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                index[node.name] = node
    return index


def _defines_eq_directly(cls: ast.ClassDef) -> bool:
    """True when ``cls`` defines ``__eq__`` on ITS OWN body — method or
    ``__eq__ = ...`` binding. The single-class predicate the transitive base scan
    walks; reuses :func:`_class_defines_dunder`."""
    return _class_defines_dunder(cls, "__eq__")


def _inherited_eq_is_safe(
    cls: ast.ClassDef, index: dict[str, ast.ClassDef]
) -> bool:
    """True when adding ``__eq__`` to ``cls`` would NOT override an inherited equality
    contract — the inherited-``__eq__`` soundness gate.

    A class with NO base is always safe (the implicit ``object.__eq__`` is identity,
    which our value-``==`` is meant to replace — exactly the landed feature). With a
    base, EVERY base must resolve BY NAME within ``index`` (the project's own classes)
    AND neither it NOR any of ITS bases (transitively) may define ``__eq__``. An
    external / un-resolvable base, or any resolvable base that (transitively) defines
    ``__eq__``, makes the result UNSAFE (cannot prove we are not silently overriding an
    inherited ``__eq__``) -> refuse. A cycle / re-visited base is treated as safe-so-far
    (the ``seen`` guard just stops infinite recursion; an actual ``__eq__`` on the cycle
    is still caught the first time it is visited)."""
    seen: set[int] = set()

    def _base_chain_clean(node: ast.ClassDef) -> bool:
        for base in node.bases:
            name = _base_name(base)
            if name is None:
                return False  # a non-name base form — cannot prove safe
            if name == "object":
                continue  # the implicit identity __eq__ we intend to replace
            parent = index.get(name)
            if parent is None:
                return False  # external / un-resolvable base — refuse
            if id(parent) in seen:
                continue  # already cleared on this walk
            seen.add(id(parent))
            if _defines_eq_directly(parent):
                return False  # a base defines __eq__ — adding ours would override it
            if not _base_chain_clean(parent):
                return False
        return True

    return _base_chain_clean(cls)


def _repr_method_lines(fields: list[str], indent: str) -> list[str]:
    """The canonical ``__repr__`` method lines at the class-body ``indent`` — the exact
    shape ``@dataclass`` emits: ``f"{type(self).__name__}(x={self.x!r}, ...)"``."""
    parts = ", ".join(f"{name}={{self.{name}!r}}" for name in fields)
    body = "    "  # one method-body level beneath the class-body indent
    return [
        f"{indent}def __repr__(self) -> str:",
        f'{indent}{body}return f"{{type(self).__name__}}({parts})"',
    ]


def _field_tuple(fields: list[str], obj: str) -> str:
    """The field tuple ``(self.x, self.y)`` / ``(other.x, other.y)`` for ``obj`` — a
    single trailing comma when there is exactly one field so it stays a tuple."""
    inner = ", ".join(f"{obj}.{name}" for name in fields)
    if len(fields) == 1:
        return f"({inner},)"
    return f"({inner})"


def _eq_method_lines(fields: list[str], indent: str) -> list[str]:
    """The canonical ``__eq__`` method lines at the class-body ``indent``: an
    ``isinstance(other, type(self))`` guard returning ``NotImplemented`` on a type
    mismatch (so the reflected ``other.__eq__`` still runs), else a field-tuple ``==``."""
    body = "    "
    self_tuple = _field_tuple(fields, "self")
    other_tuple = _field_tuple(fields, "other")
    return [
        f"{indent}def __eq__(self, other: object) -> bool:",
        f"{indent}{body}if not isinstance(other, type(self)):",
        f"{indent}{body}{body}return NotImplemented",
        f"{indent}{body}return {self_tuple} == {other_tuple}",
    ]


def _hash_method_lines(fields: list[str], indent: str) -> list[str]:
    """The canonical ``__hash__`` method lines at the class-body ``indent``:
    ``hash((self.x, self.y))`` over the SAME field tuple — emitted ONLY when ``__eq__``
    is newly added, to keep the class hashable (defining ``__eq__`` alone sets
    ``__hash__`` to ``None``)."""
    body = "    "
    self_tuple = _field_tuple(fields, "self")
    return [
        f"{indent}def __hash__(self) -> int:",
        f"{indent}{body}return hash({self_tuple})",
    ]


def _dunder_lines(
    fields: list[str], indent: str, *, add_repr: bool, add_eq: bool
) -> list[str]:
    """The spliced dunder block (``__repr__`` then ``__eq__`` + ``__hash__`` when each
    is being added), each method preceded by ONE blank line so it does not weld onto the
    statement above it. ``__hash__`` rides with a NEWLY-added ``__eq__`` so a value-equal
    class stays hashable."""
    lines: list[str] = []
    if add_repr:
        lines.append("")
        lines.extend(_repr_method_lines(fields, indent))
    if add_eq:
        lines.append("")
        lines.extend(_eq_method_lines(fields, indent))
        lines.append("")
        lines.extend(_hash_method_lines(fields, indent))
    return lines


def _class_body_end(cls: ast.ClassDef) -> int:
    """The 0-based line index just PAST the last body statement of ``cls`` — where the
    new dunder block is spliced (the end of the class body). Uses the maximum
    ``end_lineno`` over the body statements so a multi-line trailing method is fully
    cleared."""
    end = cls.body[0].lineno
    for stmt in cls.body:
        end = max(end, getattr(stmt, "end_lineno", stmt.lineno))
    return end


def _plan_one_class(
    cls: ast.ClassDef, lines: list[str], index: dict[str, ast.ClassDef]
) -> tuple[int, list[str]] | None:
    """The ``(insert_index, dunder_lines)`` splice for ONE class, or ``None`` when it
    fails any gate (an honest no-op).

    Gates: not ``@dataclass``-decorated; a NON-EMPTY proven pure-copy field set; at
    least one of ``__repr__`` / ``__eq__`` actually MISSING; and — when ``__eq__`` is the
    one being added — the inherited-``__eq__`` safety gate passes (no resolvable base
    transitively defines ``__eq__``, and every base resolves within the project)."""
    if _is_dataclass_decorated(cls):
        return None  # dataclassify / freeze own a @dataclass's value semantics
    fields = _proven_fields(cls)
    if not fields:
        return None  # no enumerable / non-empty pure-copy field set — nothing to range over

    add_repr = not _class_defines_dunder(cls, "__repr__")
    add_eq = not _class_defines_dunder(cls, "__eq__")
    if not add_repr and not add_eq:
        return None  # both already present — idempotent no-op

    if add_eq and not _inherited_eq_is_safe(cls, index):
        # An inherited / un-resolvable __eq__ would be silently overridden. Do not add
        # __eq__ (nor the __hash__ that rides with it). __repr__ has no inherited
        # contract, so still add it when missing; otherwise this class is a no-op.
        add_eq = False
        if not add_repr:
            return None

    indent = _class_indent(cls, lines)
    body = _dunder_lines(fields, indent, add_repr=add_repr, add_eq=add_eq)
    if not body:
        return None
    return _class_body_end(cls), body


def _collect_edits(
    tree: ast.Module, lines: list[str], index: dict[str, ast.ClassDef]
) -> list[tuple[int, list[str]]]:
    """The ``(insert_index, dunder_lines)`` splice for every synthesizable top-level
    class in ``tree``, in source order."""
    edits: list[tuple[int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        plan = _plan_one_class(node, lines, index)
        if plan is None:
            continue
        edits.append(plan)
    return edits


def synthesize_dunders(source: str, project_sources: list[str]) -> str | None:
    """Splice canonical ``__repr__`` / ``__eq__`` / ``__hash__`` over the proven field
    set into every eligible top-level class in ``source``, or ``None`` when nothing
    changes.

    ``project_sources`` is the project's own-module source set (tests-EXCLUDING) the
    inherited-``__eq__`` base scan resolves bases against; it MUST include ``source``
    itself (the objective threads it via ``freeze_dataclass.project_sources``). A wrong
    ``__eq__`` is a RUNTIME difference the suite catches (and ``apply_rename`` rolls
    back), so the own-module scan is the right scope (the freeze-dataclass rationale),
    while the inherited-contract refusal is the static rail. Classes are spliced in
    REVERSE source order so earlier line spans stay valid; the result is re-``ast.parse``d
    via ``dataclass_rewrite.rejoin_guarded`` so a malformed splice yields ``None`` rather
    than landing broken Python. Deterministic and idempotent."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    index = _classes_by_name(project_sources)
    lines = source.splitlines()
    edits = _collect_edits(tree, lines, index)
    if not edits:
        return None

    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so indices stay valid
    out_lines = list(lines)
    for index_at, body in edits:
        out_lines[index_at:index_at] = body
    return rejoin_guarded(source, out_lines)


def synthesizable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that would gain a synthesized dunder
    when ``source`` is considered IN ISOLATION (the project scan is just this module).

    Convenience for tests / single-file reasoning: uses ``source`` itself as the project
    source set, so the inherited-``__eq__`` scan resolves only this module's bases (a base
    defined elsewhere is then un-resolvable -> refused, the conservative floor). Sorted by
    source order. Returns ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    index = _classes_by_name([source])
    lines = source.splitlines()
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _plan_one_class(node, lines, index) is not None:
            out.append(node.name)
    return out
