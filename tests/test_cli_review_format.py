"""`apex review --format X` fans findings out to CI-interop serializers.

This wires the new exporter modules (CodeClimate/GitLab, JUnit, GitHub
annotations, SonarQube generic, CSV, HTML) plus the existing SARIF into the
review command, so Apex drops into an existing pipeline next to — or in place
of — SonarQube/CodeClimate. Each format is the sole stdout when selected.
"""

from __future__ import annotations

import argparse
import json

import pytest

import app.engine.diff_review as diff_review
from app.cli_review import _render_findings_format, cmd_review
from app.engine.diff_review import ReviewFinding, ReviewResult


def _result() -> ReviewResult:
    return ReviewResult(
        base="HEAD",
        files_reviewed=2,
        findings=[
            ReviewFinding(file="app/a.py", line=10, category="security",
                          severity="high", message="eval() of user input",
                          auto_fixable=True, fix_kind="rule:eval"),
            ReviewFinding(file="app/b.py", line=3, category="style",
                          severity="low", message="long function",
                          auto_fixable=False),
        ],
    )


def _ns(**kw) -> argparse.Namespace:
    base = dict(target="", base="HEAD", summary=False, fix=False, sarif="",
                json=False, max_findings=0, fail_on_high=False, format="",
                format_out="")
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _patch_review(monkeypatch):
    monkeypatch.setattr(diff_review, "review", lambda *a, **k: _result())


def test_render_each_format_is_nonempty_and_distinct():
    r = _result()
    sarif = _render_findings_format("sarif", r)
    assert json.loads(sarif)["version"] == "2.1.0"
    assert json.loads(_render_findings_format("codeclimate", r))  # JSON array
    assert "<testsuite" in _render_findings_format("junit", r)
    assert "::error" in _render_findings_format("github", r)
    assert json.loads(_render_findings_format("sonar", r))["issues"]
    assert "severity" in _render_findings_format("csv", r).splitlines()[0]
    assert _render_findings_format("html", r).startswith("<!")


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        _render_findings_format("nope", _result())


@pytest.mark.parametrize("fmt,needle", [
    ("codeclimate", "fingerprint"),
    ("junit", "<testsuite"),
    ("github", "::error"),
    ("sonar", '"issues"'),
    ("csv", "severity"),
    ("html", "<!"),
    ("sarif", "2.1.0"),
])
def test_cmd_review_format_to_stdout(capsys, fmt, needle):
    rc = cmd_review(_ns(format=fmt))
    assert rc == 0
    out = capsys.readouterr().out
    assert needle in out


def test_cmd_review_format_out_writes_file(tmp_path, capsys):
    out = tmp_path / "report" / "cq.json"
    rc = cmd_review(_ns(format="codeclimate", format_out=str(out)))
    assert rc == 0
    assert out.exists()
    assert json.loads(out.read_text())  # a valid CodeClimate JSON array
    assert "written to" in capsys.readouterr().out


def test_cmd_review_format_fail_on_high_exit_code(capsys):
    # A high-severity finding in the diff fails the gate even in format mode.
    rc = cmd_review(_ns(format="junit", fail_on_high=True))
    capsys.readouterr()
    assert rc == 1
