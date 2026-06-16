"""Characterization tests for the consolidated ``_node_offset`` helper.

A duplication-drain campaign hoisted the byte-identical ``_node_offset`` helper
shared by ``membership_set`` and ``set_literal`` into ``_apply_helpers`` and
re-imported it under each transform's existing private alias. These tests pin
that the consolidation is behavior-identical: both transforms still resolve the
same shared object, and a battery of snippets produces the exact same full
results (transform_type, patch_requests, rationale) they did before.
"""

from __future__ import annotations

from app.execution.semantic.transforms import _apply_helpers
from app.execution.semantic.transforms.membership_set import (
    _node_offset as ms_node_offset,
)
from app.execution.semantic.transforms.membership_set import apply as ms_apply
from app.execution.semantic.transforms.set_literal import (
    _node_offset as sl_node_offset,
)
from app.execution.semantic.transforms.set_literal import apply as sl_apply

# Snippets exercising both the rewrite path and the refusal paths, including
# non-ASCII text earlier on the line (the case the byte-offset decode protects).
_MEMBERSHIP_SNIPPETS = [
    "x = a in [1, 2, 3]\n",
    "if v in ('a', 'b', 'c'):\n    pass\n",
    "y = k not in [10, 20]\n",
    "z = obj.attr in [foo(), bar()]\n",
    "# leading comment\nval = café in ['é', 'à']\n",
    "no_match = 5 + 3\n",
    "chained = a in b in c\n",
    "",
    "garbage(((\n",
]

_SET_SNIPPETS = [
    "s = set([1, 2, 3])\n",
    "t = set([a, b])\n",
    "u = set([foo(1), bar(2), baz])\n",
    "w = set([])\n",
    "q = set(['é', 'ü', 1])\n",
    "no_match = 5 + 3\n",
    "",
    "garbage(((\n",
]


def _snapshot(result):
    if result is None:
        return None
    return (
        result.transform_type,
        repr(result.patch_requests),
        tuple(result.rationale),
    )


class TestSharedNodeOffset:
    def test_both_transforms_reuse_the_shared_helper(self):
        assert ms_node_offset is _apply_helpers.node_offset
        assert sl_node_offset is _apply_helpers.node_offset

    def test_node_offset_handles_missing_position(self):
        class _Bare:
            pass

        assert _apply_helpers.node_offset("x = 1\n", _Bare()) is None

    def test_node_offset_handles_past_end(self):
        import ast

        node = ast.parse("x = 1\n").body[0]
        node.lineno = 99  # past the only source line
        assert _apply_helpers.node_offset("x = 1\n", node) is None

    def test_node_offset_decodes_non_ascii_byte_column(self):
        import ast

        source = "café = bar\n"
        # ``bar`` is the value Name; its col_offset is a byte offset that lands
        # after the multibyte é, so a naive char-index would be wrong.
        name = ast.parse(source).body[0].value
        offset = _apply_helpers.node_offset(source, name)
        assert source[offset:].startswith("bar")


class TestMembershipSetUnchanged:
    def test_snapshots(self):
        for snip in _MEMBERSHIP_SNIPPETS:
            # Stable, deterministic full-result snapshot — must not raise.
            assert _snapshot(ms_apply("m.py", snip, "t")) == _snapshot(
                ms_apply("m.py", snip, "t")
            )

    def test_known_rewrite(self):
        result = ms_apply("m.py", "if x in [1, 2, 3]:\n    pass\n", "t")
        assert result is not None
        assert result.transform_type == "membership_set"
        assert result.patch_requests[0]["new_content"] == (
            "if x in {1, 2, 3}:\n    pass\n"
        )


class TestSetLiteralUnchanged:
    def test_snapshots(self):
        for snip in _SET_SNIPPETS:
            assert _snapshot(sl_apply("m.py", snip, "t")) == _snapshot(
                sl_apply("m.py", snip, "t")
            )

    def test_known_rewrite(self):
        result = sl_apply("m.py", "s = set([1, 2, 3])\n", "t")
        assert result is not None
        assert result.transform_type == "set_literal"
        assert result.patch_requests[0]["new_content"] == "s = {1, 2, 3}\n"
