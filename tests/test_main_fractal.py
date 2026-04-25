from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.main import _build_swarm_for_plan


class TestMainSwarmFractal:
    def test_build_swarm_plain(self):
        swarm = _build_swarm_for_plan("full_autonomous_loop", use_fractal=False)
        roles = {a.role for a in swarm.registry.agents.values()}
        assert "security_auditor" in roles
        assert "fractal_security_auditor" not in roles

    def test_build_swarm_fractal(self):
        swarm = _build_swarm_for_plan("full_autonomous_loop", use_fractal=True)
        roles = {a.role for a in swarm.registry.agents.values()}
        assert "fractal_security_auditor" in roles
        assert "fractal_documentation_enforcer" in roles
        assert "fractal_test_coverage_analyst" in roles

    def test_main_with_fractal_env(self, tmp_path: Path, monkeypatch, capsys):
        risky = tmp_path / "risky.py"
        risky.write_text("result = eval(user_input)\n")
        monkeypatch.setenv("EPISTEMIC_TARGET_ROOT", str(tmp_path))
        monkeypatch.setenv("EPISTEMIC_AUTOMATION_PLAN", "project_scan")
        monkeypatch.setenv("EPISTEMIC_OBJECTIVE", "security audit")
        monkeypatch.setenv("APEX_USE_FRACTAL", "1")
        monkeypatch.setenv("EPISTEMIC_FOCUS_BRANCH", "")

        from app.main import main
        main()
        captured = capsys.readouterr()
        assert "Fractal deep-analysis enabled" in captured.out
        assert "fractal-report.md" in captured.out

    def test_main_auto_detect_fractal(self, tmp_path: Path, monkeypatch, capsys):
        risky = tmp_path / "risky.py"
        risky.write_text("result = eval(user_input)\n")
        monkeypatch.setenv("EPISTEMIC_TARGET_ROOT", str(tmp_path))
        monkeypatch.setenv("EPISTEMIC_AUTOMATION_PLAN", "project_scan")
        monkeypatch.setenv("EPISTEMIC_OBJECTIVE", "audit security risks")
        monkeypatch.setenv("EPISTEMIC_FOCUS_BRANCH", "")

        from app.main import main
        main()
        captured = capsys.readouterr()
        assert "Fractal deep-analysis enabled" in captured.out
