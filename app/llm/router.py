from __future__ import annotations

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


class OpenAICompatibleProvider(LLMProvider):
    """Optional provider for OpenAI-compatible endpoints (OpenAI, DeepSeek, Groq, etc.).

    Only instantiated when user explicitly configures provider=openai.
    Requires: pip install openai (not in default dependencies to keep project lean).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.api_key = config.get("api_key") or ""
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = int(config.get("max_tokens", 2048))
        self.temperature = float(config.get("temperature", 0.2))
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for provider=openai. Install: pip install openai"
            ) from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        client = self._get_client()
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            model=self.model,
        )


class LocalProvider(LLMProvider):
    """Optional provider for local models via HTTP (Ollama, LM Studio, etc.).

    Only instantiated when user explicitly configures provider=local.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434/v1")
        self.model = config.get("model", "llama3")
        self.max_tokens = int(config.get("max_tokens", 2048))
        self.temperature = float(config.get("temperature", 0.2))
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for provider=local. Install: pip install openai"
            ) from exc
        self._client = OpenAI(api_key="local", base_url=self.base_url)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        client = self._get_client()
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            model=self.model,
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    """Provider for DeepSeek models (deepseek-v4, deepseek-chat).

    Uses the OpenAI-compatible API at api.deepseek.com.
    Requires: pip install openai
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__({
            **config,
            "base_url": config.get("base_url", "https://api.deepseek.com/v1"),
            "model": config.get("model", "deepseek-chat"),
        })


class LLMRouter:
    """Routes prompts to configured LLM provider.

    Usage:
        router = LLMRouter.from_config(config)
        response = router.complete("Write a docstring for this function...")
    """

    PROVIDERS: dict[str, type[LLMProvider]] = {
        "none": NoOpProvider,
        "openai": OpenAICompatibleProvider,
        "local": LocalProvider,
        "deepseek": DeepSeekProvider,
    }

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMRouter":
        llm_config = config.get("llm", {})
        provider_name = str(llm_config.get("provider", "none")).lower()
        provider_cls = cls.PROVIDERS.get(provider_name, NoOpProvider)
        provider = provider_cls(llm_config)
        return cls(provider)

    def complete(self, prompt: str, system: str | None = None) -> LLMResponse:
        return self.provider.complete(prompt, system)

    @property
    def is_enabled(self) -> bool:
        return not isinstance(self.provider, NoOpProvider)
