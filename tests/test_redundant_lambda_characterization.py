"""Characterization tests pinning ``apply``'s byte-exact rewrite behaviour.

These guard the decomposition of ``apply`` into pure helpers: the rewritten
output, the skip conditions and the refusal cases must stay identical.
"""

from __future__ import annotations

import pytest

from app.execution.semantic.transforms import redundant_lambda as rl

# Snippets that SHOULD be rewritten, paired with their exact expected output.
_REWRITES = [
    ("sorted(xs, key=lambda x: g(x))\n", "sorted(xs, key=g)\n"),
    ("sorted(xs, key=lambda a, b: g(a, b))\n", "sorted(xs, key=g)\n"),
    ("f = lambda x: mod.fn(x)\n", "f = mod.fn\n"),
    ("f = lambda x: a.b.c(x)\n", "f = a.b.c\n"),
    ("if z:\n    cb = lambda e: handler(e)\n", "if z:\n    cb = handler\n"),
    ("f = lambda a, b, c: fn(a, b, c)\n", "f = fn\n"),
    # No trailing newline — splice stays exact.
    ("sorted(xs, key=lambda x: g(x))", "sorted(xs, key=g)"),
    # Two on one line: rightmost-first splice keeps columns valid for both.
    ("a(lambda x: f(x)); b(lambda y: h(y))\n", "a(f); b(h)\n"),
    # Two on separate lines.
    ("p = lambda x: f(x)\nq = lambda y: g(y)\n", "p = f\nq = g\n"),
]

# Snippets that must be REFUSED (``apply`` returns ``None``).
_REFUSALS = [
    "sorted(xs, key=lambda x: g(x, 1))\n",      # extra positional arg
    "sorted(xs, key=lambda a, b: g(b, a))\n",   # wrong order
    "sorted(xs, key=lambda a, b: g(a))\n",      # too few args
    "sorted(xs, key=lambda x: g(x, k=1))\n",    # keyword arg
    "sorted(xs, key=lambda *a: g(*a))\n",       # *args param
    "sorted(xs, key=lambda x=1: g(x))\n",       # default
    "sorted(xs, key=lambda x: factory()(x))\n",  # callable is a call
    "sorted(xs, key=lambda x: tbl[0](x))\n",    # callable is a subscript
    "key=lambda x: x.lower\n",                    # body is attribute, not call
    "lambda x: x\n",                              # body is a Name
    "lambda: g()\n",                              # no params
    "f = lambda x: g(\n    x)\n",                # multi-line lambda — skipped
    "f = lambda a: fn(*a)\n",                    # starred call arg
    "f = lambda *, x: fn(x)\n",                  # keyword-only param
    "def (:\n",                                   # syntax error
    "x = 1 + 2\n",                                # no lambda at all
    "sorted(xs, key=g)\n",                        # already applied
    "",                                            # empty source
    "\n\n\n",                                      # blank lines only
]


@pytest.mark.parametrize("source,expected", _REWRITES)
def test_rewrite_output_is_exact(source: str, expected: str) -> None:
    result = rl.apply("p.py", source, "t")
    assert result is not None
    req = result.patch_requests[0]
    assert req["new_content"] == expected
    assert req["expected_old_content"] == source
    assert req["path"] == "p.py"
    assert result.transform_type == "drop_redundant_lambda"


@pytest.mark.parametrize("source", _REFUSALS)
def test_refusals_return_none(source: str) -> None:
    assert rl.apply("p.py", source, "t") is None


def test_rationale_reports_change_count() -> None:
    source = "p = lambda x: f(x)\nq = lambda y: g(y)\n"
    result = rl.apply("p.py", source, "t")
    assert result is not None
    assert "Removed 2 redundant forwarding lambda(s)" in result.rationale[0]


def test_mixed_line_rewrites_one_keeps_one() -> None:
    # One forwarding lambda (rewritten) and one refusal share a line.
    source = "m(lambda x: f(x), lambda y: g(y, 1))\n"
    result = rl.apply("p.py", source, "t")
    assert result is not None
    assert result.patch_requests[0]["new_content"] == "m(f, lambda y: g(y, 1))\n"


def test_spliced_line_skips_multiline_node() -> None:
    import ast

    node = ast.parse("g(\n    x)").body[0].value  # a Call, lineno != end_lineno
    # Wrap into something with differing line span via a real lambda node.
    lam = next(
        n for n in ast.walk(ast.parse("f = lambda x: g(\n    x)"))
        if isinstance(n, ast.Lambda)
    )
    lines = "f = lambda x: g(\n    x)".splitlines(keepends=True)
    assert rl._spliced_line(lines, lam) is None
    assert node is not None  # silence unused
