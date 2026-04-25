from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import cmd_fractal


class DummyNamespace:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestFractalCLI:
    def test_analyze_finds_risks(self, tmp_path: Path, capsys):
        risky = tmp_path / "risky.py"
        risky.write_text("result = eval(user_input)\n")
        args = DummyNamespace(
            subcommand="analyze",
            target=str(tmp_path),
            depth=3,
            json=False,
            max_fractal_budget=None,
        )
        ret = cmd_fractal(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "found" in captured.out.lower()
        assert "Fractal analyzed" in captured.out

    def test_tree_render(self, capsys):
        finding = json.dumps({"issue": "eval() usage", "file": "app/auth.py", "severity": "critical"})
        args = DummyNamespace(
            subcommand="tree",
            finding=finding,
            depth=3,
            target="",
        )
        ret = cmd_fractal(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Level 1" in captured.out
        assert "Level 2" in captured.out

    def test_analyze_json_output(self, tmp_path: Path, capsys):
        risky = tmp_path / "risky.py"
        risky.write_text("eval(x)\n")
        args = DummyNamespace(
            subcommand="analyze",
            target=str(tmp_path),
            depth=2,
            json=True,
            max_fractal_budget=None,
        )
        ret = cmd_fractal(args)
        assert ret == 0
        captured = capsys.readouterr()
        # Find JSON block in output (may span multiple lines)
        out = captured.out
        # JSON starts after the first line break following summary text
        # Find first '{' from the start
        start = out.find("{")
        assert start != -1, f"No JSON in output: {repr(out)}"
        data = json.loads(out[start:])
        assert "findings_count" in data
