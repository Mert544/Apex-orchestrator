from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.cli import cmd_review
from app.engine.diff_review import (
    ReviewFinding,
    ReviewResult,
    render_review_markdown,
    render_review_summary,
    review,
)

_FOOTER = (
    "_Deterministic review — same diff always yields this verdict. "
    "Zero tokens, runs offline. Apex Orchestrator._"
)


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(target=str(tmp_path), base="HEAD", fail_on_high=False,
                json=False, fix=False, sarif="", max_findings=0, summary=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def _repo_with_change(tmp_path: Path, new_src: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
              ["git", "config", "user.name", "t"], ["git", "add", "-A"],
              ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=tmp_path, capture_output=True)
    (tmp_path / "app" / "m.py").write_text(new_src)
    return tmp_path


# --- render_review_summary directly (built ReviewResult) ---------------------

def test_summary_blocking_headline_and_finding():
    result = ReviewResult(
        base="HEAD", files_reviewed=1,
        findings=[ReviewFinding("app/m.py", 5, "security", "high",
                                "use of eval() on dynamic input", True, "eval")],
    )
    out = render_review_summary(result)
    assert out.startswith("## 🔴 Apex review: 1 high-severity issue(s) in this diff")
    assert "review before merge" in out
    assert "`app/m.py:5` — use of eval() on dynamic input" in out
    assert "1 finding across 1 changed file; 1 auto-fixable" in out
    assert out.rstrip().endswith(_FOOTER)


def test_summary_clean_headline_and_nothing_to_flag():
    result = ReviewResult(base="HEAD", files_reviewed=2, findings=[])
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues in this diff")
    assert "Nothing to flag in the changed lines." in out
    assert out.rstrip().endswith(_FOOTER)


def test_summary_empty_diff():
    result = ReviewResult(base="HEAD", files_reviewed=0, findings=[])
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues in this diff")
    assert "Nothing to flag in the changed lines." in out


def test_summary_medium_only_is_clean_but_lists_findings():
    # Medium findings are not blocking → 🟢 headline, but still surfaced.
    result = ReviewResult(
        base="HEAD", files_reviewed=1,
        findings=[ReviewFinding("app/m.py", 3, "convention", "medium",
                                "team convention re-entered", True, "rule:x")],
    )
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues")
    assert "`app/m.py:3` — team convention re-entered" in out


def test_summary_caps_with_more_note():
    findings = [ReviewFinding(f"app/m{i}.py", i, "security", "high",
                              f"issue {i}", False, "") for i in range(12)]
    result = ReviewResult(base="HEAD", files_reviewed=12, findings=findings)
    out = render_review_summary(result, top=8)
    assert out.count("- 🔴") == 8
    assert "+4 more" in out


def test_summary_high_in_fixture_is_not_blocking():
    # A high finding in test/fixture code is excluded from the blocking gate,
    # mirroring blocking_high_findings — headline stays 🟢.
    result = ReviewResult(
        base="HEAD", files_reviewed=1,
        findings=[ReviewFinding("tests/test_x.py", 5, "security", "high",
                                "eval in fixture", False, "")],
    )
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues")


def test_summary_is_deterministic():
    result = ReviewResult(
        base="HEAD", files_reviewed=1,
        findings=[ReviewFinding("app/m.py", 5, "security", "high",
                                "use of eval()", True, "eval")],
    )
    assert render_review_summary(result) == render_review_summary(result)


# --- over a real (hermetic) git repo -----------------------------------------

def test_summary_over_real_repo_high(tmp_path):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    result = review(str(tmp_path))
    out = render_review_summary(result)
    assert out.startswith("## 🔴 Apex review:")
    assert "eval()" in out


def test_summary_over_real_repo_clean(tmp_path):
    _repo_with_change(tmp_path,
                      "def base():\n    return 1\n\n\ndef ok(x):\n    \"\"\"D.\"\"\"\n    return x\n")
    result = review(str(tmp_path))
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues")
    assert "Nothing to flag in the changed lines." in out


# --- the --summary flag on cmd_review ----------------------------------------

def test_cli_summary_prints_only_summary(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path, summary=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("## 🔴 Apex review:")
    # ONLY the summary — none of the full report's headers.
    assert "# Apex review — changes since" not in out
    assert out.rstrip().endswith(_FOOTER)


def test_cli_summary_respects_fail_on_high(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path, summary=True, fail_on_high=True))
    assert rc == 1
    assert capsys.readouterr().out.startswith("## 🔴 Apex review:")


def test_cli_non_summary_output_unchanged(tmp_path, capsys):
    # Adding --summary must not perturb the default (non-summary) output: it is
    # byte-identical to render_review_markdown over the same result.
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    result = review(str(tmp_path))
    assert out == render_review_markdown(result, limit=0) + "\n"
    assert "## 🔴 Apex review:" not in out  # the summary headline never leaks in
