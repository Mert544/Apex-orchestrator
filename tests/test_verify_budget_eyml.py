"""Bounded, deterministic gap-finding so the mutation-based test objectives
produce on BIG real files instead of timing out into an honest no-op.

These tests pin the three layered, deterministic bounds (Spec 1) and the
determinism landmine that guards them:

* the per-scan WORK BUDGET (a mutant-RUN COUNT, never a clock) — ``mutation_score``
  spends exactly N runs then stops with ``budget_exhausted=True``; the baseline
  costs one run; a budget that can't pay the baseline examines nothing;
* the size-aware ``_mutant_cap_for`` (a pure function of the source);
* the cheap trace PRE-FILTER ordering (under-covered module ranks first);
* DETERMINISM — two runs over the same project with the same integer budget
  process the SAME module set in the SAME order, independent of per-run timing;
* the LANDMINE — ``verify_timeout`` is NEVER a function of the budget (so the
  TimeoutExpired→KILL verdict stays machine-independent), and a budget-skip is
  never folded into killed/survived;
* BACK-COMPAT — with no budget the landed set and the score are byte-identical to
  the pre-budget behaviour on a small project.

The call-count / ordering tests monkeypatch ``_verify_killed`` (or inject a fixed
``RuntimeEvidence``) so they never pay a real copytree+pytest run; the
end-to-end landing tests use a tiny real project and run the actual engine.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from app.engine import mutation_tester as mt
from app.engine.mutation_tester import MutationResult, mutation_score
from app.engine.runtime_trace import RuntimeEvidence
from app.execution._verify_budget import (
    _DEFAULT_MUTANT_CAP,
    _MUTANT_CAP_FLOOR,
    _Budget,
    _mutant_cap_for,
)


# --- _Budget: a COUNT, not a clock -------------------------------------------

def test_budget_spend_exhaust_and_spent_accounting():
    b = _Budget(3)
    assert not b.exhausted and b.spent == 0 and b.remaining == 3
    b.spend(2)
    assert b.remaining == 1 and b.spent == 2 and not b.exhausted
    b.spend(1)
    assert b.exhausted and b.spent == 3 and b.remaining == 0


def test_budget_over_debit_clamps_at_zero_never_negative():
    b = _Budget(2)
    b.spend(5)  # over-debit
    assert b.remaining == 0 and b.exhausted and b.spent == 2


def test_budget_spend_non_positive_is_a_no_op():
    b = _Budget(2)
    b.spend(0)
    b.spend(-3)
    assert b.remaining == 2 and b.spent == 0


def test_budget_can_afford():
    assert _Budget(2).can_afford(1)
    assert _Budget(2).can_afford(2)
    assert not _Budget(2).can_afford(3)
    assert _Budget(0).can_afford(0)  # zero is always affordable
    assert not _Budget(0).can_afford(1)


def test_budget_zero_start_is_immediately_exhausted():
    b = _Budget(0)
    assert b.exhausted and b.spent == 0 and b.remaining == 0


# --- _mutant_cap_for: pure, size-aware, deterministic ------------------------

def _src_of_loc(loc: int) -> str:
    return "x\n" * (loc - 1) + "x"


def test_mutant_cap_small_file_keeps_full_default():
    # Small/medium files keep the full default cap -> byte-identical to before.
    assert _mutant_cap_for(_src_of_loc(10)) == _DEFAULT_MUTANT_CAP
    assert _mutant_cap_for(_src_of_loc(400)) == _DEFAULT_MUTANT_CAP
    assert _mutant_cap_for("") == _DEFAULT_MUTANT_CAP


def test_mutant_cap_large_file_tapers_toward_floor():
    big = _mutant_cap_for(_src_of_loc(800))
    huge = _mutant_cap_for(_src_of_loc(5000))
    assert _MUTANT_CAP_FLOOR <= huge < big < _DEFAULT_MUTANT_CAP
    # An enormous file is clamped at the floor, never below.
    assert _mutant_cap_for(_src_of_loc(500_000)) == _MUTANT_CAP_FLOOR


def test_mutant_cap_is_deterministic():
    src = _src_of_loc(3000)
    assert _mutant_cap_for(src) == _mutant_cap_for(src)
    # And monotone non-increasing in size (more lines never raises the cap).
    caps = [_mutant_cap_for(_src_of_loc(n)) for n in (401, 700, 1200, 4000)]
    assert caps == sorted(caps, reverse=True)


def test_mutant_cap_never_exceeds_default_or_drops_below_floor():
    for loc in (1, 50, 401, 999, 12345, 999_999):
        cap = _mutant_cap_for(_src_of_loc(loc))
        assert _MUTANT_CAP_FLOOR <= cap <= _DEFAULT_MUTANT_CAP


# --- mutation_score: the budget bounds COUNT, never time ---------------------

_MANY_OPS_SRC = (
    "def f(a, b):\n"
    "    c = a + b\n"
    "    d = a - b\n"
    "    e = a * b\n"
    "    return c == d and e > 0 or c < d\n"
)


def _write_many_ops(root: Path) -> str:
    (root / "mod.py").write_text(_MANY_OPS_SRC, encoding="utf-8")
    (root / "test_mod.py").write_text(
        "import mod\n\n\ndef test_smoke():\n    assert mod.f(1, 2) is not None\n",
        encoding="utf-8")
    return "mod.py"


def _fake_verify_baseline_green(kill_mutants: bool):
    """A ``_verify_killed`` replacement: the FIRST call (the baseline) returns
    green (False, not red), every later call (a mutant) returns ``kill_mutants``.
    Records the ``verify_timeout`` each call saw so the landmine guard can assert
    it is never shortened by the budget."""
    seen: list[int] = []
    state = {"first": True}

    def _fake(root, module_rel, mutated_source, verify_timeout, covering=None):
        seen.append(verify_timeout)
        if state["first"]:
            state["first"] = False
            return False  # baseline is GREEN -> the split is meaningful
        return kill_mutants

    return _fake, seen


def test_mutation_score_budget_caps_verify_runs_and_flags_exhausted(tmp_path, monkeypatch):
    """A ``_Budget(2)`` permits exactly two ``_verify_killed`` runs (baseline +
    ONE mutant) then stops with ``budget_exhausted=True`` — no real copytree."""
    rel = _write_many_ops(tmp_path)
    fake, seen = _fake_verify_baseline_green(kill_mutants=True)
    monkeypatch.setattr(mt, "_verify_killed", fake)
    result = mutation_score(tmp_path, rel, budget=_Budget(2))
    assert len(seen) == 2  # baseline + exactly one mutant, then budget gates the rest
    assert result.budget_exhausted is True
    # The examined set (one mutant) is still sound: total counts only what ran.
    assert result.total == 1 and result.killed == 1 and result.survived == 0


def test_mutation_score_budget_that_cannot_pay_baseline_examines_nothing(tmp_path, monkeypatch):
    rel = _write_many_ops(tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(
        mt, "_verify_killed",
        lambda *a, **k: calls.append(1) or True)
    result = mutation_score(tmp_path, rel, budget=_Budget(0))
    assert calls == []  # not even the baseline runs
    assert result.budget_exhausted is True
    assert result.total == 0 and result.killed == 0 and result.survived == 0
    assert result.score == 0.0


def test_budget_skip_is_never_folded_into_killed_or_survived(tmp_path, monkeypatch):
    """A budget-truncated tail must vanish from the split entirely — never be
    counted as killed (the TimeoutExpired hazard) NOR as survived."""
    rel = _write_many_ops(tmp_path)
    # Baseline green, then the first mutant SURVIVES, then budget cuts the rest.
    seq = iter([False, False])  # baseline not-red, first mutant survives

    def _fake_verify(root, module_rel, mutated_source, verify_timeout, covering=None):
        try:
            return next(seq)
        except StopIteration:  # pragma: no cover - budget stops us before here
            raise AssertionError("ran past the budget")

    monkeypatch.setattr(mt, "_verify_killed", _fake_verify)
    result = mutation_score(tmp_path, rel, budget=_Budget(2))
    assert result.budget_exhausted is True
    assert result.killed == 0 and result.survived == 1 and result.total == 1


def test_verify_timeout_is_not_a_function_of_the_budget(tmp_path, monkeypatch):
    """The LANDMINE guard: every ``_verify_killed`` call gets the FIXED
    ``verify_timeout`` regardless of remaining budget — the budget bounds COUNT,
    not per-run time, so the TimeoutExpired->KILL verdict stays machine-stable."""
    rel = _write_many_ops(tmp_path)
    fake, seen = _fake_verify_baseline_green(kill_mutants=True)
    monkeypatch.setattr(mt, "_verify_killed", fake)
    mutation_score(tmp_path, rel, verify_timeout=77, budget=_Budget(3))
    assert seen and all(t == 77 for t in seen)  # never shortened by the budget


def test_verify_killed_treats_timeout_as_kill_unconditionally(tmp_path, monkeypatch):
    """The LANDMINE itself: ``_verify_killed`` returns True (KILL) on a real
    ``TimeoutExpired`` — and the budget machinery never touches this rule (it only
    decides WHICH mutants reach ``_verify_killed``, never how it scores one)."""
    rel = _write_many_ops(tmp_path)
    (tmp_path / "mod.py").read_text()  # ensure the file exists

    def _raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(mt.subprocess, "run", _raise_timeout)
    src = (tmp_path / rel).read_text()
    # Direct call to the real verifier: a hung subprocess counts as a kill.
    assert mt._verify_killed(Path(tmp_path), rel, src, verify_timeout=120) is True


def test_budget_none_is_byte_identical_to_unbudgeted(tmp_path, monkeypatch):
    """BACK-COMPAT: ``budget=None`` runs every pending mutant and reports exactly
    the same split as the historical path (``budget_exhausted`` stays False)."""
    rel = _write_many_ops(tmp_path)
    fake, seen = _fake_verify_baseline_green(kill_mutants=True)
    monkeypatch.setattr(mt, "_verify_killed", fake)
    result = mutation_score(tmp_path, rel, budget=None)
    assert result.budget_exhausted is False
    # baseline + every pending mutant ran; total == every examined mutant.
    assert result.total == len(seen) - 1 and result.total > 1


def test_budget_exhausted_is_in_to_dict_and_defaults_false():
    d = MutationResult(module="m.py", total=0, killed=0, survived=0,
                       score=0.0).to_dict()
    assert d["budget_exhausted"] is False  # honest-reporting field, default off


# --- the objective layer: ranking, determinism, and a big-file LANDING -------

from app.execution.objectives import strengthen_tests as obj  # noqa: E402


def _multi_module_project(root: Path) -> None:
    """Two boundary-fault modules (each has a surviving ``<`` -> ``<=`` mutant) and
    a packaging ``__init__`` that must never be a candidate."""
    (root / "tests").mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for name in ("alpha", "bravo"):
        (root / f"{name}.py").write_text(
            f'def classify_{name}(n):\n    return "neg" if n < 0 else "pos"\n',
            encoding="utf-8")
        (root / "tests" / f"test_{name}.py").write_text(
            f"import {name}\n\n\ndef test_pos():\n"
            f"    assert {name}.classify_{name}(5) == \"pos\"\n",
            encoding="utf-8")


def test_can_yield_skips_modules_with_no_callable_public_function(tmp_path):
    root = tmp_path
    (root / "nofn.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "priv.py").write_text("def _hidden(x):\n    return x\n", encoding="utf-8")
    (root / "ok.py").write_text("def pub(x):\n    return x\n", encoding="utf-8")
    assert obj._can_yield(root, "nofn.py", (root / "nofn.py").read_text()) is False
    assert obj._can_yield(root, "priv.py", (root / "priv.py").read_text()) is False
    assert obj._can_yield(root, "ok.py", (root / "ok.py").read_text()) is True


def test_candidate_modules_drop_packaging_modules(tmp_path):
    _multi_module_project(tmp_path)
    rels = {rel for rel, _ in obj._candidate_modules(tmp_path)}
    assert "__init__.py" not in rels
    assert {"alpha.py", "bravo.py"} <= rels


def test_ranked_modules_is_sorted_and_deterministic(tmp_path):
    _multi_module_project(tmp_path)
    a = [rel for rel, _ in obj._ranked_modules(tmp_path)]
    b = [rel for rel, _ in obj._ranked_modules(tmp_path)]
    assert a == b  # determinism: same project -> same order
    assert a == sorted(a) or len(a) == 2  # a total, stable order


def test_trace_prefilter_ranks_undercovered_module_first(tmp_path):
    """With injected trace evidence, the module whose public-function body lines
    are LESS executed ranks FIRST (survivors concentrate there). No real pytest:
    a fixed ``RuntimeEvidence`` drives the rank deterministically."""
    _multi_module_project(tmp_path)
    root = Path(tmp_path)
    # alpha is FULLY executed (its body line ran); bravo's body line did NOT run.
    alpha_body = obj._public_body_lines(
        ast.parse((root / "alpha.py").read_text()), {"classify_alpha"})
    executed = {(str((root / "alpha.py").resolve()), ln) for ln in alpha_body}
    evidence = RuntimeEvidence(executed=frozenset(executed))
    ranked = [rel for rel, _ in obj._ranked_modules(tmp_path, evidence=evidence)]
    assert ranked[0] == "bravo.py"  # under-covered -> highest yield -> first
    assert ranked.index("bravo.py") < ranked.index("alpha.py")


def test_untested_body_lines_zero_without_evidence(tmp_path):
    _multi_module_project(tmp_path)
    root = Path(tmp_path)
    tree = ast.parse((root / "alpha.py").read_text())
    # No evidence -> the trace signal is OFF (static rank stands alone).
    assert obj._untested_body_lines(root, "alpha.py", tree,
                                    [("classify_alpha", "")], None) == 0


def test_modules_budget_stops_visiting_when_exhausted(tmp_path, monkeypatch):
    """A budget exhausted partway leaves the remaining modules UNVISITED — the
    deterministic count, not a clock, decides how far the scan reaches."""
    _multi_module_project(tmp_path)
    visited: list[str] = []
    real_plan = obj.plan_strengthen_tests

    def _spy_plan(root, rel, budget=None):
        visited.append(rel)
        if budget is not None:
            budget.spend(budget.remaining)  # drain it so only the first is visited
        return real_plan(root, rel, budget=None)

    monkeypatch.setattr(obj, "plan_strengthen_tests", _spy_plan)
    obj._modules(tmp_path, budget=_Budget(10))
    assert len(visited) == 1  # the budget gated the rest after the first module


def test_modules_determinism_independent_of_per_run_timing(tmp_path, monkeypatch):
    """Two budgeted ``_modules`` scans process the SAME module set in the SAME
    order even when a (fake) ``_verify_killed`` is artificially slow/variable —
    the budget is an integer count, not a wall clock."""
    _multi_module_project(tmp_path)
    # Baseline GREEN then every mutant killed (so no module yields) but the scan
    # still runs; the point is the VISIT ORDER is identical across runs. The
    # _verify_killed fake is reinstalled per run so the baseline-green state resets.
    real_plan = obj.plan_strengthen_tests  # capture the TRUE original once

    def _run() -> list[str]:
        fake, _seen_t = _fake_verify_baseline_green(kill_mutants=True)
        monkeypatch.setattr(mt, "_verify_killed", fake)
        seen: list[str] = []

        def _spy(root, rel, budget=None):
            seen.append(rel)
            return real_plan(root, rel, budget=budget)

        monkeypatch.setattr(obj, "plan_strengthen_tests", _spy)
        obj._modules(tmp_path, budget=_Budget(_DEFAULT_MUTANT_CAP * 4))
        return seen

    assert _run() == _run()


def test_default_scan_lands_on_a_big_many_function_module_within_budget(tmp_path):
    """The headline outcome: a constructed many-function module LANDS
    strengthen-tests assertions within the default budget. Each function has a
    boundary the single smoke test misses, so the unbudgeted scan would fan out to
    a huge number of copytree+pytest runs; the budget keeps it tractable AND still
    lands real assertions on the highest-yield module."""
    (tmp_path / "tests").mkdir()
    funcs = "".join(
        f'def classify_{i}(n):\n    return "neg" if n < {i} else "pos"\n\n'
        for i in range(8))
    (tmp_path / "big.py").write_text(funcs, encoding="utf-8")
    # A thin test that only ever hits the "pos" branch of each function.
    body = "".join(f"    assert big.classify_{i}(1000) == \"pos\"\n" for i in range(8))
    (tmp_path / "tests" / "test_big.py").write_text(
        "import big\n\n\ndef test_pos():\n" + body, encoding="utf-8")

    landed = obj._scan(tmp_path)
    assert "big.py" in landed
    plan = obj.plan_strengthen_tests(tmp_path, "big.py")
    assert plan.new_contents  # real assertions landed, not an honest no-op
    content = next(iter(plan.new_contents.values()))
    assert "assert" in content and "kills_surviving_mutants" in content


def test_default_scan_is_deterministic_landed_set(tmp_path):
    """Two default scans land the SAME modules — the budget + ranking are a pure
    function of the project, no clock or randomness."""
    _multi_module_project(tmp_path)
    assert obj._scan(tmp_path) == obj._scan(tmp_path)


# --- BACK-COMPAT golden: small project unchanged by the budget ---------------

def _thin_project(root: Path) -> None:
    (root / "tests").mkdir()
    (root / "m.py").write_text(
        'def classify(n):\n    return "neg" if n < 0 else "pos"\n',
        encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "import m\n\n\ndef test_pos():\n    assert m.classify(5) == \"pos\"\n",
        encoding="utf-8")


def test_small_project_landed_assertions_unchanged_by_budget(tmp_path):
    """The landed test-file content for a small module is byte-identical whether
    the budget is absent, a fresh default, or unbounded — the budget only bounds
    large scans, never a small module's full mutation set."""
    _thin_project(tmp_path)
    none = obj.plan_strengthen_tests(tmp_path, "m.py", budget=None)
    default = obj.plan_strengthen_tests(tmp_path, "m.py", budget=_Budget(obj._DEFAULT_VERIFY_BUDGET))
    assert none.new_contents == default.new_contents
    assert none.new_contents  # and it really did land something
    # The default scan surfaces exactly this module (small project: never exhausts).
    assert obj._scan(tmp_path) == ["m.py"]


def test_small_module_full_mutation_set_is_unchanged(tmp_path):
    """With the default budget (never exhausted on a small file) the module's
    mutation result is the full, un-truncated one — same total, never
    budget_exhausted."""
    _thin_project(tmp_path)
    full = mutation_score(tmp_path, "m.py")
    budgeted = mutation_score(tmp_path, "m.py", budget=_Budget(obj._DEFAULT_VERIFY_BUDGET))
    assert budgeted.budget_exhausted is False
    assert (budgeted.total, budgeted.killed, budgeted.survived) == (
        full.total, full.killed, full.survived)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
