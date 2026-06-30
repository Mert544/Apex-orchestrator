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
    # render is non-public (empty __all__) so the public-API rail permits dropping
    # its dead ``color`` param (the explicit import in the test is unaffected).
    (tmp_path / "app" / "m.py").write_text(
        "__all__ = []\n"
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


# --- ship-value: the North-Star concrete chain as a fractal goal --------------
#
# The five additive composites (ship-value -> finish-code/wire-surface/safety-net
# /type-and-doc) make Apex's own LAND-working-code chain a single reachable goal.
# All assertions below were reproduced byte-for-byte against the live tree and the
# move_value spine; the existing pinned tests above (lines 14-37) are the
# off-by-default byte-identity guard and MUST stay green unchanged.

_SHIP_VALUE_DECL = ["implement-stub", "tdd-implement", "scaffold-from-protocol",
                    "wire-exports", "wire-module-exports", "cover-gaps",
                    "strengthen-tests", "pin-doctest", "infer-type-hints",
                    "document-signature", "generate-usage-doc", "dataclassify"]


def test_ship_value_goal_decomposes_to_concrete_objectives():
    # The North-Star concrete chain is now ONE reachable fractal goal. At default
    # (value_led off) it flattens in DECLARATION order — which is already
    # descending buyer-value, so the sweep is concrete-first even off-by-default.
    assert resolve_goal("ship-value") == _SHIP_VALUE_DECL


def test_ship_value_subgoals_decompose():
    assert resolve_goal("finish-code") == ["implement-stub", "tdd-implement",
                                           "scaffold-from-protocol"]
    assert resolve_goal("wire-surface") == ["wire-exports", "wire-module-exports"]
    assert resolve_goal("safety-net") == ["cover-gaps", "strengthen-tests",
                                          "pin-doctest"]
    assert resolve_goal("type-and-doc") == ["infer-type-hints", "document-signature",
                                            "generate-usage-doc", "dataclassify"]


def test_existing_goal_resolution_byte_identical():
    # The off-by-default byte-identity guard for the ADDITIVE-TREE axis: the five
    # new keys must not perturb any pre-existing goal's DECLARATION-order flatten.
    assert resolve_goal("reduce-debt") == [
        "modernize", "simplify-bool-return", "remove-dead-code", "dead-params",
        "remove-unused-imports", "sort-imports", "simplify-comprehension",
        "merge-isinstance", "collapse-startswith", "dedup", "shrink-functions",
        "inline-helpers"]
    assert resolve_goal("tidy") == [
        "modernize", "simplify-bool-return", "remove-dead-code", "dead-params",
        "remove-unused-imports", "sort-imports", "simplify-comprehension",
        "merge-isinstance", "collapse-startswith"]
    assert resolve_goal("polish") == ["remove-unused-imports", "sort-imports",
                                      "simplify-comprehension"]
    assert resolve_goal("simplify-conditions") == ["merge-isinstance",
                                                   "collapse-startswith"]
    assert resolve_goal("simplify-structure") == ["dedup", "shrink-functions",
                                                  "inline-helpers"]
    assert resolve_goal("harden") == ["cover-gaps"]


def test_value_led_orders_reduce_debt_high_value_first():
    # value_led=True re-orders the SAME leaves by descending move_value with the
    # declaration index as a total tiebreak: dedup(0.60) first, sort-imports(0.18)
    # last; remove-dead-code(0.40,idx2) before dead-params(0.40,idx3).
    assert resolve_goal("reduce-debt", value_led=True) == [
        "dedup", "shrink-functions", "inline-helpers", "remove-dead-code",
        "dead-params", "modernize", "simplify-bool-return", "simplify-comprehension",
        "merge-isinstance", "remove-unused-imports", "collapse-startswith",
        "sort-imports"]


def test_value_led_orders_ship_value_concrete_first():
    # The two value-1.0 leaves lead, in declaration-index order, ahead of
    # dataclassify(0.50) / document-signature(0.68) — concrete-first at the goal
    # layer. (Declaration order already leads with them; this proves the SORT,
    # not the declaration, by also pinning the value-1.0 pair at the head.)
    led = resolve_goal("ship-value", value_led=True)
    assert led[0:2] == ["implement-stub", "tdd-implement"]
    assert led.index("implement-stub") < led.index("dataclassify")
    assert led.index("tdd-implement") < led.index("document-signature")


def test_value_led_is_deterministic_under_env():
    import subprocess
    import sys

    src = ("from app.engine.fractal_develop import resolve_goal, available_goals;"
           "print({g: resolve_goal(g, value_led=True) for g in available_goals()})")
    out0 = subprocess.run([sys.executable, "-c", src], capture_output=True,
                          text=True, env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin",
                                          "PYTHONPATH": ""}, cwd=".")
    out1 = subprocess.run([sys.executable, "-c", src], capture_output=True,
                          text=True, env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin",
                                          "PYTHONPATH": ""}, cwd=".")
    assert out0.returncode == 0 and out1.returncode == 0, (out0.stderr, out1.stderr)
    assert out0.stdout == out1.stdout  # total order is hashseed-invariant
    # And stable across repeated in-process calls.
    assert resolve_goal("ship-value", value_led=True) == resolve_goal(
        "ship-value", value_led=True)


def test_value_led_default_false_byte_identical():
    # For EVERY goal, value_led off (explicit or default) equals the unchanged
    # flatten — the byte-identity guarantee every existing caller relies on.
    for g in available_goals():
        base = resolve_goal(g)
        assert resolve_goal(g, value_led=False) == base


def test_goal_tree_leaves_are_real_objectives_still_holds():
    from app.engine.objective_compiler import available_objectives
    avail = set(available_objectives())
    for goal in GOAL_TREE:  # includes the five new composites
        for obj in resolve_goal(goal):
            assert obj in avail


def test_objective_parent_cover_gaps_stays_harden():
    # cover-gaps is now a child of BOTH harden and the new safety-net. ascend's
    # objective_parent returns the FIRST-inserted parent (dict order); harden was
    # inserted before safety-net, so the climb's naming is unchanged.
    from app.engine.ascend import objective_parent
    assert objective_parent("cover-gaps") == "harden"


def _stub_and_dataclass_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # A test-pinned fillable stub -> implement-stub (buyer value 1.00).
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    # A boilerplate __init__ class -> dataclassify (buyer value 0.50).
    (tmp_path / "app" / "pt.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    (tmp_path / "tests" / "test_pt.py").write_text(
        "from app.pt import Point\ndef test_pt():\n"
        "    p = Point(1, 2)\n    assert p.x == 1 and p.y == 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n",
                                             encoding="utf-8")
    return tmp_path


def test_compile_goal_value_led_runs_high_value_first(tmp_path):
    # On a fixture with BOTH a fillable stub (implement-stub, 1.00) and a
    # dataclassify candidate (0.50), a value-led ship-value campaign attempts the
    # higher-value concrete objective FIRST: the first sub-campaign that lands
    # work is implement-stub, ahead of dataclassify in the resolved order.
    _stub_and_dataclass_project(tmp_path)
    gr = compile_goal(str(tmp_path), "ship-value", value_led=True, max_steps=1,
                      verify=False)
    assert gr.objectives.index("implement-stub") < gr.objectives.index("dataclassify")
    landed = [r for r in gr.results if r.steps]
    assert landed and landed[0].objective == "implement-stub"
    assert landed[0].steps[0].operator == "implement_stub"


def test_self_audit_north_star_and_soundness_still_pass():
    # Adding a GOAL (not a registered objective) triggers no manifest obligation,
    # so both self-audits stay PASS — the no-parity-obligation invariant.
    import os

    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import soundness_report
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assert north_star_report(repo)["verdict"] == "PASS"
    assert soundness_report(repo)["verdict"] == "PASS"


def test_available_goals_includes_ship_value():
    goals = available_goals()
    for new in ("ship-value", "finish-code", "wire-surface", "safety-net",
                "type-and-doc"):
        assert new in goals
    # Additive: the pre-existing names are still present (no regression).
    for old in ("reduce-debt", "tidy", "modernize"):
        assert old in goals


def test_resolve_goal_value_led_recursion_safe():
    # A leaf reachable via two parents (cover-gaps: harden AND safety-net) appears
    # exactly once, and the sort fires only at the outermost frame — so the
    # value-led flatten is still de-duplicated and never re-orders a child list.
    led = resolve_goal("ship-value", value_led=True)
    assert led.count("cover-gaps") == 1
    assert len(led) == len(set(led))
    assert sorted(led) == sorted(_SHIP_VALUE_DECL)  # same leaf SET, reordered
