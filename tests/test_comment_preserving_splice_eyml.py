"""Comment-preserving splice rewrite: security/quality fixes land on commented files.

Before this change the shared rewrite driver refused (returned ``None``) whenever
the source carried ANY ``#`` comment, because its emit path unparsed the whole
module (deleting every comment). A one-line ``eval``->``literal_eval`` fix was
refused merely because an unrelated ``# noqa`` sat 40 lines away.

``run_splice_rewrite`` / ``splice_node_rewrite`` generalize the field-tested
line-anchored splice: rewrite ONLY the target statement's line span and unparse
just that node locally, so comments OUTSIDE the span survive byte-exact. A
comment INSIDE the rewritten span (which the local unparse would destroy) still
refuses -- that is the honesty guarantee. Comment-free files keep the prior
exact whole-module unparse path, byte-identical.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import _apply_helpers as helpers
from app.execution.semantic.transforms import augmented_assign as aug
from app.execution.semantic.transforms import chained_comparison as chain
from app.execution.semantic.transforms import or_default as ordef
from app.execution.semantic.transforms import security
from app.execution.semantic.transforms import startswith_tuple as sw

REL = "pkg/mod.py"


def _aug(src: str) -> str | None:
    """Drive the augmented-assign transform via the splice helper, returning text."""
    tree = ast.parse(src)
    blocked = aug._alias_unsafe_names(ast.parse(src))
    return helpers.run_splice_rewrite(tree, aug._AugAssignTransformer(blocked), src)


# --- the motivating case: eval(x) lands despite an unrelated # noqa ----------


def test_eval_lands_with_unrelated_noqa_which_survives_byte_exact():
    src = "result = eval(x)\nspam = 1  # noqa: E501\n"
    res = security.apply(REL, src, "use of eval")
    assert res is not None
    out = res.patch_requests[0]["new_content"]
    assert "ast.literal_eval(x)" in out
    # The unrelated pragma survives byte-exact, on its own line.
    assert "spam = 1  # noqa: E501\n" in out


def test_eval_lands_with_trailing_comment_on_the_same_line():
    src = "import ast\nresult = eval(x)  # parse the config\n"
    res = security.apply(REL, src, "use of eval")
    assert res is not None
    out = res.patch_requests[0]["new_content"]
    assert "ast.literal_eval(x)  # parse the config\n" in out


def test_type_ignore_pragma_on_nearby_line_survives():
    src = "y = y * 2  # type: ignore[operator]\n"
    out = _aug(src)
    assert out == "y *= 2  # type: ignore[operator]\n"


# --- comment INSIDE the rewritten node span -> still refused -----------------


def test_comment_inside_rewritten_expression_refused():
    # The comment lives between the two startswith arms, i.e. INSIDE the span the
    # local unparse overwrites; destroying it would be dishonest, so we refuse.
    src = (
        "z = (\n"
        "    s.startswith('a')  # primary\n"
        "    or s.startswith('b')\n"
        ")\n"
    )
    tree = ast.parse(src)
    assert helpers.run_splice_rewrite(tree, sw._StartswithTupleTransformer(), src) is None
    # And the public apply declines too.
    assert sw.apply(REL, src, "t") is None


def test_splice_node_rewrite_refuses_comment_inside_span_directly():
    src = "x = (x  # mid\n     + 1)\n"
    pristine = ast.parse(src)
    rewritten = ast.parse("x += 1\n")
    out = helpers.splice_node_rewrite(src, pristine.body[0], rewritten.body[0])
    assert out is None


# --- comment-free files are byte-identical to the prior unparse path ---------


def test_comment_free_byte_identical_augmented_assign():
    assert _aug("x = x + 1\n") == "x += 1\n"
    assert _aug("x = x + 1\ny = y * 2\n") == "x += 1\ny *= 2\n"


def test_comment_free_byte_identical_chained_comparison():
    res = chain.apply(REL, "y = a < b and b < c\n", "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "y = a < b < c\n"


def test_comment_free_byte_identical_startswith_tuple():
    res = sw.apply(REL, "z = s.startswith('a') or s.startswith('b')\n", "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "z = s.startswith(('a', 'b'))\n"


def test_comment_free_byte_identical_or_default():
    res = ordef.apply(REL, "v = a if a else b\n")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "v = a or b\n"


def test_comment_free_eval_byte_identical():
    src = "import ast\nresult = eval(x)\n"
    res = security.apply(REL, src, "use of eval")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "import ast\nresult = ast.literal_eval(x)\n"


# --- only the changed statement is touched; sibling comments survive ---------


def test_only_changed_statement_spliced_siblings_untouched():
    src = (
        "# leading banner\n"
        "a = a + 1  # accumulate\n"
        "b = 2  # unrelated\n"
        "# trailing note\n"
    )
    out = _aug(src)
    assert out == (
        "# leading banner\n"
        "a += 1  # accumulate\n"
        "b = 2  # unrelated\n"
        "# trailing note\n"
    )


def test_indented_statement_with_comment_lands():
    src = "def f():\n    total = total + n  # running sum\n    return total\n"
    out = _aug(src)
    assert out == "def f():\n    total += n  # running sum\n    return total\n"


# --- determinism -------------------------------------------------------------


def test_splice_is_deterministic():
    src = "x = x + 1  # c\n"
    assert _aug(src) == _aug(src) == "x += 1  # c\n"


def test_empty_and_noop_paths_return_none():
    # No candidate node -> nothing changes -> None (even with a comment present).
    assert _aug("x = y + 1  # not self-referential\n") is None
    # Comment-free no-op likewise.
    assert _aug("x = y + 1\n") is None


# --- outside-span comment-invariance: a destroyed/added comment refuses ------


def test_comment_invariance_holds_for_clean_splice():
    # Sanity: the invariance check passes for a legitimate splice (comment set
    # outside the span is unchanged), so the rewrite is emitted.
    src = "x = x + 1  # keep\n"
    pristine = ast.parse(src)
    rewritten = ast.parse("x += 1\n")
    out = helpers.splice_node_rewrite(src, pristine.body[0], rewritten.body[0])
    assert out == "x += 1  # keep\n"
