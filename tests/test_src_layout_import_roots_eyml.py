"""A separated ``src/``/``lib`` layout no longer misreads a GREEN baseline as RED.

The surviving adoption gap (the canonical FLAT shape — ``mod.py`` +
``tests/test_mod.py`` doing ``import mod`` — is already served by
``_has_flat_pytest_suite``): student/company repos often separate source into
``src/mod.py`` (or ``lib/mod.py``) with ``tests/test_mod.py`` doing a bare
``import mod``. Apex used to set ``PYTHONPATH=root`` ALONE, so ``import mod`` was
unresolvable, pytest collection errored, and the baseline was misread as RED — so
``develop`` landed NOTHING on a whole class of buyer projects.

The fix adds the ``src``/``lib`` source dir to PYTHONPATH, but ONLY when a test
imports a module that genuinely lives there by bare stem (never blindly widening
the path), with ``str(root)`` kept FIRST so a same-named package can't shadow the
target's own root modules or Apex's ``app/``.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.skills.execution.run_tests import RunTestsSkill


def _pytest_cmd() -> list[str]:
    return [sys.executable, "-m", "pytest", "-q"]


def _src_bare_module_project(root: Path, body: str) -> None:
    """A separated ``src/`` layout: a top-level ``src/calc.py`` module imported by
    bare stem from ``tests/test_calc.py`` (``import calc``)."""
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text(body, encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "import calc\n\n\n"
        "def test_add():\n    assert calc.add(1, 2) == 3\n",
        encoding="utf-8")


# --- the headline fix: a src/ bare-module layout now RUNS, honest green/red ---

def test_src_layout_runs_green_when_implemented(tmp_path: Path) -> None:
    # With ``src`` on the path the bare ``import calc`` resolves and a correct
    # implementation reads as GREEN (was a collection ERROR -> false RED before).
    _src_bare_module_project(tmp_path, "def add(a, b):\n    return a + b\n")

    summary = RunTestsSkill().run(tmp_path)
    assert summary.commands == [_pytest_cmd()]
    assert summary.ok is True
    assert summary.results  # a run actually happened


def test_src_layout_red_is_real_test_node_not_collection_error(tmp_path: Path) -> None:
    # With the stub still red, the failure is the REAL test node (the import
    # resolved, the body raised) — NOT a bare collection-error node, which is what
    # a misread baseline used to produce.
    _src_bare_module_project(
        tmp_path, "def add(a, b):\n    raise NotImplementedError\n")

    summary = RunTestsSkill().run(tmp_path)
    assert summary.ok is False
    stdout = summary.results[0]["stdout"]
    assert "tests/test_calc.py::test_add" in stdout  # the real test node ran
    assert "Interrupted" not in stdout  # not a collection error
    assert "No module named 'calc'" not in stdout  # the import was resolved


def test_lib_layout_added_when_bare_imported(tmp_path: Path) -> None:
    # ``lib/`` is honored identically to ``src/``.
    (tmp_path / "lib").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "lib" / "util.py").write_text(
        "def two():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_util.py").write_text(
        "import util\n\n\ndef test_two():\n    assert util.two() == 2\n",
        encoding="utf-8")

    roots = RunTestsSkill()._import_roots(tmp_path)
    assert roots == [str(tmp_path), str(tmp_path / "lib")]
    assert RunTestsSkill().run(tmp_path).ok is True


def test_from_import_bare_stem_also_adds_src(tmp_path: Path) -> None:
    # ``from calc import add`` (no dotted package) also pins ``src``.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")

    roots = RunTestsSkill()._import_roots(tmp_path)
    assert roots == [str(tmp_path), str(tmp_path / "src")]


# --- soundness: never blindly widen the path ---------------------------------

def test_root_stays_first(tmp_path: Path) -> None:
    # ``str(root)`` is ALWAYS the first entry so a same-named ``src/`` package can
    # never shadow the target's own root modules (or Apex's ``app/``).
    _src_bare_module_project(tmp_path, "def add(a, b):\n    return a + b\n")
    roots = RunTestsSkill()._import_roots(tmp_path)
    assert roots[0] == str(tmp_path)
    assert str(tmp_path / "src") in roots


def test_src_without_bare_imported_module_not_added(tmp_path: Path) -> None:
    # A ``src/`` whose modules NO test imports by bare stem must NOT be added —
    # the path is widened only on a genuine bare-stem need.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text(
        "def test_t():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


def test_dotted_import_does_not_add_src(tmp_path: Path) -> None:
    # A dotted import (``import src.calc`` / ``from pkg.calc import x``) is NOT a
    # bare-stem module under ``src/``; adding ``src`` wouldn't make it importable,
    # so the dir is not added.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "import src.calc\n\n\ndef test_t():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


def test_import_name_in_string_not_counted(tmp_path: Path) -> None:
    # AST-parsed: a module name that only appears in a string/comment never pins
    # ``src`` (no false widening on a textual coincidence).
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        's = "import calc"  # not a real import\n\n\n'
        "def test_t():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


# --- no false positive: flat / no-src layouts are byte-identical -------------

def test_flat_root_layout_path_unchanged(tmp_path: Path) -> None:
    # A flat-root project (``calc.py`` + ``test_calc.py`` at the root) has only the
    # root on the path — the regression guard against shadowing.
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]
    # Command SHAPE is identical to the flat case (no extra path can change it).
    summary = RunTestsSkill().run(tmp_path)
    assert summary.commands == [_pytest_cmd()]
    assert summary.ok is True


def test_no_src_or_lib_path_unchanged(tmp_path: Path) -> None:
    # A repo with NO ``src``/``lib`` dir at all keeps a single-root PYTHONPATH.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


def test_src_file_not_dir_not_added(tmp_path: Path) -> None:
    # A FILE literally named ``src`` (not a directory) must never be added.
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").write_text("not a dir\n", encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(
        "import calc\n\n\ndef test_x():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


# --- determinism -------------------------------------------------------------

def test_import_roots_is_deterministic(tmp_path: Path) -> None:
    _src_bare_module_project(tmp_path, "def add(a, b):\n    return a + b\n")
    skill = RunTestsSkill()
    first = skill._import_roots(tmp_path)
    second = skill._import_roots(tmp_path)
    assert first == second == [str(tmp_path), str(tmp_path / "src")]


def test_both_src_and_lib_sorted(tmp_path: Path) -> None:
    # When BOTH src and lib supply bare-imported modules, the extra entries are
    # sorted (``lib`` before ``src``) for a stable, deterministic path.
    (tmp_path / "src").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "lib" / "beta.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ab.py").write_text(
        "import alpha\nimport beta\n\n\ndef test_t():\n    assert True\n",
        encoding="utf-8")

    roots = RunTestsSkill()._import_roots(tmp_path)
    assert roots == [str(tmp_path), str(tmp_path / "lib"), str(tmp_path / "src")]


# --- empty/edge paths --------------------------------------------------------

def test_no_tests_no_imports_single_root(tmp_path: Path) -> None:
    # No test files at all -> no bare imports -> single root (the empty path).
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]


def test_empty_src_dir_not_added(tmp_path: Path) -> None:
    # A ``src`` dir with no ``*.py`` modules supplies nothing, even if a test does
    # a bare import (which simply won't resolve there).
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import calc\n\n\ndef test_x():\n    assert True\n", encoding="utf-8")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path)]
