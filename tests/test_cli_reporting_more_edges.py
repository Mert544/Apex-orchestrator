"""Edge-path coverage for app.cli_reporting cmd_* functions.

Deterministic, stdlib-only, no network. Heavy builders (dashboard, city,
hotspots, fractal agents) are monkeypatched so tests stay fast. The
deadcode `--confirm` path is intentionally NOT triggered here.
"""

from __future__ import annotations

import argparse
import json

import app.cli_reporting as cli_reporting


# --- cmd_debug trace: JSON branch ---------------------------------------

def test_cmd_debug_trace_json_output(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\n")
    args = argparse.Namespace(subcommand="trace", target=str(tmp_path), json=True)
    assert cli_reporting.cmd_debug(args) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert "trace_count" in report


# --- cmd_dashboard ------------------------------------------------------

def test_cmd_dashboard_default_out(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.reporting.dashboard.build_dashboard", lambda *a, **k: "<html>ok</html>")
    args = argparse.Namespace(
        target=str(tmp_path), objective="", max_ideas=5, depth=2, breadth=3, out=""
    )
    assert cli_reporting.cmd_dashboard(args) == 0
    out_path = tmp_path / ".apex" / "dashboard.html"
    assert out_path.read_text() == "<html>ok</html>"
    assert "[dashboard] Written to" in capsys.readouterr().out


def test_cmd_dashboard_explicit_out_and_objective(monkeypatch, tmp_path):
    captured = {}

    def fake_build(target, *, objective, max_ideas, idea_depth, breadth):
        captured["objective"] = objective
        return "<html>x</html>"

    monkeypatch.setattr("app.reporting.dashboard.build_dashboard", fake_build)
    dest = tmp_path / "nested" / "dash.html"
    args = argparse.Namespace(
        target=str(tmp_path), objective="security", max_ideas=5, depth=2, breadth=3, out=str(dest)
    )
    assert cli_reporting.cmd_dashboard(args) == 0
    assert dest.read_text() == "<html>x</html>"
    assert captured["objective"] == "security"


# --- cmd_hotspots -------------------------------------------------------

def test_cmd_hotspots_markdown(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.reporting.hotspots.build_hotspots", lambda target, limit: [{"module": "m"}])
    monkeypatch.setattr("app.reporting.hotspots.render_hotspots_markdown", lambda rows: "## Hotspots")
    args = argparse.Namespace(target=str(tmp_path), limit=15, json=False)
    assert cli_reporting.cmd_hotspots(args) == 0
    assert "## Hotspots" in capsys.readouterr().out


def test_cmd_hotspots_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.reporting.hotspots.build_hotspots", lambda target, limit: [{"module": "m"}])
    args = argparse.Namespace(target=str(tmp_path), limit=15, json=True)
    assert cli_reporting.cmd_hotspots(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows == [{"module": "m"}]


# --- cmd_city -----------------------------------------------------------

def test_cmd_city_default_out(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.reporting.city_dashboard.build_city", lambda target: "<html>city</html>")
    args = argparse.Namespace(target=str(tmp_path), out="")
    assert cli_reporting.cmd_city(args) == 0
    assert (tmp_path / ".apex" / "city.html").read_text() == "<html>city</html>"
    assert "[city] Written to" in capsys.readouterr().out


def test_cmd_city_explicit_out(monkeypatch, tmp_path):
    monkeypatch.setattr("app.reporting.city_dashboard.build_city", lambda target: "<html>c</html>")
    dest = tmp_path / "out" / "city.html"
    args = argparse.Namespace(target=str(tmp_path), out=str(dest))
    assert cli_reporting.cmd_city(args) == 0
    assert dest.read_text() == "<html>c</html>"


# --- cmd_report: sarif / invalid JSON / unknown format ------------------

def test_cmd_report_sarif(tmp_path):
    data = {"results": [{"agent": "sec", "findings": []}]}
    inp = tmp_path / "run.json"
    inp.write_text(json.dumps(data))
    out = tmp_path / "report.sarif"
    args = argparse.Namespace(input=str(inp), format="sarif", output=str(out))
    assert cli_reporting.cmd_report(args) == 0
    assert out.exists()


def test_cmd_report_invalid_json(tmp_path, capsys):
    inp = tmp_path / "bad.json"
    inp.write_text("{not valid json")
    args = argparse.Namespace(input=str(inp), format="markdown", output=str(tmp_path / "o.md"))
    assert cli_reporting.cmd_report(args) == 1
    assert "Invalid JSON" in capsys.readouterr().out


def test_cmd_report_unknown_format(tmp_path, capsys):
    inp = tmp_path / "run.json"
    inp.write_text(json.dumps({"results": []}))
    args = argparse.Namespace(input=str(inp), format="xml", output=str(tmp_path / "o.xml"))
    assert cli_reporting.cmd_report(args) == 1
    assert "Unknown format" in capsys.readouterr().out


# --- cmd_fractal analyze: JSON branch -----------------------------------

def test_cmd_fractal_analyze_json(monkeypatch, tmp_path, capsys):
    class FakeAgent:
        max_fractal_budget = 10

        def run(self, *, project_root, max_depth):
            return {"scanned_files": 1, "findings_count": 0, "fractal_analyzed": 0}

    monkeypatch.setattr("app.agents.fractal_agents.FractalSecurityAgent", FakeAgent)
    args = argparse.Namespace(
        subcommand="analyze", target=str(tmp_path), depth=2, json=True, max_fractal_budget=3
    )
    assert cli_reporting.cmd_fractal(args) == 0
    out = capsys.readouterr().out
    start = out.find("{")
    data = json.loads(out[start:])
    assert data["scanned_files"] == 1


# --- cmd_deadcode WITHOUT --confirm (no trace_pytest) -------------------

def test_cmd_deadcode_json_without_confirm(tmp_path, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text("def _hidden():\n    return 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    args = argparse.Namespace(
        target=str(tmp_path), limit=40, json=True, confirm=False, tests="tests"
    )
    assert cli_reporting.cmd_deadcode(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
