"""Closed-loop guard: skip fixes the proof history predicts will fail.

These tests pin the OPT-IN, BYTE-IDENTICAL-by-default contract of the
``--avoid-learned-failures`` pre-apply guard threaded through
``IdeaActionBridge.apply_plan`` and ``_MaintenancePass.run_step``:

* OFF (no avoid-map): the apply path is byte-identical to before — no history
  is consulted, no extra summary key, no skip rows, ``apply_step`` is called
  for every executable step.
* ON with a flagging history: the matching step is SKIPPED before any apply
  attempt (``apply_step`` never called for it) and recorded with a reason; the
  others apply normally.
* ON with a clean/empty history: nothing is flagged, so the applied set is the
  same as OFF (with only the additive ``skipped_learned: 0`` tally).
* Deterministic: same history + same plan -> same skips.

Determinism only — no time/random/order assertions.
"""

from __future__ import annotations

from app.engine.counterfactual_learning import failure_signatures
from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _learned_skip_reason,
    render_maintenance_markdown,
)
from app.engine.proof_of_fix import _fix_record
from app.models.idea import ActionPlan, ActionStep


def _step(branch: str, action: str, target: str) -> ActionStep:
    return ActionStep(
        branch_path=branch, title=branch, operator="op", subject=target,
        action_type=action, target=target, executable=True,
    )


def _plan(*steps: ActionStep) -> ActionPlan:
    return ActionPlan(objective="", project_root=".", mode="supervised",
                      steps=list(steps),
                      stats={"total_steps": len(steps),
                             "executable_steps": len(steps)})


class _RecordingBridge(IdeaActionBridge):
    """A bridge whose ``apply_step`` records its calls and always 'applies'
    cleanly — so a test exercises the REAL guard + summary logic in
    ``apply_plan``/``_MaintenancePass`` without running real transforms."""

    def __init__(self) -> None:
        super().__init__()
        self.applied_targets: list[str] = []

    def apply_step(self, step, project_root, mode="supervised", verify=False):
        self.applied_targets.append(step.target)
        # Empty changed_files so the harden_security convergence loop (which
        # re-applies while the target keeps changing) does NOT fire — one
        # apply_step call per step, keeping the call-count assertions exact.
        return {"applied": True, "rolled_back": False, "changed_files": []}


# A proof history where ``harden_security`` predictably FAILS on plain
# ('generic'-trait) modules: 3 attempts, all rolled back -> avoid=True. The
# threshold is >=0.6 failure rate AND >=3 attempts (counterfactual_learning).
def _flagging_history() -> list[dict]:
    fixes = [
        {"finding": {"action": "harden_security", "target": "app/svc.py"},
         "outcome": "rolled_back"}
        for _ in range(3)
    ]
    return [{"fixes": fixes}]


def _clean_history() -> list[dict]:
    return [{"fixes": [
        {"finding": {"action": "harden_security", "target": "app/svc.py"},
         "outcome": "applied"},
    ]}]


# --- OFF: byte-identical -----------------------------------------------------

_OFF_KEYS = {"mode", "verify", "commit", "total_executable", "applied",
             "rolled_back", "blocked", "committed", "results"}


def test_off_is_byte_identical():
    """No avoid-map -> no skips, no extra summary key, every step applies."""
    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"),
                 _step("b1", "harden_security", "app/other.py"))

    summary = bridge.apply_plan(plan, ".", verify=False)

    assert set(summary) == _OFF_KEYS  # no additive skipped_learned key
    assert "skipped_learned" not in summary
    assert summary["applied"] == 2
    assert bridge.applied_targets == ["app/svc.py", "app/other.py"]
    assert all(not r.get("skipped_learned") for r in summary["results"])


def test_off_even_with_flagging_history_when_map_not_passed():
    """A flagging history is irrelevant unless the avoid-map is actually passed:
    the OFF default loads nothing and behaves exactly as today."""
    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"))

    # Default and explicit-None must both be inert.
    s_default = bridge.apply_plan(plan, ".", verify=False)
    bridge2 = _RecordingBridge()
    s_none = bridge2.apply_plan(plan, ".", verify=False, avoid_signatures=None)

    assert "skipped_learned" not in s_default
    assert "skipped_learned" not in s_none
    assert bridge.applied_targets == bridge2.applied_targets == ["app/svc.py"]


# --- ON with a flagging history ---------------------------------------------

def test_on_skips_flagged_step_only():
    """A flagged action on a flagged module-trait is skipped before apply; the
    other (unflagged-action) step still applies."""
    signatures = failure_signatures(_flagging_history())
    assert signatures["harden_security | generic"]["avoid"] is True

    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"),   # flagged
                 _step("b1", "modernize", "app/svc.py"))         # not flagged

    summary = bridge.apply_plan(plan, ".", verify=False,
                                avoid_signatures=signatures)

    # The flagged step never reached apply_step; only the unflagged one did.
    assert bridge.applied_targets == ["app/svc.py"]  # only the modernize step
    assert summary["applied"] == 1
    assert summary["skipped_learned"] == 1

    skipped = [r for r in summary["results"] if r.get("skipped_learned")]
    assert len(skipped) == 1
    row = skipped[0]
    assert row["branch"] == "b0"
    assert row["action"] == "harden_security"
    assert row["applied"] is False
    assert "rolled back 3/3" in row["reason"]
    assert "`generic`" in row["reason"]


def test_on_clean_history_skips_nothing():
    """A clean history flags nothing, so the applied set matches OFF (only the
    additive zero tally differs)."""
    signatures = failure_signatures(_clean_history())
    assert all(not v["avoid"] for v in signatures.values())

    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"),
                 _step("b1", "harden_security", "app/other.py"))

    summary = bridge.apply_plan(plan, ".", verify=False,
                                avoid_signatures=signatures)

    assert bridge.applied_targets == ["app/svc.py", "app/other.py"]
    assert summary["applied"] == 2
    assert summary["skipped_learned"] == 0  # additive, but armed -> present


def test_on_empty_history_skips_nothing():
    """An empty history yields an empty avoid-map -> the guard is inert (the
    map is falsy, so not even the additive tally appears)."""
    signatures = failure_signatures([])
    assert signatures == {}

    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"))

    summary = bridge.apply_plan(plan, ".", verify=False,
                                avoid_signatures=signatures)

    assert bridge.applied_targets == ["app/svc.py"]
    assert "skipped_learned" not in summary  # empty map == OFF


def test_on_is_deterministic():
    """Same history + same plan -> identical skip set across runs."""
    signatures = failure_signatures(_flagging_history())
    plan = _plan(_step("b0", "harden_security", "app/svc.py"),
                 _step("b1", "modernize", "app/svc.py"))

    runs = []
    for _ in range(3):
        bridge = _RecordingBridge()
        summary = bridge.apply_plan(plan, ".", verify=False,
                                    avoid_signatures=signatures)
        runs.append((tuple(bridge.applied_targets), summary["skipped_learned"],
                     tuple(r.get("reason", "") for r in summary["results"]
                           if r.get("skipped_learned"))))
    assert runs[0] == runs[1] == runs[2]


# --- the skip-record shape downstream (report + proof) ----------------------

def test_skip_row_surfaces_in_report_section():
    """A skipped row renders in its own 'Skipped (learned failure)' section,
    NOT as a generic block; an OFF run never emits that section."""
    signatures = failure_signatures(_flagging_history())
    bridge = _RecordingBridge()
    plan = _plan(_step("b0", "harden_security", "app/svc.py"))
    summary = bridge.apply_plan(plan, ".", verify=False,
                                avoid_signatures=signatures)

    md = render_maintenance_markdown(summary, ".")
    assert "Skipped (learned failure)" in md
    assert "history predicts failure" in md

    off_md = render_maintenance_markdown(
        _RecordingBridge().apply_plan(plan, ".", verify=False), ".")
    assert "Skipped (learned failure)" not in off_md


def test_skip_row_proof_outcome_is_skipped_not_blocked():
    """The proof record uses its own ``skipped_learned`` outcome, so a declined
    fix never poisons the failure stats as a fresh failure."""
    row = {"branch": "b0", "action": "harden_security", "operator": "op",
           "target": "app/svc.py", "applied": False, "skipped_learned": True,
           "reason": "history predicts failure"}
    rec = _fix_record(row)
    assert rec["outcome"] == "skipped_learned"
    assert rec["rollback"]["occurred"] is False
    # An ordinary blocked row is unaffected.
    assert _fix_record({"applied": False})["outcome"] == "blocked"


def test_learned_skip_reason_fallback():
    """The reason helper never raises and falls back when no flagged stat
    matches the step's signature (e.g. an empty avoid-map)."""
    step = _step("b0", "harden_security", "app/svc.py")
    assert _learned_skip_reason({}, step).startswith("history predicts failure")


# --- no feedback poisoning: a recorded skip is not re-counted as a failure ---

def test_skipped_proof_does_not_feed_failure_stats():
    """A persisted ``skipped_learned`` fix is excluded by failure_signatures, so
    a declined fix can't self-confirm its own avoidance on the next run."""
    history = [{"fixes": [
        {"finding": {"action": "harden_security", "target": "app/svc.py"},
         "outcome": "skipped_learned"},
        {"finding": {"action": "harden_security", "target": "app/svc.py"},
         "outcome": "skipped_learned"},
        {"finding": {"action": "harden_security", "target": "app/svc.py"},
         "outcome": "skipped_learned"},
    ]}]
    # All three rows are skips -> no evidence at all -> empty signature map.
    assert failure_signatures(history) == {}


# --- CLI flag threading (default OFF, opt-in ON) -----------------------------

def test_cli_avoid_flag_off_loads_nothing(tmp_path, monkeypatch):
    """``_maintain_avoid_signatures`` returns None (loads no history) when the
    flag is absent/False — the OFF byte-identical contract at the CLI seam."""
    import argparse

    import app.cli_autonomy as ca

    def _boom(_root):
        raise AssertionError("history must NOT be loaded when the flag is OFF")

    monkeypatch.setattr("app.engine.proof_history.load_proof_history", _boom)

    args = argparse.Namespace(target=str(tmp_path))  # no avoid_learned_failures
    assert ca._maintain_avoid_signatures(args, tmp_path) is None

    args.avoid_learned_failures = False
    assert ca._maintain_avoid_signatures(args, tmp_path) is None


def test_cli_avoid_flag_on_loads_signatures(tmp_path, monkeypatch):
    """With the flag ON, the CLI seam loads the history once and returns the
    failure-signature map the guard consumes."""
    import argparse

    import app.cli_autonomy as ca

    monkeypatch.setattr("app.engine.proof_history.load_proof_history",
                        lambda root: _flagging_history())

    args = argparse.Namespace(target=str(tmp_path), avoid_learned_failures=True)
    sigs = ca._maintain_avoid_signatures(args, tmp_path)
    assert sigs["harden_security | generic"]["avoid"] is True

