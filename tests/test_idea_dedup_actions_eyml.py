"""The action plan bridges the two develop dedup objectives — ``dedup-total-return``
and ``dedup-parameterized`` — into ``apex ideate --actions`` as executable steps.

Both REDUCE cross-module DUPLICATION by lifting a duplicate into one shared helper:

  - ``dedup-total-return`` lifts an exact-duplicate block whose EVERY exit path
    returns (the provably-safe slice the base ``dedup`` objective leaves behind)
    verbatim into a returning helper, each copy becoming ``return _shared_n(...)``.
  - ``dedup-parameterized`` lifts a NEAR-duplicate group (structurally identical,
    differing only at constant/free-name leaves) into one PARAMETERIZED helper.

Unlike the per-module landers (cover-gaps / modernize), these are CROSS-MODULE: a
duplicate spans several modules, so the unit is a duplicate BLOCK/GROUP, not a lone
module. The grounding signals (:func:`dedup_total_return_modules` /
:func:`dedup_parameterizable_modules`) DELEGATE wholesale to each objective's OWN
gate (``_actionable_blocks`` / ``_actionable_groups`` — which already pair the
detector with the real planner and keep only units whose plan lands a change), then
keep a module precisely when it PARTICIPATES in one of those actionable units. Like
``cover-gaps`` / ``modernize`` the step is delegated by ``apply_step`` to the
develop-core ``apply_rename`` path (with ``impact_scope=True``). These tests assert,
for BOTH objectives:

  - the grounding signal equals the objective's OWN gate (honesty): a module
    participating in a LANDABLE duplicate qualifies; a module with nothing to dedup,
    and — crucially — a module participating in a DETECTED-but-NOT-landable duplicate
    (a non-total-return block / a near-dup whose signatures diverge) do NOT (no
    over-promise);
  - the augmentation emits the executable step (in the Refine phase) for a
    qualifying module and NONE for the negatives;
  - each is OPT-IN (default off): a default plan emits NO dedup step and is
    byte-identical run-to-run (the idea set never shifts);
  - the two flags are INDEPENDENT of each other and of every other opt-in flag;
  - a project with NO actionable duplicate is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real lift through the delegated develop-core
    path (impact-scoped verify keeps a tested module green), and honestly no-ops
    (writing nothing) when nothing is actionable — never a fake-green.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import (
    dedup_parameterizable_modules,
    dedup_total_return_modules,
)
from app.models.idea import ActionStep, IdeaNode, IdeaTreeReport


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _idea(i: int, subject: str) -> IdeaNode:
    """A root idea putting ``subject`` (a ``.py`` path) into the plan as a candidate
    target for the synthesis augmentation. The dedup signals light up a module only
    when its path is among these candidates, so the modules under test must be
    surfaced. Descending values keep a stable order."""
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


def _dedup_steps(plan, action_type: str) -> dict[str, str]:
    """{module_target: phase} for the executable dedup steps of ``action_type``."""
    return {
        s.target: s.phase
        for s in plan.steps
        if (s.operator == "synthesis"
            and s.action_type == action_type and s.executable)
    }


# ── total-return fixtures ──────────────────────────────────────────────────────
# An always-returning 5-statement block duplicated verbatim across two modules: the
# provably-safe slice dedup-total-return lifts. Both ``a.py`` and ``b.py`` PARTICIPATE.
_TR_BLOCK = (
    'def classify(x):\n'
    '    y = x + 1\n'
    '    z = y * 2\n'
    '    if z > 10:\n'
    '        return "big"\n'
    '    w = z - 3\n'
    '    return str(w)\n'
)


def _total_return_project(tmp_path: Path) -> Path:
    """Two modules sharing ONE landable always-returning duplicate, plus a negative
    that has nothing to dedup at all."""
    root = tmp_path / "tr"
    _write(root, "a.py", _TR_BLOCK)
    _write(root, "b.py", _TR_BLOCK.replace("classify", "process"))
    # A unique module with no duplicate anywhere -> never participates.
    _write(root, "lonely.py", "def solo(x):\n    return x + 99\n")
    return root


# ── parameterized fixtures ─────────────────────────────────────────────────────
# A near-duplicate group differing only at ONE constant leaf (``+ 10`` vs ``+ 20``):
# the provably-clean slice dedup-parameterized lifts. Both copies live in one package.
_PARAM_A = (
    "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + 10\n    return d\n"
)
_PARAM_B = (
    "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + 20\n    return d\n"
)


def _parameterized_project(tmp_path: Path) -> Path:
    """A package with two modules sharing ONE landable near-duplicate group, plus a
    dunder package marker that holds nothing to dedup."""
    root = tmp_path / "pp"
    _write(root, "pkg/a.py", _PARAM_A)
    _write(root, "pkg/b.py", _PARAM_B)
    _write(root, "pkg/__init__.py", "")
    return root


# === total-return: signal equals the objective's own gate (honesty) =============

def test_total_return_signal_equals_gate(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    mods = ["a.py", "b.py", "lonely.py"]
    # Both participants of the landable always-returning duplicate qualify; the
    # duplicate-free module does not.
    assert dedup_total_return_modules(str(root), mods) == ["a.py", "b.py"]
    # ...and that equals the objective's OWN gate: each qualifying module is the
    # module half of an occurrence of an actionable block.
    from app.execution.objectives.dedup_total_return import _actionable_blocks
    touched = {
        occ.split(":", 1)[0]
        for blk in _actionable_blocks(root) for occ in blk.occurrences
    }
    assert touched == {"a.py", "b.py"}


def test_total_return_signal_refuses_detected_but_unsafe(tmp_path: Path) -> None:
    """A duplicate block with NO return anywhere is DETECTED by the exact-dup
    detector but is never a total-return block, so the objective's plan blocks it —
    the signal drops it (honest by construction, never an over-promise)."""
    root = tmp_path / "unsafe"
    # 5+ duplicate statements, no return in the block -> never total-return.
    block = (
        "def work(x, sink):\n    a = x + 1\n    b = a + 2\n    c = b + 3\n"
        "    d = c + 4\n    sink.append(d)\n    sink.append(a)\n"
    )
    _write(root, "a.py", block)
    _write(root, "b.py", block.replace("work", "task"))
    # The block IS detected as an exact duplicate...
    from app.engine.dedup import find_duplicates
    assert find_duplicates(str(root)), "the block should be a detected duplicate"
    # ...but no window always-returns, so the objective has nothing actionable...
    from app.execution.objectives.dedup_total_return import _actionable_blocks
    assert _actionable_blocks(root) == []
    # ...and the signal honestly reports nothing.
    assert dedup_total_return_modules(str(root), ["a.py", "b.py"]) == []


def test_total_return_signal_deterministic_sorted_and_safe(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    mods = ["b.py", "a.py", "b.py", "nope.py"]  # dup input + missing path
    # Sorted, de-duplicated, missing path simply absent (never raises).
    assert dedup_total_return_modules(str(root), mods) == ["a.py", "b.py"]
    assert dedup_total_return_modules(str(root), mods, limit=1) == ["a.py"]
    assert dedup_total_return_modules(str(root), []) == []  # empty input


# === parameterized: signal equals the objective's own gate (honesty) ============

def test_parameterized_signal_equals_gate(tmp_path: Path) -> None:
    root = _parameterized_project(tmp_path)
    mods = ["pkg/a.py", "pkg/b.py", "pkg/__init__.py"]
    assert dedup_parameterizable_modules(str(root), mods) == ["pkg/a.py", "pkg/b.py"]
    from app.execution.objectives.dedup_parameterized import _actionable_groups
    touched = {
        occ.split(":", 1)[0]
        for g in _actionable_groups(root) for occ in g.occurrences
    }
    assert touched == {"pkg/a.py", "pkg/b.py"}


def test_parameterized_signal_refuses_detected_but_unsafe(tmp_path: Path) -> None:
    """A near-duplicate whose differing leaf is a PARAMETER makes the two copies'
    data-flow signatures diverge, so the objective's plan blocks it — the signal
    drops it even though the detector groups it (honest by construction)."""
    root = tmp_path / "diverge"
    a = ("def alpha(n, g, h):\n    base = n + 1\n    a = base + g\n    b = a + 1\n"
         "    c = b + 1\n    return c\n")
    b = ("def beta(n, g, h):\n    base = n + 1\n    a = base + h\n    b = a + 1\n"
         "    c = b + 1\n    return c\n")
    _write(root, "m.py", a + "\n\n" + b)
    # The group IS detected as a near-duplicate...
    from app.engine.near_dup import near_duplicates
    assert near_duplicates(root, fresh=True), "a near-dup group should be detected"
    # ...but its signatures diverge, so nothing is actionable...
    from app.execution.objectives.dedup_parameterized import _actionable_groups
    assert _actionable_groups(root) == []
    # ...and the signal honestly reports nothing.
    assert dedup_parameterizable_modules(str(root), ["m.py"]) == []


def test_parameterized_signal_deterministic_sorted_and_safe(tmp_path: Path) -> None:
    root = _parameterized_project(tmp_path)
    mods = ["pkg/b.py", "pkg/a.py", "pkg/b.py", "pkg/missing.py"]
    assert dedup_parameterizable_modules(str(root), mods) == ["pkg/a.py", "pkg/b.py"]
    assert dedup_parameterizable_modules(str(root), mods, limit=1) == ["pkg/a.py"]
    assert dedup_parameterizable_modules(str(root), []) == []


# === the augmentation surfaces the qualifying modules, no negatives =============

def test_plan_tree_surfaces_total_return_step(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["a.py", "b.py", "lonely.py"]),
                            project_root=str(root), dedup_total_return=True)
    assert _dedup_steps(plan, "dedup_total_return") == {"a.py": "Refine",
                                                        "b.py": "Refine"}


def test_plan_roadmap_phases_total_return_in_refine(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, ["a.py", "b.py", "lonely.py"]),
                               project_root=str(root), dedup_total_return=True)
    assert _dedup_steps(plan, "dedup_total_return") == {"a.py": "Refine",
                                                        "b.py": "Refine"}


def test_plan_tree_surfaces_parameterized_step(tmp_path: Path) -> None:
    root = _parameterized_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(
        _report(root, ["pkg/a.py", "pkg/b.py", "pkg/__init__.py"]),
        project_root=str(root), dedup_parameterized=True)
    assert _dedup_steps(plan, "dedup_parameterized") == {"pkg/a.py": "Refine",
                                                         "pkg/b.py": "Refine"}


# === opt-in: each is OFF by default (idea set never shifts) ======================

def test_total_return_is_off_by_default(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, ["a.py", "b.py", "lonely.py"])
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _dedup_steps(default, "dedup_total_return") == {}
    assert [s for s in default.steps if s.action_type == "dedup_total_return"] == []
    # Opting in adds exactly the steps the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), dedup_total_return=True)
    assert _dedup_steps(opted, "dedup_total_return") == {"a.py": "Refine",
                                                         "b.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_parameterized_is_off_by_default(tmp_path: Path) -> None:
    root = _parameterized_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, ["pkg/a.py", "pkg/b.py", "pkg/__init__.py"])
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _dedup_steps(default, "dedup_parameterized") == {}
    assert [s for s in default.steps if s.action_type == "dedup_parameterized"] == []
    opted = bridge.plan_tree(rpt, project_root=str(root), dedup_parameterized=True)
    assert _dedup_steps(opted, "dedup_parameterized") == {"pkg/a.py": "Refine",
                                                         "pkg/b.py": "Refine"}


def test_total_return_off_by_default_in_roadmap(tmp_path: Path) -> None:
    root = _total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, ["a.py", "b.py", "lonely.py"])
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _dedup_steps(default, "dedup_total_return") == {}


# === the opt-in flags are INDEPENDENT ===========================================

def test_dedup_flags_are_independent(tmp_path: Path) -> None:
    """The two dedup flags are INDEPENDENT of each other and of every other opt-in
    objective: enabling dedup-total-return must NOT pull in dedup-parameterized (nor
    cover-gaps / wire-exports / generate-usage-doc / tdd-implement / strengthen-tests
    / modernize), and vice-versa. Both duplicates live in the SAME project so the only
    reason the OTHER objective's step is absent is the flag, not the fixture."""
    root = tmp_path / "both"
    # An always-returning exact duplicate (dedup-total-return) ...
    _write(root, "a.py", _TR_BLOCK)
    _write(root, "b.py", _TR_BLOCK.replace("classify", "process"))
    # ... AND a one-constant near-duplicate (dedup-parameterized), in one package.
    _write(root, "pkg/a.py", _PARAM_A)
    _write(root, "pkg/b.py", _PARAM_B)
    _write(root, "pkg/__init__.py", "")
    bridge = IdeaActionBridge()
    mods = ["a.py", "b.py", "pkg/a.py", "pkg/b.py", "pkg/__init__.py"]

    # Enable ONLY total-return: its steps appear, parameterized's do NOT.
    tr_only = bridge.plan_tree(_report(root, mods), project_root=str(root),
                               dedup_total_return=True)
    assert _dedup_steps(tr_only, "dedup_total_return") == {"a.py": "Refine",
                                                           "b.py": "Refine"}
    assert _dedup_steps(tr_only, "dedup_parameterized") == {}
    for other in ("cover_gaps", "wire_exports", "generate_usage_doc",
                  "tdd_implement", "strengthen_tests", "modernize"):
        assert [s for s in tr_only.steps if s.action_type == other] == [], other

    # Enable ONLY parameterized: its steps appear, total-return's do NOT.
    pp_only = bridge.plan_tree(_report(root, mods), project_root=str(root),
                               dedup_parameterized=True)
    assert _dedup_steps(pp_only, "dedup_parameterized") == {"pkg/a.py": "Refine",
                                                            "pkg/b.py": "Refine"}
    assert _dedup_steps(pp_only, "dedup_total_return") == {}


def test_enabling_one_flag_adds_only_its_objective() -> None:
    """``_enabled_objectives`` adds EXACTLY the opted-in objective: each dedup flag
    appends only its own row and no other opt-in objective; with every flag off it is
    the default tuple unchanged."""
    base = IdeaActionBridge._SYNTHESIS_OBJECTIVES
    assert IdeaActionBridge._enabled_objectives(False, False) == base
    only_tr = IdeaActionBridge._enabled_objectives(
        False, False, dedup_total_return=True)
    assert [r[1] for r in only_tr if r not in base] == ["dedup_total_return"]
    only_pp = IdeaActionBridge._enabled_objectives(
        False, False, dedup_parameterized=True)
    assert [r[1] for r in only_pp if r not in base] == ["dedup_parameterized"]


# === determinism / opt-in safety: a duplicate-free project adds NOTHING =========

def test_no_dedupable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with BOTH dedup flags opted in, a project with no actionable duplicate
    gets nothing added and the plan is byte-identical run-to-run — the augmentation
    honestly no-ops."""
    root = tmp_path / "clean"
    _write(root, "alpha.py", "def a(x):\n    return x + 1\n")
    _write(root, "beta.py", "def b(y):\n    return y * 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root),
                            dedup_total_return=True, dedup_parameterized=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type in ("dedup_total_return", "dedup_parameterized")] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   dedup_total_return=True,
                                   dedup_parameterized=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_dedup_step() -> None:
    """Without a project root the signals cannot read any module, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="", ideas=[_idea(0, "a.py")])
    plan = bridge.plan_tree(rpt, project_root="",
                            dedup_total_return=True, dedup_parameterized=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type in ("dedup_total_return", "dedup_parameterized")] == []


# === apply_step actually LANDS the lift / no-ops honestly =======================

def test_apply_step_lands_total_return(tmp_path: Path) -> None:
    """The dedup-total-return step lands the real lift through the delegated
    develop-core path (impact-scoped verify), proving the executable claim is
    end-to-end real — and the impacted suite stays GREEN (the lift is
    behaviour-preserving)."""
    root = tmp_path / "land_tr"
    _write(root, "a.py", _TR_BLOCK)
    _write(root, "b.py", _TR_BLOCK.replace("classify", "process"))
    _write(root, "tests/test_ab.py",
           "import a, b\n\n\n"
           'def test_a():\n    assert a.classify(0) == "-1" and a.classify(20) == "big"\n\n\n'
           'def test_b():\n    assert b.process(0) == "-1" and b.process(20) == "big"\n')
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["a.py", "b.py"]),
                            project_root=str(root), dedup_total_return=True)
    steps = [s for s in plan.steps
             if s.action_type == "dedup_total_return" and s.executable]
    assert steps, "a dedup-total-return step should be surfaced"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "dedup_total_return"
    assert out.get("suite_green") is True  # behaviour-preserving -> still passes
    # The duplicate was lifted into a shared returning helper.
    landed_a = (root / "a.py").read_text(encoding="utf-8")
    assert "_shared" in landed_a and "return " in landed_a


def test_apply_step_lands_parameterized(tmp_path: Path) -> None:
    """The dedup-parameterized step lands the real parameterized lift through the
    delegated develop-core path, impacted suite staying GREEN."""
    root = tmp_path / "land_pp"
    _write(root, "pkg/a.py", _PARAM_A)
    _write(root, "pkg/b.py", _PARAM_B)
    _write(root, "pkg/__init__.py", "")
    _write(root, "tests/test_pp.py",
           "from pkg import a, b\n\n\n"
           "def test_a():\n    assert a.alpha(5) == 25\n\n\n"
           "def test_b():\n    assert b.beta(5) == 35\n")
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(
        _report(root, ["pkg/a.py", "pkg/b.py"]),
        project_root=str(root), dedup_parameterized=True)
    steps = [s for s in plan.steps
             if s.action_type == "dedup_parameterized" and s.executable]
    assert steps, "a dedup-parameterized step should be surfaced"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "dedup_parameterized"
    assert out.get("suite_green") is True
    # The near-duplicate constant became a parameter on the shared helper.
    landed = "".join((root / "pkg" / m).read_text(encoding="utf-8")
                     for m in ("a.py", "b.py"))
    assert "_shared" in landed


def test_apply_step_total_return_noops_when_nothing_actionable(tmp_path: Path) -> None:
    """A module with no actionable duplicate is honestly NOT applied and its source is
    left untouched — the delegated path never fakes green."""
    root = tmp_path / "noop_tr"
    _write(root, "solo.py", "def f(x):\n    return x + 1\n")
    before = (root / "solo.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="solo.py", action_type="dedup_total_return",
                      target="solo.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "dedup_total_return"
    assert (root / "solo.py").read_text(encoding="utf-8") == before


def test_apply_step_parameterized_noops_when_nothing_actionable(tmp_path: Path) -> None:
    """Same honesty for dedup-parameterized: a module with no actionable near-duplicate
    is not applied and left byte-for-byte untouched."""
    root = tmp_path / "noop_pp"
    _write(root, "solo.py", "def f(x):\n    return x * 3\n")
    before = (root / "solo.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="solo.py", action_type="dedup_parameterized",
                      target="solo.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "dedup_parameterized"
    assert (root / "solo.py").read_text(encoding="utf-8") == before
