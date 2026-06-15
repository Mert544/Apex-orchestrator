"""evolution loop: remaining uncovered branches.

Targets:
  - _measure's SecurityAgent failure path that degrades findings to 0 (92-93)
  - render_evolution_markdown's circuit-breaker warning block (195-196)
  - load_history's JSON-decode failure returning what it parsed so far (270-271)
"""

from __future__ import annotations

from pathlib import Path

from app.engine.evolution import (
    HISTORY_REL,
    EvolutionLoop,
    EvolutionResult,
    load_history,
    render_evolution_markdown,
)


def _result(**over):
    base = dict(
        cycles_run=1, reached_fixpoint=False, applied=0, rolled_back=4,
        before={"security_findings": 3, "executable_fixes": 5, "mean_roi": 2.0},
        after={"security_findings": 3, "executable_fixes": 5, "mean_roi": 2.0},
        roadmap_diff={"dropped": []},
        per_cycle=[],
        mode="supervised",
    )
    base.update(over)
    return EvolutionResult(**base)


# --- render markdown: circuit-breaker warning block (195-196) -----------------

def test_render_markdown_circuit_breaker_warning():
    result = _result(circuit_broken=True,
                     stop_reason="circuit breaker tripped (4 rollbacks in one cycle)")
    md = render_evolution_markdown(result, "/tmp/proj")
    assert "Circuit breaker tripped" in md
    assert "rolled-back fix was reverted" in md
    # The stop reason still flows into the headline.
    assert "circuit breaker tripped (4 rollbacks in one cycle)" in md


# --- _measure: SecurityAgent raising degrades findings to 0 (92-93) -----------

def test_measure_security_agent_failure_degrades_to_zero(monkeypatch):
    """When the security scan blows up, findings fall back to 0 (no crash)."""
    loop = EvolutionLoop("/tmp/proj")

    class _FakeStats:
        def __init__(self, d):
            self._d = d

        def get(self, k, default=None):
            return self._d.get(k, default)

    class _FakeRoadmap:
        stats = _FakeStats({"mean_roi": 1.5})

    class _FakePlan:
        stats = _FakeStats({"executable_steps": 4})

    class _FakeReport:
        stats = _FakeStats({"total_ideas": 9})

    class _FakeSynth:
        def build(self, report):
            return _FakeRoadmap()

    class _FakeBridge:
        def plan_roadmap(self, *a, **k):
            return _FakePlan()

    import app.engine.idea_action_bridge as iab
    import app.engine.idea_roadmap as ir

    monkeypatch.setattr(ir, "RoadmapSynthesizer", _FakeSynth)
    monkeypatch.setattr(iab, "IdeaActionBridge", _FakeBridge)

    # The SecurityAgent import lives in app.agents.skills; make it raise on use.
    import app.agents.skills as skills

    class _BoomAgent:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            raise RuntimeError("scanner exploded")

    monkeypatch.setattr(skills, "SecurityAgent", _BoomAgent)

    measure = loop._measure(_FakeReport())
    assert measure["security_findings"] == 0
    assert measure["mean_roi"] == 1.5
    assert measure["executable_fixes"] == 4
    assert measure["total_ideas"] == 9
    # The internal roadmap handle is present but stripped from the public view.
    assert "_roadmap" in measure
    assert "_roadmap" not in EvolutionLoop._public(measure)


# --- load_history: a corrupt line aborts but keeps prior entries (270-271) ----

def test_load_history_corrupt_line_returns_partial(tmp_path):
    log = Path(tmp_path) / HISTORY_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    # First line parses; the second is invalid JSON, which raises mid-loop and
    # returns whatever was accumulated so far.
    log.write_text('{"applied": 1}\n{ broken json\n{"applied": 2}\n',
                   encoding="utf-8")
    history = load_history(str(tmp_path))
    assert history == [{"applied": 1}]
