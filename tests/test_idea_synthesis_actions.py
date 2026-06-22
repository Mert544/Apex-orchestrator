"""The action plan surfaces the three develop-grade synthesis objectives.

``apex ideate --actions`` planned only test/design/harden/imports/CI steps; this
wave closes the gap so the plan ALSO surfaces the three synthesis changes the
develop core can already land — ``implement-stub``, ``infer-type-hints``,
``dataclassify`` — as genuinely-executable steps, grounded on each lander's own
predicate so the executable claim is never a fake-green.

These assert: the augmentation emits an executable synthesis step for each
QUALIFYING module and NOT for the honesty-negative ones (ambiguous-only stub,
fully-typed module, real-``__init__`` class); a synthesis-free project's plan is
byte-identical to before the augmentation (determinism / opt-in safety); and
``apply_plan`` actually LANDS the pure-transform changes (kept on green) while a
non-synthesizable target no-ops without writing.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that surfaces ``subject`` as a (recommend-only) design task —
    enough to put the module's ``.py`` path into the plan as a candidate target
    for the synthesis augmentation. Descending values keep a stable order."""
    return IdeaNode(
        id=str(i), title=f"Develop {subject}", subject=subject,
        branch_path=f"x.{i}", operator="root",
        source_facts=[f"dependency-hub: {subject}"], value=1.0 - i * 0.01,
    )


def _report(root: Path, modules: list[str]) -> IdeaTreeReport:
    ideas = [_idea(i, m) for i, m in enumerate(modules)]
    return IdeaTreeReport(objective="dev", project_root=str(root), ideas=ideas)


# A project with exactly one module per synthesis signal, plus the matching
# honesty-negative module for each (the lander would REFUSE these).
_QUALIFYING = ["labels.py", "shape.py", "calc.py"]
_NEGATIVE = ["passthru.py", "done.py", "amb.py"]


def _mixed_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    # inferable-return (f-string ⇒ str) and its negatives.
    _write(root, "labels.py", "def label(name):\n    return f\"item-{name}\"\n")
    _write(root, "passthru.py", "def echo(x):\n    return x\n")  # unprovable return
    _write(root, "done.py",
           "def label(name) -> str:\n    return f\"x-{name}\"\n")  # fully typed
    # dataclassifiable boilerplate class.
    _write(root, "shape.py",
           "class Point:\n"
           "    def __init__(self, x: int, y: int) -> None:\n"
           "        self.x = x\n"
           "        self.y = y\n")
    # fillable stub (pinned by two witnesses) and an ambiguous-only stub.
    _write(root, "calc.py", "def total(xs) -> int:\n    ...\n")
    _write(root, "tests/test_calc.py",
           "from calc import total\n\n\n"
           "def test_total():\n"
           "    assert total([1, 2, 3]) == 6\n"
           "    assert total([10, 20]) == 30\n")
    # Ambiguous stub: pinned by a SINGLE witness ⇒ implement-stub REFUSES it.
    # The ``-> int`` header keeps it out of the inferable-return signal too (its
    # return is already annotated), so it is a pure honesty-negative — no
    # synthesis step of any kind should be surfaced for it.
    _write(root, "amb.py", "def double(n) -> int:\n    ...\n")
    _write(root, "tests/test_amb.py",
           "from amb import double\n\n\n"
           "def test_double():\n    assert double(3) == 6\n")  # single witness
    return root


def _synthesis_steps(plan) -> dict[str, str]:
    """{module_target: action_type} for the executable synthesis steps in a plan."""
    return {
        s.target: s.action_type
        for s in plan.steps
        if s.operator == "synthesis" and s.executable
    }


# --- the augmentation surfaces each qualifying module, and no negative ---------

def test_plan_tree_surfaces_executable_synthesis_steps(tmp_path: Path) -> None:
    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root))
    syn = _synthesis_steps(plan)
    assert syn == {
        "labels.py": "infer_type_hints",
        "shape.py": "dataclassify",
        "calc.py": "implement_stub",
    }
    # None of the honesty-negative modules gets a synthesis step (no over-promise).
    for neg in _NEGATIVE:
        assert neg not in syn


def test_plan_roadmap_phases_synthesis_steps(tmp_path: Path) -> None:
    """The roadmap planner surfaces the same steps, phased: implement-stub builds
    new code (Evolve); the two pure refactors are Refine."""
    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root))
    by_target = {
        s.target: (s.action_type, s.phase)
        for s in plan.steps if s.operator == "synthesis" and s.executable
    }
    assert by_target == {
        "labels.py": ("infer_type_hints", "Refine"),
        "shape.py": ("dataclassify", "Refine"),
        "calc.py": ("implement_stub", "Evolve"),
    }


def test_synthesis_steps_count_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented executable steps are reflected in the plan stats — they are
    real runnable contributions, not invisible extras."""
    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    plain = bridge.plan_tree(_report(root, _NEGATIVE), project_root=str(root))
    augmented = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                                 project_root=str(root))
    # Three qualifying modules add three executable steps over the no-synthesis set.
    assert (augmented.stats["executable_steps"]
            == plain.stats["executable_steps"] + 3)


# --- determinism / opt-in safety ----------------------------------------------

def test_synthesis_free_project_plan_is_byte_identical(tmp_path: Path) -> None:
    """On a project with NO synthesis-eligible module, the augmentation adds
    nothing — the plan is byte-identical to a plan built with the augmentation
    short-circuited (no candidates), proving existing idea sets never shift."""
    root = tmp_path / "plain"
    _write(root, "plain.py", "x = 1\n")  # nothing any signal qualifies
    _write(root, "also.py", "y = 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["plain.py", "also.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root))
    assert [s for s in plan.steps if s.operator == "synthesis"] == []
    # And the bytes are stable run-to-run (no time/random).
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_augmentation_is_deterministic_on_qualifying_project(tmp_path: Path) -> None:
    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    first = json.dumps(
        [s.model_dump() for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    for _ in range(3):
        again = json.dumps(
            [s.model_dump()
             for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
            sort_keys=True,
        )
        assert again == first


def test_no_project_root_adds_no_synthesis_steps(tmp_path: Path) -> None:
    """Without a project root the signals cannot read any module, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "calc.py")])
    plan = bridge.plan_tree(rpt, project_root="")
    assert [s for s in plan.steps if s.operator == "synthesis"] == []


def test_augmentation_skips_when_step_already_present(tmp_path: Path) -> None:
    """If a synthesis (target, action_type) is somehow already in the steps, the
    augmentation does not duplicate it (the de-dup key is honoured)."""
    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root))
    keys = [(s.target, s.action_type) for s in plan.steps if s.operator == "synthesis"]
    assert len(keys) == len(set(keys))  # no duplicate (target, action) pair


# --- apply_plan actually LANDS the pure-transform changes / no-ops correctly ---

def test_apply_plan_lands_pure_transform_changes(tmp_path: Path) -> None:
    """``apply_plan`` lands the augmented pure-transform synthesis steps and KEEPS
    them when the suite stays green (full snapshot → write → verify → keep)."""
    root = tmp_path / "land"
    _write(root, "labels.py", "def label(name):\n    return f\"item-{name}\"\n")
    _write(root, "shape.py",
           "class Point:\n"
           "    def __init__(self, x: int, y: int) -> None:\n"
           "        self.x = x\n"
           "        self.y = y\n")
    _write(root, "tests/test_ok.py", "def test_ok():\n    assert True\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["labels.py", "shape.py"]),
                            project_root=str(root))
    summary = bridge.apply_plan(plan, str(root), mode="autonomous", verify=True)
    assert summary["applied"] >= 2
    assert summary["rolled_back"] == 0
    # The real changes landed and were kept.
    assert "-> str:" in (root / "labels.py").read_text(encoding="utf-8")
    assert "@dataclass" in (root / "shape.py").read_text(encoding="utf-8")


def test_apply_plan_lands_implement_stub(tmp_path: Path) -> None:
    """The implement-stub step lands a synthesised body through the delegated
    develop-core path (impact-scoped verify), proving the executable claim is
    end-to-end real and not just surfaced."""
    root = tmp_path / "stub"
    _write(root, "calc.py", "def total(xs) -> int:\n    ...\n")
    _write(root, "tests/test_calc.py",
           "from calc import total\n\n\n"
           "def test_total():\n"
           "    assert total([1, 2, 3]) == 6\n"
           "    assert total([10, 20]) == 30\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["calc.py"]), project_root=str(root))
    stub_steps = [s for s in plan.steps
                  if s.action_type == "implement_stub" and s.executable]
    assert stub_steps, "implement-stub step should be surfaced for a fillable stub"
    summary = bridge.apply_plan(plan, str(root), mode="autonomous", verify=True)
    assert summary["applied"] >= 1
    body = (root / "calc.py").read_text(encoding="utf-8")
    assert "..." not in body  # the stub body was filled
    assert "return" in body


def test_apply_step_implement_stub_noops_on_non_synthesizable(tmp_path: Path) -> None:
    """A non-synthesizable stub (no pinned test) is honestly NOT applied and the
    file is left byte-for-byte untouched — the delegated path never fakes green."""
    root = tmp_path / "noop"
    src = "def f(x):\n    ...\n"
    _write(root, "lonely.py", src)
    from app.models.idea import ActionStep
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="lonely.py", action_type="implement_stub",
                      target="lonely.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "implement_stub"
    assert (root / "lonely.py").read_text(encoding="utf-8") == src


def test_render_action_markdown_includes_synthesis_steps(tmp_path: Path) -> None:
    """The standalone synthesis steps render as runnable rows in the action
    markdown (proving ``render_action_markdown`` handles them)."""
    from app.engine.idea_action_bridge import render_action_markdown

    root = _mixed_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING), project_root=str(root))
    md = render_action_markdown(plan)
    assert "implement_stub" in md
    assert "infer_type_hints" in md
    assert "dataclassify" in md
    assert "▶ runnable" in md
