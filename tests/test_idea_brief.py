"""Work briefs: design-level ideas become actionable engineering briefs."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.engine.idea_brief import build_brief, render_brief_markdown
from app.engine.idea_permutation import IdeaPermutationEngine


def _hub_project(tmp_path: Path) -> Path:
    # core.py is a dependency hub (3 importers) -> a design-level "evolve" idea.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def shared(x):\n    return x * 2\n")
    for name in ("a", "b", "c"):
        (tmp_path / "app" / f"{name}.py").write_text(
            f"from app.core import shared\n\ndef {name}(v):\n    return shared(v)\n")
    return tmp_path


def _report(tmp_path: Path):
    return IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 1, "breadth": 3}, tmp_path
    ).run()


def test_brief_defaults_to_top_design_level_idea(tmp_path):
    _hub_project(tmp_path)
    brief = build_brief(_report(tmp_path))
    assert brief is not None
    # Grounded: the why cites the seeding fact verbatim.
    assert any(":" in w for w in brief.why)
    # Measured context comes from the tree's attached stats.
    assert brief.measured.get("loc")
    # The fractal vocabulary is the work plan: aspects with sub-concerns.
    assert brief.plan and all(concerns for _a, concerns in brief.plan)
    # Done-when includes the engine's own confirmation loop.
    assert any("--roadmap --diff" in d for d in brief.done_when)


def test_brief_for_specific_branch(tmp_path):
    _hub_project(tmp_path)
    report = _report(tmp_path)
    target = next(i for i in report.ideas if i.operator == "root")
    brief = build_brief(report, branch_path=target.branch_path)
    assert brief is not None and brief.branch_path == target.branch_path


def test_brief_markdown_reads_as_a_work_order(tmp_path):
    _hub_project(tmp_path)
    brief = build_brief(_report(tmp_path))
    md = render_brief_markdown(brief)
    assert md.startswith("# Work brief — ")
    assert "## Why this, why now" in md
    assert "## Work plan (the fractal vocabulary as a checklist)" in md
    assert "- [ ] " in md                      # actionable checkboxes
    assert "## Definition of done — the engine verifies it" in md


def test_brief_none_when_no_ideas():
    from app.models.idea import IdeaTreeReport

    assert build_brief(IdeaTreeReport(objective="", ideas=[], stats={})) is None


def test_cli_brief_renders(tmp_path, capsys):
    from app.cli import cmd_brief

    _hub_project(tmp_path)
    ns = argparse.Namespace(branch="", target=str(tmp_path), objective="",
                            depth=1, breadth=3, max_ideas=30, json=False)
    assert cmd_brief(ns) == 0
    out = capsys.readouterr().out
    assert "# Work brief — " in out and "- [ ] " in out


def _risky_hub(tmp_path: Path) -> Path:
    # A hub whose code carries REAL evidence for harden-lens concerns.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url):\n"
        "    try:\n"
        "        return url\n"
        "    except:\n"            # bare except -> 'error handling' evidence
        "        return None\n"
    )
    for name in ("a", "b", "c"):
        (tmp_path / "app" / f"{name}.py").write_text(
            f"from app.core import fetch\n\ndef {name}(v):\n    return fetch(v)\n")
    return tmp_path


def test_brief_binds_evidence_to_checklist_items(tmp_path):
    _risky_hub(tmp_path)
    report = _report(tmp_path)
    target = next(i for i in report.ideas
                  if i.operator == "root" and i.subject == "app/core.py")
    from app.engine.idea_brief import build_brief

    brief = build_brief(report, branch_path=target.branch_path)
    # At least one phrase found real evidence in the subject's code.
    assert brief.evidence, "expected evidence-bound items on a risky subject"
    md = __import__("app.engine.idea_brief", fromlist=["render_brief_markdown"])\
        .render_brief_markdown(brief)
    assert "📌 line" in md  # the pin shows in the work order


def test_burndown_resolves_items_when_evidence_vanishes(tmp_path):
    from app.engine.idea_brief import build_brief, check_brief, save_brief

    _risky_hub(tmp_path)
    report = _report(tmp_path)
    target = next(i for i in report.ideas
                  if i.operator == "root" and i.subject == "app/core.py")
    brief = build_brief(report, branch_path=target.branch_path)
    assert brief.evidence
    save_brief(brief, tmp_path)

    # Before any fix: every measured item is still open.
    before = check_brief(tmp_path, brief.branch_path)
    assert before["measured_total"] >= 1 and before["resolved"] == []

    # Fix the code (the bare except becomes specific) -> evidence vanishes.
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url):\n"
        "    try:\n"
        "        return url\n"
        "    except ValueError:\n"
        "        return None\n"
    )
    after = check_brief(tmp_path, brief.branch_path)
    assert len(after["resolved"]) >= 1
    assert len(after["open"]) < before["measured_total"] or after["open"] == []
    from app.engine.idea_brief import render_check_markdown

    md = render_check_markdown(after)
    assert "- [x] " in md and "evidence gone" in md
    assert "the scan decided, not a checkbox" in md


def test_check_without_saved_brief_returns_none(tmp_path):
    from app.engine.idea_brief import check_brief

    assert check_brief(tmp_path, "x.zz") is None


def test_cli_brief_save_then_check(tmp_path, capsys):
    from app.cli import cmd_brief

    _risky_hub(tmp_path)
    ns = argparse.Namespace(branch="", target=str(tmp_path), objective="",
                            depth=1, breadth=3, max_ideas=30, json=False,
                            save=True, check=False)
    assert cmd_brief(ns) == 0
    out = capsys.readouterr().out
    assert "Evidence baseline saved" in out
    import re
    branch = re.search(r"apex brief (\S+) --check", out).group(1)

    ns2 = argparse.Namespace(branch=branch, target=str(tmp_path), objective="",
                             depth=1, breadth=3, max_ideas=30, json=False,
                             save=False, check=True)
    assert cmd_brief(ns2) == 0
    assert "Brief burndown" in capsys.readouterr().out
