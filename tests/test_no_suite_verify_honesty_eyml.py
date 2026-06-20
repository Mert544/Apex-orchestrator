"""NO-SUITE honesty — a change kept on a project with NO detectable test suite
must be LOUDLY marked unverified-for-lack-of-suite, never blended with a
genuinely-verified change.

The develop/maintain loop applies a change and then runs the project's full test
suite to verify it; on red it auto-rolls-back. But when ``RunTestsSkill`` detects
NO test command (``commands == []``) NOTHING runs: the change is kept, yet it was
never verified and auto-rollback could not have protected it. The verifier used
to stamp a bare ``verified: False`` there — indistinguishable from a fix that ran
against a green suite the tests merely never referenced.

This pins the HONEST surfacing of that gap (the fix does NOT change WHICH changes
apply — many legitimate develop objectives apply pure/additive changes on
suite-less projects):

  * NO suite -> the apply result + proof carry the DISTINCT signal
    ``suite_available=False`` / verification-strength level ``"no-suite"`` (NOT a
    plain ``verified: False`` that looks like a run happened); the report line and
    the proof manifest read it and label the change unverified-for-lack-of-suite.
  * WITH a suite -> the result/proof are BYTE-IDENTICAL to before (the new signal
    appears ONLY on the no-suite path); no ``suite_available`` key, no
    ``no-suite`` coverage.
  * Determinism: two runs of the no-suite pass produce identical rows.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _applied_fix_line,
)
from app.engine.proof_of_fix import build_proof, proof_manifest
from app.execution._apply_verify import (
    NO_SUITE,
    mark_no_suite,
    run_full_suite_verification,
)
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


def _doc_step(target: str, branch: str = "x.1") -> ActionStep:
    # A Tier-0 additive ``add_docstring`` — the kind of pure/additive change a
    # develop objective legitimately applies on a suite-less project (no coverage
    # gate refuses it), so it reaches the no-suite verification path end-to-end.
    return ActionStep(
        branch_path=branch, title=f"doc {target}", operator="document",
        subject=target, action_type="add_docstring", target=target,
        executable=True, source_facts=[f"undocumented: {target}"],
    )


def _run(root: Path, steps: list[ActionStep], *, mode: str = "autonomous",
         commit: bool = True, test_first: bool = False) -> dict:
    # ``test_first=False`` by default: the test-first shield would otherwise WRITE
    # a characterization test before applying, making the project no longer
    # suite-less at verify time. The genuine no-suite path is what we pin here.
    plan = ActionPlan(steps=steps, mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=True, commit=commit,
        test_first=test_first, max_apply=5,
    )


# An undocumented function and — crucially — NO test files anywhere, so
# ``RunTestsSkill`` detects no test command at all.
_UTIL_SRC = "def compute(x):\n    return x * 2\n"


def _build_no_suite(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "app" / "util.py").write_text(_UTIL_SRC)
    _git_init(root)


def _build_with_suite(root: Path) -> None:
    """A project WITH a detectable suite: the SAME undocumented function plus a
    test that references it, so the additive docstring verifies against a real
    green run (the no-suite signal must NOT appear)."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "util.py").write_text(_UTIL_SRC)
    (root / "tests" / "test_util.py").write_text(
        "from app.util import compute\n"
        "def test_compute():\n    assert compute(3) == 6\n")
    _git_init(root)


# --- the shared library tail (the exact denetçi-cited code path) -------------

class _Summary:
    def __init__(self, ok: bool, commands: list[str]) -> None:
        self.ok = ok
        self.commands = commands


def _patch_runner(monkeypatch, summary: _Summary) -> None:
    import app.engine.proof_of_fix as proof_mod
    import app.skills.execution.run_tests as run_tests_mod

    class _FakeSkill:
        def run(self, root: str):  # noqa: ANN001 - test double
            return summary

    monkeypatch.setattr(run_tests_mod, "RunTestsSkill", _FakeSkill)
    monkeypatch.setattr(proof_mod, "summarize_test_run",
                        lambda s: {"ok": s.ok, "performed": bool(s.commands)})


def test_library_tail_no_commands_is_marked_no_suite(monkeypatch) -> None:
    # The exact ``_apply_verify.py`` path the denetçi flagged: no test command ->
    # the change stands, but it is LOUDLY marked unverified-for-lack-of-suite,
    # not an ambiguous bare ``verified: False``.
    _patch_runner(monkeypatch, _Summary(ok=False, commands=[]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["rolled_back"] is False
    # The distinct, loud signal:
    assert out["suite_available"] is False
    assert out["verification_strength"]["level"] == NO_SUITE
    assert out["verification_strength"]["suite_available"] is False
    # ``verified`` stays False (no run happened) — but it is no longer ALONE.
    assert out["verified"] is False


def test_library_tail_with_suite_is_byte_identical(monkeypatch) -> None:
    # A passing suite is byte-identical to before: no ``suite_available`` key, no
    # ``no-suite`` level — the new signal appears ONLY on the no-suite path.
    _patch_runner(monkeypatch, _Summary(ok=True, commands=["pytest"]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["verified"] is True
    assert out["rolled_back"] is False
    assert "suite_available" not in out
    assert "verification_strength" not in out


def test_library_tail_failing_suite_unchanged(monkeypatch) -> None:
    # A real RED suite still requests rollback and carries NO no-suite signal —
    # the absence is about lack-of-suite, never a suite that ran and failed.
    _patch_runner(monkeypatch, _Summary(ok=False, commands=["pytest"]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is False
    assert "suite_available" not in out
    assert "rolled_back" not in out


def test_mark_no_suite_is_additive_over_existing_strength() -> None:
    # ``mark_no_suite`` overlays the level onto whatever strength dict exists,
    # preserving other keys (additive) and never mutating the caller's dict.
    src = {"level": "none", "module_tests": ["t.py"]}
    out = {"verification_strength": src}
    mark_no_suite(out)
    assert out["suite_available"] is False
    assert out["verification_strength"]["level"] == NO_SUITE
    assert out["verification_strength"]["module_tests"] == ["t.py"]
    assert src["level"] == "none"  # caller's dict untouched (copied)


# --- the develop/maintain loop end-to-end ------------------------------------

def test_no_suite_develop_apply_is_marked_unverified(tmp_path):
    _build_no_suite(tmp_path)
    summary = _run(tmp_path, [_doc_step("app/util.py")])

    row = next(r for r in summary["results"]
               if r["action"] == "add_docstring")

    # WHICH changes apply is UNCHANGED: the additive docstring still lands.
    assert row["applied"] is True
    assert '"""' in (tmp_path / "app" / "util.py").read_text()

    # ...but it is LOUDLY marked unverified-for-lack-of-suite, not blended with a
    # verified fix: distinct signal, not a bare ``verified: False``.
    assert row["verified"] is False
    assert row["suite_available"] is False
    assert row["verification_strength"]["level"] == NO_SUITE
    # No suite means no genuine pass to claim.
    assert row.get("suite_green") is not True


def test_no_suite_report_line_is_unmistakable(tmp_path):
    _build_no_suite(tmp_path)
    summary = _run(tmp_path, [_doc_step("app/util.py")])
    row = next(r for r in summary["results"]
               if r["action"] == "add_docstring")

    line = _applied_fix_line(row)
    assert "NOT verified" in line
    assert "no test suite detected" in line
    assert "auto-rollback could not protect" in line
    # It must NOT masquerade as a passing suite.
    assert "tests pass" not in line


def test_no_suite_proof_carries_the_signal(tmp_path):
    _build_no_suite(tmp_path)
    summary = _run(tmp_path, [_doc_step("app/util.py")])

    proof = build_proof(summary, str(tmp_path))
    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "add_docstring")
    assert fix["outcome"] == "applied"
    assert fix["verification"]["strength"]["level"] == NO_SUITE

    # The manifest tallies it honestly under ``no-suite``, never silently
    # collapsed into ``none`` (which would imply a green suite ran).
    manifest = proof_manifest(proof)
    assert manifest["by_coverage"]["no-suite"] == 1
    assert manifest["by_coverage"]["none"] == 0


# --- the WITH-suite case stays byte-identical --------------------------------

def test_with_suite_develop_is_byte_identical(tmp_path):
    _build_with_suite(tmp_path)
    summary = _run(tmp_path, [_doc_step("app/util.py")])

    row = next(r for r in summary["results"]
               if r["action"] == "add_docstring")

    # A green-baseline fix verifies + commits exactly as today; the no-suite
    # signal NEVER appears when a suite exists.
    assert row["applied"] is True
    assert row["verified"] is True
    assert "suite_available" not in row
    assert row["verification_strength"]["level"] != NO_SUITE

    proof = build_proof(summary, str(tmp_path))
    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "add_docstring")
    assert "suite_available" not in fix["verification"]
    assert "suite_available" not in fix["verification"].get("strength", {})
    manifest = proof_manifest(proof)
    assert "no-suite" not in manifest["by_coverage"]


# --- determinism -------------------------------------------------------------

def test_no_suite_pass_is_deterministic(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _build_no_suite(root_a)
    _build_no_suite(root_b)
    a = _run(root_a, [_doc_step("app/util.py")])
    b = _run(root_b, [_doc_step("app/util.py")])

    nondet = {"commit_hash", "duration_seconds"}

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in sorted(obj.items())
                    if k not in nondet}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    assert strip(a["results"]) == strip(b["results"])
