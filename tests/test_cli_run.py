from __future__ import annotations

import argparse
from pathlib import Path

from app.cli import cmd_run


def test_run_command_report_mode(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("app.cli._get_project_root", lambda: tmp_path)
    args = argparse.Namespace(
        goal="security audit",
        target=str(tmp_path),
        mode="report",
    )
    # app.main.main() will be called; we just verify cmd_run doesn't crash
    import app.main
    original_main = app.main.main
    called = []
    def mock_main():
        called.append(True)
    monkeypatch.setattr(app.main, "main", mock_main)

    result = cmd_run(args)
    assert result == 0
    assert called

    captured = capsys.readouterr()
    assert "report mode" in captured.out.lower()
    assert "security audit" in captured.out.lower()


def test_run_command_supervised_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.cli._get_project_root", lambda: tmp_path)
    args = argparse.Namespace(
        goal="fix docstrings",
        target=str(tmp_path),
        mode="supervised",
    )
    import app.main
    monkeypatch.setattr(app.main, "main", lambda: None)
    result = cmd_run(args)
    assert result == 0


def test_run_command_autonomous_mode(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("app.cli._get_project_root", lambda: tmp_path)
    args = argparse.Namespace(
        goal="autonomous full improvement",
        target=str(tmp_path),
        mode="autonomous",
    )
    import app.main
    monkeypatch.setattr(app.main, "main", lambda: None)
    result = cmd_run(args)
    assert result == 0
    captured = capsys.readouterr()
    assert "autonomous mode" in captured.out.lower()
    assert "full_autonomous_loop" in captured.out
