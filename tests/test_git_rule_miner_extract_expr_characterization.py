"""Characterization tests for the pure helpers extracted from _extract_expr.

_extract_expr was decomposed into three pure helpers: _is_expr (does a string
parse in eval mode), _stmt_value (pick the unwrappable value node of a single
statement), and _unwrap_statement (parse + unwrap + slice source).  These tests
pin the exact behavior across every branch the original monolith covered:
bare expressions, return/assign/annassign/expr unwrapping, and rejection paths.
"""

from __future__ import annotations

import ast

from app.engine.git_rule_miner import (
    _extract_expr,
    _is_expr,
    _stmt_value,
    _unwrap_statement,
)


# --- _is_expr ----------------------------------------------------------------

def test_is_expr_true_for_bare_expression():
    assert _is_expr("len(xs) == 0") is True


def test_is_expr_false_for_statement():
    assert _is_expr("x = 5") is False


def test_is_expr_false_for_syntax_error():
    assert _is_expr("1 + ") is False


def test_is_expr_false_for_empty():
    assert _is_expr("") is False


# --- _stmt_value -------------------------------------------------------------

def _first_stmt(src: str) -> ast.stmt:
    return ast.parse(src, mode="exec").body[0]


def test_stmt_value_return_with_value():
    val = _stmt_value(_first_stmt("return foo"))
    assert isinstance(val, ast.Name) and val.id == "foo"


def test_stmt_value_bare_return_is_none():
    assert _stmt_value(_first_stmt("return")) is None


def test_stmt_value_assign():
    val = _stmt_value(_first_stmt("x = a + b"))
    assert isinstance(val, ast.BinOp)


def test_stmt_value_annassign_with_value():
    val = _stmt_value(_first_stmt("x: int = 5"))
    assert isinstance(val, ast.Constant) and val.value == 5


def test_stmt_value_annassign_without_value_is_none():
    assert _stmt_value(_first_stmt("x: int")) is None


def test_stmt_value_expr_statement():
    val = _stmt_value(_first_stmt("cache.clear()"))
    assert isinstance(val, ast.Call)


def test_stmt_value_other_statement_is_none():
    assert _stmt_value(_first_stmt("import os")) is None
    assert _stmt_value(_first_stmt("pass")) is None


# --- _unwrap_statement -------------------------------------------------------

def test_unwrap_statement_return():
    assert _unwrap_statement("return len(xs) == 0") == "len(xs) == 0"


def test_unwrap_statement_assign():
    assert _unwrap_statement("x = a + b") == "a + b"


def test_unwrap_statement_syntax_error_is_none():
    assert _unwrap_statement("x = (") is None


def test_unwrap_statement_multibody_is_none():
    assert _unwrap_statement("if True: pass") is None


def test_unwrap_statement_unhandled_form_is_none():
    assert _unwrap_statement("del x") is None


# --- _extract_expr end-to-end ------------------------------------------------

def test_extract_expr_bare_expression_fast_path():
    assert _extract_expr("  len(xs) == 0  ") == "len(xs) == 0"


def test_extract_expr_unwraps_return():
    assert _extract_expr("    return not xs") == "not xs"


def test_extract_expr_unwraps_assign():
    assert _extract_expr("x = a + b") == "a + b"


def test_extract_expr_unwraps_annassign():
    assert _extract_expr("x: int = a + b") == "a + b"


def test_extract_expr_expr_statement_call():
    assert _extract_expr("cache.clear()") == "cache.clear()"


def test_extract_expr_rejects_bare_return():
    assert _extract_expr("return") is None


def test_extract_expr_rejects_annassign_without_value():
    assert _extract_expr("x: int") is None


def test_extract_expr_rejects_unhandled_statement():
    assert _extract_expr("import os") is None
    assert _extract_expr("pass") is None


def test_extract_expr_rejects_syntax_error():
    assert _extract_expr("1 + ") is None


def test_extract_expr_rejects_multi_statement_body():
    assert _extract_expr("if True: pass") is None


def test_extract_expr_empty_input_is_none():
    assert _extract_expr("") is None
