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

W99a: a THIRD objective, ``dedup-parameterized-total-return`` (the Constant-only
parameterized lander for ALWAYS-RETURNING near-duplicates — the shape
``dedup-parameterized`` itself refuses since its tail is not a plain/tail return),
gets the same signal==gate / refuses-detected-but-unsafe / deterministic-sorted /
plan_tree+plan_roadmap-surfacing / off-by-default / no-dedupable-project /
no-project-root coverage below, plus a trio-wide flag-independence check.

W99b: a FOURTH objective, ``dedup-parameterized-guarded-return`` (the
Constant-only parameterized lander for GUARD-RETURN near-duplicates — a guard
return on some path AND a live fall-through, the shape BOTH
``dedup-parameterized`` and ``dedup-parameterized-total-return`` refuse), gets
the SAME signal==gate / refuses-detected-but-unsafe / deterministic-sorted /
plan_tree+plan_roadmap-surfacing / off-by-default / no-dedupable-project /
no-project-root coverage below, completing the quartet-wide flag-independence
check (a full 4-flag non-leak matrix — every one of the four dedup-family
opt-ins is independent of the other three, and of every other opt-in synthesis
objective).

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import (
    dedup_parameterizable_modules,
    dedup_parameterized_guarded_return_modules,
    dedup_parameterized_total_return_modules,
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


# ── parameterized-total-return fixtures ──────────────────────────────────────────
# An ALWAYS-RETURNING near-duplicate: a guard return plus a tail return, differing
# only at one constant leaf (``+ 10`` vs ``+ 20``) — the shape dedup-parameterized
# itself refuses (an early, non-tail return) and dedup-parameterized-total-return
# lifts instead.
_PTR_A = (
    "def alpha(n):\n"
    "    a = n + 1\n"
    "    if a > 5:\n"
    "        return a\n"
    "    b = a * 2\n"
    "    c = b + 10\n"
    "    return c\n"
)
_PTR_B = (
    "def beta(n):\n"
    "    a = n + 1\n"
    "    if a > 5:\n"
    "        return a\n"
    "    b = a * 2\n"
    "    c = b + 20\n"
    "    return c\n"
)


def _parameterized_total_return_project(tmp_path: Path) -> Path:
    """Two modules sharing ONE landable always-returning near-duplicate, plus a
    unique module with nothing to dedup at all."""
    root = tmp_path / "ptr"
    _write(root, "a.py", _PTR_A)
    _write(root, "b.py", _PTR_B)
    _write(root, "lonely.py", "def solo(x):\n    return x + 99\n")
    return root


# ── parameterized-guarded-return fixtures ────────────────────────────────────────
# A GUARD-RETURN near-duplicate: a guard return plus a LIVE fall-through,
# differing only at one constant leaf inside the run — the shape BOTH
# dedup-parameterized (an early, non-tail return) and
# dedup-parameterized-total-return (the run does not always-return) refuse.
# The tail is made structurally DIVERGENT across copies (``build_b`` appends
# one extra statement ``build_a`` lacks) so no shifted "ends in a differing
# return" window can ALSO form and land on the total-return sibling — the
# same trick ``test_objective_dedup_parameterized_total_return.py``'s
# ``_MATRIX_PARAMETERIZED_GUARDED`` fixture documents.
_PGR_A = (
    "def build_a(data, key, log):\n"
    "    item = data.get(key)\n"
    "    if item is None:\n"
    "        return \"missing\"\n"
    "    name = item[\"name\"]\n"
    "    size = item[\"size\"] * 2\n"
    "    label = f\"{name}:{size}\"\n"
    "    log.append(label)\n"
    "    return label\n"
)
_PGR_B = (
    "def build_b(data, key, log):\n"
    "    item = data.get(key)\n"
    "    if item is None:\n"
    "        return \"missing\"\n"
    "    name = item[\"name\"]\n"
    "    size = item[\"size\"] * 3\n"
    "    label = f\"{name}:{size}\"\n"
    "    log.append(label)\n"
    "    log.append(\"done\")\n"
    "    return label\n"
)


def _parameterized_guarded_return_project(tmp_path: Path) -> Path:
    """Two modules sharing ONE landable guard-return near-duplicate, plus a
    unique module with nothing to dedup at all."""
    root = tmp_path / "pgr"
    _write(root, "a.py", _PGR_A)
    _write(root, "b.py", _PGR_B)
    _write(root, "lonely.py", "def solo(x):\n    return x + 99\n")
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


# === parameterized-total-return: signal equals the objective's own gate =========

def test_parameterized_total_return_signal_equals_gate(tmp_path: Path) -> None:
    root = _parameterized_total_return_project(tmp_path)
    mods = ["a.py", "b.py", "lonely.py"]
    assert dedup_parameterized_total_return_modules(str(root), mods) == ["a.py", "b.py"]
    from app.execution.objectives.dedup_parameterized_total_return import (
        _actionable_groups,
    )
    touched = {
        occ.split(":", 1)[0]
        for g in _actionable_groups(root) for occ in g.occurrences
    }
    assert touched == {"a.py", "b.py"}


def test_parameterized_total_return_signal_refuses_detected_but_unsafe(
    tmp_path: Path,
) -> None:
    """A near-duplicate group whose tail is a PLAIN/TAIL return (no earlier,
    non-tail exit) is DETECTED by the near-dup detector but is dedup-
    parameterized's own domain, not dedup-parameterized-total-return's — the
    objective's plan blocks it (``the range is a plain/tail-return block``), and
    the signal drops it (honest by construction, never an over-promise)."""
    root = tmp_path / "unsafe_ptr"
    _write(root, "a.py", _PARAM_A)
    _write(root, "b.py", _PARAM_B)
    # The group IS detected as a near-duplicate...
    from app.engine.near_dup import near_duplicates
    assert near_duplicates(root, fresh=True), "a near-dup group should be detected"
    # ...but its tail is a plain return (dedup-parameterized's job), so
    # dedup-parameterized-total-return has nothing actionable...
    from app.execution.objectives.dedup_parameterized_total_return import (
        _actionable_groups,
    )
    assert _actionable_groups(root) == []
    # ...and the signal honestly reports nothing.
    assert dedup_parameterized_total_return_modules(str(root), ["a.py", "b.py"]) == []


def test_parameterized_total_return_signal_deterministic_sorted_and_safe(
    tmp_path: Path,
) -> None:
    root = _parameterized_total_return_project(tmp_path)
    mods = ["b.py", "a.py", "b.py", "nope.py"]  # dup input + missing path
    assert dedup_parameterized_total_return_modules(str(root), mods) == ["a.py", "b.py"]
    assert dedup_parameterized_total_return_modules(
        str(root), mods, limit=1) == ["a.py"]
    assert dedup_parameterized_total_return_modules(str(root), []) == []  # empty input


# === parameterized-guarded-return: signal equals the objective's own gate =======

def test_parameterized_guarded_return_signal_equals_gate(tmp_path: Path) -> None:
    root = _parameterized_guarded_return_project(tmp_path)
    mods = ["a.py", "b.py", "lonely.py"]
    assert dedup_parameterized_guarded_return_modules(str(root), mods) == ["a.py", "b.py"]
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        _actionable_groups,
    )
    touched = {
        occ.split(":", 1)[0]
        for g in _actionable_groups(root) for occ in g.occurrences
    }
    assert touched == {"a.py", "b.py"}


def test_parameterized_guarded_return_signal_refuses_detected_but_unsafe(
    tmp_path: Path,
) -> None:
    """A near-duplicate group whose tail is a PLAIN/TAIL return (no earlier,
    non-tail exit) is DETECTED by the near-dup detector but is dedup-
    parameterized's own domain, not dedup-parameterized-guarded-return's — the
    objective's plan blocks it (``the range is a plain/tail-return block``), and
    the signal drops it (honest by construction, never an over-promise)."""
    root = tmp_path / "unsafe_pgr"
    _write(root, "a.py", _PARAM_A)
    _write(root, "b.py", _PARAM_B)
    # The group IS detected as a near-duplicate...
    from app.engine.near_dup import near_duplicates
    assert near_duplicates(root, fresh=True), "a near-dup group should be detected"
    # ...but its tail is a plain return (dedup-parameterized's job), so
    # dedup-parameterized-guarded-return has nothing actionable...
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        _actionable_groups,
    )
    assert _actionable_groups(root) == []
    # ...and the signal honestly reports nothing.
    assert dedup_parameterized_guarded_return_modules(str(root), ["a.py", "b.py"]) == []


def test_parameterized_guarded_return_signal_refuses_always_returning(
    tmp_path: Path,
) -> None:
    """A near-duplicate group that ALWAYS returns is dedup-parameterized-
    total-return's own domain, not dedup-parameterized-guarded-return's — the
    objective's plan blocks it, and the signal drops it."""
    root = tmp_path / "unsafe_pgr_tr"
    _write(root, "a.py", _PTR_A)
    _write(root, "b.py", _PTR_B)
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        _actionable_groups,
    )
    assert _actionable_groups(root) == []
    assert dedup_parameterized_guarded_return_modules(str(root), ["a.py", "b.py"]) == []


def test_parameterized_guarded_return_signal_deterministic_sorted_and_safe(
    tmp_path: Path,
) -> None:
    root = _parameterized_guarded_return_project(tmp_path)
    mods = ["b.py", "a.py", "b.py", "nope.py"]  # dup input + missing path
    assert dedup_parameterized_guarded_return_modules(str(root), mods) == ["a.py", "b.py"]
    assert dedup_parameterized_guarded_return_modules(
        str(root), mods, limit=1) == ["a.py"]
    assert dedup_parameterized_guarded_return_modules(str(root), []) == []  # empty input


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


def test_plan_tree_surfaces_parameterized_total_return_step(tmp_path: Path) -> None:
    root = _parameterized_total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(
        _report(root, ["a.py", "b.py", "lonely.py"]),
        project_root=str(root), dedup_parameterized_total_return=True)
    assert _dedup_steps(plan, "dedup_parameterized_total_return") == {
        "a.py": "Refine", "b.py": "Refine"}


def test_plan_roadmap_phases_parameterized_total_return_in_refine(
    tmp_path: Path,
) -> None:
    root = _parameterized_total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(
        _report(root, ["a.py", "b.py", "lonely.py"]),
        project_root=str(root), dedup_parameterized_total_return=True)
    assert _dedup_steps(plan, "dedup_parameterized_total_return") == {
        "a.py": "Refine", "b.py": "Refine"}


def test_plan_tree_surfaces_parameterized_guarded_return_step(tmp_path: Path) -> None:
    root = _parameterized_guarded_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(
        _report(root, ["a.py", "b.py", "lonely.py"]),
        project_root=str(root), dedup_parameterized_guarded_return=True)
    assert _dedup_steps(plan, "dedup_parameterized_guarded_return") == {
        "a.py": "Refine", "b.py": "Refine"}


def test_plan_roadmap_phases_parameterized_guarded_return_in_refine(
    tmp_path: Path,
) -> None:
    root = _parameterized_guarded_return_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(
        _report(root, ["a.py", "b.py", "lonely.py"]),
        project_root=str(root), dedup_parameterized_guarded_return=True)
    assert _dedup_steps(plan, "dedup_parameterized_guarded_return") == {
        "a.py": "Refine", "b.py": "Refine"}


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


def test_parameterized_total_return_is_off_by_default(tmp_path: Path) -> None:
    root = _parameterized_total_return_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, ["a.py", "b.py", "lonely.py"])
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _dedup_steps(default, "dedup_parameterized_total_return") == {}
    assert [s for s in default.steps
            if s.action_type == "dedup_parameterized_total_return"] == []
    # Opting in adds exactly the steps the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root),
                             dedup_parameterized_total_return=True)
    assert _dedup_steps(opted, "dedup_parameterized_total_return") == {
        "a.py": "Refine", "b.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_parameterized_guarded_return_is_off_by_default(tmp_path: Path) -> None:
    root = _parameterized_guarded_return_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, ["a.py", "b.py", "lonely.py"])
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _dedup_steps(default, "dedup_parameterized_guarded_return") == {}
    assert [s for s in default.steps
            if s.action_type == "dedup_parameterized_guarded_return"] == []
    # Opting in adds exactly the steps the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root),
                             dedup_parameterized_guarded_return=True)
    assert _dedup_steps(opted, "dedup_parameterized_guarded_return") == {
        "a.py": "Refine", "b.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


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


def test_dedup_parameterized_quartet_flags_are_independent(tmp_path: Path) -> None:
    """W99b: the trio->QUARTET independence matrix. The FOURTH dedup flag,
    dedup-parameterized-guarded-return, joins the independence set: enabling
    it must NOT pull in dedup-total-return, dedup-parameterized, NOR
    dedup-parameterized-total-return, and enabling those OTHER three must not
    pull in dedup-parameterized-guarded-return either — all four
    duplicates/near-duplicates live in the SAME project so the only reason
    another objective's step is absent is the flag, not the fixture."""
    root = tmp_path / "quartet"
    # An always-returning exact duplicate (dedup-total-return) ...
    _write(root, "a.py", _TR_BLOCK)
    _write(root, "b.py", _TR_BLOCK.replace("classify", "process"))
    # ... a one-constant, plain/tail-return near-duplicate (dedup-parameterized) ...
    _write(root, "pkg/a.py", _PARAM_A)
    _write(root, "pkg/b.py", _PARAM_B)
    _write(root, "pkg/__init__.py", "")
    # ... an always-returning near-duplicate (dedup-parameterized-total-return) ...
    _write(root, "ptr/a.py", _PTR_A)
    _write(root, "ptr/b.py", _PTR_B)
    # ... AND a guard-return near-duplicate (dedup-parameterized-guarded-return).
    _write(root, "pgr/a.py", _PGR_A)
    _write(root, "pgr/b.py", _PGR_B)
    bridge = IdeaActionBridge()
    mods = ["a.py", "b.py", "pkg/a.py", "pkg/b.py", "pkg/__init__.py",
            "ptr/a.py", "ptr/b.py", "pgr/a.py", "pgr/b.py"]

    # Enable ONLY parameterized-total-return: its steps appear, the other three don't.
    ptr_only = bridge.plan_tree(_report(root, mods), project_root=str(root),
                                dedup_parameterized_total_return=True)
    assert _dedup_steps(ptr_only, "dedup_parameterized_total_return") == {
        "ptr/a.py": "Refine", "ptr/b.py": "Refine"}
    assert _dedup_steps(ptr_only, "dedup_total_return") == {}
    assert _dedup_steps(ptr_only, "dedup_parameterized") == {}
    assert _dedup_steps(ptr_only, "dedup_parameterized_guarded_return") == {}

    # Enable ONLY parameterized-guarded-return: its steps appear, the other three don't.
    pgr_only = bridge.plan_tree(_report(root, mods), project_root=str(root),
                                dedup_parameterized_guarded_return=True)
    assert _dedup_steps(pgr_only, "dedup_parameterized_guarded_return") == {
        "pgr/a.py": "Refine", "pgr/b.py": "Refine"}
    assert _dedup_steps(pgr_only, "dedup_total_return") == {}
    assert _dedup_steps(pgr_only, "dedup_parameterized") == {}
    assert _dedup_steps(pgr_only, "dedup_parameterized_total_return") == {}

    # Enable the OTHER three: parameterized-guarded-return does NOT appear.
    others = bridge.plan_tree(_report(root, mods), project_root=str(root),
                              dedup_total_return=True, dedup_parameterized=True,
                              dedup_parameterized_total_return=True)
    assert _dedup_steps(others, "dedup_total_return") == {"a.py": "Refine",
                                                          "b.py": "Refine"}
    assert _dedup_steps(others, "dedup_parameterized") == {"pkg/a.py": "Refine",
                                                            "pkg/b.py": "Refine"}
    assert _dedup_steps(others, "dedup_parameterized_total_return") == {
        "ptr/a.py": "Refine", "ptr/b.py": "Refine"}
    assert _dedup_steps(others, "dedup_parameterized_guarded_return") == {}


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
    only_ptr = IdeaActionBridge._enabled_objectives(
        False, False, dedup_parameterized_total_return=True)
    assert [r[1] for r in only_ptr if r not in base] == [
        "dedup_parameterized_total_return"]
    only_pgr = IdeaActionBridge._enabled_objectives(
        False, False, dedup_parameterized_guarded_return=True)
    assert [r[1] for r in only_pgr if r not in base] == [
        "dedup_parameterized_guarded_return"]


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


def test_no_dedupable_project_is_byte_identical_all_four_flags(
    tmp_path: Path,
) -> None:
    """Even with all FOUR dedup flags opted in (including the new
    dedup-parameterized-guarded-return), a project with no actionable
    duplicate/near-duplicate gets nothing added and the plan is byte-identical
    run-to-run — the augmentation honestly no-ops."""
    root = tmp_path / "clean_pgr"
    _write(root, "alpha.py", "def a(x):\n    return x + 1\n")
    _write(root, "beta.py", "def b(y):\n    return y * 2\n")
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha.py", "beta.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root),
                            dedup_total_return=True, dedup_parameterized=True,
                            dedup_parameterized_total_return=True,
                            dedup_parameterized_guarded_return=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type in ("dedup_total_return", "dedup_parameterized",
                                  "dedup_parameterized_total_return",
                                  "dedup_parameterized_guarded_return")] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   dedup_total_return=True,
                                   dedup_parameterized=True,
                                   dedup_parameterized_total_return=True,
                                   dedup_parameterized_guarded_return=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_parameterized_total_return_step() -> None:
    """Without a project root the signal cannot read any module, so the
    dedup-parameterized-total-return step is never added — a graceful no-op,
    never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="", ideas=[_idea(0, "a.py")])
    plan = bridge.plan_tree(rpt, project_root="",
                            dedup_parameterized_total_return=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "dedup_parameterized_total_return"] == []


def test_no_project_root_adds_no_parameterized_guarded_return_step() -> None:
    """Without a project root the signal cannot read any module, so the
    dedup-parameterized-guarded-return step is never added — a graceful no-op,
    never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="", ideas=[_idea(0, "a.py")])
    plan = bridge.plan_tree(rpt, project_root="",
                            dedup_parameterized_guarded_return=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "dedup_parameterized_guarded_return"] == []


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


def test_apply_step_lands_parameterized_guarded_return(tmp_path: Path) -> None:
    """The dedup-parameterized-guarded-return step lands the real parameterized
    sentinel-projecting lift through the delegated develop-core path, impacted
    suite staying GREEN."""
    root = tmp_path / "land_pgr"
    _write(root, "a.py", _PGR_A)
    _write(root, "b.py", _PGR_B)
    _write(root, "tests/test_ab.py",
           "import a, b\n\n\n"
           'def test_a():\n'
           '    log = []\n'
           '    assert a.build_a({"k": {"name": "n", "size": 3}}, "k", log) == "n:6"\n'
           '    assert a.build_a({}, "nope", []) == "missing"\n\n\n'
           'def test_b():\n'
           '    log = []\n'
           '    assert b.build_b({"k": {"name": "n", "size": 3}}, "k", log) == "n:9"\n'
           '    assert b.build_b({}, "nope", []) == "missing"\n')
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["a.py", "b.py"]),
                            project_root=str(root),
                            dedup_parameterized_guarded_return=True)
    steps = [s for s in plan.steps
             if s.action_type == "dedup_parameterized_guarded_return" and s.executable]
    assert steps, "a dedup-parameterized-guarded-return step should be surfaced"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "dedup_parameterized_guarded_return"
    assert out.get("suite_green") is True
    # The near-duplicate constant became a parameter on the shared sentinel helper.
    landed = "".join((root / m).read_text(encoding="utf-8") for m in ("a.py", "b.py"))
    assert "_MISS = object()" in landed


def test_apply_step_parameterized_guarded_return_noops_when_nothing_actionable(
    tmp_path: Path,
) -> None:
    """Same honesty for dedup-parameterized-guarded-return: a module with no
    actionable guard-return near-duplicate is not applied and left
    byte-for-byte untouched."""
    root = tmp_path / "noop_pgr"
    _write(root, "solo.py", "def f(x):\n    return x * 3\n")
    before = (root / "solo.py").read_text(encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="solo.py",
                      action_type="dedup_parameterized_guarded_return",
                      target="solo.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "dedup_parameterized_guarded_return"
    assert (root / "solo.py").read_text(encoding="utf-8") == before
