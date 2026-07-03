"""W98 "actionability flips": four ``design_task`` rows route to proven landers.

The bridge's ``_FACT_ACTIONS`` rows for ``dependency-hub`` / ``symbol-hub``
(→ the delegated ``cover_gaps`` lander) and ``entrypoint`` / ``confluence``
(→ the delegated ``strengthen_tests`` lander) flipped from recommend-only
design tasks to executable delegated synthesis, honest-by-construction:

  - each flipped description NAMES the landed slice AND discloses the human
    design remainder verbatim (pinned here);
  - the cover_gaps rows carry a plan-time reality probe
    (``_covergaps_unserviceable`` — the lander's OWN gate): a non-qualifying
    module downgrades to an honest ``executable=False`` with the disclosed
    reason appended (never a fake claim);
  - the strengthen_tests rows deliberately have NO plan-time probe (the
    mutation engine is unaffordable at plan time — A39 precedent); the
    apply-time gate is the honesty rail (an unqualifying module is an honest
    non-applied no-op, never a fake-green);
  - the confluence FAMILY SPLIT is preserved: an UNTESTED confluence still
    routes to ``create_test_stub`` via the ``_root_action`` exception, which
    fires BEFORE the table read;
  - the rows that must NOT flip (config / coordinator / polyglot-hotspot, the
    design operators, the unknown-fact/operator fallbacks) stay design_task.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.models.idea import IdeaNode, IdeaTreeReport

_DOWNGRADE_REASON = (
    "no cover-gap (already linked test / not characterizable); human review")


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _root(fact: str, subject: str) -> IdeaNode:
    return IdeaNode(id="i", title=f"Develop {subject}", subject=subject,
                    branch_path="x.0", operator="root", source_facts=[fact])


def _plan_step(root: Path, fact: str, subject: str):
    """The single planned step for one root idea, with plan-time probes on."""
    report = IdeaTreeReport(objective="dev", project_root=str(root),
                            ideas=[_root(fact, subject)])
    plan = IdeaActionBridge().plan_tree(report, project_root=str(root))
    steps = [s for s in plan.steps if s.subject == subject]
    assert steps, f"the {fact} idea should surface a step for {subject}"
    return steps[0]


def _gappy_project(tmp_path: Path) -> Path:
    """One untested module with a public, blindly-callable function (the
    cover-gaps lander CAN characterize it) — the qualifying fixture shape."""
    root = tmp_path / "proj"
    _write(root, "widget.py", "def greet(name):\n    return f\"hi {name}\"\n")
    return root


def _covered_project(tmp_path: Path) -> Path:
    """One module with an existing linked test — the lander refuses (empty
    plan), so a flipped cover_gaps step must downgrade honestly."""
    root = tmp_path / "proj"
    _write(root, "covered.py", "def f():\n    return 1\n")
    _write(root, "tests/test_covered.py",
           "import covered\n\n\ndef test_covered():\n    assert covered.f() == 1\n")
    return root


# --- (1) each flip fires executable on a qualifying fixture -------------------

def test_dependency_hub_flip_lands_characterization_test(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "dependency-hub: widget.py", "widget.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    assert (root / "tests" / "test_widget.py").exists()
    assert "import widget" in (root / "tests" / "test_widget.py").read_text(
        encoding="utf-8")


def test_symbol_hub_flip_lands_characterization_test(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "symbol-hub: widget.py", "widget.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    assert (root / "tests" / "test_widget.py").exists()


def test_entrypoint_flip_surfaces_executable_strengthen_tests(tmp_path: Path) -> None:
    # No plan-time probe for strengthen_tests (mutation engine unaffordable at
    # plan time): the step surfaces executable; the apply-time gate decides.
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "entrypoint: widget.py", "widget.py")
    assert step.action_type == "strengthen_tests"
    assert step.executable is True


def test_confluence_flip_surfaces_executable_strengthen_tests(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "confluence: widget.py", "widget.py")
    assert step.action_type == "strengthen_tests"
    assert step.executable is True


# --- (2) honest downgrade / apply-time no-op on non-qualifying fixtures -------

def test_dependency_hub_downgrades_with_disclosed_reason(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    step = _plan_step(root, "dependency-hub: covered.py", "covered.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is False
    assert step.description.endswith(f" — {_DOWNGRADE_REASON}")


def test_symbol_hub_downgrades_with_disclosed_reason(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    step = _plan_step(root, "symbol-hub: covered.py", "covered.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is False
    assert step.description.endswith(f" — {_DOWNGRADE_REASON}")


def test_dependency_hub_downgrades_on_missing_module(tmp_path: Path) -> None:
    # Fail CLOSED: a hub target that does not exist cannot be characterized —
    # the probe downgrades instead of promising a test for nothing.
    root = tmp_path / "empty"
    root.mkdir()
    step = _plan_step(root, "dependency-hub: ghost.py", "ghost.py")
    assert step.executable is False
    assert _DOWNGRADE_REASON in step.description


def test_entrypoint_apply_time_gate_noops_honestly(tmp_path: Path) -> None:
    # A module with NO linked test cannot be strengthened: the delegated
    # lander's own gate yields an empty plan and apply_step reports an honest
    # non-applied result — never a fake-green.
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "entrypoint: widget.py", "widget.py")
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is False
    assert out["transform_type"] == "strengthen_tests"
    assert "no strengthen-tests" in out.get("reason", "")


# --- probe unit: the lander's OWN gate, edge paths -----------------------------

def test_covergaps_probe_empty_on_qualifying_module(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    assert IdeaActionBridge()._covergaps_unserviceable(
        "widget.py", str(root)) == ""


def test_covergaps_probe_fallback_reason_on_covered_module(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    assert IdeaActionBridge()._covergaps_unserviceable(
        "covered.py", str(root)) == _DOWNGRADE_REASON


def test_covergaps_probe_prefers_lander_blockers(tmp_path: Path, monkeypatch) -> None:
    # When the lander discloses its own blocker strings, they take precedence
    # over the generic fallback text.
    from app.execution import cover_gaps as cg
    from app.execution.cross_file_rename import RenamePlan

    def _blocked(project_root, module_rel):
        return RenamePlan(old=module_rel, new="cover-gaps",
                          blockers=["cannot read x.py", "second reason"])

    monkeypatch.setattr(cg, "plan_cover_gaps", _blocked)
    assert IdeaActionBridge()._covergaps_unserviceable(
        "x.py", str(tmp_path)) == "cannot read x.py; second reason"


# --- (3) the four disclosure templates, pinned verbatim ------------------------

def test_flipped_disclosure_texts_pinned_verbatim() -> None:
    assert _FACT_ACTIONS["dependency-hub"] == (
        "cover_gaps",
        "Land a characterization safety-net test for the central "
        "module {s} — a regression net before it evolves (the "
        "evolution plan itself stays a human design decision)", True)
    assert _FACT_ACTIONS["symbol-hub"] == (
        "cover_gaps",
        "Land a characterization test pinning the public behavior of "
        "the symbol-rich module {s} before generalizing it (the "
        "generalization design itself stays a human decision)", True)
    assert _FACT_ACTIONS["entrypoint"] == (
        "strengthen_tests",
        "Strengthen the tests behind entrypoint {s} with mutant-killing "
        "assertions before growing it (which capability to grow stays a "
        "human design decision)", True)
    assert _FACT_ACTIONS["confluence"] == (
        "strengthen_tests",
        "Strengthen the thin tests on {s} before changing it — several "
        "independent pressures converge here (the decoupling design "
        "itself stays a human decision)", True)


# --- (4) the confluence family split is preserved ------------------------------

def test_confluence_split_tested_vs_untested() -> None:
    bridge = IdeaActionBridge()
    tested = bridge.plan_idea(_root("confluence: app/hub.py", "app/hub.py"))
    assert tested.action_type == "strengthen_tests"
    assert tested.executable is True
    # The _root_action untested exception fires BEFORE the flipped table row.
    untested = bridge.plan_idea(
        _root("confluence: app/hub.py (untested)", "app/hub.py"))
    assert untested.action_type == "create_test_stub"
    assert untested.executable is True


# --- (5) forbidden rows stay design_task (pinned) -------------------------------

def test_forbidden_rows_still_design_task() -> None:
    assert _FACT_ACTIONS["config"] == (
        "design_task", "Make configuration {s} environment-aware", False)
    assert _FACT_ACTIONS["coordinator"][0] == "design_task"
    assert _FACT_ACTIONS["coordinator"][2] is False
    assert _FACT_ACTIONS["polyglot-hotspot"][0] == "design_task"
    assert _FACT_ACTIONS["polyglot-hotspot"][2] is False


def test_design_operators_and_fallbacks_still_design_task() -> None:
    bridge = IdeaActionBridge()
    for op in ("extend", "integrate", "generalize", "observe"):
        step = bridge.plan_idea(IdeaNode(id="i", title="t", subject="app/x.py",
                                         operator=op))
        assert step.action_type == "design_task"
        assert step.executable is False
    unknown_fact = bridge.plan_idea(_root("mystery-label: app/x.py", "app/x.py"))
    assert unknown_fact.action_type == "design_task"
    assert unknown_fact.executable is False
    assert unknown_fact.description == "Develop app/x.py"
    unknown_op = bridge.plan_idea(IdeaNode(id="i", title="t", subject="app/x.py",
                                           operator="nonexistent-op"))
    assert unknown_op.action_type == "design_task"
    assert unknown_op.executable is False
