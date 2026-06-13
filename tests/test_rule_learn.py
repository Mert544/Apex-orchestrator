"""apex teach: anti-unification learns verified rules from examples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.execution.rule_learn import learn_rule
from app.execution.rewrite_rules import load_rules, save_rule


def test_two_examples_generalize_to_a_metavariable_rule():
    rule = learn_rule([("len(xs) == 0", "not xs"),
                       ("len(a.b) == 0", "not a.b")])
    assert rule.ok, rule.blockers
    assert rule.pattern == "len($v1) == 0"
    assert rule.replacement == "not $v1"
    assert any("self-check passed on 2" in n for n in rule.notes)


def test_same_capture_pair_reuses_one_metavariable():
    # x+x→2*x and y+y→2*y: both holes in each example carry the SAME text,
    # so the learner must emit one $v1, not two — that is what makes the
    # learned pattern demand structural equality of the two operands.
    rule = learn_rule([("x + x", "2 * x"), ("y + y", "2 * y")])
    assert rule.ok, rule.blockers
    assert rule.pattern == "$v1 + $v1"
    assert rule.replacement == "2 * $v1"


def test_single_example_yields_exact_rule_with_honest_note():
    rule = learn_rule([("os.getcwd()", "Path.cwd()")])
    assert rule.ok
    assert rule.pattern == "os.getcwd()"
    assert rule.replacement == "Path.cwd()"
    assert any("exact-match" in n for n in rule.notes)


def test_structureless_examples_block_instead_of_matching_everything():
    # 'a + 1' vs 'b - 2': even the operator differs, so the only common
    # skeleton is one bare metavariable — refused, never guessed.
    rule = learn_rule([("a + 1", "f(a)"), ("b - 2", "f(b)")])
    assert not rule.ok
    assert any("don't share a structure" in b for b in rule.blockers)


def test_replacement_needing_uncaptured_values_blocks():
    # BEFOREs agree everywhere except $v1=(a|c); AFTERs differ in a SECOND
    # position (b|d) the pattern never captured — inexpressible, blocked.
    rule = learn_rule([("f(a)", "g(a, b)"), ("f(c)", "g(c, d)")])
    assert not rule.ok
    assert any("doesn't capture" in b for b in rule.blockers)


def test_bad_expressions_block():
    rule = learn_rule([("len(x ==", "not x")])
    assert not rule.ok
    assert any("not a pair of valid expressions" in b for b in rule.blockers)


def test_rule_book_save_load_and_duplicate_guard(tmp_path):
    assert load_rules(tmp_path) == []
    assert save_rule(tmp_path, "no-len-zero", "len($x) == 0", "not $x") is None
    rules = load_rules(tmp_path)
    assert rules == [{"name": "no-len-zero", "pattern": "len($x) == 0",
                      "replacement": "not $x"}]
    err = save_rule(tmp_path, "no-len-zero", "p", "r")
    assert err and "already exists" in err
    # Corrupt book reads as empty, never crashes.
    (tmp_path / ".apex" / "rewrite-rules.json").write_text("{nope")
    assert load_rules(tmp_path) == []


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def empty(xs):\n"
        "    return len(xs) == 0\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import empty\n"
        "def test_empty():\n"
        "    assert empty([]) is True\n"
    )
    return tmp_path


def test_cli_teach_learns_previews_and_saves(tmp_path, capsys):
    from app.cli import cmd_teach

    _project(tmp_path)
    ns = argparse.Namespace(
        examples=["len(xs) == 0", "not xs", "len(a.b) == 0", "not a.b"],
        save="no-len-zero", target=str(tmp_path))
    assert cmd_teach(ns) == 0
    out = capsys.readouterr().out
    assert "Learned rule: `len($v1) == 0` → `not $v1`" in out
    assert "-    return len(xs) == 0" in out   # preview, not applied
    assert "saved" in out
    assert (tmp_path / "app" / "core.py").read_text().count("len(xs) == 0") == 1
    assert load_rules(tmp_path)[0]["name"] == "no-len-zero"

    # Odd number of expressions is refused.
    ns2 = argparse.Namespace(examples=["a", "b", "c"], save="", target=str(tmp_path))
    assert cmd_teach(ns2) == 1


def test_cli_rewrite_runs_saved_rule_and_enforces_book(tmp_path, capsys):
    from app.cli import cmd_rewrite

    _project(tmp_path)
    save_rule(tmp_path, "no-len-zero", "len($x) == 0", "not $x")

    # --rules lists the book.
    ns = argparse.Namespace(pattern="", replacement=None, target=str(tmp_path),
                            dry_run=False, no_verify=False, json=False,
                            save="", rule="", rules=True, all=False)
    assert cmd_rewrite(ns) == 0
    assert "no-len-zero" in capsys.readouterr().out

    # --all applies every rule, verified; a second pass reports "holds".
    ns = argparse.Namespace(pattern="", replacement=None, target=str(tmp_path),
                            dry_run=False, no_verify=False, json=False,
                            save="", rule="", rules=False, all=True)
    assert cmd_rewrite(ns) == 0
    assert "re-applied" in capsys.readouterr().out
    assert "not xs" in (tmp_path / "app" / "core.py").read_text()
    assert cmd_rewrite(ns) == 0
    assert "holds (no drift)" in capsys.readouterr().out

    # --rule NAME runs one saved rule; unknown name is a clean error.
    ns = argparse.Namespace(pattern="", replacement=None, target=str(tmp_path),
                            dry_run=True, no_verify=False, json=False,
                            save="", rule="ghost", rules=False, all=False)
    assert cmd_rewrite(ns) == 1
    assert "no saved rule" in capsys.readouterr().out
