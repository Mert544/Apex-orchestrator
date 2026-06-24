"""Merge duplicate ``from``-imports — collapse repeated same-module lines into one.

Multiple top-level ``from <m> import ...`` statements that name the SAME module at
the SAME relative ``level`` are redundant line noise: they can be written as a
single ``from <m> import a, b, c`` whose bound names are byte-for-byte the same
multiset. Apex merges exactly those groups and nothing else:

  - ``from collections import OrderedDict`` + ``from collections import defaultdict``
    -> ``from collections import OrderedDict, defaultdict`` (first-appearance order);
  - an EXACT duplicate alias (same ``name``, same ``asname``) is de-duplicated — still
    binding-identical, only the literal repeat is dropped.

The merge is PROVABLY behaviour-preserving: the multiset of ``(module, level, name,
asname)`` bindings the module establishes is unchanged — only the statement count
drops (importing the same module twice is a no-op in CPython; the module object is
cached, so a merge cannot change an import side effect either).

Conservative by design — any ambiguity leaves the WHOLE module untouched, never a
guess:
  - only TOP-LEVEL (``tree.body``) ``from``-imports are grouped; a guarded import
    inside ``try``/``if``/``with`` or a function/class body is conditional and is
    never hoisted to a top-level sibling's position (an import guarded by a DIFFERENT
    block than its would-be partner is left alone);
  - ``from __future__ import ...`` is NEVER merged (a compiler directive whose order
    and placement are significant);
  - a star import (``from x import *``) anywhere makes the module a no-op (names could
    be bound through it);
  - a statement carrying a trailing comment, ``# noqa`` or ``# type:`` on any of its
    source lines is left as written (merging would silently drop the human's note);
    a STANDALONE comment line in the GAP between two members also blocks the group —
    deleting the second member would orphan it (its referent is gone);
  - an INCOMPATIBLE alias — the SAME bound local name imported from two different
    ``(name, asname)`` pairs (e.g. ``import x as a`` and ``import y as a``) — blocks
    that one group: merging would silently pick a single binding, so the group is
    left untouched;
  - INTERVENING code between the first and last member of a group blocks it on two
    grounds: (a) execution re-order — any non-import statement that RUNS between them
    would move; (b) binding re-order — an intervening import (a plain ``import`` or
    another ``from``-import group) that BINDS A LOCAL NAME the group also binds, since
    hoisting a member up past it flips that name's final binding. A disjoint-name
    intervening import is import-only and stays safe to coalesce past;
  - the rewritten module must re-``ast.parse``, or the whole change is dropped.

Edits are line-span replacements applied bottom-up so earlier line numbers stay
valid. Deterministic, stdlib-only, idempotent (a module with no duplicate group is a
byte-identical no-op).
"""

from __future__ import annotations

import ast

__all__ = ["merge_duplicate_imports"]


def _has_star_import(tree: ast.Module) -> bool:
    """Does any statement anywhere do ``from x import *``? If so the whole module
    is a no-op — names could be bound through the star."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names):
            return True
    return False


def _mergeable_node(node: ast.AST) -> bool:
    """A top-level ``from``-import we may consider merging: a ``from x import ...``
    that is neither ``from __future__`` nor a star import (both always left alone)."""
    if not isinstance(node, ast.ImportFrom):
        return False
    return node.module != "__future__" and not any(
        alias.name == "*" for alias in node.names)


def _group_key(node: ast.ImportFrom) -> tuple[int, str]:
    """The ``(level, module)`` identity a ``from``-import is grouped by — same
    relative level AND same module string merge together."""
    return (node.level, node.module or "")


def _carries_comment(lines: list[str], lineno: int, end_lineno: int) -> bool:
    """Does any source line of the statement carry a ``#`` comment (a trailing
    comment, ``# noqa`` or ``# type:``) that a merge would drop?

    Conservative: a ``#`` anywhere outside a string on the statement's lines is
    treated as a comment to preserve. Tokenizing the exact span is overkill — the
    rare false positive (a ``#`` inside a string literal on an import line, which is
    not valid in a ``from``-import anyway) only makes the merge a SAFE refuse."""
    for i in range(lineno - 1, end_lineno):
        if "#" in lines[i]:
            return True
    return False


def _comment_between_members(group: list[ast.ImportFrom], lines: list[str]) -> bool:
    """Does a STANDALONE comment line sit in a gap BETWEEN two consecutive members of
    the group?

    ``_carries_comment`` only scans each statement's OWN source lines, so a comment on
    its own line between two members (e.g. ``from m import a`` / ``# why b`` /
    ``from m import b``) is invisible to it — yet the merge deletes the second member,
    leaving that comment orphaned (its referent is gone). Refuse the merge when such a
    gap comment exists. Conservative: any ``#`` on an inter-member line counts (the
    same SAFE-refuse rationale as ``_carries_comment``)."""
    for prev, cur in zip(group, group[1:]):
        for i in range(prev.end_lineno, cur.lineno - 1):
            if "#" in lines[i]:
                return True
    return False


def _alias_pairs(node: ast.ImportFrom) -> list[tuple[str, str | None]]:
    """The ``(name, asname)`` pairs a ``from``-import binds, in source order."""
    return [(alias.name, alias.asname) for alias in node.names]


def _bound_name(pair: tuple[str, str | None]) -> str:
    """The local name a ``(name, asname)`` pair binds: the asname if present, else
    the imported name (a ``from``-import name is never dotted)."""
    name, asname = pair
    return asname if asname is not None else name


def _import_local_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    """The set of LOCAL (top-level) names an import statement binds.

    For ``from m import a, b as c`` it is ``{a, c}`` (the asname wins). For a plain
    ``import x.y`` it is ``{x}`` — binding ``import x.y`` makes only the top package
    ``x`` a name (``import x.y as z`` binds ``z`` instead). These are exactly the
    names a merge could RE-ORDER, so they are what an intervening import is checked
    against."""
    if isinstance(node, ast.ImportFrom):
        return {_bound_name(pair) for pair in _alias_pairs(node)}
    names: set[str] = set()
    for alias in node.names:
        names.add(alias.asname if alias.asname is not None
                  else alias.name.split(".", 1)[0])
    return names


def _group_local_names(group: list[ast.ImportFrom]) -> set[str]:
    """Every LOCAL name the group's members bind — the names whose final binding a
    merge must not silently re-order."""
    names: set[str] = set()
    for node in group:
        names |= _import_local_names(node)
    return names


def _has_incompatible_alias(group: list[ast.ImportFrom]) -> bool:
    """Does the group bind the SAME local name from two DIFFERENT ``(name, asname)``
    pairs? Merging then would silently pick one binding, so the group is refused.

    An EXACT repeat (identical pair) is fine — it de-duplicates to one alias, still
    binding-identical."""
    by_local: dict[str, tuple[str, str | None]] = {}
    for node in group:
        for pair in _alias_pairs(node):
            local = _bound_name(pair)
            if local in by_local and by_local[local] != pair:
                return True
            by_local[local] = pair
    return False


def _intervening_code(tree: ast.Module, group: list[ast.ImportFrom]) -> bool:
    """Is there a statement between the FIRST and LAST member of ``group`` that makes
    the merge unsafe?

    Merging collapses the later members onto the first's position; that is only safe
    when nothing between them is disturbed. Two distinct hazards block the group:

    * EXECUTION re-order — any non-import statement (an assignment, a call, a
      def/class, a ``try``/``if`` block, …) between the endpoints would run in a
      different order after the collapse, so it blocks.
    * BINDING re-order — an intervening import (plain ``import`` or another
      ``from``-import group) that binds a LOCAL NAME the group ALSO binds. Imports
      are cached, so re-ordering their SIDE EFFECTS is a no-op; but hoisting a group
      member up past such an import moves where that member's binding executes,
      which FLIPS the name's final binding (e.g. ``from a import x`` / ``import y`` /
      ``from a import y`` — merging the two ``from a`` lines lifts ``y`` above
      ``import y`` so ``y`` ends up the module, not ``a.y``). A DISJOINT-name
      intervening import touches none of the group's names and stays safe to
      coalesce past.

    Conservative: refuse if unsure."""
    first, last = group[0], group[-1]
    group_names = _group_local_names(group)
    for node in tree.body:
        if not (first.lineno < node.lineno <= last.lineno):
            continue
        if node in group:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if _import_local_names(node) & group_names:
                return True  # rebinds a group name — collapsing flips its binding
            continue  # disjoint-name import — safe to coalesce past
        return True
    return False


def _ordered_aliases(group: list[ast.ImportFrom]) -> list[tuple[str, str | None]]:
    """The merged alias list: every ``(name, asname)`` pair across the group in
    first-appearance order, with exact repeats de-duplicated."""
    seen: set[tuple[str, str | None]] = set()
    out: list[tuple[str, str | None]] = []
    for node in group:
        for pair in _alias_pairs(node):
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out


def _alias_text(pair: tuple[str, str | None]) -> str:
    """Render one alias as it appears in an import list (``a`` or ``a as b``)."""
    name, asname = pair
    return name if asname is None else f"{name} as {asname}"


def _merged_line(group: list[ast.ImportFrom], newline: str) -> str:
    """The single replacement ``from``-import for ``group``, emitted at (and with the
    indentation of) the first member, listing every alias in first-appearance order."""
    first = group[0]
    indent = " " * first.col_offset
    prefix = "." * first.level + (first.module or "")
    parts = ", ".join(_alias_text(p) for p in _ordered_aliases(group))
    return f"{indent}from {prefix} import {parts}{newline}"


class _Rewrite:
    """One located edit: replace lines [lo, hi] (1-based, inclusive) with ``text``
    (None deletes the span — a later group member folded into the first)."""

    __slots__ = ("lo", "hi", "text")

    def __init__(self, lo: int, hi: int, text: str | None) -> None:
        self.lo = lo
        self.hi = hi
        self.text = text


def _group_is_mergeable(
    tree: ast.Module, group: list[ast.ImportFrom], lines: list[str]
) -> bool:
    """Is this ≥2-member group safe to merge? (All refusal gates in one place.)"""
    if len(group) < 2:
        return False
    if any(_carries_comment(lines, n.lineno, n.end_lineno) for n in group):
        return False
    if _comment_between_members(group, lines):
        return False
    if _has_incompatible_alias(group):
        return False
    if _intervening_code(tree, group):
        return False
    return True


def _group_rewrites(
    group: list[ast.ImportFrom], lines: list[str]
) -> list[_Rewrite]:
    """Rewrites for one mergeable group: the merged line at the first member, each
    later member deleted."""
    first = group[0]
    newline = "\n" if lines[first.end_lineno - 1].endswith("\n") else ""
    rewrites = [_Rewrite(first.lineno, first.end_lineno,
                         _merged_line(group, newline))]
    for node in group[1:]:
        rewrites.append(_Rewrite(node.lineno, node.end_lineno, None))
    return rewrites


def _collect_rewrites(tree: ast.Module, lines: list[str]) -> list[_Rewrite]:
    """Every merge rewrite in the module body. Groups module-body ``from``-imports by
    ``(level, module)`` (first-appearance order preserved), keeps the mergeable
    ≥2-member groups, and emits each one's merged-line + delete-span edits."""
    groups: dict[tuple[int, str], list[ast.ImportFrom]] = {}
    for node in tree.body:
        if _mergeable_node(node):
            groups.setdefault(_group_key(node), []).append(node)

    rewrites: list[_Rewrite] = []
    for group in groups.values():
        if _group_is_mergeable(tree, group, lines):
            rewrites.extend(_group_rewrites(group, lines))
    return rewrites


def _apply(lines: list[str], rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up so earlier line numbers stay valid. A ``None`` text
    deletes the span; otherwise it replaces the span with the single merged line."""
    out = list(lines)
    for rw in sorted(rewrites, key=lambda r: r.lo, reverse=True):
        if rw.text is None:
            out[rw.lo - 1:rw.hi] = []
        else:
            out[rw.lo - 1:rw.hi] = [rw.text]
    return "".join(out)


def merge_duplicate_imports(source: str) -> str | None:
    """Return ``source`` with duplicate top-level ``from``-imports merged, or ``None``
    when there is nothing safe to merge.

    The path-free core the objective plan reuses: it applies the exact conservative
    detector documented at module scope — ``from __future__`` and star-import modules
    are never touched, comment/``# noqa``/``# type:`` lines and non-top-level imports
    are left alone, incompatible aliases and intervening-code groups are refused.
    ``None`` means "leave as-is": the source doesn't parse, a star import makes the
    module a no-op, no group was mergeable, the merge would be byte-identical, or the
    merged source would not re-parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    if _has_star_import(tree):
        return None  # too risky — names could be bound via the star (no-op)

    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, lines)
    if not rewrites:
        return None  # nothing to merge

    new_source = _apply(lines, rewrites)
    if new_source == source:
        return None
    try:
        ast.parse(new_source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None  # never emit broken source
    return new_source
