"""Characterization harness: prove the refactor of ``plan_dedup_total_return``
is BYTE-IDENTICAL to the pre-refactor implementation.

It loads the ORIGINAL module source straight from ``git show HEAD:`` into a fresh
module object, then runs BOTH the original and the current (refactored) planner
on the same inputs and asserts every observable :class:`RenamePlan` field is
equal — blockers, new (helper name), defined_in, originals, new_contents,
edits_by_file, warnings, and ok. Inputs span four classes: a rich multi-occurrence
total-return block, a broken-parse module, a missing-file occurrence, and a no-op
(too-few-occurrences) block, plus every blocker/positive fixture reused from the
main suite.

If HEAD already contains the refactor (e.g. after committing), the original is
loaded from the file as it stood at HEAD — which is still the appropriate
baseline for the proof recorded in this commit's history.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.dedup import DuplicateBlock
from app.execution.dedup_total_return import (
    plan_dedup_total_return as plan_current,
)

_REL = "app/execution/dedup_total_return.py"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[1]


def _load_original():
    """Load ``app/execution/dedup_total_return.py`` as it stood at HEAD into a
    standalone module object and return its ``plan_dedup_total_return``."""
    root = _repo_root()
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_REL}"], cwd=root, text=True
    )
    spec = importlib.util.spec_from_loader("_dedup_total_return_head", loader=None)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dedup_total_return_head"] = mod
    exec(compile(src, f"HEAD:{_REL}", "exec"), mod.__dict__)  # noqa: S102
    return mod.plan_dedup_total_return


plan_original = _load_original()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_PLAN_FIELDS = (
    "old", "new", "defined_in", "blockers", "originals",
    "new_contents", "edits_by_file", "warnings",
)


def _snapshot(plan) -> dict:
    """Capture every observable field of a RenamePlan as plain data."""
    snap = {"ok": plan.ok}
    for field in _PLAN_FIELDS:
        snap[field] = getattr(plan, field, "<<missing>>")
    return snap


def _assert_identical(root: Path, block, label: str) -> None:
    orig = _snapshot(plan_original(root, block))
    new = _snapshot(plan_current(root, block))
    assert orig == new, (
        f"[{label}] refactored plan diverged from HEAD original.\n"
        f"original={orig!r}\nrefactored={new!r}"
    )


# ── Fixtures reused/adapted from the main suite, covering each input class. ──

_GUARD_RETURN = '''\
def alpha(cond, a, b):
    z = a + b
    w = z * 2
    if cond:
        return w
    return z


def beta(cond, a, b):
    z = a + b
    w = z * 2
    if cond:
        return w
    return z
'''

_IF_ELIF_ELSE = '''\
def sign_alpha(n):
    base = n
    scaled = base
    if scaled > 0:
        return "pos"
    elif scaled < 0:
        return "neg"
    else:
        return "zero"


def sign_beta(n):
    base = n
    scaled = base
    if scaled > 0:
        return "pos"
    elif scaled < 0:
        return "neg"
    else:
        return "zero"
'''

_CROSS_A = '''\
def alpha(cond, x):
    y = x + 1
    z = y + 1
    if cond:
        return y
    return z
'''

_CROSS_B = '''\
def beta(cond, x):
    y = x + 1
    z = y + 1
    if cond:
        return y
    return z
'''

_PLAIN_TAIL = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 100
'''

_WITH_YIELD = '''\
def alpha(items):
    total = 0
    for it in items:
        yield it
    return total


def beta(items):
    total = 0
    for it in items:
        yield it
    return total
'''

_WITH_NESTED_DEF = '''\
def alpha(x):
    def inner(y):
        return y + 1
    z = inner(x)
    return z


def beta(x):
    def inner(y):
        return y + 1
    z = inner(x)
    return z
'''

_SIG_DIVERGE = '''\
k = 7  # module global referenced by beta (alpha takes `k` as a parameter)


def alpha(cond, k):
    a = k + 1
    b = a + 1
    if cond:
        return a
    return b


def beta(cond):
    a = k + 1
    b = a + 1
    if cond:
        return a
    return b
'''

_ABOVE_CONTAINER_TR = '''\
def bar(x):
    a = x + 1
    b = a + 2
    return a + b


def foo(x):
    s0 = x + 100
    a = x + 1
    b = a + 2
    return a + b
'''

_BROKEN = "def alpha(:\n    return 1\n"


def test_char_rich_guard_return_same_file(tmp_path):
    """Rich input: a clean two-occurrence total-return block lifts identically."""
    _write(tmp_path, "pkg/mod.py", _GUARD_RETURN)
    block = DuplicateBlock(fingerprint="g", lines=4,
                           occurrences=["pkg/mod.py:2", "pkg/mod.py:10"])
    _assert_identical(tmp_path, block, "rich/guard-return")


def test_char_rich_if_elif_else(tmp_path):
    _write(tmp_path, "mod.py", _IF_ELIF_ELSE)
    block = DuplicateBlock(fingerprint="s", lines=3,
                           occurrences=["mod.py:2", "mod.py:13"])
    _assert_identical(tmp_path, block, "rich/if-elif-else")


def test_char_rich_cross_file(tmp_path):
    """Rich input across two modules — exercises the import-emit branch."""
    _write(tmp_path, "a.py", _CROSS_A)
    _write(tmp_path, "b.py", _CROSS_B)
    block = DuplicateBlock(fingerprint="c", lines=4,
                           occurrences=["a.py:2", "b.py:2"])
    _assert_identical(tmp_path, block, "rich/cross-file")


def test_char_above_container_regression(tmp_path):
    """Emit order [foo, bar] — the anchor-rebase / helper-insert branch."""
    _write(tmp_path, "mod.py", _ABOVE_CONTAINER_TR)
    block = DuplicateBlock(fingerprint="h", lines=3,
                           occurrences=["mod.py:9", "mod.py:2"])
    _assert_identical(tmp_path, block, "rich/above-container")


def test_char_broken_parse(tmp_path):
    """Broken-parse input: the module doesn't parse → identical blocker string."""
    _write(tmp_path, "mod.py", _BROKEN)
    block = DuplicateBlock(fingerprint="b", lines=2,
                           occurrences=["mod.py:1", "mod.py:2"])
    _assert_identical(tmp_path, block, "broken-parse")


def test_char_missing_file(tmp_path):
    """Missing-file input: occurrence points at a non-existent module."""
    block = DuplicateBlock(fingerprint="m", lines=2,
                           occurrences=["missing.py:1", "missing.py:5"])
    _assert_identical(tmp_path, block, "missing-file")


def test_char_noop_too_few_occurrences(tmp_path):
    """No-op input: fewer than two occurrences → identical early blocker."""
    block = DuplicateBlock(fingerprint="x", lines=2, occurrences=["mod.py:1"])
    _assert_identical(tmp_path, block, "noop/too-few")


def test_char_zero_statements(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=0,
                           occurrences=["mod.py:1", "mod.py:5"])
    _assert_identical(tmp_path, block, "noop/zero-statements")


def test_char_malformed_occurrence(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=2,
                           occurrences=["not-a-location", "also-bad"])
    _assert_identical(tmp_path, block, "noop/malformed")


def test_char_plain_tail_blocks(tmp_path):
    _write(tmp_path, "mod.py", _PLAIN_TAIL)
    block = DuplicateBlock(fingerprint="p", lines=5,
                           occurrences=["mod.py:2", "mod.py:11"])
    _assert_identical(tmp_path, block, "block/plain-tail")


def test_char_yield_blocks(tmp_path):
    _write(tmp_path, "mod.py", _WITH_YIELD)
    block = DuplicateBlock(fingerprint="y", lines=3,
                           occurrences=["mod.py:2", "mod.py:9"])
    _assert_identical(tmp_path, block, "block/yield")


def test_char_nested_def_blocks(tmp_path):
    _write(tmp_path, "mod.py", _WITH_NESTED_DEF)
    block = DuplicateBlock(fingerprint="n", lines=3,
                           occurrences=["mod.py:2", "mod.py:9"])
    _assert_identical(tmp_path, block, "block/nested-def")


def test_char_diverging_signatures_block(tmp_path):
    _write(tmp_path, "mod.py", _SIG_DIVERGE)
    block = DuplicateBlock(fingerprint="d", lines=4,
                           occurrences=["mod.py:5", "mod.py:13"])
    _assert_identical(tmp_path, block, "block/diverging-signatures")


@pytest.mark.parametrize(
    "label,occurrences,lines",
    [
        ("occ-out-of-range", ["mod.py:999", "mod.py:1000"], 2),
        ("not-in-function", ["mod.py:1", "mod.py:1"], 1),
    ],
)
def test_char_edge_resolution_paths(tmp_path, label, occurrences, lines):
    """Edge resolution paths: lines that don't snap to a function/run."""
    _write(tmp_path, "mod.py", _GUARD_RETURN)
    block = DuplicateBlock(fingerprint="e", lines=lines, occurrences=occurrences)
    _assert_identical(tmp_path, block, f"edge/{label}")


def test_char_no_occurrences_attr(tmp_path):
    """No-op input: an object lacking the expected attributes entirely."""
    class _Bare:
        pass

    _assert_identical(tmp_path, _Bare(), "noop/bare-object")


def test_original_and_current_are_distinct_objects():
    """Sanity: the harness really loaded a SEPARATE original implementation."""
    assert plan_original is not plan_current
    assert plan_original.__code__ is not plan_current.__code__


def test_emitted_positive_reparses_under_both(tmp_path):
    """Both implementations emit re-parseable source for a positive case."""
    _write(tmp_path, "pkg/mod.py", _GUARD_RETURN)
    block = DuplicateBlock(fingerprint="g", lines=4,
                           occurrences=["pkg/mod.py:2", "pkg/mod.py:10"])
    for planner in (plan_original, plan_current):
        plan = planner(tmp_path, block)
        assert plan.ok, plan.blockers
        for src in plan.new_contents.values():
            ast.parse(src)
