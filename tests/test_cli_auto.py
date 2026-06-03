from __future__ import annotations

import argparse
from pathlib import Path

from app.cli import cmd_auto


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=False, mode=None, commit=False,
        no_verify=False, max_apply=0, json=False, out="",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "app" / "util.py").write_text("def helper():\n    return 1\n")
    return tmp_path


def test_auto_recommend_default_changes_nothing(tmp_path, capsys):
    _project(tmp_path)
    before = (tmp_path / "app" / "svc.py").read_text()
    rc = cmd_auto(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "autonomous review" in out.lower()
    assert "Best next moves" in out
    assert "apex auto --apply" in out  # tells the user the one command to act
    # Recommend mode never writes.
    assert (tmp_path / "app" / "svc.py").read_text() == before


def test_auto_apply_applies_verified_fix(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, max_apply=3))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Applied" in out or "Blocked" in out
    # The yaml.load -> safe_load hardening should have been applied + verified.
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()


def test_auto_apply_upgrades_report_mode(tmp_path, capsys):
    # --apply with an explicit report mode must upgrade to supervised (report
    # can't patch), so a fix still lands.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, mode="report", max_apply=2))
    assert rc == 0
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()


def test_auto_goal_is_surfaced(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_auto(_ns(tmp_path, goal="improve security"))
    assert rc == 0
    assert "improve security" in capsys.readouterr().out


def test_auto_json_apply(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, json=True, max_apply=2))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "applied" in payload and "results" in payload


def test_auto_writes_out_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    out_file = tmp_path / "auto.md"
    rc = cmd_auto(_ns(tmp_path, apply=True, out=str(out_file), max_apply=2))
    assert rc == 0
    assert out_file.exists() and out_file.read_text().strip()
