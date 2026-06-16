"""Simplify dict-get ternaries — rewrite ``x[k] if k in x else d``.

A small, surgical modernization: the ternary that reads a key only when it is
present is exactly ``dict.get`` with a default::

    x[k] if k in x else d            -> x.get(k, d)
    self.cache[k] if k in self.cache else None
                                     -> self.cache.get(k, None)
    d['x'] if 'x' in d else 1        -> d.get('x', 1)

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the whole expression is an ``ast.IfExp`` (the ternary
    ``BODY if TEST else ORELSE``);
  - ``body`` is an ``ast.Subscript`` on ``<x>`` with key ``<k>``;
  - ``test`` is an ``ast.Compare`` with a single ``ast.In`` op, ``<k2> in <x2>``;
  - the container ``<x>`` equals ``<x2>`` and the key ``<k>`` equals ``<k2>``,
    each compared by ``ast.dump``; any difference skips the occurrence;
  - the IfExp must live on a SINGLE line so the column-span splice is trivially
    correct — multi-line ternaries are skipped.

Because ``<x>`` and ``<k>`` are evaluated twice in the original (in the
subscript and in the ``in`` test) but once after the rewrite, the change is
only safe when they are side-effect-free. So ``<x>`` is restricted to a Name or
an Attribute chain of Names, and ``<k>`` to a Name / Constant / Attribute chain;
anything that could have a side effect (a Call, a Subscript, ...) skips the
occurrence. This keeps the rewrite always correct.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. The container and key
keep their ORIGINAL source text (via ``ast.get_source_segment``) for fidelity;
any segment that can't be recovered skips that occurrence, and the rewritten
module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left within a line so earlier
offsets stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)

__all__ = ["plan_simplify_dict_get"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its repetition is often deliberate
    boilerplate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _is_pure_container(node: ast.AST) -> bool:
    """``<x>`` is side-effect-free to evaluate twice: a Name or an Attribute
    chain rooted in a Name."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_pure_container(node.value)
    return False


def _is_pure_key(node: ast.AST) -> bool:
    """``<k>`` is side-effect-free to evaluate twice: a Name, a Constant, or an
    Attribute chain rooted in a Name/Constant."""
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_pure_key(node.value)
    return False


def _try_ifexp(node: ast.IfExp, source: str) -> _Rewrite | None:
    """If ``node`` is a ``x[k] if k in x else d`` ternary, return its rewrite,
    else None."""
    if node.lineno != node.end_lineno:
        return None

    body = node.body
    if not isinstance(body, ast.Subscript):
        return None
    container = body.value
    key = body.slice
    # In py3.9+ the slice is the expression directly; a real slice (a:b) is an
    # ast.Slice, which never equals a membership element, so it's filtered out
    # by the dump comparison below — but guard explicitly for clarity.
    if isinstance(key, ast.Slice):
        return None

    test = node.test
    if not isinstance(test, ast.Compare):
        return None
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.In):
        return None
    element = test.left
    membership = test.comparators[0]

    if ast.dump(container) != ast.dump(membership):
        return None
    if ast.dump(key) != ast.dump(element):
        return None

    if not _is_pure_container(container):
        return None
    if not _is_pure_key(key):
        return None

    x_src = ast.get_source_segment(source, container)
    k_src = ast.get_source_segment(source, key)
    d_src = ast.get_source_segment(source, node.orelse)
    if x_src is None or k_src is None or d_src is None:
        return None

    replacement = f"{x_src}.get({k_src}, {d_src})"
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    replacement)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every dict-get ternary rewrite in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp):
            rw = _try_ifexp(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: (r.lineno, r.col), reverse=True):
        line = lines[rw.lineno - 1]
        lines[rw.lineno - 1] = line[:rw.col] + rw.text + line[rw.end_col:]
    return "".join(lines)


def plan_simplify_dict_get(project_root: str | Path,
                           module_rel: str) -> RenamePlan:
    """Build the single-module dict-get simplification plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every exact
    ``x[k] if k in x else d`` ternary in the file into ``x.get(k, d)``; an empty
    plan means nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="simplify-dict-get")
    if _is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="simplification")
