"""The action plan bridges the develop objective ``generate-usage-doc`` into
``apex ideate --actions`` as an executable step.

generate-usage-doc deterministically writes a package's sibling ``USAGE.md`` from
its PUBLIC API alone — the package's public top-level functions/classes, their
signatures, the first line of each docstring, and any ``>>>`` doctest examples
already written in those docstrings. It is PURE + a DOCTEST ORACLE (no pytest):
before the doc is allowed to stand, every ``>>>`` example is executed against the
imported package in a clean subprocess, and an example that does not run green is
omitted (an honest under-claim, never a fake-green). Like ``wire-exports`` it is
NOT a SemanticPatchResult transform — ``apply_step`` delegates it to the
develop-core ``apply_rename`` path (with ``impact_scope=True``). These tests
assert:

  - the synthesis grounding signal ``generate_usage_doc_packages`` equals the
    lander's own gate (a non-empty ``plan_generate_usage_doc(...).new_contents``):
    a package with a public API and no current doc qualifies; a package with NO
    public API, an already-current ``USAGE.md``, and a non-package ``.py`` module
    do NOT (honesty / no over-promise);
  - the augmentation emits an executable ``generate_usage_doc`` step (in the Refine
    phase) for the qualifying package and none for the negatives;
  - generate-usage-doc is OPT-IN (default off): a default plan emits NO
    generate_usage_doc step and is byte-identical run-to-run (idea set never
    shifts);
  - the three broad opt-in flags are INDEPENDENT: opting generate-usage-doc in
    does NOT enable cover-gaps or wire-exports;
  - a project with NO documentable package is byte-identical to before the
    augmentation (determinism / opt-in safety);
  - ``apply_step`` actually LANDS the real ``USAGE.md`` through the delegated
    develop-core path, and honestly no-ops (writing nothing) on a package with no
    usage-doc.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_synthesis_signals import generate_usage_doc_packages
from app.execution.objectives.generate_usage_doc import plan_generate_usage_doc
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


# One package Apex CAN document, plus the honesty-negatives the lander would
# refuse (a package with nothing public to document, an already-current doc, and
# a non-package loose module).
_QUALIFYING = ["pkg/__init__.py"]
_NEGATIVE = ["nopub/__init__.py", "current/__init__.py", "loose.py"]


def _doc_text(root: Path, init_rel: str) -> str:
    """The exact ``USAGE.md`` the lander would write for a package (used to make
    the 'already current' negative a true byte-identical no-op)."""
    return plan_generate_usage_doc(str(root), init_rel).new_contents[
        init_rel.replace("__init__.py", "USAGE.md")
    ]


def _documentable_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    # Public API, no doc yet: the lander renders a USAGE.md the doc oracle proves.
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py",
           'def run(x):\n    """Run the thing."""\n    return x\n')
    # Nothing public to document (only an underscore-private module) => no-op plan.
    _write(root, "nopub/__init__.py", "")
    _write(root, "nopub/_priv.py", "def _x():\n    return 1\n")
    # Already current: write the exact doc the lander would produce => no-op plan.
    _write(root, "current/__init__.py", "")
    _write(root, "current/mod.py",
           'def go():\n    """Go now."""\n    return 1\n')
    _write(root, "current/USAGE.md", _doc_text(root, "current/__init__.py"))
    # A loose non-package module is not a generate-usage-doc target => no-op plan.
    _write(root, "loose.py", "def f():\n    return 1\n")
    return root


def _doc_steps(plan) -> dict[str, str]:
    """{package_target: phase} for the executable generate_usage_doc steps."""
    return {
        s.target: s.phase
        for s in plan.steps
        if (s.operator == "synthesis"
            and s.action_type == "generate_usage_doc" and s.executable)
    }


# --- the grounding signal equals the lander's own gate (honesty) --------------

def test_signal_equals_lander_gate(tmp_path: Path) -> None:
    root = _documentable_project(tmp_path)
    mods = _QUALIFYING + _NEGATIVE
    # The signal lights up ONLY the documentable, not-yet-current package.
    assert generate_usage_doc_packages(str(root), mods) == ["pkg/__init__.py"]
    # And that is EXACTLY the lander's own gate: a non-empty new_contents.
    assert bool(plan_generate_usage_doc(str(root), "pkg/__init__.py").new_contents)
    for neg in _NEGATIVE:
        assert bool(plan_generate_usage_doc(str(root), neg).new_contents) is False


def test_signal_is_deterministic_and_sorted(tmp_path: Path) -> None:
    root = tmp_path / "many"
    # Two independent documentable packages; sorted, deduped, cap honored.
    _write(root, "b/__init__.py", "")
    _write(root, "b/mod.py", 'def b():\n    """B."""\n    return 2\n')
    _write(root, "a/__init__.py", "")
    _write(root, "a/mod.py", 'def a():\n    """A."""\n    return 1\n')
    mods = ["b/__init__.py", "a/__init__.py", "b/__init__.py"]  # dup collapses
    assert generate_usage_doc_packages(str(root), mods) == [
        "a/__init__.py", "b/__init__.py"]
    assert generate_usage_doc_packages(str(root), mods, limit=1) == ["a/__init__.py"]


def test_signal_never_raises_on_missing_or_broken(tmp_path: Path) -> None:
    root = tmp_path / "edge"
    # A package whose only module is unparseable contributes no public symbol, so
    # there is nothing to document (empty no-op plan) — never a raise.
    _write(root, "broken/__init__.py", "")
    _write(root, "broken/mod.py", "def oops(:\n")  # syntax error
    # Missing path + broken-content package both simply do not qualify.
    assert generate_usage_doc_packages(
        str(root), ["nope/__init__.py", "broken/__init__.py"]) == []
    assert generate_usage_doc_packages(str(root), []) == []  # empty input


# --- the augmentation surfaces the qualifying package, and no negative --------

def test_plan_tree_surfaces_executable_usage_doc_step(tmp_path: Path) -> None:
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), generate_usage_doc=True)
    assert _doc_steps(plan) == {"pkg/__init__.py": "Refine"}


def test_plan_roadmap_phases_usage_doc_in_refine(tmp_path: Path) -> None:
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_roadmap(_report(root, _QUALIFYING + _NEGATIVE),
                               project_root=str(root), generate_usage_doc=True)
    assert _doc_steps(plan) == {"pkg/__init__.py": "Refine"}


def test_usage_doc_step_counts_toward_executable_stats(tmp_path: Path) -> None:
    """The augmented generate_usage_doc step is a real runnable contribution, so it
    raises the plan's executable-step count (the exact delta also covers any
    sibling synthesis objective the qualifying package legitimately lights up)."""
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    plain = bridge.plan_tree(_report(root, _NEGATIVE), project_root=str(root),
                             generate_usage_doc=True)
    augmented = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                                 project_root=str(root), generate_usage_doc=True)
    doc_added = len(_doc_steps(augmented))
    assert doc_added == 1  # exactly the one qualifying package
    assert (augmented.stats["executable_steps"]
            >= plain.stats["executable_steps"] + doc_added)


# --- opt-in: generate-usage-doc is OFF by default (idea set never shifts) ------

def test_usage_doc_is_off_by_default(tmp_path: Path) -> None:
    """generate-usage-doc targets packages BROADLY, so it is opt-in: a default
    ``plan_tree`` (no ``generate_usage_doc=True``) emits NO generate_usage_doc step
    even on a documentable project, and is byte-identical run-to-run."""
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_tree(rpt, project_root=str(root))
    assert _doc_steps(default) == {}
    assert [s for s in default.steps
            if s.action_type == "generate_usage_doc"] == []
    # Opting in adds the step the default plan withheld.
    opted = bridge.plan_tree(rpt, project_root=str(root), generate_usage_doc=True)
    assert _doc_steps(opted) == {"pkg/__init__.py": "Refine"}
    # The default plan is stable run-to-run (no time/random in the off path).
    once = json.dumps([s.model_dump() for s in default.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root)).steps],
        sort_keys=True,
    )
    assert once == twice


def test_usage_doc_off_by_default_in_roadmap(tmp_path: Path) -> None:
    """The roadmap planner likewise withholds generate-usage-doc unless opted in."""
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    rpt = _report(root, _QUALIFYING + _NEGATIVE)
    default = bridge.plan_roadmap(rpt, project_root=str(root))
    assert _doc_steps(default) == {}


def test_three_opt_in_flags_are_independent(tmp_path: Path) -> None:
    """The three broad opt-in objectives are INDEPENDENT flags: opting
    generate-usage-doc in must NOT enable cover-gaps or wire-exports (the qualifying
    package would legitimately light up wire-exports if its flag were on, so this
    proves the flag — not the project — gates it)."""
    root = _documentable_project(tmp_path)
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, _QUALIFYING + _NEGATIVE),
                            project_root=str(root), generate_usage_doc=True)
    assert [s for s in plan.steps if s.action_type == "cover_gaps"] == []
    assert [s for s in plan.steps if s.action_type == "wire_exports"] == []
    assert _doc_steps(plan) == {"pkg/__init__.py": "Refine"}


def test_enabling_one_flag_adds_only_its_objective() -> None:
    """``_enabled_objectives`` adds EXACTLY the opted-in objective: the
    generate-usage-doc flag appends ``generate_usage_doc`` and neither cover_gaps
    nor wire_exports, and with every flag off it is the default tuple unchanged."""
    base = IdeaActionBridge._SYNTHESIS_OBJECTIVES
    assert IdeaActionBridge._enabled_objectives(False, False, False) == base
    only_doc = IdeaActionBridge._enabled_objectives(False, False, True)
    added = [row for row in only_doc if row not in base]
    assert [r[1] for r in added] == ["generate_usage_doc"]


# --- determinism / opt-in safety: a no-doc project adds NOTHING ---------------

def test_no_documentable_project_is_byte_identical(tmp_path: Path) -> None:
    """Even with generate-usage-doc OPTED IN, a project with NO documentable
    package (every package already current) gets nothing added and the plan is
    byte-identical run-to-run — proving the augmentation honestly no-ops."""
    root = tmp_path / "plain"
    _write(root, "alpha/mod.py", 'def a():\n    """A."""\n    return 1\n')
    _write(root, "alpha/__init__.py", "")
    _write(root, "alpha/USAGE.md", _doc_text(root, "alpha/__init__.py"))
    _write(root, "beta/mod.py", 'def b():\n    """B."""\n    return 2\n')
    _write(root, "beta/__init__.py", "")
    _write(root, "beta/USAGE.md", _doc_text(root, "beta/__init__.py"))
    bridge = IdeaActionBridge()
    rpt = _report(root, ["alpha/__init__.py", "beta/__init__.py"])
    plan = bridge.plan_tree(rpt, project_root=str(root), generate_usage_doc=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "generate_usage_doc"] == []
    once = json.dumps([s.model_dump() for s in plan.steps], sort_keys=True)
    twice = json.dumps(
        [s.model_dump()
         for s in bridge.plan_tree(rpt, project_root=str(root),
                                   generate_usage_doc=True).steps],
        sort_keys=True,
    )
    assert once == twice


def test_no_project_root_adds_no_usage_doc_step() -> None:
    """Without a project root the signal cannot read any package, so nothing is
    added — a graceful no-op, never a raise."""
    bridge = IdeaActionBridge()
    rpt = IdeaTreeReport(objective="dev", project_root="",
                         ideas=[_idea(0, "pkg/__init__.py")])
    plan = bridge.plan_tree(rpt, project_root="", generate_usage_doc=True)
    assert [s for s in plan.steps if s.operator == "synthesis"
            and s.action_type == "generate_usage_doc"] == []


# --- apply_step actually LANDS the real USAGE.md / no-ops honestly ------------

def test_apply_step_lands_usage_doc_change(tmp_path: Path) -> None:
    """The generate_usage_doc step lands the real ``USAGE.md`` through the delegated
    develop-core path (impact-scoped verify), proving the executable claim is
    end-to-end real and not just surfaced."""
    root = tmp_path / "land"
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py",
           'def run(x):\n    """Run the thing."""\n    return x\n')
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(_report(root, ["pkg/__init__.py"]),
                            project_root=str(root), generate_usage_doc=True)
    steps = [s for s in plan.steps
             if s.action_type == "generate_usage_doc" and s.executable]
    assert steps, "a generate_usage_doc step should be surfaced for a documentable package"
    out = bridge.apply_step(steps[0], str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "generate_usage_doc"
    # The package now carries a USAGE.md restating its public API verbatim.
    doc = (root / "pkg" / "USAGE.md").read_text(encoding="utf-8")
    assert "# `pkg` — Usage" in doc
    assert "### `run(x)`" in doc and "Run the thing." in doc


def test_apply_step_usage_doc_verifies_against_importing_test(tmp_path: Path) -> None:
    """With a test that imports the package, the delegated impact-scoped verify runs
    that real test and reports the suite green — the doctest oracle plus the
    impacted-test gate together prove the doc is safe to land end-to-end."""
    root = tmp_path / "verify"
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/engine.py",
           'def run(x):\n    """Run the thing."""\n    return x\n')
    _write(root, "tests/test_pkg.py",
           "from pkg.engine import run\n\n\ndef test_run():\n    assert run(1) == 1\n")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="pkg/__init__.py", action_type="generate_usage_doc",
                      target="pkg/__init__.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is True
    assert out.get("suite_green") is True  # the importing test passed post-doc
    assert (root / "pkg" / "USAGE.md").exists()


def test_apply_step_usage_doc_noops_on_no_public_api(tmp_path: Path) -> None:
    """A package with NO public API is honestly NOT applied and no ``USAGE.md`` is
    written — the delegated path never fakes green."""
    root = tmp_path / "noop"
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/_priv.py", "def _x():\n    return 1\n")
    step = ActionStep(branch_path="x.0", title="t", operator="synthesis",
                      subject="pkg/__init__.py", action_type="generate_usage_doc",
                      target="pkg/__init__.py", executable=True)
    bridge = IdeaActionBridge()
    out = bridge.apply_step(step, str(root), mode="autonomous", verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "generate_usage_doc"
    # No doc was written — nothing honest to document.
    assert not (root / "pkg" / "USAGE.md").exists()
