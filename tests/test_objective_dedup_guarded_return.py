"""Tests for the dedup-guarded-return objective: registered, on the fast board,
actionable on the guard-prelude duplicate shape both dedup siblings refuse —
and provably non-contending with them (disjoint admissibility by construction).
"""

from __future__ import annotations

from pathlib import Path

# A 5-statement shared prelude (== the dedup detector's default min_statements)
# with a guard return AND a live fall-through: the tails differ, and `label`
# projects out of the block. dedup_extract blocks this (non-tail return);
# dedup_total_return blocks it too (control can fall off the block's end);
# dedup_guarded_return lifts it.
_GUARDED_DUP = '''\
def build_a(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    label = f"{name}:{size}"
    log.append("a")
    return "A-" + label


def build_b(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    label = f"{name}:{size}"
    log.append("b")
    return "B-" + label
'''


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_GUARDED_DUP, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    assert "dedup-guarded-return" in available_objectives()
    # Same exact-dup detector the fast board already runs for `dedup` — not gated.
    assert "dedup-guarded-return" not in expensive_names()


def test_on_the_default_fast_board(tmp_path):
    from app.engine.ascend import rank_objectives
    _project(tmp_path)
    board = {r.objective for r in rank_objectives(str(tmp_path))}
    assert "dedup-guarded-return" in board


def test_actionable_on_guard_prelude_duplicate(tmp_path):
    from app.execution.objectives.dedup_guarded_return import fitness, moves
    root = _project(tmp_path)
    assert fitness(str(root)) >= 1.0
    mv = moves(str(root))
    assert mv, "should propose a lifting move"
    assert mv[0].operator == "dedup_guarded_return"
    plan = mv[0].build_plan()
    assert plan.new_contents, f"the move should produce a rewrite, blockers={plan.blockers}"
    new = plan.new_contents["app/m.py"]
    # Both copies became a sentinel-guarded call; the body is no longer repeated.
    assert new.count("= object()") == 1
    assert new.count("item = data.get(key)") == 1
    # Behaviour preserved on both paths.
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    data = {"k": {"name": "n", "size": 3}}
    assert ns["build_a"](data, "k", []) == "A-n:6"
    assert ns["build_b"](data, "k", []) == "B-n:6"
    assert ns["build_a"](data, "nope", []) == "missing"


def test_never_contends_with_the_siblings(tmp_path):
    # The SAME project through all three dedup-family objective gates: the
    # guard-prelude block is guarded-return's alone; and a total-return
    # specimen is refused by guarded-return (disjoint complements).
    from app.execution.objectives.dedup_guarded_return import (
        fitness as guarded_fitness,
    )
    from app.execution.objectives.dedup_total_return import (
        fitness as total_fitness,
    )
    root = _project(tmp_path)
    assert guarded_fitness(str(root)) >= 1.0
    assert total_fitness(str(root)) == 0.0


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective
    root = _project(tmp_path)
    result = compile_objective(str(root), objective="dedup-guarded-return",
                               apply=True, verify=False)
    assert result.steps, "an explicit run should land the lifting move"
    new = (root / "app" / "m.py").read_text()
    assert "= object()" in new and new.count("item = data.get(key)") == 1
