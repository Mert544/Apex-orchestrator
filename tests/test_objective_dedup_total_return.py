"""Tests for the dedup-total-return objective: registered, on the fast board,
and actionable on an exact-duplicate block whose every exit path returns — the
control-flow slice the base dedup objective leaves behind.
"""

from __future__ import annotations

from pathlib import Path

# A 6-statement block (>= the dedup detector's default min_statements=5) whose
# every exit path returns: a guard return plus a final return. dedup_extract
# blocks this (non-tail return); dedup_total_return lifts it.
_TOTAL_RETURN_DUP = '''\
def alpha(cond, a, b):
    z = a + b
    w = z * 2
    q = w + 1
    r = q - 3
    if cond:
        return r
    return z


def beta(cond, a, b):
    z = a + b
    w = z * 2
    q = w + 1
    r = q - 3
    if cond:
        return r
    return z
'''


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_TOTAL_RETURN_DUP, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    assert "dedup-total-return" in available_objectives()
    # Same exact-dup detector the fast board already runs for `dedup` — not gated.
    assert "dedup-total-return" not in expensive_names()


def test_on_the_default_fast_board(tmp_path):
    from app.engine.ascend import rank_objectives
    _project(tmp_path)
    board = {r.objective for r in rank_objectives(str(tmp_path))}
    assert "dedup-total-return" in board


def test_actionable_on_total_return_duplicate(tmp_path):
    from app.execution.objectives.dedup_total_return import fitness, moves
    root = _project(tmp_path)
    assert fitness(str(root)) >= 1.0
    mv = moves(str(root))
    assert mv, "should propose a lifting move"
    assert mv[0].operator == "dedup_total_return"
    plan = mv[0].build_plan()
    assert plan.new_contents, f"the move should produce a rewrite, blockers={plan.blockers}"
    new = plan.new_contents["app/m.py"]
    helper = plan.new
    # Both copies became `return _shared(...)`; the body is no longer repeated.
    assert new.count(f"return {helper}(") == 2
    assert new.count("q = w + 1") == 1
    # Behaviour preserved.
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    assert ns["alpha"](True, 2, 3) == ns["beta"](True, 2, 3)
    assert ns["alpha"](False, 2, 3) == ns["beta"](False, 2, 3)


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective
    root = _project(tmp_path)
    result = compile_objective(str(root), objective="dedup-total-return",
                               apply=True, verify=False)
    assert result.steps, "an explicit run should land the lifting move"
    new = (root / "app" / "m.py").read_text()
    assert "_shared" in new and new.count("q = w + 1") == 1
