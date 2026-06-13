"""Tests for the shared transform primitives in ``_transform_base``.

These cover the four helpers the single-module transforms extracted: the
fixture-path exclusion, the column-span splice, the line-span replace, and the
statement-block walker — including their edge and empty paths."""

from __future__ import annotations

import ast

from app.execution._transform_base import (
    apply_column_rewrites,
    apply_line_rewrites,
    is_fixture_path,
    iter_statement_blocks,
)


# ── is_fixture_path ─────────────────────────────────────────────────────────

def test_is_fixture_path_recognizes_subjects():
    assert is_fixture_path("tests/test_x.py")
    assert is_fixture_path("examples/demo.py")
    assert is_fixture_path("example/demo.py")
    assert is_fixture_path("pkg/fixtures/data.py")
    assert is_fixture_path("a/tests/helper.py")
    assert is_fixture_path("a/examples/b.py")
    assert is_fixture_path("pkg/test_helper.py")  # basename starts with test_


def test_is_fixture_path_rejects_real_code():
    assert not is_fixture_path("app/execution/bool_return.py")
    assert not is_fixture_path("app/calc.py")
    # "test" without a trailing underscore in the basename is not a fixture.
    assert not is_fixture_path("app/tester.py")


def test_is_fixture_path_normalizes_backslashes_and_case():
    assert is_fixture_path("Tests\\Test_X.py")
    assert is_fixture_path("PKG\\FIXTURES\\data.py")
    assert not is_fixture_path("App\\Calc.py")


# ── apply_column_rewrites ───────────────────────────────────────────────────

def test_column_rewrite_single():
    src = "y = isinstance(x, A) or isinstance(x, B)\n"
    # Replace the whole RHS expression span on line 1.
    out = apply_column_rewrites(src, [(1, 4, 40, "isinstance(x, (A, B))")])
    assert out == "y = isinstance(x, (A, B))\n"


def test_column_rewrite_two_on_one_line_right_to_left():
    # Two non-overlapping spans on the same line, given left-to-right; the helper
    # must apply right-to-left so the first splice doesn't shift the second.
    src = "AA BB\n"
    out = apply_column_rewrites(src, [(1, 0, 2, "x"), (1, 3, 5, "yy")])
    assert out == "x yy\n"


def test_column_rewrite_preserves_other_lines_and_no_trailing_newline():
    src = "a = 1\nfoo\nb = 2"  # last line has no trailing newline
    out = apply_column_rewrites(src, [(2, 0, 3, "BAR")])
    assert out == "a = 1\nBAR\nb = 2"


def test_column_rewrite_empty_is_identity():
    src = "anything\n"
    assert apply_column_rewrites(src, []) == src


# ── apply_line_rewrites ─────────────────────────────────────────────────────

def test_line_rewrite_collapses_span():
    src = "if c:\n    return True\nelse:\n    return False\n"
    out = apply_line_rewrites(src, [(1, 4, ["return bool(c)\n"])])
    assert out == "return bool(c)\n"


def test_line_rewrite_bottom_up_keeps_line_numbers_valid():
    src = "L1\nL2\nL3\nL4\n"
    # Two disjoint spans given low-first; the helper applies highest-lo first so
    # the lower span's indices stay valid.
    out = apply_line_rewrites(src, [(1, 2, ["A\n"]), (3, 4, ["B\n"])])
    assert out == "A\nB\n"


def test_line_rewrite_preserves_missing_trailing_newline():
    # The replacement carries no trailing newline, mirroring a source whose last
    # line had none — spliced verbatim.
    src = "x = []\nfor i in r:\n    x.append(i)"  # no trailing newline
    out = apply_line_rewrites(src, [(1, 3, ["x = [i for i in r]"])])
    assert out == "x = [i for i in r]"


def test_line_rewrite_empty_is_identity():
    src = "z = 0\n"
    assert apply_line_rewrites(src, []) == src


# ── iter_statement_blocks ───────────────────────────────────────────────────

def test_iter_statement_blocks_yields_every_block():
    src = (
        "x = 1\n"
        "def f():\n"
        "    if a:\n"
        "        b = 1\n"
        "    else:\n"
        "        c = 2\n"
        "    try:\n"
        "        d = 3\n"
        "    except ValueError:\n"
        "        e = 4\n"
        "    finally:\n"
        "        g = 5\n"
    )
    tree = ast.parse(src)
    blocks = list(iter_statement_blocks(tree))
    # module body, function body, if-body, if-orelse, try-body, except-body,
    # try-finalbody all appear; every yielded item is a non-empty stmt list.
    assert blocks
    assert all(b and all(isinstance(s, ast.stmt) for s in b) for b in blocks)
    # The module body (``x = 1`` + ``def f``) is among them.
    assert any(isinstance(b[0], ast.Assign) and isinstance(b[1], ast.FunctionDef)
               for b in blocks if len(b) == 2)
    # The except handler body (``e = 4``) is surfaced.
    assert any(len(b) == 1 and isinstance(b[0], ast.Assign)
               and isinstance(b[0].targets[0], ast.Name)
               and b[0].targets[0].id == "e" for b in blocks)


def test_iter_statement_blocks_empty_module():
    assert list(iter_statement_blocks(ast.parse(""))) == []
