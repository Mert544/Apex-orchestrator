from __future__ import annotations

from pathlib import Path

from app.engine.ascend import (
    AscendReport,
    GoalRanking,
    ascend,
    objective_parent,
    rank_objectives,
    render_ascend_markdown,
    render_plan_markdown,
)


def _debt_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    if text == None:\n        return dict()\n"
        "    return text[:width]\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n"
        "    assert render(None) == {}\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _clean_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import add\ndef test_a():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- ranking ------------------------------------------------------------------

def test_objective_parent_maps_into_tree():
    assert objective_parent("modernize") == "tidy"
    assert objective_parent("dedup") == "simplify-structure"
    assert objective_parent("remove-unused-imports") == "polish"
    # An objective not nested under any goal falls back to its own name.
    assert objective_parent("totally-unknown") == "totally-unknown"


def test_rank_objectives_orders_by_pending_desc(tmp_path):
    _debt_project(tmp_path)
    rankings = rank_objectives(str(tmp_path))
    assert rankings  # every registered objective appears
    pendings = [r.pending for r in rankings]
    assert pendings == sorted(pendings, reverse=True)  # worst first
    # The project has a dead parameter, so that objective carries pending > 0.
    by_name = {r.objective: r.pending for r in rankings}
    assert by_name.get("dead-params", 0) >= 1


def test_rank_objectives_respects_goal_restriction(tmp_path):
    _debt_project(tmp_path)
    rankings = rank_objectives(str(tmp_path), ["dead-params", "modernize"])
    assert {r.objective for r in rankings} == {"dead-params", "modernize"}


def test_rank_objectives_unknown_name_skipped(tmp_path):
    _clean_project(tmp_path)
    rankings = rank_objectives(str(tmp_path), ["modernize", "not-a-real-objective"])
    assert {r.objective for r in rankings} == {"modernize"}


# --- the climb ----------------------------------------------------------------

def test_ascend_climbs_and_proves_grade(tmp_path):
    _debt_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    assert report.applied
    assert report.rounds  # it did at least one round of work
    assert report.total_moves >= 1
    src = (tmp_path / "app" / "m.py").read_text()
    assert "== None" not in src and "color" not in src  # debt developed away
    assert report.grade_end >= report.grade_start  # never regressed the grade


def test_ascend_reaches_fixpoint_on_clean_project(tmp_path):
    _clean_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    assert report.fixpoint is True
    assert report.rounds == []  # nothing to do


def test_ascend_dry_run_changes_nothing(tmp_path):
    _debt_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    report = ascend(str(tmp_path), apply=False)
    assert report.applied is False
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert report.preview  # it reported what it would do


def test_ascend_goal_restriction_only_touches_those_objectives(tmp_path):
    _debt_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, goal="tidy", max_rounds=4)
    # Every round's objective is one of tidy's leaves.
    from app.engine.fractal_develop import resolve_goal
    tidy = set(resolve_goal("tidy"))
    assert all(r.objective in tidy for r in report.rounds)


def test_ascend_records_history(tmp_path):
    _debt_project(tmp_path)
    ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    from app.engine.dev_history import DevHistory
    runs = DevHistory.load(str(tmp_path)).entries()
    assert any(r.objective.startswith("ascend:") for r in runs)


# --- rendering & report -------------------------------------------------------

def test_render_plan_markdown_lists_board(tmp_path):
    _debt_project(tmp_path)
    md = render_plan_markdown(rank_objectives(str(tmp_path)))
    assert "Develop plan" in md and "Pending" in md and "Next move" in md


def test_render_plan_markdown_fixpoint(tmp_path):
    md = render_plan_markdown([GoalRanking("modernize", 0.0, "tidy")])
    assert "fixpoint" in md


def test_render_ascend_markdown_climb(tmp_path):
    _debt_project(tmp_path)
    md = render_ascend_markdown(ascend(str(tmp_path), apply=True, verify=False))
    assert "Ascend" in md and "Health:" in md and "Round" in md


def test_render_ascend_markdown_preview():
    report = AscendReport(applied=False, preview=[GoalRanking("dead-params", 3.0, "tidy")])
    md = render_ascend_markdown(report)
    assert "preview" in md.lower() and "dead-params" in md


def test_ascend_to_dict_round_trips(tmp_path):
    _debt_project(tmp_path)
    d = ascend(str(tmp_path), apply=True, verify=False).to_dict()
    assert "rounds" in d and "grade_delta" in d and d["applied"] is True


# --- CLI ----------------------------------------------------------------------

def test_cmd_plan(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_plan
    _debt_project(tmp_path)
    rc = cmd_plan(argparse.Namespace(target=str(tmp_path), goal="", json=False))
    assert rc == 0
    assert "Develop plan" in capsys.readouterr().out


def test_cmd_ascend_apply(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_ascend
    _debt_project(tmp_path)
    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=True, max_rounds=4, max_steps=25,
        until="", no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ascend" in out
    assert "color" not in (tmp_path / "app" / "m.py").read_text()


def test_cmd_ascend_until_letter(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_ascend
    _debt_project(tmp_path)
    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=True, max_rounds=4, max_steps=25,
        until="A-", no_verify=True, json=False))
    assert rc == 0


def test_target_score_parsing():
    from app.cli_autonomy import _target_score
    assert _target_score("90") == 90
    assert _target_score("A-") == 90
    assert _target_score("b+") == 87
    assert _target_score("") is None
    assert _target_score("nonsense") is None
