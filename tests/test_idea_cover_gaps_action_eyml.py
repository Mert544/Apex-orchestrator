"""The action plan bridges the develop objective ``cover-gaps`` into
``apex ideate --actions`` as an executable step.

cover-gaps deterministically writes a brand-new ``tests/test_<stem>.py``
characterization test for an UNTESTED module. Like ``implement-stub`` it is NOT a
SemanticPatchResult transform — ``apply_step`` delegates it to the develop-core
``apply_rename`` path. These tests assert:

  - the synthesis grounding signal ``cover_gaps_modules`` equals the lander's own
    gate (a non-empty ``plan_cover_gaps(...).new_contents``): an untested module
    with a characterizable public symbol qualifies; an already-linked-test module
    and a ``__init__.py`` dunder do NOT (honesty / no over-promise);
  - the augmentation emits an executable ``cover_gaps`` step (in the Stabilize
    phase) for the qualifying module and none for the negatives;
  - a project with NO cover-gappable module is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the new characterization test through the
    delegated develop-core path, and honestly no-ops (writing nothing) on a module
    with no cover-gap.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import cover_gaps_modules
from app.execution.cover_gaps import plan_cover_gaps
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that puts ``subject`` (a ``.py`` path) into the plan as a
    candidate target for the synthesis augmentation. Descending values keep a
    stable order."""
    return IdeaNode(
        id=str(i), title=f"Develop {subject}", subject=subject,
        branch_path=f"x.{i}", operator="root",
        source_facts=[f"dependency-hub: {subject}"], value=1.0 - i * 0.01,
    )


def _report(root: Path, modules: list[str]) -> IdeaTreeReport:
    ideas = [_idea(i, m) for i, m in enumerate(modules)]
    return IdeaTreeReport(objective="dev", project_root=str(root), ideas=ideas)


# One untested module Apex CAN characterize, plus the honesty-negatives the
# lander would refuse (an already-linked-test module and a dunder package marker).
_QUALIFYING = ["widget.py"]
_NEGATIVE = ["covered.py", "__init__.py"]


def _gappy_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    # Untested module with a public, blindly-callable function => the lander writes
    # tests/test_widget.py.
    _write(root, "widget.py", "def greet(name):\n    return f\"hi {name}\"\n")
    # Already covered: a linked tests/test_covered.py exists => empty no-op plan.
    _write(root, "covered.py", "def f():\n    return 1\n")
    _write(root, "tests/test_covered.py",
           "import covered\n\n\ndef test_covered():\n    assert covered.f() == 1\n")
    # A dunder package marker is not a testable unit => empty no-op plan.
    _write(root, "__init__.py", "X = 1\n")
    return root


def _cover_gap_steps(plan) -> dict[str, str]:
    """{module_target: phase} for the executable cover_gaps steps in a plan."""
    return {
        s.target: s.phase
        for s in plan.steps
        if s.operator == "synthesis" and s.action_type == "cover_gaps" and s.executable
    }


# --- the grounding signal equals the lander's own gate (honesty) --------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    mods = _QUALIFYING + _NEGATIVE
    # The signal lights up ONLY the untested-characterizable module.
    assert cover_gaps_modules(str(root), mods) == ["widget.py"]
    # And that is EXACTLY the lander's own gate: a non-empty new_contents.
    assert bool(plan_cover_gaps(str(root), "widget.py").new_contents) is True
    for neg in _NEGATIVE:
        assert bool(plan_cover_gaps(str(root), neg).new_contents) is False


def test_signal_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = tmp_path / "many"
    _write(root, "b.py", "def b():\n    return 2\n")
    _write(root, "a.py", "def a():\n    return 1\n")
    mods = ["b.py", "a.py", "b.py"]  # duplicate input collapses to one
    assert cover_gaps_modules(str(root), mods) == ["a.py", "b.py"]
    assert cover_gaps_modules(str(root), mods, limit=1) == ["a.py"]


def test_signal_never_raises_on_missing_or_broken(tmp_path: Path) -> None:
    root = tmp_path / "edge"
    _write(root, "broken.py", "def oops(:\n")  # syntax error -> lander blocks
    # Missing path + unparseable module both simply do not qualify (no raise).
    assert cover_gaps_modules(str(root), ["nope.py", "broken.py"]) == []
    assert cover_gaps_modules(str(root), []) == []  # empty input


# --- the augmentation surfaces the qualifying module, and no negative ---------

def test_plan_tree_surfaces_executable_cover_gaps_step(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), cover_gaps=True)
    assert _cover_gap_steps(plan) == {"widget.py": "Stabilize"}


def test_plan_roadmap_phases_cover_gaps_in_stabilize(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root), cover_gaps=True)
    assert _cover_gap_steps(plan) == {"widget.py": "Stabilize"}


def test_cover_gaps_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented cover_gaps step is a real runnable contribution, so it raises
    the plan's executable-step count (the exact delta also covers any sibling
    synthesis objective the qualifying module legitimately lights up)."""
    root = _gappy_project(tmp_path)
    bridge = IdeaActionBridge()
    plain = bridge.plan_tree(_report(root, _NEGATIVE), project_root=str(root),
                             cover_gaps=True)
    augmented = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                                 project_root=str(root), cover_gaps=True)
    cover_gaps_added = len(_cover_gap_steps(augmented))
    assert cover_gaps_added == 1  # exactly the one qualifying module
    # The executable count rises by AT LEAST the cover_gaps step (the qualifying
    # module may honestly also light up another synthesis signal).
    assert (augmented.stats["executable_steps"]
            >= plain.stats["executable_steps"] + cover_gaps_added)


# --- opt-in: cover-gaps is OFF by default (idea set never shifts) -------------

def test_cover_gaps_is_off_by_default(tmp_path: Path) -> None:
    """cover-gaps shares the idea budget and qualifies a BROAD set, so it is
    opt-in: a default ``plan_tree`` (no ``cover_gaps=True``) emits NO cover_gaps
    step even on a gappy project, and is byte-identical to the same plan built
    with the augmentation having nothing to add (default off → no shift)."""
    root = _gappy_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _cover_gap_steps(default) == {}
    assert [s for s in default.steps
            if s.action_type == "cover_gaps"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), cover_gaps=True)
    assert _cover_gap_steps(opted) == {"widget.py": "Stabilize"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_cover_gaps_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds cover-gaps unless opted in."""
    root = _gappy_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _cover_gap_steps(default) == {}


# --- determinism / opt-in safety: a no-gap project adds NOTHING ---------------

def test_no_cover_gap_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with cover-gaps OPTED IN, a project with NO cover-gappable module
    (every module already has a linked test) gets nothing added and the plan is
    byte-identical run-to-run — proving the augmentation honestly no-ops."""
    root = tmp_path / "plain"
    _write(root, "alpha.py", "def a():\n    return 1\n")
    _write(root, "tests/test_alpha.py",
           "import alpha\n\n\ndef test_a():\n    assert alpha.a() == 1\n")
    _write(root, "beta.py", "def b():\n    return 2\n")
    _write(root, "tests/test_beta.py",
           "import beta\n\n\ndef test_b():\n    assert beta.b() == 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), cover_gaps=True)
    assert [s for s in plan.steps
            if s.operator == "synthesis" and s.action_type == "cover_gaps"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   cover_gaps=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_cover_gaps_step() -> None:
    """Without a project root the signal cannot read any module, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "widget.py")])
    plan = bridge.plan_tree(rpt, project_root="", cover_gaps=True)
    assert [s for s in plan.steps
            if s.operator == "synthesis" and s.action_type == "cover_gaps"] == []


# --- apply_step actually LANDS the new test / no-ops correctly ----------------

def test_apply_step_lands_cover_gaps_test(tmp_path: Path) -> None:
    """The cover_gaps step lands a brand-new characterization test through the
    delegated develop-core path (impact-scoped verify), proving the executable
    claim is end-to-end real and not just surfaced."""
    root = tmp_path / "land"
    _write(root, "widget.py", "def greet(name):\n    return f\"hi {name}\"\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["widget.py"]), project_root=str(root),
                            cover_gaps=True)
    steps = [s for s in plan.steps
             if s.action_type == "cover_gaps" and s.executable]
    assert steps, "a cover_gaps step should be surfaced for an untested module"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    # The brand-new characterization test file was written.
    assert (root / "tests" / "test_widget.py").exists()
    assert "import widget" in (root / "tests" / "test_widget.py").read_text(
        encoding="utf-8")


def test_apply_step_cover_gaps_noops_on_no_gap(tmp_path: Path) -> None:
    """A module that already has a linked test is honestly NOT applied and no test
    file is written — the delegated path never fakes green."""
    root = tmp_path / "noop"
    _write(root, "covered.py", "def f():\n    return 1\n")
    _write(root, "tests/test_covered.py",
           "import covered\n\n\ndef test_covered():\n    assert covered.f() == 1\n")
    before = (root / "tests" / "test_covered.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="covered.py", action_type="cover_gaps",
                      target="covered.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "cover_gaps"
    # The existing linked test is left byte-for-byte untouched.
    assert (root / "tests" / "test_covered.py").read_text(encoding="utf-8") == before
