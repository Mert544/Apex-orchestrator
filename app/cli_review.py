"""Review-family commands: diff-scoped PR review with guarded --fix.

Extracted from the `app/cli.py` monolith — the engine's own #1 convergence
target (central dependency hub × high churn). Pure mechanical move:
`app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_review(args: argparse.Namespace) -> int:
    """Review only the lines changed since a base ref — Apex as a PR reviewer."""
    from app.engine.diff_review import render_review_markdown, review

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = review(str(target), base=getattr(args, "base", "HEAD") or "HEAD")

    # --fix: apply the auto-fixable findings on the changed files, test-verified.
    fix_report = None
    if getattr(args, "fix", False):
        fix_report = _apply_review_fixes(str(target), result)

    # --sarif: export findings for GitHub code scanning / CI dashboards.
    sarif_out = getattr(args, "sarif", "")
    if sarif_out:
        from app.engine.sarif_export import review_to_sarif

        sarif_path = Path(sarif_out)
        sarif_path.parent.mkdir(parents=True, exist_ok=True)
        sarif_path.write_text(json.dumps(review_to_sarif(result), indent=2) + "\n",
                              encoding="utf-8")

    if args.json:
        payload = result.to_dict()
        if fix_report is not None:
            payload["fixes"] = fix_report
        print(json.dumps(payload, indent=2))
    else:
        print(render_review_markdown(result))
        if fix_report is not None:
            print(_render_review_fixes_markdown(fix_report))
        if sarif_out:
            print(f"[review] SARIF written to {sarif_out}")
    # Non-zero exit when high-severity issues land in the diff (CI-friendly).
    if getattr(args, "fail_on_high", False) and any(f.severity == "high" for f in result.findings):
        return 1
    return 0


def _apply_review_fixes(target: str, result) -> dict:
    """Apply the auto-fixable review findings through the SAME guarded pass
    `apex maintain` uses — risk tiers, test-first shield, convergence ladder,
    verification strength — so review fixes carry identical trust guarantees
    (a tier-1 fix on an uncovered file is shielded or blocked, never gambled).
    """
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan, ActionStep

    files = sorted({f.file for f in result.findings if f.auto_fixable and f.file.endswith(".py")})
    steps: list[ActionStep] = []
    for rel in files:
        # harden_security runs the detection ladder (security → mutable-default
        # → modernization) and converges per file; add_docstring covers docs.
        steps.append(ActionStep(branch_path=f"review:{rel}", title=f"fix {rel}",
                                operator="harden", subject=rel, action_type="harden_security",
                                target=rel, executable=True,
                                source_facts=[f"review-finding: {rel}"]))
        steps.append(ActionStep(branch_path=f"review:{rel}.doc", title=f"doc {rel}",
                                operator="document", subject=rel, action_type="add_docstring",
                                target=rel, executable=True,
                                source_facts=[f"review-finding: {rel}"]))
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(objective="apply review findings", steps=steps),
        target, mode="supervised", verify=True)

    applied: list[dict] = []
    blocked: list[dict] = []
    fixes_total = 0
    for r in summary.get("results", []):
        if r.get("applied"):
            entry = {"file": r["target"], "transform": r.get("transform_type")}
            fixes_total += 1 + int(r.get("converged_fixes", 0) or 0)
            if r.get("converged_fixes"):
                entry["converged_fixes"] = r["converged_fixes"]
            if r.get("shield_test"):
                entry["shield_test"] = r["shield_test"]
            applied.append(entry)
        elif "tier-1" in (r.get("reason") or ""):
            blocked.append({"file": r.get("target", ""), "reason": r["reason"]})
    return {"applied": applied, "applied_count": fixes_total,
            "files_touched": sorted({a["file"] for a in applied}),
            "blocked": blocked}


def _render_review_fixes_markdown(fix: dict) -> str:
    if fix.get("applied"):
        lines = [f"\n## 🔧 Applied {fix['applied_count']} fix(es) (test-verified)"]
        for a in fix["applied"]:
            extra = f" (+{a['converged_fixes']} converged)" if a.get("converged_fixes") else ""
            if a.get("shield_test"):
                extra += f" 🛡️ shielded first by `{a['shield_test']}`"
            lines.append(f"- `{a['file']}` — {a['transform']}{extra}")
    else:
        lines = ["\n_No auto-fixes applied (nothing verified cleanly, or nothing fixable)._"]
    for b in fix.get("blocked", []):
        lines.append(f"- ⛔ `{b['file']}` — {b['reason']}")
    lines.append("")
    return "\n".join(lines)


