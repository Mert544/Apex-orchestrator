from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    title: str
    snippet: str
    source: str
    url: str = ""


class SearchProvider(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[SearchResult]: ...


class TavilySearchProvider:
    def __init__(self, api_key: str | None = None, timeout: float = 8.0) -> None:
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        if not self.enabled:
            return []

        payload = json.dumps(
            {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": top_k,
                "include_answer": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url="https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

        results: list[SearchResult] = []
        for item in raw.get("results", [])[:top_k]:
            results.append(
                SearchResult(
                    title=item.get("title", "Untitled result"),
                    snippet=item.get("content", "")[:400],
                    source="tavily",
                    url=item.get("url", ""),
                )
            )
        return results


class WikipediaSearchProvider:
    def __init__(self, timeout: float = 6.0) -> None:
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return os.getenv("EPISTEMIC_ENABLE_LIVE_SEARCH", "0") == "1"

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        if not self.enabled:
            return []

        encoded = urllib.parse.quote(query)
        url = (
            "https://en.wikipedia.org/w/api.php?action=opensearch"
            f"&search={encoded}&limit={top_k}&namespace=0&format=json"
        )

        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

        titles = raw[1] if len(raw) > 1 else []
        descriptions = raw[2] if len(raw) > 2 else []
        urls = raw[3] if len(raw) > 3 else []

        results: list[SearchResult] = []
        for idx, title in enumerate(titles[:top_k]):
            snippet = descriptions[idx] if idx < len(descriptions) else ""
            page_url = urls[idx] if idx < len(urls) else ""
            results.append(
                SearchResult(title=title, snippet=snippet, source="wikipedia", url=page_url)
            )
        return results


class CompositeSearchTool:
    """Try providers in order, returning the first non-empty result.

    Improvements over a naive fan-out:
    - **Enabled-only**: providers exposing a falsy ``enabled`` are skipped, so we
      never make a doomed call (and offline-by-default stays truly offline).
    - **Caching**: identical (query, top_k) lookups are memoized, so repeated
      searches during a reasoning run don't re-hit the network.
    - **Observability**: ``last_provider`` and ``stats`` expose hits/misses/
      cache/errors for telemetry and debugging.
    """

    def __init__(self, providers: list[SearchProvider] | None = None) -> None:
        self.providers = providers or [TavilySearchProvider(), WikipediaSearchProvider()]
        self.last_provider: str | None = None
        self._cache: dict[tuple[str, int], list[SearchResult]] = {}
        self.stats = {"calls": 0, "cache_hits": 0, "provider_hits": 0, "errors": 0, "empty": 0}

    @staticmethod
    def _provider_name(provider: SearchProvider) -> str:
        return type(provider).__name__

    @staticmethod
    def _is_enabled(provider: SearchProvider) -> bool:
        # Providers may expose `enabled` as a property; default to True if absent.
        enabled = getattr(provider, "enabled", True)
        return bool(enabled)

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        self.stats["calls"] += 1
        key = (query, top_k)
        if key in self._cache:
            self.stats["cache_hits"] += 1
            return self._cache[key]

        for provider in self.providers:
            if not self._is_enabled(provider):
                continue
            try:
                results = provider.search(query=query, top_k=top_k)
            except Exception:
                self.stats["errors"] += 1
                results = []
            if results:
                self.last_provider = self._provider_name(provider)
                self.stats["provider_hits"] += 1
                self._cache[key] = results
                return results

        self.stats["empty"] += 1
        self.last_provider = None
        self._cache[key] = []
        return []
