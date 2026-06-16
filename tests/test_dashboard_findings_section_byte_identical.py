"""Characterization harness proving the refactor of ``_findings_section`` is
byte-identical to the original at git HEAD.

``_findings_section`` was decomposed into small pure helpers (chips builder,
best-effort exposure lookup, per-row renderer, table builder). This test loads
the *original* function body from ``git show HEAD:<file>`` into an isolated
module, then renders the FULL HTML string for a battery of representative
finding shapes through both the original and the refactored implementation and
asserts exact (byte-for-byte) equality. It covers: no findings (the empty-table
gate), populated findings with mixed/absent fields, the >12 truncation, the
coverage bar present/absent, HTML-special characters (escaping), and the
project_root exposure path (present + best-effort failure).

Offline, stdlib-only, deterministic — no network, no time/random assertions.
"""

import os
import subprocess
import sys
import types

import pytest

from app.reporting import dashboard_sections as REFACTORED

_REL = "app/reporting/dashboard_sections.py"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_original():
    """Compile the HEAD version of the module under a throwaway module name."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_REL}"], cwd=_REPO
    ).decode("utf-8")
    mod = types.ModuleType("_dashboard_sections_head_findings")
    mod.__file__ = os.path.join(_REPO, _REL)
    sys.modules["_dashboard_sections_head_findings"] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


ORIGINAL = _load_original()


# --- finding fixtures spanning the matrix -----------------------------------

def _findings_empty():
    return {}


def _findings_no_security():
    return {
        "security": {"findings_count": 0, "findings": []},
        "docstring": {"gaps_found": 7},
        "coverage": {"coverage_ratio": 0.82},
        "dependency": {"total_edges": 41, "circular_imports": [["a", "b"]]},
    }


def _findings_populated():
    return {
        "security": {
            "findings_count": 3,
            "findings": [
                {"file": "app/x.py", "line": 10, "details": "eval used",
                 "severity": "critical"},
                {"file": "app/y.py", "line": 22, "risk_type": "sql injection",
                 "severity": "high"},
                {"file": "app/z.py", "line": 3, "severity": "low"},
            ],
        },
        "docstring": {"gaps_found": 2},
        "coverage": {"coverage_ratio": 0.25},
        "dependency": {"total_edges": 9, "circular_imports": []},
    }


def _findings_no_coverage():
    return {
        "security": {
            "findings_count": 1,
            "findings": [
                {"file": "app/q.py", "line": 1, "issue": "hardcoded secret",
                 "severity": "medium"},
            ],
        },
        "dependency": {"total_edges": 0},
    }


def _findings_special_chars():
    return {
        "security": {
            "findings_count": 1,
            "findings": [
                {"file": "app/<weird> & co.py", "line": "?",
                 "risk": "a < b && c > d \"x\" 'y'", "severity": "HIGH"},
            ],
        },
        "coverage": {"coverage_ratio": 0.5},
    }


def _findings_truncation():
    return {
        "security": {
            "findings_count": 20,
            "findings": [
                {"file": f"app/m{i}.py", "line": i,
                 "details": f"finding {i}", "severity": "low"}
                for i in range(20)
            ],
        },
        "coverage": {"coverage_ratio": 0.99},
    }


def _findings_missing_fields():
    return {
        "security": {
            "findings": [
                {},
                {"severity": ""},
                {"file": "app/only.py"},
            ],
        },
    }


_FIXTURES = [
    _findings_empty,
    _findings_no_security,
    _findings_populated,
    _findings_no_coverage,
    _findings_special_chars,
    _findings_truncation,
    _findings_missing_fields,
]


@pytest.mark.parametrize("make", _FIXTURES, ids=[f.__name__ for f in _FIXTURES])
def test_findings_section_byte_identical_no_root(make):
    findings = make()
    before = ORIGINAL._findings_section(findings)
    after = REFACTORED._findings_section(findings)
    assert before == after, "rendered HTML diverged from HEAD original"


@pytest.mark.parametrize("make", _FIXTURES, ids=[f.__name__ for f in _FIXTURES])
def test_findings_section_byte_identical_with_root(make, tmp_path):
    # project_root drives the best-effort exposure path. Against an empty tree
    # the analyzer either yields neutral "—" rows or fails closed; either way
    # both implementations must agree byte-for-byte.
    findings = make()
    root = str(tmp_path)
    before = ORIGINAL._findings_section(findings, root)
    after = REFACTORED._findings_section(findings, root)
    assert before == after, "rendered HTML diverged from HEAD original"


def test_findings_section_empty_table_gate():
    out = REFACTORED._findings_section({})
    assert "No security findings 🎉" in out
    assert out == ORIGINAL._findings_section({})


def test_findings_exposures_empty_inputs():
    # No root or no findings -> no exposure lookup, returns [] (never raises).
    assert REFACTORED._findings_exposures([], "") == []
    assert REFACTORED._findings_exposures([{"file": "a.py", "line": 1}], "") == []
    assert REFACTORED._findings_exposures([], "/some/root") == []


def test_findings_exposures_failure_degrades_to_empty(monkeypatch):
    # A raising analyzer is swallowed: best-effort -> [].
    import app.engine.exposure as exposure_mod

    def _boom(root, pairs):
        raise RuntimeError("no git")

    monkeypatch.setattr(exposure_mod, "analyze_exposure", _boom)
    out = REFACTORED._findings_exposures(
        [{"file": "a.py", "line": 1}], "/some/root"
    )
    assert out == []


def test_findings_chips_pure():
    # Pure helper: chip markup is deterministic and the substrings appear in the
    # full original render, anchoring the decomposition boundary.
    f = _findings_populated()
    chips = REFACTORED._findings_chips(f)
    assert chips == REFACTORED._findings_chips(f)  # deterministic
    assert chips in ORIGINAL._findings_section(f)


def test_findings_row_pure_escapes():
    # Per-row helper escapes codebase-sourced strings and stamps the exposure.
    row = REFACTORED._findings_row(
        {"file": "a<b>.py", "line": 5, "details": "x & y", "severity": "high"},
        "2 months",
    )
    assert "a&lt;b&gt;.py" in row
    assert "x &amp; y" in row
    assert "2 months" in row


def test_findings_table_empty_rows_gate():
    # No rows -> the empty placeholder row, matching the original's fallback.
    assert REFACTORED._findings_table([], []) == (
        "<table><thead><tr><th>Location</th><th>Issue</th><th>Severity</th>"
        "<th>Exposure</th></tr></thead><tbody>"
        "<tr><td colspan=4 class=empty>No security findings 🎉</td></tr>"
        "</tbody></table>"
    )
