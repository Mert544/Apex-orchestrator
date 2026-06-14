"""Extra edge-coverage for the remove-double-negation develop transform.

Targets the non-Not unary path, the multiline guard, the source-recovery
guards in ``_try_unaryop``, the re-parse-failure guard and the no-op early
return. Deterministic, stdlib-only, no network.
"""

from __future__ import annotations

import ast

from app.execution import remove_double_negation as mod
from app.execution.remove_double_negation import (
    _try_unaryop,
    plan_remove_double_negation,
)


def _project(tmp_path, body):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return "app/m.py"


def _rewrite(tmp_path, body):
    rel = _project(tmp_path, body)
    plan = plan_remove_double_negation(str(tmp_path), rel)
    return plan.new_contents.get(rel), plan


# --- _try_unaryop negative branches -------------------------------------

def test_non_not_unaryop_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "def f(x):\n    return -x\n")
    assert new is None
    assert not plan.blockers


def test_unary_invert_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "def f(x):\n    return ~x\n")
    assert new is None


def test_not_plain_name_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "def f(x):\n    return not x\n")
    assert new is None


def test_chained_compare_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "def f(a, b, c):\n    return not a == b == c\n")
    assert new is None


def test_ordering_op_untouched(tmp_path):
    # `not a < b` is not `a >= b` on floats/NaN -> intentionally left alone.
    new, plan = _rewrite(tmp_path, "def f(a, b):\n    return not a < b\n")
    assert new is None


def test_try_unaryop_multiline_returns_none():
    src = "not (\n  a == b)"
    node = ast.parse(src, mode="eval").body
    assert node.lineno != node.end_lineno
    assert _try_unaryop(node, src) is None


def test_try_unaryop_double_not_inner_unrecoverable_returns_none():
    # not not <operand without position> -> inner segment None.
    inner = ast.Name(id="x", ctx=ast.Load())  # no position info
    operand = ast.UnaryOp(op=ast.Not(), operand=inner)
    node = ast.UnaryOp(op=ast.Not(), operand=operand)
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 9
    assert _try_unaryop(node, "not not x") is None


def test_try_unaryop_compare_operand_unrecoverable_returns_none():
    # not (a == b) where left operand lacks position info -> left None.
    left = ast.Name(id="a", ctx=ast.Load())  # no position
    right = ast.Name(id="b", ctx=ast.Load(), lineno=1, col_offset=8,
                     end_lineno=1, end_col_offset=9)
    cmp = ast.Compare(left=left, ops=[ast.Eq()], comparators=[right])
    node = ast.UnaryOp(op=ast.Not(), operand=cmp)
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 12
    assert _try_unaryop(node, "not (a == b)") is None


# --- positive sanity (keeps the inverter table honest) ------------------

def test_double_not_becomes_bool(tmp_path):
    new, plan = _rewrite(tmp_path, "def f(x):\n    return not not x\n")
    assert "bool(x)" in new


# --- plan-level scaffolding guards --------------------------------------

def test_unreadable_path_blocks(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").mkdir()
    plan = plan_remove_double_negation(str(tmp_path), "app/m.py")
    assert plan.blockers == ["cannot read app/m.py"]
    assert not plan.new_contents


def test_reparse_failure_blocks(tmp_path, monkeypatch):
    rel = _project(tmp_path, "def f(a, b):\n    return not (a == b)\n")
    monkeypatch.setattr(mod, "_apply", lambda s, r: "def f(:\n")
    plan = plan_remove_double_negation(str(tmp_path), rel)
    assert plan.blockers
    assert "would not re-parse" in plan.blockers[0]
    assert not plan.new_contents


def test_apply_noop_returns_empty_plan(tmp_path, monkeypatch):
    body = "def f(a, b):\n    return not (a == b)\n"
    rel = _project(tmp_path, body)
    monkeypatch.setattr(mod, "_apply", lambda s, r: body)
    plan = plan_remove_double_negation(str(tmp_path), rel)
    assert not plan.new_contents
    assert not plan.blockers
