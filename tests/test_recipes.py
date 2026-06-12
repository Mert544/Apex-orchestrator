"""Recipes: the catalog named, described, and composable."""

from __future__ import annotations

import argparse

from app.execution.recipes import (
    COMPOSITES,
    RECIPES,
    filter_plan,
    recipe_actions,
    render_recipes_markdown,
)
from app.models.idea import ActionPlan, ActionStep


def test_every_recipe_carries_metadata_and_a_tier():
    for r in RECIPES.values():
        assert r.description and r.tags
        assert r.tier in (0, 1)  # executables are never design-tier


def test_composites_only_reference_known_recipes():
    for name, parts in COMPOSITES.items():
        assert parts, name
        for p in parts:
            assert p in RECIPES, f"{name} references unknown recipe {p}"


def test_recipe_actions_resolution():
    assert recipe_actions("harden_security") == {"harden_security"}
    assert recipe_actions("modernize") == {
        "modernize_comparisons", "organize_imports", "fix_mutable_defaults"}
    assert recipe_actions("nope") is None


def _plan() -> ActionPlan:
    steps = [
        ActionStep(branch_path="a", title="t", operator="harden",
                   subject="m.py", action_type="harden_security",
                   target="m.py", executable=True),
        ActionStep(branch_path="b", title="t", operator="document",
                   subject="m.py", action_type="add_docstring",
                   target="m.py", executable=True),
        ActionStep(branch_path="c", title="t", operator="extend",
                   subject="m.py", action_type="design_task",
                   target="m.py", executable=False),
    ]
    return ActionPlan(objective="", steps=steps)


def test_filter_plan_scopes_executables_keeps_design_thinking():
    plan = _plan()
    remaining = filter_plan(plan, "safety-net")
    assert remaining == 1
    kinds = [(s.action_type, s.executable) for s in plan.steps]
    assert ("add_docstring", True) in kinds
    assert ("design_task", False) in kinds      # thinking is never hidden
    assert ("harden_security", True) not in kinds


def test_filter_plan_unknown_recipe_fails_loudly():
    import pytest

    with pytest.raises(ValueError, match="known:"):
        filter_plan(_plan(), "tpyo")


def test_render_lists_singles_and_composites():
    md = render_recipes_markdown()
    assert "| `harden_security` | single |" in md
    assert "| `modernize` | composite |" in md
    assert "apex maintain --recipe modernize" in md


def test_cli_maintain_recipe_scopes_the_pass(tmp_path, capsys):
    from app.cli import cmd_maintain

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # One modernize target + one security target.
    (tmp_path / "app" / "old.py").write_text(
        "def f(x):\n    if x == None:\n        return 0\n    return x\n")
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    # old.py gets a covering test so the 'untested' seed doesn't claim its
    # subject — the modernization seed must own it for this scenario.
    (tmp_path / "tests" / "test_old.py").write_text(
        "from app.old import f\ndef test_f():\n    assert f(None) == 0\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    ns = argparse.Namespace(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=False, out="", dry_run=False, proof="", recipe="modernize")
    assert cmd_maintain(ns) == 0
    out = capsys.readouterr().out
    assert "scoped to recipe `modernize`" in out
    # The point of scoping is what stays OUT: the security fix never ran —
    # eval survives untouched and no harden step appears in the report.
    # (The positive path — the filter keeping allowed steps, and the
    # modernize transform itself — is covered by the unit tests above.)
    assert "eval(e)" in (tmp_path / "app" / "danger.py").read_text()
    assert "harden_security" not in out


def test_cli_maintain_unknown_recipe_exits_one(tmp_path, capsys):
    from app.cli import cmd_maintain

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    ns = argparse.Namespace(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=False, out="", dry_run=False, proof="", recipe="tpyo")
    assert cmd_maintain(ns) == 1
    assert "unknown recipe" in capsys.readouterr().out


def test_cli_recipes_lists(capsys):
    from app.cli import cmd_recipes

    assert cmd_recipes(argparse.Namespace(json=False)) == 0
    assert "composable" in capsys.readouterr().out
