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
    covering_test_files,
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


def test_collect_sites_covers_new_operator_families():
    src = (
        "def f(x):\n"
        "    x += 1\n"
        "    return x + 1\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "augassign:+=>-=" in ops
    assert "number:1>2" in ops
    assert "return:value>None" in ops


def test_collect_sites_number_mutates_to_n_plus_one():
    src = "x = 41\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    num = [s for s in sites if s.operator.startswith("number:")]
    assert len(num) == 1
    assert num[0].original == "41" and num[0].mutated == "42"


def test_collect_sites_float_number_mutates_in_kind():
    src = "x = 1.5\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    num = [s for s in sites if s.operator.startswith("number:")]
    assert len(num) == 1
    assert num[0].original == "1.5" and num[0].mutated == "2.5"


def test_collect_sites_skips_bool_for_number_operator():
    # ``True`` is a constant but a bool — it must stay a boolean-constant flip,
    # never a number flip.
    src = "x = True\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "constant:True>False" in ops
    assert not any(o.startswith("number:") for o in ops)


def test_collect_sites_return_none_has_no_return_mutant():
    # A bare ``return None`` (and ``return`` with no value) is excluded.
    src = (
        "def f():\n"
        "    return None\n"
        "def g():\n"
        "    return\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator == "return:value>None" for s in sites)


def test_collect_sites_skips_multiline_return():
    src = (
        "def f(a, b):\n"
        "    return (a +\n"
        "            b)\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator == "return:value>None" for s in sites)


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
    # ``return a == b`` now seeds both a comparison flip and a return-value
    # flip; the strong suite (exact True/False) kills every one of them.
    assert result.total >= 1
    assert result.killed == result.total
    assert result.survived == 0
    assert result.score == 1.0
    assert result.survivors == []
    ops = {m.operator for m in result.survivors}
    assert ops == set()


def test_weak_suite_lets_mutant_survive(tmp_path):
    # A suite that only checks "not None" never observes the flipped operator,
    # so the comparison mutant survives. (The return-value flip turns the
    # result into ``None`` and IS caught by the ``is not None`` assertion.)
    test_src = (
        "from mod import is_equal\n"
        "def test_smoke():\n"
        "    assert is_equal(1, 1) is not None\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.survived >= 1
    survivor_ops = {m.operator for m in result.survivors}
    assert "comparison:==>!=" in survivor_ops
    comp = next(m for m in result.survivors if m.operator == "comparison:==>!=")
    assert comp.line == 2


_NUM_MODULE_SRC = '''\
def add_one(x):
    return x + 1
'''


def test_number_mutant_killed_by_strong_test(tmp_path):
    # A strong test pins the exact value, so ``1 -> 2`` is caught. (The
    # arithmetic ``+ -> -`` and return-value flips are caught too.)
    test_src = (
        "from mod import add_one\n"
        "def test_add():\n"
        "    assert add_one(1) == 2\n"
    )
    rel = _write_project(tmp_path, _NUM_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    ops = {m.operator for m in (result.survivors)}
    # No survivor carries the number flip: the strong test killed it.
    assert "number:1>2" not in ops
    killed_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "number:1>2" in killed_ops
    assert result.score == 1.0


def test_number_mutant_survives_weak_test(tmp_path):
    # A weak ``is not None`` test never observes the changed number value.
    test_src = (
        "from mod import add_one\n"
        "def test_add():\n"
        "    assert add_one(1) is not None\n"
    )
    rel = _write_project(tmp_path, _NUM_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    survivor_ops = {m.operator for m in result.survivors}
    assert "number:1>2" in survivor_ops


def test_return_value_mutant_killed_by_value_test(tmp_path):
    module_src = (
        "def make():\n"
        "    return 7\n"
        "def use():\n"
        "    return make()\n"
    )
    test_src = (
        "from mod import use\n"
        "def test_use():\n"
        "    assert use() == 7\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=20)
    # ``return make()`` -> ``return None`` is a seeded fault the value test kills.
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "return:value>None" in all_ops
    assert not any(m.operator == "return:value>None" for m in result.survivors)


def test_augmented_assign_mutant_generated(tmp_path):
    module_src = (
        "def accumulate(n):\n"
        "    total = 0\n"
        "    total += n\n"
        "    return total\n"
    )
    test_src = (
        "from mod import accumulate\n"
        "def test_acc():\n"
        "    assert accumulate(3) == 3\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=20)
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "augassign:+=>-=" in all_ops
    # The strong test (3 != -3) kills the ``+= -> -=`` flip.
    assert not any(m.operator == "augassign:+=>-=" for m in result.survivors)


def _mutants_of(result, root, rel):
    """All mutants (killed + survived) re-derived from the source for assertion
    on which operators were SEEDED, independent of kill/survive outcome."""
    import ast as _ast

    from app.engine.mutation_tester import _collect_sites
    from pathlib import Path as _Path

    src = (_Path(root) / rel).read_text(encoding="utf-8")
    sites = _collect_sites(_ast.parse(src), src.splitlines(keepends=True))

    class _M:
        def __init__(self, op):
            self.operator = op

    return [_M(s.operator) for s in sites]


def test_no_mutable_sites_returns_empty_result(tmp_path):
    # A module with NO mutable sites: no operators, no numeric/return-value
    # constants. ``return x`` would now seed a return-value mutant, and a bare
    # ``return None`` is excluded, so we use a function whose body is ``pass``.
    module_src = (
        "def noop(x):\n"
        "    pass\n"
    )
    test_src = (
        "from mod import noop\n"
        "def test_pt():\n"
        "    assert noop(5) is None\n"
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


def test_determinism_two_runs_identical_new_operators(tmp_path):
    # A module exercising number / return-value / augmented-assign operators
    # must produce byte-identical results across two runs.
    module_src = (
        "def step(x):\n"
        "    total = 0\n"
        "    total += 1\n"
        "    return total + x\n"
    )
    test_src = (
        "from mod import step\n"
        "def test_step():\n"
        "    assert step(2) == 3\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    assert a == b


def test_augassign_splice_keeps_equals_token():
    # The augmented-assign flip mutates only the operator char, leaving ``=``.
    from app.engine.mutation_tester import _Site, _splice
    src = "x += 1\n"
    lines = src.splitlines(keepends=True)
    site = _Site(line=1, col=2, end_col=3, operator="augassign:+=>-=",
                 original="+", mutated="-")
    mutated = _splice(lines, site)
    assert mutated == "x -= 1\n"


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
                         score=1.0, survivors=[], scoped_tests=["tests/test_mod.py"])
    assert m.to_dict()["killed"] is True
    d = res.to_dict()
    assert d["module"] == "mod.py" and d["score"] == 1.0 and d["survivors"] == []
    assert d["scoped_tests"] == ["tests/test_mod.py"]


# --- test scoping (deterministic, coverage-free) --------------------------

def _write_pkg_module(root, src):
    """Lay down an ``app/foo.py`` package module for the scoping tests."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "foo.py").write_text(src, encoding="utf-8")
    return "app/foo.py"


def test_covering_test_files_finds_from_import(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n    assert is_equal(1, 1) is True\n",
        encoding="utf-8",
    )
    # An unrelated test that imports something else must be ignored.
    (tests / "test_other.py").write_text(
        "import os\ndef test_o():\n    assert os.sep\n", encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_foo.py"]


def test_covering_test_files_handles_import_forms(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    # `import app.foo`
    (tests / "test_a.py").write_text(
        "import app.foo\ndef test_a():\n    assert app.foo.is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # `from app import foo` (parent package + member)
    (tests / "test_b.py").write_text(
        "from app import foo\ndef test_b():\n    assert foo.is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # `from app.foo import is_equal`
    (tests / "test_c.py").write_text(
        "from app.foo import is_equal\ndef test_c():\n    assert is_equal(1, 1)\n",
        encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]


def test_covering_test_files_skips_parse_errors(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text(
        "from app.foo import is_equal\ndef test_ok():\n    assert is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # A syntactically broken test file must be skipped, not crash the scan.
    (tests / "test_broken.py").write_text(
        "from app.foo import is_equal\ndef test_x(:\n    pass\n", encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_ok.py"]


def test_covering_test_files_empty_when_unrelated(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_other.py").write_text(
        "import os\ndef test_o():\n    assert os.sep\n", encoding="utf-8",
    )
    assert covering_test_files(str(tmp_path), rel) == []


def test_scoped_run_uses_only_covering_tests(tmp_path):
    # Strong covering test kills the mutant; an unrelated test that would CRASH
    # if executed proves only the covering test was actually run.
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
        encoding="utf-8",
    )
    # This unrelated test does NOT import app.foo and would fail loudly if run.
    (tests / "test_poison.py").write_text(
        "def test_poison():\n    assert False, 'should not run'\n",
        encoding="utf-8",
    )
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.killed == result.total
    assert result.score == 1.0
    assert result.scoped_tests == ["tests/test_foo.py"]


def test_scoped_run_no_covering_test_falls_back(tmp_path):
    # No test imports the module -> scope is empty -> fall back to full suite.
    # The full suite here has a weak test that doesn't import the module, so the
    # mutant survives, and scoped_tests is empty to record the fallback.
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_unrelated.py").write_text(
        "def test_u():\n    assert 1 == 1\n", encoding="utf-8",
    )
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.survived == result.total
    assert result.score == 0.0
    assert result.scoped_tests == []


def test_scope_tests_false_reproduces_full_suite(tmp_path):
    # With scoping off, the original full-suite path runs; scoped_tests stays
    # empty and a strong root-level test still kills the mutant.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10, scope_tests=False)
    assert result.total >= 1
    assert result.killed == result.total
    assert result.score == 1.0
    assert result.scoped_tests == []


def test_scoped_determinism_two_runs_identical(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
        encoding="utf-8",
    )
    a = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    assert a == b
    assert a["scoped_tests"] == ["tests/test_foo.py"]


def test_scoped_run_original_tree_unchanged(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n    assert is_equal(1, 1) is True\n",
        encoding="utf-8",
    )
    before = (tmp_path / rel).read_text(encoding="utf-8")
    mutation_score(str(tmp_path), rel, max_mutants=10)
    after = (tmp_path / rel).read_text(encoding="utf-8")
    assert after == before == _MODULE_SRC


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
    assert payload["total"] >= 1
    assert payload["survived"] >= 1
    survivor_ops = {s["operator"] for s in payload["survivors"]}
    assert "comparison:==>!=" in survivor_ops


def test_cmd_mutants_empty_module(tmp_path, capsys):
    module_src = "def noop(x):\n    pass\n"
    test_src = (
        "from mod import noop\n"
        "def test_pt():\n"
        "    assert noop(1) is None\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No mutable sites" in out
