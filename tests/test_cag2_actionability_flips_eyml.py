"""CAG2-W3 "actionability flip x3": three more design_task rows route to the
proven ``cover_gaps`` lander.

The bridge's ``_FACT_ACTIONS`` rows for ``complexity-hotspot`` /
``knowledge-risk`` / ``churn-hotspot`` flip from recommend-only design tasks
to executable delegated synthesis, honest-by-construction, exactly like the
W98 ``dependency-hub`` / ``symbol-hub`` flips before them:

  - ZERO new probe code: the SAME plan-time ``_covergaps_unserviceable``
    probe (the ``cover_gaps`` lander's OWN gate) already fires for every
    executable root step, so wiring is a pure ``_FACT_ACTIONS`` table
    addition;
  - each flipped description NAMES the landed slice (a characterization
    test) AND discloses the FAMILY-SPECIFIC human-remaining design slice in
    parentheses (pinned verbatim here) — the signal's own intent (simplify /
    spread-knowledge / smooth-the-change-path) is never claimed as
    delivered;
  - a module the lander can't characterize (already linked test / not
    characterizable) downgrades to an honest ``executable=False`` with the
    disclosed reason appended (never a fake claim);
  - the rows that must NOT flip (config / coordinator / polyglot-hotspot,
    the design operators, the unknown-fact/operator fallbacks) stay
    design_task, unmodified by this wave.

Deterministic: fixed sources under ``tmp_path``, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.models.idea import IdeaNode, IdeaTreeReport

_DOWNGRADE_REASON = (
    "no cover-gap (already linked test / not characterizable); human review")

_NEW_LABELS = ("complexity-hotspot", "knowledge-risk", "churn-hotspot")


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


# --- (1) each flip fires executable on a qualifying fixture, and REALLY lands
#         a characterization test via apply_step -------------------------------

def test_complexity_hotspot_flip_lands_characterization_test(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "complexity-hotspot: widget.py", "widget.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    assert (root / "tests" / "test_widget.py").exists()
    assert "import widget" in (root / "tests" / "test_widget.py").read_text(
        encoding="utf-8")


def test_knowledge_risk_flip_lands_characterization_test(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "knowledge-risk: widget.py", "widget.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    assert (root / "tests" / "test_widget.py").exists()


def test_churn_hotspot_flip_lands_characterization_test(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    step = _plan_step(root, "churn-hotspot: widget.py", "widget.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is True
    out = IdeaActionBridge().apply_step(step, str(root), mode="autonomous",
                                        verify=True)
    assert out["applied"] is True
    assert out["transform_type"] == "cover_gaps"
    assert (root / "tests" / "test_widget.py").exists()


# --- (2) honest downgrade on a non-qualifying (already-covered) fixture -------

def test_complexity_hotspot_downgrades_with_disclosed_reason(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    step = _plan_step(root, "complexity-hotspot: covered.py", "covered.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is False
    assert step.description.endswith(f" — {_DOWNGRADE_REASON}")


def test_knowledge_risk_downgrades_with_disclosed_reason(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    step = _plan_step(root, "knowledge-risk: covered.py", "covered.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is False
    assert step.description.endswith(f" — {_DOWNGRADE_REASON}")


def test_churn_hotspot_downgrades_with_disclosed_reason(tmp_path: Path) -> None:
    root = _covered_project(tmp_path)
    step = _plan_step(root, "churn-hotspot: covered.py", "covered.py")
    assert step.action_type == "cover_gaps"
    assert step.executable is False
    assert step.description.endswith(f" — {_DOWNGRADE_REASON}")


def test_complexity_hotspot_downgrades_on_missing_module(tmp_path: Path) -> None:
    # Fail CLOSED (shared with dependency-hub/symbol-hub): a target that does
    # not exist cannot be characterized — the probe downgrades instead of
    # promising a test for nothing. One representative label suffices since
    # all three route through the IDENTICAL _covergaps_unserviceable probe.
    root = tmp_path / "empty"
    root.mkdir()
    step = _plan_step(root, "complexity-hotspot: ghost.py", "ghost.py")
    assert step.executable is False
    assert _DOWNGRADE_REASON in step.description


# --- (3) the three disclosure templates, pinned verbatim -----------------------

def test_flipped_disclosure_texts_pinned_verbatim() -> None:
    assert _FACT_ACTIONS["complexity-hotspot"] == (
        "cover_gaps",
        "Land a characterization safety-net test for the "
        "complexity hotspot {s} before it's simplified — a "
        "regression net for the riskiest place to change "
        "(the simplification itself stays a human design "
        "decision)", True)
    assert _FACT_ACTIONS["knowledge-risk"] == (
        "cover_gaps",
        "Land a characterization safety-net test for the "
        "knowledge-risk module {s} — a regression net so it "
        "isn't understood by one author alone (spreading "
        "the knowledge itself, via docs and pairing, stays "
        "a human task)", True)
    assert _FACT_ACTIONS["churn-hotspot"] == (
        "cover_gaps",
        "Land a characterization safety-net test for the "
        "churn hotspot {s} — a regression net for the module "
        "changing most before its next commit (smoothing "
        "the change path itself — interfaces, coupling — "
        "stays a human design decision)", True)


def test_flipped_disclosures_name_the_landed_slice_and_disclose_the_remainder() -> None:
    # Each description NAMES the landed slice (a characterization test) and
    # DISCLOSES a family-specific human-remaining slice in parentheses — and
    # the three are textually DISTINCT (never a copy-pasted template).
    descriptions = {label: _FACT_ACTIONS[label][1] for label in _NEW_LABELS}
    assert len(set(descriptions.values())) == 3
    for label, desc in descriptions.items():
        assert "characterization" in desc
        assert desc.count("(") == 1 and desc.endswith(")")
        assert "{s}" in desc
    # The parenthetical remainder is family-specific, not shared boilerplate.
    assert "simplif" in descriptions["complexity-hotspot"]
    assert "knowledge" in descriptions["knowledge-risk"]
    assert "change path" in descriptions["churn-hotspot"]


# --- (4) forbidden rows stay design_task (pinned; this wave touches ONLY the
#         three new keys) -------------------------------------------------------

def test_forbidden_rows_still_design_task() -> None:
    assert _FACT_ACTIONS["config"] == (
        "design_task", "Make configuration {s} environment-aware", False)
    assert _FACT_ACTIONS["coordinator"][0] == "design_task"
    assert _FACT_ACTIONS["coordinator"][2] is False
    assert _FACT_ACTIONS["polyglot-hotspot"][0] == "design_task"
    assert _FACT_ACTIONS["polyglot-hotspot"][2] is False


def test_design_operators_still_design_task() -> None:
    bridge = IdeaActionBridge()
    for op in ("extend", "integrate", "generalize", "observe"):
        step = bridge.plan_idea(IdeaNode(id="i", title="t", subject="app/x.py",
                                         operator=op))
        assert step.action_type == "design_task"
        assert step.executable is False


def test_new_labels_were_not_previously_wired() -> None:
    # Documents the pre-wave state this test file flips: each label maps to
    # cover_gaps now, never the generic ('design_task', 'Develop {s}', False)
    # fallback a stray/unknown fact label would still get.
    for label in _NEW_LABELS:
        assert _FACT_ACTIONS[label][0] == "cover_gaps"
        assert _FACT_ACTIONS[label][2] is True
    unknown_fact = IdeaActionBridge().plan_idea(
        _root("mystery-label: app/x.py", "app/x.py"))
    assert unknown_fact.action_type == "design_task"
    assert unknown_fact.executable is False
    assert unknown_fact.description == "Develop app/x.py"
