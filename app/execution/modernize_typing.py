"""Modernize a module's TYPE ANNOTATIONS to the PEP 585 / PEP 604 spellings —
``typing.List[x]`` -> ``list[x]``, ``Optional[X]`` -> ``X | None``,
``Union[A, B]`` -> ``A | B``, ``typing.Text`` -> ``str`` — in ANNOTATION POSITIONS
ONLY.

The honest chore this closes: a typed module written before the modern builtins
were subscriptable spells its containers ``typing.List[int]`` / ``Dict[str, int]``
and its unions ``Optional[Foo]`` / ``Union[A, B]``. PEP 585 (Python 3.9) made the
builtin generics (``list[int]``, ``dict[str, int]``, …) subscriptable and PEP 604
(Python 3.10) added the ``X | None`` union syntax — the spellings every modern
typed file uses by hand. :func:`modernize_typing` LANDS exactly that migration,
deterministically and for free, no LLM — the canonical expensive-paid-LLM
busywork.

THE LOAD-BEARING SAFETY GATE — the whole recipe turns on it. A rewrite to an
annotation is applied ONLY when the module is PROVABLY not runtime-evaluating its
annotations, detected STRUCTURALLY as ``from __future__ import annotations`` being
present (reuse :func:`app.execution.future_annotations.has_future_annotations`).
Under PEP 563 every annotation is a LAZY string that is only resolved on demand,
so both PEP 585 (``list[x]``, which at runtime needs 3.9) and PEP 604 (``X | None``,
which at runtime needs 3.10) are SAFE on ANY Python that merely PARSES them. When
the module has NO future-import, :func:`modernize_typing` REFUSES (returns
``None`` — an honest no-op): it does NOT probe the target's Python version, does
NOT assume 3.10. The refusal is RECOVERABLE — the existing
``add-from-future-annotations`` objective (suite-gated) runs first, and this
objective then fires on the now-deferred module. That composition is the elegant
core.

THE SOUNDNESS BOUNDARY — annotation-position ONLY. Only AST nodes in an annotation
slot are visited / rewritten: an :class:`ast.AnnAssign` annotation, an
:class:`ast.arg` annotation, a ``FunctionDef``/``AsyncFunctionDef`` return
(``-> T``), and the subscript subtrees WITHIN them. A ``typing.List`` in
EXPRESSION position — ``x = List``, ``isinstance(x, List)``, ``List[int]()``,
``cast(List[int], y)`` — is NEVER visited, so it is NEVER rewritten. This
structural boundary is the core behaviour-preservation guarantee: a
runtime-VALUE use of a typing name keeps its meaning untouched.

It REFUSES (an honest ``None`` no-op — never a guess) when the module:

  - has NO ``from __future__ import annotations`` (the load-bearing gate above);
  - does ``from typing import *`` (a star-import can't prove a bare ``List`` is
    typing's, so every bare-name rewrite in the module is refused);
  - binds a typing name AMBIGUOUSLY (the same local name bound both to typing and
    to something else — the binding is no longer provably typing's);
  - SHADOWS a typing name with a non-import binding (a local ``List = ...``, a
    ``def List`` / ``class List``, a parameter/assignment named ``List`` in scope)
    — that name in that module is no longer provably ``typing.List``, so it is left
    alone (the round-16 shadow lesson);
  - hits a SHARP EDGE in an annotation: ``Tuple[()]`` (the empty-tuple type, whose
    builtin spelling is subtle) or a STRING-LITERAL annotation (``x: "List[int]"``)
    — both deferred to a later wave;
  - does not parse, or the rewrite would not re-parse (never land broken Python).

Union normalization is sound and total: ``Union[A, B, None]`` -> ``A | B | None``,
``Optional[Union[A, B]]`` -> ``A | B | None`` (a single ``| None`` tail, never a
double), single-element ``Union[X]`` -> ``X``, nested ``Union`` is FLATTENED, and a
duplicate member is preserved as written (``ast.unparse`` of the rebuilt
``BinOp``). ``Optional[X]`` -> ``X | None``.

DEAD-IMPORT CLEANUP (wave-2): a ``typing`` name this transform MODERNIZED can be
left with no remaining reference — ``Optional[X]`` -> ``X | None`` consumes the
only ``Optional`` use, so ``from typing import Optional`` becomes an F401. Wave-1
left that line ALONE (it composed with ``remove-unused-imports`` on a later pass),
but a user running modernize-typing ALONE on a ruff-strict project was then left
import-dirty. So, AFTER the annotation rewrites, for each ``typing`` name this
transform actually rewrote (the rename targets plus ``Optional``/``Union``), if
that name is now PROVABLY fully unreferenced in the rewritten module — no remaining
``ast.Name``/attribute use ANYWHERE, and not listed in ``__all__`` — its alias is
dropped from its ``from typing import ...`` line (the whole line goes when EVERY
name on it died; an ``import typing`` / ``import typing as t`` line goes only when
``typing``/``t`` is itself fully unreferenced). A PARTIAL import is kept intact
(``from typing import Optional, Any`` with ``Any`` still used -> only ``Optional``
dropped). This REUSES the ``remove-unused-imports`` detector
(:func:`app.execution.unused_imports._used_names` / ``_all_names`` /
``_has_star_import`` / ``_collect_rewrites``) scoped to ONLY the names this
transform modernized — a non-typing unused import, a name still used in EXPRESSION
position (``cast(Optional[int], y)``, which the annotation-slot boundary never
rewrote, so ``Optional`` stays referenced), an ``__all__`` export, a star-import
module, or a ``# noqa`` line is NEVER touched. Soundness over recall: any ambiguity
leaves the import as written. An annotation with no rewritable node, and a module
where no typing name became fully dead, are both left byte-for-byte unchanged.

Deterministic (pure AST walk + per-slot span splice in REVERSE source order, no
clock/random/LLM), stdlib-only, zero-token, idempotent (a second run finds no
legacy spelling left in any annotation and is a byte-identical no-op). Reuses
:func:`app.execution.future_annotations.has_future_annotations` for the gate and
:func:`app.execution.dataclass_rewrite.rejoin_guarded` for the "splice, preserve
the trailing newline, re-``ast.parse`` guard" epilogue every line-splicing rewrite
shares.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import rejoin_guarded
from app.execution.future_annotations import has_future_annotations
from app.execution.unused_imports import (
    _all_names,
    _apply,
    _bound_name,
    _collect_rewrites,
    _has_star_import,
    _is_prunable_import,
    _used_names,
)

__all__ = [
    "modernize_typing",
    "modernizable_annotations",
]

# The ``typing`` names this transform migrates, and their PEP 585 builtin image.
# ``Optional`` / ``Union`` carry no builtin name (they become ``|`` expressions),
# so they are handled structurally rather than via this rename map.
_PEP585: dict[str, str] = {
    "List": "list",
    "Dict": "dict",
    "Tuple": "tuple",
    "Set": "set",
    "FrozenSet": "frozenset",
    "Type": "type",
}
# ``typing.Text`` is a deprecated alias of ``str`` (no subscript) — a bare-name
# substitution, in the same family.
_PLAIN: dict[str, str] = {"Text": "str"}

# Every ``typing`` name this transform reasons about (the rename targets plus the
# union constructors). A local name is "a typing name" only when it resolves to
# one of these.
_TYPING_NAMES: frozenset[str] = (
    frozenset(_PEP585) | frozenset(_PLAIN) | frozenset({"Optional", "Union"})
)


class _Bindings:
    """How the module spells each migratable ``typing`` name, proven from its
    imports — the typing-binding scan.

    ``bare`` maps a LOCAL bare name (as written in an annotation) to the canonical
    ``typing`` name it resolves to: ``from typing import List`` -> ``{"List":
    "List"}``; ``from typing import List as L`` -> ``{"L": "List"}``. ``modules``
    is the set of local names bound to the ``typing`` MODULE itself (``import
    typing`` -> ``{"typing"}``; ``import typing as t`` -> ``{"t"}``), so a dotted
    ``t.List`` attribute resolves. ``refuse`` is True when the scan hit an
    unrecoverable ambiguity — a ``from typing import *`` (a bare ``List`` can't be
    proven typing's) or a name bound to BOTH typing and something else — in which
    case the whole module is a no-op."""

    def __init__(self) -> None:
        self.bare: dict[str, str] = {}
        self.modules: set[str] = set()
        self.refuse: bool = False
        # Local names that have been bound to a NON-typing source too (so a typing
        # binding of the same local name is ambiguous -> refuse that name).
        self._non_typing: set[str] = set()

    def bind_bare(self, local: str, canonical: str) -> None:
        """Record ``local`` (the name as written) -> ``canonical`` (the typing
        name). A collision with a different canonical, or with a name already
        bound non-typing, is an ambiguity -> refuse the whole module."""
        if local in self._non_typing:
            self.refuse = True
            return
        existing = self.bare.get(local)
        if existing is not None and existing != canonical:
            self.refuse = True
            return
        self.bare[local] = canonical

    def note_non_typing(self, local: str) -> None:
        """Record that ``local`` is also bound to a non-typing source; if it was
        (or later is) a typing binding too, that name is ambiguous."""
        self._non_typing.add(local)
        if local in self.bare:
            self.refuse = True


def _scan_importfrom(node: ast.ImportFrom, bindings: _Bindings) -> None:
    """Fold one ``from ... import ...`` into the binding scan.

    A ``from typing import *`` is an unrecoverable ambiguity (refuse). A ``from
    typing import <Name>[ as <local>]`` for a migratable name records the local ->
    canonical binding. Any OTHER import that binds a local name equal to a
    migratable name (a differently-sourced ``List``) marks that name non-typing, so
    a later/earlier typing binding of it is ambiguous."""
    if node.module == "typing":
        for alias in node.names:
            if alias.name == "*":
                bindings.refuse = True  # star-import: a bare List is unprovable
                continue
            local = alias.asname or alias.name
            if alias.name in _TYPING_NAMES:
                bindings.bind_bare(local, alias.name)
        return
    # An import from some OTHER module that shadows a migratable local name.
    for alias in node.names:
        local = alias.asname or alias.name
        if local in _TYPING_NAMES:
            bindings.note_non_typing(local)


def _scan_import(node: ast.Import, bindings: _Bindings) -> None:
    """Fold one ``import ...`` into the binding scan.

    ``import typing`` / ``import typing as t`` records the module alias (so
    ``t.List`` resolves). Any other ``import x`` whose bound local name equals a
    migratable name marks it non-typing."""
    for alias in node.names:
        if alias.name == "typing":
            bindings.modules.add(alias.asname or "typing")
            continue
        local = (alias.asname or alias.name).split(".")[0]
        if local in _TYPING_NAMES:
            bindings.note_non_typing(local)


def _scan_bindings(tree: ast.Module) -> _Bindings:
    """The typing-binding scan over a module's whole import surface — every
    ``import`` / ``from import`` (at any depth, via :func:`ast.walk`)."""
    bindings = _Bindings()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            _scan_importfrom(node, bindings)
        elif isinstance(node, ast.Import):
            _scan_import(node, bindings)
    return bindings


def _shadowed_names(tree: ast.Module) -> set[str]:
    """The migratable ``typing`` names SHADOWED by a NON-import binding anywhere in
    ``tree`` — a ``def``/``class`` of that name, or any ``Store``-context target
    (``Name = ...``, ``for Name in``, ``with x as Name``, a walrus, a parameter).

    Such a binding means the name no longer provably refers to ``typing``'s, so a
    rewrite of that bare name is refused module-wide (the conservative round-16
    shadow lesson — soundness over recall). Import rebindings are handled by the
    binding scan; this catches only the non-import shadows."""
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in _TYPING_NAMES:
                shadowed.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id in _TYPING_NAMES:
                shadowed.add(node.id)
        elif isinstance(node, ast.arg):
            if node.arg in _TYPING_NAMES:
                shadowed.add(node.arg)
    return shadowed


class _Resolver:
    """Resolve an annotation-position expression node to the canonical ``typing``
    name it spells, honouring the proven bindings and the shadow set.

    ``resolve`` returns the canonical name (``"List"``, ``"Optional"``, …) for a
    bare ``Name`` that the binding scan proved typing's and that is NOT shadowed,
    or for a dotted ``Attribute`` ``<mod>.<Name>`` whose head is a bound typing
    module — else ``None`` (not a typing name we migrate)."""

    def __init__(self, bindings: _Bindings, shadowed: set[str]) -> None:
        self._bindings = bindings
        self._shadowed = shadowed

    def resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self._shadowed:
                return None  # a non-import binding shadows it -> not typing's
            return self._bindings.bare.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr in _TYPING_NAMES:
            if isinstance(node.value, ast.Name) and node.value.id in self._bindings.modules:
                return node.attr
        return None


# A sentinel returned by the rewriter to mean "this annotation hits a sharp edge
# (``Tuple[()]`` or a string-literal annotation) — refuse the whole module".
_REFUSE = object()


class _Rewriter:
    """Rebuild a SINGLE annotation expression with the migrated spellings, or
    report a sharp-edge refusal.

    ``rewrite(node)`` returns ``(new_node, changed)`` where ``new_node`` is the
    transformed copy and ``changed`` says whether anything was actually migrated,
    or :data:`_REFUSE` when the annotation hits a wave-1 sharp edge. Pure: it
    builds fresh AST nodes (the input tree is never mutated)."""

    def __init__(self, resolver: _Resolver) -> None:
        self._resolver = resolver

    def rewrite(self, node: ast.expr) -> tuple[ast.expr, bool] | object:
        # A STRING-LITERAL annotation (``x: "List[int]"``) — refuse in wave 1
        # (forward-ref strings need their own careful handling).
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return _REFUSE
        if isinstance(node, ast.Subscript):
            return self._rewrite_subscript(node)
        head = self._resolver.resolve(node)
        if head in _PLAIN:  # bare Text -> str
            return ast.Name(id=_PLAIN[head], ctx=ast.Load()), True
        return node, False

    def _rewrite_subscript(self, node: ast.Subscript) -> tuple[ast.expr, bool] | object:
        head = self._resolver.resolve(node.value)
        if head == "Optional":
            return self._rewrite_optional(node)
        if head == "Union":
            return self._rewrite_union(node)
        # ``Tuple[()]`` — the empty-tuple type. Its builtin spelling (``tuple[()]``
        # vs ``tuple[]`` / ``tuple`` debates) is a wave-1 sharp edge -> refuse.
        if head == "Tuple" and self._is_empty_tuple_slice(node.slice):
            return _REFUSE
        # A non-union subscript (``List[int]``, ``Dict[str, int]``, a plain
        # ``Callable[[int], str]`` …): migrate the head if it is a PEP-585 name,
        # and recurse THROUGH the slice (including each element of a multi-arg
        # ``Dict[str, List[int]]`` tuple slice) so nested ``List``/``Optional``/…
        # migrate too.
        new_slice = self._rewrite_slice_through(node.slice)
        if new_slice is _REFUSE:
            return _REFUSE
        slice_node, slice_changed = new_slice  # type: ignore[misc]
        value_node, value_changed = self._rewrite_value_head(node.value, head)
        changed = slice_changed or value_changed
        return ast.Subscript(value=value_node, slice=slice_node, ctx=ast.Load()), changed

    @staticmethod
    def _is_empty_tuple_slice(slice_node: ast.expr) -> bool:
        """True when a ``Tuple[...]`` slice is the EMPTY-tuple marker ``()`` — an
        ``ast.Tuple`` with no elements (the source ``Tuple[()]``)."""
        return isinstance(slice_node, ast.Tuple) and not slice_node.elts

    def _rewrite_slice_through(self, slice_node: ast.expr) -> tuple[ast.expr, bool] | object:
        """Rewrite a (non-union) subscript SLICE, recursing into every element.

        A multi-argument slice is an :class:`ast.Tuple` (``Dict[str, int]`` ->
        ``Tuple[str, int]``); each element is rewritten so a nested legacy spelling
        (``Dict[str, List[int]]``) migrates. A single-element slice is rewritten
        directly. :data:`_REFUSE` propagates from any element's sharp edge."""
        if isinstance(slice_node, ast.Tuple):
            new_elts: list[ast.expr] = []
            changed = False
            for elt in slice_node.elts:
                rewritten = self.rewrite(elt)
                if rewritten is _REFUSE:
                    return _REFUSE
                elt_node, elt_changed = rewritten  # type: ignore[misc]
                new_elts.append(elt_node)
                changed = changed or elt_changed
            return ast.Tuple(elts=new_elts, ctx=ast.Load()), changed
        return self.rewrite(slice_node)

    def _rewrite_value_head(self, value: ast.expr, head: str | None) -> tuple[ast.expr, bool]:
        """Migrate a subscript HEAD ``List`` -> ``list`` (PEP 585) when proven
        typing's; any other head is recursed into (so a head that is itself a
        migratable expression still transforms) but, when not a migratable name, is
        returned as written."""
        if head in _PEP585:
            return ast.Name(id=_PEP585[head], ctx=ast.Load()), True
        nested = self.rewrite(value)
        if nested is _REFUSE:
            # A string-literal head is not reachable in valid annotations; fall back
            # to the value as written rather than refusing the whole module on it.
            return value, False
        return nested  # type: ignore[return-value]

    def _rewrite_slice_members(self, node: ast.Subscript) -> tuple[list[ast.expr], bool] | object:
        """The migrated member list of a ``Union``/``Optional`` subscript slice,
        FLATTENING nested ``Union``, or :data:`_REFUSE` on a sharp edge.

        Returns ``(members, none_seen)``: ``members`` are the rebuilt non-``None``
        member nodes in source order (duplicates preserved as written),
        ``none_seen`` is True when an explicit ``None`` member was present (so a
        single ``| None`` tail is appended once)."""
        raw = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        members: list[ast.expr] = []
        none_seen = False
        for elt in raw:
            if isinstance(elt, ast.Constant) and elt.value is None:
                none_seen = True
                continue
            # A nested Union inside the slice is flattened into this level.
            if isinstance(elt, ast.Subscript) and self._resolver.resolve(elt.value) == "Union":
                inner = self._rewrite_slice_members(elt)
                if inner is _REFUSE:
                    return _REFUSE
                inner_members, inner_none = inner  # type: ignore[misc]
                members.extend(inner_members)
                none_seen = none_seen or inner_none
                continue
            rewritten = self.rewrite(elt)
            if rewritten is _REFUSE:
                return _REFUSE
            members.append(rewritten[0])  # type: ignore[index]
        return members, none_seen

    def _rewrite_union(self, node: ast.Subscript) -> tuple[ast.expr, bool] | object:
        """``Union[A, B, …]`` -> ``A | B | …`` (PEP 604), flattening nested
        ``Union`` and folding any ``None`` member into a single ``| None`` tail. A
        single-member ``Union[X]`` collapses to ``X``."""
        collected = self._rewrite_slice_members(node)
        if collected is _REFUSE:
            return _REFUSE
        members, none_seen = collected  # type: ignore[misc]
        if none_seen:
            members.append(ast.Constant(value=None))
        if not members:
            # ``Union[None]`` / ``Union[()]`` — degenerate; leave as written.
            return node, False
        return self._or_chain(members), True

    def _rewrite_optional(self, node: ast.Subscript) -> tuple[ast.expr, bool] | object:
        """``Optional[X]`` -> ``X | None``; ``Optional[Union[A, B]]`` ->
        ``A | B | None`` (the inner union flattens, a single ``| None`` tail)."""
        inner = node.slice
        # ``Optional`` takes exactly one argument; a tuple slice is malformed —
        # leave it as written rather than guess.
        if isinstance(inner, ast.Tuple):
            return node, False
        if isinstance(inner, ast.Subscript) and self._resolver.resolve(inner.value) == "Union":
            collected = self._rewrite_slice_members(inner)
            if collected is _REFUSE:
                return _REFUSE
            members, _none = collected  # type: ignore[misc]
        else:
            rewritten = self.rewrite(inner)
            if rewritten is _REFUSE:
                return _REFUSE
            members = [rewritten[0]]  # type: ignore[list-item]
        members.append(ast.Constant(value=None))
        return self._or_chain(members), True

    @staticmethod
    def _or_chain(members: list[ast.expr]) -> ast.expr:
        """Left-fold ``[A, B, C]`` into the ``BinOp`` ``A | B | C`` (PEP 604)."""
        result = members[0]
        for member in members[1:]:
            result = ast.BinOp(left=result, op=ast.BitOr(), right=member)
        return result


def _annotation_slots(tree: ast.Module) -> list[ast.expr]:
    """Every ANNOTATION-POSITION expression in ``tree``, in source order — the
    ONLY slots this transform may touch.

    Collects an :class:`ast.AnnAssign` annotation, every annotated :class:`ast.arg`
    (regular / positional-only / keyword-only / ``*args`` / ``**kwargs``), and a
    ``FunctionDef``/``AsyncFunctionDef`` return annotation. A ``typing`` name in
    EXPRESSION position is never in this list, so it is never visited."""
    slots: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            slots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                slots.append(node.returns)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            slots.append(node.annotation)
    return slots


def _node_span(node: ast.expr) -> tuple[int, int, int, int] | None:
    """The ``(lineno, col, end_lineno, end_col)`` span of ``node`` (1-based line,
    0-based col), or ``None`` when position info is missing."""
    if (node.lineno is None or node.col_offset is None
            or node.end_lineno is None or node.end_col_offset is None):
        return None
    return node.lineno, node.col_offset, node.end_lineno, node.end_col_offset


def _splice(lines: list[str], span: tuple[int, int, int, int], text: str) -> list[str] | None:
    """Replace the ``span`` region of ``lines`` (physical lines WITHOUT line
    endings) with ``text`` (a single-line annotation unparse).

    A multi-line span collapses to the single replacement line. Returns the new
    line list, or ``None`` when the span indexes are out of range (defensive — the
    caller treats it as a refusal). The caller applies splices in REVERSE source
    order so earlier spans stay valid."""
    lineno, col, end_lineno, end_col = span
    if lineno - 1 < 0 or end_lineno - 1 >= len(lines):
        return None
    start_line = lines[lineno - 1]
    end_line = lines[end_lineno - 1]
    if col > len(start_line) or end_col > len(end_line):
        return None
    new_line = start_line[:col] + text + end_line[end_col:]
    out = list(lines)
    out[lineno - 1:end_lineno] = [new_line]
    return out


def _record_touched(
    slot: ast.expr, resolver: _Resolver, touched: set[str]
) -> None:
    """Record into ``touched`` the LOCAL name of every ``typing`` reference the
    resolver proves inside ``slot`` — the bare ``Name`` id (``Optional``, ``L``)
    for a ``from typing import`` binding, or the module-alias head id (``t`` of
    ``t.List``, ``typing`` of ``typing.Optional``) for a dotted attribute.

    Called only for a slot that ACTUALLY produced an edit, so ``touched`` is
    exactly the set of import-bound local names this transform modernized — the
    scope of the dead-import cleanup. A bare ``List`` (resolves but is unchanged
    when unsubscripted) may be over-recorded harmlessly: it still appears in the
    rewritten source, so the deadness recheck keeps its import anyway."""
    for node in ast.walk(slot):
        if resolver.resolve(node) is None:
            continue
        if isinstance(node, ast.Name):
            touched.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            touched.add(node.value.id)


def _collect_edits(
    tree: ast.Module, rewriter: _Rewriter, resolver: _Resolver
) -> tuple[list[tuple[tuple[int, int, int, int], str]], set[str]] | object:
    """Every ``(span, new_text)`` annotation-slot edit (in source order) plus the
    set of import-bound local names the transform modernized, or :data:`_REFUSE`
    when any slot hits a sharp edge.

    For each annotation slot the rewriter rebuilds the expression; only a slot that
    ACTUALLY migrated something contributes an edit (an annotation with no legacy
    spelling is left byte-for-byte unchanged) and feeds :func:`_record_touched`. A
    slot with no position info is skipped (it cannot be spliced safely)."""
    edits: list[tuple[tuple[int, int, int, int], str]] = []
    touched: set[str] = set()
    for slot in _annotation_slots(tree):
        result = rewriter.rewrite(slot)
        if result is _REFUSE:
            return _REFUSE
        new_node, changed = result  # type: ignore[misc]
        if not changed:
            continue
        span = _node_span(slot)
        if span is None:
            continue
        try:
            text = ast.unparse(new_node)
        except (ValueError, AttributeError):
            return _REFUSE
        edits.append((span, text))
        _record_touched(slot, resolver, touched)
    return edits, touched


def _dead_modernized_names(
    tree: ast.Module, used: set[str], touched: set[str]
) -> set[str]:
    """The subset of ``touched`` (the names this transform modernized) that is now
    PROVABLY fully dead: absent from the rewritten module's ``used`` names (no
    remaining ``Name``/attribute reference — so an expression-position
    ``cast(Optional[int], y)`` keeps ``Optional``) and not an ``__all__`` export
    (reusing the ``remove-unused-imports`` export guard)."""
    exported = _all_names(tree)
    return {name for name in touched if name not in used and name not in exported}


def _prune_dead_aliases(
    tree: ast.Module, source: str, used: set[str], dead: set[str]
) -> str | None:
    """Drop exactly the ``dead`` aliases from ``source``'s imports via the reused
    ``remove-unused-imports`` rewriter, re-parse-guarded.

    ``keep`` is every bound name EXCEPT ``dead``, so the reused
    :func:`app.execution.unused_imports._collect_rewrites` can only ever drop names
    in ``dead`` — a non-typing import, a still-used name, or a name nobody
    modernized is forced into ``keep`` and never touched (the focus guarantee).
    Returns the cleaned source, ``source`` unchanged when nothing is pruned, or
    ``None`` only if the result would not parse (never land broken Python)."""
    all_bound = {
        _bound_name(alias)
        for node in tree.body if _is_prunable_import(node)
        for alias in node.names
    }
    keep = all_bound - dead
    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, lines, used, keep)
    if not rewrites:
        return source
    cleaned = _apply(lines, rewrites)
    try:
        ast.parse(cleaned)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source  # never land broken Python -> fall back to the safe rewrite
    return cleaned


def _strip_dead_typing_imports(source: str, touched: set[str]) -> str | None:
    """Drop, from ``source``'s ``typing`` imports, ONLY the modernized names in
    ``touched`` that are now provably fully unreferenced — the wave-2 dead-import
    cleanup. Returns the cleaned source, or ``source`` unchanged when nothing is
    safe to drop, or ``None`` only if the cleaned text would not parse.

    Reuses the ``remove-unused-imports`` detector
    (:func:`app.execution.unused_imports._used_names` / ``_all_names`` /
    ``_collect_rewrites`` / ``_apply``) but SCOPED to ``touched`` via
    :func:`_dead_modernized_names` + :func:`_prune_dead_aliases`: a name is
    droppable only when this transform modernized it AND no reference survives AND
    it is not an ``__all__`` export. A star-import module is left whole; ``# noqa``
    lines are honoured by the reused ``_collect_rewrites``. Idempotent and
    deterministic — byte-identical to the wave-1 splice when nothing died."""
    if not touched:
        return source  # transform rewrote nothing import-bound -> nothing to clean
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source  # rejoin_guarded already proved it parses; defensive no-op
    if _has_star_import(tree):
        return source  # a star-import could rebind a name -> never edit imports
    import_nodes = {
        id(node) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    used = _used_names(tree, import_nodes)
    dead = _dead_modernized_names(tree, used, touched)
    if not dead:
        return source  # no modernized typing name became fully dead -> byte-identical
    return _prune_dead_aliases(tree, source, used, dead)


def modernizable_annotations(source: str) -> bool:
    """True when :func:`modernize_typing` would change ``source`` — a convenience
    for tests / fitness reasoning. ``False`` on any refusal or no-op (a syntax
    error, no future-import, an ambiguous/star/shadowed binding, a sharp edge, or
    simply no legacy spelling in any annotation)."""
    return modernize_typing(source) is not None


def modernize_typing(source: str) -> str | None:
    """Rewrite ``source``'s annotation-position ``typing`` spellings to PEP 585 /
    PEP 604, or ``None`` when nothing changes / any refusal fires.

    The load-bearing gate first: ``None`` unless ``from __future__ import
    annotations`` is present (so every annotation is a deferred PEP 563 string and
    both ``list[x]`` and ``X | None`` are runtime-safe on any parsing Python). Then
    the typing-binding scan (refuse on ``from typing import *`` or an ambiguous
    binding), the shadow scan (a non-import shadow of a typing name refuses that
    name), and an ANNOTATION-SLOT-ONLY rewrite (an ``AnnAssign``/``arg``/return
    annotation and the subscript subtrees within them — never an expression-position
    typing use). A ``Tuple[()]`` or string-literal annotation refuses the whole
    module (wave-1 sharp edges). Edits splice in REVERSE source order, then the
    result is re-``ast.parse``d (a malformed rewrite is dropped). Finally
    :func:`_strip_dead_typing_imports` drops any ``typing`` name THIS rewrite
    modernized that is now fully unreferenced (the wave-2 dead-import cleanup, so
    the change lands ruff-F401-clean standalone) — scoped to those names only, and
    byte-identical to the splice when none died. Deterministic, stdlib-only,
    idempotent — a second run finds no legacy spelling and is a byte-identical
    no-op."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None  # never rewrite broken source
    if not has_future_annotations(source):
        return None  # the gate: annotations are not provably deferred -> refuse

    bindings = _scan_bindings(tree)
    if bindings.refuse:
        return None  # star-import / ambiguous binding -> a bare List is unprovable
    if not bindings.bare and not bindings.modules:
        return None  # no migratable typing name is even imported -> nothing to do

    resolver = _Resolver(bindings, _shadowed_names(tree))
    rewriter = _Rewriter(resolver)
    collected = _collect_edits(tree, rewriter, resolver)
    if collected is _REFUSE:
        return None  # a sharp-edge annotation (Tuple[()] / string literal) -> refuse
    edits, touched = collected  # type: ignore[misc]
    if not edits:
        return None  # no annotation carried a legacy spelling -> idempotent no-op

    lines = source.splitlines()
    # Apply in REVERSE source order so an earlier span stays valid as a later one
    # collapses multi-line spans. Sort by (line, col) descending; a tuple key gives
    # a total, deterministic order.
    for span, text in sorted(edits, key=lambda e: (e[0][0], e[0][1]), reverse=True):
        spliced = _splice(lines, span, text)
        if spliced is None:
            return None  # an out-of-range span -> refuse rather than corrupt
        lines = spliced
    rewritten = rejoin_guarded(source, lines)
    if rewritten is None:
        return None  # a malformed annotation splice is dropped, never landed
    # Wave-2: now that the modernized spellings have consumed their typing names,
    # drop any ``from typing import ...`` alias that became fully dead (scoped to
    # ONLY the names this transform modernized) so the rewrite lands ruff-clean
    # standalone. Byte-identical to the splice result when nothing died.
    return _strip_dead_typing_imports(rewritten, touched)
