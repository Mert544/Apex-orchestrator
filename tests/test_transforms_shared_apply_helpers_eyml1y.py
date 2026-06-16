"""Characterization tests for the consolidated apply-boilerplate helpers.

The visit-driver tail (cluster A: ``augmented_assign``, ``chained_comparison``,
``startswith_tuple``) and the parse-and-collect prologue (cluster B:
``collection_literal``, ``isinstance_merge``, ``negated_comparison``) were
extracted into ``_apply_helpers`` because they were byte-identical across the
sibling transforms. These tests pin the consolidated helpers directly AND drive
each transform's ``apply`` across convertible / must-NOT-convert / empty inputs,
asserting the full result (transform_type, patch_requests, rationale) so any
behavioural drift in the shared path is caught.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import _apply_helpers as helpers
from app.execution.semantic.transforms import augmented_assign as aug
from app.execution.semantic.transforms import chained_comparison as chain
from app.execution.semantic.transforms import collection_literal as coll
from app.execution.semantic.transforms import isinstance_merge as iso
from app.execution.semantic.transforms import negated_comparison as neg
from app.execution.semantic.transforms import startswith_tuple as sw

REL = "pkg/mod.py"


# --- helper: parse_or_none --------------------------------------------------


def test_parse_or_none_valid():
    tree = helpers.parse_or_none("x = 1\n")
    assert isinstance(tree, ast.Module)


def test_parse_or_none_syntax_error():
    assert helpers.parse_or_none("x = (") is None


def test_parse_or_none_empty():
    assert isinstance(helpers.parse_or_none(""), ast.Module)


# --- helper: run_rewrite_transformer ---------------------------------------


class _NoChange(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False


class _Identity(ast.NodeTransformer):
    """Marks changed=True but rewrites nothing, so output round-trips to a no-op."""

    def __init__(self) -> None:
        self.changed = True


def test_run_rewrite_transformer_unchanged_returns_none():
    tree = ast.parse("x = 1\n")
    assert helpers.run_rewrite_transformer(tree, _NoChange(), "x = 1\n") is None


def test_run_rewrite_transformer_noop_rewrite_returns_none():
    # changed=True but the unparsed text is identical -> refuse the no-op.
    src = "x = 1\n"
    tree = ast.parse(src)
    assert helpers.run_rewrite_transformer(tree, _Identity(), src) is None


def test_run_rewrite_transformer_restores_trailing_newline():
    # A real rewrite via the augmented-assign transformer, with no trailing \n
    # on input: helper must NOT append a newline (input had none).
    src = "x = x + 1"
    tree = ast.parse(src)
    out = helpers.run_rewrite_transformer(tree, aug._AugAssignTransformer(), src)
    assert out == "x += 1"

    src_nl = "x = x + 1\n"
    tree_nl = ast.parse(src_nl)
    out_nl = helpers.run_rewrite_transformer(tree_nl, aug._AugAssignTransformer(), src_nl)
    assert out_nl == "x += 1\n"


# --- helper: parse_and_collect_lines ---------------------------------------


def test_parse_and_collect_lines_syntax_error():
    assert helpers.parse_and_collect_lines("x = (", lambda t: []) is None


def test_parse_and_collect_lines_no_nodes():
    assert helpers.parse_and_collect_lines("x = 1\n", lambda t: []) is None


def test_parse_and_collect_lines_returns_nodes_and_lines():
    src = "a = 1\nb = 2\n"
    out = helpers.parse_and_collect_lines(src, lambda t: ["sentinel"])
    assert out is not None
    nodes, lines = out
    assert nodes == ["sentinel"]
    assert lines == ["a = 1\n", "b = 2\n"]


# --- end-to-end: full-result characterization per transform -----------------


def _full(res):
    if res is None:
        return None
    return (res.transform_type, res.patch_requests, list(res.rationale))


def test_augmented_assign_full_result():
    assert _full(aug.apply(REL, "x = x + 1\n")) == (
        "augmented_assign",
        [{"path": REL, "new_content": "x += 1\n", "expected_old_content": "x = x + 1\n"}],
        [f"Rewrote `x = x <op> y` as augmented assignment in {REL}."],
    )
    # must NOT convert: attribute target, name-on-right, syntax error, empty.
    assert aug.apply(REL, "obj.x = obj.x + 1\n") is None
    assert aug.apply(REL, "x = a + x\n") is None
    assert aug.apply(REL, "x = (") is None
    assert aug.apply(REL, "") is None


def test_chained_comparison_full_result():
    assert _full(chain.apply(REL, "y = a < b and b < c\n", "t")) == (
        "chained_comparison",
        [{
            "path": REL,
            "new_content": "y = a < b < c\n",
            "expected_old_content": "y = a < b and b < c\n",
        }],
        [f"Merged and-joined comparisons into a chain in {REL}."],
    )
    assert chain.apply(REL, "y = a < b and b > c\n", "t") is None  # mixed direction
    assert chain.apply(REL, "y = f() < b and b < c\n", "t") is None  # side effect
    assert chain.apply(REL, "x = (", "t") is None
    assert chain.apply(REL, "", "t") is None


def test_startswith_tuple_full_result():
    res = sw.apply(REL, "z = s.startswith('a') or s.startswith('b')\n", "t")
    assert _full(res) == (
        "startswith_tuple",
        [{
            "path": REL,
            "new_content": "z = s.startswith(('a', 'b'))\n",
            "expected_old_content": "z = s.startswith('a') or s.startswith('b')\n",
        }],
        [f"Merged ored startswith/endswith calls into a tuple argument in {REL}."],
    )
    assert sw.apply(REL, "z = s.startswith('a') or s.endswith('b')\n", "t") is None
    assert sw.apply(REL, "z = f().startswith('a') or f().startswith('b')\n", "t") is None
    assert sw.apply(REL, "x = (", "t") is None
    assert sw.apply(REL, "", "t") is None


def test_collection_literal_full_result():
    res = coll.apply(REL, "d = dict()\n", "t")
    assert res is not None
    assert res.transform_type == "modernize_collection_literal"
    assert res.patch_requests[0]["new_content"] == "d = {}\n"
    assert res.patch_requests[0]["expected_old_content"] == "d = dict()\n"
    assert res.rationale
    # must NOT convert: set(), args present, multi-line call, syntax error, empty.
    assert coll.apply(REL, "s = set()\n", "t") is None
    assert coll.apply(REL, "d = dict(a=1)\n", "t") is None
    # The call node itself spans two lines, so the splice is skipped.
    assert coll.apply(REL, "v = dict(\n)\n", "t") is None
    assert coll.apply(REL, "x = (", "t") is None
    assert coll.apply(REL, "", "t") is None


def test_isinstance_merge_full_result():
    res = iso.apply(REL, "r = isinstance(x, int) or isinstance(x, float)\n", "t")
    assert res is not None
    assert res.transform_type == "merge_isinstance"
    assert res.patch_requests[0]["new_content"] == "r = isinstance(x, (int, float))\n"
    assert res.rationale
    assert iso.apply(REL, "r = isinstance(x, int) or x is None\n", "t") is None
    assert iso.apply(REL, "r = isinstance(x, int) or isinstance(y, float)\n", "t") is None
    assert iso.apply(REL, "x = (", "t") is None
    assert iso.apply(REL, "", "t") is None


def test_negated_comparison_full_result():
    res = neg.apply(REL, "if not x in y:\n    pass\n", "t")
    assert res is not None
    assert res.transform_type == "fix_negated_comparison"
    assert res.patch_requests[0]["new_content"] == "if x not in y:\n    pass\n"
    assert res.rationale
    assert neg.apply(REL, "if not x == y:\n    pass\n", "t") is None  # eq not negatable
    assert neg.apply(REL, "x = (", "t") is None
    assert neg.apply(REL, "", "t") is None


def test_determinism_repeated_calls_identical():
    src = "r = isinstance(x, int) or isinstance(x, float)\n"
    first = iso.apply(REL, src, "t")
    second = iso.apply(REL, src, "t")
    assert first is not None and second is not None
    assert first.patch_requests == second.patch_requests
    assert first.rationale == second.rationale
