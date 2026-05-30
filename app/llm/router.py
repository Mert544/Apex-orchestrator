from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
        }


class LLMProvider:
    """Abstract base for LLM providers."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        """Whether this provider is ready to make real calls."""
        return True


class NoOpProvider(LLMProvider):
    """Default provider: does nothing, returns empty response.

    This preserves full autonomy — no external API calls.
    """

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        return LLMResponse(
            content="",
            input_tokens=0,
            output_tokens=0,
            model="none",
        )

    @property
    def enabled(self) -> bool:
        return False


# Free / low-cost OpenAI-compatible endpoints. Pick one via `llm.provider`.
# All are reachable through the same OpenAICompatibleProvider below, so no
# extra dependency is needed — only the Python standard library.
OPENAI_COMPATIBLE_PRESETS: dict[str, dict[str, str]] = {
    # GitHub Models — free for developers/students with a GitHub account.
    # Create a token with the `models:read` permission and export it as
    # GITHUB_TOKEN (or GITHUB_MODELS_TOKEN).
    "github": {
        "base_url": "https://models.github.ai/inference",
        "model": "openai/gpt-4o-mini",
        "api_key_env": "GITHUB_TOKEN",
    },
    # Groq — generous free tier, no credit card, very fast.
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    # Google Gemini via its OpenAI-compatible endpoint — free tier.
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "api_key_env": "GEMINI_API_KEY",
    },
    # OpenRouter — exposes several `:free` models.
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    # Ollama — fully local, no API key, no network egress.
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key_env": "",
    },
}


class OpenAICompatibleProvider(LLMProvider):
    """Call any OpenAI-compatible /chat/completions endpoint.

    Uses only the Python standard library (urllib) so the project keeps its
    zero-dependency promise. Works with GitHub Models, Groq, Google Gemini,
    OpenRouter, a local Ollama server, or OpenAI itself.

    Config keys (all optional unless noted):
        base_url:     endpoint root, e.g. https://models.github.ai/inference
        model:        model id, e.g. openai/gpt-4o-mini
        api_key:      key/token (prefer api_key_env so secrets stay out of files)
        api_key_env:  name of the env var holding the key, e.g. GITHUB_TOKEN
        timeout:      request timeout in seconds (default 60)
        max_tokens:   max completion tokens (default 1024)
        temperature:  sampling temperature (default 0.2)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.model = str(config.get("model", ""))
        self._key_env = str(config.get("api_key_env", "") or "")
        key = str(config.get("api_key", "") or "")
        if not key and self._key_env:
            key = os.environ.get(self._key_env, "")
        self.api_key = key
        # A provider that declares no key env (e.g. Ollama) needs no key.
        self._keyless = self._key_env == ""
        self.timeout = float(config.get("timeout", 60))
        self.max_tokens = int(config.get("max_tokens", 1024))
        self.temperature = float(config.get("temperature", 0.2))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url) and bool(self.model) and (
            bool(self.api_key) or self._keyless
        )

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        if not self.enabled:
            return LLMResponse(content="", model=self.model)

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
        ).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Graceful degradation: callers fall back to deterministic logic.
            return LLMResponse(content="", model=self.model)

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        content = ""
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content", "") or ""
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            model=str(data.get("model", self.model)),
        )


class LLMRouter:
    """Routes prompts to configured LLM provider.

    Usage:
        router = LLMRouter.from_config(config)
        response = router.complete("Write a docstring for this function...")
    """

    PROVIDERS: dict[str, type[LLMProvider]] = {
        "none": NoOpProvider,
    }

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMRouter":
        llm_config = dict(config.get("llm", {}))
        provider_name = str(llm_config.get("provider", "none")).lower()

        # Named preset for a free/low-cost OpenAI-compatible endpoint.
        preset = OPENAI_COMPATIBLE_PRESETS.get(provider_name)
        if preset is not None:
            # User config overrides preset defaults (model, base_url, key, ...).
            merged = {**preset, **{k: v for k, v in llm_config.items() if v != ""}}
            return cls(OpenAICompatibleProvider(merged))

        provider_cls = cls.PROVIDERS.get(provider_name, NoOpProvider)
        return cls(provider_cls(llm_config))

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        return self.provider.complete(prompt, system)

    @property
    def is_enabled(self) -> bool:
        return self.provider.enabled
