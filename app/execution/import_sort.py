"""Sort imports — order one clean import block deterministically.

A code-DEVELOPMENT move (not a detector): reorder ONE contiguous, comment-free
run of top-level ``import`` / ``from ... import`` statements into grouped,
alphabetized order while preserving each import line's ORIGINAL source text
exactly (via :func:`ast.get_source_segment`, so multi-line parenthesized bodies
survive verbatim).

The block is the maximal run of consecutive module-body statements that are all
``ast.Import`` / ``ast.ImportFrom``, starting at the first such statement that
appears AFTER the module docstring and AFTER any ``from __future__`` imports.
``__future__`` imports stay exactly where they are — never moved or grouped.

Statements are classified into three groups:

  0 = standard library (root module in ``sys.stdlib_module_names``),
  1 = third-party (anything else not first-party),
  2 = first-party (root module is ``app``, or a relative import).

and rendered groups-in-order 0, 1, 2 with a single blank line between non-empty
groups and no blank lines within a group. Sort key is ``(group, root_lower,
original_text)`` — deterministic, never dependent on dict/set iteration order.

Conservative by design — any ambiguity is a NO-OP (empty plan, no blockers),
never a guess:
  - if the chosen run's line span contains any non-import source line (a comment
    or a blank line interleaved with the imports), abort;
  - fewer than two imports in the run, abort;
  - an already-sorted block (byte-identical render) is a no-op;
  - read/parse failure is a blocker; the rewritten module must re-parse or block.

Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_sort_imports"]

# The project's own package — its imports are first-party (group 2).
_FIRST_PARTY_ROOTS = frozenset({"app"})


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its import ordering is often
    deliberate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _is_import(node: ast.stmt) -> bool:
    return isinstance(node, (ast.Import, ast.ImportFrom))


def _is_future(node: ast.stmt) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _root_module(node: ast.stmt) -> str:
    """The root module name of an import statement: ``import a.b`` -> ``a``,
    ``from a.b import x`` -> ``a``. Relative imports yield ``""``."""
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0] if node.names else ""
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return ""
        return (node.module or "").split(".")[0]
    return ""


def _group_of(node: ast.stmt) -> int:
    """0 = stdlib, 1 = third-party, 2 = first-party. A relative import
    (``from . import x``) is first-party; ``app`` is first-party."""
    if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
        return 2
    root = _root_module(node)
    if root in _FIRST_PARTY_ROOTS:
        return 2
    if root and root in sys.stdlib_module_names:
        return 0
    return 1


def _find_block(tree: ast.Module) -> list[ast.stmt] | None:
    """The contiguous import run to sort, or None when there isn't a clean one.

    Skips a leading module docstring and every ``from __future__`` import, then
    takes the maximal run of consecutive import statements starting at the first
    non-future import. Fewer than two members -> None."""
    body = list(tree.body)
    i = 0
    # Skip the module docstring, if present.
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        i = 1
    # Skip `from __future__` imports — left exactly where they are.
    while i < len(body) and _is_future(body[i]):
        i += 1
    # The run must start on an import statement.
    if i >= len(body) or not _is_import(body[i]):
        return None
    start = i
    while i < len(body) and _is_import(body[i]) and not _is_future(body[i]):
        i += 1
    run = body[start:i]
    if len(run) < 2:
        return None
    return run


def _span_is_clean(source: str, run: list[ast.stmt]) -> bool:
    """Every source line in the run's lineno..end_lineno span belongs to an
    import statement — no interleaved comment or blank line. Multi-line
    parenthesized imports are fine: their whole span is one statement's."""
    lines = source.splitlines()
    covered: set[int] = set()
    for node in run:
        for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            covered.add(lineno)
    lo = run[0].lineno
    hi = run[-1].end_lineno or run[-1].lineno
    for lineno in range(lo, hi + 1):
        if lineno not in covered:
            return False  # a line inside the span isn't part of any import
        # A covered line that is blank/comment-only would mean a stray gap; the
        # gap is caught above, but guard the blank case explicitly too.
        if lineno - 1 < len(lines) and not lines[lineno - 1].strip():
            return False
    return True


def _statement_key(node: ast.stmt) -> str:
    """The lowercased module key a statement sorts within its group by."""
    if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
        return ("." * node.level + (node.module or "")).lower()
    return _root_module(node).lower()


def _render_block(source: str, run: list[ast.stmt]) -> str | None:
    """The sorted import block as text, or None when a statement's source
    segment can't be recovered."""
    entries: list[tuple[int, str, str]] = []
    for node in run:
        segment = ast.get_source_segment(source, node)
        if segment is None:
            return None
        entries.append((_group_of(node), _statement_key(node), segment))
    entries.sort(key=lambda e: (e[0], e[1], e[2]))

    chunks: list[list[str]] = [[], [], []]
    for group, _key, segment in entries:
        chunks[group].append(segment)
    blocks = ["\n".join(chunk) for chunk in chunks if chunk]
    return "\n\n".join(blocks)


def _splice(source: str, lo: int, hi: int, new_block: str) -> str:
    """Replace lines [lo, hi] (1-based, inclusive) with ``new_block``,
    preserving the original region's trailing newline shape."""
    lines = source.splitlines(keepends=True)
    last = lines[hi - 1]
    newline = "\n" if last.endswith("\n") else ""
    lines[lo - 1:hi] = [new_block + newline]
    return "".join(lines)


def plan_sort_imports(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module import-sort plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    An empty plan means there was no clean, unsorted import run to reorder (a
    no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="sort-imports")
    root = Path(project_root)
    path = root / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return plan

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{module_rel} doesn't parse: {e}")
        return plan

    run = _find_block(tree)
    if run is None:
        return plan  # nothing to sort — empty plan (ok is False, no blockers)

    if not _span_is_clean(source, run):
        return plan  # interleaved comment/blank line — abort, stay safe

    new_block = _render_block(source, run)
    if new_block is None:
        plan.blockers.append(
            f"{module_rel}: an import statement's source couldn't be "
            "recovered — skipped to stay safe")
        return plan

    lo = run[0].lineno
    hi = run[-1].end_lineno or run[-1].lineno
    original_region = "".join(source.splitlines(keepends=True)[lo - 1:hi])
    # Already sorted when the render matches the original region (modulo the
    # trailing newline the splice re-attaches).
    if new_block == original_region.rstrip("\n"):
        return plan

    new_source = _splice(source, lo, hi, new_block)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: import sort would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(run)
    return plan
