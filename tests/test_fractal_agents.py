from __future__ import annotations

import pytest

from app.agents.fractal_agents import (
    FractalSecurityAgent,
    FractalDocstringAgent,
    FractalTestStubAgent,
    FractalAnalyzerAgent,
)
from app.agents.bus import AgentBus


class TestFractalSecurityAgent:
    def test_finds_risks_and_analyzes(self, tmp_path):
        risky = tmp_path / "risky.py"
        risky.write_text("result = eval(user_input)\n")
        agent = FractalSecurityAgent()
        result = agent.run(project_root=tmp_path, max_depth=3)
        assert result["findings_count"] >= 1
        assert result["fractal_analyzed"] >= 1
        assert len(result["fractal_trees"]) >= 1

    def test_respects_budget(self, tmp_path):
        for i in range(20):
            (tmp_path / f"file_{i}.py").write_text(f"eval(x{i})\n")
        agent = FractalSecurityAgent()
        agent.max_fractal_budget = 3
        result = agent.run(project_root=tmp_path)
        assert result["fractal_analyzed"] <= 3

    def test_broadcasts_fractal_event(self, tmp_path):
        bus = AgentBus()
        received = []
        bus.subscribe("test", "fractal.analysis.complete", lambda msg: received.append(msg))
        agent = FractalSecurityAgent(bus=bus)
        risky = tmp_path / "risky.py"
        risky.write_text("eval(x)\n")
        agent.run(project_root=tmp_path)
        assert len(received) >= 1


class TestFractalDocstringAgent:
    def test_finds_gaps_and_analyzes(self, tmp_path):
        code = tmp_path / "code.py"
        code.write_text("def foo(): pass\n")
        agent = FractalDocstringAgent()
        result = agent.run(project_root=tmp_path, max_depth=3)
        assert result["findings_count"] >= 1
        assert result["fractal_analyzed"] >= 1
        assert any(f["issue"] == "missing_docstring" for f in result["findings"])


class TestFractalTestStubAgent:
    def test_finds_gaps_and_analyzes(self, tmp_path):
        src = tmp_path / "src.py"
        src.write_text("def bar(): pass\n")
        agent = FractalTestStubAgent()
        result = agent.run(project_root=tmp_path, max_depth=3)
        assert result["findings_count"] >= 1
        assert result["fractal_analyzed"] >= 1
        assert any(f["issue"] == "missing_test" for f in result["findings"])


class TestFractalAnalyzerAgent:
    def test_analyzes_finding(self):
        finding = {"issue": "eval() usage", "file": "auth.py"}
        agent = FractalAnalyzerAgent(name="test-analyzer", finding=finding, max_depth=3)
        result = agent.run()
        assert result["finding"] == finding
        assert "fractal_tree" in result
        assert result["fractal_tree"]["level"] == 1
