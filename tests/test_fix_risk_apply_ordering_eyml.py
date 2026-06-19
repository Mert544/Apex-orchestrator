"""Opt-in fix-risk-aware maintain apply ordering — deterministic pin.

Closes the intelligence loop: the read-only fix-risk model
(``app/engine/fix_risk_model.py``) now influences ``IdeaActionBridge.apply_plan``
when ``prefer_reliable`` is set. The contract is strictly additive and OPT-IN:

* default OFF → the executable steps are iterated in EXACTLY the plan order, and
  ``--max-apply`` takes the same prefix, so the applied set is byte-identical to
  before this feature existed;
* ON with a seeded proof history → the steps are STABLY re-ranked low-fix-risk
  first, so a ``--max-apply 1`` budget spends on the historically-most-reliable
  fix;
* ON with NO proof history → every step scores the neutral baseline (0.5), so a
  stable sort leaves the order unchanged (identical to default);
* best-effort → if the model raises, the original order is returned.

The proof history is seeded by writing a fake proof-of-fix JSON to the real
on-disk location the loader reads (``<root>/.apex/*.json`` with
``schema == SCHEMA``), matching the house style of
``tests/test_fix_risk_model_eyml.py``. Ordering is observed by stubbing
``_MaintenancePass.run_step`` to record the steps it is handed (and tick the
``applied`` counter the ``max_apply`` cap reads), so the test pins ORDER only,
with no file mutation or verification side effects. All assertions are
deterministic — no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.engine.idea_action_bridge as bridge_mod
from app.engine.idea_action_bridge import IdeaActionBridge, _MaintenancePass
from app.engine.proof_of_fix import SCHEMA
from app.models.idea import ActionPlan, ActionStep


# --- fixtures ----------------------------------------------------------------


def _step(target: str, action_type: str = "fix", value: float = 0.0) -> ActionStep:
    return ActionStep(
        branch_path=f"x.{target}", title=f"t {target}", operator="o",
        subject=target, action_type=action_type, target=target,
        executable=True, value=value,
    )


def _plan(steps: list[ActionStep]) -> ActionPlan:
    return ActionPlan(steps=steps, stats={}, mode="supervised")


def _proof(fixes: list[dict]) -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": "2026-01-01T00:00:00+00:00", "fixes": fixes}


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


def _seed_history(root: Path, fixes: list[dict]) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "p.json").write_text(json.dumps(_proof(fixes), indent=2), encoding="utf-8")


def _record_order(monkeypatch) -> list[str]:
    """Stub run_step to record handed steps + tick the max_apply counter.

    Records each step's target in call order, and increments ``applied`` so the
    ``apply_plan`` ``max_apply`` cap behaves exactly as in production — but with
    no file mutation, verification, or commit side effects."""
    seen: list[str] = []

    def fake_run_step(self, step):
        seen.append(step.target)
        self.applied += 1

    monkeypatch.setattr(_MaintenancePass, "run_step", fake_run_step)
    return seen


# --- default OFF: byte-identical to today ------------------------------------


def test_default_off_iterates_exact_plan_order(monkeypatch, tmp_path):
    """Without ``prefer_reliable`` the apply loop sees the steps in plan order,
    UNCHANGED — even though a proof history exists that WOULD reorder them."""
    # History that makes 'a' high-risk and 'c' low-risk (so a reorder is visible).
    _seed_history(tmp_path, [
        _fix("fix", "c", "applied"), _fix("fix", "c", "applied"),
        _fix("fix", "a", "rolled_back"), _fix("fix", "a", "rolled_back"),
    ])
    plan = _plan([_step("a"), _step("b"), _step("c")])
    seen = _record_order(monkeypatch)

    summary = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised")

    assert seen == ["a", "b", "c"]
    assert summary["applied"] == 3
    assert summary["total_executable"] == 3
    # Opt-in summary keys must not appear on a default run.
    assert "skipped_learned" not in summary


def test_default_off_max_apply_takes_plan_prefix(monkeypatch, tmp_path):
    """Default-off + ``--max-apply 1`` applies the FIRST plan step, regardless of
    its (worse) fix-risk — proving the cap still spends on plan order."""
    _seed_history(tmp_path, [
        _fix("fix", "a", "rolled_back"), _fix("fix", "a", "rolled_back"),
        _fix("fix", "c", "applied"), _fix("fix", "c", "applied"),
    ])
    plan = _plan([_step("a"), _step("b"), _step("c")])
    seen = _record_order(monkeypatch)

    summary = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="supervised", max_apply=1)

    assert seen == ["a"]
    assert summary["applied"] == 1


# --- ON: re-rank by ascending fix-risk ---------------------------------------


def test_prefer_reliable_applies_lowest_risk_first_under_cap(monkeypatch, tmp_path):
    """With ``prefer_reliable`` + ``--max-apply 1``, the historically-reliable
    fix ('c', all applied) is taken FIRST, ahead of the risky leader ('a')."""
    _seed_history(tmp_path, [
        _fix("fix", "a", "rolled_back"), _fix("fix", "a", "rolled_back"),
        _fix("fix", "c", "applied"), _fix("fix", "c", "applied"),
    ])
    plan = _plan([_step("a"), _step("b"), _step("c")])
    seen = _record_order(monkeypatch)

    summary = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="supervised",
        max_apply=1, prefer_reliable=True)

    assert seen == ["c"]
    assert summary["applied"] == 1


def test_prefer_reliable_full_pass_is_risk_sorted(monkeypatch, tmp_path):
    """Uncapped, ``prefer_reliable`` applies EVERY step (nothing dropped) but in
    ascending-risk order: reliable 'c' first, untouched 'b' (baseline) next,
    risky 'a' last."""
    _seed_history(tmp_path, [
        _fix("fix", "a", "rolled_back"), _fix("fix", "a", "rolled_back"),
        _fix("fix", "c", "applied"), _fix("fix", "c", "applied"),
    ])
    plan = _plan([_step("a"), _step("b"), _step("c")])
    seen = _record_order(monkeypatch)

    summary = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="supervised", prefer_reliable=True)

    assert seen == ["c", "b", "a"]
    assert sorted(seen) == ["a", "b", "c"]  # pure reorder — nothing added/dropped
    assert summary["applied"] == 3


def test_prefer_reliable_no_history_keeps_plan_order(monkeypatch, tmp_path):
    """ON but with NO proof history: every step scores the neutral baseline
    (0.5), so the stable sort is a no-op — order is identical to default."""
    plan = _plan([_step("a"), _step("b"), _step("c")])
    seen = _record_order(monkeypatch)

    IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="supervised", prefer_reliable=True)

    assert seen == ["a", "b", "c"]


def test_prefer_reliable_ties_keep_phase_order(monkeypatch, tmp_path):
    """Equal-risk steps keep their incoming plan order (STABLE sort). The two
    'unseen'-action steps both abstain to the baseline; the step whose action
    has a reliable record jumps ahead, but the two baseline steps stay in their
    original relative order."""
    # Only the 'reliable_act' action has a record; 'unseen_act' abstains to 0.5.
    _seed_history(tmp_path, [
        _fix("reliable_act", "c", "applied"),
        _fix("reliable_act", "c", "applied"),
    ])
    plan = _plan([
        _step("b", action_type="unseen_act"),
        _step("d", action_type="unseen_act"),
        _step("c", action_type="reliable_act"),
    ])
    seen = _record_order(monkeypatch)

    IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="supervised", prefer_reliable=True)

    # 'c' (low risk) first; 'b' and 'd' (tied baseline) keep plan order.
    assert seen == ["c", "b", "d"]


# --- helper-level pins (unit) ------------------------------------------------


def test_rerank_helper_is_pure_permutation(tmp_path):
    """``_rerank_by_fix_risk`` returns a permutation of its input — same steps,
    none added or dropped — even when it reorders."""
    _seed_history(tmp_path, [
        _fix("fix", "a", "rolled_back"), _fix("fix", "a", "rolled_back"),
        _fix("fix", "c", "applied"), _fix("fix", "c", "applied"),
    ])
    steps = [_step("a"), _step("b"), _step("c")]
    out = IdeaActionBridge._rerank_by_fix_risk(steps, str(tmp_path))
    assert [s.target for s in out] == ["c", "b", "a"]
    assert {id(s) for s in out} == {id(s) for s in steps}


def test_rerank_helper_single_or_empty_short_circuits(tmp_path):
    """Fewer than two steps cannot reorder — returns a copy of the input."""
    assert IdeaActionBridge._rerank_by_fix_risk([], str(tmp_path)) == []
    one = [_step("a")]
    out = IdeaActionBridge._rerank_by_fix_risk(one, str(tmp_path))
    assert [s.target for s in out] == ["a"]


def test_rerank_helper_falls_back_when_model_raises(monkeypatch, tmp_path):
    """Best-effort: a raising fix_risk must not crash — the original order is
    returned unchanged."""
    def boom(*_a, **_k):
        raise RuntimeError("no data")

    monkeypatch.setattr(bridge_mod, "fix_risk", boom, raising=False)
    import app.engine.fix_risk_model as frm
    monkeypatch.setattr(frm, "fix_risk", boom)

    steps = [_step("a"), _step("b"), _step("c")]
    out = IdeaActionBridge._rerank_by_fix_risk(steps, str(tmp_path))
    assert [s.target for s in out] == ["a", "b", "c"]
