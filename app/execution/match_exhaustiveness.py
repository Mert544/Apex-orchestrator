"""Fill the missing arm of a dispatch over a PROVABLY-CLOSED discriminant set with
a LOUD exhaustiveness sentinel — turning a silent fall-through (a latent bug) into a
total, loud dispatch.

A ``match``/``case`` block or an ``if``/``elif`` chain that branches on a discriminant
whose value set is PROVABLY closed — an ``Enum`` subclass defined in THIS module, a
``Literal[...]`` of simple constants, or ``bool`` — but does not handle every member
and carries NO catch-all (``case _:`` / a trailing ``else:``) has a SILENT
fall-through: an unhandled value falls off the end and the dispatch returns ``None``
(or does nothing). :func:`complete_match_exhaustiveness` APPENDS one final arm whose
body is ``raise AssertionError(f"unhandled <subject>: {<subject>!r}")`` — a ``case _:``
for a ``match``, a trailing ``else:`` for an ``if``/``elif`` — so the missing case is
LOUD instead of silent. This is the dispatch-level sibling of ``enforce-enum-unique``:
a STRUCTURAL soundness proof (no suite needed to prove correctness), intra-module.

SOUNDNESS — why it never regresses correct behaviour. The inserted arm executes ONLY
on a discriminant value the existing code does not handle today. Either (a) that value
cannot occur at runtime → the arm is dead code (behaviour-preserving), or (b) it can
occur → today it silently falls through (a bug) and the new arm makes it loud (an
improvement). In BOTH cases no currently-passing test can break: the new arm runs only
on input the old code mishandled. The full-suite gate + auto-rollback are the backstop,
not the proof — the exact posture of ``enforce-enum-unique`` (static refusal,
runtime-additive). Over-approximate toward REFUSAL (an honest no-op, empty plan) on
EVERY uncertainty: a discriminant type not provably one of the three closed forms (a
bare ``str``/``int``, a non-literal ``Literal``, an ``Enum`` reached via import/alias —
its full member set can't be proven statically), a wildcard/capture/trailing-``else``
already present (the set is already total), a chain that already handles every member,
or an unmodelled match subject (not a bare ``Name``). "When in doubt, refuse."

Deterministic (pure AST walk + reverse-order line splice, no clock/random/hashseed),
stdlib-only, zero-token, idempotent (a second run sees the sentinel arm and returns a
byte-identical no-op). Reuses :mod:`app.execution.enum_unique`'s member/literal
enumeration (``_member_target_name`` / ``_is_inert_body_stmt`` / ``_literal_value`` /
``_base_attr_name`` / ``_is_enum_class``), :func:`app.execution.final_marker._insert_decorator`'s
header-indent idiom (adapted to insert AFTER the node), and
:func:`app.execution.dataclass_rewrite.rejoin_guarded` for the "splice, preserve
newline, re-``ast.parse`` guard, byte-identical-None on no change" epilogue.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import rejoin_guarded
from app.execution.enum_unique import (
    _base_attr_name,
    _is_enum_class,
    _is_inert_body_stmt,
    _literal_value,
    _member_target_name,
)

__all__ = [
    "complete_match_exhaustiveness",
    "closed_dispatches",
    "enum_member_names",
]


def enum_member_names(cls: ast.ClassDef) -> frozenset[str] | None:
    """The member NAMES of a top-level ``Enum`` subclass ``cls``, or ``None`` when its
    body cannot be enumerated as bare-``Name`` member targets.

    Reuses ``enum_unique``'s class-body model: a member is a bare-``Name`` ``Assign`` /
    ``AnnAssign``-with-value target (``RED = ...`` / ``RED: int = ...``); a docstring /
    ``def`` / nested class / dunder / bare type-decl is inert and ignored. ANY other
    top-level statement (a ``for``/``if``/tuple-target/augmented-assign) means the
    members can't be enumerated exactly → ``None`` (refuse the whole enum). Unlike
    ``@enum.unique`` we need only the NAMES, not value-distinctness, so ``auto()`` is
    fine — its NAME is still a bare target."""
    names: list[str] = []
    for stmt in cls.body:
        name = _member_target_name(stmt)
        if name is not None:
            names.append(name)
        elif not _is_inert_body_stmt(stmt):
            return None  # an unmodelled binder — can't enumerate the closed set
    if not names:
        return None  # an empty enum carries no closed set to complete
    return frozenset(names)


def _enum_member_map(tree: ast.Module) -> dict[str, frozenset[str]]:
    """``{enum_class_name: member_names}`` for every TOP-LEVEL in-module ``Enum``
    subclass whose members enumerate. An enum that can't be enumerated is omitted, so
    a dispatch over it finds no closed set and is refused. Same conservative stance as
    ``enum_unique._is_enum_class`` — an enum imported/aliased from another module is
    simply absent here, so it is never treated as closed."""
    out: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_enum_class(node):
            members = enum_member_names(node)
            if members is not None:
                out[node.name] = members
    return out


class _ClosedSet(NamedTuple):
    """A proven-closed discriminant value set: ``keys`` is every member's canonical
    string key (an enum member NAME, or the ``repr`` of a literal/bool constant) and
    ``enum_name`` is the enum class an enum set dispatches through (``None`` for a
    ``Literal``/``bool`` set). The dispatch is total iff every key in ``keys`` is
    handled by some arm."""

    keys: frozenset[str]
    enum_name: str | None


def _literal_keys(slice_node: ast.expr) -> frozenset[str] | None:
    """The canonical keys of a ``Literal[...]`` subscript slice, or ``None`` when any
    element is not a simple accepted constant (a ``Name``, a call, a nested
    ``Literal`` → refuse). A 1-element ``Literal[x]`` has a bare (non-``Tuple``)
    slice; a multi-element one a ``Tuple``. Each key is ``repr(value)`` via
    ``enum_unique._literal_value`` (the same accepted-constant test)."""
    elts = slice_node.elts if isinstance(slice_node, ast.Tuple) else [slice_node]
    keys: set[str] = set()
    for elt in elts:
        materialised = _literal_value(elt)
        if materialised is None:
            return None  # a non-literal Literal element — not provably closed
        keys.add(repr(materialised[0]))
    return frozenset(keys) if keys else None


def _closed_set_from_annotation(
    ann: ast.expr, enums: dict[str, frozenset[str]]
) -> _ClosedSet | None:
    """The :class:`_ClosedSet` an annotation proves, or ``None`` when it is not one of
    the three closed forms. ``x: SomeEnum`` (a Name of an in-module enum) → the enum's
    members; ``x: Literal[...]`` of simple constants → those constants; ``x: bool`` →
    ``{True, False}``. A bare ``str``/``int``, a ``Literal`` built from a Name, or an
    enum not enumerated in ``enums`` yields ``None`` (refuse)."""
    if isinstance(ann, ast.Name):
        if ann.id == "bool":
            return _ClosedSet(frozenset({repr(True), repr(False)}), None)
        if ann.id in enums:
            return _ClosedSet(enums[ann.id], ann.id)
        return None
    if isinstance(ann, ast.Subscript) and _base_attr_name(ann.value) == "Literal":
        keys = _literal_keys(ann.slice)
        return _ClosedSet(keys, None) if keys is not None else None
    return None


def _subject_name(expr: ast.expr) -> str | None:
    """The bare discriminant NAME a dispatch subject is, or ``None`` for any other
    shape (an attribute, a call, a subscript) — an unmodelled subject we refuse."""
    return expr.id if isinstance(expr, ast.Name) else None


def _annotation_of(scope: ast.AST, name: str) -> ast.expr | None:
    """The FIRST annotation binding ``name`` in ``scope`` — a function parameter
    annotation or an ``x: T`` ``AnnAssign`` target — or ``None``.

    Scans the scope's own parameters then walks its body for an ``AnnAssign`` of
    ``name``. The first hit wins (deterministic, source order). A name with no
    annotation in scope yields ``None`` → the caller falls back to the arms (for an
    enum) or refuses."""
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = scope.args
        for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
            if arg.arg == name and arg.annotation is not None:
                return arg.annotation
    for node in ast.walk(scope):
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == name):
            return node.annotation
    return None


def _member_key_of_value(value: ast.expr, closed: _ClosedSet) -> str | None:
    """The closed-set key a handled-arm VALUE expression contributes, or ``None`` when
    it is not a member of ``closed``.

    Enum set: an ``Attribute`` ``<EnumName>.<MEMBER>`` whose base Name equals
    ``closed.enum_name`` and whose ``.attr`` is a known member → that member name.
    Literal/bool set: a simple constant whose ``repr`` is a known key → that key.
    Anything else (a bare Name, a wrong enum, an unknown member/constant) → ``None``,
    so it neither marks a member handled nor counts as a catch-all."""
    if closed.enum_name is not None:
        if (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                and value.value.id == closed.enum_name and value.attr in closed.keys):
            return value.attr
        return None
    materialised = _literal_value(value)
    if materialised is None:
        return None
    key = repr(materialised[0])
    return key if key in closed.keys else None


def _indent_at(lines: list[str], lineno: int) -> str:
    """The leading whitespace of the 1-based source ``lineno`` — the
    ``header[:len-lstrip]`` idiom ``final_marker._insert_decorator`` uses, read at an
    existing arm header so the appended arm lands at the SAME column."""
    line = lines[lineno - 1]
    return line[: len(line) - len(line.lstrip())]


def _sentinel_body(subject_text: str, body_indent: str) -> str:
    """The single sentinel statement line: ``<indent>raise AssertionError(f"unhandled
    <subj>: {<subj>!r}")`` — no business logic, the discriminant spelled exactly as it
    appears in source (``subject_text``)."""
    return (f'{body_indent}raise AssertionError(f"unhandled {subject_text}: '
            f'{{{subject_text}!r}}")')


class _Edit(NamedTuple):
    """One append edit: insert ``lines`` (the new arm header + sentinel body) AFTER
    0-based line index ``after`` (the dispatch's last source line). Applied in reverse
    ``after`` order so earlier line spans stay valid."""

    after: int
    lines: list[str]


# --- the match-statement path (``ast.Match``) --------------------------------

def _case_is_wildcard(case: ast.match_case) -> bool:
    """True when ``case``'s pattern is an irrefutable catch-all — a ``case _:``
    (``MatchAs`` with ``pattern is None and name is None``) OR a capture ``case
    other:`` (``MatchAs`` with ``pattern is None and name is not None``). Both make the
    dispatch already total, so the presence of either forces a REFUSE."""
    return isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


def _case_keys(case: ast.match_case, closed: _ClosedSet) -> set[str] | None:
    """The closed-set keys ``case`` handles, or ``None`` when it carries a guard or a
    pattern shape we cannot map to plain members (a guarded ``case``, a ``MatchOr`` of
    non-member patterns, a class/sequence pattern). A ``MatchValue`` mapping to a
    member contributes that one key; a ``MatchOr`` contributes each alternative's key.
    An unmappable arm yields ``None`` → refuse (we can't prove what it covers)."""
    if case.guard is not None:
        return None  # a guard means the arm may NOT cover the value — unprovable
    patterns = (case.pattern.patterns if isinstance(case.pattern, ast.MatchOr)
                else [case.pattern])
    keys: set[str] = set()
    for pat in patterns:
        if not isinstance(pat, ast.MatchValue):
            return None  # a class/sequence/star pattern — unmodelled
        key = _member_key_of_value(pat.value, closed)
        if key is None:
            return None  # a value pattern that is not a known member — refuse
        keys.add(key)
    return keys


def _handled_match_keys(
    node: ast.Match, closed: _ClosedSet
) -> set[str] | None:
    """Every closed-set key the ``match`` handles, or ``None`` when ANY case is a
    catch-all (already total → refuse) or carries an unmappable pattern (refuse)."""
    handled: set[str] = set()
    for case in node.cases:
        if _case_is_wildcard(case):
            return None  # an existing catch-all — the set is already total
        keys = _case_keys(case, closed)
        if keys is None:
            return None
        handled |= keys
    return handled


def _match_wildcard_edit(node: ast.Match, lines: list[str], subject_text: str) -> _Edit:
    """The append edit for a ``match`` missing arms: a trailing ``case _:`` at the
    existing case column with the sentinel one level deeper, inserted after the last
    case body's end line. The case column comes from the FIRST case header; the body
    indent from the last case's first body statement (its real indentation)."""
    case_indent = _indent_at(lines, node.cases[0].pattern.lineno)
    body_indent = _indent_at(lines, node.cases[-1].body[0].lineno)
    new_lines = [f"{case_indent}case _:", _sentinel_body(subject_text, body_indent)]
    return _Edit(after=node.end_lineno - 1, lines=new_lines)


# --- the if/elif path (``ast.If``) -------------------------------------------

def _elif_branch(node: ast.If) -> ast.If | None:
    """The next ``elif`` branch of an ``if`` chain, or ``None``. An ``elif`` is the
    SOLE ``orelse`` statement AND an ``If`` at the SAME column as ``node`` (``elif`` is
    sugar — the inner ``If`` keeps the chain's column); a deeper-indented ``if`` inside
    an ``else:`` block is a NESTED if, not part of this chain, so it is excluded."""
    if (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
            and node.orelse[0].col_offset == node.col_offset):
        return node.orelse[0]
    return None


def _has_trailing_else(node: ast.If) -> bool:
    """True when the ``if``/``elif`` chain ends in a bare ``else:`` — the last link's
    ``orelse`` is non-empty and is NOT another same-column ``elif``. A trailing
    ``else:`` is an existing catch-all → REFUSE (the chain is already total)."""
    link = node
    while True:
        nxt = _elif_branch(link)
        if nxt is None:
            return bool(link.orelse)  # a non-elif orelse is a real `else:` block
        link = nxt


def _branch_keys_from_test(test: ast.expr, closed: _ClosedSet,
                           subject: str) -> set[str] | None:
    """The closed-set keys ONE branch test dispatches on, or ``None`` when the test is
    not a provable ``<subject> == MEMBER`` / ``is MEMBER`` / ``in (MEMBER, ...)``.

    Accepts a single-op ``Compare`` whose left is the subject Name and whose op is
    ``==``/``is`` against one member, or ``in`` against a tuple/list of members. Any
    other shape (a ``BoolOp``, a multi-compare, a non-subject left, a non-member
    comparator) yields ``None`` → the whole chain is refused (we can't prove its
    coverage)."""
    if (not isinstance(test, ast.Compare) or len(test.ops) != 1
            or _subject_name(test.left) != subject):
        return None
    op, rhs = test.ops[0], test.comparators[0]
    if isinstance(op, (ast.Eq, ast.Is)):
        key = _member_key_of_value(rhs, closed)
        return {key} if key is not None else None
    if isinstance(op, ast.In) and isinstance(rhs, (ast.Tuple, ast.List)):
        keys = {_member_key_of_value(e, closed) for e in rhs.elts}
        return keys if None not in keys else None  # type: ignore[comparison-overlap]
    return None


def _handled_if_keys(node: ast.If, closed: _ClosedSet,
                     subject: str) -> set[str] | None:
    """Every closed-set key the ``if``/``elif`` chain handles, or ``None`` when any
    branch test is not a provable subject-vs-member dispatch (refuse)."""
    handled: set[str] = set()
    link: ast.If | None = node
    while link is not None:
        keys = _branch_keys_from_test(link.test, closed, subject)
        if keys is None:
            return None
        handled |= keys
        link = _elif_branch(link)
    return handled


def _chain_end_line(node: ast.If) -> int:
    """The 1-based source line the ``if``/``elif`` chain ends on — the ``end_lineno`` of
    the LAST link's body (the chain has no trailing ``else``, the caller guarantees),
    so the ``else:`` is appended directly after it."""
    link = node
    while True:
        nxt = _elif_branch(link)
        if nxt is None:
            return link.body[-1].end_lineno
        link = nxt


def _if_else_edit(node: ast.If, lines: list[str], subject_text: str) -> _Edit:
    """The append edit for an ``if``/``elif`` chain missing branches: a trailing
    ``else:`` at the ``if`` keyword's column with the sentinel one level deeper,
    inserted after the chain's last body line. The body indent is read from the first
    branch's first body statement (its real indentation)."""
    if_indent = _indent_at(lines, node.lineno)
    body_indent = _indent_at(lines, node.body[0].lineno)
    new_lines = [f"{if_indent}else:", _sentinel_body(subject_text, body_indent)]
    return _Edit(after=_chain_end_line(node) - 1, lines=new_lines)


# --- resolving a dispatch's closed set + collecting edits --------------------

def _scope_of(tree: ast.Module, node: ast.AST) -> ast.AST:
    """The nearest enclosing function/class/module of ``node`` — where its subject's
    annotation is searched. Walks every scope-bearing node and returns the innermost
    one that contains ``node`` by line span; falls back to the module."""
    best: ast.AST = tree
    best_span = -1
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start, end = scope.lineno, getattr(scope, "end_lineno", scope.lineno)
        if start <= node.lineno <= end and start > best_span:
            best, best_span = scope, start
    return best


def _enum_from_arm_values(values: list[ast.expr],
                          enums: dict[str, frozenset[str]]) -> _ClosedSet | None:
    """The enum :class:`_ClosedSet` proven by the arm VALUES alone — when every
    handled value is ``<EnumName>.<MEMBER>`` for ONE in-module enum (no annotation
    needed). ``None`` unless all values name the SAME enumerated enum; the dispatch is
    then closed over that enum's full member set."""
    seen: set[str] = set()
    for value in values:
        if not (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                and value.value.id in enums and value.attr in enums[value.value.id]):
            return None
        seen.add(value.value.id)
    if len(seen) != 1:
        return None  # zero, or a mix of enums — not a single closed set
    name = next(iter(seen))
    return _ClosedSet(enums[name], name)


def _match_arm_values(node: ast.Match) -> list[ast.expr]:
    """Every ``MatchValue`` value across the ``match``'s cases (flattening ``MatchOr``)
    — the candidate enum-member references used to infer the enum when no annotation
    proves the subject's type. Non-``MatchValue`` patterns contribute nothing."""
    out: list[ast.expr] = []
    for case in node.cases:
        pats = (case.pattern.patterns if isinstance(case.pattern, ast.MatchOr)
                else [case.pattern])
        out.extend(p.value for p in pats if isinstance(p, ast.MatchValue))
    return out


def _if_arm_values(node: ast.If) -> list[ast.expr]:
    """Every comparator across the ``if``/``elif`` chain's branch tests (flattening an
    ``in (...)`` tuple) — the candidate enum-member references for enum inference."""
    out: list[ast.expr] = []
    link: ast.If | None = node
    while link is not None:
        test = link.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            rhs = test.comparators[0]
            out.extend(rhs.elts if isinstance(rhs, (ast.Tuple, ast.List)) else [rhs])
        link = _elif_branch(link)
    return out


def _resolve_closed_set(scope: ast.AST, subject: str, arm_values: list[ast.expr],
                        enums: dict[str, frozenset[str]]) -> _ClosedSet | None:
    """The proven :class:`_ClosedSet` for ``subject``, or ``None`` (refuse). Prefers an
    annotation in ``scope`` (``bool`` / ``Literal[...]`` / an in-module enum); falls
    back to inferring a single in-module enum from the dispatch's arm VALUES. A subject
    with neither a closed annotation nor all-same-enum arms is refused."""
    ann = _annotation_of(scope, subject)
    if ann is not None:
        from_ann = _closed_set_from_annotation(ann, enums)
        if from_ann is not None:
            return from_ann
    return _enum_from_arm_values(arm_values, enums)


def _subject_text(lines: list[str], expr: ast.expr) -> str:
    """The exact source slice of the (single-line) subject ``Name`` — spelled into the
    sentinel verbatim. A bare ``Name`` is always single-line, so its slice is
    ``line[col_offset:end_col_offset]``."""
    return lines[expr.lineno - 1][expr.col_offset: expr.end_col_offset]


def _match_edit(node: ast.Match, tree: ast.Module, lines: list[str],
                enums: dict[str, frozenset[str]]) -> _Edit | None:
    """The append edit for one ``match`` dispatch, or ``None`` (refuse). Refuses unless
    the subject is a bare Name, its set is provably closed, the cases carry no
    catch-all and only mappable patterns, and at least one member is unhandled."""
    subject = _subject_name(node.subject)
    if subject is None:
        return None  # an unmodelled match subject
    closed = _resolve_closed_set(_scope_of(tree, node), subject,
                                 _match_arm_values(node), enums)
    if closed is None:
        return None
    handled = _handled_match_keys(node, closed)
    if handled is None or not (closed.keys - handled):
        return None  # a catch-all/unmappable arm, or already total
    return _match_wildcard_edit(node, lines, _subject_text(lines, node.subject))


def _if_edit(node: ast.If, tree: ast.Module, lines: list[str],
             enums: dict[str, frozenset[str]]) -> _Edit | None:
    """The append edit for one ``if``/``elif`` chain head, or ``None`` (refuse).
    Refuses unless every branch tests the SAME bare-Name subject against a member, the
    set is provably closed, there is no trailing ``else:``, and a member is unhandled."""
    if _has_trailing_else(node):
        return None  # an existing catch-all — already total
    subject = _subject_name(node.test.left) if isinstance(node.test, ast.Compare) else None
    if subject is None:
        return None
    closed = _resolve_closed_set(_scope_of(tree, node), subject,
                                 _if_arm_values(node), enums)
    if closed is None:
        return None
    handled = _handled_if_keys(node, closed, subject)
    if handled is None or not (closed.keys - handled):
        return None
    return _if_else_edit(node, lines, subject)


def _elif_if_nodes(tree: ast.Module) -> set[int]:
    """The ``id()``s of every ``If`` that is an ``elif`` link of another chain — the
    inner ``If`` nodes a chain HEAD owns. Collected so the dispatch walk treats only
    chain HEADS as candidates (an ``elif`` is part of its head's chain, never its own
    dispatch)."""
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            nxt = _elif_branch(node)
            if nxt is not None:
                inner.add(id(nxt))
    return inner


def _collect_edits(tree: ast.Module, lines: list[str]) -> list[_Edit]:
    """Every append edit for the module, in source order. Walks each ``ast.Match`` and
    each ``if``/``elif`` chain HEAD (an ``If`` that is not another chain's ``elif``),
    resolving its closed set and refusing on any uncertainty. Empty when nothing is a
    fillable closed-set dispatch."""
    enums = _enum_member_map(tree)
    elif_ids = _elif_if_nodes(tree)
    edits: list[_Edit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Match):
            edit = _match_edit(node, tree, lines, enums)
        elif isinstance(node, ast.If) and id(node) not in elif_ids:
            edit = _if_edit(node, tree, lines, enums)
        else:
            continue
        if edit is not None:
            edits.append(edit)
    return edits


def closed_dispatches(source: str) -> list[str]:
    """The subject TEXTS of the fillable closed-set dispatches in ``source`` — every
    ``match`` / ``if``-chain that is provably closed, missing an arm, and has no
    catch-all. Convenience for tests / single-file reasoning; source order. Returns
    ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = source.splitlines()
    out: list[str] = []
    for edit in _collect_edits(tree, lines):
        # The sentinel line names the subject between "unhandled " and ":".
        sentinel = edit.lines[-1]
        out.append(sentinel.split("unhandled ", 1)[1].split(":", 1)[0])
    return out


def complete_match_exhaustiveness(source: str) -> str | None:
    """Append a loud exhaustiveness sentinel to every fillable closed-set dispatch in
    ``source``, or ``None`` when nothing changes.

    The proof is purely intra-module (a discriminant's type is provably an in-module
    ``Enum`` / a ``Literal[...]`` of constants / ``bool``, and the dispatch lacks a
    member arm AND a catch-all), so NO whole-project scan is needed. Edits are applied
    in REVERSE source line order so earlier line spans stay valid (the same idiom
    ``enum_unique`` uses for its reverse-order decoration). Deterministic and idempotent
    — a second run sees the appended ``case _:`` / ``else:`` catch-all and refuses; the
    result is re-``ast.parse``d via ``rejoin_guarded`` before return, so a malformed
    splice yields ``None`` rather than landing broken Python (and an unchanged result is
    byte-identical ``None``)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    lines = source.splitlines()
    edits = _collect_edits(tree, lines)
    if not edits:
        return None
    out_lines = list(lines)
    for edit in sorted(edits, key=lambda e: e.after, reverse=True):
        out_lines[edit.after + 1: edit.after + 1] = edit.lines
    return rejoin_guarded(source, out_lines)
