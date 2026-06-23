"""Deterministic coverage for cmd_auto's narrative-enrichment and decision
branches in app/cli_autonomy.py — the paths the existing real-engine tests in
test_cli_auto.py don't reliably hit.

Everything heavy is monkeypatched at the SOURCE modules (cmd_auto imports its
collaborators lazily inside the function body, so patching the origin modules is
what takes effect): the idea engine, roadmap synthesizer, tree-shape analyzer,
the action bridge, the security agent, the idea-memory ledger, the autonomy
policy, signal trends and proof-of-fix. No real pytest suite runs, nothing
touches a real repo, and there are no time/random/order assertions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import cmd_auto


def _ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=False, recommend=False, mode=None,
        commit=False, no_verify=False, max_apply=0, json=False, out="",
    )
    base.update(over)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# Lightweight fakes for the collaborators cmd_auto pulls in.                   #
# --------------------------------------------------------------------------- #
class _FakeShape:
    def __init__(self, *, observations=None, heaviest_module="", heaviest_loc=0,
                 total_ideas=3, distinct_subjects=2):
        self.observations = observations or []
        self.heaviest_module = heaviest_module
        self.heaviest_loc = heaviest_loc
        self.total_ideas = total_ideas
        self.distinct_subjects = distinct_subjects


class _QuickWin:
    def __init__(self, title, roi):
        self.title = title
        self.roi = roi


class _FakeRoadmap:
    def __init__(self, quick_wins=None):
        self.quick_wins = quick_wins or []


class _FakeRoadmapSynth:
    _roadmap = _FakeRoadmap()

    def build(self, report):
        return self._roadmap


class _FakeEngine:
    last_profile = None

    def __init__(self, **kw):
        pass

    def run(self, objective=None):
        return {"objective": objective}


class _FakePlugins:
    def load_all(self):
        pass

    def idea_operators(self):
        return []


class _FakeScout:
    def __init__(self, executable):
        self.stats = {"executable_steps": executable}


class _FakeBridge:
    """Controls plan_roadmap/apply_plan so no real planning/apply happens."""

    _executable = 0
    _apply_summary: dict = {"results": []}
    applied: list = []

    def plan_roadmap(self, report, mode="report", project_root="", draft=False,
                     **synth_kwargs):
        # `apex auto` now passes the cheap synthesis opt-ins (modernize /
        # dedup_total_return / dedup_parameterized) here autonomously, and the
        # expensive ones under --deep; this double ignores them (the real bridge
        # accepts them) so these decision/narrative tests stay focused.
        return _FakeScout(self._executable)

    def apply_plan(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        type(self).applied.append((mode, verify, max_apply, commit))
        return self._apply_summary


def _patch_common(monkeypatch, *, shape, roadmap, executable, apply_summary=None,
                  sec_findings=None, sec_raises=False, mem_summary=None,
                  mem_raises=False, decision=None):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: _FakePlugins())

    synth = _FakeRoadmapSynth()
    synth._roadmap = roadmap
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: synth)
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: shape)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": "# Maintenance")

    bridge = _FakeBridge()
    type(bridge)._executable = executable
    if apply_summary is not None:
        type(bridge)._apply_summary = apply_summary
    type(bridge).applied = []
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)

    # Security agent
    class _Sec:
        def run(self, project_root=""):
            if sec_raises:
                raise RuntimeError("scanner exploded")
            return {"findings": sec_findings or []}

    monkeypatch.setattr("app.agents.skills.SecurityAgent", lambda *a, **k: _Sec())
    monkeypatch.setattr("app.engine.health_score._is_fixture_path",
                        lambda p: "fixture" in str(p) or "examples" in str(p))

    # Idea memory
    class _Mem:
        def summary(self):
            return mem_summary or {}

    def _load(root):
        if mem_raises:
            raise RuntimeError("corrupt ledger")
        return _Mem()

    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.load",
                        staticmethod(_load))
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.learn_from",
                        staticmethod(lambda summary, target: None))

    # Signal trends + proof-of-fix sinks (no disk writes / no real engine)
    class _Trends:
        def __init__(self, root):
            pass

        def record(self, profile):
            pass

    monkeypatch.setattr("app.engine.signal_trends.SignalTrends", _Trends)
    monkeypatch.setattr("app.engine.proof_of_fix.build_proof",
                        lambda summary, root, objective="": {"proof": True})
    monkeypatch.setattr("app.engine.proof_of_fix.write_proof",
                        lambda proof, root: str(Path(root) / ".apex" / "proof.json"))

    # Autonomy policy
    from app.policies.autonomy_policy import AutonomyDecision

    class _Policy:
        def decide(self, **kw):
            return decision if decision is not None else AutonomyDecision(
                False, "report", "no safe, auto-applicable fixes found")

    monkeypatch.setattr("app.policies.autonomy_policy.AutonomyPolicy",
                        lambda *a, **k: _Policy())

    # Working-tree-clean is consulted but its value doesn't matter once the
    # policy is fixed; make it deterministic anyway.
    monkeypatch.setattr("app.cli_autonomy._working_tree_clean", lambda target: True)
    return bridge


# --------------------------------------------------------------------------- #
# Headline enrichment branches (observations / quick_wins / heaviest module)  #
# --------------------------------------------------------------------------- #
def test_auto_headline_includes_observations_and_heaviest(tmp_path, capsys, monkeypatch):
    shape = _FakeShape(observations=["a", "b", "c", "d", "e"],
                       heaviest_module="app/big.py", heaviest_loc=900)
    roadmap = _FakeRoadmap([_QuickWin("Trim dead param", 9.0)])
    _patch_common(monkeypatch, shape=shape, roadmap=roadmap, executable=0)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "heaviest `app/big.py` (900 LOC)" in out
    assert "What stands out:" in out
    # capped at the first four observations
    assert "- a" in out and "- d" in out and "- e" not in out
    assert "Best next moves" in out
    assert "Trim dead param  (ROI 9.0)" in out


def test_auto_headline_no_observations_no_quick_wins(tmp_path, capsys, monkeypatch):
    shape = _FakeShape(observations=[], heaviest_module="")
    roadmap = _FakeRoadmap([])
    _patch_common(monkeypatch, shape=shape, roadmap=roadmap, executable=0)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "What stands out:" not in out
    assert "Best next moves" not in out


# --------------------------------------------------------------------------- #
# Security headline: fixture split + scanner failure must not break auto.      #
# --------------------------------------------------------------------------- #
def test_auto_security_fixture_split(tmp_path, capsys, monkeypatch):
    findings = [{"file": "app/svc.py"}, {"file": "examples/demo/vuln.py"}]
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=0, sec_findings=findings)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 security finding(s)" in out
    assert "+1 in example/fixture code" in out


def test_auto_security_scanner_failure_degrades_gracefully(tmp_path, capsys, monkeypatch):
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=0, sec_raises=True)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    # a failing scanner falls back to zero findings, never raising
    assert "0 security finding(s)" in out


# --------------------------------------------------------------------------- #
# Idea-memory "what I've learned" enrichment line.                            #
# --------------------------------------------------------------------------- #
def test_auto_memory_enrichment_line(tmp_path, capsys, monkeypatch):
    mem = {"most_reliable": [{"key": "yaml.safe_load", "success_rate": 0.75,
                              "samples": 8}]}
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=0, mem_summary=mem)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "What I've learned here" in out
    assert "yaml.safe_load" in out
    assert "75% of the time" in out
    assert "8 samples" in out


def test_auto_memory_load_failure_is_silent(tmp_path, capsys, monkeypatch):
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=0, mem_raises=True)
    rc = cmd_auto(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    # a corrupt ledger simply omits the line — no crash, no learned line
    assert "What I've learned here" not in out


# --------------------------------------------------------------------------- #
# Recommend path — JSON shape.                                                #
# --------------------------------------------------------------------------- #
def test_auto_recommend_json_payload(tmp_path, capsys, monkeypatch):
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(False, "report", "nothing to do")
    shape = _FakeShape(observations=["x"], total_ideas=7, distinct_subjects=3)
    roadmap = _FakeRoadmap([_QuickWin("win", 4.0)])
    _patch_common(monkeypatch, shape=shape, roadmap=roadmap, executable=2,
                  decision=decision)
    rc = cmd_auto(_ns(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is False
    assert payload["ideas"] == 7
    assert payload["modules"] == 3
    assert payload["applicable"] == 2
    assert payload["quick_wins"] == [{"title": "win", "roi": 4.0}]
    assert payload["decision"]["reason"] == "nothing to do"


# --------------------------------------------------------------------------- #
# Act path — proof-of-fix, uncommitted footer, out-file (markdown + json).     #
# --------------------------------------------------------------------------- #
def test_auto_act_markdown_with_proof_and_footer(tmp_path, capsys, monkeypatch):
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(True, "supervised", "clean tree + fixes")
    summary = {"results": [{"applied": True}], "applied": 1, "commit": False}
    bridge = _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                           executable=3, apply_summary=summary, decision=decision)
    rc = cmd_auto(_ns(tmp_path, apply=True, max_apply=4))
    out = capsys.readouterr().out
    assert rc == 0
    assert "applying autonomously" in out.lower()
    assert "Proof-of-fix evidence written" in out
    assert "not committed" in out
    # apply was routed with the requested cap and not committing
    assert bridge.applied[-1] == ("supervised", True, 4, False)


def test_auto_act_json_includes_decision(tmp_path, capsys, monkeypatch):
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(True, "supervised", "go")
    summary = {"results": [{"applied": True}], "applied": 1}
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=1, apply_summary=summary, decision=decision)
    rc = cmd_auto(_ns(tmp_path, apply=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["decision"]["act"] is True
    assert payload["applied"] == 1


def test_auto_act_no_results_skips_proof_and_out(tmp_path, capsys, monkeypatch):
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(True, "supervised", "go")
    summary = {"results": [], "applied": 0}
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=1, apply_summary=summary, decision=decision)
    out_file = tmp_path / "auto.md"
    rc = cmd_auto(_ns(tmp_path, apply=True, out=str(out_file)))
    out = capsys.readouterr().out
    assert rc == 0
    # empty results -> no proof line emitted
    assert "Proof-of-fix" not in out
    assert "[auto] Report written to" in out
    assert out_file.exists()


def test_auto_act_report_mode_upgraded_to_supervised(tmp_path, capsys, monkeypatch):
    """decision.act with a report mode must upgrade to supervised before apply."""
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(True, "report", "apply explicitly requested")
    summary = {"results": [{"applied": True}], "applied": 1}
    bridge = _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                           executable=1, apply_summary=summary, decision=decision)
    rc = cmd_auto(_ns(tmp_path, apply=True))
    assert rc == 0
    # the plan/apply ran in supervised, never "report"
    assert bridge.applied[-1][0] == "supervised"


def test_auto_act_commit_omits_uncommitted_footer(tmp_path, capsys, monkeypatch):
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(True, "autonomous", "go")
    summary = {"results": [{"applied": True}], "applied": 1}
    bridge = _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                           executable=1, apply_summary=summary, decision=decision)
    rc = cmd_auto(_ns(tmp_path, apply=True, commit=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "not committed" not in out
    assert bridge.applied[-1][3] is True  # commit forwarded


# --------------------------------------------------------------------------- #
# Goal-driven mode inference (and its best-effort failure path).              #
# --------------------------------------------------------------------------- #
def test_auto_goal_mode_inference_failure_is_swallowed(tmp_path, capsys, monkeypatch):
    """A goal that makes IntentParser raise must not break auto — mode stays
    unset and the policy decision drives behavior."""
    from app.policies.autonomy_policy import AutonomyDecision
    decision = AutonomyDecision(False, "report", "nothing")
    _patch_common(monkeypatch, shape=_FakeShape(), roadmap=_FakeRoadmap(),
                  executable=0, decision=decision)

    class _BoomParser:
        def parse(self, goal):
            raise RuntimeError("cannot parse")

    monkeypatch.setattr("app.intent.parser.IntentParser",
                        lambda *a, **k: _BoomParser())
    rc = cmd_auto(_ns(tmp_path, goal="do something vague"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "do something vague" in out
