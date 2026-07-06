from __future__ import annotations

from pathlib import Path

from app.reporting.composer import ReportComposer

# composer.py is already at 100% line coverage; these lock in SARIF/Markdown
# contract details (rule dedup, level mapping, id truncation, severity icons).


def test_sarif_dedups_rules_and_maps_levels():
    results = [
        {"agent": "sec", "findings": [
            {"issue": "eval() usage", "severity": "critical", "file": "a.py", "suggestion": "fix"},
            {"issue": "eval() usage", "severity": "high", "file": "b.py"},
            {"issue": "weak hash", "severity": "medium", "file": "c.py"},
        ]},
    ]
    sarif = ReportComposer(results).to_sarif()
    run = sarif["runs"][0]
    # Duplicate issue collapses to one rule; every finding still yields a result.
    assert len(run["rules"]) == 2
    assert len(run["results"]) == 3
    levels = [r["level"] for r in run["results"]]
    assert levels == ["error", "error", "warning"]


def test_sarif_rule_id_truncated_to_40_chars():
    long_issue = "a" * 60 + " b"
    results = [{"agent": "x", "findings": [
        {"issue": long_issue, "severity": "low", "file": "f.py"},
    ]}]
    sarif = ReportComposer(results).to_sarif()
    rule_id = sarif["runs"][0]["rules"][0]["id"]
    assert len(rule_id) == 40
    assert rule_id == "a" * 40


def test_markdown_high_and_info_severity_icons(tmp_path: Path):
    results = [{"agent": "sec", "findings": [
        {"issue": "high risk", "severity": "high", "file": "h.py", "suggestion": "harden"},
        {"issue": "note", "severity": "info", "file": "i.py"},
    ]}]
    md = ReportComposer(results).to_markdown(tmp_path / "r.md")
    assert "\U0001f7e0 **high risk**" in md  # orange for high
    assert "\U0001f7e1 **note**" in md       # yellow default for info
    assert "\U0001f4a1 harden" in md         # suggestion line rendered
    assert md.count("\U0001f4a1") == 1       # only the high finding has a suggestion
