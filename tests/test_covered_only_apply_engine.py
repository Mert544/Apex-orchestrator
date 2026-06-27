"""Engine-level covered-only gate: ``apply_rename`` / ``compile_objective`` roll
back a green-but-unreferencing move, and the bridge ``apply_plan`` forwards it.

These pin the SAFE-by-default mechanism at the gated writer, independent of any
CLI string assembly. Each new assertion was verified to FAIL pre-change (the
``covered_only`` parameter did not exist).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.objective_compiler import compile_objective


def _covered_and_weak(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "covered.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_covered.py").write_text(
        "from pkg.covered import is_missing\n"
        "def test_m():\n    assert is_missing(None) is True\n", encoding="utf-8")
    (root / "pkg" / "weak.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# compile_objective(covered_only=...) — the develop-core sweep engine          #
# --------------------------------------------------------------------------- #
def test_compile_objective_covered_only_withholds_uncovered(tmp_path: Path):
    _covered_and_weak(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=True, covered_only=True)
    landed = {s.target for s in r.steps}
    assert "pkg/covered.py:modernize" in landed
    assert "pkg/weak.py:modernize" not in landed          # withheld, not landed
    assert any("weak.py" in w for w in r.withheld)          # surfaced for messaging
    # The withheld move's file is restored (idiom preserved on disk).
    assert "== None" in (tmp_path / "pkg" / "weak.py").read_text()
    # Every landed step is genuinely coverage-verified.
    assert all(s.coverage_verified for s in r.steps)


def test_compile_objective_default_lands_weak_move(tmp_path: Path):
    # Off (the default / --allow-weak path): BOTH land, byte-for-byte as today.
    _covered_and_weak(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=True)
    landed = {s.target for s in r.steps}
    assert {"pkg/covered.py:modernize", "pkg/weak.py:modernize"} <= landed
    assert r.withheld == []
    assert "value is None" in (tmp_path / "pkg" / "weak.py").read_text()


def test_compile_result_to_dict_withheld_is_additive(tmp_path: Path):
    # A run that withheld nothing omits the key entirely (byte-identical contract).
    _covered_and_weak(tmp_path)
    clean = compile_objective(str(tmp_path), objective="modernize", apply=True,
                              verify=True)
    assert "withheld" not in clean.to_dict()


# --------------------------------------------------------------------------- #
# apply_rename(covered_only=...) — the one legal gated writer                   #
# --------------------------------------------------------------------------- #
def _modernize_plan_for(root: Path, rel: str):
    """The real ``RenamePlan`` the modernize objective would build for ``rel``
    (re-uses the engine's own move builder — no hand-rolled plan)."""
    from app.engine.objective_compiler import _modernize_moves

    mv = next(m for m in _modernize_moves(str(root)) if m.target.startswith(rel + ":"))
    return mv.build_plan()


def test_apply_rename_withholds_uncovered_change(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename

    _covered_and_weak(tmp_path)
    plan = _modernize_plan_for(tmp_path, "pkg/weak.py")
    assert plan.new_contents  # there IS a change to make
    res = apply_rename(str(tmp_path), plan, verify=True, covered_only=True)
    assert res.get("withheld_uncovered") is True
    assert res.get("applied") is False and res.get("rolled_back") is True
    # File restored — the uncovered change was NOT left on disk.
    assert "== None" in (tmp_path / "pkg" / "weak.py").read_text()


def test_apply_rename_covered_change_still_lands(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename

    _covered_and_weak(tmp_path)
    plan = _modernize_plan_for(tmp_path, "pkg/covered.py")
    res = apply_rename(str(tmp_path), plan, verify=True, covered_only=True)
    assert res.get("applied") is True
    assert not res.get("withheld_uncovered")
    assert "value is None" in (tmp_path / "pkg" / "covered.py").read_text()


# --------------------------------------------------------------------------- #
# IdeaActionBridge.apply_plan(covered_only=...) — the maintain/auto sweep gate  #
# --------------------------------------------------------------------------- #
def test_apply_plan_threads_covered_only_to_apply_step(tmp_path, monkeypatch):
    """The bridge sweep path FORWARDS ``covered_only`` to the gated per-step
    writer ``apply_step`` (so the develop-core / SemanticPatch tails enforce it).
    A spy pins the wiring without depending on any one transform's coverage tier.
    """
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan, ActionStep

    _covered_and_weak(tmp_path)
    seen: list[bool] = []
    real = IdeaActionBridge.apply_step

    def _spy(self, step, project_root, *a, covered_only=False, **k):
        seen.append(covered_only)
        return real(self, step, project_root, *a, covered_only=covered_only, **k)

    monkeypatch.setattr(IdeaActionBridge, "apply_step", _spy)
    bridge = IdeaActionBridge()
    step = ActionStep(
        branch_path="x.modernize", title="modernize pkg/covered.py",
        operator="modernize", subject="pkg/covered.py",
        action_type="modernize", target="pkg/covered.py", executable=True)
    plan = ActionPlan(objective="", project_root=str(tmp_path), mode="supervised",
                      steps=[step], stats={"total_steps": 1, "executable_steps": 1})
    bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True,
                      covered_only=True)
    # The covered-only flag reached the gated writer for the planned step.
    assert seen and all(seen)


def test_apply_plan_default_does_not_thread_covered_only(tmp_path, monkeypatch):
    # Off by default: the gated writer is called with covered_only False, so a
    # default maintain/auto pass is byte-identical to today.
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan, ActionStep

    _covered_and_weak(tmp_path)
    seen: list[bool] = []
    real = IdeaActionBridge.apply_step

    def _spy(self, step, project_root, *a, covered_only=False, **k):
        seen.append(covered_only)
        return real(self, step, project_root, *a, covered_only=covered_only, **k)

    monkeypatch.setattr(IdeaActionBridge, "apply_step", _spy)
    bridge = IdeaActionBridge()
    step = ActionStep(
        branch_path="x.modernize", title="modernize pkg/covered.py",
        operator="modernize", subject="pkg/covered.py",
        action_type="modernize", target="pkg/covered.py", executable=True)
    plan = ActionPlan(objective="", project_root=str(tmp_path), mode="supervised",
                      steps=[step], stats={"total_steps": 1, "executable_steps": 1})
    bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    assert seen and not any(seen)


# --------------------------------------------------------------------------- #
# TIER-AWARE withhold (denetçi P0): a smoke-only `module`-coverage move is a    #
# FALSE green for a Tier-1 behaviour change — it must NOT land. A Tier-0        #
# semantics-preserving move with the SAME `module` coverage MUST still land.    #
# --------------------------------------------------------------------------- #
def _module_only_covered(root: Path, body: str, *, names_changed_fn: bool = False) -> None:
    """A package whose module is imported by a test that DOES NOT name the changed
    function (``parse``) — so ``assess_strength`` grades the change ``module``, the
    smoke-only false-green a Tier-1 rewrite must not ride. ``body`` is the source of
    ``pkg/sec.py``; the test always calls ``other()`` only."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "sec.py").write_text(body, encoding="utf-8")
    call = ("from pkg.sec import parse\ndef test_p():\n    assert parse('1') == 1\n"
            if names_changed_fn
            else "import pkg.sec\ndef test_i():\n    assert pkg.sec.other() == 1\n")
    (root / "tests" / "test_sec.py").write_text(call, encoding="utf-8")


_EVAL_BODY = "def parse(s):\n    return eval(s)\n\n\ndef other():\n    return 1\n"
_NONE_BODY = "def parse(s):\n    return s == None\n\n\ndef other():\n    return 1\n"


def test_tier1_module_coverage_is_withheld(tmp_path: Path):
    # harden (eval -> literal_eval) is Tier 1: a test that only IMPORTS the module
    # (coverage == "module", never names parse) can't vouch for the behaviour
    # change. The covered-only sweep WITHHOLDS it — the false-green this fix closes.
    _module_only_covered(tmp_path, _EVAL_BODY)
    r = compile_objective(str(tmp_path), objective="harden", apply=True,
                          verify=True, covered_only=True)
    assert r.steps == []                                   # nothing landed
    assert any("sec.py" in w for w in r.withheld)          # surfaced as withheld
    # The file is restored byte-exact — the eval rewrite did NOT land.
    assert (tmp_path / "pkg" / "sec.py").read_text() == _EVAL_BODY


def test_tier0_module_coverage_still_lands(tmp_path: Path):
    # modernize (== None -> is None) is Tier 0 / semantics-preserving: module
    # coverage IS sound proof, so the SAME `module`-coverage situation LANDS — the
    # tier-aware gate is not over-strict.
    _module_only_covered(tmp_path, _NONE_BODY)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=True, covered_only=True)
    assert any(s.target.endswith(":modernize") for s in r.steps)
    assert r.withheld == []
    assert "is None" in (tmp_path / "pkg" / "sec.py").read_text()


def test_tier1_function_coverage_lands(tmp_path: Path):
    # When a test NAMES the changed function (coverage == "function"), the Tier-1
    # harden is genuinely vouched-for and LANDS — covered-only is about the blind
    # spot, not blocking real coverage.
    _module_only_covered(tmp_path, _EVAL_BODY, names_changed_fn=True)
    r = compile_objective(str(tmp_path), objective="harden", apply=True,
                          verify=True, covered_only=True)
    assert any(s.coverage_verified for s in r.steps)
    assert "literal_eval" in (tmp_path / "pkg" / "sec.py").read_text()


def test_tier1_module_coverage_compiler_and_bridge_agree(tmp_path: Path):
    # The two sweep paths must give the SAME verdict on the SAME logical move (the
    # matrix-consistency invariant): the Tier-1 harden on module-only coverage is
    # withheld by BOTH the compiler (objective) and the bridge (apply_step).
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionStep

    _module_only_covered(tmp_path, _EVAL_BODY)
    comp = compile_objective(str(tmp_path), objective="harden", apply=True,
                             verify=True, covered_only=True)
    compiler_withheld = comp.steps == [] and "literal_eval" not in (
        tmp_path / "pkg" / "sec.py").read_text()

    # Reset and run the identical move via the bridge's gated writer.
    (tmp_path / "pkg" / "sec.py").write_text(_EVAL_BODY, encoding="utf-8")
    step = ActionStep(
        branch_path="x.h", title="harden pkg/sec.py", operator="harden",
        subject="pkg/sec.py", action_type="harden_security",
        target="pkg/sec.py", executable=True)
    br = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                       verify=True, covered_only=True)
    bridge_withheld = (not br.get("applied")) and br.get("verified") is not True

    assert compiler_withheld and bridge_withheld           # both refuse — they agree


def test_coverage_verifies_is_shared_one_predicate():
    # No copy-paste: the bridge's coverage verdict IS the shared risk_tiers one
    # (the grade dedup detector would dock a duplicated copy).
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.execution.risk_tiers import coverage_verifies

    for tier in (0, 1, 2):
        for cov in ("function", "module", "none", "test-change", ""):
            assert (IdeaActionBridge._coverage_verifies(tier, cov)
                    == coverage_verifies(tier, cov))
    # The behaviour the fix turns on: Tier-1 module is a FALSE green, Tier-0 isn't.
    assert coverage_verifies(0, "module") is True
    assert coverage_verifies(1, "module") is False
    assert coverage_verifies(1, "function") is True
