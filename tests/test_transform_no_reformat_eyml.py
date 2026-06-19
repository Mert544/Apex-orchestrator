"""Red-team regression: the three AST-rewriting semantic transforms that route
through ``run_rewrite_transformer`` must NOT reformat the whole file.

The shared driver used to ``ast.unparse`` the entire module, which silently
deleted every comment (including ``# type: ignore`` / ``# noqa`` /
``# pyright: ignore`` pragmas that change lint/type-check behaviour), flipped
quote styles and collapsed blank lines — turning an advertised one-line edit
into a file-wide reformat. The driver is now a surgical span splice: only the
bytes of the changed construct are replaced.

These tests pin, for ``augmented_assign``, ``chained_comparison`` and
``startswith_tuple``:

* every comment in the original source survives the apply;
* every line that is NOT the rewritten construct is byte-for-byte identical;
* exactly the target construct changed; and
* the rewrites stay deterministic.

Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import augmented_assign as aug
from app.execution.semantic.transforms import chained_comparison as chain
from app.execution.semantic.transforms import startswith_tuple as sw

REL = "pkg/mod.py"


# --- harness ----------------------------------------------------------------


def _aug(src: str) -> str | None:
    r = aug.apply(REL, src)
    return r.patch_requests[0]["new_content"] if r else None


def _chain(src: str) -> str | None:
    r = chain.apply(REL, src, "t")
    return r.patch_requests[0]["new_content"] if r else None


def _sw(src: str) -> str | None:
    r = sw.apply(REL, src, "t")
    return r.patch_requests[0]["new_content"] if r else None


def _comments(src: str) -> list[str]:
    """Every ``#``-comment text in ``src`` (verbatim, in order)."""
    out: list[str] = []
    for line in src.splitlines():
        idx = line.find("#")
        if idx != -1:
            out.append(line[idx:])
    return out


def _assert_only_target_lines_changed(before: str, after: str, target_substr: str) -> None:
    """Lines not containing ``target_substr`` must be byte-identical before/after,
    and the line count must be unchanged (no blank-line collapsing)."""
    bl = before.splitlines(keepends=True)
    al = after.splitlines(keepends=True)
    assert len(bl) == len(al), (bl, al)
    for b, a in zip(bl, al):
        if target_substr in b:
            continue  # the rewritten construct's own line(s) may differ
        assert b == a, (b, a)


# --- augmented_assign -------------------------------------------------------


def test_aug_preserves_all_comments_and_nontarget_lines():
    before = (
        "import os  # noqa: F401\n"
        "\n"
        "# running total\n"
        "x = compute()  # type: ignore[no-any-return]\n"
        "x = x + 1  # bump the counter\n"
        "\n"
        "y = other()  # pyright: ignore[reportGeneralTypeIssues]\n"
    )
    after = _aug(before)
    assert after is not None
    # The single target construct changed...
    assert "x += 1" in after
    assert "x = x + 1" not in after
    # ...and every comment survived (the unparse used to drop all of these).
    assert _comments(after) == _comments(before)
    # ...and only the target line differs.
    _assert_only_target_lines_changed(before, after, "x = x + 1")
    # The target's own trailing comment is also preserved by the span splice.
    assert "# bump the counter" in after
    ast.parse(after)


def test_aug_preserves_quote_style_and_blank_lines_elsewhere():
    before = (
        'NAME = "kept double quotes"\n'
        "\n\n"
        "total = total * factor\n"
        "\n"
        "OTHER = 'kept single quotes'\n"
    )
    after = _aug(before)
    assert after is not None
    assert "total *= factor" in after
    assert 'NAME = "kept double quotes"\n' in after
    assert "OTHER = 'kept single quotes'\n" in after
    # blank lines (including the double blank) are not collapsed
    assert "\n\n\n" in after


def test_aug_refused_input_with_comments_is_unchanged():
    # An unsafe shape (name on the right) must still refuse, comments intact.
    assert _aug("x = 1 + x  # do not touch\n") is None


# --- chained_comparison -----------------------------------------------------


def test_chain_preserves_all_comments_and_nontarget_lines():
    before = (
        "from typing import Any  # noqa\n"
        "\n"
        "lo = 0  # type: ignore\n"
        "ok = a < b and b < c  # merge me\n"
        "hi = 10  # pyright: ignore\n"
    )
    after = _chain(before)
    assert after is not None
    assert "a < b < c" in after
    assert "a < b and b < c" not in after
    assert _comments(after) == _comments(before)
    _assert_only_target_lines_changed(before, after, "a < b")
    assert "# merge me" in after
    ast.parse(after)


def test_chain_nested_double_chain_keeps_comments():
    before = "w = (a < b and b < c) and (p < q and q < r)  # both inner chains\n"
    after = _chain(before)
    assert after is not None
    assert "a < b < c" in after
    assert "p < q < r" in after
    assert _comments(after) == ["# both inner chains"]
    ast.parse(after)


def test_chain_refused_input_with_comments_is_unchanged():
    assert _chain("v = a < b and b > c  # mixed direction\n") is None


# --- startswith_tuple -------------------------------------------------------


def test_sw_preserves_all_comments_and_nontarget_lines():
    before = (
        "import re  # noqa: F401\n"
        "\n"
        "PREFIX = 'a'  # type: ignore\n"
        "hit = s.startswith('a') or s.startswith('b')  # collapse\n"
        "SUFFIX = 'b'  # pyright: ignore\n"
    )
    after = _sw(before)
    assert after is not None
    assert "startswith(('a', 'b'))" in after
    assert "s.startswith('a') or s.startswith('b')" not in after
    assert _comments(after) == _comments(before)
    _assert_only_target_lines_changed(before, after, "startswith('a')")
    assert "# collapse" in after
    ast.parse(after)


def test_sw_refused_input_with_comments_is_unchanged():
    assert _sw("z = s.startswith('a') or s.endswith('b')  # mixed methods\n") is None


# --- cross-cutting: determinism --------------------------------------------


def test_all_three_are_deterministic_with_comments():
    samples = [
        (_aug, "x = x + 1  # c\ny = compute()  # type: ignore\n"),
        (_chain, "ok = a < b and b < c  # c\nz = 1  # noqa\n"),
        (_sw, "h = s.startswith('a') or s.startswith('b')  # c\nz = 1  # noqa\n"),
    ]
    for fn, src in samples:
        first = fn(src)
        assert first is not None
        for _ in range(4):
            assert fn(src) == first


def test_no_target_with_only_comments_returns_none():
    # A file that is all comments / unrelated code has nothing to rewrite, so
    # every transform refuses (and therefore trivially preserves the file).
    src = "# just a comment\nx = 1  # type: ignore\n"
    assert _aug(src) is None
    assert _chain(src) is None
    assert _sw(src) is None
