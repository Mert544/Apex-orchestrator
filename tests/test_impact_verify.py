"""Tests for impact-scoped verification — the keystone that lets the organism
gate a move against only the tests that exercise it, fast enough to develop its
own large body. The full suite stays the backstop (used when nothing covers a
change).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.test_impact import impacted_test_files
from app.execution.cross_file_rename import RenamePlan, apply_rename


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "core.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "lonely.py").write_text(
        "def g():\n    return 9\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\ndef test_f():\n    assert f() == 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _edit_plan(rel: str, original: str, new: str) -> RenamePlan:
    plan = RenamePlan(old=rel, new="edit")
    plan.originals[rel] = original
    plan.new_contents[rel] = new
    plan.edits_by_file[rel] = 1
    return plan


# --- impacted_test_files ------------------------------------------------------

def test_covering_test_is_impacted(tmp_path):
    _project(tmp_path)
    assert impacted_test_files(tmp_path, ["app/core.py"]) == ["tests/test_core.py"]


def test_changed_test_file_includes_itself(tmp_path):
    _project(tmp_path)
    assert "tests/test_core.py" in impacted_test_files(tmp_path, ["tests/test_core.py"])


def test_uncovered_module_has_no_impacted_tests(tmp_path):
    _project(tmp_path)
    assert impacted_test_files(tmp_path, ["app/lonely.py"]) == []


def test_worktree_test_copies_are_excluded(tmp_path):
    # Agent git worktrees live under `.claude/worktrees/<id>/` as full repo
    # copies. Walking into them would double-count the covering test and collide
    # its basename, blocking every develop move. They must be skipped so only the
    # real `tests/test_core.py` is returned.
    _project(tmp_path)
    wt = tmp_path / ".claude" / "worktrees" / "agent-x" / "tests"
    wt.mkdir(parents=True)
    (wt / "test_core.py").write_text(
        "from app.core import f\ndef test_f():\n    assert f() == 1\n", encoding="utf-8")
    assert impacted_test_files(tmp_path, ["app/core.py"]) == ["tests/test_core.py"]


# --- apply_rename(impact_scope=True) ------------------------------------------

def test_scoped_keeps_a_passing_change(tmp_path):
    _project(tmp_path)
    plan = _edit_plan("app/core.py", "def f():\n    return 1\n",
                      "def f():\n    return 1  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)
    assert res["applied"] is True and res["verified"] is True
    assert res["test_evidence"]["scoped"] is True
    assert res["test_evidence"]["tests"] == ["tests/test_core.py"]
    assert "# tidy" in (tmp_path / "app" / "core.py").read_text()


def test_scoped_rolls_back_a_breaking_change(tmp_path):
    _project(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before, "def f():\n    return 2\n")  # breaks test
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)
    assert res["applied"] is False and res["rolled_back"] is True
    assert res["test_evidence"]["scoped"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before  # restored


def test_scoped_falls_back_to_full_suite_when_uncovered(tmp_path):
    _project(tmp_path)
    # app/lonely.py has no covering test → scoped scope is empty → full suite runs.
    plan = _edit_plan("app/lonely.py", "def g():\n    return 9\n",
                      "def g():\n    return 9  # ok\n")
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)
    assert res["applied"] is True and res["verified"] is True
    # The full-suite path doesn't set the scoped marker.
    assert not res["test_evidence"].get("scoped")


def test_no_verify_ignores_scope(tmp_path):
    _project(tmp_path)
    plan = _edit_plan("app/core.py", "def f():\n    return 1\n", "def f():\n    return 2\n")
    res = apply_rename(tmp_path, plan, verify=False, impact_scope=True)
    assert res["applied"] is True and "verified" not in res  # no gate at all


# --- end-to-end through compile_objective -------------------------------------

def test_compile_objective_scope_verify_smoke(tmp_path):
    # A modernizable module with a covering test: scoped verification keeps the
    # verified move and the suite stays green.
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def f(x):\n    if x == None:\n        return 0\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\ndef test_f():\n    assert f(None) == 0\n    assert f(3) == 3\n",
        encoding="utf-8")
    from app.engine.objective_compiler import compile_objective
    result = compile_objective(str(tmp_path), objective="modernize", apply=True,
                               verify=True, scope_verify=True)
    assert result.steps  # it landed a verified move
    assert "is None" in (tmp_path / "app" / "core.py").read_text()
