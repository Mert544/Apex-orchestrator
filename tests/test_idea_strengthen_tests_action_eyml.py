"""The action plan bridges the develop objective ``strengthen-tests`` into
``apex ideate --actions`` as an executable step.

strengthen-tests HARDENS an existing-but-thin test: for a module whose tests miss
a surviving mutant, it deterministically appends a DOUBLE-GATED assertion (one
that PASSES on the real code AND FAILS against the specific surviving mutant it
kills) to that module's ``tests/test_<stem>.py`` — landing real new test code only
when the gate verifies it. It is PER-MODULE (a surfaced step's subject/target is
the module rel-path, exactly like cover-gaps) and, like ``cover-gaps`` /
``implement-stub``, it is NOT a SemanticPatchResult transform — ``apply_step``
delegates it to the develop-core ``apply_rename`` path (with ``impact_scope=True``).
These tests assert:

  - the grounding signal ``strengthenable_modules`` equals the lander's OWN gate (a
    non-empty ``plan_strengthen_tests(...).new_contents``): a module with a
    surviving mutant a double-gated assertion can kill qualifies; a SATURATED module
    (its tests already kill every mutant), a module whose survivor no honest literal
    oracle can kill, and a test/fixture or dunder target do NOT (honesty / no
    over-promise);
  - the augmentation emits an executable ``strengthen_tests`` step (in the Stabilize
    phase) for the qualifying module and NONE for the negatives;
  - strengthen-tests is OPT-IN (default off): a default plan emits NO
    strengthen_tests step and is byte-identical run-to-run (idea set never shifts);
  - the opt-in flags are INDEPENDENT: opting strengthen-tests in does NOT enable
    cover-gaps / wire-exports / generate-usage-doc / tdd-implement;
  - a project with NO strengthenable module is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real mutant-killing assertion through the
    delegated develop-core path (impact-scoped verify), and honestly no-ops
    (writing nothing) when the module is saturated — never a fake-green.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import strengthenable_modules
from app.execution.strengthen_tests import plan_strengthen_tests
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that puts ``subject`` (a ``.py`` path) into the plan as a
    candidate target for the synthesis augmentation. The strengthen-tests signal
    lights up a module only when its path is among these candidates, so the module
    under test must be surfaced. Descending values keep a stable order."""
    return IdeaNode(
        id=str(i), title=f"Develop {subject}", subject=subject,
        branch_path=f"x.{i}", operator="root",
        # W98: the carrier fact is `coordinator` (proven-permanently
        # recommend-only), NOT `dependency-hub` — that row now routes to the
        # executable cover_gaps lander, which would collide with the augmented
        # step on the dedupe key and trigger the plan-time cover-gaps probe on
        # these fixtures. The carrier only needs to surface the .py candidate.
        source_facts=[f"coordinator: {subject}"], value=1.0 - i * 0.01,
    )


def _report(root: Path, modules: list[str]) -> IdeaTreeReport:
    ideas = [_idea(i, m) for i, m in enumerate(modules)]
    return IdeaTreeReport(objective="dev", project_root=str(root), ideas=ideas)


# The qualifying module Apex CAN strengthen: ``m.classify`` has an ``n < 0``
# boundary the only test (the ``pos`` branch) leaves uncaught — a surviving mutant
# the lander pins with a double-gated assertion. The negatives are an UNKILLABLE
# module (``u.pick`` returns a non-literal ``Box()`` on either branch, so its real
# survivor has no reproducible oracle) and a packaging dunder.
_QUALIFYING = ["m.py"]
_NEGATIVE = ["u.py", "__init__.py"]


def _thin_project(tmp_path: Path) -> Path:
    """ONE strengthenable module + the honesty-negatives the lander refuses. The
    mutation baseline is run PER MODULE in an isolated copy, so the negatives can
    co-locate here without interfering."""
    root = tmp_path / "proj"
    # m.classify: the ``n < 0`` boundary survives (only the pos branch is tested) ->
    # strengthen-tests appends a boundary-pinning double-gated assertion.
    _write(root, "m.py", 'def classify(n):\n    return "neg" if n < 0 else "pos"\n')
    _write(root, "tests/test_m.py",
           "import m\n\n\ndef test_pos():\n    assert m.classify(5) == \"pos\"\n")
    # u.pick returns a Box() on either branch: its ``n < 0`` mutant survives, but a
    # real object is not a reproducible literal oracle -> the lander lands nothing.
    _write(root, "u.py",
           "class Box:\n    pass\n\n\n"
           "def pick(n):\n    if n < 0:\n        return Box()\n    return Box()\n")
    _write(root, "tests/test_u.py",
           "import u\n\n\ndef test_runs():\n    assert isinstance(u.pick(5), u.Box)\n")
    # A dunder package marker is not a testable behaviour unit -> empty no-op plan.
    _write(root, "__init__.py", "X = 1\n")
    return root


def _strengthen_steps(plan) -> dict[str, str]:
    """{module_target: phase} for the executable strengthen_tests steps in a plan."""
    return {
        s.target: s.phase
        for s in plan.steps
        if (s.operator == "synthesis"
            and s.action_type == "strengthen_tests" and s.executable)
    }


# --- the grounding signal equals the lander's own gate (honesty) --------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _thin_project(tmp_path)
    mods = _QUALIFYING + _NEGATIVE
    # The signal lights up ONLY the module with a killable surviving mutant...
    assert strengthenable_modules(str(root), mods) == ["m.py"]
    # ...and that is EXACTLY the lander's OWN gate: a non-empty new_contents.
    assert bool(plan_strengthen_tests(str(root), "m.py").new_contents) is True
    for neg in _NEGATIVE:
        assert bool(plan_strengthen_tests(str(root), neg).new_contents) is False


def test_signal_refuses_saturated_module(tmp_path: Path) -> None:
    """A module whose tests ALREADY kill every mutant has no survivor to pin, so
    the lander lands nothing — the signal equals exactly the lander's own gate
    (a non-empty plan), never an over-promise on an already-strong test."""
    root = _thin_project(tmp_path)
    # Land the killing assertion first, making m.py saturated.
    plan = plan_strengthen_tests(str(root), "m.py")
    for rel, text in plan.new_contents.items():
        _write(root, rel, text)
    # Now there is no surviving mutant left -> the lander refuses (empty plan)...
    assert plan_strengthen_tests(str(root), "m.py").new_contents == {}
    # ...so the signal drops it (honesty: a saturated module is not surfaced).
    assert strengthenable_modules(str(root), ["m.py"]) == []


def test_signal_refuses_unkillable_survivor(tmp_path: Path) -> None:
    """A module that genuinely HAS a surviving mutant but whose function returns a
    non-literal (no reproducible oracle) is DETECTED-but-refused: the lander lands
    nothing, so the signal drops it (it equals the lander's own gate)."""
    root = _thin_project(tmp_path)
    # u.pick has a real survivor but no honest literal oracle -> empty plan.
    assert plan_strengthen_tests(str(root), "u.py").new_contents == {}
    assert strengthenable_modules(str(root), ["u.py"]) == []


def test_signal_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = tmp_path / "many"
    # Two independent strengthenable modules (each a thin boundary test).
    _write(root, "bb.py", 'def s(n):\n    return "neg" if n < 0 else "pos"\n')
    _write(root, "tests/test_bb.py",
           "import bb\n\n\ndef test_pos():\n    assert bb.s(5) == \"pos\"\n")
    _write(root, "aa.py", 'def g(n):\n    return "lo" if n < 0 else "hi"\n')
    _write(root, "tests/test_aa.py",
           "import aa\n\n\ndef test_hi():\n    assert aa.g(5) == \"hi\"\n")
    mods = ["bb.py", "aa.py", "bb.py"]  # duplicate input collapses, order normalised
    assert strengthenable_modules(str(root), mods) == ["aa.py", "bb.py"]
    assert strengthenable_modules(str(root), mods, limit=1) == ["aa.py"]


def test_signal_never_raises_on_missing_or_broken(tmp_path: Path) -> None:
    root = tmp_path / "edge"
    _write(root, "broken.py", "def oops(:\n")  # syntax error -> lander blocks
    # Missing path + unparseable module both simply do not qualify (no raise).
    assert strengthenable_modules(str(root), ["nope.py", "broken.py"]) == []
    assert strengthenable_modules(str(root), []) == []  # empty candidate input


# --- the augmentation surfaces the qualifying module, and no negative ---------

def test_plan_tree_surfaces_executable_strengthen_step(tmp_path: Path) -> None:
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), strengthen_tests=True)
    assert _strengthen_steps(plan) == {"m.py": "Stabilize"}


def test_plan_roadmap_phases_strengthen_in_stabilize(tmp_path: Path) -> None:
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root), strengthen_tests=True)
    assert _strengthen_steps(plan) == {"m.py": "Stabilize"}


def test_strengthen_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented strengthen_tests step is a real runnable contribution, so it
    raises the plan's executable-step count by exactly the one qualifying module.

    The baseline is the SAME report with strengthen-tests OFF (so the only delta is
    the augmented synthesis step itself, not a different idea set)."""
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    plain = bridge.plan_tree(rpt, project_root=str(root))  # strengthen off
    augmented = bridge.plan_tree(rpt, project_root=str(root), strengthen_tests=True)
    added = len(_strengthen_steps(augmented))
    assert added == 1  # exactly the one strengthenable module
    assert (augmented.stats["executable_steps"]
            == plain.stats["executable_steps"] + added)


# --- opt-in: strengthen-tests is OFF by default (idea set never shifts) --------

def test_strengthen_is_off_by_default(tmp_path: Path) -> None:
    """strengthen-tests runs the mutation engine per candidate and targets modules
    broadly, so it is opt-in: a default ``plan_tree`` (no ``strengthen_tests=True``)
    emits NO strengthen_tests step even on a strengthenable project, and is
    byte-identical run-to-run."""
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _strengthen_steps(default) == {}
    assert [s for s in default.steps if s.action_type == "strengthen_tests"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), strengthen_tests=True)
    assert _strengthen_steps(opted) == {"m.py": "Stabilize"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_strengthen_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds strengthen-tests unless opted in."""
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _strengthen_steps(default) == {}


def test_opt_in_flags_are_independent(tmp_path: Path) -> None:
    """The broad opt-in objectives are INDEPENDENT flags: opting strengthen-tests
    in must NOT enable cover-gaps / wire-exports / generate-usage-doc /
    tdd-implement."""
    root = _thin_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), strengthen_tests=True)
    assert [s for s in plan.steps if s.action_type == "cover_gaps"] == []
    assert [s for s in plan.steps if s.action_type == "wire_exports"] == []
    assert [s for s in plan.steps if s.action_type == "generate_usage_doc"] == []
    assert [s for s in plan.steps if s.action_type == "tdd_implement"] == []
    assert _strengthen_steps(plan) == {"m.py": "Stabilize"}


def test_enabling_one_flag_adds_only_its_objective() -> None:
    """``_enabled_objectives`` adds EXACTLY the opted-in objective: the
    strengthen-tests flag appends ``strengthen_tests`` and no other opt-in
    objective, and with every flag off it is the default tuple unchanged."""
    base = IdeaActionBridge._SYNTHESIS_OBJECTIVES
    assert IdeaActionBridge._enabled_objectives(
        False, False, False, False, False) == base
    only_str = IdeaActionBridge._enabled_objectives(
        False, False, False, False, strengthen_tests=True)
    added = [row for row in only_str if row not in base]
    assert [r[1] for r in added] == ["strengthen_tests"]


# --- determinism / opt-in safety: a no-survivor project adds NOTHING ----------

def test_no_strengthenable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with strengthen-tests OPTED IN, a project whose modules are already
    saturated (every mutant killed) gets nothing added and the plan is
    byte-identical run-to-run — proving the augmentation honestly no-ops."""
    root = tmp_path / "saturated"
    # A constant function has no surviving boundary mutant; its test pins it fully.
    _write(root, "alpha.py", "def a():\n    return 1\n")
    _write(root, "tests/test_alpha.py",
           "import alpha\n\n\ndef test_a():\n    assert alpha.a() == 1\n")
    _write(root, "beta.py", "def b():\n    return 2\n")
    _write(root, "tests/test_beta.py",
           "import beta\n\n\ndef test_b():\n    assert beta.b() == 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), strengthen_tests=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "strengthen_tests"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   strengthen_tests=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_strengthen_step() -> None:
    """Without a project root the signal cannot run the mutation engine, so nothing
    is added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "m.py")])
    plan = bridge.plan_tree(rpt, project_root="", strengthen_tests=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "strengthen_tests"] == []


# --- apply_step actually LANDS the assertion / no-ops honestly ----------------

def test_apply_step_lands_strengthen_assertion(tmp_path: Path) -> None:
    """The strengthen_tests step lands the real mutant-killing assertion through the
    delegated develop-core path (impact-scoped verify), proving the executable claim
    is end-to-end real and not just surfaced — and the suite stays GREEN."""
    root = tmp_path / "land"
    _write(root, "m.py", 'def classify(n):\n    return "neg" if n < 0 else "pos"\n')
    _write(root, "tests/test_m.py",
           "import m\n\n\ndef test_pos():\n    assert m.classify(5) == \"pos\"\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["m.py"]),
                            project_root=str(root), strengthen_tests=True)
    steps = [s for s in plan.steps
             if s.action_type == "strengthen_tests" and s.executable]
    assert steps, "a strengthen_tests step should be surfaced for the thin module"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "strengthen_tests"
    assert out.get("suite_green") is True  # the extended suite still passes
    # The mutant-killing assertion lands in Apex's OWN file at a collision-proof
    # unique basename (it calls the function across the boundary the old test
    # missed); the project's idiomatic ``tests/test_m.py`` is left untouched.
    original_thin = (root / "tests" / "test_m.py").read_text(encoding="utf-8")
    landed = (root / "tests" / "test_m_apex_mutants.py").read_text(encoding="utf-8")
    assert "def test_m_kills_surviving_mutants():" in landed
    assert "_apex_fn_classify(" in landed
    assert "def test_pos():" in original_thin  # the original test is preserved


def test_apply_step_strengthen_noops_on_saturated_module(tmp_path: Path) -> None:
    """A module whose tests already kill every mutant (saturated) is honestly NOT
    applied and its test file is left untouched — the delegated path never fakes
    green."""
    root = tmp_path / "noop"
    # A constant function has no surviving mutant to kill; its test is saturated.
    _write(root, "settled.py", "def k():\n    return 7\n")
    _write(root, "tests/test_settled.py",
           "import settled\n\n\ndef test_k():\n    assert settled.k() == 7\n")
    before = (root / "tests" / "test_settled.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="settled.py", action_type="strengthen_tests",
                      target="settled.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "strengthen_tests"
    # The existing test is left byte-for-byte untouched — nothing was fabricated.
    assert (root / "tests" / "test_settled.py").read_text(encoding="utf-8") == before
