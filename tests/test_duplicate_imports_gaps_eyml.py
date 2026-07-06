"""Coverage-gap / characterization tests for
:mod:`app.execution.duplicate_imports`.

The module was at 98% line coverage when this file was added; the only three
uncovered lines (``merge_duplicate_imports`` — the ``new_source == source``
byte-identical guard and the ``ast.parse(new_source)`` re-parse guard) are DEFENSIVE
branches that the public entry point cannot reach: a merge always deletes at least
one later member's line (so the result is never byte-identical) and only ever emits a
single valid ``from m import a, b`` line (so the result always re-parses). Rather than
force them via internal monkeypatching, these are characterization tests locking the
documented conservative-refusal contract that keeps those guards defensive.
"""

from __future__ import annotations

import ast

from app.execution.duplicate_imports import merge_duplicate_imports


def _bindings(source: str) -> list[tuple[int, str, str, str | None]]:
    out: list[tuple[int, str, str, str | None]] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.append((node.level, node.module or "", alias.name, alias.asname))
    return sorted(out)


# --- the merge lands (and stays binding-identical) --------------------------

def test_disjoint_intervening_import_is_safe_to_coalesce_past():
    # An intervening plain import that binds NO group name is import-only — cached,
    # so re-ordering its side effect is a no-op; the group still merges past it.
    src = (
        "from m import a\n"
        "import os\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert "from m import a, b\n" in out
    assert "import os\n" in out
    ast.parse(out)


def test_merged_output_preserves_binding_multiset():
    src = (
        "from pkg import a\n"
        "from pkg import b as B\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert _bindings(out) == _bindings(src)


# --- every documented refusal keeps the emit-guard unreachable --------------

def test_intervening_rebind_of_group_name_blocks_merge():
    # ``import y`` between two ``from a`` lines rebinds ``y``; hoisting the second
    # ``from a import y`` up past it would flip ``y``'s final binding — refuse.
    src = (
        "from a import x\n"
        "import y\n"
        "from a import y\n"
    )
    assert merge_duplicate_imports(src) is None


def test_standalone_comment_between_members_blocks_merge():
    src = (
        "from m import a\n"
        "# why b\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_trailing_comment_on_member_blocks_merge():
    src = (
        "from m import a  # keep\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_incompatible_alias_blocks_merge():
    # Same local name ``a`` from two different (name, asname) pairs — merging would
    # silently pick one binding, so the group is refused.
    src = (
        "from m import x as a\n"
        "from m import y as a\n"
    )
    assert merge_duplicate_imports(src) is None


def test_star_import_anywhere_makes_module_a_noop():
    src = (
        "from m import a\n"
        "from m import b\n"
        "from other import *\n"
    )
    assert merge_duplicate_imports(src) is None


def test_future_imports_are_never_merged():
    src = (
        "from __future__ import annotations\n"
        "from __future__ import division\n"
    )
    assert merge_duplicate_imports(src) is None


def test_guarded_non_toplevel_import_is_not_hoisted():
    src = (
        "from m import a\n"
        "try:\n"
        "    from m import b\n"
        "except ImportError:\n"
        "    pass\n"
    )
    assert merge_duplicate_imports(src) is None


def test_distinct_relative_levels_are_distinct_groups():
    src = (
        "from .m import a\n"
        "from ..m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_syntax_error_source_is_a_clean_noop():
    assert merge_duplicate_imports("from m import (") is None


def test_single_import_has_nothing_to_merge():
    assert merge_duplicate_imports("from m import a\n") is None


def test_idempotent_second_run_is_byte_identical_noop():
    src = (
        "from m import a\n"
        "from m import b\n"
    )
    once = merge_duplicate_imports(src)
    assert once is not None
    assert merge_duplicate_imports(once) is None  # already merged — no re-touch
