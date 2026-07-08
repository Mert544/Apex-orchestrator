"""Falsifiable tests for conftest-linkage widening in the covering scope — the
fix for the audit's fixture-blindness finding: a module imported ONLY by
``tests/conftest.py`` (the classic fixture pattern) got the covering scope
``['tests/conftest.py']``, and pytest collects NOTHING from a conftest (exit
5) — so the per-move gate verified nothing: a false red in absolute mode
(every correct move on that module rolled back with "impacted tests failed"),
and before the delta validity guard, a fake green in delta mode.

The fix replaces a matched conftest with the test files its fixtures actually
serve (everything under its directory), and lets a conftest with no tests
below it expand to nothing (full-suite fallback). Each semantic test here
failed on the pre-fix code.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.mutation_tester import covering_test_files
from app.engine.test_impact import impacted_test_files
from app.execution.cross_file_rename import RenamePlan, apply_rename


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_project(tmp_path: Path) -> Path:
    """pkg/calc.py is imported ONLY by tests/conftest.py; the test consumes it
    through the fixture and imports nothing from the package itself."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/conftest.py",
           "import pytest\nfrom pkg.calc import add\n\n\n"
           "@pytest.fixture\ndef adder():\n    return add\n")
    _write(tmp_path, "tests/test_use_fixture.py",
           "def test_add(adder):\n    assert adder(1, 2) == 3\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")
    return tmp_path


def test_conftest_only_linkage_widens_to_served_tests(tmp_path):
    _fixture_project(tmp_path)
    covering = covering_test_files(tmp_path, "pkg/calc.py")
    assert "tests/test_use_fixture.py" in covering
    assert "tests/conftest.py" not in covering  # not collectible — never passed to pytest


def test_impacted_tests_inherit_the_widening(tmp_path):
    _fixture_project(tmp_path)
    impacted = impacted_test_files(tmp_path, ["pkg/calc.py"])
    assert "tests/test_use_fixture.py" in impacted
    assert "tests/conftest.py" not in impacted


def test_conftest_with_no_tests_below_expands_to_nothing(tmp_path):
    # The honest degrade: a conftest linkage with no runnable tests under it
    # yields an EMPTY scope, so the caller falls back to the full suite instead
    # of "verifying" against a run that collects nothing.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/conftest.py", "from pkg.calc import add\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")
    assert covering_test_files(tmp_path, "pkg/calc.py") == []


def test_scoped_verify_now_lands_a_correct_change(tmp_path):
    # THE under-delivery this fixes: a harmless edit to the fixture-linked
    # module used to be rolled back as a false red (the scoped run collected
    # nothing, exit 5). It must now verify green against the fixture-using test.
    _fixture_project(tmp_path)
    original = (tmp_path / "pkg" / "calc.py").read_text(encoding="utf-8")
    plan = RenamePlan(old="pkg/calc.py", new="edit")
    plan.originals["pkg/calc.py"] = original
    plan.new_contents["pkg/calc.py"] = "def add(a, b):\n    return a + b  # tidy\n"
    plan.edits_by_file["pkg/calc.py"] = 1
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)
    assert res["applied"] is True and res["verified"] is True
    assert res["test_evidence"]["scoped"] is True
    assert "tests/test_use_fixture.py" in res["test_evidence"]["tests"]


def test_scoped_verify_still_blocks_a_breaking_change(tmp_path):
    # Soundness control: the widened scope actually RUNS the fixture-using
    # test, so a behavior break is caught and rolled back.
    _fixture_project(tmp_path)
    original = (tmp_path / "pkg" / "calc.py").read_text(encoding="utf-8")
    plan = RenamePlan(old="pkg/calc.py", new="edit")
    plan.originals["pkg/calc.py"] = original
    plan.new_contents["pkg/calc.py"] = "def add(a, b):\n    return a - b\n"
    plan.edits_by_file["pkg/calc.py"] = 1
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)
    assert res["applied"] is False and res["rolled_back"] is True
    assert (tmp_path / "pkg" / "calc.py").read_text(encoding="utf-8") == original


def test_widening_is_deterministic(tmp_path):
    _fixture_project(tmp_path)
    first = covering_test_files(tmp_path, "pkg/calc.py")
    second = covering_test_files(tmp_path, "pkg/calc.py")
    assert first == second == sorted(first)
