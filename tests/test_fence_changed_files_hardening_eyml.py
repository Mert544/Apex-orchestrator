"""Withheld-change FENCE — gate EVERY staged ``changed_file``, not just target.

Residual defensive gap behind the withhold-fence (commit c16625b): the pre-commit
fence gate in ``app/engine/idea_action_bridge.py`` checked only
``self._is_fenced(step.target)``, but ``_commit`` stages EVERY path in
``r["changed_files"]`` (``git add -- <file>`` per path). A later step whose
``step.target`` is UNFENCED but whose ``changed_files`` includes a FENCED sibling
would bypass the per-target gate and sweep the still-on-disk withheld hunk into
git via whole-file staging.

Not reachable today (no registered transform emits cross-file ``changed_files`` —
``_step_targets`` returns ``[step.target]`` for non-test/non-CI actions), so this
hardens the invariant against a FUTURE cross-file transform: the gate now blocks
when ANY staged file is fenced (``_commit_touches_fenced``), keeping the fenced-
``step.target`` case as a subset and the no-withhold case byte-identical.

These tests drive ``_MaintenancePass`` directly (no cross-file transform exists to
exercise it end-to-end), crafting an applied result whose ``changed_files``
carries a fenced sibling while ``step.target`` is clean.

HARD GATES pinned here:
  * Cross-file leak closed: target unfenced + a fenced path in ``changed_files``
    -> commit WITHHELD, the fenced file is NOT swept into git, entry is fenced.
  * No regression: a fenced ``step.target`` is still blocked (subset behaviour).
  * No regression: when NOTHING is fenced the commit proceeds exactly as before
    (the ``any(...)`` is False), and the file reaches git.
  * Mutation-harden: reverting the gate to a target-only check re-leaks.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _MaintenancePass
from app.models.idea import ActionStep


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


def _head_blob(root: Path, rel: str) -> str:
    out = subprocess.run(["git", "show", f"HEAD:{rel}"],
                         cwd=root, capture_output=True, text=True)
    return out.stdout


def _docstring_step(target: str, branch: str = "x.2") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"document {target}", operator="document",
        subject=target, action_type="add_docstring", target=target,
        executable=True, source_facts=[f"missing-docstring: {target}"],
    )


# Two clean modules. ``sibling.py`` will carry a (simulated) withheld hunk on
# disk and be FENCED; ``lead.py`` is the unfenced ``step.target`` whose crafted
# result also lists the fenced sibling in ``changed_files``.
_LEAD_BEFORE = (
    "def lead(name):\n"
    '    return "lead " + name\n'
)
_LEAD_AFTER = (
    '"""Lead module."""\n'
    "\n"
    "\n"
    "def lead(name):\n"
    '    return "lead " + name\n'
)
_SIBLING_CLEAN = (
    'def run():\n'
    '    return "safe"\n'
)
# The withheld hunk sitting on disk for review — must NEVER reach git.
_SIBLING_WITHHELD_MARK = "WITHHELD_DO_NOT_COMMIT"
_SIBLING_DIRTY = (
    'def run():\n'
    f'    return "{_SIBLING_WITHHELD_MARK}"\n'
)


def _build(root: Path) -> tuple[Path, Path]:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    lead = root / "pkg" / "lead.py"
    sibling = root / "pkg" / "sibling.py"
    lead.write_text(_LEAD_BEFORE)
    sibling.write_text(_SIBLING_CLEAN)
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(root)
    return lead, sibling


def _pass(root: Path) -> _MaintenancePass:
    """A committer-bearing pass with verification/baseline pre-flight short-
    circuited so a crafted Tier-0 result flows straight to the fence gate."""
    mp = _MaintenancePass(
        IdeaActionBridge(), str(root),
        mode="autonomous", verify=False, test_first=False, commit=True,
    )
    assert mp.committer is not None  # autonomous commit is live
    mp._baseline_green = True        # baseline pre-flight already green -> no red gate
    return mp


def _applied_result(changed_files: list[str], disk_path: Path,
                     new_text: str) -> dict:
    """A Tier-0 applied result (verified, real cover) so the only gate that can
    fire is the fence gate. The on-disk write models the apply having landed."""
    disk_path.write_text(new_text)
    return {
        "applied": True,
        "verified": True,
        "coverage": "function",
        "changed_files": list(changed_files),
    }


# --- PIN 1: cross-file leak is closed ----------------------------------------

def test_fenced_sibling_in_changed_files_blocks_commit(tmp_path):
    lead, sibling = _build(tmp_path)
    mp = _pass(tmp_path)

    # An earlier step withheld a behaviour change on sibling.py: fence it and
    # leave the withheld hunk on disk (exactly what _settle_applied/_converge do).
    sibling.write_text(_SIBLING_DIRTY)
    mp._fence_files("pkg/sibling.py")

    # A LATER step targets the UNFENCED lead.py, but its (hypothetically cross-
    # file) result lists the FENCED sibling among changed_files.
    step = _docstring_step("pkg/lead.py")
    r = _applied_result(["pkg/lead.py", "pkg/sibling.py"], lead, _LEAD_AFTER)
    entry: dict = {"risk_tier": 0}
    mp._settle_applied(step, r, entry)

    # The commit is WITHHELD because a staged file is fenced — even though the
    # target itself was clean.
    assert entry.get("committed") is False
    assert entry.get("fenced") is True
    assert "unreviewed withheld change" in entry.get("reason", "")
    assert mp.committed == 0

    # THE BREACH CHECK: the withheld sibling hunk must NOT be in git.
    assert _SIBLING_WITHHELD_MARK not in _head_blob(tmp_path, "pkg/sibling.py")
    # ...and lead.py's docstring was not committed either (the whole commit was
    # withheld, not partially staged).
    assert '"""Lead module."""' not in _head_blob(tmp_path, "pkg/lead.py")


# --- PIN 2: the fenced-target case stays a subset (no regression) ------------

def test_fenced_target_still_blocked(tmp_path):
    lead, _sibling = _build(tmp_path)
    mp = _pass(tmp_path)

    # The target itself is fenced; changed_files holds only the target.
    lead.write_text("def lead(name):\n    return WITHHELD_DO_NOT_COMMIT\n")
    mp._fence_files("pkg/lead.py")

    step = _docstring_step("pkg/lead.py")
    r = _applied_result(["pkg/lead.py"], lead, _LEAD_AFTER)
    entry: dict = {"risk_tier": 0}
    mp._settle_applied(step, r, entry)

    assert entry.get("committed") is False
    assert entry.get("fenced") is True
    assert _SIBLING_WITHHELD_MARK not in _head_blob(tmp_path, "pkg/lead.py")


# --- PIN 3: no-fence case commits exactly as before --------------------------

def test_no_fence_commits_as_before(tmp_path):
    lead, _sibling = _build(tmp_path)
    mp = _pass(tmp_path)

    # Nothing fenced -> any(...) is False -> the commit proceeds.
    step = _docstring_step("pkg/lead.py")
    r = _applied_result(["pkg/lead.py"], lead, _LEAD_AFTER)
    entry: dict = {"risk_tier": 0}
    mp._settle_applied(step, r, entry)

    assert entry.get("committed") is True
    assert entry.get("fenced") is not True
    assert "fenced" not in entry
    assert mp.committed == 1
    assert '"""Lead module."""' in _head_blob(tmp_path, "pkg/lead.py")


# --- PIN 4: mutation-harden — a target-only gate re-leaks ---------------------

def test_mutation_target_only_gate_leaks(tmp_path):
    # Exercises the WHOLE-set gate: the fenced file is in changed_files but is
    # NOT the target. A target-only check (the pre-hardening behaviour) would let
    # this commit through and leak the withheld hunk — so this test FAILS when the
    # gate is reverted to ``_is_fenced(step.target)``.
    lead, sibling = _build(tmp_path)
    mp = _pass(tmp_path)
    sibling.write_text(_SIBLING_DIRTY)
    mp._fence_files("pkg/sibling.py")

    step = _docstring_step("pkg/lead.py")
    r = _applied_result(["pkg/lead.py", "pkg/sibling.py"], lead, _LEAD_AFTER)
    entry: dict = {"risk_tier": 0}
    mp._settle_applied(step, r, entry)

    assert entry.get("committed") is False, (
        "whole-set fence removed: a step whose changed_files holds a fenced "
        "sibling committed, sweeping the withheld change into git"
    )
    assert _SIBLING_WITHHELD_MARK not in _head_blob(tmp_path, "pkg/sibling.py")


# --- direct unit check on the helper -----------------------------------------

def test_commit_touches_fenced_helper(tmp_path):
    mp = _MaintenancePass(
        IdeaActionBridge(), str(tmp_path),
        mode="autonomous", verify=False, test_first=False, commit=True,
    )
    mp._fence_files("pkg/sibling.py")
    step = _docstring_step("pkg/lead.py")

    # Fenced path among changed_files -> True.
    assert mp._commit_touches_fenced(
        {"changed_files": ["pkg/lead.py", "pkg/sibling.py"]}, step) is True
    # No fenced path -> False.
    assert mp._commit_touches_fenced(
        {"changed_files": ["pkg/lead.py"]}, step) is False
    # Empty changed_files falls back to [step.target] (unfenced here) -> False.
    assert mp._commit_touches_fenced({"changed_files": []}, step) is False
    # Fallback to a fenced step.target -> True.
    fenced_step = _docstring_step("pkg/sibling.py")
    assert mp._commit_touches_fenced({"changed_files": []}, fenced_step) is True
