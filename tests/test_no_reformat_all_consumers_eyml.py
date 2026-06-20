"""Guard: the shared rewrite driver never destroys a comment.

``ast.unparse`` rebuilds the whole module from an AST that carries no comments,
so the *whole-module* emit path would silently delete every ``#`` comment (incl.
``# type: ignore`` / ``# noqa`` pragmas), flip quotes, and collapse blank lines.

Consumers now route through ``run_splice_rewrite``: comment-free files keep the
exact whole-module ``ast.unparse`` path (byte-identical to before), while a file
WITH a comment is rewritten by splicing ONLY the changed statement's line span,
so comments OUTSIDE that span survive byte-exact. A comment INSIDE the rewritten
span (which the local unparse would destroy) still refuses. These tests pin, for
EVERY consumer, that:

  * a convertible file WITH a trailing/unrelated comment -> the fix LANDS and the
    comment survives byte-exact,
  * the SAME file with the comment removed -> rewrites identically,

so no comment is ever destroyed and no comment-free behaviour regresses.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import _apply_helpers as helpers
from app.execution.semantic.transforms import augmented_assign as aug
from app.execution.semantic.transforms import chained_comparison as chain
from app.execution.semantic.transforms import or_default as ordef
from app.execution.semantic.transforms import startswith_tuple as sw

REL = "pkg/mod.py"


# --- source_has_comment detector -------------------------------------------


def test_source_has_comment_true_for_plain_comment():
    assert helpers.source_has_comment("x = 1  # note\n") is True


def test_source_has_comment_true_for_pragmas():
    assert helpers.source_has_comment("x = 1  # type: ignore\n") is True
    assert helpers.source_has_comment("import os  # noqa: F401\n") is True


def test_source_has_comment_false_for_comment_free():
    assert helpers.source_has_comment("x = x + 1\n") is False


def test_source_has_comment_false_for_hash_in_string():
    # A '#' inside a string literal is NOT a comment; tokenize distinguishes it.
    assert helpers.source_has_comment("x = '# not a comment'\n") is False


def test_source_has_comment_conservative_on_unparseable():
    # Unparseable input is treated as "has a comment" so we never rewrite a file
    # we could not fully inspect.
    assert helpers.source_has_comment("def f(:\n") is True


# --- driver: refuse only on comment loss, splice-preserve otherwise ---------


def test_driver_splices_when_source_has_comment():
    # A trailing comment is OUTSIDE the statement span -> the fix lands and the
    # comment survives byte-exact (no longer a blanket refusal).
    src = "x = x + 1  # keep me\n"
    tree = ast.parse(src)
    assert helpers.run_splice_rewrite(tree, aug._AugAssignTransformer(), src) == "x += 1  # keep me\n"


def test_driver_rewrites_when_no_comment():
    src = "x = x + 1\n"
    tree = ast.parse(src)
    assert helpers.run_splice_rewrite(tree, aug._AugAssignTransformer(), src) == "x += 1\n"


# --- per-consumer: land WITH a comment (preserved), rewrite identically without


def test_augmented_assign_lands_with_comment_rewrites_without():
    with_comment = "x = x + 1  # tally\n"
    without = "x = x + 1\n"
    res_c = aug.apply(REL, with_comment)
    assert res_c is not None
    assert res_c.patch_requests[0]["new_content"] == "x += 1  # tally\n"
    res = aug.apply(REL, without)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "x += 1\n"


def test_augmented_assign_preserves_type_ignore_pragma():
    src = "x = x + 1  # type: ignore[assignment]\n"
    res = aug.apply(REL, src)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "x += 1  # type: ignore[assignment]\n"


def test_chained_comparison_lands_with_comment_rewrites_without():
    with_comment = "y = a < b and b < c  # range check\n"
    without = "y = a < b and b < c\n"
    res_c = chain.apply(REL, with_comment, "t")
    assert res_c is not None
    assert res_c.patch_requests[0]["new_content"] == "y = a < b < c  # range check\n"
    res = chain.apply(REL, without, "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "y = a < b < c\n"


def test_startswith_tuple_lands_with_comment_rewrites_without():
    with_comment = "z = s.startswith('a') or s.startswith('b')  # noqa\n"
    without = "z = s.startswith('a') or s.startswith('b')\n"
    res_c = sw.apply(REL, with_comment, "t")
    assert res_c is not None
    assert res_c.patch_requests[0]["new_content"] == "z = s.startswith(('a', 'b'))  # noqa\n"
    res = sw.apply(REL, without, "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "z = s.startswith(('a', 'b'))\n"


def test_or_default_lands_with_comment_rewrites_without():
    with_comment = "v = a if a else b  # default\n"
    without = "v = a if a else b\n"
    res_c = ordef.apply(REL, with_comment)
    assert res_c is not None
    assert res_c.patch_requests[0]["new_content"] == "v = a or b  # default\n"
    res = ordef.apply(REL, without)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "v = a or b\n"


# --- a comment on an unrelated line survives (the edit splices only its stmt) -


def test_comment_on_unrelated_line_survives():
    src = "# module header\nx = x + 1\n"
    res = aug.apply(REL, src)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "# module header\nx += 1\n"


# --- determinism ------------------------------------------------------------


def test_splice_is_deterministic():
    src = "x = x + 1  # c\n"
    first = aug.apply(REL, src)
    second = aug.apply(REL, src)
    assert first is not None and second is not None
    assert (first.patch_requests[0]["new_content"]
            == second.patch_requests[0]["new_content"] == "x += 1  # c\n")
