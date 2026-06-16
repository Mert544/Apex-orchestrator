"""Use enumerate — rewrite ``for i in range(len(seq)): seq[i]`` into enumerate.

A classic anti-pattern modernization: a loop that walks indices only to index
back into the same sequence is just ``enumerate``. The transform rewrites the
EXACT shape below and nothing else::

    for i in range(len(seq)):
        ... seq[i] ...

becomes (the index is dropped because it is now unused — see below)::

    for _, seq_item in enumerate(seq):
        ... seq_item ...

This rewrites the loop BODY, not just a header, so it is the most conservative
of the transforms: any doubt is a SKIP, never a guess.

The ``i``-vs-``_`` decision (documented & enforced by the tests + ruff):
  The match guarantees ``i`` is referenced ONLY through ``seq[i]`` loads, every
  one of which is replaced by the fresh element name. After the rewrite ``i`` is
  therefore TRULY unused, so binding it would trip an unused-variable lint. We
  bind the index to ``_`` (``for _, <elem> in enumerate(seq):``) — the
  conventional throwaway — rather than keeping a dead ``i``. This is only ever
  done because the match proves ``i`` had no other use, so dropping its name
  loses nothing and the result stays lint-clean.

Conservative by design — every condition below must hold, or the occurrence is
skipped (and an occurrence whose segment can't be recovered is skipped too):

  - an ``ast.For`` (not ``AsyncFor``) with NO ``orelse`` (no for/else);
  - the loop target is a plain Name ``i``;
  - the iterable is EXACTLY ``range(len(<seq>))`` — a Call to the bare name
    ``range`` with ONE positional arg, which is a Call to the bare name ``len``
    with ONE positional arg ``<seq>``, where ``<seq>`` is a Name or an
    attribute-chain of Names (e.g. ``self.items``) — no calls, no subscripts,
    no starargs, no keywords anywhere in the ``range``/``len`` calls. The
    start-stop forms (``range(0, len(x))``, ``range(len(a), len(b))``) are NOT
    this shape and are left untouched;
  - inside the body, ``i`` is used ONLY as ``<seq>[i]`` — a Subscript of EXACTLY
    ``<seq>`` by EXACTLY the Name ``i`` in Load context — and NOWHERE else (not a
    store ``seq[i] = ...``, not ``i + 1``, not passed anywhere, not referenced by
    a nested function/lambda/comprehension); any other appearance of ``i`` skips;
  - ``<seq>`` is not rebound anywhere in the body (a plain-Name seq assigned/
    augmented/annotated/deleted, or the first name of an attribute-chain seq
    rebound, would change what is indexed) — any rebinding skips;
  - the fresh element name (derived from ``<seq>``'s LAST name + ``_item``, made
    unique) must not collide with any name bound or used in the enclosing
    function (or module, for a top-level loop) — uniqueness is enforced.

Edits are line-span replacements located by the AST: the whole ``for`` (header
through the last body line) is replaced by the rewritten header plus the body
with every ``seq[i]`` load swapped for the element name. The element-name
substitution is a column splice within the (verbatim-copied) body lines, applied
right-to-left so offsets stay valid. The rewritten module must re-parse or the
whole plan blocks. Rewrites across a module are applied bottom-up so earlier line
numbers stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_line_rewrites,
)
from app.execution._transform_base import plan_single_module_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_use_enumerate"]


def _attr_chain_names(node: ast.expr) -> list[str] | None:
    """The dotted name list of an attribute-chain of plain Names, else None.

    ``seq`` -> ``["seq"]``; ``self.items`` -> ``["self", "items"]``;
    ``a.b.c`` -> ``["a", "b", "c"]``. Anything with a call/subscript/star in the
    chain (``f().x``, ``a[0].b``) yields None so the seq is a pure attribute path.
    """
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        base = _attr_chain_names(node.value)
        if base is None:
            return None
        return [*base, node.attr]
    return None


def _bare_call(node: ast.expr, name: str) -> ast.Call | None:
    """``node`` as a Call to the bare builtin Name ``name`` with exactly one
    positional arg and no starargs/keywords, else None."""
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Name) or node.func.id != name:
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    if isinstance(node.args[0], ast.Starred):
        return None
    return node


def _range_len_seq(iter_node: ast.expr) -> ast.expr | None:
    """The ``<seq>`` node of an iterable that is EXACTLY ``range(len(<seq>))``
    where ``<seq>`` is a Name or attribute-chain of Names, else None.

    Excludes the two-arg / start-stop forms (``range(0, len(x))``,
    ``range(len(a), len(b))``) — those are not the bare ``range(len(seq))`` shape.
    """
    range_call = _bare_call(iter_node, "range")
    if range_call is None:
        return None
    len_call = _bare_call(range_call.args[0], "len")
    if len_call is None:
        return None
    seq = len_call.args[0]
    if _attr_chain_names(seq) is None:
        return None
    return seq


def _is_seq_index_load(node: ast.AST, seq_names: list[str]) -> bool:
    """True when ``node`` is exactly ``<seq>[i]`` in Load context — a Subscript
    whose value is the attribute-chain ``seq_names`` and whose index is the plain
    Name ``i`` (also Load) — i.e. the one allowed shape that mentions ``i``."""
    if not isinstance(node, ast.Subscript):
        return False
    if not isinstance(node.ctx, ast.Load):
        return False
    if _attr_chain_names(node.value) != seq_names:
        return False
    index = node.slice
    return (
        isinstance(index, ast.Name)
        and index.id == "i"
        and isinstance(index.ctx, ast.Load)
    )


def _i_used_only_as_index(body: list[ast.stmt], seq_names: list[str]) -> bool:
    """True iff EVERY occurrence of the Name ``i`` in ``body`` is the index of a
    sanctioned ``<seq>[i]`` Load and ``i`` appears NOWHERE else.

    We walk every node; whenever we meet an allowed ``<seq>[i]`` subscript we mark
    the inner ``i`` Name node as 'accounted for'. Any ``i`` Name node that is not
    one of those accounted-for indices (a store ``i``, ``i + 1``, ``f(i)``, an
    ``i`` captured by a nested def/lambda/comprehension — ``ast.walk`` reaches
    into those too) means ``i`` has a use we can't drop, so we refuse."""
    accounted: set[int] = set()
    for stmt in body:
        for node in ast.walk(stmt):
            if _is_seq_index_load(node, seq_names):
                accounted.add(id(node.slice))
    for stmt in body:
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Name) and node.id == "i"
                    and id(node) not in accounted):
                return False
    return True


def _seq_rebound(body: list[ast.stmt], seq_names: list[str]) -> bool:
    """True if ``<seq>`` could be rebound anywhere in ``body``.

    For a plain-Name seq (``["seq"]``) any binding of that name — assignment,
    aug-assignment, annotated assignment, ``for`` target, ``with``/``except``
    alias, ``del``, or a nested ``def``/``class``/import of that name — counts.
    For an attribute-chain seq (``self.items``) we conservatively treat a rebind
    of its FIRST name (``self``) the same way: if ``self`` is reassigned the path
    no longer points where it did. Detected via every Store/Del-context Name plus
    the binding statements ``ast.walk`` exposes."""
    head = seq_names[0]
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and node.id == head and isinstance(
                    node.ctx, (ast.Store, ast.Del)):
                return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.name == head:
                return True
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound == head:
                        return True
    return False


def _scope_names(scope: ast.AST) -> set[str]:
    """Every name bound OR used directly within ``scope``, used to guarantee the
    fresh element name does not collide.

    We over-collect deliberately — every ``Name``, every ``arg``, every
    ``def``/``class`` name, every imported alias, every attribute *attr* — so the
    chosen element name is fresh against anything the code references. Walking the
    whole subtree (including nested scopes) is intentionally conservative."""
    names: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _fresh_elem_name(seq_names: list[str], taken: set[str]) -> str:
    """A fresh element name derived from ``<seq>``'s last name + ``_item``, made
    unique against ``taken`` by appending ``_2``, ``_3``, … as needed."""
    base = f"{seq_names[-1]}_item"
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


class _Rewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) — the
    whole ``for`` — with ``header`` plus ``body_lines`` (the original body lines
    with each ``seq[i]`` load spliced to the element name)."""

    __slots__ = ("lo", "hi", "header", "body_lines")

    def __init__(self, lo: int, hi: int, header: str,
                 body_lines: list[str]) -> None:
        self.lo = lo
        self.hi = hi
        self.header = header
        self.body_lines = body_lines


def _splice_body(lines: list[str], body_lo: int, body_hi: int,
                 subs: list[ast.Subscript], elem: str) -> list[str] | None:
    """The body lines [body_lo, body_hi] with every ``<seq>[i]`` Load (``subs``)
    column-replaced by ``elem``, applied right-to-left/bottom-up so offsets stay
    valid. Returns None if any subscript spans multiple lines (we only splice
    single-line occurrences, keeping the rewrite trivially correct)."""
    out = [lines[n - 1] for n in range(body_lo, body_hi + 1)]
    ordered = sorted(
        subs, key=lambda s: (s.lineno, s.col_offset), reverse=True)
    for sub in ordered:
        if sub.lineno != sub.end_lineno:
            return None  # multi-line subscript — skip the whole occurrence
        rel = sub.lineno - body_lo
        line = out[rel]
        out[rel] = line[:sub.col_offset] + elem + line[sub.end_col_offset:]
    return out


def _match_header_seq(for_stmt: ast.For) -> tuple[ast.expr, list[str]] | None:
    """The ``(seq_node, seq_names)`` of a ``for i in range(len(seq)):`` header
    with no for/else and target the plain Name ``i``, else None."""
    if for_stmt.orelse:
        return None  # for/else changes semantics — skip
    if not isinstance(for_stmt.target, ast.Name) or for_stmt.target.id != "i":
        return None
    seq = _range_len_seq(for_stmt.iter)
    if seq is None:
        return None
    seq_names = _attr_chain_names(seq)
    if seq_names is None:  # _range_len_seq guarantees this, but stay defensive
        return None
    return seq, seq_names


def _index_subs(body: list[ast.stmt], seq_names: list[str]) -> list[ast.Subscript]:
    """Every sanctioned ``<seq>[i]`` Load subscript in ``body`` (the loads to be
    spliced to the element name)."""
    subs: list[ast.Subscript] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Subscript) and _is_seq_index_load(
                    node, seq_names):
                subs.append(node)
    return subs


def _seq_source(source: str, seq: ast.expr) -> str | None:
    """The single-line source text of ``seq``, or None when it spans lines or
    cannot be recovered."""
    if seq.lineno != seq.end_lineno:
        return None  # multi-line seq — skip
    seq_src = ast.get_source_segment(source, seq)
    if seq_src is None or "\n" in seq_src:
        return None  # can't recover the seq source — skip
    return seq_src


def _match_for(for_stmt: ast.For, source: str
               ) -> tuple[str, list[str], list[ast.Subscript]] | None:
    """The ``(seq_src, seq_names, subs)`` of a fully-validated convertible loop —
    exact header, ``i`` used only as ``seq[i]``, ``seq`` not rebound, at least one
    recoverable single-line ``seq[i]`` load — else None (the occurrence skips)."""
    matched = _match_header_seq(for_stmt)
    if matched is None:
        return None
    seq, seq_names = matched
    if not _i_used_only_as_index(for_stmt.body, seq_names):
        return None
    if _seq_rebound(for_stmt.body, seq_names):
        return None
    # Need at least one ``seq[i]`` load, or enumerate adds nothing.
    subs = _index_subs(for_stmt.body, seq_names)
    if not subs:
        return None
    seq_src = _seq_source(source, seq)
    if seq_src is None:
        return None
    return seq_src, seq_names, subs


def _try_for(for_stmt: ast.For, source: str, lines: list[str],
             scope_names: set[str]) -> _Rewrite | None:
    """If ``for_stmt`` is the exact ``for i in range(len(seq)): ... seq[i] ...``
    shape with ``i`` used only as ``seq[i]`` and ``seq`` not rebound, return its
    rewrite; else None (the occurrence is skipped)."""
    matched = _match_for(for_stmt, source)
    if matched is None:
        return None
    seq_src, seq_names, subs = matched

    elem = _fresh_elem_name(seq_names, scope_names)
    body_lo = for_stmt.body[0].lineno
    body_hi = max(s.end_lineno for s in for_stmt.body)
    body_lines = _splice_body(lines, body_lo, body_hi, subs, elem)
    if body_lines is None:
        return None

    newline = "\n" if lines[for_stmt.lineno - 1].endswith("\n") else ""
    header = (" " * for_stmt.col_offset
              + f"for _, {elem} in enumerate({seq_src}):" + newline)
    return _Rewrite(for_stmt.lineno, body_hi, header, body_lines)


def _enclosing_scopes(tree: ast.Module) -> list[ast.AST]:
    """The module plus every function/lambda/class — each a scope whose names a
    contained loop's fresh element name must avoid."""
    scopes: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            scopes.append(node)
    return scopes


def _scope_for(for_stmt: ast.For, scopes: list[ast.AST]) -> ast.AST:
    """The NEAREST scope (function/class/module) that contains ``for_stmt`` — the
    smallest scope whose subtree includes it — so the element name is fresh where
    it actually lands."""
    best: ast.AST = scopes[0]
    best_size = -1
    for scope in scopes:
        if scope is for_stmt:
            continue
        if not any(node is for_stmt for node in ast.walk(scope)):
            continue
        size = sum(1 for _ in ast.walk(scope))
        if best_size < 0 or size < best_size:
            best, best_size = scope, size
    return best


def _collect_rewrites(tree: ast.Module, source: str,
                      lines: list[str]) -> list[_Rewrite]:
    """Every NON-OVERLAPPING use-enumerate rewrite in ``tree``.

    Nested matching loops could overlap (an inner ``for`` inside the body of an
    outer match); applying both would corrupt the source, so — exactly like
    merge-nested-if — we keep the OUTERMOST of any overlapping group and leave
    the remainder for a later pass (the compiler re-scans)."""
    scopes = _enclosing_scopes(tree)
    candidates: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            scope = _scope_for(node, scopes)
            scope_names = _scope_names(scope)
            rw = _try_for(node, source, lines, scope_names)
            if rw is not None:
                candidates.append(rw)

    kept: list[_Rewrite] = []
    covered_through = 0  # highest ``hi`` of an accepted rewrite (1-based line)
    for rw in sorted(candidates, key=lambda r: r.lo):
        if rw.lo <= covered_through:
            continue  # nested inside an already-kept span — skip this pass
        kept.append(rw)
        covered_through = rw.hi
    return kept


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up (highest line first) so earlier line numbers stay
    valid. Each becomes the rewritten header line plus the spliced body lines,
    replacing the whole original ``for``."""
    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, [rw.header, *rw.body_lines]) for rw in rewrites],
    )


def plan_use_enumerate(project_root: str | Path,
                       module_rel: str) -> RenamePlan:
    """Build the single-module use-enumerate plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every exact
    ``for i in range(len(seq)): ... seq[i] ...`` shape (``i`` used only as the
    index, ``seq`` not rebound, no for/else) into
    ``for _, <elem> in enumerate(seq): ... <elem> ...``. An empty plan means
    nothing matched — a no-op, not a failure."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="use-enumerate",
        collect=lambda tree, source: _collect_rewrites(
            tree, source, source.splitlines(keepends=True)),
        apply=_apply,
        reparse_phrase="use-enumerate")
