"""fix assert-on-tuple — rewrite ``assert (cond, "msg")`` to ``assert cond, "msg"``.

This is the classic always-true assert typo: ``assert (cond, "msg")`` parses as
``assert <2-tuple>`` — a non-empty tuple, which is ALWAYS truthy — so the
assertion silently never fires. The author meant ``assert cond, "msg"`` (a test
with a failure message). The detector (``app/engine/detectors.py``) already flags
this as "assert on a tuple is always true — remove the parentheses"; this
transform closes the detect>>act gap by actually fixing it.

Unlike the equivalence-preserving refactors that live beside it, this is a
**bug fix**: it CHANGES behaviour, on purpose, from "always passes" (the no-op
bug) to "actually checks the condition". The original code never did what it
read as doing, so there is no behaviour worth preserving — the safety here is
the conservative shape-match plus the re-parse guard.

Apex rewrites ONLY the exact, unambiguous classic typo and nothing else:

  - the node is an ``ast.Assert`` whose ``msg`` is ``None`` (an
    ``assert (a, b), c`` that already has a real message is left alone) and whose
    ``test`` is an ``ast.Tuple`` with EXACTLY 2 elements where the SECOND element
    is a plain string ``ast.Constant`` — the classic ``assert (cond, "msg")``
    shape. A tuple with a different element count (empty, 1-tuple, 3-tuple), a
    2-tuple whose second element is not a plain ``str`` constant (a deliberate
    tuple value being asserted, or an f-string we can't safely splice), is
    skipped;
  - the whole ``Assert`` lives on a SINGLE line (``lineno == end_lineno``) so the
    column-span splice is trivially correct — multi-line asserts are skipped;
  - the FIRST tuple element (the intended condition) is NOT itself a tuple or a
    starred expression — splicing a bare tuple beside ``assert`` would re-create
    the very bug, and a starred element is not a valid standalone test;
  - the replacement is rebuilt from the ORIGINAL source segments of the condition
    and the message constant (so any inner formatting survives), joined as
    ``assert <cond>, <msg>``. A redundant paren pair around the original tuple is
    dropped as a natural consequence — the splice replaces the whole ``Assert``
    statement span.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Conservative by design —
any source segment that can't be recovered skips that occurrence, and the
rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left (handled by
``apply_column_rewrites``) so earlier offsets stay valid. Deterministic,
stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    is_fixture_path,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fix_assert_tuple"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _is_plain_str_constant(node: ast.expr) -> bool:
    """True if ``node`` is a plain ``str`` literal (``ast.Constant`` whose value
    is a ``str``) — NOT an f-string (``ast.JoinedStr``) or bytes/other constant."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _try_assert(node: ast.Assert, source: str) -> _Rewrite | None:
    """If ``node`` is the classic ``assert (cond, "msg")`` typo, return its
    rewrite, else None."""
    if node.msg is not None:  # `assert (a, b), c` — already has a real message
        return None
    test = node.test
    if not isinstance(test, ast.Tuple):
        return None
    if len(test.elts) != 2:  # only the classic 2-tuple (cond, "msg") shape
        return None
    cond, msg = test.elts
    if not _is_plain_str_constant(msg):  # 2nd element must be a plain str literal
        return None
    # The condition is spliced beside `assert` (a full-test context), but a bare
    # tuple there would re-create the bug and a starred expr is not a valid test.
    if isinstance(cond, (ast.Tuple, ast.Starred)):
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None

    cond_src = ast.get_source_segment(source, cond)
    msg_src = ast.get_source_segment(source, msg)
    if cond_src is None or msg_src is None:  # can't recover source — skip
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    f"assert {cond_src}, {msg_src}")


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every classic always-true ``assert (cond, "msg")`` tuple typo in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            rw = _try_assert(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_fix_assert_tuple(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module fix-assert-tuple plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every classic
    ``assert (cond, "msg")`` always-true tuple typo to a real ``assert cond,
    "msg"`` whose shape matches exactly (2-tuple, plain-string second element, no
    existing message, single line, splice-safe condition, recoverable segments).
    An empty plan (no new_contents, no blockers) means nothing matched — a no-op,
    not a failure.

    This is a behaviour-CHANGING bug fix: the original assert always passed; the
    rewritten one actually checks the condition. The conservative shape-match plus
    the re-parse guard are the safety."""
    plan = RenamePlan(old=module_rel, new="fix-assert-tuple")
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
