"""The action plan bridges the develop objective ``wire-exports`` into
``apex ideate --actions`` as an executable step.

wire-exports deterministically rewrites a package ``__init__.py`` to declare its
public re-export surface (``from .module import Name`` lines + a complete sorted
``__all__``). It is PURE + an IMPORT ORACLE (no pytest): before the candidate is
allowed to stand it is subprocess-imported and every name in the new ``__all__``
must resolve. Like ``cover-gaps`` it is NOT a SemanticPatchResult transform —
``apply_step`` delegates it to the develop-core ``apply_rename`` path (with
``impact_scope=True``). These tests assert:

  - the synthesis grounding signal ``wire_export_packages`` equals the lander's
    own gate (a non-empty ``plan_wire_exports(...).new_contents``): an unwired
    package with a public surface qualifies; an already-wired package, a package
    with nothing public to export, and a non-package ``.py`` module do NOT
    (honesty / no over-promise);
  - the augmentation emits an executable ``wire_exports`` step (in the Refine
    phase) for the qualifying package and none for the negatives;
  - wire-exports is OPT-IN (default off): a default plan emits NO wire_exports
    step and is byte-identical run-to-run (idea set never shifts);
  - a project with NO wireable package is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real ``__all__`` change through the
    delegated develop-core path, and honestly no-ops (writing nothing) on a
    package with no wire-export.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import wire_export_packages
from app.execution.objectives.wire_exports import plan_wire_exports
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that puts ``subject`` (a ``.py`` path — a package ``__init__.py``
    IS one) into the plan as a candidate target for the synthesis augmentation.
    Descending values keep a stable order."""
    return IdeaNode(
        id=str(i), title=f"Develop {subject}", subject=subject,
        branch_path=f"x.{i}", operator="root",
        source_facts=[f"dependency-hub: {subject}"], value=1.0 - i * 0.01,
    )


def _report(root: Path, modules: list[str]) -> IdeaTreeReport:
    ideas = [_idea(i, m) for i, m in enumerate(modules)]
    return IdeaTreeReport(objective="dev", project_root=str(root), ideas=ideas)


# One unwired package Apex CAN wire, plus the honesty-negatives the lander would
# refuse (an already-wired package, a package with no public surface, and a
# non-package loose module).
_QUALIFYING = ["pkg/__init__.py"]
_NEGATIVE = ["wired/__init__.py", "empty/__init__.py", "loose.py"]


def _wireable_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    # Unwired package: empty __init__ + public sibling modules => the lander emits
    # a re-export surface + __all__ that the import oracle proves resolves.
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py", "def run():\n    return 1\n\n\nclass Engine:\n    pass\n")
    _write(root, "pkg/io.py", "def load():\n    return 2\n")
    # Already wired: __all__ already names every export => empty no-op plan.
    _write(root, "wired/mod.py", "def go():\n    return 1\n")
    _write(root, "wired/__init__.py", 'from .mod import go\n\n__all__ = [\n    "go",\n]\n')
    # Nothing public to export (only an underscore-private module) => no-op plan.
    _write(root, "empty/__init__.py", "")
    _write(root, "empty/_priv.py", "def _x():\n    return 1\n")
    # A loose non-package module is not a wire-exports target => no-op plan.
    _write(root, "loose.py", "def f():\n    return 1\n")
    return root


def _wire_steps(plan) -> dict[str, str]:
    """{package_target: phase} for the executable wire_exports steps in a plan."""
    return {
        s.target: s.phase
        for s in plan.steps
        if s.operator == "synthesis" and s.action_type == "wire_exports" and s.executable
    }


# --- the grounding signal equals the lander's own gate (honesty) --------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _wireable_project(tmp_path)
    mods = _QUALIFYING + _NEGATIVE
    # The signal lights up ONLY the unwired-with-public-surface package.
    assert wire_export_packages(str(root), mods) == ["pkg/__init__.py"]
    # And that is EXACTLY the lander's own gate: a non-empty new_contents.
    assert bool(plan_wire_exports(str(root), "pkg/__init__.py").new_contents) is True
    for neg in _NEGATIVE:
        assert bool(plan_wire_exports(str(root), neg).new_contents) is False


def test_signal_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = tmp_path / "many"
    # Two independent wireable packages; sorted, deduped, cap honored.
    _write(root, "b/__init__.py", "")
    _write(root, "b/mod.py", "def b():\n    return 2\n")
    _write(root, "a/__init__.py", "")
    _write(root, "a/mod.py", "def a():\n    return 1\n")
    mods = ["b/__init__.py", "a/__init__.py", "b/__init__.py"]  # dup collapses
    assert wire_export_packages(str(root), mods) == ["a/__init__.py", "b/__init__.py"]
    assert wire_export_packages(str(root), mods, limit=1) == ["a/__init__.py"]


def test_signal_never_raises_on_missing_or_broken(tmp_path: Path) -> None:
    root = tmp_path / "edge"
    # A package whose only module is unparseable contributes no public symbol, so
    # there is nothing to wire (empty no-op plan) — never a raise.
    _write(root, "broken/__init__.py", "")
    _write(root, "broken/mod.py", "def oops(:\n")  # syntax error
    # Missing path + broken-content package both simply do not qualify.
    assert wire_export_packages(str(root), ["nope/__init__.py", "broken/__init__.py"]) == []
    assert wire_export_packages(str(root), []) == []  # empty input


# --- the augmentation surfaces the qualifying package, and no negative --------

def test_plan_tree_surfaces_executable_wire_exports_step(tmp_path: Path) -> None:
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), wire_exports=True)
    assert _wire_steps(plan) == {"pkg/__init__.py": "Refine"}


def test_plan_roadmap_phases_wire_exports_in_refine(tmp_path: Path) -> None:
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root), wire_exports=True)
    assert _wire_steps(plan) == {"pkg/__init__.py": "Refine"}


def test_wire_exports_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented wire_exports step is a real runnable contribution, so it
    raises the plan's executable-step count (the exact delta also covers any
    sibling synthesis objective the qualifying package legitimately lights up)."""
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    plain = bridge.plan_tree(_report(root, _NEGATIVE), project_root=str(root),
                             wire_exports=True)
    augmented = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                                 project_root=str(root), wire_exports=True)
    wire_added = len(_wire_steps(augmented))
    assert wire_added == 1  # exactly the one qualifying package
    # The executable count rises by AT LEAST the wire_exports step (the qualifying
    # package may honestly also light up another synthesis signal).
    assert (augmented.stats["executable_steps"]
            >= plain.stats["executable_steps"] + wire_added)


# --- opt-in: wire-exports is OFF by default (idea set never shifts) -----------

def test_wire_exports_is_off_by_default(tmp_path: Path) -> None:
    """wire-exports targets packages BROADLY, so it is opt-in: a default
    ``plan_tree`` (no ``wire_exports=True``) emits NO wire_exports step even on a
    wireable project, and is byte-identical run-to-run (default off → no shift)."""
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _wire_steps(default) == {}
    assert [s for s in default.steps if s.action_type == "wire_exports"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), wire_exports=True)
    assert _wire_steps(opted) == {"pkg/__init__.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_wire_exports_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds wire-exports unless opted in."""
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _wire_steps(default) == {}


def test_opting_in_wire_exports_does_not_pull_in_cover_gaps(tmp_path: Path) -> None:
    """The two broad opt-in objectives are INDEPENDENT flags: opting wire-exports
    in must not enable cover-gaps (and the wireable package's modules are covered,
    so cover-gaps would otherwise have nothing here anyway)."""
    root = _wireable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), wire_exports=True)
    assert [s for s in plan.steps if s.action_type == "cover_gaps"] == []
    assert _wire_steps(plan) == {"pkg/__init__.py": "Refine"}


# --- determinism / opt-in safety: a no-wire project adds NOTHING --------------

def test_no_wireable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with wire-exports OPTED IN, a project with NO wireable package (every
    package already fully wired) gets nothing added and the plan is byte-identical
    run-to-run — proving the augmentation honestly no-ops."""
    root = tmp_path / "plain"
    _write(root, "alpha/mod.py", "def a():\n    return 1\n")
    _write(root, "alpha/__init__.py", 'from .mod import a\n\n__all__ = [\n    "a",\n]\n')
    _write(root, "beta/mod.py", "def b():\n    return 2\n")
    _write(root, "beta/__init__.py", 'from .mod import b\n\n__all__ = [\n    "b",\n]\n')
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha/__init__.py", "beta/__init__.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), wire_exports=True)
    assert [s for s in plan.steps
            if s.operator == "synthesis" and s.action_type == "wire_exports"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   wire_exports=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_wire_exports_step() -> None:
    """Without a project root the signal cannot read any package, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "pkg/__init__.py")])
    plan = bridge.plan_tree(rpt, project_root="", wire_exports=True)
    assert [s for s in plan.steps
            if s.operator == "synthesis" and s.action_type == "wire_exports"] == []


# --- apply_step actually LANDS the real __all__ change / no-ops honestly -------

def test_apply_step_lands_wire_exports_change(tmp_path: Path) -> None:
    """The wire_exports step lands the real re-export surface + ``__all__`` through
    the delegated develop-core path (impact-scoped verify), proving the executable
    claim is end-to-end real and not just surfaced."""
    root = tmp_path / "land"
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py", "def run():\n    return 1\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["pkg/__init__.py"]),
                            project_root=str(root), wire_exports=True)
    steps = [s for s in plan.steps
             if s.action_type == "wire_exports" and s.executable]
    assert steps, "a wire_exports step should be surfaced for an unwired package"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "wire_exports"
    # The package __init__.py now declares the proven public re-export surface.
    wired = (root / "pkg" / "__init__.py").read_text(encoding="utf-8")
    assert "from .engine import run" in wired
    assert '__all__ = [' in wired and '"run",' in wired


def test_apply_step_wire_exports_verifies_against_importing_test(tmp_path: Path) -> None:
    """With a test that imports the package, the delegated impact-scoped verify
    runs that real test and reports the suite green — the import oracle plus the
    impacted-test gate together prove the wiring is safe end-to-end."""
    root = tmp_path / "verify"
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py", "def run():\n    return 1\n")
    # A test that imports the package through its (about-to-be-wired) surface.
    _write(root, "tests/test_pkg.py",
           "from pkg import run\n\n\ndef test_run():\n    assert run() == 1\n")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="pkg/__init__.py", action_type="wire_exports",
                      target="pkg/__init__.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out.get("suite_green") is True  # the importing test passed post-wire
    assert "from .engine import run" in (root / "pkg" / "__init__.py").read_text(
        encoding="utf-8")


def test_apply_step_wire_exports_noops_on_no_wire(tmp_path: Path) -> None:
    """A package that is already fully wired is honestly NOT applied and its
    ``__init__.py`` is left byte-for-byte untouched — the delegated path never
    fakes green."""
    root = tmp_path / "noop"
    _write(root, "pkg/mod.py", "def go():\n    return 1\n")
    _write(root, "pkg/__init__.py", 'from .mod import go\n\n__all__ = [\n    "go",\n]\n')
    before = (root / "pkg" / "__init__.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="pkg/__init__.py", action_type="wire_exports",
                      target="pkg/__init__.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "wire_exports"
    # The already-wired __init__.py is left byte-for-byte untouched.
    assert (root / "pkg" / "__init__.py").read_text(encoding="utf-8") == before
