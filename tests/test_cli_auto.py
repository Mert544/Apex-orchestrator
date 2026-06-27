from __future__ import annotations

import argparse
from pathlib import Path

from app.cli import cmd_auto


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=False, allow_weak=False,
        recommend=False, mode=None, commit=False,
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


def test_auto_apply_withholds_uncovered_behaviour_fix(tmp_path, capsys):
    # SAFE-by-default sweep: yaml.load -> safe_load is a Tier-1 BEHAVIOUR change on
    # a module NO test exercises (test_ok.py doesn't import cfg.py), so a green
    # suite can't vouch for it. The covered-only sweep WITHHOLDS it (previewed,
    # not landed) and says how to land it.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, max_apply=3))
    assert rc == 0
    out = capsys.readouterr().out
    # The uncovered behaviour change did NOT land; the message points to --allow-weak.
    assert "yaml.safe_load" not in (tmp_path / "app" / "cfg.py").read_text()
    assert "Withheld" in out and "--allow-weak" in out


def test_auto_apply_allow_weak_lands_uncovered_fix(tmp_path, capsys):
    # --allow-weak restores land-everything: the yaml.load -> safe_load hardening
    # lands even though no test exercises it (the round-21-safe opt-out).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, allow_weak=True, max_apply=3))
    assert rc == 0
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()


def test_auto_apply_upgrades_report_mode(tmp_path, capsys):
    # --apply with an explicit report mode must upgrade to supervised (report
    # can't patch), so a fix still lands. With --allow-weak the uncovered harden
    # lands (covered-only would otherwise withhold it).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc = cmd_auto(_ns(tmp_path, apply=True, allow_weak=True, mode="report", max_apply=2))
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


def _git_project(tmp_path: Path):
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, capture_output=True)


def test_auto_previews_by_default_on_clean_tree(tmp_path, capsys):
    # PREVIEW-by-default (footgun fix): a bare `apex auto` on a CLEAN tree no
    # longer auto-applies — it recommends and tells the user to pass --apply.
    _git_project(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    rc = cmd_auto(_ns(tmp_path, max_apply=2))
    assert rc == 0
    out = capsys.readouterr().out
    assert "apex auto --apply" in out  # the one command to actually act
    # Nothing was written — the clean tree is untouched (no silent edit).
    assert (tmp_path / "app" / "cfg.py").read_text() == before


def test_auto_recommends_on_dirty_tree(tmp_path, capsys):
    # Dirty tree -> Apex declines to auto-edit and recommends instead (now via the
    # preview-by-default gate, which fires before the dirty-tree branch).
    _git_project(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    (tmp_path / "app" / "cfg.py").write_text(before + "x = 1\n")  # uncommitted change
    rc = cmd_auto(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "chose not to apply" in out.lower()
    assert "--apply" in out
    # cfg.py still has the user's edit and was NOT hardened.
    assert "yaml.safe_load" not in (tmp_path / "app" / "cfg.py").read_text()


def test_auto_recommend_flag_forces_no_action_on_clean_tree(tmp_path, capsys):
    _git_project(tmp_path)
    rc = cmd_auto(_ns(tmp_path, recommend=True))
    assert rc == 0
    # Even on a clean tree, --recommend keeps it read-only.
    assert "yaml.safe_load" not in (tmp_path / "app" / "cfg.py").read_text()


def test_auto_writes_out_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    out_file = tmp_path / "auto.md"
    rc = cmd_auto(_ns(tmp_path, apply=True, out=str(out_file), max_apply=2))
    assert rc == 0
    assert out_file.exists() and out_file.read_text().strip()


def test_auto_headline_excludes_fixture_findings_like_the_grade(tmp_path, capsys):
    # Project code is clean; an examples/ fixture carries an intentional eval.
    # The headline must report 0 project findings and disclose the fixture ones
    # separately — one consistent story with the grade.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("def ok():\n    return 1\n")
    (tmp_path / "examples" / "demo").mkdir(parents=True)
    (tmp_path / "examples" / "demo" / "vuln.py").write_text("def run(e):\n    return eval(e)\n")
    rc = cmd_auto(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "0 security finding(s)" in out
    assert "in example/fixture code" in out
