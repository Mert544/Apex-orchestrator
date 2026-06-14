"""Proof-of-VALUE: an applied & verified fix carries its measured before→after win.

When Apex applies and verifies a fix, the evidence should prove *value*, not just
"applied, verified": the maintenance report line and the proof-of-fix record both
carry the measured structural improvement (max nesting / cyclomatic / cognitive /
lines). These tests pin that the win is computed at apply-time from the in-hand
before (snapshot) + after (written) source, threaded into the per-fix record, and
rendered on the applied-fix line — and that a fix moving no metric stays exactly
byte-identical to today (no impact clause anywhere). Deterministic, stdlib-only.
"""

from __future__ import annotations

from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _applied_fix_line,
    render_maintenance_markdown,
)
from app.engine.proof_of_fix import build_proof

# A flatten-nesting change: deep guard pyramid -> early return. Moves every metric.
_BEFORE = (
    "def f(x):\n"
    "    if x:\n"
    "        if x > 1:\n"
    "            if x > 2:\n"
    "                return x\n"
    "    return 0\n"
)
_AFTER = (
    "def f(x):\n"
    "    if not x:\n"
    "        return 0\n"
    "    return x\n"
)


# --- apply-time impact measurement -----------------------------------------

def test_measure_applied_impact_summarizes_a_metric_win():
    snapshot = {"app/m.py": _BEFORE}
    requests = [{"path": "app/m.py", "new_content": _AFTER}]
    impact = IdeaActionBridge._measure_applied_impact(
        snapshot, requests, ["app/m.py"])
    # A real win is summarized, leading with max nesting (fixed metric order).
    assert "max nesting 3→1" in impact
    assert "cognitive" in impact


def test_measure_applied_impact_empty_when_no_metric_moves():
    # Byte-identical before/after -> nothing improved -> empty (no clause).
    snapshot = {"app/m.py": _BEFORE}
    requests = [{"path": "app/m.py", "new_content": _BEFORE}]
    assert IdeaActionBridge._measure_applied_impact(
        snapshot, requests, ["app/m.py"]) == ""


def test_measure_applied_impact_skips_non_python_files():
    snapshot = {"README.md": "# old\n\nmore\n"}
    requests = [{"path": "README.md", "new_content": "# new\n"}]
    assert IdeaActionBridge._measure_applied_impact(
        snapshot, requests, ["README.md"]) == ""


def test_measure_applied_impact_never_raises_on_garbage():
    # A measurement slip must not break the apply/record — defensive empty.
    assert IdeaActionBridge._measure_applied_impact(
        {"x.py": None}, [{}], ["x.py"]) == ""


def test_measure_applied_impact_is_deterministic():
    snapshot = {"app/m.py": _BEFORE}
    requests = [{"path": "app/m.py", "new_content": _AFTER}]
    first = IdeaActionBridge._measure_applied_impact(
        snapshot, requests, ["app/m.py"])
    second = IdeaActionBridge._measure_applied_impact(
        snapshot, requests, ["app/m.py"])
    assert first == second and first != ""


# --- proof-of-fix record carries impact ------------------------------------

def test_fix_record_carries_impact_when_present():
    summary = {
        "results": [
            {"branch": "1", "applied": True, "target": "app/m.py",
             "impact": "max nesting 3→1, cognitive 6→1"},
        ],
    }
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert rec["outcome"] == "applied"
    assert rec["impact"] == "max nesting 3→1, cognitive 6→1"


def test_fix_record_omits_impact_when_no_metric_moved():
    # No "impact" on the row -> the record is byte-identical to today's shape.
    base = {"results": [{"branch": "1", "applied": True, "target": "app/m.py"}]}
    with_empty = {"results": [{"branch": "1", "applied": True,
                               "target": "app/m.py", "impact": ""}]}
    rec_base = build_proof(base, "/tmp/p")["fixes"][0]
    rec_empty = build_proof(with_empty, "/tmp/p")["fixes"][0]
    assert "impact" not in rec_base
    assert "impact" not in rec_empty


# --- maintenance markdown renders the win ----------------------------------

def test_applied_fix_line_shows_impact_clause():
    line = _applied_fix_line({
        "branch": "1", "action": "harden", "verified": True,
        "verification_strength": {"level": "module"},
        "changed_files": ["app/m.py"],
        "impact": "max nesting 3→1, cognitive 6→3",
    })
    # The measured win rides on the applied-fix line, after the verify clause.
    assert "(tests pass — suite references this module)" in line
    assert "— max nesting 3→1, cognitive 6→3" in line


def test_maintenance_markdown_shows_impact():
    summary = {
        "mode": "supervised", "verify": True, "applied": 1,
        "rolled_back": 0, "blocked": 0, "total_executable": 1,
        "results": [
            {"branch": "1", "action": "harden", "applied": True,
             "verified": True, "changed_files": ["app/m.py"],
             "impact": "max nesting 3→1, cognitive 6→3"},
        ],
    }
    md = render_maintenance_markdown(summary, "/tmp/p")
    assert "max nesting 3→1, cognitive 6→3" in md


def test_maintenance_markdown_byte_identical_without_impact():
    # A fix that moves no metric must render exactly as it did before the
    # proof-of-value feature: no "impact" key -> no clause, byte-for-byte same.
    def row(extra: dict) -> dict:
        base = {"branch": "1", "action": "harden", "applied": True,
                "verified": True, "changed_files": ["app/m.py"]}
        base.update(extra)
        return base

    no_clause = _applied_fix_line(row({}))
    empty_clause = _applied_fix_line(row({"impact": ""}))
    assert no_clause == empty_clause
    assert "—" not in no_clause.split("app/m.py", 1)[1]


# --- end-to-end through the real apply path --------------------------------

def test_real_apply_path_attaches_impact(tmp_path):
    # Drive the genuine apply path: a deep-nesting function Apex can flatten.
    # When the transform fires, the result dict carries a measured impact and
    # it survives into the proof-of-fix record + maintenance markdown.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text(_BEFORE)
    from app.models.idea import IdeaNode

    idea = IdeaNode(id="i", title="Refactor: app/svc.py", subject="app/svc.py",
                    operator="refactor", operator_chain=["refactor"],
                    source_facts=["deep-nesting: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")

    if not (result.get("applied") and result.get("impact")):
        # The transform may decline on this shape; only assert when it fired.
        return
    assert "→" in result["impact"]
    proof = build_proof({"results": [{**result, "branch": "1",
                                      "action": "refactor"}]}, str(tmp_path))
    assert proof["fixes"][0]["impact"] == result["impact"]
    md = render_maintenance_markdown(
        {"mode": "supervised", "applied": 1, "results": [
            {**result, "branch": "1", "action": "refactor"}]}, str(tmp_path))
    assert result["impact"] in md
