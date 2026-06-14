"""Tests for the dedup-parameterized objective: registered, EXPENSIVE (off the
fast plan/ascend board), and actionable on a constant-only near-duplicate.
"""

from __future__ import annotations

from pathlib import Path


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # Two functions, structurally identical, differing in ONE constant (10 vs 20).
    (tmp_path / "app" / "m.py").write_text(
        "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 10\n    return d\n\n\n"
        "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 20\n    return d\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    assert "dedup-parameterized" in available_objectives()
    # The near_dup detector is ~1.8s after the O(1) segment-slicing rewrite, so
    # the objective no longer carries the expensive flag.
    assert "dedup-parameterized" not in expensive_names()


def test_on_the_default_fast_board(tmp_path):
    # No longer expensive → the fast plan/ascend board (no explicit list) includes it.
    from app.engine.ascend import rank_objectives
    _project(tmp_path)
    board = {r.objective for r in rank_objectives(str(tmp_path))}
    assert "dedup-parameterized" in board


def test_actionable_on_a_constant_near_duplicate(tmp_path):
    from app.execution.objectives.dedup_parameterized import fitness, moves
    root = _project(tmp_path)
    assert fitness(str(root)) >= 1.0
    mv = moves(str(root))
    assert mv, "should propose a parameterizing move"
    plan = mv[0].build_plan()
    assert plan.new_contents, f"the move should produce a rewrite, blockers={plan.blockers}"
    new = plan.new_contents["app/m.py"]
    # The differing constant became a parameter; both call sites pass their own value.
    assert "def _shared_1(" in new
    assert "return _shared_1(n, 10)" in new and "return _shared_1(n, 20)" in new
    # Behaviour preserved.
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    assert ns["alpha"](5) == 25 and ns["beta"](5) == 35


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective
    root = _project(tmp_path)
    result = compile_objective(str(root), objective="dedup-parameterized",
                               apply=True, verify=False)
    assert result.steps, "an explicit run should land the parameterizing move"
    new = (root / "app" / "m.py").read_text()
    assert "_shared_1" in new and "c + p0" in new
