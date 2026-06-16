"""Characterization harness: prove `_apply_review_fixes` is byte-identical
before vs after the decomposition refactor.

The pre-refactor function body is loaded verbatim from the HEAD snapshot
(`git show HEAD:app/cli_review.py` captured at /tmp by the refactor session,
re-embedded here so the test is self-contained) and run side-by-side with the
current implementation against the SAME stubbed dependencies across several
inputs. Every returned report (dict structure, ordering, counts, blocker/verdict
strings) must match exactly. Offline, stdlib-only, deterministic.
"""
from __future__ import annotations

import importlib
import types

import pytest

from app.engine.diff_review import ReviewFinding, ReviewResult

# ── The verbatim pre-refactor _apply_review_fixes (HEAD snapshot) ────────────
# This is the EXACT body of `_apply_review_fixes` as it stood at the refactor's
# base commit (extracted via `git show HEAD:app/cli_review.py`); copied byte-for
# -byte so the harness compares against the genuine original, not a paraphrase.
_ORIGINAL_SRC = '''
def _apply_review_fixes(target: str, result) -> dict:
    """Apply the auto-fixable review findings through the SAME guarded pass
    `apex maintain` uses — risk tiers, test-first shield, convergence ladder,
    verification strength — so review fixes carry identical trust guarantees
    (a tier-1 fix on an uncovered file is shielded or blocked, never gambled).

    Rule-book violations (fix_kind="rule:NAME") are applied directly via the
    saved pattern rewrite rather than through the harden ladder — the rule IS
    the fix, suite-verified with rollback exactly like every other Apex change.
    """
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.execution.cross_file_rename import apply_rename
    from app.execution.pattern_rewrite import plan_pattern_rewrite
    from app.execution.rewrite_rules import load_rules
    from app.models.idea import ActionPlan, ActionStep

    applied: list[dict] = []
    blocked: list[dict] = []
    fixes_total = 0

    # ── Rule-book violations: run the saved rule directly (not via harden) ──
    rule_names = sorted({f.fix_kind[5:] for f in result.findings
                         if f.fix_kind.startswith("rule:") and f.auto_fixable})
    if rule_names:
        all_rules = {r["name"]: r for r in load_rules(target)}
        for name in rule_names:
            r = all_rules.get(name)
            if not r:
                continue
            plan = plan_pattern_rewrite(target, r["pattern"], r["replacement"])
            if plan.blockers:
                blocked.append({"file": "(all)", "reason": f"rule:{name}: {plan.blockers[0]}"})
                continue
            if not plan.new_contents:
                continue
            res = apply_rename(target, plan, verify=True)
            if res.get("applied"):
                fixes_total += res.get("edits", 1)
                for f in res.get("changed_files", []):
                    applied.append({"file": f, "transform": f"rule:{name}"})
            else:
                blocked.append({"file": "(all)",
                                 "reason": f"rule:{name}: {res.get('reason', 'rolled back')}"})

    # ── Detector findings: harden ladder + docstring (skip rule-only files) ──
    files = sorted({f.file for f in result.findings
                    if f.auto_fixable and f.file.endswith(".py")
                    and not f.fix_kind.startswith("rule:")})
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
    if steps:
        summary = IdeaActionBridge().apply_plan(
            ActionPlan(objective="apply review findings", steps=steps),
            target, mode="supervised", verify=True)
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
'''


def _load_original():
    mod = types.ModuleType("_cli_review_original")
    exec(compile(_ORIGINAL_SRC, "<original>", "exec"), mod.__dict__)
    return mod._apply_review_fixes


class _FakePlan:
    def __init__(self, blockers=None, new_contents=None):
        self.blockers = blockers or []
        self.new_contents = new_contents if new_contents is not None else {"x": "y"}


def _rf(file, kind, auto=True):
    return ReviewFinding(file, 5, "convention", "medium", f"msg {kind}",
                         auto_fixable=auto, fix_kind=kind)


# Each scenario: (findings, rules, plan_factory, apply_rename_fn, apply_plan_fn)
def _scenarios():
    return {
        # 1. rule applied cleanly
        "rule_applied": dict(
            findings=[_rf("app/m.py", "rule:no-len-zero")],
            rules=[{"name": "no-len-zero", "pattern": "len($x) == 0", "replacement": "not $x"}],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda t, p, verify=True: {"applied": True, "edits": 2,
                                                    "changed_files": ["app/m.py"]},
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": []},
        ),
        # 2. rule blocked by plan blocker
        "rule_plan_blocker": dict(
            findings=[_rf("app/m.py", "rule:no-len-zero")],
            rules=[{"name": "no-len-zero", "pattern": "p", "replacement": "r"}],
            plan=lambda *a: _FakePlan(blockers=["uncovered file"]),
            apply_rename=lambda *a, **k: pytest.fail("must not apply"),
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": []},
        ),
        # 3. rule rolled back
        "rule_rolled_back": dict(
            findings=[_rf("app/m.py", "rule:no-len-zero")],
            rules=[{"name": "no-len-zero", "pattern": "p", "replacement": "r"}],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda t, p, verify=True: {"applied": False, "reason": "suite failed"},
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": []},
        ),
        # 4. empty plan skipped
        "rule_empty_plan": dict(
            findings=[_rf("app/m.py", "rule:no-len-zero")],
            rules=[{"name": "no-len-zero", "pattern": "p", "replacement": "r"}],
            plan=lambda *a: _FakePlan(new_contents={}),
            apply_rename=lambda *a, **k: pytest.fail("must not apply"),
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": []},
        ),
        # 5. rule missing
        "rule_missing": dict(
            findings=[_rf("app/m.py", "rule:gone")],
            rules=[],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda *a, **k: pytest.fail("must not apply"),
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": []},
        ),
        # 6. detector applied with converged + shield, plus tier-1 block
        "detector_mixed": dict(
            findings=[_rf("app/a.py", "eval"), _rf("app/b.py", "mutable-default")],
            rules=[],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda *a, **k: {"applied": False},
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": [
                {"applied": True, "target": "app/a.py", "transform_type": "harden",
                 "converged_fixes": 2, "shield_test": "tests/test_a.py"},
                {"applied": False, "target": "app/b.py", "reason": "tier-1 blocked: uncovered"},
            ]},
        ),
        # 7. detector non-tier-1 drop
        "detector_drop": dict(
            findings=[_rf("app/a.py", "eval")],
            rules=[],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda *a, **k: {"applied": False},
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": [
                {"applied": False, "target": "app/a.py", "reason": "skipped: clean"}]},
        ),
        # 8. both rule + detector together, multi-file applied
        "rule_and_detector": dict(
            findings=[_rf("app/m.py", "rule:r1"), _rf("app/c.py", "eval"),
                      _rf("app/d.py", "modernize"), _rf("notpy.txt", "eval"),
                      _rf("app/skip.py", "style", auto=False)],
            rules=[{"name": "r1", "pattern": "p", "replacement": "r"}],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda t, p, verify=True: {"applied": True,
                                                    "changed_files": ["app/m.py", "app/x.py"]},
            apply_plan=lambda self, plan, target, mode="supervised", verify=True: {"results": [
                {"applied": True, "target": "app/c.py", "transform_type": "harden"},
                {"applied": True, "target": "app/d.py", "transform_type": "modernize",
                 "converged_fixes": 0},
            ]},
        ),
        # 9. empty findings
        "empty": dict(
            findings=[],
            rules=[],
            plan=lambda *a: _FakePlan(),
            apply_rename=lambda *a, **k: pytest.fail("must not apply"),
            apply_plan=lambda self, plan, target, mode="supervised", verify=True:
                pytest.fail("must not run plan"),
        ),
    }


@pytest.mark.parametrize("name", list(_scenarios().keys()))
def test_apply_review_fixes_byte_identical(name, tmp_path, monkeypatch):
    sc = _scenarios()[name]

    def patch_deps():
        import app.engine.idea_action_bridge as iab
        import app.execution.cross_file_rename as cfr
        import app.execution.pattern_rewrite as pr
        import app.execution.rewrite_rules as rr
        monkeypatch.setattr(rr, "load_rules", lambda target: sc["rules"])
        monkeypatch.setattr(pr, "plan_pattern_rewrite", sc["plan"])
        monkeypatch.setattr(cfr, "apply_rename", sc["apply_rename"])
        monkeypatch.setattr(iab.IdeaActionBridge, "apply_plan", sc["apply_plan"])

    result_orig = ReviewResult(base="HEAD", files_reviewed=1, findings=list(sc["findings"]))
    result_new = ReviewResult(base="HEAD", files_reviewed=1, findings=list(sc["findings"]))

    patch_deps()
    original = _load_original()
    out_orig = original(str(tmp_path), result_orig)

    patch_deps()
    cr = importlib.import_module("app.cli_review")
    out_new = cr._apply_review_fixes(str(tmp_path), result_new)

    assert out_new == out_orig, f"{name}: {out_new!r} != {out_orig!r}"
