import importlib
import json
from unittest.mock import patch

from app.tools.external_search import (
    CompositeSearchTool,
    SearchResult,
    TavilySearchProvider,
    WikipediaSearchProvider,
)


class _FakeProvider:
    def __init__(self, name, results, enabled=True, raises=False):
        self._name = name
        self._results = results
        self.enabled = enabled
        self._raises = raises
        self.calls = 0

    def search(self, query, top_k=3):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._results


def _r(title):
    return SearchResult(title=title, snippet="s", source="fake")


# --- Opt-in / off-by-default quarantine guarantees --------------------------

def _boom(*args, **kwargs):
    raise AssertionError("network call attempted (urlopen) — must not happen")


def test_import_and_construction_do_no_network(monkeypatch):
    """Importing the module and building default providers makes no network call.

    Any ``urlopen`` invocation during import/construction is a hard failure,
    protecting Apex's offline / zero-token wedge.
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EPISTEMIC_ENABLE_LIVE_SEARCH", raising=False)
    with patch("urllib.request.urlopen", _boom):
        module = importlib.import_module("app.tools.external_search")
        importlib.reload(module)
        # Default construction must not reach out either.
        module.TavilySearchProvider()
        module.WikipediaSearchProvider()
        module.CompositeSearchTool()


def test_providers_default_disabled_without_explicit_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EPISTEMIC_ENABLE_LIVE_SEARCH", raising=False)
    assert TavilySearchProvider().enabled is False
    assert WikipediaSearchProvider().enabled is False


def test_default_composite_makes_no_network_call(monkeypatch):
    """A default-constructed CompositeSearchTool stays a no-op (offline)."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EPISTEMIC_ENABLE_LIVE_SEARCH", raising=False)
    with patch("urllib.request.urlopen", _boom):
        tool = CompositeSearchTool()
        assert tool.search("anything") == []
        assert tool.last_provider is None


# --- CompositeSearchTool (the engine improvement) ---------------------------

def test_returns_first_nonempty_provider():
    p1 = _FakeProvider("a", [])
    p2 = _FakeProvider("b", [_r("hit")])
    tool = CompositeSearchTool(providers=[p1, p2])
    res = tool.search("q")
    assert [r.title for r in res] == ["hit"]
    assert tool.last_provider == "_FakeProvider"
    assert tool.stats["provider_hits"] == 1


def test_skips_disabled_providers():
    disabled = _FakeProvider("a", [_r("x")], enabled=False)
    enabled = _FakeProvider("b", [_r("y")])
    tool = CompositeSearchTool(providers=[disabled, enabled])
    tool.search("q")
    assert disabled.calls == 0  # never called
    assert enabled.calls == 1


def test_caches_repeated_queries():
    p = _FakeProvider("a", [_r("hit")])
    tool = CompositeSearchTool(providers=[p])
    tool.search("q")
    tool.search("q")  # served from cache
    assert p.calls == 1
    assert tool.stats["cache_hits"] == 1


def test_error_counts_and_continues():
    bad = _FakeProvider("a", [], raises=True)
    good = _FakeProvider("b", [_r("ok")])
    tool = CompositeSearchTool(providers=[bad, good])
    res = tool.search("q")
    assert res[0].title == "ok"
    assert tool.stats["errors"] == 1


def test_all_empty_records_empty():
    tool = CompositeSearchTool(providers=[_FakeProvider("a", [])])
    assert tool.search("q") == []
    assert tool.stats["empty"] == 1
    assert tool.last_provider is None


# --- Providers (network mocked) ---------------------------------------------

def test_tavily_disabled_without_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    p = TavilySearchProvider(api_key=None)
    assert p.enabled is False
    assert p.search("q") == []


def test_tavily_parses_results():
    p = TavilySearchProvider(api_key="k")
    payload = {"results": [{"title": "T", "content": "C" * 500, "url": "http://x"}]}

    class _Resp:
        def read(self):
            return json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", lambda *a, **k: _Resp()):
        res = p.search("q", top_k=1)
    assert res[0].title == "T"
    assert res[0].source == "tavily"
    assert len(res[0].snippet) <= 400


def test_wikipedia_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EPISTEMIC_ENABLE_LIVE_SEARCH", raising=False)
    assert WikipediaSearchProvider().search("q") == []


def test_wikipedia_parses_opensearch(monkeypatch):
    monkeypatch.setenv("EPISTEMIC_ENABLE_LIVE_SEARCH", "1")
    raw = ["q", ["Python"], ["A language"], ["http://wiki/Python"]]

    class _Resp:
        def read(self):
            return json.dumps(raw).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", lambda *a, **k: _Resp()):
        res = WikipediaSearchProvider().search("q", top_k=1)
    assert res[0].title == "Python"
    assert res[0].source == "wikipedia"
