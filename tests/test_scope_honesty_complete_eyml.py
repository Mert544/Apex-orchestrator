"""COMPLETE + single-sourced honest analyzed-ratio across ALL scope surfaces.

A prior fix (78b9f53) made ``apex scope`` parse-aware but it was INCOMPLETE and
INCONSISTENT:

DEFECT 1 — the honest numerator only subtracted *parse-failures* from a strictly
larger counted set, so in-language files dropped for OTHER reasons were still
falsely counted as "analysed":
  - ``.pyi`` stubs: counted in ``python_file_count`` but the structure analyzer's
    ``iter_source_files('*.py')`` walk NEVER yields them, so a ``.pyi``-only repo
    reported "analyses 100% (all Python)";
  - files past the structure-scan cap: a broken file sorting past the analyzer's
    cap was invisible, so the repo reported 100% with the broken file unseen.

DEFECT 2 — only ``cli_insight._scope_report`` was fixed; the grade/pulse footer,
the readiness scope section and the dashboard scope tile still read the raw
LANGUAGE ratio, so ONE repo reported DIFFERENT honesty numbers per surface.

The complete fix makes "analysed" a SINGLE SOURCE OF TRUTH — a ``.py`` file the
structure analyzer would build a module from, i.e. one that parses — and routes
EVERY surface through the same ``analyzed_ratio_honest`` + ``unanalyzed_count``.

These tests pin:
  - a ``.pyi``-only (and ``.pyi``-with-broken) repo → ratio < 100%, ``.pyi`` NAMED;
  - a 600-valid + 1-broken-past-the-cap repo → ratio < 100%, broken file NAMED;
  - a parse-failure repo → still honest (regression-guard for 78b9f53);
  - the SAME repo reports the SAME number from scope AND pulse AND readiness AND
    dashboard (cross-surface consistency);
  - an ALL-analysed repo → byte-identical scope/pulse/readiness/dashboard vs the
    pre-fix language-ratio path (the common-case no-regression, pinned hard);
  - determinism across two runs.

Offline, stdlib + pytest only.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

from app.cli_insight import _scope_report, cmd_scope, render_scope_markdown
from app.cli_reporting import _pulse_scope
from app.engine.readiness_report import _scope_section
from app.reporting.dashboard import _hero_scope_pct
from app.reporting.dashboard_sections import _scope_composition
from app.tools.project_profile import (
    ProjectProfiler,
    render_analysis_scope_line,
)


# --- helpers ----------------------------------------------------------------

def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _run_scope(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _surface_pcts(root: Path) -> dict[str, int]:
    """The analysed-percentage every honest surface reports for ``root``."""
    profile = ProjectProfiler(str(root)).profile(light=True)
    rep = _scope_report(root)
    pulse = _pulse_scope(root)
    section = _scope_section(profile)
    return {
        "scope": int(rep["analyzed_pct"]),
        "pulse": int(pulse["analyzed_pct"]),
        "readiness": int(round(section["analyzed_ratio"] * 100)),
        "dashboard": int(_hero_scope_pct(profile)),
    }


# --- DEFECT 1a: a .pyi-only repo is NOT 100% analysed -----------------------

def test_pyi_only_repo_is_not_fully_analyzed_and_names_stub(tmp_path: Path):
    """A ``.pyi``-only repo: the LANGUAGE ratio claims 100%, but the structure
    analyzer never walks a ``.pyi``, so the HONEST ratio is 0% and the stub is
    NAMED (the exact 78b9f53 blind spot — parse-failure-only accounting)."""
    _write(tmp_path, "stubs/mod.pyi", "def f() -> int: ...\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    # Legacy LANGUAGE ratio still counts the .pyi as "Python" -> 100%.
    assert profile.python_file_count == 1
    assert profile.analyzed_ratio == 1.0
    # ...but NOTHING was actually analysed, and the stub is named.
    assert profile.unanalyzed_count == 1
    assert profile.unanalyzed_files == ["stubs/mod.pyi"]
    assert profile.analyzed_ratio_honest == 0.0
    # Back-compat alias carries the SAME complete set, not only parse-failures.
    assert profile.unparsed_count == 1
    assert profile.unparsed_files == ["stubs/mod.pyi"]


def test_pyi_with_broken_py_counts_both(tmp_path: Path):
    """A ``.pyi`` stub AND a broken ``.py`` are BOTH disclosed (the complete set
    spans more than one drop reason)."""
    _write(tmp_path, "src/good.py", "def f():\n    return 1\n")
    _write(tmp_path, "src/iface.pyi", "class P: ...\n")
    _write(tmp_path, "src/broken.py", "def f(:\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    # 3 in-language files; only good.py is truly analysed.
    assert profile.python_file_count == 3
    assert sorted(profile.unanalyzed_files) == ["src/broken.py", "src/iface.pyi"]
    assert profile.unanalyzed_count == 2
    # 1 of 3 source files analysed.
    assert abs(profile.analyzed_ratio_honest - (1 / 3)) < 1e-9
    rep = _scope_report(tmp_path)
    assert rep["all_python"] is False
    assert rep["analyzed_pct"] == 33


def test_pyi_named_in_scope_markdown(tmp_path: Path):
    """The scope markdown NAMES the ``.pyi`` and never claims 100% (all Python)."""
    _write(tmp_path, "stubs/a.pyi", "x: int\n")
    rc, out = _run_scope(tmp_path)
    assert rc == 0
    assert "Apex analyses 100% of this repo (all Python)." not in out
    assert "stubs/a.pyi" in out


# --- DEFECT 1b: an over-cap broken file is NOT hidden -----------------------

def _over_cap_repo(root: Path, n_valid: int = 600) -> str:
    """``n_valid`` valid ``.py`` files plus ONE broken file that sorts LAST, i.e.
    PAST the structure-scan cap (500). Returns the broken file's rel path."""
    for i in range(n_valid):
        _write(root, f"pkg/m{i:04d}.py", "x = 1\n")
    broken = "pkg/zzz_broken.py"  # sorts after every m####.py -> position > 500
    _write(root, broken, "def f(:\n")
    return broken


def test_over_cap_broken_file_is_disclosed_not_hidden(tmp_path: Path):
    """600 valid + 1 broken sorting past the structure-scan cap → the repo reports
    < 100% and NAMES the broken file (the accounting walk runs to the PROFILER's
    cap, so a file past the smaller structure-scan cap is no longer invisible)."""
    broken = _over_cap_repo(tmp_path, n_valid=600)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.python_file_count == 601
    assert profile.unanalyzed_count == 1
    assert broken in profile.unanalyzed_files
    assert profile.analyzed_ratio_honest < 1.0
    rep = _scope_report(tmp_path)
    assert rep["all_python"] is False
    assert rep["analyzed_pct"] < 100
    assert broken in rep["unparsed_files"]


# --- DEFECT 1 regression-guard for 78b9f53: a parse-failure stays honest -----

def test_plain_parse_failure_still_honest(tmp_path: Path):
    """The original 78b9f53 case still works: one syntax-error ``.py`` of two ->
    50% honest, named. Guards against a regression in the rewritten accounting."""
    _write(tmp_path, "pkg/good.py", "def f():\n    return 1\n")
    _write(tmp_path, "pkg/broken.py", "def f(:\n    return 1\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.analyzed_ratio == 1.0          # language ratio unchanged
    assert profile.analyzed_ratio_honest == 0.5   # honest ratio
    assert profile.unanalyzed_files == ["pkg/broken.py"]


# --- DEFECT 2: cross-surface consistency — ONE honest number everywhere ------

def test_all_surfaces_report_same_number_on_dropped_repo(tmp_path: Path):
    """scope == pulse == readiness == dashboard on a repo WITH a dropped file."""
    _write(tmp_path, "pkg/good.py", "def f():\n    return 1\n")
    _write(tmp_path, "pkg/broken.py", "def f(:\n")
    pcts = _surface_pcts(tmp_path)
    assert pcts == {"scope": 50, "pulse": 50, "readiness": 50, "dashboard": 50}


def test_all_surfaces_agree_on_pyi_only_repo(tmp_path: Path):
    """A ``.pyi``-only repo reports 0% analysed from EVERY surface (not 100%)."""
    _write(tmp_path, "stubs/a.pyi", "x: int\n")
    pcts = _surface_pcts(tmp_path)
    assert pcts == {"scope": 0, "pulse": 0, "readiness": 0, "dashboard": 0}


def test_pulse_and_grade_footer_drop_all_python_when_dropped(tmp_path: Path):
    """The pulse ``all_python`` reassurance flips OFF when an in-language file was
    not analysed, and the grade scope line discloses the gap instead of staying
    silent."""
    _write(tmp_path, "pkg/good.py", "def f():\n    return 1\n")
    _write(tmp_path, "pkg/broken.py", "def f(:\n")
    pulse = _pulse_scope(tmp_path)
    assert pulse["all_python"] is False
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    line = render_analysis_scope_line(profile)
    assert line != ""  # no longer the silent "" for an all-Python broken repo
    assert "not analysed" in line or "could not be analysed" in line


# --- COMMON CASE (hard pin): an all-analysed repo is byte-identical ----------

def _all_analyzed_repo(root: Path) -> None:
    """All-Python, all-parseable, no ``.pyi``, well under any cap — the common
    case (this is the shape of Apex itself and every clean fixture)."""
    _write(root, "app/core.py", "def f():\n    return 1\n")
    _write(root, "app/util.py", "VALUE = 2\n")
    _write(root, "app/model.py", "class M:\n    pass\n")


def _polyglot_clean_repo(root: Path) -> None:
    """A polyglot repo with NO dropped files — exercises the non-trivial
    out-of-scope branch of every surface while keeping unanalyzed == 0."""
    _write(root, "app/core.py", "def f():\n    return 1\n")
    _write(root, "web/app.js", "const x = 1;\nconsole.log(x);\n")
    _write(root, "web/style.css", "body { margin: 0; }\n")


def test_common_case_honest_equals_language_ratio(tmp_path: Path):
    """With NOTHING dropped the honest ratio EQUALS the raw language ratio (the
    invariant that makes the common case byte-identical)."""
    _all_analyzed_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.unanalyzed_count == 0
    assert profile.analyzed_ratio_honest == profile.analyzed_ratio == 1.0


def test_common_case_scope_byte_identical(tmp_path: Path):
    """An all-analysed repo's scope markdown is the SAME bytes the pre-fix
    LANGUAGE-ratio path produced (no dropped-file section, no ratio shift)."""
    _all_analyzed_repo(tmp_path)
    rc, out = _run_scope(tmp_path)
    assert rc == 0
    # The reassuring all-Python headline is intact (proves no spurious drop).
    assert "Apex analyses 100% of this repo (all Python)." in out
    # And nothing about parsing/exclusion leaks into the clean page.
    assert "could not be" not in out
    assert "not analysed" not in out


def test_common_case_all_surfaces_report_100(tmp_path: Path):
    """Every surface still reports 100% on a clean all-Python repo."""
    _all_analyzed_repo(tmp_path)
    pcts = _surface_pcts(tmp_path)
    assert pcts == {"scope": 100, "pulse": 100, "readiness": 100, "dashboard": 100}


def test_common_case_pulse_all_python_reassurance_kept(tmp_path: Path):
    """The pulse keeps its ``all_python`` reassurance on a clean repo (byte-level
    no-regression for the footer)."""
    _all_analyzed_repo(tmp_path)
    pulse = _pulse_scope(tmp_path)
    assert pulse == {
        "all_python": True,
        "analyzed_pct": 100,
        "out_of_scope_pct": 0,
        "files": [],
    }


def test_common_case_dashboard_scope_composition_omitted(tmp_path: Path):
    """An all-analysed all-Python repo renders NO scope-composition bar — its
    dashboard page stays byte-identical to before this feature existed."""
    _all_analyzed_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert _scope_composition(profile) == ""


def test_polyglot_clean_repo_unchanged_across_surfaces(tmp_path: Path):
    """A polyglot repo with NO dropped files: every surface reports the SAME
    language ratio it always did (honest == language because unanalyzed == 0), and
    the dashboard composition bar still renders (out-of-scope remainder exists)."""
    _polyglot_clean_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.unanalyzed_count == 0
    assert profile.analyzed_ratio_honest == profile.analyzed_ratio
    # The honest number matches the language ratio on every surface.
    expected = round(profile.analyzed_ratio * 100)
    pcts = _surface_pcts(tmp_path)
    assert pcts["scope"] == pcts["pulse"] == expected
    assert pcts["dashboard"] == expected
    # The composition bar renders for a genuine polyglot split.
    assert _scope_composition(profile) != ""


# --- determinism ------------------------------------------------------------

def test_determinism_across_two_runs(tmp_path: Path):
    """Byte-stable: two profiles + two scope renders of the same dropped-file repo
    are identical (sorted unanalyzed list, no clock/random)."""
    _write(tmp_path, "a/ok.py", "x = 1\n")
    _write(tmp_path, "a/zeta_broken.py", "def f(:\n")
    _write(tmp_path, "a/alpha_broken.py", "class C(:\n")
    _write(tmp_path, "a/iface.pyi", "y: int\n")
    p1 = ProjectProfiler(str(tmp_path)).profile()
    p2 = ProjectProfiler(str(tmp_path)).profile()
    assert p1.unanalyzed_files == p2.unanalyzed_files
    assert p1.unanalyzed_count == p2.unanalyzed_count
    assert p1.analyzed_ratio_honest == p2.analyzed_ratio_honest
    md1 = render_scope_markdown(_scope_report(tmp_path))
    md2 = render_scope_markdown(_scope_report(tmp_path))
    assert md1 == md2


def test_empty_repo_is_all_analyzed(tmp_path: Path):
    """An empty repo (no source files) trivially has nothing unanalysed and keeps
    the all-Python shape — the empty/edge path."""
    rep = _scope_report(tmp_path)
    assert rep["all_python"] is True
    assert rep["unparsed_count"] == 0
    assert rep["analyzed_pct"] == 100
