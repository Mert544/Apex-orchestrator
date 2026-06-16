"""Byte-identical characterization for the refactor of ``plan_dedup_extract``.

Loads the ORIGINAL (pre-refactor) module from ``git show HEAD~`` source captured
at test time and compares its ``RenamePlan`` output field-by-field against the
CURRENT refactored module across a battery of inputs: a rich rewrite case, a
cross-file case, a broken-parse case, a missing-file case, divergent-signature,
tail-return, descriptive-naming, collision, the above-container regression, and
no-op/empty/malformed/single-occurrence cases. Zero mismatches required.

The original source is captured into a temp module so both implementations run
in-process against identical project trees on disk.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.dedup import DuplicateBlock
from app.execution.dedup_extract import plan_dedup_extract as plan_new

_REPO = Path(__file__).resolve().parents[1]


def _load_original():
    """Import the pre-refactor ``dedup_extract`` from ``git show HEAD:...`` as a
    standalone module, so we can run the OLD ``plan_dedup_extract`` in-process."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/execution/dedup_extract.py"],
        cwd=_REPO, text=True,
    )
    # If HEAD already contains the refactor (committed), fall back to HEAD~1.
    if "_finalize_plan" in src and "def _validate_block" in src:
        src = subprocess.check_output(
            ["git", "show", "HEAD~1:app/execution/dedup_extract.py"],
            cwd=_REPO, text=True,
        )
    spec = importlib.util.spec_from_loader("_dedup_extract_orig", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dedup_extract_orig"] = mod
    exec(compile(src, "<dedup_extract_orig>", "exec"), mod.__dict__)
    return mod.plan_dedup_extract


plan_old = _load_original()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _plan_fields(plan) -> dict:
    """Every observable field of a RenamePlan as plain comparable data."""
    return {
        "old": plan.old,
        "new": plan.new,
        "defined_in": plan.defined_in,
        "originals": dict(plan.originals),
        "new_contents": dict(plan.new_contents),
        "edits_by_file": dict(plan.edits_by_file),
        "blockers": list(plan.blockers),
        "warnings": list(plan.warnings),
        "ok": plan.ok,
    }


def _assert_identical(root: Path, block) -> None:
    old = _plan_fields(plan_old(root, block))
    new = _plan_fields(plan_new(root, block))
    assert old == new, (
        "REFACTOR DIVERGED:\n"
        f"  old={old}\n  new={new}")


# ── input fixtures (sources + the DuplicateBlock that targets them) ──

_RICH = '''\
import os
import sys


def generate_patch_alpha():
    a = os.getpid()
    b = a + 2
    c = b * 3
    d = c - 1
    e = d + a
    return e


def generate_patch_beta():
    a = os.getpid()
    b = a + 2
    c = b * 3
    d = c - 1
    e = d + a
    return e + 100
'''

_TAIL = '''\
def alpha(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 5


def beta(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 5
'''

_DIVERGENT = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return d


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e
'''

_NO_COMMON = '''\
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

_ABOVE = '''\
def bar(x):
    a = x + 1
    b = a * 2
    c = b - 3
    return c + 100


def foo(x):
    a = x + 1
    b = a * 2
    c = b - 3
    return c
'''

_CROSS_A = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e
'''
_CROSS_B = '''\
def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 7
'''


def _occ_lines(src: str, marker_fn: str, n: int) -> list[str]:
    """Locate ``module:lineno`` occurrences: first body stmt of each target fn."""
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append(node.body[0].lineno)
    return out


def test_rich_same_module(tmp_path):
    _write(tmp_path, "pkg/mod.py", _RICH)
    lines = _occ_lines(_RICH, "", 5)
    block = DuplicateBlock(fingerprint="r", lines=5,
                           occurrences=[f"pkg/mod.py:{lines[0]}",
                                        f"pkg/mod.py:{lines[1]}"])
    _assert_identical(tmp_path, block)


def test_tail_return(tmp_path):
    _write(tmp_path, "m.py", _TAIL)
    lines = _occ_lines(_TAIL, "", 5)
    block = DuplicateBlock(fingerprint="t", lines=5,
                           occurrences=[f"m.py:{lines[0]}", f"m.py:{lines[1]}"])
    _assert_identical(tmp_path, block)


def test_divergent_signature(tmp_path):
    _write(tmp_path, "m.py", _DIVERGENT)
    lines = _occ_lines(_DIVERGENT, "", 5)
    block = DuplicateBlock(fingerprint="d", lines=5,
                           occurrences=[f"m.py:{lines[0]}", f"m.py:{lines[1]}"])
    _assert_identical(tmp_path, block)


def test_no_common_tokens(tmp_path):
    _write(tmp_path, "m.py", _NO_COMMON)
    lines = _occ_lines(_NO_COMMON, "", 5)
    block = DuplicateBlock(fingerprint="n", lines=5,
                           occurrences=[f"m.py:{lines[0]}", f"m.py:{lines[1]}"])
    _assert_identical(tmp_path, block)


def test_descriptive_collision(tmp_path):
    src = "_generate_patch = 1\n\n\n" + _RICH
    _write(tmp_path, "m.py", src)
    lines = _occ_lines(src, "", 5)
    block = DuplicateBlock(fingerprint="c", lines=5,
                           occurrences=[f"m.py:{lines[0]}", f"m.py:{lines[1]}"])
    _assert_identical(tmp_path, block)


def test_above_container_emit_order(tmp_path):
    _write(tmp_path, "m.py", _ABOVE)
    # emit order [foo(line9), bar(line2)] — first-in-emit not topmost.
    block = DuplicateBlock(fingerprint="a", lines=3,
                           occurrences=["m.py:9", "m.py:2"])
    _assert_identical(tmp_path, block)


def test_cross_file(tmp_path):
    _write(tmp_path, "pkg/a.py", _CROSS_A)
    _write(tmp_path, "pkg/b.py", _CROSS_B)
    _write(tmp_path, "pkg/__init__.py", "")
    block = DuplicateBlock(fingerprint="x", lines=5,
                           occurrences=["pkg/a.py:2", "pkg/b.py:2"])
    _assert_identical(tmp_path, block)


def test_broken_parse(tmp_path):
    _write(tmp_path, "m.py", "def alpha(:\n    pass\n")
    block = DuplicateBlock(fingerprint="b", lines=5,
                           occurrences=["m.py:2", "m.py:2"])
    _assert_identical(tmp_path, block)


def test_missing_file(tmp_path):
    block = DuplicateBlock(fingerprint="m", lines=5,
                           occurrences=["nope.py:2", "nope.py:5"])
    _assert_identical(tmp_path, block)


def test_single_occurrence(tmp_path):
    _write(tmp_path, "m.py", _NO_COMMON)
    block = DuplicateBlock(fingerprint="s", lines=5, occurrences=["m.py:2"])
    _assert_identical(tmp_path, block)


def test_empty_occurrences(tmp_path):
    block = DuplicateBlock(fingerprint="e", lines=5, occurrences=[])
    _assert_identical(tmp_path, block)


def test_malformed_occurrence(tmp_path):
    block = DuplicateBlock(fingerprint="mm", lines=5,
                           occurrences=["no-colon", "also/bad"])
    _assert_identical(tmp_path, block)


def test_zero_statements(tmp_path):
    _write(tmp_path, "m.py", _NO_COMMON)
    block = DuplicateBlock(fingerprint="z", lines=0,
                           occurrences=["m.py:2", "m.py:11"])
    _assert_identical(tmp_path, block)


def test_occurrence_not_inside_function(tmp_path):
    _write(tmp_path, "m.py", "x = 1\ny = 2\nz = 3\nw = 4\nv = 5\n")
    block = DuplicateBlock(fingerprint="f", lines=3,
                           occurrences=["m.py:1", "m.py:1"])
    _assert_identical(tmp_path, block)


@pytest.mark.parametrize("nstmt", [2, 3, 4, 5])
def test_varied_statement_counts(tmp_path, nstmt):
    _write(tmp_path, "m.py", _RICH)
    lines = _occ_lines(_RICH, "", nstmt)
    block = DuplicateBlock(fingerprint=f"v{nstmt}", lines=nstmt,
                           occurrences=[f"m.py:{lines[0]}", f"m.py:{lines[1]}"])
    _assert_identical(tmp_path, block)
