import json
from unittest.mock import patch

from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _make_orchestrator(llm_config=None):
    config = {
        "max_depth": 2,
        "max_total_nodes": 10,
        "top_k_questions": 2,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    }
    if llm_config is not None:
        config["llm"] = llm_config
    return FractalResearchOrchestrator(
        config=config,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return json.dumps(self._body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_run_without_llm_has_no_summary():
    """Default (no LLM) stays deterministic and offline."""
    orchestrator = _make_orchestrator()
    report = orchestrator.run("Test objective")
    assert report.llm_summary == ""


def test_run_with_github_models_attaches_summary(monkeypatch):
    """End-to-end: orchestrator -> adapter -> router -> (mocked) GitHub Models."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls = {"n": 0}

    completion = {
        "model": "openai/gpt-4o-mini",
        "choices": [
            {"message": {"content": "- Finding A\n- Finding B\n- Finding C"}}
        ],
        "usage": {"prompt_tokens": 30, "completion_tokens": 12},
    }

    def _open(req, timeout=None):
        calls["n"] += 1
        # confirm it really hit the GitHub Models endpoint with auth
        assert req.full_url.endswith("/chat/completions")
        assert req.headers["Authorization"] == "Bearer ghp_test"
        return _FakeResp(completion)

    orchestrator = _make_orchestrator(llm_config={"provider": "github"})
    assert orchestrator.llm.is_enabled is True

    with patch("urllib.request.urlopen", _open):
        report = orchestrator.run("Investigate the CI setup")

    assert calls["n"] >= 1
    assert report.llm_summary == "- Finding A\n- Finding B\n- Finding C"


def test_run_with_llm_error_degrades_gracefully(monkeypatch):
    """A provider/network failure must not break the run."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    def _boom(req, timeout=None):
        raise OSError("connection refused")

    orchestrator = _make_orchestrator(llm_config={"provider": "github"})
    with patch("urllib.request.urlopen", _boom):
        report = orchestrator.run("Investigate the CI setup")

    # Run still completes; summary just stays empty.
    assert report.llm_summary == ""
    assert len(report.main_findings) >= 1
