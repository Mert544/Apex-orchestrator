import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.llm.router import (
    LLMRouter,
    OpenAICompatibleProvider,
    OPENAI_COMPATIBLE_PRESETS,
)


@contextmanager
def _fake_urlopen(captured, *, payload=None, error=None):
    """Patch urllib so no real network call happens.

    Records the outgoing Request in ``captured`` and returns ``payload`` as the
    JSON body, or raises ``error`` to simulate a network failure.
    """

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return json.dumps(self._body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _open(req, timeout=None):
        captured["request"] = req
        captured["timeout"] = timeout
        if error is not None:
            raise error
        return _Resp(payload)

    with patch("urllib.request.urlopen", _open):
        yield


_COMPLETION = {
    "model": "openai/gpt-4o-mini",
    "choices": [{"message": {"role": "assistant", "content": "Hello there"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
}


def test_github_preset_builds_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    router = LLMRouter.from_config({"llm": {"provider": "github"}})
    assert isinstance(router.provider, OpenAICompatibleProvider)
    assert router.is_enabled is True
    assert router.provider.base_url == OPENAI_COMPATIBLE_PRESETS["github"]["base_url"]
    assert router.provider.model == OPENAI_COMPATIBLE_PRESETS["github"]["model"]


def test_github_provider_disabled_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    router = LLMRouter.from_config({"llm": {"provider": "github"}})
    assert router.is_enabled is False
    # Disabled provider makes no call and returns empty content.
    assert router.complete("hi").content == ""


def test_complete_parses_response_and_sends_auth(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    router = LLMRouter.from_config({"llm": {"provider": "github"}})
    captured: dict = {}
    with _fake_urlopen(captured, payload=_COMPLETION):
        resp = router.complete("Say hi", system="be terse")

    assert resp.content == "Hello there"
    assert resp.input_tokens == 12
    assert resp.output_tokens == 4

    req = captured["request"]
    assert req.full_url.endswith("/chat/completions")
    assert req.headers["Authorization"] == "Bearer ghp_secret"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["messages"][-1] == {"role": "user", "content": "Say hi"}


def test_network_error_degrades_gracefully(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    router = LLMRouter.from_config({"llm": {"provider": "github"}})
    captured: dict = {}
    with _fake_urlopen(captured, error=OSError("connection refused")):
        resp = router.complete("anything")
    assert resp.content == ""


def test_ollama_preset_is_keyless(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    router = LLMRouter.from_config({"llm": {"provider": "ollama"}})
    assert isinstance(router.provider, OpenAICompatibleProvider)
    # No API key required for a local Ollama endpoint.
    assert router.is_enabled is True
    assert router.provider.api_key == ""


def test_user_config_overrides_preset(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    router = LLMRouter.from_config(
        {"llm": {"provider": "groq", "model": "llama-3.1-8b-instant"}}
    )
    assert router.provider.model == "llama-3.1-8b-instant"
    assert router.is_enabled is True


def test_unknown_provider_still_falls_back_to_none():
    router = LLMRouter.from_config({"llm": {"provider": "does-not-exist"}})
    assert router.is_enabled is False
    assert router.complete("hi").content == ""
