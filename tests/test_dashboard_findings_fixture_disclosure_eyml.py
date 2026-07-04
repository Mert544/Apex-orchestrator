"""examples/ fixture disclosure in the dashboard's "Scan findings" card
(ÇAĞ2-W11, item 2).

``apex grade`` already EXCLUDES example/test/fixture findings from its score
(``health_score._is_fixture_path`` / ``ProjectProfiler._is_fixture_path`` drop
them from the modules the security scan is charged against) — an
``examples/legacy_bank/...`` demo vulnerability is an intentional teaching
fixture, not a real risk in this project's own shipped code. ``SecurityAgent``
(which feeds the dashboard) does NOT apply that exclusion: it keeps every
finding in the raw scan, on purpose, so nothing the scanner saw is silently
dropped. Before this fix the dashboard rendered those fixture findings exactly
like a real one — misleading, since a reader has no way to tell "16 security
findings" apart from "16 demo vulnerabilities intentionally planted in
examples/". These tests pin the fix: fixture findings stay fully VISIBLE
(never hidden) but are now labelled in place, and a summary chip discloses how
many of the raw count are excluded-from-grade fixtures.
"""

from __future__ import annotations

from app.reporting.dashboard_sections import (
    _findings_chips,
    _findings_row,
    _findings_section,
    _is_fixture_path,
)


# --- _is_fixture_path: the same rule the grade already uses ------------------

def test_is_fixture_path_matches_examples_tests_fixtures_dirs():
    assert _is_fixture_path("examples/legacy_bank/app/accounts.py")
    assert _is_fixture_path("example/demo.py")
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("fixtures/bad.py")
    assert _is_fixture_path("nested/examples/deep/file.py")
    assert _is_fixture_path("nested/tests/deep/file.py")


def test_is_fixture_path_matches_test_prefixed_name_anywhere():
    assert _is_fixture_path("some/dir/test_helper.py")


def test_is_fixture_path_normalizes_backslashes_and_case():
    assert _is_fixture_path("Examples\\Legacy_Bank\\App\\Accounts.py")


def test_is_fixture_path_rejects_real_shipped_code():
    assert not _is_fixture_path("app/execution/objectives/harden.py")
    assert not _is_fixture_path("app/main.py")
    # "example" must be a real path component, not merely a substring of one.
    assert not _is_fixture_path("app/exemplary_module.py")


# --- _findings_row: the finding stays visible, now labelled in place --------

def test_findings_row_labels_fixture_finding_intentional():
    row = _findings_row(
        {"file": "examples/legacy_bank/app/accounts.py", "line": 23,
         "details": "Detected eval at line 23", "severity": "critical"},
        "—",
    )
    assert "examples/legacy_bank/app/accounts.py" in row  # never hidden
    assert "Detected eval at line 23" in row
    assert "intentional fixture" in row
    assert "excluded from grade" in row


def test_findings_row_real_finding_carries_no_fixture_note():
    row = _findings_row(
        {"file": "app/main.py", "line": 2, "details": "eval() on input", "severity": "high"},
        "—",
    )
    assert "intentional fixture" not in row
    assert "excluded from grade" not in row


# --- _findings_chips: a disclosed count, never a silent drop ---------------

def test_findings_chips_discloses_fixture_count_when_present():
    findings = {
        "security": {
            "findings_count": 3,
            "findings": [
                {"file": "examples/legacy_bank/app/accounts.py", "line": 23, "severity": "critical"},
                {"file": "examples/ml_pipeline/app/pipeline.py", "line": 17, "severity": "high"},
                {"file": "app/main.py", "line": 2, "severity": "high"},
            ],
        },
    }
    chips = _findings_chips(findings)
    assert "3</div>" in chips or "3<" in chips  # the raw, undiminished total is still shown
    assert "intentional fixtures" in chips
    assert "excluded from grade" in chips
    assert "2" in chips  # exactly 2 of the 3 are fixtures


def test_findings_chips_omits_fixture_chip_when_none_present():
    # No fixture findings -> byte-identical to the pre-fix chips (no new chip).
    findings = {
        "security": {
            "findings_count": 1,
            "findings": [{"file": "app/main.py", "line": 2, "severity": "high"}],
        },
    }
    chips = _findings_chips(findings)
    assert "intentional fixtures" not in chips


def test_findings_chips_empty_findings_is_untouched():
    assert "intentional fixtures" not in _findings_chips({})


# --- _findings_section: end-to-end, still never hides a finding ------------

def test_findings_section_all_fixture_findings_still_all_shown():
    findings = {
        "security": {
            "findings_count": 2,
            "findings": [
                {"file": "examples/legacy_bank/app/accounts.py", "line": 23,
                 "details": "Detected eval at line 23", "severity": "critical"},
                {"file": "examples/ml_pipeline/app/pipeline.py", "line": 17,
                 "details": "Detected yaml.load at line 17", "severity": "high"},
            ],
        },
    }
    out = _findings_section(findings)
    assert "examples/legacy_bank/app/accounts.py" in out
    assert "examples/ml_pipeline/app/pipeline.py" in out
    # One label per row (2) plus the summary chip (1) -- both disclose, never hide.
    assert out.count("intentional fixture") == 3
    assert "excluded from grade" in out
