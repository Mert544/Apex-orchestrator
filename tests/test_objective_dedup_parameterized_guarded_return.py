"""Tests for the dedup-parameterized-guarded-return objective: registered, on
the fast board, actionable on the GUARD-RETURN near-duplicate shape both
siblings refuse — and provably non-contending with the whole dedup family
(disjoint admissibility by construction; the full six-member matrix lives in
tests/test_objective_dedup_parameterized_total_return.py alongside its five
family siblings, mirroring the objective compiler's own registration order).
"""

from __future__ import annotations

from pathlib import Path

# The flagship near-dup fixture: a guard return + LIVE fall-through (the
# shape both dedup-parameterized and dedup-parameterized-total-return
# refuse), ONE constant diff inside the run. The default 5-statement scan
# window must stop BEFORE the function's own tail return (else the window
# collapses to an always-returning shape and lands on the total-return
# sibling instead) — a live post-guard tail (``log.append`` + the differing
# ``return``) keeps the 5-statement guarded window itself fall-through-ended.
_GUARD_RETURN_NEAR_DUP = '''\
def build_a(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    label = f"{name}:{size}"
    log.append(label)
    return f"A:{label}"


def build_b(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 3
    label = f"{name}:{size}"
    log.append(label)
    return f"B:{label}"
'''


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_GUARD_RETURN_NEAR_DUP, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    assert "dedup-parameterized-guarded-return" in available_objectives()
    # Same memoized near-dup detector the fast board already runs for
    # dedup-parameterized — not gated.
    assert "dedup-parameterized-guarded-return" not in expensive_names()


def test_on_the_default_fast_board(tmp_path):
    from app.engine.ascend import rank_objectives
    _project(tmp_path)
    board = {r.objective for r in rank_objectives(str(tmp_path))}
    assert "dedup-parameterized-guarded-return" in board


def test_actionable_on_guard_return_near_duplicate(tmp_path):
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        fitness,
        moves,
    )
    root = _project(tmp_path)
    assert fitness(str(root)) >= 1.0
    mv = moves(str(root))
    assert mv, "should propose a lifting move"
    assert mv[0].operator == "dedup_parameterized_guarded_return"
    assert "near-dup-guarded-return-" in mv[0].target
    assert "sentinel-projecting" in mv[0].description
    plan = mv[0].build_plan()
    assert plan.new_contents, f"the move should produce a rewrite, blockers={plan.blockers}"
    new = plan.new_contents["app/m.py"]
    helper = plan.new
    # The guard survives inside the helper; both copies GUARD the sentinel.
    assert "if item is None:" in new and 'return "missing"' in new
    assert new.count(f"= {helper}(") == 2
    # Behaviour preserved: exec-equivalent to the ORIGINAL source.
    before: dict = {}
    exec(compile(_GUARD_RETURN_NEAR_DUP, "<orig>", "exec"), before)  # noqa: S102
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    data = {"k": {"name": "n", "size": 4}}
    for fn in ("build_a", "build_b"):
        b_log: list = []
        a_log: list = []
        assert before[fn](data, "k", b_log) == ns[fn](data, "k", a_log)
        assert b_log == a_log
        b_log, a_log = [], []
        assert before[fn](data, "nope", b_log) == ns[fn](data, "nope", a_log) \
            == "missing"


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective
    root = _project(tmp_path)
    result = compile_objective(
        str(root), objective="dedup-parameterized-guarded-return",
        apply=True, verify=False)
    assert result.steps, "an explicit run should land the lifting move"
    new = (root / "app" / "m.py").read_text()
    # Descriptive helper name from the shared "build" token (not the
    # `_shared_<n>` fallback the total-return sibling's alpha/beta pair uses).
    assert "def _build(" in new
    assert "_MISS = object()" in new
    assert new.count("= _build(") == 2


def test_actionable_groups_empty_on_a_project_with_no_guard_return_near_dup(
    tmp_path,
):
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        _actionable_groups,
        fitness,
    )
    (tmp_path / "m.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8")
    assert _actionable_groups(str(tmp_path)) == []
    assert fitness(str(tmp_path)) == 0.0


def test_moves_target_is_module_qualified(tmp_path):
    from app.execution.objectives.dedup_parameterized_guarded_return import moves
    root = _project(tmp_path)
    mv = moves(str(root))
    assert mv[0].target.startswith("app/m.py:near-dup-guarded-return-")
