"""The action plan bridges the develop objective ``modernize`` into
``apex ideate --actions`` as an executable step.

``modernize`` rewrites a module's OWN source with behaviour-preserving idiom
modernizations: ``== None`` / ``!= None`` → ``is`` / ``is not``, dead ``f``
prefixes dropped, and an empty ``dict()`` / ``list()`` / ``tuple()`` constructor
replaced with its literal. It is PER-MODULE (a surfaced step's subject/target is
the module rel-path, exactly like cover-gaps) but, unlike the single-plan
landers, it is OBJECTIVE-COMPILER-driven — a campaign of the objective compiler's
tidy transforms. The grounding layer's :func:`modernize_plan` DELEGATES to those
exact transforms (chaining each over the module's own source), and — like
``cover-gaps`` / ``strengthen-tests`` — ``apply_step`` delegates the step to the
develop-core ``apply_rename`` path (with ``impact_scope=True``). These tests
assert:

  - the grounding signal ``modernizable_modules`` equals modernize's OWN gate (a
    non-empty ``modernize_plan(...).new_contents``): a module carrying a stale
    idiom qualifies; an ALREADY-MODERN module (every idiom already in its tidy
    form), an unreadable / unparseable module, and a missing path do NOT (honesty
    / no over-promise);
  - the signal is the union over the compiler's transforms: a module with several
    distinct idioms qualifies, and the landed plan modernizes ALL of them at once;
  - the augmentation emits an executable ``modernize`` step (in the Refine phase)
    for the qualifying module and NONE for the negatives;
  - modernize is OPT-IN (default off): a default plan emits NO modernize step and
    is byte-identical run-to-run (idea set never shifts);
  - the opt-in flags are INDEPENDENT: opting modernize in does NOT enable
    cover-gaps / wire-exports / generate-usage-doc / tdd-implement /
    strengthen-tests;
  - a project with NO modernizable module is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real idiom rewrite through the delegated
    develop-core path (impact-scoped verify keeps a tested module green), and
    honestly no-ops (writing nothing) when the module is already modern — never a
    fake-green.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import modernizable_modules, modernize_plan
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that puts ``subject`` (a ``.py`` path) into the plan as a
    candidate target for the synthesis augmentation. The modernize signal lights up
    a module only when its path is among these candidates, so the module under test
    must be surfaced. Descending values keep a stable order."""
    return IdeaNode(
        id=str(i), title=f"Develop {subject}", subject=subject,
        branch_path=f"x.{i}", operator="root",
        source_facts=[f"dependency-hub: {subject}"], value=1.0 - i * 0.01,
    )


def _report(root: Path, modules: list[str]) -> IdeaTreeReport:
    ideas = [_idea(i, m) for i, m in enumerate(modules)]
    return IdeaTreeReport(objective="dev", project_root=str(root), ideas=ideas)


# The qualifying module Apex CAN modernize: ``m.py`` carries a stale ``== None``
# comparison AND an empty ``dict()`` constructor — both idioms the compiler's tidy
# transforms rewrite. The negatives are an ALREADY-MODERN module (its comparison is
# ``is None`` and it returns a ``{}`` literal, so no transform changes it) and a
# packaging dunder that holds nothing to modernize.
_QUALIFYING = ["m.py"]
_NEGATIVE = ["clean.py", "__init__.py"]


def _idiom_project(tmp_path: Path) -> Path:
    """ONE modernizable module + the honesty-negatives modernize leaves untouched."""
    root = tmp_path / "proj"
    # m.classify: ``x == None`` -> ``x is None`` AND ``dict()`` -> ``{}`` (two idioms).
    _write(root, "m.py",
           'def classify(x):\n    if x == None:\n        return dict()\n'
           '    return {"v": x}\n')
    # clean.py is already in its idiomatic form: ``is None`` + a ``{}`` literal, so
    # every tidy transform is a no-op -> the lander lands nothing.
    _write(root, "clean.py",
           'def g(x):\n    if x is None:\n        return {}\n    return x\n')
    # A dunder package marker holds no modernizable idiom -> empty no-op plan.
    _write(root, "__init__.py", "X = 1\n")
    return root


def _modernize_steps(plan) -> dict[str, str]:
    """{module_target: phase} for the executable modernize steps in a plan."""
    return {
        s.target: s.phase
        for s in plan.steps
        if (s.operator == "synthesis"
            and s.action_type == "modernize" and s.executable)
    }


# --- the grounding signal equals modernize's own gate (honesty) ---------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _idiom_project(tmp_path)
    mods = _QUALIFYING + _NEGATIVE
    # The signal lights up ONLY the module carrying a stale idiom...
    assert modernizable_modules(str(root), mods) == ["m.py"]
    # ...and that is EXACTLY modernize's OWN gate: a non-empty plan new_contents.
    assert bool(modernize_plan(str(root), "m.py").new_contents) is True
    for neg in _NEGATIVE:
        assert bool(modernize_plan(str(root), neg).new_contents) is False


def test_signal_refuses_already_modern_module(tmp_path: Path) -> None:
    """A module whose idioms are ALREADY tidy has nothing for the compiler's
    transforms to rewrite, so the delegated plan is empty — the signal equals
    exactly modernize's own gate, never an over-promise on idiomatic code."""
    root = _idiom_project(tmp_path)
    # Modernize m.py first, making it fully idiomatic.
    plan = modernize_plan(str(root), "m.py")
    for rel, text in plan.new_contents.items():
        _write(root, rel, text)
    # Now no transform changes it -> the lander refuses (empty plan)...
    assert modernize_plan(str(root), "m.py").new_contents == {}
    # ...so the signal drops it (honesty: an already-modern module is not surfaced).
    assert modernizable_modules(str(root), ["m.py"]) == []


def test_signal_is_union_over_transforms(tmp_path: Path) -> None:
    """The signal/plan is the UNION of the compiler's tidy transforms: a module with
    several distinct idioms qualifies, and the landed plan modernizes ALL of them at
    once (delegating to the real transforms, never copying their logic)."""
    root = tmp_path / "multi"
    # Three distinct idioms in one module: ``!= None``, a dead ``f`` prefix, and an
    # empty ``list()`` constructor.
    _write(root, "multi.py",
           'def f(x):\n    if x != None:\n        msg = f"static"\n'
           '        return msg, list()\n    return None\n')
    assert modernizable_modules(str(root), ["multi.py"]) == ["multi.py"]
    new = modernize_plan(str(root), "multi.py").new_contents["multi.py"]
    assert "is not None" in new       # the comparison was modernized
    assert 'f"static"' not in new     # the dead f-prefix was dropped
    assert "list()" not in new and "[]" in new  # the empty constructor → literal


def test_signal_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = tmp_path / "many"
    # Two independent modernizable modules (each a stale ``== None`` comparison).
    _write(root, "bb.py", "def s(x):\n    return x == None\n")
    _write(root, "aa.py", "def g(x):\n    return x == None\n")
    mods = ["bb.py", "aa.py", "bb.py"]  # duplicate input collapses, order normalised
    assert modernizable_modules(str(root), mods) == ["aa.py", "bb.py"]
    assert modernizable_modules(str(root), mods, limit=1) == ["aa.py"]


def test_signal_never_raises_on_missing_or_broken(tmp_path: Path) -> None:
    root = tmp_path / "edge"
    _write(root, "broken.py", "def oops(:\n")  # syntax error -> transforms return None
    # Missing path + unparseable module both simply do not qualify (no raise).
    assert modernizable_modules(str(root), ["nope.py", "broken.py"]) == []
    assert modernizable_modules(str(root), []) == []  # empty candidate input


# --- the augmentation surfaces the qualifying module, and no negative ---------

def test_plan_tree_surfaces_executable_modernize_step(tmp_path: Path) -> None:
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), modernize=True)
    assert _modernize_steps(plan) == {"m.py": "Refine"}


def test_plan_roadmap_phases_modernize_in_refine(tmp_path: Path) -> None:
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root), modernize=True)
    assert _modernize_steps(plan) == {"m.py": "Refine"}


def test_modernize_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented modernize step is a real runnable contribution, so it raises the
    plan's executable-step count by exactly the one qualifying module.

    The baseline is the SAME report with modernize OFF (so the only delta is the
    augmented synthesis step itself, not a different idea set)."""
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    plain = bridge.plan_tree(rpt, project_root=str(root))  # modernize off
    augmented = bridge.plan_tree(rpt, project_root=str(root), modernize=True)
    added = len(_modernize_steps(augmented))
    assert added == 1  # exactly the one modernizable module
    assert (augmented.stats["executable_steps"]
            == plain.stats["executable_steps"] + added)


# --- opt-in: modernize is OFF by default (idea set never shifts) --------------

def test_modernize_is_off_by_default(tmp_path: Path) -> None:
    """modernize targets modules broadly, so it is opt-in: a default ``plan_tree``
    (no ``modernize=True``) emits NO modernize step even on a modernizable project,
    and is byte-identical run-to-run."""
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _modernize_steps(default) == {}
    assert [s for s in default.steps if s.action_type == "modernize"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), modernize=True)
    assert _modernize_steps(opted) == {"m.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_modernize_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds modernize unless opted in."""
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _modernize_steps(default) == {}


def test_opt_in_flags_are_independent(tmp_path: Path) -> None:
    """The broad opt-in objectives are INDEPENDENT flags: opting modernize in must
    NOT enable cover-gaps / wire-exports / generate-usage-doc / tdd-implement /
    strengthen-tests."""
    root = _idiom_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), modernize=True)
    assert [s for s in plan.steps if s.action_type == "cover_gaps"] == []
    assert [s for s in plan.steps if s.action_type == "wire_exports"] == []
    assert [s for s in plan.steps if s.action_type == "generate_usage_doc"] == []
    assert [s for s in plan.steps if s.action_type == "tdd_implement"] == []
    assert [s for s in plan.steps if s.action_type == "strengthen_tests"] == []
    assert _modernize_steps(plan) == {"m.py": "Refine"}


def test_enabling_one_flag_adds_only_its_objective() -> None:
    """``_enabled_objectives`` adds EXACTLY the opted-in objective: the modernize
    flag appends ``modernize`` and no other opt-in objective, and with every flag
    off it is the default tuple unchanged."""
    base = IdeaActionBridge._SYNTHESIS_OBJECTIVES
    assert IdeaActionBridge._enabled_objectives(
        False, False, False, False, False) == base
    only_mod = IdeaActionBridge._enabled_objectives(
        False, False, False, False, False, modernize=True)
    added = [row for row in only_mod if row not in base]
    assert [r[1] for r in added] == ["modernize"]


# --- determinism / opt-in safety: an already-modern project adds NOTHING ------

def test_no_modernizable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with modernize OPTED IN, a project whose modules are already idiomatic
    gets nothing added and the plan is byte-identical run-to-run — proving the
    augmentation honestly no-ops."""
    root = tmp_path / "modern"
    # Already-idiomatic modules: ``is None`` comparisons, ``{}`` / ``[]`` literals.
    _write(root, "alpha.py",
           "def a(x):\n    return {} if x is None else {'v': x}\n")
    _write(root, "beta.py",
           "def b(x):\n    return [] if x is None else [x]\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), modernize=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "modernize"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   modernize=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_modernize_step() -> None:
    """Without a project root the signal cannot read any module, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "m.py")])
    plan = bridge.plan_tree(rpt, project_root="", modernize=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "modernize"] == []


# --- apply_step actually LANDS the modernization / no-ops honestly ------------

def test_apply_step_lands_modernization(tmp_path: Path) -> None:
    """The modernize step lands the real idiom rewrite through the delegated
    develop-core path (impact-scoped verify), proving the executable claim is
    end-to-end real and not just surfaced — and the impacted test stays GREEN
    (the rewrite is behaviour-preserving)."""
    root = tmp_path / "land"
    _write(root, "m.py",
           'def classify(x):\n    if x == None:\n        return dict()\n'
           '    return {"v": x}\n')
    _write(root, "tests/test_m.py",
           "import m\n\n\ndef test_none():\n    assert m.classify(None) == {}\n\n\n"
           'def test_val():\n    assert m.classify(3) == {"v": 3}\n')
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["m.py"]),
                            project_root=str(root), modernize=True)
    steps = [s for s in plan.steps
             if s.action_type == "modernize" and s.executable]
    assert steps, "a modernize step should be surfaced for the stale-idiom module"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "modernize"
    assert out.get("suite_green") is True  # behaviour-preserving -> still passes
    # Both stale idioms were modernized in the one landed change.
    landed = (root / "m.py").read_text(encoding="utf-8")
    assert "if x is None:" in landed   # == None -> is None
    assert "return {}" in landed       # dict() -> {}
    assert "== None" not in landed and "dict()" not in landed


def test_apply_step_modernize_noops_on_modern_module(tmp_path: Path) -> None:
    """A module whose idioms are already tidy is honestly NOT applied and its source
    is left untouched — the delegated path never fakes green."""
    root = tmp_path / "noop"
    _write(root, "settled.py",
           "def g(x):\n    if x is None:\n        return {}\n    return x\n")
    before = (root / "settled.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="settled.py", action_type="modernize",
                      target="settled.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "modernize"
    # The source is left byte-for-byte untouched — nothing was fabricated.
    assert (root / "settled.py").read_text(encoding="utf-8") == before
