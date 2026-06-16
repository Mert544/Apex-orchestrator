"""Tests for `apex insights` — the combined deterministic analyzer sweep.

Builds a small tmp project (production module + a test module + a debt marker
+ a long function + a magic literal) and drives ``cmd_insights`` in both
Markdown and ``--json`` modes via an ``argparse.Namespace``. Asserts each
analyzer's section / JSON key is present, exit code 0, byte-stable output
(determinism), and that the parser registers the ``insights`` subcommand.

Stdlib-only, offline, no monkeypatching of the analyzers themselves — the whole
point is the real end-to-end wiring over a real (tiny) tree.
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import app.cli_insights as cli_insights

# The fixed analyzer registry — keep this list in lock-step with the module so
# a dropped/renamed analyzer is caught by the section/key assertions below.
ANALYZER_KEYS = [
    "type_hint_coverage",
    "docstring_coverage",
    "complexity_profile",
    "dead_code_scan",
    "todo_debt",
    "test_balance",
    "function_length",
    "api_ergonomics",
    "naming_audit",
    "literal_density",
    "coupling_metrics",
    "cohesion_metrics",
    "exception_hygiene",
    "async_safety",
    "return_consistency",
    "global_state",
    "logging_hygiene",
    "comment_quality",
    "inheritance_depth",
    "config_surface",
]

# The 10 analyzers wired in by this change — asserted to appear everywhere.
NEW_ANALYZER_KEYS = [
    "coupling_metrics",
    "cohesion_metrics",
    "exception_hygiene",
    "async_safety",
    "return_consistency",
    "global_state",
    "logging_hygiene",
    "comment_quality",
    "inheritance_depth",
    "config_surface",
]

SECTION_TITLES = [
    "Type-hint coverage",
    "Docstring coverage",
    "Complexity profile",
    "Dead code",
    "TODO debt",
    "Test balance",
    "Function length",
    "API ergonomics",
    "Naming audit",
    "Literal density",
    "Coupling metrics",
    "Cohesion metrics",
    "Exception hygiene",
    "Async safety",
    "Return consistency",
    "Global state",
    "Logging hygiene",
    "Comment quality",
    "Inheritance depth",
    "Config surface",
]


def _build_project(root: Path) -> None:
    """A tiny but real project: production code with hints/docstrings/debt/a
    long function/a repeated magic literal, plus a matching test module so the
    test-balance analyzer has both sides to weigh."""
    pkg = root / "mypkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # Production module: documented + annotated function, an undocumented one,
    # a TODO marker, a deliberately long function, and a repeated magic number.
    long_body = "\n".join(f"    x{i} = 99 + {i}" for i in range(60))
    (pkg / "core.py").write_text(
        '"""Core module."""\n\n'
        "MAGIC = 99\n\n"
        "def documented(a: int, b: int) -> int:\n"
        '    """Add two numbers."""\n'
        "    return a + b + 99\n\n"
        "def undocumented(a, b):\n"
        "    # TODO: annotate this and add a docstring\n"
        "    return a + b\n\n"
        "def big_function():\n"
        f"{long_body}\n"
        "    return x0\n",
        encoding="utf-8",
    )
    # A second module rigged to trip the newly-wired analyzers: a deep
    # inheritance chain (depth >= 4), a mutable module-level global, a class
    # with two disjoint methods (zero cohesion), a swallowed exception, an
    # async function making a blocking call, an inconsistent-return function,
    # and a block of commented-out code.
    (pkg / "smells.py").write_text(
        '"""Smelly module for the extended analyzer sweep."""\n'
        "import time\n\n"
        "shared_cache = {}\n\n"
        "class A:\n    pass\n\n"
        "class B(A):\n    pass\n\n"
        "class C(B):\n    pass\n\n"
        "class D(C):\n    pass\n\n"
        "class E(D):\n    pass\n\n"
        "class Disjoint:\n"
        "    def first(self):\n        return self.x\n"
        "    def second(self):\n        return self.y\n\n"
        "def swallow():\n"
        "    try:\n        risky()\n    except Exception:\n        pass\n\n"
        "async def blocking():\n"
        "    time.sleep(1)\n\n"
        "def inconsistent(flag):\n"
        "    if flag:\n        return 1\n    return\n\n"
        "def risky():\n"
        "    # x = 1 + 2\n"
        "    # y = x * 3\n"
        "    # return y\n"
        "    return 0\n",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_core.py").write_text(
        "from mypkg.core import documented\n\n"
        "def test_documented():\n"
        "    assert documented(1, 2) == 102\n",
        encoding="utf-8",
    )


def _ns(target: str, *, as_json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(target=target, json=as_json)


def _capture(args: argparse.Namespace) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_insights.cmd_insights(args)
    return rc, buf.getvalue()


# === Markdown mode ======================================================

def test_markdown_has_every_section(tmp_path):
    _build_project(tmp_path)
    rc, out = _capture(_ns(str(tmp_path)))
    assert rc == 0
    assert "# Apex insights" in out
    for title in SECTION_TITLES:
        assert f"## {title}" in out, f"missing section: {title}"


def test_markdown_surfaces_real_signals(tmp_path):
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path)))
    # The TODO marker we planted shows up in the TODO debt section.
    assert "TODO" in out
    # The repeated magic literal 99 is surfaced by literal density.
    assert "99" in out


# === JSON mode ==========================================================

def test_json_has_every_analyzer_key(tmp_path):
    _build_project(tmp_path)
    rc, out = _capture(_ns(str(tmp_path), as_json=True))
    assert rc == 0
    payload = json.loads(out)
    assert "root" in payload
    assert set(payload["analyzers"].keys()) == set(ANALYZER_KEYS)
    # Every analyzer succeeded on this tree (no {"error": ...} entries).
    for key, data in payload["analyzers"].items():
        assert isinstance(data, dict)
        assert "error" not in data, f"{key} failed: {data.get('error')}"


def test_json_carries_expected_metrics(tmp_path):
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path), as_json=True))
    analyzers = json.loads(out)["analyzers"]
    # At least one TODO marker counted.
    assert analyzers["todo_debt"]["total"] >= 1
    # Type-hint coverage has a ratio in [0, 1].
    ratio = analyzers["type_hint_coverage"]["overall_ratio"]
    assert 0.0 <= ratio <= 1.0


# === Determinism ========================================================

def test_markdown_is_deterministic(tmp_path):
    _build_project(tmp_path)
    _, first = _capture(_ns(str(tmp_path)))
    _, second = _capture(_ns(str(tmp_path)))
    assert first == second


def test_json_is_deterministic(tmp_path):
    _build_project(tmp_path)
    _, first = _capture(_ns(str(tmp_path), as_json=True))
    _, second = _capture(_ns(str(tmp_path), as_json=True))
    assert first == second


# === Empty / edge project ==============================================

def test_empty_project_still_renders_all_sections(tmp_path):
    # No source files at all — every analyzer must still produce a section and
    # exit 0 (best-effort, never crash on an empty tree).
    rc, out = _capture(_ns(str(tmp_path)))
    assert rc == 0
    for title in SECTION_TITLES:
        assert f"## {title}" in out


def test_empty_project_json_keys(tmp_path):
    rc, out = _capture(_ns(str(tmp_path), as_json=True))
    assert rc == 0
    assert set(json.loads(out)["analyzers"].keys()) == set(ANALYZER_KEYS)


# === Resilience: a failing analyzer is skipped, not fatal ===============

def test_failing_analyzer_is_skipped(tmp_path, monkeypatch):
    _build_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("synthetic analyzer failure")

    # Break ONE analyzer at its source module; the report must still render
    # the other nine and exit 0, with the broken one noted as an error.
    monkeypatch.setattr("app.tools.naming_audit.analyze_naming", boom)
    rc, out = _capture(_ns(str(tmp_path)))
    assert rc == 0
    assert "## Naming audit" in out
    assert "skipped" in out

    rc_j, out_j = _capture(_ns(str(tmp_path), as_json=True))
    assert rc_j == 0
    assert "error" in json.loads(out_j)["analyzers"]["naming_audit"]


# === Newly-wired analyzers ==============================================

def test_markdown_has_new_sections(tmp_path):
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path)))
    for key in NEW_ANALYZER_KEYS:
        title = {
            "coupling_metrics": "Coupling metrics",
            "cohesion_metrics": "Cohesion metrics",
            "exception_hygiene": "Exception hygiene",
            "async_safety": "Async safety",
            "return_consistency": "Return consistency",
            "global_state": "Global state",
            "logging_hygiene": "Logging hygiene",
            "comment_quality": "Comment quality",
            "inheritance_depth": "Inheritance depth",
            "config_surface": "Config surface",
        }[key]
        assert f"## {title}" in out, f"missing section: {title}"


def test_json_has_new_analyzer_keys(tmp_path):
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path), as_json=True))
    analyzers = json.loads(out)["analyzers"]
    for key in NEW_ANALYZER_KEYS:
        assert key in analyzers, f"missing key: {key}"
        assert "error" not in analyzers[key], f"{key} failed: {analyzers[key]}"


def test_new_analyzers_surface_real_offenders(tmp_path):
    """The rigged fixture must trip the offender lists of several new
    analyzers (proving the EXACT offenders keys are wired correctly)."""
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path), as_json=True))
    analyzers = json.loads(out)["analyzers"]
    # Disjoint-method class -> cohesion offender.
    assert len(analyzers["cohesion_metrics"]["low_cohesion"]) >= 1
    # Mutable module-level dict -> global-state offender.
    assert len(analyzers["global_state"]["mutable_globals"]) >= 1
    # A<B<C<D<E chain -> deep inheritance offender.
    assert len(analyzers["inheritance_depth"]["deep_classes"]) >= 1
    # Swallowed exception -> exception-hygiene offender.
    assert len(analyzers["exception_hygiene"]["offenders"]) >= 1
    # time.sleep in an async def -> blocking call.
    assert len(analyzers["async_safety"]["blocking_calls"]) >= 1
    # Mixed bare/value return -> return-consistency offender.
    assert len(analyzers["return_consistency"]["offenders"]) >= 1
    # Commented-out code block -> comment-quality offender.
    assert len(analyzers["comment_quality"]["commented_out"]) >= 1


def test_generic_offender_render_is_surfaced(tmp_path):
    """A generic offender bullet renders the identifier and salient k=v."""
    _build_project(tmp_path)
    _, out = _capture(_ns(str(tmp_path)))
    # The disjoint class name appears as a generic offender bullet under
    # Cohesion metrics.
    assert "classname=Disjoint" in out


def test_offender_generic_renders_module_and_pairs():
    bullet = cli_insights._offender_generic(
        {"module": "m.py", "function": "f", "line": 9, "reason": "x", "depth": 4}
    )
    assert bullet.startswith("`m.py`")
    # At most three salient pairs, in fixed priority order (function before
    # reason before depth; line is lowest priority and gets dropped here).
    assert bullet == "`m.py` — function=f, reason=x, depth=4"


def test_offender_generic_falls_back_to_key_then_qmark():
    assert cli_insights._offender_generic({"key": "CFG"}) == "`CFG`"
    assert cli_insights._offender_generic({}) == "`?`"


def test_headline_list_counts_and_handles_empty():
    headline = cli_insights._headline_list("xs", "things")
    assert headline({"xs": [1, 2, 3]}) == "3 things"
    assert headline({}) == "0 things"
    assert headline({"xs": None}) == "0 things"


def test_new_analyzers_are_deterministic(tmp_path):
    _build_project(tmp_path)
    _, first = _capture(_ns(str(tmp_path), as_json=True))
    _, second = _capture(_ns(str(tmp_path), as_json=True))
    assert first == second


def test_new_failing_analyzer_is_isolated(tmp_path, monkeypatch):
    _build_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("synthetic cohesion failure")

    monkeypatch.setattr("app.tools.cohesion_metrics.analyze_cohesion", boom)
    rc, out = _capture(_ns(str(tmp_path)))
    assert rc == 0
    assert "## Cohesion metrics" in out
    assert "skipped" in out
    # The other new analyzers still render.
    assert "## Coupling metrics" in out
    assert "## Config surface" in out

    rc_j, out_j = _capture(_ns(str(tmp_path), as_json=True))
    assert rc_j == 0
    analyzers = json.loads(out_j)["analyzers"]
    assert "error" in analyzers["cohesion_metrics"]
    assert "error" not in analyzers["inheritance_depth"]


# === Parser registration ================================================

def test_register_parsers_adds_insights_subcommand():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    cli_insights.register_parsers(subparsers)
    args = parser.parse_args(["insights", "--target", "x", "--json"])
    assert args.command == "insights"
    assert args.target == "x"
    assert args.json is True
    assert args.func is cli_insights.cmd_insights


def test_register_parsers_defaults():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    cli_insights.register_parsers(subparsers)
    args = parser.parse_args(["insights"])
    assert args.target == ""
    assert args.json is False
