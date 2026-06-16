"""Byte-identical characterization for the shared resolve-occurrence PREFIX.

``dedup_extract._resolve_occurrence`` and
``dedup_total_return._resolve_total_return`` shared a byte-identical ~7-statement
PREFIX before their control-flow admissibility checks diverged: the
``rel not in trees`` blocker, ``tree``/``source`` bindings, the
``_enclosing_function`` lookup (with its closures blocker), and the
``_locate_run`` snap (with its contiguous-run blocker). That prefix moved into
:func:`app.execution._dedup_helpers.resolve_occurrence_prefix`; each resolve
helper now calls it and continues with its own divergent tail.

This test proves the move changed NOTHING observable. For each refactored
transform (``plan_dedup_extract``, ``plan_dedup_total_return``) it loads the
pre-refactor module verbatim from ``git show`` as a standalone in-process module
and compares its ``RenamePlan`` output field-by-field against the CURRENT module
across a battery of inputs — including every blocker path the shared prefix now
emits (missing module, occurrence not inside a top-level function, a block that
can't snap to a contiguous run), each of which must produce the IDENTICAL blocker
string. Zero mismatches required, per transform.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.dedup import DuplicateBlock
from app.execution.dedup_extract import plan_dedup_extract as de_new
from app.execution.dedup_total_return import plan_dedup_total_return as dtr_new

_REPO = Path(__file__).resolve().parents[1]
_MARKER = "resolve_occurrence_prefix"


def _pre_refactor_source(rel: str) -> str:
    """The newest version of ``rel`` in history that PREDATES the resolve-prefix
    consolidation (i.e. still carries the inlined prefix). Walks back the commits
    touching ``rel`` until one without ``resolve_occurrence_prefix`` is found, so
    the comparison is always against the genuine original no matter how many
    follow-up commits land on top of the refactor."""
    revs = subprocess.check_output(
        ["git", "log", "--format=%H", "--", rel], cwd=_REPO, text=True).split()
    for rev in revs:
        src = subprocess.check_output(
            ["git", "show", f"{rev}:{rel}"], cwd=_REPO, text=True)
        if _MARKER not in src:
            return src
    raise AssertionError(
        f"no pre-consolidation revision of {rel} found in history — "
        "characterization would compare a refactor against itself")


def _load_head(rel: str, modname: str, fn_name: str):
    """Import the PRE-refactor module as a standalone in-process module and return
    its ``fn_name`` callable. Its own intra-package imports still resolve against
    the real (unchanged) shared helpers, so only the inlined prefix differs."""
    src = _pre_refactor_source(rel)
    spec = importlib.util.spec_from_loader(modname, loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    exec(compile(src, f"<{modname}>", "exec"), mod.__dict__)
    return getattr(mod, fn_name)


de_old = _load_head("app/execution/dedup_extract.py",
                    "_de_head_prefix_eyml1y", "plan_dedup_extract")
dtr_old = _load_head("app/execution/dedup_total_return.py",
                     "_dtr_head_prefix_eyml1y", "plan_dedup_total_return")


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


def _body_starts(src: str) -> list[int]:
    tree = ast.parse(src)
    return [n.body[0].lineno for n in tree.body
            if isinstance(n, ast.FunctionDef)]


# ── source fixtures ──────────────────────────────────────────────────────

# A plain (non-returning) duplicate: dedup_extract success with a live-out
# signature; dedup_total_return rejects it (not always-returns).
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

# A TOTAL-RETURN block (every exit path returns) — the shape both transforms
# resolve through the shared prefix, then dedup_total_return accepts.
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

# A plain tail-return block dedup_extract handles but dedup_total_return rejects.
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

# An occurrence whose first statement is NOT inside a top-level function body
# (it sits in a nested closure) — exercises the prefix's "closures" blocker.
_CLOSURE = '''\
def outer_alpha():
    def inner():
        a = 1
        b = 2
        c = 3
        d = 4
        return a + b + c + d
    return inner


def outer_beta():
    def inner():
        a = 1
        b = 2
        c = 3
        d = 4
        return a + b + c + d
    return inner
'''


def _block(occs, n):
    return DuplicateBlock(fingerprint="x", lines=n, occurrences=occs)


# ── dedup_extract ────────────────────────────────────────────────────────

@pytest.mark.parametrize("src,n", [(_RICH, 5), (_TAIL, 5)])
def test_de_success(tmp_path, src, n):
    _write(tmp_path, "m.py", src)
    s = _body_starts(src)
    block = _block([f"m.py:{s[0]}", f"m.py:{s[1]}"], n)
    _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


def test_de_cross_file(tmp_path):
    half = _RICH.split("\n\n\n")[1]
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "import os\n\n\n" + half)
    _write(tmp_path, "pkg/b.py", "import os\n\n\n" + half)
    block = _block(["pkg/a.py:4", "pkg/b.py:4"], 5)
    _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


def test_de_prefix_blockers(tmp_path):
    """Every blocker path the shared prefix now emits, for dedup_extract."""
    _write(tmp_path, "m.py", _RICH)
    s = _body_starts(_RICH)
    _write(tmp_path, "clo.py", _CLOSURE)
    cs = _body_starts(_CLOSURE)
    for block in (
        # rel not in trees (missing module)
        _block(["gone.py:5", "gone.py:14"], 5),
        # occurrence not inside a top-level function (closure body)
        _block([f"clo.py:{cs[0] + 2}", f"clo.py:{cs[1] + 2}"], 4),
        # can't snap to a contiguous run of n statements (n too large)
        _block([f"m.py:{s[0]}", f"m.py:{s[1]}"], 99),
        # start_line that is not a statement starter at all
        _block(["m.py:1", "m.py:1"], 5),
    ):
        _assert_same(de_old(tmp_path, block), de_new(tmp_path, block))


# ── dedup_total_return ───────────────────────────────────────────────────

def test_dtr_success(tmp_path):
    _write(tmp_path, "m.py", _TOTAL_RETURN)
    s = _body_starts(_TOTAL_RETURN)
    block = _block([f"m.py:{s[0]}", f"m.py:{s[1]}"], 3)
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_cross_file(tmp_path):
    one = _TOTAL_RETURN.split("\n\n\n")[1]
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", one)
    _write(tmp_path, "pkg/b.py", one)
    block = _block(["pkg/a.py:2", "pkg/b.py:2"], 3)
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_rejects_plain_tail(tmp_path):
    _write(tmp_path, "m.py", _TAIL)
    s = _body_starts(_TAIL)
    block = _block([f"m.py:{s[0]}", f"m.py:{s[1]}"], 5)
    _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))


def test_dtr_prefix_blockers(tmp_path):
    """Every blocker path the shared prefix now emits, for dedup_total_return."""
    _write(tmp_path, "m.py", _TOTAL_RETURN)
    s = _body_starts(_TOTAL_RETURN)
    _write(tmp_path, "clo.py", _CLOSURE)
    cs = _body_starts(_CLOSURE)
    for block in (
        # rel not in trees (missing module)
        _block(["gone.py:2", "gone.py:11"], 3),
        # occurrence not inside a top-level function (closure body)
        _block([f"clo.py:{cs[0] + 2}", f"clo.py:{cs[1] + 2}"], 4),
        # can't snap to a contiguous run of n statements (n too large)
        _block([f"m.py:{s[0]}", f"m.py:{s[1]}"], 99),
        # start_line that is not a statement starter
        _block(["m.py:1", "m.py:1"], 3),
    ):
        _assert_same(dtr_old(tmp_path, block), dtr_new(tmp_path, block))
