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
