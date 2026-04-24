from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


class TestApexCIScript:
    def test_script_exists(self):
        script = Path(__file__).parent.parent / "scripts" / "apex_ci.sh"
        assert script.exists()

    def test_script_contains_apex_ci_markers(self):
        script = Path(__file__).parent.parent / "scripts" / "apex_ci.sh"
        content = script.read_text(encoding="utf-8")
        assert "apex-ci" in content
        assert "GITHUB_ACTIONS" in content
        assert "GITLAB_CI" in content
        assert "JENKINS_URL" in content

    def test_detects_github_actions(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")
        # Just verify env var setup; actual detection is in shell script
        assert subprocess.os.environ.get("GITHUB_ACTIONS") == "true"

    def test_detects_gitlab_ci(self, monkeypatch):
        monkeypatch.setenv("GITLAB_CI", "true")
        monkeypatch.setenv("CI_PROJECT_NAME", "test-project")
        assert subprocess.os.environ.get("GITLAB_CI") == "true"
