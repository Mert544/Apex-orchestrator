"""apex rewrite: structural $-metavariable rewriting under the family creed."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.pattern_rewrite import plan_pattern_rewrite


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def empty(xs):\n"
        "    return len(xs) == 0  # emptiness check\n"
        "\n"
        "def both(a, b):\n"
        "    return len(a.items) == 0 and len(b) == 0\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import empty\n"
        "def test_empty():\n"
        "    assert empty([]) is True\n"
        "    assert empty([1]) is False\n"
    )
    return tmp_path


def test_metavariable_match_rewrites_and_keeps_spelling(tmp_path):
    _project(tmp_path)
    plan = plan_pattern_rewrite(tmp_path, "len($x) == 0", "not $x")
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    # The capture's own spelling survives — attribute chains included.
    assert "return not xs  # emptiness check" in core
    assert "return not a.items and not b" in core
    assert plan.edits_by_file["app/core.py"] == 3
    ast.parse(core)


def test_repeated_metavariable_must_capture_same_text(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(a, b):\n"
        "    same = a + a\n"
        "    diff = a + b\n"
        "    return same, diff\n"
    )
    plan = plan_pattern_rewrite(tmp_path, "$v + $v", "2 * $v")
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/m.py"]
    assert "same = 2 * a" in new
    assert "diff = a + b" in new  # different captures: not a match


def test_multiline_match_is_skipped_with_warning(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(xs):\n"
        "    return len(\n"
        "        xs) == 0\n"
    )
    plan = plan_pattern_rewrite(tmp_path, "len($x) == 0", "not $x")
    assert not plan.blockers
    assert not plan.new_contents
    assert any("spans lines" in w for w in plan.warnings)


def test_nested_match_inside_a_rewritten_match_is_skipped(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(x):\n"
        "    return int(int(x))\n"
    )
    plan = plan_pattern_rewrite(tmp_path, "int($x)", "round($x)")
    assert plan.ok, plan.blockers
    # Outermost wins; the inner int(x) travels inside the capture untouched.
    assert "return round(int(x))" in plan.new_contents["app/m.py"]
    assert plan.edits_by_file["app/m.py"] == 1


def test_guardrails_block_dishonest_inputs(tmp_path):
    _project(tmp_path)
    # Unparsable pattern / replacement.
    assert not plan_pattern_rewrite(tmp_path, "len($x ==", "not $x").ok
    assert not plan_pattern_rewrite(tmp_path, "len($x) == 0", "not $x or").ok
    # A replacement metavariable the pattern never binds.
    plan = plan_pattern_rewrite(tmp_path, "len($x) == 0", "not $y")
    assert any("$y" in b for b in plan.blockers)
    # A bare metavariable would match the whole world.
    plan = plan_pattern_rewrite(tmp_path, "$x", "f($x)")
    assert any("bare metavariable" in b for b in plan.blockers)


def test_no_match_is_an_honest_noop(tmp_path):
    _project(tmp_path)
    plan = plan_pattern_rewrite(tmp_path, "frozenset($x)", "set($x)")
    assert not plan.blockers and not plan.new_contents


def test_apply_verifies_and_rolls_back_on_red(tmp_path):
    _project(tmp_path)
    res = apply_rename(tmp_path, plan_pattern_rewrite(tmp_path, "len($x) == 0", "not $x"),
                       verify=True)
    assert res["applied"] is True and res["verified"] is True

    # A semantics-CHANGING rewrite must come back when the suite goes red.
    before = (tmp_path / "app" / "core.py").read_text()
    res2 = apply_rename(tmp_path, plan_pattern_rewrite(tmp_path, "not $x", "bool($x)"),
                        verify=True)
    assert res2["applied"] is False and res2["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before


def test_cli_rewrite_round_trip(tmp_path, capsys):
    from app.cli import cmd_rewrite

    _project(tmp_path)
    ns = argparse.Namespace(pattern="len($x) == 0", replacement="not $x",
                            target=str(tmp_path), dry_run=True,
                            no_verify=False, json=False)
    assert cmd_rewrite(ns) == 0
    out = capsys.readouterr().out
    assert "-    return len(xs) == 0  # emptiness check" in out
    assert "+    return not xs  # emptiness check" in out

    ns.dry_run = False
    assert cmd_rewrite(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "not xs" in (tmp_path / "app" / "core.py").read_text()
