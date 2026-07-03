"""The action plan bridges the develop objective ``tdd-implement`` into
``apex ideate --actions`` as an executable step.

tdd-implement is the everyday TDD inner loop a budget-limited student/team
otherwise pays an LLM for, message by message: "I wrote the test — now write the
code." Given a FAILING test that calls a function that does NOT EXIST YET, it
deterministically synthesises a real ``def foo`` in the correct module so the RED
test goes GREEN — landing working code only when the gate verifies it. It is the
one PER-SYMBOL synthesis objective: a surfaced step's subject/target is
``"<module_rel>:<name>"`` for ONE missing function. Like ``implement-stub`` it is
NOT a SemanticPatchResult transform — ``apply_step`` delegates it to the
develop-core ``apply_rename`` path (with ``impact_scope=True``). These tests
assert:

  - the grounding signal ``tdd_implementable_symbols`` equals the lander's OWN
    gate (the objective's ``_missing`` spine: ``detect_missing_symbols`` whose
    ``plan_tdd_implement(...).new_contents`` is non-empty): a symbol the lander can
    synthesise a passing function for qualifies; a fully-tested symbol, an
    assertion failure on EXISTING code (not a missing symbol), and a symbol whose
    single example no fixed template can prove do NOT (honesty / no over-promise);
  - the augmentation emits an executable ``tdd_implement`` step (in the Evolve
    phase) for the qualifying symbol and NONE for the negatives;
  - tdd-implement is OPT-IN (default off): a default plan emits NO tdd_implement
    step and is byte-identical run-to-run (idea set never shifts);
  - the opt-in flags are INDEPENDENT: opting tdd-implement in does NOT enable
    cover-gaps / wire-exports / generate-usage-doc;
  - a project with NO implementable missing symbol is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real synthesised function through the
    delegated develop-core path (impact-scoped verify), and honestly no-ops
    (writing nothing) when there is no missing symbol — never a fake-green.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import tdd_implementable_symbols
from app.execution.objectives.tdd_implement import (
    detect_missing_symbols,
    plan_tdd_implement,
)
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea that puts ``subject`` (a ``.py`` module path) into the plan as a
    candidate target. The tdd-implement signal lights up a symbol only when its
    MODULE is among these candidates, so the module under test must be surfaced.
    Descending values keep a stable order."""
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


# The qualifying symbol target Apex CAN implement: ``mymath.add`` does not exist;
# a RED test pins it with TWO examples so a parameter template ``a + b``, not a
# constant, wins.
_QUALIFYING_TARGET = "mymath.py:add"
_CANDIDATE_MODULES = ["mymath.py"]


def _implementable_project(tmp_path: Path) -> Path:
    """ONE implementable missing symbol. tdd-implement runs the whole suite to
    harvest failures, so — unlike the pure-AST package signals — co-locating
    mutually-interfering RED tests would change what pytest collects; the honesty
    NEGATIVES therefore live in their own isolated projects (one suite each), which
    is also how the tdd-implement objective's own tests model each refusal."""
    root = tmp_path / "proj"
    # ``mymath.add`` is absent; the RED test pins two examples a parameter template
    # proves, so the lander would land ``def add(a0, a1): return a0 + a1``.
    _write(root, "mymath.py", '"""tiny"""\n\n\ndef double(x):\n    return x * 2\n')
    _write(root, "tests/test_mymath.py",
           "from mymath import add\n\n\n"
           "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    return root


def _assertion_failure_project(tmp_path: Path) -> Path:
    """NEGATIVE — assertion failure on EXISTING code: ``calc.add`` exists but is
    wrong. That is NOT a missing symbol (out of scope; we never touch logic)."""
    root = tmp_path / "assertfail"
    _write(root, "calc.py", "def add(a, b):\n    return a - b\n")
    _write(root, "tests/test_calc.py",
           "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    return root


def _already_green_project(tmp_path: Path) -> Path:
    """NEGATIVE — already implemented (suite green): nothing is missing."""
    root = tmp_path / "settled"
    _write(root, "settled.py", "def mul(a, b):\n    return a * b\n")
    _write(root, "tests/test_settled.py",
           "from settled import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n")
    return root


def _unprovable_project(tmp_path: Path) -> Path:
    """NEGATIVE — a missing symbol the lander CANNOT synthesise: a single
    unprovable example (``ghost(3, 4) == 99``) no fixed template fits, so it is
    DETECTED but refused (empty plan)."""
    root = tmp_path / "lone"
    _write(root, "lone.py", "def existing():\n    return 1\n")
    _write(root, "tests/test_lone.py",
           "from lone import ghost\n\n\ndef test_ghost():\n    assert ghost(3, 4) == 99\n")
    return root


def _tdd_steps(plan) -> dict[str, str]:
    """{symbol_target: phase} for the executable tdd_implement steps."""
    return {
        s.target: s.phase
        for s in plan.steps
        if (s.operator == "synthesis"
            and s.action_type == "tdd_implement" and s.executable)
    }


# --- the grounding signal equals the lander's own gate (honesty) --------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _implementable_project(tmp_path)
    # The signal lights up the implementable missing symbol...
    assert tdd_implementable_symbols(str(root), _CANDIDATE_MODULES) == [
        _QUALIFYING_TARGET]
    # ...and that is EXACTLY the lander's OWN gate (the objective's ``_missing``
    # spine): a detected missing symbol with a non-empty ``plan_tdd_implement`` plan.
    qualifying = {f"{m.module_rel}:{m.name}": m
                  for m in detect_missing_symbols(str(root))}
    assert _QUALIFYING_TARGET in qualifying
    assert bool(plan_tdd_implement(
        str(root), qualifying[_QUALIFYING_TARGET]).new_contents)


def test_signal_refuses_assertion_failure_on_existing_code(tmp_path: Path) -> None:
    """An assertion failure on an EXISTING function is NOT a missing symbol — the
    detector attributes nothing, so the signal is empty (honesty: we never touch
    existing logic, and never over-promise a synthesis we could not perform)."""
    root = _assertion_failure_project(tmp_path)
    assert detect_missing_symbols(str(root)) == []
    assert tdd_implementable_symbols(str(root), ["calc.py"]) == []


def test_signal_refuses_already_green_symbol(tmp_path: Path) -> None:
    """A symbol that already exists (suite green) is not missing → empty signal."""
    root = _already_green_project(tmp_path)
    assert detect_missing_symbols(str(root)) == []
    assert tdd_implementable_symbols(str(root), ["settled.py"]) == []


def test_signal_refuses_unprovable_missing_symbol(tmp_path: Path) -> None:
    """A missing symbol IS detected, but when no fixed template proves its single
    example the lander lands nothing — so the signal drops it (it equals exactly the
    lander's own gate: a non-empty plan), never an over-promise."""
    root = _unprovable_project(tmp_path)
    detected = {f"{m.module_rel}:{m.name}": m
                for m in detect_missing_symbols(str(root))}
    assert "lone.py:ghost" in detected  # DETECTED as missing...
    # ...but refused by the lander (no template), so it does NOT qualify.
    assert not plan_tdd_implement(str(root), detected["lone.py:ghost"]).new_contents
    assert tdd_implementable_symbols(str(root), ["lone.py"]) == []


def test_signal_is_restricted_to_candidate_modules(tmp_path: Path) -> None:
    """The PER-SYMBOL signal stays tied to the plan's candidates: a symbol whose
    module is NOT among ``modules`` is dropped even though the lander would land
    it — so augmentation never surfaces a symbol the plan did not already raise."""
    root = _implementable_project(tmp_path)
    # ``mymath.py`` excluded → the only landable symbol is filtered out.
    assert tdd_implementable_symbols(str(root), ["other.py", "more.py"]) == []
    # Re-include it → it reappears (proving the module set, not the project, gates).
    assert tdd_implementable_symbols(str(root), ["mymath.py"]) == [_QUALIFYING_TARGET]


def test_signal_is_deterministic_sorted_and_capped(tmp_path: Path) -> None:
    root = tmp_path / "many"
    # Two independent implementable missing symbols in two modules. Both use the
    # ATTRIBUTE shape (``import mod`` then ``mod.fn(...)``) so each test COLLECTS
    # cleanly and fails at runtime — a ``from mod import fn`` collection error would
    # interrupt pytest's collection and mask the sibling module's failure.
    _write(root, "aa.py", '"""a"""\n')
    _write(root, "tests/test_aa.py",
           "import aa\n\n\n"
           "def test_inc():\n    assert aa.inc(2, 3) == 5\n    assert aa.inc(10, 1) == 11\n")
    _write(root, "bb.py", '"""b"""\n')
    _write(root, "tests/test_bb.py",
           "import bb\n\n\n"
           "def test_sum():\n    assert bb.plus(1, 2) == 3\n    assert bb.plus(4, 5) == 9\n")
    mods = ["bb.py", "aa.py", "bb.py"]  # dup module collapses, order normalised
    out = tdd_implementable_symbols(str(root), mods)
    assert out == ["aa.py:inc", "bb.py:plus"]  # sorted by target
    assert tdd_implementable_symbols(str(root), mods, limit=1) == ["aa.py:inc"]


def test_signal_never_raises_on_missing_or_no_suite(tmp_path: Path) -> None:
    # A project with NO test suite has nothing to attribute → empty, never a raise.
    root = tmp_path / "edge"
    _write(root, "solo.py", "def f():\n    return 1\n")
    assert tdd_implementable_symbols(str(root), ["solo.py"]) == []
    assert tdd_implementable_symbols(str(root), []) == []  # empty candidate input


# --- the augmentation surfaces the qualifying symbol, and no negative ---------

def test_plan_tree_surfaces_executable_tdd_step(tmp_path: Path) -> None:
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _CANDIDATE_MODULES),
                            project_root=str(root), tdd_implement=True)
    assert _tdd_steps(plan) == {_QUALIFYING_TARGET: "Evolve"}


def test_plan_roadmap_phases_tdd_in_evolve(tmp_path: Path) -> None:
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _CANDIDATE_MODULES),
                               project_root=str(root), tdd_implement=True)
    assert _tdd_steps(plan) == {_QUALIFYING_TARGET: "Evolve"}


def test_tdd_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented tdd_implement step is a real runnable contribution, so it
    raises the plan's executable-step count by exactly the one qualifying symbol.

    The baseline is the SAME report with tdd-implement OFF (so the only delta is
    the augmented synthesis step itself, not a different idea set)."""
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _CANDIDATE_MODULES)
    plain = bridge.plan_tree(rpt, project_root=str(root))  # tdd-implement off
    augmented = bridge.plan_tree(rpt, project_root=str(root), tdd_implement=True)
    added = len(_tdd_steps(augmented))
    assert added == 1  # exactly the one implementable missing symbol
    assert (augmented.stats["executable_steps"]
            == plain.stats["executable_steps"] + added)


# --- opt-in: tdd-implement is OFF by default (idea set never shifts) -----------

def test_tdd_is_off_by_default(tmp_path: Path) -> None:
    """tdd-implement runs the whole suite and targets symbols broadly, so it is
    opt-in: a default ``plan_tree`` (no ``tdd_implement=True``) emits NO
    tdd_implement step even on an implementable project, and is byte-identical."""
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _CANDIDATE_MODULES)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _tdd_steps(default) == {}
    assert [s for s in default.steps if s.action_type == "tdd_implement"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), tdd_implement=True)
    assert _tdd_steps(opted) == {_QUALIFYING_TARGET: "Evolve"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_tdd_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds tdd-implement unless opted in."""
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _CANDIDATE_MODULES)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _tdd_steps(default) == {}


def test_opt_in_flags_are_independent(tmp_path: Path) -> None:
    """The broad opt-in objectives are INDEPENDENT flags: opting tdd-implement in
    must NOT enable cover-gaps / wire-exports / generate-usage-doc."""
    root = _implementable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _CANDIDATE_MODULES),
                            project_root=str(root), tdd_implement=True)
    assert [s for s in plan.steps if s.action_type == "cover_gaps"] == []
    assert [s for s in plan.steps if s.action_type == "wire_exports"] == []
    assert [s for s in plan.steps if s.action_type == "generate_usage_doc"] == []
    assert _tdd_steps(plan) == {_QUALIFYING_TARGET: "Evolve"}


def test_enabling_one_flag_adds_only_its_objective() -> None:
    """``_enabled_objectives`` adds EXACTLY the opted-in objective: the
    tdd-implement flag appends ``tdd_implement`` and no other opt-in objective, and
    with every flag off it is the default tuple unchanged."""
    base = IdeaActionBridge._SYNTHESIS_OBJECTIVES
    assert IdeaActionBridge._enabled_objectives(False, False, False, False) == base
    only_tdd = IdeaActionBridge._enabled_objectives(
        False, False, False, tdd_implement=True)
    added = [row for row in only_tdd if row not in base]
    assert [r[1] for r in added] == ["tdd_implement"]


# --- determinism / opt-in safety: a project with no missing symbol adds NOTHING

def test_no_implementable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with tdd-implement OPTED IN, a project whose suite is fully green (no
    missing symbol) gets nothing added and the plan is byte-identical run-to-run —
    proving the augmentation honestly no-ops."""
    root = tmp_path / "green"
    _write(root, "alpha.py", "def a(x):\n    return x\n")
    _write(root, "tests/test_alpha.py",
           "from alpha import a\n\n\ndef test_a():\n    assert a(1) == 1\n")
    _write(root, "beta.py", "def b(x):\n    return x\n")
    _write(root, "tests/test_beta.py",
           "from beta import b\n\n\ndef test_b():\n    assert b(2) == 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), tdd_implement=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "tdd_implement"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   tdd_implement=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_tdd_step() -> None:
    """Without a project root the signal cannot run the suite, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "mymath.py")])
    plan = bridge.plan_tree(rpt, project_root="", tdd_implement=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "tdd_implement"] == []


# --- apply_step actually LANDS the real function / no-ops honestly ------------

def test_apply_step_lands_synthesised_function(tmp_path: Path) -> None:
    """The tdd_implement step lands the real synthesised ``def add`` through the
    delegated develop-core path (impact-scoped verify), proving the executable
    claim is end-to-end real and not just surfaced — and the RED test goes GREEN."""
    root = tmp_path / "land"
    _write(root, "mymath.py", '"""tiny"""\n\n\ndef double(x):\n    return x * 2\n')
    _write(root, "tests/test_mymath.py",
           "from mymath import add\n\n\n"
           "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["mymath.py"]),
                            project_root=str(root), tdd_implement=True)
    steps = [s for s in plan.steps
             if s.action_type == "tdd_implement" and s.executable]
    assert steps, "a tdd_implement step should be surfaced for the missing symbol"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "tdd_implement"
    assert out.get("suite_green") is True  # the previously-RED test now passes
    # The module now defines a real ``add`` (the parameter template, not a constant).
    landed = (root / "mymath.py").read_text(encoding="utf-8")
    assert "def add(a0, a1):" in landed
    assert "return a0 + a1" in landed


def test_apply_step_tdd_noops_on_no_missing_symbol(tmp_path: Path) -> None:
    """A target whose symbol is NOT missing (the function already exists / suite is
    green) is honestly NOT applied and the module is untouched — the delegated path
    never fakes green."""
    root = tmp_path / "noop"
    _write(root, "mymath.py", "def add(a, b):\n    return a + b\n")
    _write(root, "tests/test_mymath.py",
           "from mymath import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    original = (root / "mymath.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="mymath.py:add", action_type="tdd_implement",
                      target="mymath.py:add", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "tdd_implement"
    # Nothing was rewritten — there was no missing symbol to honestly implement.
    assert (root / "mymath.py").read_text(encoding="utf-8") == original
