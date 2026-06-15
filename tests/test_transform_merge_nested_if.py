from __future__ import annotations

import ast
import itertools

from app.execution.semantic.transforms import merge_nested_if as m


def _apply(src: str) -> str | None:
    r = m.apply("mod.py", src, "merge nested if")
    if r is None:
        return None
    # Contract sanity: a result is a single patch carrying the rewritten file.
    assert r.transform_type == "merge_nested_if"
    assert len(r.patch_requests) == 1
    req = r.patch_requests[0]
    assert req["path"] == "mod.py"
    assert req["expected_old_content"] == src
    return req["new_content"]


# --------------------------------------------------------------------------- #
# Mergeable cases
# --------------------------------------------------------------------------- #

def test_basic_merge_produces_and():
    out = _apply("def f(a, b):\n    if a:\n        if b:\n            return 1\n")
    assert out == "def f(a, b):\n    if (a) and (b):\n        return 1\n"
    ast.parse(out)


def test_merge_reparses_and_is_single_if():
    out = _apply("if a:\n    if b:\n        x = 1\n")
    assert out is not None
    tree = ast.parse(out)
    ifs = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
    assert len(ifs) == 1
    assert isinstance(ifs[0].test, ast.BoolOp)
    assert isinstance(ifs[0].test.op, ast.And)
    assert not ifs[0].orelse


def test_precedence_preserved_with_parens():
    # `if a or c:` must NOT become `a or c and b` (wrong precedence).
    out = _apply("if a or c:\n    if b:\n        x = 1\n")
    assert out == "if (a or c) and (b):\n    x = 1\n"
    ast.parse(out)


def test_multiline_body_dedented_correctly():
    out = _apply("if a:\n    if b:\n        x = 1\n        y = 2\n        z = 3\n")
    assert out == "if (a) and (b):\n    x = 1\n    y = 2\n    z = 3\n"
    ast.parse(out)


def test_blank_lines_in_body_preserved():
    out = _apply("if a:\n    if b:\n        x = 1\n\n        y = 2\n")
    assert out == "if (a) and (b):\n    x = 1\n\n    y = 2\n"
    ast.parse(out)


def test_only_topmost_pair_merges_per_call():
    # Triple nesting: only the outermost pair collapses; inner `if c` stays.
    out = _apply("if a:\n    if b:\n        if c:\n            x = 1\n")
    assert out == "if (a) and (b):\n    if c:\n        x = 1\n"
    ast.parse(out)


def test_semantically_equivalent_including_short_circuit():
    template = (
        "calls = []\n"
        "def A():\n    calls.append('A'); return a_val\n"
        "def B():\n    calls.append('B'); return b_val\n"
        "ran = False\n"
        "if A():\n    if B():\n        ran = True\n"
    )
    merged = _apply(template)
    assert merged is not None
    for a_val, b_val in itertools.product([True, False], repeat=2):
        g1: dict = {"a_val": a_val, "b_val": b_val}
        g2: dict = {"a_val": a_val, "b_val": b_val}
        exec(template, g1)
        exec(merged, g2)
        assert g1["calls"] == g2["calls"], (a_val, b_val)
        assert g1["ran"] == g2["ran"], (a_val, b_val)


# --------------------------------------------------------------------------- #
# Refusal cases  (every one must return None)
# --------------------------------------------------------------------------- #

def test_refuses_inner_else():
    assert _apply("if a:\n    if b:\n        x = 1\n    else:\n        x = 2\n") is None


def test_refuses_inner_elif():
    assert _apply("if a:\n    if b:\n        x = 1\n    elif c:\n        x = 3\n") is None


def test_refuses_outer_else():
    assert _apply("if a:\n    if b:\n        x = 1\nelse:\n    x = 9\n") is None


def test_refuses_outer_trailing_statement():
    assert _apply("if a:\n    if b:\n        x = 1\n    y = 2\n") is None


def test_refuses_outer_leading_statement():
    assert _apply("if a:\n    pre = 1\n    if b:\n        x = 1\n") is None


def test_refuses_comment_between_headers():
    assert _apply("if a:\n    # keep me\n    if b:\n        x = 1\n") is None


def test_refuses_blank_line_between_headers():
    assert _apply("if a:\n\n    if b:\n        x = 1\n") is None


def test_refuses_when_inner_is_not_an_if():
    assert _apply("if a:\n    x = 1\n") is None
    assert _apply("if a:\n    while b:\n        x = 1\n") is None


def test_refuses_outer_with_two_children():
    assert _apply("if a:\n    if b:\n        x = 1\n    if c:\n        x = 2\n") is None


def test_refuses_syntax_error_returns_none():
    assert _apply("def f(:\n    pass\n") is None
    assert _apply("if a\n    if b:\n        x = 1\n") is None


def test_refuses_inline_inner_body_header():
    # `if b: x = 1` keeps the inner body on the header line; splice would be unsafe.
    assert _apply("if a:\n    if b: x = 1\n") is None


def test_refuses_walrus_in_outer_condition():
    # Conservative: the parenthesised named-expression span is not proven safe.
    assert _apply("if (n := f()):\n    if n > 0:\n        x = 1\n") is None


def test_no_target_returns_none():
    assert _apply("x = 1\ny = 2\n") is None
    assert _apply("") is None


# --------------------------------------------------------------------------- #
# Robustness invariants
# --------------------------------------------------------------------------- #

def test_deterministic_same_input_same_output():
    src = "if a:\n    if b:\n        return 1\n"
    assert _apply(src) == _apply(src)


def test_idempotent_no_second_merge():
    src = "if a:\n    if b:\n        x = 1\n"
    once = _apply(src)
    assert once is not None
    assert _apply(once) is None


def test_never_emits_unparseable_output():
    samples = [
        "if a:\n    if b:\n        x = 1\n",
        "def f(a, b):\n    if a:\n        if b:\n            return a + b\n",
        "if a or c:\n    if b and d:\n        x = 1\n        y = 2\n",
        "class C:\n    def m(self):\n        if self.a:\n            if self.b:\n                self.x = 1\n",
        "if a:\n    if b:\n        x = 1\n    else:\n        x = 2\n",  # refused
        "if a:\n    pre = 1\n    if b:\n        x = 1\n",            # refused
        "x = 1\n",                                                   # no target
    ]
    for src in samples:
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # must always parse when a patch is produced
