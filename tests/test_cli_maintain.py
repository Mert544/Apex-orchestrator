import argparse
import json

from app.cli import cmd_maintain


def _ns(tmp_path, **over):
    base = dict(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=False, out="", dry_run=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_maintain_report_mode_changes_nothing(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "danger.py"
    src.write_text("def run(e):\n    return eval(e)\n")
    rc = cmd_maintain(_ns(tmp_path, mode="report"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Apex Maintenance Report" in out
    # report mode never patches.
    assert src.read_text() == "def run(e):\n    return eval(e)\n"


def test_maintain_supervised_applies_and_reports(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    rc = cmd_maintain(_ns(tmp_path, mode="supervised", json=True))
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert rc == 0
    # Supervised pass applies at least one verified fix and never commits.
    assert summary["applied"] >= 1
    assert summary["commit"] is False
    # COVERED-ONLY DEFAULT: `danger.py` has NO test exercising it, so its
    # `harden_security` fix is a green-but-unreferencing WEAK move — withheld
    # (rolled back), not silently landed. `calc.py`'s covered fixes still land.
    assert summary["rolled_back"] >= 1
    assert summary.get("withheld_uncovered", 0) >= 1
    assert "return eval(e)" in (tmp_path / "app" / "danger.py").read_text()


def test_maintain_supervised_allow_weak_lands_uncovered_fix_too(tmp_path, capsys):
    """``--allow-weak`` restores the historical land-everything behaviour: the
    SAME uncovered `danger.py` fix that the default (covered-only) pass
    withholds now lands, and nothing is rolled back."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    rc = cmd_maintain(_ns(tmp_path, mode="supervised", json=True, allow_weak=True))
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert rc == 0
    assert summary["applied"] >= 1
    assert summary["rolled_back"] == 0
    assert not summary.get("withheld_uncovered")
    assert "return eval(e)" not in (tmp_path / "app" / "danger.py").read_text()
    assert "literal_eval(e)" in (tmp_path / "app" / "danger.py").read_text()


def test_maintain_writes_report_file_and_json(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    out_file = tmp_path / "report.md"
    rc = cmd_maintain(_ns(tmp_path, mode="report", out=str(out_file)))
    assert rc == 0
    assert out_file.exists()
    assert "Apex Maintenance Report" in out_file.read_text()


def test_maintain_dry_run_previews_without_changes(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "danger.py"
    src.write_text("def run(e):\n    return eval(e)\n")
    rc = cmd_maintain(_ns(tmp_path, mode="supervised", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out
    # Nothing on disk changed.
    assert src.read_text() == "def run(e):\n    return eval(e)\n"
