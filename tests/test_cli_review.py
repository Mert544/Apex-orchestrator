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


def test_impact_command(tmp_path, capsys):
    import argparse
    from app.cli import cmd_impact
    (tmp_path / "m.py").write_text("def core():\n    return 1\n\ndef caller():\n    return core()\n")
    rc = cmd_impact(argparse.Namespace(function="core", target=str(tmp_path), json=False))
    assert rc == 0
    assert "Impact of changing `core()`" in capsys.readouterr().out


def test_impact_command_json(tmp_path, capsys):
    import argparse
    import json
    from app.cli import cmd_impact
    (tmp_path / "m.py").write_text("def core():\n    return 1\n\ndef caller():\n    return core()\n")
    rc = cmd_impact(argparse.Namespace(function="core", target=str(tmp_path), json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["function"] == "core" and "blast_radius" in payload


def test_review_fix_applies_verified_fixes(tmp_path, capsys):
    # apex review --fix applies the auto-fixable findings on the changed files
    # (test-verified) and reports them.
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import base\ndef test_b():\n    assert base() == 1\n"
    )
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
              ["git", "config", "user.name", "t"], ["git", "add", "-A"],
              ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=tmp_path, capture_output=True)
    (tmp_path / "app" / "m.py").write_text(
        "def base():\n    return 1\n\ndef risky(c, o=[]):\n    if c == None:\n        return 0\n    return eval(c)\n"
    )
    rc = cmd_review(_ns(tmp_path, fix=True))
    assert rc == 0  # findings present but --fix is not gated by --fail-on-high here
    out = capsys.readouterr().out
    assert "Applied" in out and "fix(es)" in out
    fixed = (tmp_path / "app" / "m.py").read_text()
    assert "ast.literal_eval(c)" in fixed   # eval fixed
    assert "o=None" in fixed                # mutable default fixed
    assert "c is None" in fixed             # modernized


def test_review_fix_shields_uncovered_file(tmp_path, capsys):
    # review --fix now runs through the same guarded pass as apex maintain:
    # an eval fix on a file NO test references gets a shield test first.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    (tmp_path / "tests" / "test_other.py").write_text("def test_o():\n    assert True\n")
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
              ["git", "config", "user.name", "t"], ["git", "add", "-A"],
              ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=tmp_path, capture_output=True)
    (tmp_path / "app" / "m.py").write_text(
        "def base():\n    return 1\n\ndef risky(c):\n    return eval(c)\n")
    rc = cmd_review(_ns(tmp_path, fix=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "🛡️ shielded first by `tests/test_m.py`" in out
    assert (tmp_path / "tests" / "test_m.py").exists()
    assert "ast.literal_eval(c)" in (tmp_path / "app" / "m.py").read_text()
