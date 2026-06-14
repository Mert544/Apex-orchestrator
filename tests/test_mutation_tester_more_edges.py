"""Edge-path coverage for the mutation tester's pure helpers.

These tests pin the boundary/early-return branches that the existing suite
leaves uncovered: multi-line nodes that are skipped, malformed/equivalent
splices, the numeric-literal mutation rules, the dotted-path and test-file
classifiers, the import-name collector, and the per-mutant timeout kill.
All inputs are constructed explicitly so the tests stay deterministic.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from app.engine.mutation_tester import (
    _Site,
    _collect_sites,
    _imported_names,
    _is_test_file,
    _module_dotted_path,
    _mutate_number,
    _op_span,
    _splice,
    _verify_killed,
    covering_test_files,
)


# --- _op_span: the token-not-present early return --------------------------

def test_op_span_returns_none_when_token_absent():
    assert _op_span("a + b", 0, "==") is None


def test_op_span_returns_span_when_present():
    assert _op_span("a == b", 0, "==") == (2, 4)


# --- multi-line nodes are skipped (no single-line span to splice) ----------

def test_boolop_multiline_is_skipped():
    src = "def f(a, b):\n    return (a\n            and b)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator.startswith("boolean:") for s in sites)


def test_binop_multiline_is_skipped():
    src = "def f(a, b):\n    return (a +\n            b)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator.startswith("arithmetic:") for s in sites)


def test_compare_multiline_is_skipped():
    src = "def f(a, b):\n    return (a ==\n            b)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator.startswith("comparison:") for s in sites)


def test_return_multiline_value_is_skipped():
    src = "def f(a, b):\n    return (a\n            + b)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator == "return:value>None" for s in sites)


def test_augassign_multiline_is_skipped():
    src = "def f(x, y):\n    x += (y\n          + 1)\n    return x\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator.startswith("augassign:") for s in sites)


# --- numeric-literal mutation rules ----------------------------------------

def test_mutate_number_int_increments():
    assert _mutate_number(3, "3") == "4"


def test_mutate_number_int_refuses_exotic_literal():
    # Hex literal: the written token isn't str(value), so no mutation.
    assert _mutate_number(255, "0xff") is None


def test_mutate_number_float_increments():
    assert _mutate_number(1.5, "1.5") == "2.5"


def test_mutate_number_float_refuses_mismatched_text():
    # Underscored forms don't equal repr(value); refuse them.
    assert _mutate_number(1000.0, "1_000.0") is None


def test_mutate_number_bool_is_refused():
    assert _mutate_number(True, "True") is None


def test_mutate_number_non_numeric_returns_none():
    # Defensive final branch: a value that is neither int nor float (a complex
    # literal slips past the int/float dispatch) -> None.
    assert _mutate_number(complex(1, 2), "(1+2j)") is None


def test_number_site_skipped_when_replacement_none():
    # A hex literal yields replacement None -> no number site is collected.
    src = "def f():\n    return 0xff\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator.startswith("number:") for s in sites)


# --- _splice: the three None-returning guards ------------------------------

def test_splice_returns_none_when_line_out_of_range():
    site = _Site(line=99, col=0, end_col=1, operator="x", original="a", mutated="b")
    assert _splice(["only one line\n"], site) is None


def test_splice_returns_none_when_original_mismatch():
    # The recorded original doesn't match the actual line text -> bail out.
    site = _Site(line=1, col=0, end_col=1, operator="x", original="Z", mutated="b")
    assert _splice(["abc\n"], site) is None


def test_splice_returns_none_when_result_unparseable():
    # Replacing a token so the module no longer parses -> None.
    site = _Site(line=1, col=4, end_col=5, operator="x", original="1", mutated="def")
    assert _splice(["x = 1\n"], site) is None


def test_splice_succeeds_on_valid_replacement():
    site = _Site(line=1, col=4, end_col=5, operator="x", original="1", mutated="2")
    assert _splice(["x = 1\n"], site) == "x = 2\n"


# --- _module_dotted_path / _is_test_file -----------------------------------

def test_module_dotted_path_collapses_init():
    assert _module_dotted_path("app/engine/__init__.py") == "app.engine"


def test_module_dotted_path_plain_module():
    assert _module_dotted_path("app/engine/foo.py") == "app.engine.foo"


def test_is_test_file_rejects_non_python():
    assert _is_test_file("tests/data.txt") is False


def test_is_test_file_accepts_under_tests_dir():
    assert _is_test_file("tests/helpers/util.py") is True


def test_is_test_file_accepts_test_prefix():
    assert _is_test_file("pkg/test_thing.py") is True


# --- _imported_names: relative imports are ignored -------------------------

def test_imported_names_ignores_relative_imports():
    src = "from . import sibling\nfrom .pkg import thing\n"
    names = _imported_names(ast.parse(src))
    assert names == set()


def test_imported_names_records_absolute_and_member():
    src = "import app.engine\nfrom app.engine import foo\n"
    names = _imported_names(ast.parse(src))
    assert "app.engine" in names
    assert "app.engine.foo" in names


# --- covering_test_files: empty dotted path early return -------------------

def test_covering_test_files_empty_for_bad_module(tmp_path: Path):
    # ``__init__.py`` at the root collapses to an empty dotted path -> [].
    assert covering_test_files(tmp_path, "__init__.py") == []


def test_covering_test_files_skips_excluded_dirs(tmp_path: Path):
    # A test under an excluded dir (.git) must NOT be discovered, even though
    # it imports the target module.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    real = tmp_path / "tests"
    real.mkdir()
    (real / "test_mod.py").write_text("import app.mod\n", encoding="utf-8")
    skipped = tmp_path / ".git"
    skipped.mkdir()
    (skipped / "test_evil.py").write_text("import app.mod\n", encoding="utf-8")

    found = covering_test_files(tmp_path, "app/mod.py")
    assert found == ["tests/test_mod.py"]


# --- _verify_killed: a timeout counts as a kill ----------------------------

def test_verify_killed_timeout_counts_as_kill(tmp_path: Path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(subprocess, "run", _boom)
    killed = _verify_killed(tmp_path, "app/mod.py", "x = 2\n", verify_timeout=1)
    assert killed is True
