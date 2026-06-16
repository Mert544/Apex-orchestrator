"""Characterization tests pinning the refactor of ``_dead_span``.

These feed many source snippets through the transform's public ``apply`` path
and assert on the exact, observable output (rewrite string, skip conditions,
rationale). They lock the decomposition of ``_dead_span`` into pure helpers so
the byte-for-byte behaviour cannot drift.
"""

from __future__ import annotations

import ast

import pytest

from app.execution.semantic.transforms import unreachable_cleanup as uc


def _apply(src: str):
    return uc.apply("rel/p.py", src, "remove unreachable code")


def _content(src: str) -> str | None:
    r = _apply(src)
    return r.patch_requests[0]["new_content"] if r else None


# --- skip conditions (apply returns None) ---------------------------------

SKIP_CASES = [
    "def f():\n    return 1\n",  # terminator is the last statement
    "def f():\n    x = 1\n    return x\n",  # no dead tail
    "def f():\n    return 1\n    # comment\n    x = 2\n",  # comment in span
    "def f():\n    return 1  # trailing\n    x = 2  # tail\n",  # tail comment dead
    "def f():\n    return 1\n    def inner():\n        pass\n",  # nested def
    "def f():\n    return 1\n    async def g():\n        pass\n",  # nested async def
    "def f():\n    return 1\n    class C:\n        pass\n",  # nested class
    "def f():\n    return 1\n    global g\n",  # global binding
    "def f():\n    return 1\n    nonlocal y\n",  # nonlocal binding
    "x = 1\n",  # module-level only: no suites
    "",  # empty source
    "def (bad syntax\n",  # unparseable
]


@pytest.mark.parametrize("src", SKIP_CASES)
def test_apply_skips(src: str):
    assert _apply(src) is None


# --- removal cases (exact output preserved) -------------------------------

def _dump(src: str) -> str:
    return ast.dump(ast.parse(src))


def test_removes_single_dead_statement():
    out = _content("def f():\n    return 1\n    x = 2\n")
    assert out == "def f():\n    return 1\n"


def test_removes_multiple_dead_statements():
    out = _content("def f():\n    return 1\n    x = 2\n    y = 3\n    z = 4\n")
    assert out == "def f():\n    return 1\n"


def test_removes_after_raise_break_continue():
    assert _content("def f():\n    raise ValueError('x')\n    y = 2\n") == (
        "def f():\n    raise ValueError('x')\n"
    )
    assert _content("for i in r:\n    break\n    y = 2\n") == "for i in r:\n    break\n"
    assert _content("for i in r:\n    continue\n    y = 2\n") == (
        "for i in r:\n    continue\n"
    )


def test_blank_lines_and_multiline_terminator():
    # Blank lines after the terminator are swept up with the dead statement.
    assert _content("def f():\n    return 1\n\n    x = 2\n") == "def f():\n    return 1\n"
    # The span starts after the terminator's *last* physical line.
    out = _content("def f():\n    return (\n        1\n    )\n    x = 2\n")
    assert out == "def f():\n    return (\n        1\n    )\n"


def test_hash_inside_string_is_not_a_comment():
    src = "def f():\n    return 1\n    x = '# not a comment'\n"
    assert _content(src) == "def f():\n    return 1\n"


def test_rationale_and_transform_type_preserved():
    r = _apply("def f():\n    return 1\n    x = 2\n")
    assert r is not None
    assert r.transform_type == "remove_unreachable_code"
    assert r.rationale == [
        "Removed statically-unreachable statement(s) after an unconditional "
        "return/raise/break/continue in rel/p.py."
    ]
    pr = r.patch_requests[0]
    assert pr["path"] == "rel/p.py"
    assert pr["expected_old_content"] == "def f():\n    return 1\n    x = 2\n"


# --- pure-helper unit checks ----------------------------------------------

def _suite(src: str) -> list[ast.stmt]:
    return ast.parse(src).body[0].body


def test_terminator_index_helper():
    assert uc._terminator_index(_suite("def f():\n    return 1\n    x = 2\n")) == 0
    # Terminator already last -> None.
    assert uc._terminator_index(_suite("def f():\n    x = 1\n    return x\n")) is None
    # No terminator -> None.
    assert uc._terminator_index(_suite("def f():\n    x = 1\n    y = 2\n")) is None


def test_has_unsafe_stmt_helper():
    assert uc._has_unsafe_stmt(_suite("def f():\n    def g():\n        pass\n"))
    assert uc._has_unsafe_stmt(_suite("def f():\n    global z\n"))
    assert not uc._has_unsafe_stmt(_suite("def f():\n    x = 1\n    y = 2\n"))


def test_span_helpers():
    term, *dead = _suite("def f():\n    return 1\n    x = 2\n")
    assert uc._span_bounds(term, dead) == (3, 3)
    assert uc._span_has_comment((3, 3), {3})
    assert not uc._span_has_comment((3, 3), {5})
