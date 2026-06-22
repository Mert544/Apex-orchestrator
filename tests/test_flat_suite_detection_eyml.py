"""Flat root-level `test_*.py` suites are detected (the common student layout).

A P0 adoption blocker: a flat repo with `calc.py` + `test_calc.py` at the root
and NO config (`pyproject.toml`/`pytest.ini`/`tests/`) is collected fine by
`pytest`'s own default discovery, yet `RunTestsSkill._detect_commands` used to
emit nothing for it. The develop loop then saw NO suite and marked EVERY landed
contribution `no-suite` — the "verified, never-fakes-green" promise silently
failed for the exact target buyer.

This pins the fix: mirror pytest's default discovery (`test_*.py` / `*_test.py`,
plus a root `conftest.py`) at the rootdir and the obvious top-level package
dirs, while keeping every existing trigger BYTE-IDENTICAL and never
false-triggering on a repo with zero test files.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.skills.execution.run_tests import RunTestsSkill


def _pytest_cmd(root: Path) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q"]


# --- the flat layout is now detected -----------------------------------------

def test_flat_root_test_file_detected(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n")

    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_flat_suffix_test_file_detected(tmp_path: Path) -> None:
    # pytest also collects `*_test.py` under its default pattern.
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "calc_test.py").write_text(
        "from calc import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n")

    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_root_conftest_detected(tmp_path: Path) -> None:
    # A bare `conftest.py` at the root signals a pytest project too.
    (tmp_path / "conftest.py").write_text("def pytest_configure(config):\n    pass\n")

    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_test_file_in_top_level_package_detected(tmp_path: Path) -> None:
    # Tests living one level down in the obvious top-level package are still
    # within pytest's default rootdir collection — detect them, bounded.
    pkg = tmp_path / "src"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    (pkg / "test_mod.py").write_text(
        "from mod import f\n"
        "def test_f():\n    assert f() == 1\n")

    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


# --- the flat suite actually RUNS (green/red are honest) ---------------------

def test_flat_suite_runs_green(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n")

    summary = RunTestsSkill().run(tmp_path)
    assert summary.commands == [_pytest_cmd(tmp_path)]
    assert summary.ok is True
    assert summary.results  # a run actually happened


def test_flat_suite_runs_red_on_failure(tmp_path: Path) -> None:
    (tmp_path / "test_bad.py").write_text(
        "def test_bad():\n    assert False\n")

    summary = RunTestsSkill().run(tmp_path)
    assert summary.commands == [_pytest_cmd(tmp_path)]
    assert summary.ok is False  # a real failing suite, honestly red


# --- no false positive: a repo with no test files stays no-suite -------------

def test_no_test_files_stays_no_suite(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# project\n")

    assert RunTestsSkill()._detect_commands(tmp_path) == []
    assert RunTestsSkill().run(tmp_path).commands == []


def test_nested_app_dir_without_tests_stays_no_suite(tmp_path: Path) -> None:
    # The no-suite-honesty shape: an `app/` package with source but NO test file
    # anywhere must NOT trigger a flat-suite false positive.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.py").write_text("def compute(x):\n    return x * 2\n")

    assert RunTestsSkill()._detect_commands(tmp_path) == []


def test_venv_bundled_tests_do_not_false_trigger(tmp_path: Path) -> None:
    # A dependency's tests bundled under the target's own virtualenv must not be
    # mistaken for the project's own suite.
    venv_tests = tmp_path / ".venv" / "lib" / "pkg"
    venv_tests.mkdir(parents=True)
    (venv_tests / "test_dep.py").write_text("def test_dep():\n    assert True\n")
    (tmp_path / "main.py").write_text("def main():\n    return 0\n")

    assert RunTestsSkill()._detect_commands(tmp_path) == []


def test_deep_nested_tests_not_walked(tmp_path: Path) -> None:
    # Detection is bounded to root + first-level dirs; a test buried two levels
    # deep (with no config and no top-level test) is not collected here.
    deep = tmp_path / "src" / "pkg"
    deep.mkdir(parents=True)
    (deep / "test_deep.py").write_text("def test_deep():\n    assert True\n")

    assert RunTestsSkill()._detect_commands(tmp_path) == []


# --- existing config triggers are byte-identical (only flat trigger ADDED) ---

def test_tests_dir_path_unchanged(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_pyproject_path_unchanged(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_pytest_ini_path_unchanged(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [_pytest_cmd(tmp_path)]


def test_package_json_path_unchanged(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x"}\n')
    cmds = RunTestsSkill()._detect_commands(tmp_path)
    assert cmds == [["npm", "test", "--", "--runInBand"]]


# --- determinism -------------------------------------------------------------

def test_detection_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert True\n")
    skill = RunTestsSkill()
    first = skill._detect_commands(tmp_path)
    second = skill._detect_commands(tmp_path)
    assert first == second == [_pytest_cmd(tmp_path)]


# --- src-layout PYTHONPATH: the bare-stem import gap is unblocked -------------

def test_src_layout_bare_import_runs_green(tmp_path: Path) -> None:
    # The separated layout (``src/calc.py`` + ``tests/test_calc.py`` doing
    # ``import calc``): with only the root on PYTHONPATH this was a collection
    # ERROR misread as RED; now ``src`` is on the path and a correct impl is GREEN.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "import calc\n"
        "def test_add():\n    assert calc.add(1, 2) == 3\n")

    assert RunTestsSkill().run(tmp_path).ok is True


def test_flat_layout_path_is_single_root(tmp_path: Path) -> None:
    # Regression guard for shadowing: a flat-root project keeps ONLY the root on
    # the import path (no src/lib widening), so its command shape is unchanged.
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n")

    assert RunTestsSkill()._import_roots(tmp_path) == [str(tmp_path.resolve())]
