"""SARIF 2.1.0 export for `apex review` — findings where reviewers already look.

SARIF is the interchange format GitHub code scanning (and most CI security
dashboards) ingest natively. Exporting the diff review as SARIF puts Apex's
deterministic findings inline on the PR's "Security" tab instead of a build
log. Pure function of the :class:`ReviewResult` — same findings in, same
SARIF out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.diff_review import ReviewFinding, ReviewResult

_INFO_URI = "https://github.com/Mert544/Apex-orchestrator"
_LEVEL = {"high": "error", "medium": "warning", "low": "note"}


def _rule_id(finding: ReviewFinding) -> str:
    """Stable rule id: the detector's fix_kind when routed, else the category."""
    key = (finding.fix_kind or finding.category or "finding").replace(" ", "-")
    return f"apex/{key}"


def _message(finding: ReviewFinding) -> str:
    text = finding.message
    if finding.suggestion:
        old, new = finding.suggestion
        text += f" Suggested fix: replace `{old}` with `{new}`."
    elif finding.auto_fixable:
        text += " Auto-fixable by `apex maintain`."
    return text


def review_to_sarif(result: ReviewResult) -> dict:
    """Render a :class:`ReviewResult` as a SARIF 2.1.0 log (one run)."""
    from app.engine.proof_of_fix import tool_version

    rules: dict[str, dict] = {}
    results: list[dict] = []
    for f in result.findings:
        rid = _rule_id(f)
        rules.setdefault(rid, {
            "id": rid,
            "shortDescription": {"text": f.message},
            "properties": {"category": f.category},
        })
        results.append({
            "ruleId": rid,
            "level": _LEVEL.get(f.severity, "note"),
            "message": {"text": _message(f)},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.file, "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": max(f.line, 1)},
                }
            }],
            "properties": {
                "severity": f.severity,
                "category": f.category,
                "autoFixable": f.auto_fixable,
            },
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "Apex Orchestrator",
                "informationUri": _INFO_URI,
                "version": tool_version(),
                "rules": sorted(rules.values(), key=lambda r: r["id"]),
            }},
            "results": results,
        }],
    }
