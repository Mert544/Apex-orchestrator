"""SARIF export: branch-level edges — level/rule-id fallbacks, message variants, line floor."""

from __future__ import annotations

from app.engine.diff_review import ReviewFinding, ReviewResult
from app.engine.sarif_export import review_to_sarif


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(base="HEAD", files_reviewed=1, findings=findings)


def test_unknown_severity_maps_to_note():
    """A severity outside the high/medium/low table defaults to SARIF 'note' (line 53)."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 3, "style", "trivia", "odd severity", False),
    ]))
    assert sarif["runs"][0]["results"][0]["level"] == "note"


def test_medium_severity_maps_to_warning():
    """Medium severity renders as SARIF 'warning'."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 3, "security", "medium", "moderate issue", False),
    ]))
    assert sarif["runs"][0]["results"][0]["level"] == "warning"


def test_rule_id_falls_back_to_finding_when_empty():
    """Empty fix_kind and empty category fall back to the literal 'finding' rule id."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "", "low", "nondescript", False, ""),
    ]))
    assert sarif["runs"][0]["results"][0]["ruleId"] == "apex/finding"


def test_auto_fixable_without_suggestion_appends_maintain_hint():
    """An auto-fixable finding with no concrete suggestion gets the 'apex maintain' hint."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "docs", "low", "missing docstring", True, "docstring"),
    ]))
    text = sarif["runs"][0]["results"][0]["message"]["text"]
    assert text == "missing docstring Auto-fixable by `apex maintain`."


def test_non_auto_fixable_without_suggestion_has_plain_message():
    """No suggestion and not auto-fixable leaves the message verbatim (both branches off)."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "docs", "low", "untouched message", False, "docs"),
    ]))
    assert sarif["runs"][0]["results"][0]["message"]["text"] == "untouched message"


def test_suggestion_wins_over_auto_fixable_message():
    """When both a suggestion and auto_fixable are set, the suggestion text is used (elif)."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "security", "high", "use literal_eval", True, "eval",
                      suggestion=("eval(x)", "ast.literal_eval(x)")),
    ]))
    text = sarif["runs"][0]["results"][0]["message"]["text"]
    assert "Suggested fix: replace `eval(x)` with `ast.literal_eval(x)`." in text
    assert "apex maintain" not in text


def test_zero_line_is_floored_to_one():
    """A line of 0 is floored to startLine 1 (SARIF regions are 1-based)."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 0, "security", "high", "bad", False),
    ]))
    region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 1


def test_negative_line_is_floored_to_one():
    """A negative line never produces an invalid startLine below 1."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", -5, "security", "high", "bad", False),
    ]))
    region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 1


def test_rules_sorted_by_id():
    """The driver's rules list is sorted by id regardless of finding order."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "z-cat", "low", "z msg", False),
        ReviewFinding("a.py", 2, "a-cat", "low", "a msg", False),
    ]))
    ids = [r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]]
    assert ids == ["apex/a-cat", "apex/z-cat"]


def test_rule_shortdescription_uses_first_message_seen():
    """Deduplicated rules keep the message of the first finding that defined them."""
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "security", "high", "first message", True, "eval"),
        ReviewFinding("b.py", 2, "security", "high", "second message", True, "eval"),
    ]))
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    assert len(rules) == 1
    assert rules[0]["shortDescription"]["text"] == "first message"
    assert rules[0]["properties"]["category"] == "security"
