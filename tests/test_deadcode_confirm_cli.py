from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_reporting as cli_reporting
from app.engine.runtime_trace import RuntimeEvidence, trace_pytest
from app.reporting.deadcode import find_dead_code, render_dead_code_markdown


def _proj(tmp: Path) -> Path:
    (tmp / "pkg").mkdir()
    (tmp / "pkg" / "__init__.py").write_text("")
    # A private, unreferenced symbol -> a high-confidence dead finding.
    (tmp / "pkg" / "m.py").write_text("def _hidden():\n    return 1\n")
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    return tmp


def test_cmd_deadcode_confirm_annotates_and_renders_runtime_column(tmp_path, capsys, monkeypatch):
    _proj(tmp_path)
    # Hand-built evidence with NO lines for the file -> "static-only" (file
    # never loaded under the traced run). We monkeypatch trace_pytest so no real
    # suite runs; we only test the wiring.
    evidence = RuntimeEvidence(executed=frozenset())
    captured: dict[str, object] = {}

    def fake_trace_pytest(test_path: str, *, root: str | None = None) -> RuntimeEvidence:
        captured["test_path"] = test_path
        captured["root"] = root
        return evidence

    # cmd_deadcode imports trace_pytest lazily from the module; patch the source.
    monkeypatch.setattr(
        "app.engine.runtime_trace.trace_pytest", fake_trace_pytest, raising=True
    )

    args = argparse.Namespace(
        target=str(tmp_path), limit=40, json=False, confirm=True, tests="tests/sub"
    )
    assert cli_reporting.cmd_deadcode(args) == 0
    out = capsys.readouterr().out
    assert "| Runtime |" in out
    assert "Runtime legend" in out
    assert "static-only" in out
    # The user's targeted --tests path and project root were threaded through.
    assert captured["test_path"] == "tests/sub"
    assert captured["root"] == str(tmp_path)


def test_cmd_deadcode_confirm_json_includes_runtime_key(tmp_path, capsys, monkeypatch):
    _proj(tmp_path)
    evidence = RuntimeEvidence(executed=frozenset())

    def fake_trace_pytest(test_path: str, *, root: str | None = None) -> RuntimeEvidence:
        return evidence

    monkeypatch.setattr(
        "app.engine.runtime_trace.trace_pytest", fake_trace_pytest, raising=True
    )
    args = argparse.Namespace(
        target=str(tmp_path), limit=40, json=True, confirm=True, tests="tests"
    )
    assert cli_reporting.cmd_deadcode(args) == 0
    import json

    rows = json.loads(capsys.readouterr().out)
    assert rows and all("runtime" in r for r in rows)


def test_cmd_deadcode_without_confirm_is_byte_identical(tmp_path, capsys):
    _proj(tmp_path)
    # Reference output: the pre-existing renderer over the static-only findings.
    expected = render_dead_code_markdown(find_dead_code(str(tmp_path), limit=40)) + "\n"

    args = argparse.Namespace(
        target=str(tmp_path), limit=40, json=False, confirm=False, tests="tests"
    )
    assert cli_reporting.cmd_deadcode(args) == 0
    out = capsys.readouterr().out
    assert out == expected
    assert "Runtime" not in out


def test_render_without_runtime_key_byte_identical_to_legacy(tmp_path):
    _proj(tmp_path)
    rows = find_dead_code(str(tmp_path), limit=40)
    assert all("runtime" not in r for r in rows)
    md = render_dead_code_markdown(rows)
    # Legacy header / divider, no Runtime column, no legend.
    assert "| Module | Symbol | Kind | Line | Confidence |" in md
    assert "Runtime" not in md
    assert "Runtime legend" not in md


def test_trace_pytest_smoke_traces_one_toy_test(tmp_path):
    # A tiny, self-contained 1-test file traced in-process. Evidence must be
    # non-empty (the toy test's own lines ran) and must record that the file
    # loaded.
    tdir = tmp_path / "tests"
    tdir.mkdir()
    toy = tdir / "test_toy.py"
    toy.write_text(
        "def test_toy():\n"
        "    x = 1 + 1\n"
        "    assert x == 2\n"
    )
    ev = trace_pytest(str(toy))
    assert ev.executed  # something ran
    assert ev.has_evidence_for(str(toy))
    assert ev.was_executed(str(toy), 2)  # the body line executed
