"""Edge-case coverage for app/execution/merge_nested_if.py.

Targets the conservative-skip branches and plan-level guards the canonical suite
leaves open:

  - the ``get_source_segment`` recovery-failure skip (line 109);
  - the non-positive dedent unit skip (line 115);
  - the ambiguous-dedent skip when an inner-body continuation line carries less
    indentation than the block (line 126);
  - the re-parse-failure blocker (lines 212-215);
  - the "merge changed nothing" early return (line 217).

Deterministic, stdlib-only; explicit AST/source inputs.
"""

from __future__ import annotations

import ast

import app.execution.merge_nested_if as mni
from app.execution.merge_nested_if import plan_merge_nested_if


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# --- ambiguous dedent: a continuation line indented below the block ------- #

def test_inner_body_continuation_under_indent_skipped(tmp_path):
    # The inner body's statement spills onto a line dedented past the block's
    # indent (the `2)` sits at column 0). The dedent would be ambiguous, so the
    # occurrence is skipped — an empty no-op plan, never a partial rewrite.
    src = "if a:\n    if b:\n        x = (1 +\n2)\n"
    _write(tmp_path, "app/m.py", src)
    plan = plan_merge_nested_if(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- get_source_segment recovery failure (line 109) ----------------------- #

def test_source_segment_none_skips_occurrence(monkeypatch):
    src = "if a:\n    if b:\n        body()\n"
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    outer = tree.body[0]
    monkeypatch.setattr(ast, "get_source_segment", lambda s, n: None)
    assert mni._try_if(outer, src, lines) is None


# --- non-positive dedent unit (line 115) ---------------------------------- #

def test_non_positive_dedent_unit_skips_occurrence():
    # When the inner body's first statement isn't indented past the inner ``if``
    # (unit <= 0), the merge is refused. We tamper the parsed node's column to
    # force the degenerate geometry the guard defends against.
    src = "if a:\n    if b:\n        body()\n"
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    outer = tree.body[0]
    inner = outer.body[0]
    inner.body[0].col_offset = inner.col_offset  # unit == 0
    assert mni._try_if(outer, src, lines) is None


# --- plan-level re-parse failure (lines 212-215) -------------------------- #

def test_merge_that_would_not_reparse_blocks(tmp_path, monkeypatch):
    src = "if a:\n    if b:\n        body()\n"
    _write(tmp_path, "app/m.py", src)
    monkeypatch.setattr(mni, "_apply", lambda source, rewrites: "def broken(:\n")
    plan = plan_merge_nested_if(str(tmp_path), "app/m.py")
    assert plan.blockers
    assert any("would not re-parse" in b for b in plan.blockers)
    assert not plan.new_contents


# --- plan-level "changed nothing" early return (line 217) ----------------- #

def test_merge_that_changes_nothing_is_noop(tmp_path, monkeypatch):
    # Rewrites are collected, but if applying them yields source identical to the
    # original the plan stays an empty no-op (no edit recorded, no blocker).
    src = "if a:\n    if b:\n        body()\n"
    _write(tmp_path, "app/m.py", src)
    monkeypatch.setattr(mni, "_apply", lambda source, rewrites: source)
    plan = plan_merge_nested_if(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok
