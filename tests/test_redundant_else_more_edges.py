"""Extra edge-coverage for the remove-redundant-else develop transform.

Targets the ambiguous-else-header guard, the non-positive dedent-unit guard,
the per-line dedent-pad guard, the re-parse-failure guard and the no-op early
return. Deterministic, stdlib-only, no network.
"""

from __future__ import annotations

import ast

from app.execution import redundant_else as mod
from app.execution.redundant_else import (
    _find_else_line,
    _try_if,
    plan_remove_redundant_else,
)


def _project(tmp_path, body):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return "app/m.py"


def _rewrite(tmp_path, body):
    rel = _project(tmp_path, body)
    plan = plan_remove_redundant_else(str(tmp_path), rel)
    return plan.new_contents.get(rel), plan


# --- _find_else_line guards ---------------------------------------------

def test_find_else_line_single_match():
    lines = ["a\n", "b\n", "    else:\n", "c\n"]
    assert _find_else_line(lines, 1, 4) == 3


def test_find_else_line_none_when_absent():
    lines = ["a\n", "b\n", "c\n"]
    assert _find_else_line(lines, 1, 3) is None


def test_find_else_line_ambiguous_two_headers_returns_none():
    # Two lines stripping to exactly ``else:`` in the open span -> ambiguous.
    lines = ["if c:\n", "    return 1\n", "    else:\n", "    else:\n",
             "    body\n"]
    assert _find_else_line(lines, 2, 5) is None


# --- _try_if guards -----------------------------------------------------

def test_try_if_no_orelse_returns_none():
    stmt = ast.parse("if c:\n    return 1\n").body[0]
    assert _try_if(stmt, ["if c:\n", "    return 1\n"]) is None


def test_try_if_body_not_terminal_returns_none():
    src = "if c:\n    x = 1\nelse:\n    return 2\n"
    stmt = ast.parse(src).body[0]
    assert _try_if(stmt, src.splitlines(keepends=True)) is None


def test_try_if_non_positive_unit_returns_none():
    # Build an If whose else-body column is not deeper than the if column so
    # the dedent unit is <= 0 -> skipped (defensive guard).
    ret = ast.Return(value=ast.Constant(value=1, lineno=2, col_offset=4,
                                        end_lineno=2, end_col_offset=5),
                     lineno=2, col_offset=0, end_lineno=2, end_col_offset=5)
    els = ast.Pass(lineno=4, col_offset=0, end_lineno=4, end_col_offset=4)
    stmt = ast.If(test=ast.Name(id="c", ctx=ast.Load(), lineno=1,
                                col_offset=3, end_lineno=1, end_col_offset=4),
                  body=[ret], orelse=[els],
                  lineno=1, col_offset=0, end_lineno=4, end_col_offset=4)
    lines = ["if c:\n", "    return 1\n", "else:\n", "pass\n"]
    assert _try_if(stmt, lines) is None


def test_else_body_line_lacking_pad_skipped(tmp_path):
    # A multiline string in the else-body has an interior line with no leading
    # spaces, so the dedent would be ambiguous -> the occurrence is skipped.
    body = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    else:\n"
        '        s = """\n'
        "abc\n"
        '"""\n'
        "        return s\n"
    )
    new, plan = _rewrite(tmp_path, body)
    assert new is None
    assert not plan.blockers


# --- positive sanity ----------------------------------------------------

def test_basic_redundant_else_flattened(tmp_path):
    body = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
    )
    new, plan = _rewrite(tmp_path, body)
    assert new is not None
    assert "else:" not in new
    ast.parse(new)


# --- plan-level scaffolding guards --------------------------------------

def test_unreadable_path_blocks(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").mkdir()
    plan = plan_remove_redundant_else(str(tmp_path), "app/m.py")
    assert plan.blockers == ["cannot read app/m.py"]
    assert not plan.new_contents


def test_reparse_failure_blocks(tmp_path, monkeypatch):
    rel = _project(
        tmp_path,
        "def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n")
    monkeypatch.setattr(mod, "_apply", lambda s, r: "def f(:\n")
    plan = plan_remove_redundant_else(str(tmp_path), rel)
    assert plan.blockers
    assert "would not re-parse" in plan.blockers[0]
    assert not plan.new_contents


def test_apply_noop_returns_empty_plan(tmp_path, monkeypatch):
    body = "def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n"
    rel = _project(tmp_path, body)
    monkeypatch.setattr(mod, "_apply", lambda s, r: body)
    plan = plan_remove_redundant_else(str(tmp_path), rel)
    assert not plan.new_contents
    assert not plan.blockers
