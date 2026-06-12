"""SARIF export: `apex review` findings in GitHub-code-scanning form."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.engine.diff_review import ReviewFinding, ReviewResult
from app.engine.sarif_export import review_to_sarif


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(base="HEAD", files_reviewed=1, findings=findings)


def test_sarif_structure_and_level_mapping():
    sarif = review_to_sarif(_result([
        ReviewFinding("app/m.py", 4, "security", "high", "eval() on input",
                      True, "eval", suggestion=("return eval(c)", "return ast.literal_eval(c)")),
        ReviewFinding("app/m.py", 9, "docs", "low", "missing docstring", False, ""),
    ]))
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "Apex Orchestrator"
    res = run["results"]
    assert [r["level"] for r in res] == ["error", "note"]
    assert res[0]["ruleId"] == "apex/eval"
    assert res[1]["ruleId"] == "apex/docs"  # no fix_kind -> category fallback
    assert "Suggested fix" in res[0]["message"]["text"]
    loc = res[0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "app/m.py"
    assert loc["region"]["startLine"] == 4
    assert res[0]["properties"]["autoFixable"] is True


def test_sarif_rules_deduplicate_by_id():
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "security", "high", "eval() on input", True, "eval"),
        ReviewFinding("b.py", 2, "security", "high", "eval() on input", True, "eval"),
    ]))
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == ["apex/eval"]
    assert len(sarif["runs"][0]["results"]) == 2


def test_sarif_empty_review_is_valid():
    sarif = review_to_sarif(_result([]))
    assert sarif["runs"][0]["results"] == []
    assert sarif["runs"][0]["tool"]["driver"]["rules"] == []


def test_sarif_spaced_fix_kind_makes_stable_rule_id():
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "security", "medium", "bare except swallows", True, "bare except"),
    ]))
    assert sarif["runs"][0]["results"][0]["ruleId"] == "apex/bare-except"


def test_cli_review_writes_sarif(tmp_path: Path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
              ["git", "config", "user.name", "t"], ["git", "add", "-A"],
              ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=tmp_path, capture_output=True)
    (tmp_path / "app" / "m.py").write_text(
        "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    from app.cli import cmd_review

    sarif_path = tmp_path / "out" / "apex.sarif"
    args = argparse.Namespace(target=str(tmp_path), base="HEAD", fail_on_high=False,
                              json=False, fix=False, sarif=str(sarif_path))
    rc = cmd_review(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "SARIF written" in out
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    assert any("eval" in r["ruleId"] for r in sarif["runs"][0]["results"])
