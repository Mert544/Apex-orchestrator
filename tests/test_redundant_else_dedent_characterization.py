"""Characterization tests pinning ``_dedent_else`` byte-for-byte.

These golden cases were captured before ``_dedent_else`` was decomposed into
pure helpers and must remain identical: each exercises the apply path end to
end (convertible rewrites and must-NOT-convert skips), asserting the exact
emitted ``new_content`` (or ``None``).
"""
from __future__ import annotations

from app.execution.semantic.transforms import redundant_else


def _run(src: str) -> str | None:
    result = redundant_else.apply("f.py", src, "title")
    if result is None:
        return None
    return result.patch_requests[0]["new_content"]


# (name, source, expected new_content-or-None)
GOLDEN: list[tuple[str, str, str | None]] = [
    ("conv_basic",
     "if x:\n    return 1\nelse:\n    print('a')\n",
     "if x:\n    return 1\nprint('a')\n"),
    ("conv_nested",
     "def f():\n    if a:\n        return 1\n    else:\n"
     "        if b:\n            c()\n        d()\n",
     "def f():\n    if a:\n        return 1\n    if b:\n"
     "        c()\n    d()\n"),
    ("conv_blank_gap",
     "if x:\n    return 1\nelse:\n\n    a()\n",
     "if x:\n    return 1\n\na()\n"),
    ("conv_blank_in_body",
     "if x:\n    return 1\nelse:\n    a()\n\n    b()\n",
     "if x:\n    return 1\na()\n\nb()\n"),
    ("conv_tab_step",
     "if x:\n\treturn 1\nelse:\n\tprint('a')\n",
     "if x:\n\treturn 1\nprint('a')\n"),
    ("conv_raise",
     "def f():\n    if a:\n        raise ValueError('x')\n    else:\n        return 0\n",
     "def f():\n    if a:\n        raise ValueError('x')\n    return 0\n"),
    ("conv_continue",
     "for i in r:\n    if x:\n        continue\n    else:\n        do(i)\n",
     "for i in r:\n    if x:\n        continue\n    do(i)\n"),
    ("conv_break",
     "while x:\n    if y:\n        break\n    else:\n        step()\n",
     "while x:\n    if y:\n        break\n    step()\n"),
    ("conv_no_trailing_newline",
     "if x:\n    return 1\nelse:\n    a()",
     "if x:\n    return 1\na()"),
    ("conv_overindented_body",
     "if x:\n    return 1\nelse:\n        a()\n",
     "if x:\n    return 1\n    a()\n"),
    ("skip_no_else", "if x:\n    return 1\n", None),
    ("skip_elif",
     "if x:\n    return 1\nelif y:\n    return 2\nelse:\n    a()\n", None),
    ("skip_comment_gap",
     "if x:\n    return 1\nelse:\n    # c\n    a()\n", None),
    ("skip_nonterminating",
     "if x:\n    y = 1\nelse:\n    a()\n", None),
    ("skip_terminator_not_last",
     "if x:\n    return 1\n    y = 2\nelse:\n    a()\n", None),
    ("skip_nested_terminator",
     "if x:\n    if y:\n        return 1\nelse:\n    a()\n", None),
    ("skip_loop_nested_terminator",
     "if x:\n    for i in r:\n        return 1\nelse:\n    a()\n", None),
    ("skip_syntax_error", "if x\n    return 1\n", None),
    ("skip_empty", "", None),
]


def test_golden_outputs_byte_identical() -> None:
    for name, src, expected in GOLDEN:
        assert _run(src) == expected, name


def test_determinism_repeated_apply() -> None:
    src = "if x:\n    return 1\nelse:\n    a()\n    b()\n"
    first = _run(src)
    assert first == _run(src) == _run(src)


def test_first_eligible_if_chosen() -> None:
    src = ("if a:\n    return 1\nelse:\n    p()\n"
           "if b:\n    return 2\nelse:\n    q()\n")
    out = _run(src)
    # Only the first if's else is flattened; the second is untouched.
    assert out == ("if a:\n    return 1\np()\n"
                   "if b:\n    return 2\nelse:\n    q()\n")


def test_result_re_parses_and_metadata() -> None:
    import ast

    result = redundant_else.apply(
        "pkg/mod.py", "if x:\n    return 1\nelse:\n    a()\n", "title")
    assert result is not None
    ast.parse(result.patch_requests[0]["new_content"])
    assert result.transform_type == "remove_redundant_else"
    assert result.patch_requests[0]["path"] == "pkg/mod.py"
    assert "redundant `else`" in result.rationale[0]
