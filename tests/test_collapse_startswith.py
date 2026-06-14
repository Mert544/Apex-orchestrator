"""Tests for the collapse-startswith objective: registered, on the fast board,
and actionable on a ``startswith(a) or startswith(b)`` or-chain — collapsing it
into a single ``startswith((a, b))`` call while preserving behaviour.

The objective itself is a thin self-registration wrapper over
``plan_collapse_startswith``; these tests pin that it surfaces in the registry
with the right wiring and rewrites real source end-to-end.
"""

from __future__ import annotations

from pathlib import Path

# An or-chain the collapse transform targets: two startswith calls on the same
# subject joined by `or`, plus an endswith chain to exercise both branches.
_OR_CHAIN = '''\
def f(x):
    if x.startswith("a") or x.startswith("b"):
        return 1
    if x.endswith(".py") or x.endswith(".pyi"):
        return 2
    return 0
'''


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_OR_CHAIN, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives

    assert "collapse-startswith" in available_objectives()
    assert "collapse-startswith" not in expensive_names()


def test_registered_spec_shape():
    from app.engine import develop_registry

    develop_registry.discover()
    spec = develop_registry._REGISTRY["collapse-startswith"]
    assert spec.name == "collapse-startswith"
    assert callable(spec.fitness)
    assert callable(spec.moves)


def test_fitness_and_moves_on_or_chain(tmp_path):
    from app.engine import develop_registry

    develop_registry.discover()
    spec = develop_registry._REGISTRY["collapse-startswith"]
    root = _project(tmp_path)

    assert spec.fitness(str(root)) >= 1.0
    moves = spec.moves(str(root))
    assert moves, "should propose a collapse move"
    mv = moves[0]
    assert mv.operator == "collapse_startswith"
    assert mv.target == "app/m.py:collapse-startswith"
    assert mv.description == "collapse startswith/endswith or-chains in app/m.py"


def test_collapse_rewrites_into_tuple(tmp_path):
    from app.execution.startswith_tuple import plan_collapse_startswith

    root = _project(tmp_path)
    plan = plan_collapse_startswith(str(root), "app/m.py")
    new = plan.new_contents["app/m.py"]

    # The two or-chains became single tuple-arg calls.
    assert 'x.startswith(("a", "b"))' in new
    assert 'x.endswith((".py", ".pyi"))' in new
    assert " or " not in new

    # Behaviour preserved across both startswith and endswith branches.
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    f = ns["f"]
    assert f("apple") == 1
    assert f("banana") == 1
    assert f("module.py") == 2
    assert f("stub.pyi") == 2
    assert f("zebra") == 0


def test_no_move_on_clean_module(tmp_path):
    from app.execution.startswith_tuple import plan_collapse_startswith

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "clean.py").write_text(
        'def g(x):\n    return x.startswith("a")\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    plan = plan_collapse_startswith(str(tmp_path), "app/clean.py")
    # A single, non-or-chained call is already minimal: nothing to collapse.
    assert plan.new_contents == {} or "app/clean.py" not in plan.new_contents


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective

    root = _project(tmp_path)
    result = compile_objective(str(root), objective="collapse-startswith",
                               apply=True, verify=False)
    assert result.steps, "an explicit run should land the collapse move"
    new = (root / "app" / "m.py").read_text()
    assert 'x.startswith(("a", "b"))' in new
