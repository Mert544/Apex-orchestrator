"""Attempts-budget — a cost ceiling on apply+rollback cycles (opt-in, default off).

Headline moat (eyml): ``IdeaActionBridge.apply_plan`` already bounds the number of
APPLIED fixes via ``max_apply``. But ``max_apply=5`` does NOT bound the number of
ATTEMPTS: a run can burn 30 apply+rollback cycles (each one runs the transform +
verify, then rolls back when the suite fails) before five fixes finally land. The
applied counter never moved on a rollback, so the applied budget never fired — the
compute ceiling was missing.

``apply_plan(max_attempts=N)`` adds that ceiling. An ATTEMPT is any step that
reaches the apply stage and is APPLIED OR ROLLED_BACK (it ran the transform +
verify, regardless of outcome); a blocked / safety-gated / learned-skipped step
never reached apply and is NOT an attempt. The single pass AND every drain round
break once ``self.attempted >= max_attempts`` (the counter accumulates across
rounds, never resets), so total apply+rollback cycles can never exceed N.

PINS:
  * CAP-ON-ROLLBACK: a plan of many rollback-prone steps with ``max_attempts=N``
    stops after exactly N attempts even though ``applied < max_apply`` (the applied
    budget would never have stopped it).
  * BYTE-IDENTICAL DEFAULT: ``max_attempts=None`` -> no break, no extra summary
    keys, and a run identical to one that never knew about the budget (runs every
    step).
  * SHARED ACROSS DRAIN: with ``drain=True`` the attempts accumulate across rounds
    — the cap bounds the TOTAL across the single pass + all drain rounds, it is
    never reset per round.
  * DETERMINISM: same fixture twice -> byte-identical results + attempt count.

The rollback-prone behaviour is driven through a deterministic stub of
``apply_step`` (the public seam ``run_step`` calls), so the test pins the budget
CONTROL FLOW without depending on a specific transform+suite combination producing
a real rollback. The byte-identical-default proof additionally runs the REAL apply
path on an on-disk fixture so the ``None`` case is exercised end-to-end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import ActionPlan, ActionStep


# --- helpers -----------------------------------------------------------------

def _git_init(root: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, capture_output=True)


# Unsorted imports -> a real, deterministic ``organize_imports`` fix (Tier-0,
# so no shield/tier gate fires with verify=False).
_SRC = "import sys\nimport os\n\n\ndef f(x):\n    return x + 1\n"


def _step(action: str, target: str, branch: str = "x.1") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"{action} {target}", operator="o",
        subject=target, action_type=action, target=target, executable=True,
    )


def _build_real(tmp_path: Path, n: int) -> Path:
    """``n`` modules each carrying ONE real organize_imports fix."""
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    for i in range(n):
        (pkg / f"m{i}.py").write_text(_SRC)
    _git_init(tmp_path)
    return tmp_path


def _real_plan(n: int) -> ActionPlan:
    return ActionPlan(
        steps=[_step("organize_imports", f"pkg/m{i}.py", f"x.{i}")
               for i in range(n)],
        mode="supervised",
    )


def _rollback_apply_step(*outcomes):
    """A deterministic ``apply_step`` stub: returns the given per-call outcome
    dicts in order (then repeats the last). Each call models one step reaching
    the apply stage with a fixed result (rolled_back / applied / blocked)."""
    calls = {"i": 0}
    seq = list(outcomes)

    def _stub(step, project_root, mode="supervised", verify=False):
        idx = min(calls["i"], len(seq) - 1)
        calls["i"] += 1
        return dict(seq[idx])

    _stub.calls = calls
    return _stub


_ROLLBACK = {"applied": False, "rolled_back": True,
             "reason": "tests failed after patch; changes rolled back",
             "changed_files": []}
_APPLIED = {"applied": True, "rolled_back": False, "changed_files": []}


def _stub_plan(n: int) -> ActionPlan:
    return ActionPlan(
        steps=[_step("organize_imports", f"pkg/m{i}.py", f"x.{i}")
               for i in range(n)],
        mode="supervised",
    )


# --- PIN 1: attempts cap stops a rollback storm the applied budget can't ------

def test_attempts_cap_stops_rollback_storm(monkeypatch):
    """20 rollback-prone steps, ``max_apply=5`` (would NEVER fire — nothing
    applies), ``max_attempts=3`` -> exactly 3 steps reach apply, then stop."""
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "apply_step", _rollback_apply_step(_ROLLBACK))

    summary = bridge.apply_plan(
        _stub_plan(20), "/nonexistent", mode="supervised", verify=False,
        max_apply=5, max_attempts=3,
    )

    assert summary["applied"] == 0          # nothing landed
    assert summary["rolled_back"] == 3      # exactly the attempt ceiling
    assert summary["attempted"] == 3
    assert summary["attempts_exhausted"] is True
    # The applied budget alone would have let all 20 burn — prove the attempts
    # ceiling, not max_apply, is what stopped it.
    assert summary["applied"] < 5
    assert len(summary["results"]) == 3


def test_attempts_cap_counts_applied_and_rolled_back(monkeypatch):
    """An attempt = applied OR rolled_back. A mix of both counts each once; a
    cap of 4 stops after 4 attempts regardless of which outcome each was."""
    bridge = IdeaActionBridge()
    # alternate applied / rolled_back; max_apply high so it never fires.
    monkeypatch.setattr(
        bridge, "apply_step",
        _rollback_apply_step(_APPLIED, _ROLLBACK, _APPLIED, _ROLLBACK,
                             _APPLIED, _ROLLBACK),
    )
    summary = bridge.apply_plan(
        _stub_plan(20), "/nonexistent", mode="supervised", verify=False,
        max_apply=100, max_attempts=4,
    )
    assert summary["attempted"] == 4
    assert summary["applied"] + summary["rolled_back"] == 4
    assert summary["attempts_exhausted"] is True


def test_blocked_step_is_not_an_attempt(monkeypatch):
    """A blocked step never reached apply (transform/verify never ran), so it is
    NOT counted as an attempt — the ceiling only bounds real apply cycles."""
    bridge = IdeaActionBridge()
    _BLOCKED = {"applied": False, "rolled_back": False, "reason": "blocked"}
    monkeypatch.setattr(
        bridge, "apply_step",
        _rollback_apply_step(_BLOCKED, _BLOCKED, _ROLLBACK, _ROLLBACK),
    )
    summary = bridge.apply_plan(
        _stub_plan(20), "/nonexistent", mode="supervised", verify=False,
        max_attempts=2,
    )
    # Two blocked (not attempts) then two rolled_back (attempts) -> stops after
    # the 2nd rollback; blocked never consumed the budget.
    assert summary["blocked"] == 2
    assert summary["rolled_back"] == 2
    assert summary["attempted"] == 2
    assert summary["attempts_exhausted"] is True


# --- PIN 2: byte-identical default (max_attempts=None) ------------------------

def test_none_is_byte_identical_stub(monkeypatch):
    """``max_attempts=None`` -> every step runs, no ``attempted`` /
    ``attempts_exhausted`` keys; result count == plan length."""
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "apply_step", _rollback_apply_step(_ROLLBACK))
    summary = bridge.apply_plan(
        _stub_plan(7), "/nonexistent", mode="supervised", verify=False,
    )
    assert summary["rolled_back"] == 7      # all ran, none stopped
    assert "attempted" not in summary
    assert "attempts_exhausted" not in summary
    assert len(summary["results"]) == 7


def test_none_is_byte_identical_real(tmp_path):
    """The same run with ``max_attempts=None`` vs. NOT PASSING the arg at all is
    byte-identical on a REAL on-disk fixture (the default-off invariant). Each run
    gets its OWN pristine fixture (the apply mutates the tree)."""
    root_legacy = _build_real(tmp_path / "legacy", 3)
    root_none = _build_real(tmp_path / "none", 3)
    bridge = IdeaActionBridge()
    legacy = bridge.apply_plan(_real_plan(3), str(root_legacy),
                               mode="supervised", verify=False)
    explicit_none = bridge.apply_plan(_real_plan(3), str(root_none),
                                      mode="supervised", verify=False,
                                      max_attempts=None)
    # The two runs are on distinct roots, so drop the (root-independent) result
    # fields that don't vary and compare the budget-relevant summary.
    assert legacy == explicit_none
    assert legacy["applied"] == 3
    assert "attempted" not in legacy
    assert "attempts_exhausted" not in legacy


# --- PIN 3: attempts accumulate across drain rounds --------------------------

def _drain_replan(counter):
    """A re-plan callable that yields a fresh 2-step plan each round: one step
    that APPLIES (a NEW changed file, so the drain keeps progressing) followed by
    one that ROLLS BACK (a burned apply+rollback cycle). Each round therefore
    spends 2 attempts but only 1 apply — the exact shape a cost ceiling must
    bound."""
    def _replan(changed):
        counter["r"] += 1
        r = counter["r"]
        return ActionPlan(
            steps=[
                _step("organize_imports", f"pkg/applied_{r}.py", f"d.{r}.a"),
                _step("organize_imports", f"pkg/rolled_{r}.py", f"d.{r}.b"),
            ],
            mode="supervised",
        )
    return _replan


# Each apply call: the applied step reports its OWN new changed file (drain
# progresses); the rollback step reports none. Drive this by step.branch suffix.
def _drain_apply_step():
    def _stub(step, project_root, mode="supervised", verify=False):
        if step.branch_path.endswith(".a") or step.branch_path == "x.0":
            # An applying step exposes a brand-new file so the drain has a
            # non-empty changed set and keeps going.
            return {"applied": True, "rolled_back": False,
                    "changed_files": [f"pkg/new_{step.branch_path}.py"]}
        return {"applied": False, "rolled_back": True, "changed_files": [],
                "reason": "tests failed after patch; changes rolled back"}
    return _stub


def test_attempts_shared_across_drain_rounds(monkeypatch):
    """With ``drain=True`` the attempt budget caps TOTAL attempts across the
    single pass + every drain round — never reset per round."""
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "apply_step", _drain_apply_step())

    # Single pass: one applying step (x.0) + one rollback (x.1) = 2 attempts.
    single = ActionPlan(
        steps=[_step("organize_imports", "pkg/a.py", "x.0"),
               _step("organize_imports", "pkg/b.py", "x.1")],
        mode="supervised",
    )
    counter = {"r": 0}
    summary = bridge.apply_plan(
        single, "/nonexistent", mode="supervised", verify=False,
        drain=True, replan=_drain_replan(counter), max_rounds=8, max_attempts=5,
    )

    # 2 (single pass) + drain rounds (2 attempts each), but TOTAL attempts capped
    # at 5 — proving the budget is shared across rounds, never reset.
    assert summary["attempted"] == 5
    assert summary["attempts_exhausted"] is True
    # The drain ran past the single pass (which alone is only 2 attempts) but
    # stopped on the budget, not on max_rounds.
    assert summary["drain_rounds"] >= 1
    assert summary["drain_rounds"] < 8


def test_drain_none_attempts_runs_further(monkeypatch):
    """Without an attempts cap (None) the SAME drain runs MORE rounds than the
    capped run above — proving the cap, not some other limit, is what stopped it.
    No ``attempted`` key is emitted."""
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "apply_step", _drain_apply_step())
    single = ActionPlan(
        steps=[_step("organize_imports", "pkg/a.py", "x.0"),
               _step("organize_imports", "pkg/b.py", "x.1")],
        mode="supervised",
    )
    counter = {"r": 0}
    summary = bridge.apply_plan(
        single, "/nonexistent", mode="supervised", verify=False,
        drain=True, replan=_drain_replan(counter), max_rounds=4,
    )
    assert "attempted" not in summary
    assert "attempts_exhausted" not in summary
    # Single pass (2) + 4 drain rounds * 2 = 10 attempts, none capped.
    assert summary["applied"] + summary["rolled_back"] == 10
    assert summary["drain_rounds"] == 4


# --- PIN 4: determinism -------------------------------------------------------

def test_determinism(monkeypatch):
    def _run():
        b = IdeaActionBridge()
        monkeypatch.setattr(b, "apply_step", _rollback_apply_step(_ROLLBACK))
        return b.apply_plan(_stub_plan(20), "/nonexistent", mode="supervised",
                            verify=False, max_apply=9, max_attempts=4)

    a = _run()
    b = _run()
    assert a["attempted"] == b["attempted"] == 4
    assert a["results"] == b["results"]
    assert a == b
