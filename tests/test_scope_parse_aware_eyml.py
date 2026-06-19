"""Parse-aware HONESTY for `apex scope`.

The defect this guards (P1): `apex scope` claimed "Apex analyses 100% of this
repo (all Python)" even when one or more ``.py`` files were silently DROPPED
because they failed ``ast.parse``. The old ``analyzed_ratio`` was a pure LANGUAGE
ratio — a broken ``.py`` still counted in ``python_file_count``, so it was
reported "analysed" though PythonStructureAnalyzer dropped it from the structure
graph / security scan / cycle detection. A maliciously-mangled or merely broken
file hid for free.

The fix threads the dropped files (off the analyzer's SINGLE parse pass, no
reparse) onto the profile as ``unparsed_files`` / ``unparsed_count`` and exposes
``analyzed_ratio_honest`` (the numerator minus those drops). The scope report now
reads the honest ratio and NAMES the unparseable files. These tests pin:

1. a repo with one syntax-error ``.py`` → scope ratio < 100%, the broken file
   NAMED, the count correct;
2. an all-parseable repo → still 100% AND byte-identical scope text vs the
   pre-fix path (proves no common-case regression);
3. determinism across two runs (byte-for-byte, JSON and markdown).

Offline, stdlib + pytest only.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_insight import _scope_report, cmd_scope
from app.tools.project_profile import ProjectProfiler


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _broken_file_repo(root: Path) -> None:
    """All-Python repo where exactly ONE file fails to parse."""
    _write(root, "pkg_util/good.py", "def f():\n    return 1\n")
    _write(root, "pkg_util/broken.py", "def f(:\n    return 1\n")


def _all_parseable_repo(root: Path) -> None:
    """All-Python repo where EVERY file parses cleanly."""
    _write(root, "app/core.py", "def f():\n    return 1\n")
    _write(root, "app/util.py", "VALUE = 2\n")
    _write(root, "app/model.py", "class M:\n    pass\n")


# --- 1. broken-file repo: the gap is disclosed, never hidden ----------------

def test_profile_records_unparsed_file(tmp_path: Path):
    _broken_file_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    # Both .py count toward the LANGUAGE ratio (legacy field unchanged)...
    assert profile.python_file_count == 2
    assert profile.source_file_count == 2
    assert profile.analyzed_ratio == 1.0
    # ...but the HONEST ratio subtracts the dropped file, and names it.
    assert profile.unparsed_count == 1
    assert profile.unparsed_files == ["pkg_util/broken.py"]
    assert profile.analyzed_ratio_honest == 0.5


def test_scope_report_ratio_below_100_and_names_file(tmp_path: Path):
    _broken_file_repo(tmp_path)
    rep = _scope_report(tmp_path)
    assert rep["analyzed_pct"] == 50
    assert rep["analyzed_pct"] < 100
    assert rep["all_python"] is False  # a real gap exists; no reassurance path
    assert rep["unparsed_count"] == 1
    assert rep["unparsed_files"] == ["pkg_util/broken.py"]


def test_scope_markdown_names_broken_file(tmp_path: Path):
    _broken_file_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    # Never the false "100% (all Python)" claim.
    assert "Apex analyses 100% of this repo (all Python)." not in out
    assert "could not be parsed and was excluded" in out
    assert "pkg_util/broken.py" in out
    # The honest headline percentage.
    assert "Apex analyses 50% of this repo" in out


def test_scope_json_carries_unparsed(tmp_path: Path):
    _broken_file_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["all_python"] is False
    assert data["analyzed_pct"] == 50
    assert data["unparsed_count"] == 1
    assert data["unparsed_files"] == ["pkg_util/broken.py"]


def test_multiple_broken_files_counted_and_sorted(tmp_path: Path):
    _write(tmp_path, "a/ok.py", "x = 1\n")
    _write(tmp_path, "a/zeta_broken.py", "def f(:\n")
    _write(tmp_path, "a/alpha_broken.py", "class C(:\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.unparsed_count == 2
    # Sorted, deterministic order regardless of walk order.
    assert profile.unparsed_files == ["a/alpha_broken.py", "a/zeta_broken.py"]
    rep = _scope_report(tmp_path)
    # 1 of 3 source files truly analysed -> 33%.
    assert rep["analyzed_pct"] == 33


# --- 2. all-parseable repo: still 100%, byte-identical (no regression) -------

def test_all_parseable_repo_still_100_pct(tmp_path: Path):
    _all_parseable_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.unparsed_count == 0
    assert profile.unparsed_files == []
    # Honest ratio EQUALS the language ratio when nothing was dropped.
    assert profile.analyzed_ratio_honest == 1.0
    assert profile.analyzed_ratio == 1.0


def test_all_parseable_scope_text_byte_identical_to_pre_fix(tmp_path: Path):
    """The common case must not regress: an all-parseable, all-Python repo still
    renders the EXACT pre-fix reassurance block (pinned verbatim here)."""
    _all_parseable_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    expected = (
        "# Apex analysis scope\n\n"
        "Apex analyses 100% of this repo (all Python).\n\n"
        "_Every source-bearing file here is Python — the subset Apex deep-"
        "analyses — so its grade speaks for the whole repo._"
    )
    assert out.rstrip("\n") == expected
    # And the JSON shape's pre-fix fields are unchanged.
    rep = _scope_report(tmp_path)
    assert rep["all_python"] is True
    assert rep["analyzed_pct"] == 100
    assert rep["out_of_scope_pct"] == 0
    assert rep["unparsed_count"] == 0


# --- 3. determinism ----------------------------------------------------------

def test_determinism_across_runs(tmp_path: Path):
    _broken_file_repo(tmp_path)
    _, md1 = _run(tmp_path)
    _, md2 = _run(tmp_path)
    assert md1 == md2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2
    # The profile field itself is deterministic too.
    p1 = ProjectProfiler(str(tmp_path)).profile()
    p2 = ProjectProfiler(str(tmp_path)).profile()
    assert p1.unparsed_files == p2.unparsed_files
    assert p1.analyzed_ratio_honest == p2.analyzed_ratio_honest


# --- edge: a repo of ONLY broken files (no parseable modules) ----------------

def test_all_broken_repo_reports_zero_analysed(tmp_path: Path):
    """Even when NO module parses (so structure analysis returns nothing), the
    drops are still recorded — the early-return path must not swallow them."""
    _write(tmp_path, "a.py", "def f(:\n")
    _write(tmp_path, "b.py", "class C(:\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.unparsed_count == 2
    assert profile.unparsed_files == ["a.py", "b.py"]
    assert profile.analyzed_ratio_honest == 0.0
    rep = _scope_report(tmp_path)
    assert rep["analyzed_pct"] == 0
    assert rep["unparsed_count"] == 2


# --- edge: empty repo is unaffected -----------------------------------------

def test_empty_repo_unaffected(tmp_path: Path):
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.unparsed_count == 0
    assert profile.unparsed_files == []
    assert profile.analyzed_ratio_honest == 1.0
