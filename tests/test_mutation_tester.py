"""Mutation testing — a deterministic test-strength fitness signal.

These tests build tiny synthetic projects in ``tmp_path`` (one module + one
test file each) so the per-mutant pytest runs stay fast, and exercise the
strong/weak/empty/cap/determinism/safety paths plus the CLI command.
"""

from __future__ import annotations

import argparse
import ast

from app.cli_insight import cmd_mutants
from app.engine.mutation_tester import (
    Mutant,
    MutationResult,
    _collect_sites,
    mutation_score,
)

# --- tiny synthetic project scaffolding -----------------------------------

_MODULE_SRC = '''\
def is_equal(a, b):
    return a == b
'''


def _write_project(root, module_src, test_src, module_rel="mod.py"):
    """Lay down a minimal pytest project: one module + one test."""
    (root / module_rel).write_text(module_src, encoding="utf-8")
    (root / "test_mod.py").write_text(test_src, encoding="utf-8")
    return module_rel


# --- site enumeration (pure, fast) ----------------------------------------

def test_collect_sites_covers_all_operator_families():
    src = (
        "def f(a, b):\n"
        "    return a == b and a + b > 0 or True\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "comparison:==>!=" in ops
    assert "arithmetic:+>-" in ops
    assert "comparison:>><=" in ops
    assert "boolean:and>or" in ops
    assert "boolean:or>and" in ops
    assert "constant:True>False" in ops


def test_collect_sites_is_deterministic_document_order():
    src = "x = (1 < 2) and (3 > 4)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    keys = [(s.line, s.col) for s in sites]
    assert keys == sorted(keys)


def test_collect_sites_skips_multiline_compares():
    src = (
        "def f(a, b):\n"
        "    return (a\n"
        "            == b)\n"
    )
    # The Compare node spans two lines, so it must not be mutated (the splice
    # would not be exact). No single-line mutable site here.
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert sites == []


# --- end-to-end scoring ---------------------------------------------------

def test_strong_suite_kills_comparison_mutant(tmp_path):
    # A suite that pins exact return values catches the == -> != flip.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total == 1
    assert result.killed == 1
    assert result.survived == 0
    assert result.score == 1.0
    assert result.survivors == []


def test_weak_suite_lets_mutant_survive(tmp_path):
    # A suite that only checks "not None" never observes the flipped operator.
    test_src = (
        "from mod import is_equal\n"
        "def test_smoke():\n"
        "    assert is_equal(1, 1) is not None\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total == 1
    assert result.killed == 0
    assert result.survived == 1
    assert result.score == 0.0
    assert result.survivors and result.survivors[0].operator == "comparison:==>!="
    assert result.survivors[0].line == 2


def test_no_mutable_sites_returns_empty_result(tmp_path):
    module_src = (
        "def greet(name):\n"
        "    return \"hello \" + name\n"
    )
    # The only BinOp is string concatenation; "+" -> "-" still parses, so to
    # get a genuinely empty module we use one with NO mutable operators.
    module_src = (
        "def passthrough(x):\n"
        "    return x\n"
    )
    test_src = (
        "from mod import passthrough\n"
        "def test_pt():\n"
        "    assert passthrough(5) == 5\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total == 0
    assert result.killed == 0
    assert result.survived == 0
    assert result.score == 0.0
    assert result.survivors == []


def test_syntax_error_module_returns_empty_result(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    result = mutation_score(str(tmp_path), "broken.py")
    assert result.total == 0
    assert result.score == 0.0


def test_missing_module_returns_empty_result(tmp_path):
    result = mutation_score(str(tmp_path), "does_not_exist.py")
    assert result.total == 0
    assert result.score == 0.0


def test_max_mutants_caps_the_count(tmp_path):
    module_src = (
        "def classify(a, b, c):\n"
        "    return a == b and b == c and a == c\n"
    )
    test_src = (
        "from mod import classify\n"
        "def test_c():\n"
        "    assert classify(1, 1, 1) is True\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    # There are >1 mutable sites; cap to 1.
    result = mutation_score(str(tmp_path), rel, max_mutants=1)
    assert result.total == 1


def test_determinism_two_runs_identical(tmp_path):
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    assert a == b


def test_original_file_unchanged_after_run(tmp_path):
    # Safety: the real tree is read-only; mutation happens only in copies.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    before = (tmp_path / rel).read_text(encoding="utf-8")
    mutation_score(str(tmp_path), rel, max_mutants=10)
    after = (tmp_path / rel).read_text(encoding="utf-8")
    assert after == before == _MODULE_SRC


def test_to_dict_round_trips_fields():
    m = Mutant(module="mod.py", line=2, operator="comparison:==>!=",
               original="==", mutated="!=", killed=True)
    res = MutationResult(module="mod.py", total=1, killed=1, survived=0,
                         score=1.0, survivors=[])
    assert m.to_dict()["killed"] is True
    d = res.to_dict()
    assert d["module"] == "mod.py" and d["score"] == 1.0 and d["survivors"] == []


# --- CLI ------------------------------------------------------------------

def test_cmd_mutants_human_output(tmp_path, capsys):
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mutation score" in out
    assert "100.0%" in out


def test_cmd_mutants_json_output(tmp_path, capsys):
    test_src = (
        "from mod import is_equal\n"
        "def test_smoke():\n"
        "    assert is_equal(1, 1) is not None\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=True)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    import json as _json
    payload = _json.loads(out)
    assert rc == 0
    assert payload["total"] == 1
    assert payload["survived"] == 1
    assert payload["survivors"][0]["operator"] == "comparison:==>!="


def test_cmd_mutants_empty_module(tmp_path, capsys):
    module_src = "def passthrough(x):\n    return x\n"
    test_src = (
        "from mod import passthrough\n"
        "def test_pt():\n"
        "    assert passthrough(1) == 1\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No mutable sites" in out
