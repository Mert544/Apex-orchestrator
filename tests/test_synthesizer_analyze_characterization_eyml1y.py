"""Characterization tests locking the refactored synthesize/run behavior.

These assert the exact, deterministic, offline outputs of the decomposed
``Synthesizer.synthesize`` and ``AnalyzeFailureLogSkill.run`` so future edits
cannot silently drift the contract that the byte-identical refactor preserved.
"""
from __future__ import annotations

from app.models.enums import ClaimType, NodeStatus, QuestionType, StopReason
from app.models.node import ResearchNode
from app.models.question import Question
from app.skills.repair.analyze_failure_log import AnalyzeFailureLogSkill
from app.skills.synthesizer import Synthesizer


def _node(i, **kw):
    return ResearchNode(
        id=f"n{i}",
        claim=kw.get("claim", f"claim{i}"),
        branch_path=kw.get("branch_path", f"b{i}"),
        source_question=kw.get("source_question"),
        evidence_for=kw.get("evidence_for", []),
        evidence_against=kw.get("evidence_against", []),
        assumptions=kw.get("assumptions", []),
        questions=[Question(text=t, qtype=QuestionType.MISSING) for t in kw.get("questions", [])],
        claim_type=kw.get("claim_type", ClaimType.GENERAL),
        claim_priority=kw.get("claim_priority", 0.0),
        confidence=kw.get("confidence", 0.5),
        risk=kw.get("risk", 0.3),
        status=kw.get("status", NodeStatus.NEW),
        stop_reason=kw.get("stop_reason"),
    )


def test_synthesize_empty_nodes():
    report = Synthesizer(None).synthesize("obj", [])
    assert report.objective == "obj"
    assert report.main_findings == []
    assert report.key_risks == []
    assert report.recommended_actions == []
    assert report.estimated_analysis_tokens == report.estimated_total_tokens
    assert report.estimated_response_tokens == 0
    assert report.estimated_memory_tokens == 0


def test_synthesize_dedup_sort_and_caps():
    nodes = [
        _node(0, claim="dup", assumptions=["a", "b"], evidence_for=["e1"],
              evidence_against=["x1"], questions=["q1", "q1"], claim_priority=0.9,
              source_question="why?", risk=0.12),
        _node(1, claim="dup", assumptions=["a", "c"], evidence_for=["e1", "e2"],
              evidence_against=["x2"], questions=["q2"], claim_priority=0.5,
              status=NodeStatus.STOPPED, stop_reason=StopReason.LOW_NOVELTY, risk=0.99),
        _node(2, claim="other", claim_priority=0.7, status=NodeStatus.STOPPED,
              stop_reason=None),
    ]
    report = Synthesizer(None).synthesize("obj", nodes)
    # sorted by priority desc: n0 (0.9), n2 (0.7), n1 (0.5)
    assert list(report.confidence_map.keys()) == ["dup", "other"]
    # dedup of assumptions / evidence / questions / findings
    assert report.assumptions == ["a", "b", "c"]
    assert report.strongest_supporting_evidence == ["e1", "e2"]
    assert report.strongest_opposing_evidence == ["x1", "x2"]
    assert report.unresolved_questions == ["q1", "q2"]
    assert report.main_findings == ["dup", "other"]
    # only n1 is STOPPED with a reason
    assert report.stopped_branches == ["b1 dup -> low_novelty"]
    assert report.branch_questions == {"b0": "why?"}
    # key_risks exact format + priority order
    assert report.key_risks[0] == "[b0] [general] dup -> risk=0.12 priority=0.90"
    # "dup" appears twice; the lower-priority node (0.5) is processed last and
    # overwrites the dict entry, matching the original loop semantics.
    assert report.claim_priorities == {"dup": 0.5, "other": 0.7}


def test_synthesize_findings_cap_at_ten():
    nodes = [_node(i, claim=f"c{i}", claim_priority=float(i) / 100.0) for i in range(15)]
    report = Synthesizer(None).synthesize("obj", nodes)
    assert len(report.main_findings) == 10
    # highest priority first
    assert report.main_findings[0] == "c14"


def test_synthesize_determinism():
    nodes = [_node(i, claim=f"c{i}", claim_priority=0.1 * i) for i in range(5)]
    a = Synthesizer(None).synthesize("obj", [n.model_copy(deep=True) for n in nodes])
    b = Synthesizer(None).synthesize("obj", [n.model_copy(deep=True) for n in nodes])
    assert a.model_dump() == b.model_dump()


def test_run_patch_apply_failure_takes_priority():
    skill = AnalyzeFailureLogSkill()
    out = skill.run({
        "patch_apply": {"ok": False, "error": "boom"},
        "test_summary": {"ok": False, "results": [{"ok": False, "command": ["pytest"]}]},
        "patch_scope": {"ok": False},
        "sensitive_edit": {"ok": False, "touched_sensitive_paths": ["id_rsa"]},
    })
    assert out.primary_failure_type == "patch_apply_failure"
    assert out.summary == ["boom"]
    assert out.failing_commands == []
    assert out.recommended_next_step.startswith("Check patch input")


def test_run_patch_apply_failure_default_message():
    out = AnalyzeFailureLogSkill().run({"patch_apply": {"ok": False}})
    assert out.summary == ["Patch application failed before verification."]


def test_run_test_failure_collects_commands():
    out = AnalyzeFailureLogSkill().run({
        "test_summary": {
            "ok": False,
            "results": [
                {"ok": True, "command": ["a"]},
                {"ok": False, "command": ["pytest", "-q"]},
                {"ok": False, "command": ["ruff"]},
            ],
        },
    })
    assert out.primary_failure_type == "test_failure"
    assert out.failing_commands == [["pytest", "-q"], ["ruff"]]
    assert out.summary == [
        "Detected failing verification commands.",
        "Command failed: pytest -q",
        "Command failed: ruff",
    ]


def test_run_patch_scope_failure():
    out = AnalyzeFailureLogSkill().run({"patch_scope": {"ok": False, "reasons": ["r1", "r2"]}})
    assert out.primary_failure_type == "patch_scope_failure"
    assert out.summary == ["r1", "r2"]
    # default reasons when empty
    out2 = AnalyzeFailureLogSkill().run({"patch_scope": {"ok": False}})
    assert out2.summary == ["Patch scope failed policy checks."]


def test_run_sensitive_edit_failure():
    out = AnalyzeFailureLogSkill().run({
        "sensitive_edit": {"ok": False, "touched_sensitive_paths": ["secret.env"]},
    })
    assert out.primary_failure_type == "sensitive_edit"
    assert out.summary == [
        "Sensitive paths were touched during planning or verification.",
        "Sensitive path: secret.env",
    ]


def test_run_no_failure_detected_and_empty():
    for payload in ({}, {"patch_apply": {"ok": True}, "test_summary": {"ok": True}}):
        out = AnalyzeFailureLogSkill().run(payload)
        assert out.primary_failure_type == "no_failure_detected"
        assert out.summary == ["No failure detected in verification output."]
        assert out.failing_commands == []


def test_run_none_valued_sections():
    out = AnalyzeFailureLogSkill().run({
        "test_summary": None,
        "patch_scope": None,
        "sensitive_edit": None,
        "patch_apply": None,
    })
    assert out.primary_failure_type == "no_failure_detected"
