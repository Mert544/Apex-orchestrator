"""Tests for the dedup-parameterized-total-return objective: registered, on
the fast board, actionable on the ALWAYS-RETURNING near-duplicate shape its
sibling refuses — and provably non-contending with the whole dedup family
(disjoint admissibility by construction).
"""

from __future__ import annotations

from pathlib import Path

# The flagship near-dup fixture (guard return + tail return, ONE constant
# diff), verbatim from tests/test_near_dup_extract.py:313-330 /
# tests/test_near_dup_total_return_eyml.py — the shape dedup-parameterized
# refuses (an early, non-tail return) and this objective lifts.
_EARLY_RETURN = '''\
def alpha(n):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 10
    return c


def beta(n):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 20
    return c
'''


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_EARLY_RETURN, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_registered_and_not_expensive():
    from app.engine.develop_registry import expensive_names
    from app.engine.objective_compiler import available_objectives
    assert "dedup-parameterized-total-return" in available_objectives()
    # Same memoized near-dup detector the fast board already runs for
    # dedup-parameterized — not gated.
    assert "dedup-parameterized-total-return" not in expensive_names()


def test_on_the_default_fast_board(tmp_path):
    from app.engine.ascend import rank_objectives
    _project(tmp_path)
    board = {r.objective for r in rank_objectives(str(tmp_path))}
    assert "dedup-parameterized-total-return" in board


def test_actionable_on_always_returning_near_duplicate(tmp_path):
    from app.execution.objectives.dedup_parameterized_total_return import (
        fitness,
        moves,
    )
    root = _project(tmp_path)
    assert fitness(str(root)) >= 1.0
    mv = moves(str(root))
    assert mv, "should propose a lifting move"
    assert mv[0].operator == "dedup_parameterized_total_return"
    plan = mv[0].build_plan()
    assert plan.new_contents, f"the move should produce a rewrite, blockers={plan.blockers}"
    new = plan.new_contents["app/m.py"]
    helper = plan.new
    # The guard survives inside the helper; both copies RETURN the helper.
    assert "if a > 5:" in new and "return a" in new
    assert new.count(f"return {helper}(") == 2
    # Behaviour preserved: exec-equivalent to the ORIGINAL source (not a
    # hand-derived relationship — the guard path returns the SAME value on
    # both sides, only the non-guard path's constant differs).
    before: dict = {}
    exec(compile(_EARLY_RETURN, "<orig>", "exec"), before)  # noqa: S102
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102 - controlled test src
    for n in (0, 3, 6, 20):
        assert ns["alpha"](n) == before["alpha"](n)
        assert ns["beta"](n) == before["beta"](n)


def test_compile_objective_can_run_it(tmp_path):
    from app.engine.objective_compiler import compile_objective
    root = _project(tmp_path)
    result = compile_objective(str(root), objective="dedup-parameterized-total-return",
                               apply=True, verify=False)
    assert result.steps, "an explicit run should land the lifting move"
    new = (root / "app" / "m.py").read_text()
    assert "_shared" in new and new.count("return _shared") == 2


# ══════════════════════════════════════════════════════════════════════════
# The MANDATORY five-member non-contention matrix: each fixture scores
# actionable on EXACTLY ONE of {dedup, dedup-total-return, dedup-guarded-
# return, dedup-parameterized, dedup-parameterized-total-return} and is
# refused by the other four — the dedup family's admissibility shapes are
# disjoint complements by construction, so the five never contend for the
# same block/group.
#
# "dedup" (base) uses an ACTIONABLE-filtered proxy (does ``plan_dedup_extract``
# actually land a rewrite on the SAME detected block?) rather than the raw
# ``duplication_fitness`` scalar: that scalar counts every block the DETECTOR
# finds, including total-return/guarded-return-shaped ones dedup_extract
# itself refuses, so it is not actionable-filtered like its four self-
# registered siblings and would show false "contention" on shapes it can
# never actually touch — the matrix compares what each objective would
# REALLY land, not a raw detector count.
# ══════════════════════════════════════════════════════════════════════════

_ALL_FIVE = ("dedup", "dedup-total-return", "dedup-guarded-return",
            "dedup-parameterized", "dedup-parameterized-total-return")


def _actionable_counts(root: Path) -> dict[str, float]:
    """``{objective: actionable_count}`` for all five dedup-family objectives
    on ``root`` — each computed by calling the REAL lander (never a proxy),
    so "actionable" means "this objective's own transform would land a
    rewrite here", the honest definition non-contention needs."""
    from app.engine.dedup import find_duplicates
    from app.execution.dedup_extract import plan_dedup_extract
    from app.execution.objectives.dedup_guarded_return import (
        fitness as guarded_fitness,
    )
    from app.execution.objectives.dedup_parameterized import (
        fitness as parameterized_fitness,
    )
    from app.execution.objectives.dedup_parameterized_total_return import (
        fitness as parameterized_total_return_fitness,
    )
    from app.execution.objectives.dedup_total_return import (
        fitness as total_return_fitness,
    )

    dedup_actionable = sum(
        1 for b in find_duplicates(str(root))
        if plan_dedup_extract(root, b).new_contents)
    return {
        "dedup": float(dedup_actionable),
        "dedup-total-return": total_return_fitness(str(root)),
        "dedup-guarded-return": guarded_fitness(str(root)),
        "dedup-parameterized": parameterized_fitness(str(root)),
        "dedup-parameterized-total-return":
            parameterized_total_return_fitness(str(root)),
    }


def _assert_exactly_one_actionable(root: Path, expect: str) -> None:
    counts = _actionable_counts(root)
    for name in _ALL_FIVE:
        if name == expect:
            assert counts[name] >= 1.0, f"{expect} fixture: {name} = {counts}"
        else:
            assert counts[name] == 0.0, f"{expect} fixture: {name} = {counts}"


# 1. dedup (base): a plain block, no return anywhere.
_DEDUP_BASE = '''\
def alpha(x):
    a = x + 1
    b = a * 2
    c = b + 3
    d = c - 1
    print(d)


def beta(x):
    a = x + 1
    b = a * 2
    c = b + 3
    d = c - 1
    print(d)
'''

# 2. dedup-total-return: exact-dup, always-returns (no fall-through).
_MATRIX_TOTAL_RETURN = '''\
def alpha(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    c = b + 1
    return c


def beta(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    c = b + 1
    return c
'''

# 3. dedup-guarded-return: exact-dup, guard return + LIVE fall-through.
# Adapted from tests/test_objective_dedup_guarded_return.py's own fixture,
# with the post-guard markers widened from STRING constants to module-level
# NAMEs (TAG_*/PREFIX_*): the exact-dup detector's byte-identical fingerprint
# still only matches the guard+prelude window (differing markers make the
# trailing window non-byte-identical, so dedup-total-return never sees it) —
# and because the markers are NAMEs, not Constants, the separate NEAR-DUP
# detector's more permissive matching, which WOULD otherwise group the
# trailing window on its differing constants, is refused by
# dedup-parameterized's OWN Constant-only gate (W99a defers Name holes), so
# it never contends with dedup-parameterized either.
_MATRIX_GUARDED = '''\
TAG_A = "a"
TAG_B = "b"
PREFIX_A = "A-"
PREFIX_B = "B-"


def build_a(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    label = f"{name}:{size}"
    log.append(TAG_A)
    return PREFIX_A + label


def build_b(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    label = f"{name}:{size}"
    log.append(TAG_B)
    return PREFIX_B + label
'''

# 4. dedup-parameterized: near-dup, plain/tail-return, one constant diff.
_MATRIX_PARAMETERIZED = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d


def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''


def _write_single(tmp_path: Path, src: str) -> Path:
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    return tmp_path


def test_matrix_dedup_base_is_the_only_actionable_objective(tmp_path):
    _write_single(tmp_path, _DEDUP_BASE)
    _assert_exactly_one_actionable(tmp_path, "dedup")


def test_matrix_dedup_total_return_is_the_only_actionable_objective(tmp_path):
    _write_single(tmp_path, _MATRIX_TOTAL_RETURN)
    _assert_exactly_one_actionable(tmp_path, "dedup-total-return")


def test_matrix_dedup_guarded_return_is_the_only_actionable_objective(tmp_path):
    _write_single(tmp_path, _MATRIX_GUARDED)
    _assert_exactly_one_actionable(tmp_path, "dedup-guarded-return")


def test_matrix_dedup_parameterized_is_the_only_actionable_objective(tmp_path):
    _write_single(tmp_path, _MATRIX_PARAMETERIZED)
    _assert_exactly_one_actionable(tmp_path, "dedup-parameterized")


def test_matrix_early_return_near_dup_is_the_only_actionable_objective(tmp_path):
    # The REQUIRED three-way row: the flagship _EARLY_RETURN near-dup fixture
    # (guard return + tail return, one constant diff) lands ONLY on
    # dedup-parameterized-total-return — dedup-parameterized refuses it (an
    # early, non-tail return), and the three EXACT-dup siblings never see it
    # at all (the near-dup detector requires >=1 differing leaf; the exact
    # detector requires byte-identical copies, and this group differs).
    _write_single(tmp_path, _EARLY_RETURN)
    _assert_exactly_one_actionable(tmp_path, "dedup-parameterized-total-return")
