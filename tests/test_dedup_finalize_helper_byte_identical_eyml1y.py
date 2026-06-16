"""Byte-identical characterization for the shared finalise-helper consolidation.

The dedup / near-dup extract transforms each ended by stamping the SAME five
fields onto their ``RenamePlan`` (``plan.new``, ``plan.defined_in``,
``plan.originals``, ``plan.new_contents``, ``plan.edits_by_file``). That
byte-identical tail moved into :func:`app.execution._dedup_helpers
.stamp_multi_module_plan`; this test proves the move changed nothing.

For EACH refactored transform (``plan_dedup_extract``, ``plan_dedup_total_return``,
``plan_near_dup_extract``) it loads the pre-refactor module verbatim from
``git show HEAD:...`` as a standalone in-process module and compares its
``RenamePlan`` output field-by-field against the CURRENT module across a battery
of inputs: a successful same-module rewrite, a cross-file rewrite, the no-param /
no-return warning path, divergent signatures, broken parse, missing file, and the
empty / malformed / single-occurrence / zero-statement blocker paths. Zero
mismatches required, per transform.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.dedup import DuplicateBlock
from app.engine.near_dup import NearDuplicateGroup
from app.execution.dedup_extract import plan_dedup_extract as de_new
from app.execution.dedup_total_return import plan_dedup_total_return as dtr_new
from app.execution.near_dup_extract import plan_near_dup_extract as nde_new

_REPO = Path(__file__).resolve().parents[1]


def _pre_refactor_source(rel: str) -> str:
    """The newest version of ``rel`` in history that PREDATES the finalise-helper
    consolidation (i.e. still carries the inlined finalise tail). Walks back the
    commits touching ``rel`` until one without ``stamp_multi_module_plan`` is found,
    so the comparison is always against the genuine original no matter how many
    follow-up commits land on top of the refactor."""
    revs = subprocess.check_output(
        ["git", "log", "--format=%H", "--", rel], cwd=_REPO, text=True).split()
    for rev in revs:
        src = subprocess.check_output(
            ["git", "show", f"{rev}:{rel}"], cwd=_REPO, text=True)
        if "stamp_multi_module_plan" not in src:
            return src
    raise AssertionError(
        f"no pre-consolidation revision of {rel} found in history — "
        "characterization would compare a refactor against itself")


def _load_head(rel: str, modname: str, fn_name: str):
    """Import the PRE-refactor module as a standalone in-process module and return
    its ``fn_name`` callable."""
    src = _pre_refactor_source(rel)
    spec = importlib.util.spec_from_loader(modname, loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    exec(compile(src, f"<{modname}>", "exec"), mod.__dict__)
    return getattr(mod, fn_name)


de_old = _load_head("app/execution/dedup_extract.py",
                    "_de_head_eyml1y", "plan_dedup_extract")
dtr_old = _load_head("app/execution/dedup_total_return.py",
                     "_dtr_head_eyml1y", "plan_dedup_total_return")
nde_old = _load_head("app/execution/near_dup_extract.py",
                     "_nde_head_eyml1y", "plan_near_dup_extract")


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


def _assert_same(old_plan, new_plan) -> None:
    old = _plan_fields(old_plan)
    new = _plan_fields(new_plan)
    assert old == new, f"REFACTOR DIVERGED:\n  old={old}\n  new={new}"


# ── shared source fixtures ──────────────────────────────────────────────

# A rich, plain (non-returning-block) duplicate: exercises dedup_extract's
# success path with a live-out signature and a descriptive helper name, plus the
# warning paths.
_RICH = '''\
import os


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

# A no-live-in/no-live-out self-contained block: exercises the warning branch
# both transforms keep AFTER calling the shared helper.
_SELF_CONTAINED = '''\
def alpha():
    x = 1
    y = 2
    z = 3
    w = 4
    print(x + y + z + w)


def beta():
    x = 1
    y = 2
    z = 3
    w = 4
    print(x + y + z + w)
'''

# A TOTAL-RETURN block (every exit path returns): the one shape
# dedup_total_return accepts. Each copy returns via an if/else ladder.
_TOTAL_RETURN = '''\
def classify_alpha(x):
    a = x + 1
    b = a * 2
    if b > 0:
        return b
    else:
        return -b


def classify_beta(x):
    a = x + 1
    b = a * 2
    if b > 0:
        return b
    else:
        return -b
'''

# A tail-return block dedup_extract handles but dedup_total_return rejects
# (the block's tail is a return yet it is not "always returns" via if/else).
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

# A near-duplicate: structurally identical, differing only at a constant leaf.
_NEAR = '''\
def render_alpha():
    a = 1
    b = a + 10
    c = b * 2
    d = c - 3
    return d


def render_beta():
    a = 1
    b = a + 20
    c = b * 2
    d = c - 3
    return d
'''


def _body_starts(src: str) -> list[int]:
    """First body-statement line of each top-level function, in source order."""
    tree = ast.parse(src)
    return [n.body[0].lineno for n in tree.body
            if isinstance(n, ast.FunctionDef)]


# ── dedup_extract ───────────────────────────────────────────────────────

def _de_block(src: str, n: int = 5) -> DuplicateBlock:
    s = _body_starts(src)
    return DuplicateBlock(fingerprint="x", lines=n,
                          occurrences=[f"m.py:{s[0]}", f"m.py:{s[1]}"])


@pytest.mark.parametrize("src", [_RICH, _SELF_CONTAINED, _TAIL])
def test_dedup_extract_success(tmp_path, src):
    _write(tmp_path, "m.py", src)
    block = _de_block(src)
    _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


def test_dedup_extract_cross_file(tmp_path):
    half = _RICH.split("\n\n\n")[1]
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "import os\n\n\n" + _RICH.split("\n\n\n")[1])
    _write(tmp_path, "pkg/b.py", "import os\n\n\n" + half)
    block = DuplicateBlock(fingerprint="x", lines=5,
                           occurrences=["pkg/a.py:4", "pkg/b.py:4"])
    _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


def test_dedup_extract_blockers(tmp_path):
    _write(tmp_path, "m.py", _RICH)
    for block in (
        DuplicateBlock(fingerprint="e", lines=5, occurrences=[]),
        DuplicateBlock(fingerprint="s", lines=5, occurrences=["m.py:5"]),
        DuplicateBlock(fingerprint="z", lines=0,
                       occurrences=["m.py:5", "m.py:14"]),
        DuplicateBlock(fingerprint="b", lines=5,
                       occurrences=["no-colon", "x"]),
        DuplicateBlock(fingerprint="m", lines=5,
                       occurrences=["gone.py:2", "gone.py:5"]),
    ):
        _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


# ── dedup_total_return ──────────────────────────────────────────────────

def _dtr_block(src: str, n: int = 4) -> DuplicateBlock:
    s = _body_starts(src)
    return DuplicateBlock(fingerprint="x", lines=n,
                          occurrences=[f"m.py:{s[0]}", f"m.py:{s[1]}"])


def test_dtr_total_return_success(tmp_path):
    _write(tmp_path, "m.py", _TOTAL_RETURN)
    block = _dtr_block(_TOTAL_RETURN, n=3)
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_rejects_plain_tail(tmp_path):
    _write(tmp_path, "m.py", _TAIL)
    block = _dtr_block(_TAIL, n=5)
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_cross_file_total_return(tmp_path):
    one = _TOTAL_RETURN.split("\n\n\n")[1]
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", one)
    _write(tmp_path, "pkg/b.py", one)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["pkg/a.py:2", "pkg/b.py:2"])
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_blockers(tmp_path):
    _write(tmp_path, "m.py", _TOTAL_RETURN)
    for block in (
        DuplicateBlock(fingerprint="e", lines=3, occurrences=[]),
        DuplicateBlock(fingerprint="z", lines=0,
                       occurrences=["m.py:2", "m.py:10"]),
        DuplicateBlock(fingerprint="b", lines=3, occurrences=["bad", "x"]),
        DuplicateBlock(fingerprint="m", lines=3,
                       occurrences=["gone.py:2", "gone.py:5"]),
    ):
        _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


# ── near_dup_extract ────────────────────────────────────────────────────

def _nde_group(occ_lines, diff_count, differences, lines=5):
    return NearDuplicateGroup(
        occurrences=[f"m.py:{ln}" for ln in occ_lines], lines=lines,
        diff_count=diff_count, differences=differences)


def test_nde_success(tmp_path):
    _write(tmp_path, "m.py", _NEAR)
    s = _body_starts(_NEAR)
    group = _nde_group([s[0], s[1]], 1, [["10", "20"]], lines=5)
    _assert_same(nde_old(tmp_path, group), nde_new(tmp_path, group))


def test_nde_cross_file(tmp_path):
    one = _NEAR.split("\n\n\n")[0]
    two = _NEAR.split("\n\n\n")[1]
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", one + "\n")
    _write(tmp_path, "pkg/b.py", two + "\n")
    group = NearDuplicateGroup(
        occurrences=["pkg/a.py:2", "pkg/b.py:2"], lines=5,
        diff_count=1, differences=[["10", "20"]])
    _assert_same(nde_old(tmp_path, group), nde_new(tmp_path, group))


def test_nde_blockers(tmp_path):
    _write(tmp_path, "m.py", _NEAR)
    for group in (
        _nde_group([], 1, [["10", "20"]]),
        _nde_group([2], 1, [["10", "20"]]),
        # zero-diff group (an exact dup, not near's job)
        _nde_group([2, 11], 0, []),
        # malformed: diff_count disagrees with the columns
        _nde_group([2, 11], 2, [["10", "20"]]),
    ):
        _assert_same(nde_old(tmp_path, group), nde_new(tmp_path, group))
