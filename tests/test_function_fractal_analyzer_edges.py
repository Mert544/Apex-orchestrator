"""Edge/error-path coverage for the function-fractal analyzer.

These tests pin the early-return and skip branches the existing suites leave
open: the AST-cache ``stat``/parse failure returns, ``analyze_file`` on an
unparseable file, the ``input()`` risk path, the call-graph cache hit, the
``max_files`` truncation, the per-file parse-skip in ``build_call_graph``, the
plain ``import`` collector, the class-method qualified-name branch, the
cross-file-impact ``analyze_file`` exception guard, and the attribute-call
fall-through in ``_resolve_call``.

All inputs are explicit synthetic sources written under ``tmp_path``; nothing
asserts on time, randomness, or unordered iteration order.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- _get_cached_ast: stat() failure on a missing path ---------------------

def test_get_cached_ast_returns_none_on_missing_file(tmp_path: Path):
    # No file at the path -> path.stat() raises OSError -> None.
    analyzer = FunctionFractalAnalyzer()
    assert analyzer._get_cached_ast(tmp_path / "nope.py") is None


# --- _get_cached_ast: unparseable source -----------------------------------

def test_get_cached_ast_returns_none_on_syntax_error(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")
    analyzer = FunctionFractalAnalyzer()
    assert analyzer._get_cached_ast(bad) is None


# --- analyze_file: parse failure yields an empty result list ---------------

def test_analyze_file_returns_empty_on_unparseable_file(tmp_path: Path):
    bad = tmp_path / "broken.py"
    bad.write_text("def (oops\n", encoding="utf-8")
    assert FunctionFractalAnalyzer().analyze_file(bad) == []


# --- _analyze_function: input() flagged as a Python-2-style risk ------------

def test_input_call_is_flagged_as_risk(tmp_path: Path):
    mod = tmp_path / "app" / "uses_input.py"
    _write(mod, "def grab():\n    return input('name: ')\n")
    results = FunctionFractalAnalyzer().analyze_file(mod)
    fn = next(r for r in results if r["name"] == "grab")
    assert any("input()" in r for r in fn["risks"])
    assert fn["risk_score"] >= 0.3


# --- build_call_graph: cache hit returns the same graph object --------------

def test_build_call_graph_uses_cache_on_second_call(tmp_path: Path):
    _write(tmp_path / "app" / "m.py", "def f():\n    return 1\n")
    analyzer = FunctionFractalAnalyzer()
    first = analyzer.build_call_graph(tmp_path / "app")
    second = analyzer.build_call_graph(tmp_path / "app")
    # Same cached object is returned (cache key matched), not a fresh rebuild.
    assert first is second


# --- build_call_graph: max_files caps how many files are graphed -----------

def test_build_call_graph_respects_max_files(tmp_path: Path):
    for i in range(4):
        _write(tmp_path / "app" / f"m{i}.py", f"def f{i}():\n    return {i}\n")
    analyzer = FunctionFractalAnalyzer(max_files=1)
    graph = analyzer.build_call_graph(tmp_path / "app")
    # Exactly one file's worth of functions made it into the graph.
    files = {info["file"] for info in graph.values()}
    assert len(files) == 1


# --- build_call_graph: an unparseable file is skipped (continue) -----------

def test_build_call_graph_skips_unparseable_file(tmp_path: Path):
    _write(tmp_path / "app" / "good.py", "def g():\n    return 1\n")
    _write(tmp_path / "app" / "bad.py", "def (broken\n")
    graph = FunctionFractalAnalyzer().build_call_graph(tmp_path / "app")
    assert "app.good::g" in graph
    assert not any("bad" in key for key in graph)


# --- build_call_graph: plain `import x` import statement is collected -------

def test_build_call_graph_handles_plain_import(tmp_path: Path):
    # A bare ``import`` (not ``from ... import``) exercises the Import branch of
    # the import collector; the module still graphs cleanly.
    _write(
        tmp_path / "app" / "p.py",
        "import os\n"
        "def f():\n"
        "    return os.getcwd()\n",
    )
    graph = FunctionFractalAnalyzer().build_call_graph(tmp_path / "app")
    assert "app.p::f" in graph


# --- build_call_graph: methods get class-qualified names -------------------

def test_build_call_graph_qualifies_method_names(tmp_path: Path):
    _write(
        tmp_path / "app" / "c.py",
        "class Widget:\n"
        "    def render(self):\n"
        "        return 1\n",
    )
    graph = FunctionFractalAnalyzer().build_call_graph(tmp_path / "app")
    assert "app.c::Widget.render" in graph


# --- compute_cross_file_impact: analyze_file raising is swallowed ----------

def test_cross_file_impact_skips_file_when_analyze_raises(tmp_path: Path, monkeypatch):
    _write(tmp_path / "app" / "r.py", "def risky():\n    eval('1')\n")
    analyzer = FunctionFractalAnalyzer()

    def boom(_file_path):
        raise RuntimeError("analysis blew up")

    monkeypatch.setattr(analyzer, "analyze_file", boom)
    # Every file raises in analyze_file -> the except/continue guard fires for
    # each entry and the impact map ends up empty (no crash).
    impact = analyzer.compute_cross_file_impact(tmp_path / "app")
    assert impact == {}


# --- _resolve_call: an attribute call resolves to None ---------------------

def test_resolve_call_attribute_returns_none():
    analyzer = FunctionFractalAnalyzer()
    call = ast.parse("obj.method()", mode="eval").body
    resolved = analyzer._resolve_call(call, {}, "app.mod", {})
    assert resolved is None
