"""Edge / branch coverage for `apex scope` (`cmd_scope` / `_scope_report` /
`render_scope_markdown`) beyond the happy paths pinned in test_cli_scope.py.

Targets the branches that file doesn't reach:
  - the profile-failure path (`ProjectProfiler(...).profile()` raises → the
    empty all-Python shape, never a crash);
  - a polyglot repo whose non-Python remainder carries NO language breakdown
    rows but DOES name out-of-scope files (the 592->601 skip-breakdown branch);
  - a non-Python file that IS test-linked (stem named by a test file's stem) →
    the `has_test=True` render branch (no "no test found" flag);
  - the churn singular/plural wording in the rendered file list.

Deterministic, stdlib-only, no network. The fixtures construct hermetic tmp
git repos with a fixed committer env wherever churn wording is asserted.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path

from app.cli_insight import _scope_report, cmd_scope, render_scope_markdown


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")


# --- profile-failure path ---------------------------------------------------

def test_profile_failure_collapses_to_all_python(monkeypatch, tmp_path):
    # If the profiler raises, _scope_report must NOT propagate — it collapses to
    # the honest empty (all-Python) shape and cmd_scope still exits 0.
    import app.tools.project_profile as pp

    def _boom(self, *a, **k):
        raise RuntimeError("profiler exploded")

    monkeypatch.setattr(pp.ProjectProfiler, "profile", _boom)

    rep = _scope_report(tmp_path)
    assert rep["all_python"] is True
    assert rep["source_file_count"] == 0
    assert rep["files"] == []
    assert rep["language_breakdown"] == []

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "all Python" in out


# --- non-Python file that IS test-linked (has_test True branch) --------------

def test_linked_non_python_file_not_flagged_untested(tmp_path):
    # A test file whose stem references the JS file's stem makes that out-of-scope
    # file "tested" — the `any(stem in t for t in test_stems)` branch — so it is
    # NOT flagged "no test found".
    _write(tmp_path, "app/core.py", "def f():\n    return 1\n")
    _write(tmp_path, "web/widget.js", "function go() { return 1; }\n" * 30)
    # tests/test_widget.py -> stem "test_widget" contains "widget".
    _write(tmp_path, "tests/test_widget.py", "def test_widget():\n    assert True\n")

    rep = _scope_report(tmp_path)
    js = next(f for f in rep["files"] if f["path"] == "web/widget.js")
    assert js["has_test"] is True

    _, out = _run(tmp_path)
    # The widget line is present but carries NO untested flag.
    assert "web/widget.js" in out
    widget_line = next(ln for ln in out.splitlines() if "web/widget.js" in ln)
    assert "no test found" not in widget_line


# --- render branch: files present but no language breakdown rows -------------

def test_render_files_without_breakdown_rows():
    # A hand-built report: out of scope, files named, but an empty breakdown.
    # Exercises the 592->601 branch (skip the breakdown section, still render the
    # files section).
    rep = {
        "source_file_count": 4,
        "python_file_count": 3,
        "analyzed_pct": 75,
        "out_of_scope_pct": 25,
        "all_python": False,
        "language_breakdown": [],
        "files": [
            {"path": "web/a.js", "language": "JavaScript", "loc": 40,
             "churn": 1, "has_test": False},
        ],
    }
    md = render_scope_markdown(rep)
    assert "## Outside analysis scope" not in md
    assert "## Largest / most-active out-of-scope files" in md
    assert "web/a.js" in md
    # churn == 1 -> singular "commit".
    assert "1 commit)" in md
    assert "1 commits)" not in md


def test_render_churn_plural_wording():
    rep = {
        "source_file_count": 4,
        "python_file_count": 3,
        "analyzed_pct": 75,
        "out_of_scope_pct": 25,
        "all_python": False,
        "language_breakdown": [{"language": "JavaScript", "files": 1}],
        "files": [
            {"path": "web/a.js", "language": "JavaScript", "loc": 40,
             "churn": 3, "has_test": False},
        ],
    }
    md = render_scope_markdown(rep)
    assert "3 commits)" in md
    # Single-file language line uses the singular "file".
    assert "JavaScript — 1 file" in md


def test_render_no_files_section_when_empty():
    # all_python False, a breakdown, but no named files (e.g. only denied/unmapped
    # out-of-scope ext) -> the files section is omitted entirely.
    rep = {
        "source_file_count": 3,
        "python_file_count": 2,
        "analyzed_pct": 67,
        "out_of_scope_pct": 33,
        "all_python": False,
        "language_breakdown": [{"language": "JSON", "files": 1}],
        "files": [],
    }
    md = render_scope_markdown(rep)
    assert "## Outside analysis scope" in md
    assert "## Largest / most-active out-of-scope files" not in md


# --- churn wording end to end over a hermetic git repo ----------------------

def test_polyglot_churn_counted_in_git_repo(tmp_path):
    # A real (small) git repo so churn is non-zero and the plural wording fires
    # deterministically. Fixed committer env keeps it hermetic.
    _init_repo(tmp_path)
    _write(tmp_path, "app/core.py", "def f():\n    return 1\n")
    _write(tmp_path, "web/app.js", "function go() { return 1; }\n" * 20)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "first")
    _write(tmp_path, "web/app.js", "function go() { return 2; }\n" * 20)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "second")

    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    js = next(f for f in data["files"] if f["path"] == "web/app.js")
    assert js["churn"] == 2

    _, md = _run(tmp_path)
    line = next(ln for ln in md.splitlines() if "web/app.js" in ln)
    assert "2 commits)" in line
