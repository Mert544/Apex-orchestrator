from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.cli import cmd_review


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(target=str(tmp_path), base="HEAD", fail_on_high=False, json=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def _repo_with_change(tmp_path: Path, new_src: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
              ["git", "config", "user.name", "t"], ["git", "add", "-A"],
              ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=tmp_path, capture_output=True)
    (tmp_path / "app" / "m.py").write_text(new_src)
    return tmp_path


def test_review_reports_changed_issues(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path))
    assert rc == 0
    assert "eval()" in capsys.readouterr().out


def test_review_fail_on_high(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path, fail_on_high=True))
    assert rc == 1  # a high-severity issue is in the diff


def test_review_clean_passes(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\n\ndef ok(x):\n    \"\"\"D.\"\"\"\n    return x\n")
    rc = cmd_review(_ns(tmp_path, fail_on_high=True))
    assert rc == 0


def test_review_json(tmp_path, capsys):
    _repo_with_change(tmp_path, "def base():\n    return 1\n\ndef bad(c=[]):\n    return c\n")
    rc = cmd_review(_ns(tmp_path, json=True))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "findings" in payload and "auto_fixable_count" in payload
