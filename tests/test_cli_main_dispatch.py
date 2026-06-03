from __future__ import annotations

import argparse

import pytest

import app.cli as cli


def test_main_no_subcommand_runs_auto(monkeypatch, tmp_path):
    # Bare `apex` (no subcommand) now runs the autonomous review on the project,
    # so users don't have to memorize commands.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return eval(x)\n")
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    captured = {}

    def _fake_auto(args):
        captured["ran"] = args
        return 0

    monkeypatch.setattr(cli, "cmd_auto", _fake_auto)
    monkeypatch.setattr("sys.argv", ["apex"])
    assert cli.main() == 0
    assert "ran" in captured  # dispatched to the autonomous review


def test_main_dispatches_to_func(monkeypatch):
    # A subcommand with a light handler exercises the dispatch tail (args.func).
    monkeypatch.setattr("sys.argv", ["apex", "plugin", "list"])
    calls = []
    monkeypatch.setattr(cli, "cmd_plugin_list", lambda args: calls.append(args) or 0)
    rc = cli.main()
    assert rc == 0
    assert calls


def test_main_unknown_subcommand_exits(monkeypatch):
    monkeypatch.setattr("sys.argv", ["apex", "definitely-not-a-command"])
    with pytest.raises(SystemExit):
        cli.main()


def test_main_ideate_wires_args(monkeypatch, tmp_path):
    # End-to-end through argparse into cmd_ideate (captured), proving the
    # ideate subparser builds the namespace the handler expects.
    monkeypatch.setattr(
        "sys.argv",
        ["apex", "ideate", "--target", str(tmp_path), "--depth", "1", "--breadth", "2"],
    )
    seen = {}

    def fake_ideate(args: argparse.Namespace) -> int:
        seen["target"] = args.target
        seen["depth"] = args.depth
        seen["breadth"] = args.breadth
        return 0

    monkeypatch.setattr(cli, "cmd_ideate", fake_ideate)
    assert cli.main() == 0
    assert seen["target"] == str(tmp_path)
    assert seen["depth"] == 1
    assert seen["breadth"] == 2
