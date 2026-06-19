"""Guard: ``run_rewrite_transformer`` refuses when unparse would drop comments.

``ast.unparse`` rebuilds the whole module from an AST that carries no comments,
so a transform advertised as a one-line edit would silently delete every ``#``
comment (incl. ``# type: ignore`` / ``# noqa`` pragmas), flip quotes, and
collapse blank lines. The shared driver now refuses (returns ``None``) when the
source contains any comment. These tests pin, for EVERY consumer of
``run_rewrite_transformer``, that:

  * a convertible file WITH a comment -> ``apply`` returns ``None`` (refused),
  * the SAME file with the comment removed -> still rewrites identically,

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


# --- run_rewrite_transformer refuses on comment loss ------------------------


def test_driver_refuses_when_source_has_comment():
    src = "x = x + 1  # keep me\n"
    tree = ast.parse(src)
    assert helpers.run_rewrite_transformer(tree, aug._AugAssignTransformer(), src) is None


def test_driver_rewrites_when_no_comment():
    src = "x = x + 1\n"
    tree = ast.parse(src)
    assert helpers.run_rewrite_transformer(tree, aug._AugAssignTransformer(), src) == "x += 1\n"


# --- per-consumer: refuse on comment, rewrite identically without -----------


def test_augmented_assign_refuses_with_comment_rewrites_without():
    with_comment = "x = x + 1  # tally\n"
    without = "x = x + 1\n"
    assert aug.apply(REL, with_comment) is None
    res = aug.apply(REL, without)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "x += 1\n"


def test_augmented_assign_refuses_type_ignore_pragma():
    src = "x = x + 1  # type: ignore[assignment]\n"
    assert aug.apply(REL, src) is None


def test_chained_comparison_refuses_with_comment_rewrites_without():
    with_comment = "y = a < b and b < c  # range check\n"
    without = "y = a < b and b < c\n"
    assert chain.apply(REL, with_comment, "t") is None
    res = chain.apply(REL, without, "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "y = a < b < c\n"


def test_startswith_tuple_refuses_with_comment_rewrites_without():
    with_comment = "z = s.startswith('a') or s.startswith('b')  # noqa\n"
    without = "z = s.startswith('a') or s.startswith('b')\n"
    assert sw.apply(REL, with_comment, "t") is None
    res = sw.apply(REL, without, "t")
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "z = s.startswith(('a', 'b'))\n"


def test_or_default_refuses_with_comment_rewrites_without():
    with_comment = "v = a if a else b  # default\n"
    without = "v = a if a else b\n"
    assert ordef.apply(REL, with_comment) is None
    res = ordef.apply(REL, without)
    assert res is not None
    assert res.patch_requests[0]["new_content"] == "v = a or b\n"


# --- a comment elsewhere in the file (not on the edited line) also refuses ---


def test_refuses_comment_on_unrelated_line():
    src = "# module header\nx = x + 1\n"
    assert aug.apply(REL, src) is None


# --- determinism ------------------------------------------------------------


def test_refusal_is_deterministic():
    src = "x = x + 1  # c\n"
    assert aug.apply(REL, src) is None
    assert aug.apply(REL, src) is None
