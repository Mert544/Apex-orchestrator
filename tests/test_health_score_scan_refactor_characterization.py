"""Byte-identical proof for the _scan_own_modules / _collect_metrics refactor.

Loads the pre-refactor health_score module straight from git HEAD (snapshotted
to a temp file by the harness fixture) and compares the FULL HealthScore result
of grade() against the current (refactored) module, on representative temp trees
(a clean repo and a multi-bucket lossy repo). Zero mismatches across score,
letter, fixes, scope_line, and every component (name/points_lost/detail/top_files)
proves the decomposition is behavior-preserving.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from app.engine import health_score as current


def _load_original(tmp_path):
    """Load the HEAD version of health_score.py as a standalone module."""
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/health_score.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    path = tmp_path / "health_score_head.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("hs_head", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hs_head"] = mod
    spec.loader.exec_module(mod)
    return mod


def _snapshot(h):
    return {
        "score": h.score,
        "letter": h.letter,
        "fixes": list(h.fixes),
        "scope_line": h.scope_line,
        "components": [
            (c.name, c.points_lost, c.detail, list(c.top_files))
            for c in h.components
        ],
    }


def _build_clean(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "calc.py").write_text(
        'def add(a, b):\n    """Add."""\n    return a + b\n', encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")


def _build_lossy(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    # Security (eval/yaml) + mutable default + None-compare bug.
    (root / "app" / "risky.py").write_text(
        "import yaml\n\n\n"
        "def load(s, cache=[]):\n"
        "    if s == None:\n"
        "        return eval(s)\n"
        "    return yaml.load(s)\n",
        encoding="utf-8")
    # Untested module.
    (root / "app" / "untested.py").write_text(
        "def helper(x):\n    return x + 1\n", encoding="utf-8")
    # Over-complex function + two duplicated blocks for maintainability/duplication.
    branchy = "def grade_fn(n):\n    total = 0\n" + "".join(
        f"    if n == {i}:\n        total += {i}\n" for i in range(14)
    ) + "    return total\n"
    dup = (
        "    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n"
        "    return a + b + c + d + e\n"
    )
    (root / "app" / "big.py").write_text(
        branchy + "\n\ndef one():\n" + dup + "\n\ndef two():\n" + dup,
        encoding="utf-8")
    (root / "tests" / "test_big.py").write_text(
        "from app.big import grade_fn\ndef test_g():\n    assert grade_fn(0) == 0\n",
        encoding="utf-8")
    # Reliability debt: open() without encoding, requests without timeout.
    (root / "app" / "io_debt.py").write_text(
        "import requests\n\n\n"
        "def read(p):\n    return open(p).read()\n\n\n"
        "def fetch(u):\n    return requests.get(u)\n",
        encoding="utf-8")


def _build_empty(root):
    # No modules at all — exercises the empty/profile-default paths.
    (root / "README.md").write_text("# empty\n", encoding="utf-8")


@pytest.mark.parametrize("builder", [_build_clean, _build_lossy, _build_empty])
def test_grade_byte_identical_vs_head(tmp_path, builder):
    orig = _load_original(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    builder(proj)
    assert _snapshot(current.grade(proj)) == _snapshot(orig.grade(proj))


@pytest.mark.parametrize("builder", [_build_clean, _build_lossy, _build_empty])
def test_collect_metrics_identical_vs_head(tmp_path, builder):
    orig = _load_original(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    builder(proj)
    from app.tools.project_profile import ProjectProfiler

    prof_cur = ProjectProfiler(str(proj)).profile(light=True)
    prof_orig = ProjectProfiler(str(proj)).profile(light=True)
    m_cur = current._collect_metrics(proj, prof_cur)
    m_orig = orig._collect_metrics(proj, prof_orig)
    from dataclasses import asdict

    cur = asdict(m_cur)
    # _GradeMetrics gained stub-debt fields (folded into Correctness). On these
    # no-stub fixtures they are the INERT defaults, so the grade is byte-identical
    # to HEAD; every pre-existing metric must still match HEAD exactly.
    assert cur.pop("stub_debt") == 0
    assert cur.pop("top_stub_files") == []
    assert cur == asdict(m_orig)


@pytest.mark.parametrize("builder", [_build_clean, _build_lossy, _build_empty])
def test_scan_own_modules_identical_vs_head(tmp_path, builder):
    orig = _load_original(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    builder(proj)
    from app.tools.project_profile import ProjectProfiler

    prof = ProjectProfiler(str(proj)).profile(light=True)
    assert current._scan_own_modules(proj, prof) == orig._scan_own_modules(proj, prof)
