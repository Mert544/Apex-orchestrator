"""Branch-level edge coverage for app.engine.diff_review.

Targets the genuinely-uncovered branch from `--cov-branch` term-missing
(525->528: a result that HAS findings but none high/medium, so the summary's
notable list is empty and the trailing blank line is skipped) plus a handful of
adjacent boundary paths the existing suites don't pin down: the multi-line hunk
expansion in changed_lines, the rule-finding on-diff emission, the no-callers
impact skip, the markdown limit/footer, and the summary's file/finding
pluralization. Deterministic and hermetic — no network, no time/order asserts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.diff_review import (
    ReviewFinding,
    ReviewResult,
    _change_impacts,
    _compiled_rules,
    _rule_findings,
    changed_lines,
    render_review_markdown,
    render_review_summary,
    review,
)


def _git(tmp_path: Path, *cmds) -> None:
    for c in cmds:
        subprocess.run(c, cwd=tmp_path, capture_output=True)


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(base="HEAD", files_reviewed=1, findings=findings)


# --- the uncovered summary branch: findings present, but none notable --------

def test_summary_low_only_findings_skip_trailing_blank(tmp_path):
    # total > 0 but `notable` (high/medium) is empty -> `shown` is falsy, so the
    # `if shown:` blank-line append is skipped (branch 525->528) and the footer
    # follows the count line directly with no notable bullets in between.
    result = _result([
        ReviewFinding("app/m.py", 2, "refactor", "low", "tiny single-use helper",
                      False, "inline"),
        ReviewFinding("app/m.py", 9, "docs", "low", "missing docstring", True, ""),
    ])
    out = render_review_summary(result)
    assert out.startswith("## 🟢 Apex review: no high-severity issues in this diff")
    assert "2 findings across 1 changed file; 1 auto-fixable" in out
    # No high/medium bullets were rendered at all.
    assert "- 🔴" not in out and "- 🟠" not in out
    # Footer is reached with exactly one blank line before it (the count's), not two.
    assert out.endswith(
        "1 auto-fixable with `apex review --fix`.\n\n"
        "_Deterministic review — same diff always yields this verdict. "
        "Zero tokens, runs offline. Apex Orchestrator._"
    )


def test_summary_low_only_is_deterministic(tmp_path):
    result = _result([
        ReviewFinding("app/m.py", 2, "refactor", "low", "tiny helper", False, "inline"),
    ])
    assert render_review_summary(result) == render_review_summary(result)


# --- changed_lines: multi-line hunk count expansion --------------------------

def test_changed_lines_expands_multi_line_hunk(monkeypatch, tmp_path):
    # A hunk header `+5,3` adds lines 5,6,7 (range start..start+count). Confirms
    # the count!=None arm and the range expansion (lines 116-118).
    import app.engine.diff_review as dr

    class FakeOut:
        returncode = 0
        stdout = (
            "diff --git a/app/m.py b/app/m.py\n"
            "+++ b/app/m.py\n"
            "@@ -1,0 +5,3 @@\n"
            "+a = 1\n+b = 2\n+c = 3\n"
        )

    monkeypatch.setattr(dr.subprocess, "run", lambda *a, **k: FakeOut())
    assert changed_lines(str(tmp_path)) == {"app/m.py": {5, 6, 7}}


def test_changed_lines_single_line_hunk_defaults_count_to_one(monkeypatch, tmp_path):
    # A hunk header with no count (`+8`) defaults count to 1 -> just line 8
    # (the `if m.group(2) is not None else 1` else-arm at line 116).
    import app.engine.diff_review as dr

    class FakeOut:
        returncode = 0
        stdout = "+++ b/app/m.py\n@@ -3 +8 @@\n+x = 1\n"

    monkeypatch.setattr(dr.subprocess, "run", lambda *a, **k: FakeOut())
    assert changed_lines(str(tmp_path)) == {"app/m.py": {8}}


def test_changed_lines_hunk_before_any_file_is_ignored(monkeypatch, tmp_path):
    # A `@@` line that appears while `current` is still None (no preceding
    # `+++ b/`) is skipped by the `current is not None` guard (line 111 False).
    import app.engine.diff_review as dr

    class FakeOut:
        returncode = 0
        stdout = "@@ -1 +1 @@\n+orphan = 1\n"

    monkeypatch.setattr(dr.subprocess, "run", lambda *a, **k: FakeOut())
    assert changed_lines(str(tmp_path)) == {}


# --- _rule_findings: the on-diff emission (positive control) ------------------

def test_rule_findings_emits_for_match_on_diff(tmp_path):
    # The mirror of the existing off-diff skip test: when the matched line IS in
    # the changed set, a convention finding is emitted (the 219 True branch).
    from app.execution.rewrite_rules import save_rule

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "base.py").write_text("def existing():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    save_rule(str(tmp_path), "no-len-zero", "len($x) == 0", "not $x")
    compiled = _compiled_rules(str(tmp_path))
    src = "def chk(xs):\n    return len(xs) == 0\n"
    out = _rule_findings(str(tmp_path), "m.py", src, {2}, compiled)
    assert len(out) == 1
    f = out[0]
    assert f.category == "convention"
    assert f.severity == "medium"
    assert f.auto_fixable is True
    assert f.fix_kind == "rule:no-len-zero"
    assert f.line == 2


# --- _change_impacts: a touched function with no callers is dropped ----------

def test_change_impacts_drops_function_without_callers(tmp_path):
    # A changed function that nobody calls produces no ChangeImpact (line 387
    # `if callers:` False) — the impact list stays empty even though the function
    # was touched.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "solo.py").write_text("def base():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    # Add a brand-new uncalled function.
    (tmp_path / "app" / "solo.py").write_text(
        "def base():\n    return 1\n\n\ndef lonely():\n    return 2\n")
    changes = changed_lines(str(tmp_path))
    sources = {rel: (Path(tmp_path) / rel).read_text(encoding="utf-8") for rel in changes}
    impacts = _change_impacts(str(tmp_path), changes, sources)
    assert all(i.function != "lonely" for i in impacts)


def test_change_impacts_skips_file_with_no_loaded_source(tmp_path):
    # When a changed file has no entry in `sources` (e.g. it failed to read in
    # review()), _change_impacts skips it via the `if not source` guard (line
    # 374) rather than crashing.
    changes = {"app/ghost.py": {1, 2}}
    assert _change_impacts(str(tmp_path), changes, {}) == []


# --- render_review_markdown: limit + hidden footer ---------------------------

def test_render_markdown_limit_truncates_and_notes_hidden():
    findings = [ReviewFinding(f"app/m{i}.py", i + 1, "security", "high",
                              f"issue {i}", False, "") for i in range(5)]
    md = render_review_markdown(_result(findings), limit=2)
    assert "and **3 more** finding(s)" in md
    # Only the first two file refs are listed.
    assert "`app/m0.py:1`" in md
    assert "`app/m4.py:5`" not in md


def test_render_markdown_no_changed_files_short_circuits():
    md = render_review_markdown(ReviewResult(base="origin/main", files_reviewed=0))
    assert "_No changed Python files to review._" in md
    assert "changes since `origin/main`" in md


def test_render_markdown_clean_diff_celebrates():
    md = render_review_markdown(ReviewResult(base="HEAD", files_reviewed=3))
    assert "Reviewed 3 changed file(s)." in md
    assert "No issues found in the changed lines" in md


def test_render_markdown_impacts_section_more_suffix():
    # caller_count exceeds the listed callers -> "(+N more)" suffix appears.
    from app.engine.diff_review import ChangeImpact

    result = ReviewResult(
        base="HEAD", files_reviewed=1,
        impacts=[ChangeImpact(file="app/m.py", function="parse", lineno=3,
                              caller_count=10, callers=["app/a.py:1", "app/b.py:2"])],
    )
    md = render_review_markdown(result)
    assert "Change impact" in md
    assert "**parse()**" in md
    assert "(+8 more)" in md


# --- render_review_summary: pluralization boundaries -------------------------

def test_summary_singular_file_and_finding_words():
    result = _result([
        ReviewFinding("app/m.py", 5, "security", "high", "single high issue", True, "eval"),
    ])
    out = render_review_summary(result)
    assert "1 finding across 1 changed file;" in out


def test_summary_plural_files_and_findings_words():
    result = ReviewResult(
        base="HEAD", files_reviewed=2,
        findings=[
            ReviewFinding("app/a.py", 1, "security", "high", "issue a", False, ""),
            ReviewFinding("app/b.py", 2, "security", "medium", "issue b", False, ""),
        ],
    )
    out = render_review_summary(result)
    assert "2 findings across 2 changed files;" in out


def test_summary_top_zero_lists_all_notable():
    findings = [ReviewFinding(f"app/m{i}.py", i + 1, "security", "high",
                              f"issue {i}", False, "") for i in range(4)]
    result = ReviewResult(base="HEAD", files_reviewed=4, findings=findings)
    out = render_review_summary(result, top=0)
    assert out.count("- 🔴") == 4
    assert "+0 more" not in out
    assert "more" not in out.split("Apex review")[1].split("issue 0")[0]


# --- review() end-to-end: a real high finding lands on the diff --------------

def test_review_flags_eval_on_changed_line(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    (tmp_path / "app" / "m.py").write_text(
        "def base():\n    return 1\n\n\ndef bad(c):\n    return eval(c)\n")
    result = review(str(tmp_path))
    assert result.files_reviewed == 1
    evals = [f for f in result.findings if f.fix_kind == "eval"]
    assert evals and evals[0].severity == "high"
    assert evals[0].file == "app/m.py"
