"""Cascade-drain — apply fixes to a true RE-DETECTED fixpoint (opt-in, bounded).

Headline moat (eyml): ``IdeaActionBridge.apply_plan`` iterated the plan ONCE, in
order. A fix that EXPOSED or UNBLOCKED a second fixable issue was missed until a
separate pass — the loop was detect → fix, never detect → fix → RE-DETECT →
prove. The cascade-drain wraps the single apply pass in a bounded
re-detect → re-plan → apply OUTER loop (opt-in ``drain=True``, hard ``max_rounds``
cap), so the loop converges to a real fixpoint:

  * after a round that applies >=1 fix, re-detect over ONLY the sorted set of
    files earlier fixes changed, build a fresh plan, DEDUP every already-attempted
    ``(action, target)`` signature, and apply;
  * the drain draws from the SAME ``max_apply`` budget (never reset per round), so
    total applied across all rounds can never exceed the budget;
  * it STOPS when a round applies zero new fixes OR ``max_rounds`` is reached, and
    records the round count / convergence additively (``drain_rounds`` /
    ``converged``).

HARD GATES pinned here:
  * A-EXPOSES-B: a fixture where fix A (the round-0 single pass) exposes fix B that
    the single pass never re-examines -> ``drain=True`` applies BOTH (the round-0
    pass + one extra drain round) and records the round count; ``drain=False``
    applies ONLY fix A (byte-identical single pass).
  * BYTE-IDENTICAL DEFAULT: ``drain=False`` summary keys + results are identical to
    a run that never knew about the drain (no ``drain_rounds``/``converged`` keys).
  * BUDGET SHARED: the drain honours ``max_apply`` across rounds — total applied
    never exceeds it even when more fixes are exposed.
  * MAX_ROUNDS CAP: a pathological re-exposing fixture (every round exposes a fresh
    fix) stops at exactly ``max_rounds`` and reports ``converged: False``.
  * IDEMPOTENT: a second drain over a converged tree applies zero (no changed set
    -> zero rounds, ``converged: True``).
  * WITHHELD DOES NOT LOOP: a fix that is applied-on-disk-but-withheld is added to
    the dedup skip-set, so the drain never re-attempts it and terminates.
  * DETERMINISM: same fixture twice -> byte-identical results + round count.

Deterministic, stdlib + pytest only. The A-exposes-B cascade is driven through an
injected ``replan`` callable (the public seam the drain re-detects through), so
the test pins the convergence CONTROL FLOW without depending on a specific pair of
transforms co-occurring in one file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


_SRC = "import os\nimport sys\n\n\ndef f(x):\n    return x + 1\n"


def _step(action: str, target: str, branch: str = "x.1") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"{action} {target}", operator="o",
        subject=target, action_type=action, target=target, executable=True,
    )


def _build(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    # Two modules, each carrying ONE deterministic fixable issue (unsorted
    # imports). ``a.py`` is the round-0 fix; ``b.py`` is the fix only re-detected
    # AFTER ``a.py`` has been changed (modelled by the injected re-plan).
    (pkg / "a.py").write_text(_SRC)
    (pkg / "b.py").write_text(_SRC)
    _git_init(tmp_path)
    return tmp_path


def _replan_a_exposes_b(changed: list[str]) -> ActionPlan:
    """Fix B (organize_imports on pkg/b.py) becomes detectable ONLY once fix A
    has changed pkg/a.py — the exact "A exposed B" cascade the single pass
    misses. Re-detection over the changed set returns B's step; a converged
    re-plan (b.py already handled) returns an empty plan."""
    if "pkg/a.py" in changed:
        return ActionPlan(steps=[_step("organize_imports", "pkg/b.py", "x.2")],
                          mode="supervised")
    return ActionPlan(steps=[], mode="supervised")


def _apply(root: Path, *, drain: bool, replan=None, max_apply=None,
           max_rounds: int = 8, plan_steps=None, mode: str = "supervised") -> dict:
    steps = plan_steps if plan_steps is not None else [_step("organize_imports", "pkg/a.py")]
    plan = ActionPlan(steps=steps, mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=False, drain=drain,
        replan=replan, max_apply=max_apply, max_rounds=max_rounds,
    )


# --- PIN 1: A exposes B — drain applies both, single pass applies only A ------

def test_drain_applies_b_that_single_pass_misses(tmp_path):
    root = _build(tmp_path)

    single = _apply(root, drain=False)
    # Single pass: only fix A applied, and NO drain keys leak into the summary.
    assert single["applied"] == 1
    assert [r["target"] for r in single["results"] if r.get("applied")] == ["pkg/a.py"]
    assert "drain_rounds" not in single
    assert "converged" not in single


def test_drain_true_converges_to_fixpoint_across_two_rounds(tmp_path):
    root = _build(tmp_path)

    summary = _apply(root, drain=True, replan=_replan_a_exposes_b)

    # BOTH A and B applied: the drain re-detected B (exposed by A) and applied it.
    applied_targets = sorted(r["target"] for r in summary["results"] if r.get("applied"))
    assert applied_targets == ["pkg/a.py", "pkg/b.py"]
    assert summary["applied"] == 2
    # Two passes land both fixes: the round-0 single pass (A) + ONE extra drain
    # round that re-detected and applied B. A subsequent re-detect finds only the
    # already-handled B (deduped) -> no further productive round -> converged.
    assert summary["drain_rounds"] == 1
    assert summary["converged"] is True


# --- PIN 2: byte-identical default (drain=False == legacy single pass) --------

def test_drain_false_byte_identical_to_legacy(tmp_path):
    root_a = _build(tmp_path / "a")
    root_b = _build(tmp_path / "b")

    # A run that passes NO drain kwargs at all (legacy call shape).
    plan = ActionPlan(steps=[_step("organize_imports", "pkg/a.py")], mode="supervised")
    legacy = IdeaActionBridge().apply_plan(plan, str(root_a), mode="supervised", verify=False)
    drained_off = _apply(root_b, drain=False)

    assert set(legacy.keys()) == set(drained_off.keys())
    assert "drain_rounds" not in legacy
    assert legacy["applied"] == drained_off["applied"]
    assert [r.get("target") for r in legacy["results"]] == \
        [r.get("target") for r in drained_off["results"]]
    assert (root_a / "pkg" / "a.py").read_text() == (root_b / "pkg" / "a.py").read_text()


# --- PIN 3: budget shared across rounds ---------------------------------------

def test_max_apply_budget_shared_across_rounds(tmp_path):
    root = _build(tmp_path)

    # Budget of 1: fix A spends it in round 0, so the drain must apply ZERO more
    # even though B is exposed — total applied can never exceed the budget.
    summary = _apply(root, drain=True, replan=_replan_a_exposes_b, max_apply=1)

    assert summary["applied"] == 1
    assert [r["target"] for r in summary["results"] if r.get("applied")] == ["pkg/a.py"]
    # b.py is exposed but never applied — the drain stopped at the shared budget.
    assert (root / "pkg" / "b.py").read_text() == _SRC


# --- PIN 4: max_rounds cap on a pathological re-exposing fixture ---------------

def test_max_rounds_cap_terminates_pathological_drain(tmp_path):
    root = _build(tmp_path)
    # Each round creates a FRESH module and exposes a fix on it forever — without
    # a cap this would never converge. ``max_rounds`` must hard-stop it.
    counter = {"n": 0}

    def _endless_replan(changed: list[str]) -> ActionPlan:
        counter["n"] += 1
        name = f"gen{counter['n']}"
        mod = root / "pkg" / f"{name}.py"
        mod.write_text(_SRC)
        return ActionPlan(steps=[_step("organize_imports", f"pkg/{name}.py",
                                        f"x.{counter['n']}")], mode="supervised")

    summary = _apply(root, drain=True, replan=_endless_replan, max_rounds=3)

    # Stopped at exactly the cap and reported NON-convergence.
    assert summary["drain_rounds"] == 3
    assert summary["converged"] is False
    # 1 (fix A) + 3 capped rounds = 4 applied; the loop did not run away.
    assert summary["applied"] == 4


# --- PIN 5: idempotent — a second drain over a converged tree applies zero -----

def test_second_drain_on_converged_tree_applies_zero(tmp_path):
    root = _build(tmp_path)

    first = _apply(root, drain=True, replan=_replan_a_exposes_b)
    assert first["applied"] == 2  # A + B landed

    # Second invocation: a.py/b.py are already tidy. The single pass applies
    # nothing, so there is no changed set -> the drain runs ZERO rounds and
    # reports convergence immediately. Idempotent.
    second = _apply(root, drain=True, replan=_replan_a_exposes_b)
    assert second["applied"] == 0
    assert second["drain_rounds"] == 0
    assert second["converged"] is True


# --- PIN 6: a withheld/fenced fix never causes an infinite re-attempt ----------

def test_withheld_fix_is_deduped_and_drain_terminates(tmp_path):
    """A re-plan that keeps re-surfacing the SAME (already-attempted) fix must NOT
    loop forever: the dedup skip-set drops the re-surfaced signature, so the round
    applies nothing new and the drain converges. This is the mechanism that stops
    a withheld/fenced fix (applied-on-disk, signature handled) from being retried
    every round."""
    root = _build(tmp_path)
    seen = {"n": 0}

    def _resurface_same(changed: list[str]) -> ActionPlan:
        # Always re-propose the very fix already applied in round 0 (same
        # signature). The drain must DEDUP it, not re-attempt it.
        seen["n"] += 1
        return ActionPlan(steps=[_step("organize_imports", "pkg/a.py")],
                          mode="supervised")

    summary = _apply(root, drain=True, replan=_resurface_same, max_rounds=8)

    # Only the round-0 fix counted; the re-surfaced duplicate applied nothing, so
    # the drain stopped after a single non-progressing round (well under the cap).
    assert summary["applied"] == 1
    assert summary["drain_rounds"] <= 1
    assert summary["converged"] is True


# --- PIN 6b: a REAL withheld behaviour change is deduped, drain terminates -----

# pickle (Tier-0 flag, committed) THEN behaviour-changing subprocess/yaml — the
# converged behaviour change is withheld on an UNTESTED module (proven by
# test_converge_harden_gate_eyml).
_VULN = (
    "import pickle\n"
    "import subprocess\n"
    "import yaml\n"
    "\n\n"
    "def load(b):\n    return pickle.loads(b)\n"
    "\n\n"
    "def run():\n    return subprocess.run(\"ls\", shell=True)\n"
    "\n\n"
    "def parse(text):\n    return yaml.load(text)\n"
)


def test_real_withheld_fix_not_re_attempted_each_round(tmp_path):
    """An autonomous behaviour-changing harden on an UNTESTED module is applied on
    disk but WITHHELD from commit (the withhold-fence path). Its signature is in
    the dedup skip-set, so a re-plan that re-surfaces the SAME harden never
    re-attempts it — the drain terminates instead of looping on the withheld fix."""
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "vuln.py").write_text(_VULN)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    attempts = {"n": 0}

    def _resurface_harden(changed: list[str]) -> ActionPlan:
        attempts["n"] += 1
        # Re-propose the SAME harden every round; the drain must dedup it.
        return ActionPlan(steps=[_step("harden_security", "pkg/vuln.py")],
                          mode="autonomous")

    plan = ActionPlan(steps=[_step("harden_security", "pkg/vuln.py")], mode="autonomous")
    summary = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="autonomous", verify=True, commit=True,
        test_first=True, max_apply=5, drain=True, replan=_resurface_harden,
        max_rounds=8,
    )

    # The harden applied on disk but was withheld from commit (fence/withhold).
    row = next(r for r in summary["results"] if r["action"] == "harden_security")
    assert row.get("commit_withheld") or row.get("converged_withheld")
    # It is NOT re-attempted every round: the re-surfaced signature is deduped, so
    # the drain converges well under the cap rather than looping forever.
    assert summary["drain_rounds"] < 8
    assert summary["converged"] is True


# --- PIN 7: determinism — same fixture twice -> byte-identical ----------------

_NONDET_KEYS = {"commit_hash", "duration_seconds"}


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in sorted(obj.items()) if k not in _NONDET_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def test_determinism_byte_identical(tmp_path):
    root_a = _build(tmp_path / "a")
    root_b = _build(tmp_path / "b")

    a = _apply(root_a, drain=True, replan=_replan_a_exposes_b)
    b = _apply(root_b, drain=True, replan=_replan_a_exposes_b)

    assert a["drain_rounds"] == b["drain_rounds"]
    assert _strip(a["results"]) == _strip(b["results"])
    assert (root_a / "pkg" / "b.py").read_text() == (root_b / "pkg" / "b.py").read_text()


# --- PIN 8: default re-plan (real engine) is offline + deterministic -----------

def test_default_replan_runs_offline_and_converges(tmp_path):
    """With no injected ``replan`` the drain falls back to re-running the idea
    engine on the project (offline by default) and converges without crashing.
    Pins that the default seam is wired and terminates."""
    root = _build(tmp_path)
    summary = _apply(root, drain=True, max_rounds=4)
    # Whatever the engine re-detects, the drain must terminate within the cap and
    # report a bounded round count + a convergence verdict.
    assert isinstance(summary["drain_rounds"], int)
    assert 0 <= summary["drain_rounds"] <= 4
    assert isinstance(summary["converged"], bool)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
