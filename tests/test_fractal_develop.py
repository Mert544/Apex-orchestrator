from __future__ import annotations

from pathlib import Path

from app.engine.fractal_develop import (
    GOAL_TREE,
    available_goals,
    compile_goal,
    render_goal_markdown,
    resolve_goal,
)


def test_reduce_debt_decomposes_to_all_objectives():
    objs = resolve_goal("reduce-debt")
    assert objs == ["modernize", "simplify-bool-return", "remove-dead-code",
                    "dead-params", "remove-unused-imports", "sort-imports",
                    "simplify-comprehension", "merge-isinstance", "collapse-startswith",
                    "dedup", "shrink-functions", "inline-helpers"]


def test_subgoals_decompose():
    assert resolve_goal("tidy") == ["modernize", "simplify-bool-return",
                                    "remove-dead-code", "dead-params",
                                    "remove-unused-imports", "sort-imports",
                                    "simplify-comprehension", "merge-isinstance",
                                    "collapse-startswith"]
    assert resolve_goal("polish") == ["remove-unused-imports", "sort-imports",
                                      "simplify-comprehension"]
    assert resolve_goal("simplify-conditions") == ["merge-isinstance", "collapse-startswith"]
    assert resolve_goal("simplify-structure") == ["dedup", "shrink-functions", "inline-helpers"]


def test_harden_is_a_standalone_test_dimension_goal():
    # `harden` writes missing tests; deliberately NOT reachable from reduce-debt.
    assert resolve_goal("harden") == ["cover-gaps"]
    assert "cover-gaps" not in resolve_goal("reduce-debt")


def test_an_objective_is_a_valid_leaf_goal():
    assert resolve_goal("modernize") == ["modernize"]


def test_unknown_goal_resolves_to_nothing():
    assert resolve_goal("conquer-the-world") == []


def test_resolution_dedups_and_preserves_order():
    # reduce-debt fans out via two sub-goals; no objective appears twice.
    objs = resolve_goal("reduce-debt")
    assert len(objs) == len(set(objs))


def test_goal_tree_leaves_are_real_objectives():
    from app.engine.objective_compiler import available_objectives
    avail = set(available_objectives())
    for goal in GOAL_TREE:
        for obj in resolve_goal(goal):
            assert obj in avail  # the tree can't reference a non-existent objective


def test_available_goals_includes_composites_and_objectives():
    goals = available_goals()
    assert "reduce-debt" in goals and "tidy" in goals and "modernize" in goals


def _multi_debt_project(tmp_path: Path) -> Path:
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


def test_compile_goal_runs_subcampaigns(tmp_path):
    _multi_debt_project(tmp_path)
    gr = compile_goal(str(tmp_path), "reduce-debt", apply=True, verify=False)
    assert gr.objectives  # decomposed
    assert gr.total_moves >= 1  # modernize + dead-params had work
    src = (tmp_path / "app" / "m.py").read_text()
    assert "is None" in src and "return {}" in src and "color" not in src


def test_compile_goal_dry_run_writes_nothing(tmp_path):
    _multi_debt_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    gr = compile_goal(str(tmp_path), "tidy", apply=False)
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert "modernize" in gr.objectives


def test_render_goal_markdown(tmp_path):
    _multi_debt_project(tmp_path)
    md = render_goal_markdown(compile_goal(str(tmp_path), "reduce-debt", apply=True, verify=False))
    assert "Develop goal" in md and "reduce-debt" in md and "Decomposes into" in md


def test_render_unknown_goal():
    from app.engine.fractal_develop import GoalResult
    md = render_goal_markdown(GoalResult(goal="nope", objectives=[]))
    assert "Unknown goal" in md


def test_cmd_develop_goal_flag(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_develop
    _multi_debt_project(tmp_path)
    rc = cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", goal="reduce-debt",
        all_objectives=False, from_dream=False, playbook=False, history=False,
        grade=False, apply=True, max_steps=25, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Develop goal" in out and "Decomposes into" in out
    assert "color" not in (tmp_path / "app" / "m.py").read_text()
