"""fix not in is — rewrite ``not a in b`` to ``a not in b`` (E713/E714).

The classic readability cleanup: Python negates a membership/identity test in
two equivalent ways, and only one reads as English::

    not a in b      ->  a not in b      (E713)
    not a is b      ->  a is not b      (E714)

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.UnaryOp(op=ast.Not, operand=X)`` where ``X`` is an
    ``ast.Compare`` with EXACTLY ONE operator (``len(X.ops) == 1``) that is
    ``ast.In`` or ``ast.Is`` — chained compares (``not a in b in c``) and any
    other operator (``not a == b``, ``not a < b``) are left untouched;
  - the whole ``UnaryOp`` lives on a SINGLE line (``lineno == end_lineno``) so
    the column-span splice is trivially correct — multi-line ``UnaryOp`` nodes
    are skipped;
  - the replacement is rebuilt from the ORIGINAL source segments of the compare's
    left operand and its single comparator (so attribute/subscript operands and
    any inner formatting survive), joined with `` not in `` / `` is not ``. A
    redundant paren pair around the operand (``not (a in b)``) is dropped as a
    natural consequence — the splice replaces the entire ``UnaryOp`` span.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Conservative by design —
any source segment that can't be recovered skips that occurrence, and the
rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left (sorted by ``(lineno,
col_offset)`` descending) so earlier offsets stay valid even when two negations
share a line or one is nested in another. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fix_not_in_is"]


# The single-operator compare ops we negate, mapped to their negated text.
_NEGATED: dict[type[ast.cmpop], str] = {
    ast.In: " not in ",
    ast.Is: " is not ",
}


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded as a subject."""
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


def _try_unaryop(node: ast.UnaryOp, source: str) -> _Rewrite | None:
    """If ``node`` is ``not a in b`` / ``not a is b`` (single-operator), return
    its rewrite, else None."""
    if not isinstance(node.op, ast.Not):
        return None
    compare = node.operand
    if not isinstance(compare, ast.Compare):
        return None
    if len(compare.ops) != 1:  # chained compare — never a partial rewrite
        return None
    joiner = _NEGATED.get(type(compare.ops[0]))
    if joiner is None:  # not In/Is — leave == < etc. alone
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None

    left = ast.get_source_segment(source, compare.left)
    right = ast.get_source_segment(source, compare.comparators[0])
    if left is None or right is None:  # can't recover source — skip
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    f"{left}{joiner}{right}")


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every negated single-operator ``in``/``is`` compare in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp):
            rw = _try_unaryop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid (handles two on a line and one nested in another)."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: (r.lineno, r.col), reverse=True):
        line = lines[rw.lineno - 1]
        lines[rw.lineno - 1] = line[:rw.col] + rw.text + line[rw.end_col:]
    return "".join(lines)


def plan_fix_not_in_is(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module fix-not-in-is plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every
    ``not a in b`` to ``a not in b`` and ``not a is b`` to ``a is not b`` whose
    shape matches exactly (single operator, single line, recoverable operands).
    An empty plan (no new_contents, no blockers) means nothing matched — a no-op,
    not a failure."""
    plan = RenamePlan(old=module_rel, new="fix-not-in-is")
    if _is_fixture_path(module_rel):
        return plan
    path = Path(project_root) / module_rel
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

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: rewrite would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
