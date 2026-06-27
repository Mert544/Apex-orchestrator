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
