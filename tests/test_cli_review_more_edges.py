"""Edge-path coverage for app.cli_review.

Targets the genuinely-missing lines: the --sarif export path, the JSON
payload-with-fixes branch, the --max-findings cap in the rendered comment,
the rule-book --fix application (applied + blocked), the blocked-render
markdown, and register_parsers' argparse wiring.

Every apply/verify is monkeypatched so NO real pytest runs. Hermetic tmp
git repos use a fixed committer env with gpgsign off; no network, no
time/random/order assertions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.cli_review import (
    _apply_review_fixes,
    _render_review_fixes_markdown,
    cmd_review,
    register_parsers,
)
from app.engine.diff_review import ReviewFinding, ReviewResult


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(target=str(tmp_path), base="HEAD", fail_on_high=False, json=False,
                fix=False, sarif="", max_findings=0)
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


# --- --sarif export ----------------------------------------------------------

def test_review_writes_sarif_file_and_notes_it(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    sarif_path = tmp_path / "out" / "review.sarif"
    rc = cmd_review(_ns(tmp_path, sarif=str(sarif_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert f"SARIF written to {sarif_path}" in out
    assert sarif_path.exists()
    doc = json.loads(sarif_path.read_text())
    assert doc["version"] == "2.1.0"


def test_review_sarif_with_json_output_skips_note(tmp_path, capsys):
    # In JSON mode the human-readable "SARIF written" note is not printed, but
    # the file is still produced.
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    sarif_path = tmp_path / "review.sarif"
    rc = cmd_review(_ns(tmp_path, sarif=str(sarif_path), json=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "SARIF written" not in out
    assert sarif_path.exists()
    json.loads(out)  # the stdout is pure JSON


# --- --max-findings cap in the rendered comment ------------------------------

def test_review_max_findings_caps_rendered_comment(tmp_path, capsys):
    # Several findings on the diff; --max-findings=1 caps the listed lines and
    # adds the "more" footer (exercises the limit kwarg pass-through).
    _repo_with_change(
        tmp_path,
        "def base():\n    return 1\n\n"
        "def bad(c):\n    if c == None:\n        return eval(c)\n    return f\"x\"\n",
    )
    rc = cmd_review(_ns(tmp_path, max_findings=1))
    assert rc == 0
    out = capsys.readouterr().out
    assert "more** finding(s)" in out


# --- --fix JSON payload carries the fix report -------------------------------

def test_review_fix_json_includes_fixes(tmp_path, capsys, monkeypatch):
    # --fix in JSON mode embeds the fix report under "fixes" without running any
    # real verification (apply pass stubbed).
    import app.cli_review as cr

    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    monkeypatch.setattr(cr, "_apply_review_fixes",
                        lambda target, result: {"applied": [], "applied_count": 0,
                                                "files_touched": [], "blocked": []})
    rc = cmd_review(_ns(tmp_path, fix=True, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fixes"] == {"applied": [], "applied_count": 0,
                                "files_touched": [], "blocked": []}


# --- rule-book --fix application (applied + blocked) -------------------------

class _FakePlan:
    def __init__(self, blockers=None, new_contents=None):
        self.blockers = blockers or []
        self.new_contents = new_contents if new_contents is not None else {"x": "y"}


def _rule_result() -> ReviewResult:
    f = ReviewFinding("app/m.py", 5, "convention", "medium",
                      "rule `no-len-zero`", auto_fixable=True, fix_kind="rule:no-len-zero")
    return ReviewResult(base="HEAD", files_reviewed=1, findings=[f])


def test_apply_review_fixes_runs_saved_rule(tmp_path, monkeypatch):
    # The rule-book branch: a saved rule is planned and applied via apply_rename
    # (verify=True), all stubbed so no real suite runs.
    import app.execution.cross_file_rename as cfr
    import app.execution.pattern_rewrite as pr
    import app.execution.rewrite_rules as rr

    monkeypatch.setattr(rr, "load_rules",
                        lambda target: [{"name": "no-len-zero",
                                         "pattern": "len($x) == 0", "replacement": "not $x"}])
    monkeypatch.setattr(pr, "plan_pattern_rewrite",
                        lambda target, pat, rep: _FakePlan())
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda target, plan, verify=True: {
                            "applied": True, "edits": 2,
                            "changed_files": ["app/m.py"]})
    report = _apply_review_fixes(str(tmp_path), _rule_result())
    assert report["applied_count"] == 2
    assert report["applied"] == [{"file": "app/m.py", "transform": "rule:no-len-zero"}]
    assert report["blocked"] == []


def test_apply_review_fixes_blocks_on_plan_blocker(tmp_path, monkeypatch):
    # A rule whose plan reports a blocker is recorded as blocked, never applied.
    import app.execution.cross_file_rename as cfr
    import app.execution.pattern_rewrite as pr
    import app.execution.rewrite_rules as rr

    monkeypatch.setattr(rr, "load_rules",
                        lambda target: [{"name": "no-len-zero",
                                         "pattern": "len($x) == 0", "replacement": "not $x"}])
    monkeypatch.setattr(pr, "plan_pattern_rewrite",
                        lambda target, pat, rep: _FakePlan(blockers=["uncovered file"]))
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not apply")))
    report = _apply_review_fixes(str(tmp_path), _rule_result())
    assert report["applied"] == []
    assert report["blocked"] == [{"file": "(all)", "reason": "rule:no-len-zero: uncovered file"}]


def test_apply_review_fixes_rule_rolled_back(tmp_path, monkeypatch):
    # apply_rename returns not-applied -> recorded as blocked with its reason.
    import app.execution.cross_file_rename as cfr
    import app.execution.pattern_rewrite as pr
    import app.execution.rewrite_rules as rr

    monkeypatch.setattr(rr, "load_rules",
                        lambda target: [{"name": "no-len-zero",
                                         "pattern": "len($x) == 0", "replacement": "not $x"}])
    monkeypatch.setattr(pr, "plan_pattern_rewrite",
                        lambda target, pat, rep: _FakePlan())
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda target, plan, verify=True: {"applied": False,
                                                           "reason": "suite failed"})
    report = _apply_review_fixes(str(tmp_path), _rule_result())
    assert report["applied"] == []
    assert report["blocked"] == [{"file": "(all)", "reason": "rule:no-len-zero: suite failed"}]


def test_apply_review_fixes_rule_empty_plan_is_skipped(tmp_path, monkeypatch):
    # A plan with no blockers but no new_contents is a no-op rule (line 93
    # continue): nothing applied, nothing blocked.
    import app.execution.cross_file_rename as cfr
    import app.execution.pattern_rewrite as pr
    import app.execution.rewrite_rules as rr

    monkeypatch.setattr(rr, "load_rules",
                        lambda target: [{"name": "no-len-zero",
                                         "pattern": "len($x) == 0", "replacement": "not $x"}])
    monkeypatch.setattr(pr, "plan_pattern_rewrite",
                        lambda target, pat, rep: _FakePlan(new_contents={}))
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not apply")))
    report = _apply_review_fixes(str(tmp_path), _rule_result())
    assert report == {"applied": [], "applied_count": 0,
                      "files_touched": [], "blocked": []}


def test_apply_review_fixes_non_tier1_block_is_dropped(tmp_path, monkeypatch):
    # A detector result that is neither applied nor a tier-1 block is silently
    # dropped (the 132->123 loop-back, not recorded as blocked).
    import app.engine.idea_action_bridge as iab

    f = ReviewFinding("app/a.py", 2, "security", "high", "eval", True, "eval")
    result = ReviewResult(base="HEAD", files_reviewed=1, findings=[f])

    def fake_apply_plan(self, plan, target, mode="supervised", verify=True):
        return {"results": [
            {"applied": False, "target": "app/a.py", "reason": "skipped: clean"}]}

    monkeypatch.setattr(iab.IdeaActionBridge, "apply_plan", fake_apply_plan)
    report = _apply_review_fixes(str(tmp_path), result)
    assert report["applied"] == []
    assert report["blocked"] == []  # non-tier-1 reasons are not surfaced


def test_apply_review_fixes_rule_missing_is_skipped(tmp_path, monkeypatch):
    # A finding referencing a rule that no longer exists is skipped silently.
    import app.execution.rewrite_rules as rr

    monkeypatch.setattr(rr, "load_rules", lambda target: [])
    report = _apply_review_fixes(str(tmp_path), _rule_result())
    assert report == {"applied": [], "applied_count": 0,
                      "files_touched": [], "blocked": []}


def test_apply_review_fixes_detector_branch_records_applied_and_blocked(tmp_path, monkeypatch):
    # The detector branch goes through IdeaActionBridge.apply_plan; stub it to
    # return one applied (with converged + shield) and one tier-1 blocked result.
    import app.engine.idea_action_bridge as iab

    findings = [
        ReviewFinding("app/a.py", 2, "security", "high", "eval", True, "eval"),
        ReviewFinding("app/b.py", 3, "bug", "medium", "mutable default", True, "mutable-default"),
    ]
    result = ReviewResult(base="HEAD", files_reviewed=2, findings=findings)

    def fake_apply_plan(self, plan, target, mode="supervised", verify=True):
        return {"results": [
            {"applied": True, "target": "app/a.py", "transform_type": "harden",
             "converged_fixes": 2, "shield_test": "tests/test_a.py"},
            {"applied": False, "target": "app/b.py", "reason": "tier-1 blocked: uncovered"},
        ]}

    monkeypatch.setattr(iab.IdeaActionBridge, "apply_plan", fake_apply_plan)
    report = _apply_review_fixes(str(tmp_path), result)
    assert report["applied"] == [
        {"file": "app/a.py", "transform": "harden", "converged_fixes": 2,
         "shield_test": "tests/test_a.py"}]
    assert report["applied_count"] == 3  # 1 + 2 converged
    assert report["blocked"] == [{"file": "app/b.py", "reason": "tier-1 blocked: uncovered"}]


# --- blocked-render markdown -------------------------------------------------

def test_render_review_fixes_markdown_no_fixes():
    md = _render_review_fixes_markdown({"applied": [], "blocked": []})
    assert "No auto-fixes applied" in md


def test_render_review_fixes_markdown_lists_blocked():
    md = _render_review_fixes_markdown(
        {"applied": [], "blocked": [{"file": "(all)", "reason": "rule:x: nope"}]})
    assert "⛔" in md and "rule:x: nope" in md


def test_render_review_fixes_markdown_lists_applied_with_extras():
    md = _render_review_fixes_markdown({
        "applied_count": 4,
        "applied": [{"file": "app/a.py", "transform": "harden",
                     "converged_fixes": 2, "shield_test": "tests/test_a.py"}],
        "blocked": []})
    assert "Applied 4 fix(es)" in md
    assert "+2 converged" in md
    assert "shielded first by `tests/test_a.py`" in md


# --- register_parsers wiring -------------------------------------------------

def test_register_parsers_wires_review_subcommand():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_parsers(subparsers)
    args = parser.parse_args([
        "review", "--target", "/x", "--base", "origin/main",
        "--fail-on-high", "--sarif", "out.sarif", "--fix",
        "--max-findings", "12", "--json"])
    assert args.func is cmd_review
    assert args.target == "/x"
    assert args.base == "origin/main"
    assert args.fail_on_high is True
    assert args.sarif == "out.sarif"
    assert args.fix is True
    assert args.max_findings == 12
    assert args.json is True


def test_register_parsers_defaults():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_parsers(subparsers)
    args = parser.parse_args(["review"])
    assert args.target == ""
    assert args.base == "HEAD"
    assert args.fail_on_high is False
    assert args.sarif == ""
    assert args.fix is False
    assert args.max_findings == 0
    assert args.json is False
    assert callable(args.func)
