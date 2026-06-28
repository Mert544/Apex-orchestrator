"""Piece B — the LEARN-LOOP: ``dream --land --apply`` → outcome memory.

The dream READS ``IdeaMemory`` land-rates to rank directions, but its OWN
``dream --land --apply`` landings never fed back — so it could not learn which
DREAMED DIRECTIONS (the chain's objectives) actually land on this project.
``record_dream_outcomes`` closes that loop: after an apply it records each move's
realized per-direction outcome into the SAME ``.apex/idea-memory.json`` learn
store the ranking reads — a LANDED step is ``applied`` for its dreamed direction,
a WITHHELD move is recorded as not-landed (``blocked``).

HONEST + no-double-count: the per-OPERATOR dimension is left to the verified-with-
rollback compiler the chain composes (which already credits ``by_operator``), so
the learn-loop adds ONLY the missing per-label (dreamed-direction) dimension —
never inflating a sample count, never fabricating a success.

These tests pin: (1) a real landed move records the dreamed direction (and the
operator is present from the compile path, never double-counted); (2) a withheld
move is recorded as not-landed; (3) a DRY RUN / empty chain writes NOTHING
(byte-identical); (4) the record is deterministic and a write failure is swallowed.
"""

from __future__ import annotations

from app.engine.dream_develop import (
    DreamChainReport,
    dream_develop,
    record_dream_outcomes,
)
from app.engine.idea_memory import IdeaMemory
from app.engine.objective_compiler import CompileResult, CompileStep


def _stub_project(tmp_path):
    """A project carrying a genuinely fillable stub the dream chain can land."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        "def total(xs) -> int:\n    ...\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import total\n\n\ndef test_total():\n"
        "    assert total([1, 2, 3]) == 6\n    assert total([10, 20]) == 30\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")


# --- (1) a real landed move feeds the dreamed direction back ------------------

def test_landed_move_records_the_dreamed_direction(tmp_path):
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=True, verify=True, fast=True)
    assert report.total_moves >= 1, "the chain should land the fillable stub"

    record_dream_outcomes(report, str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))

    # The dreamed DIRECTION (the objective) is now learnable — the new dimension.
    assert "implement-stub" in mem.by_label
    assert mem.by_label["implement-stub"].applied >= 1
    # The OPERATOR outcome is present too (from the verified-with-rollback compiler
    # the chain composes), and is NOT double-counted by the learn-loop: exactly one
    # applied per landed step, not two.
    assert "implement_stub" in mem.by_operator
    landed_steps = sum(len(r.steps) for r in report.results)
    assert mem.by_operator["implement_stub"].applied == landed_steps


def test_learn_loop_does_not_double_count_the_operator(tmp_path):
    """Anti-fake-green: the learn-loop must never inflate the per-operator sample
    count the compiler already recorded. The label dimension carries the same
    applied count, but the operator total stays exactly the landed-step count."""
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=True, verify=True, fast=True)
    landed = sum(len(r.steps) for r in report.results)
    record_dream_outcomes(report, str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_operator["implement_stub"].total == landed  # not 2×landed


# --- (2) a withheld move is recorded as NOT-landed (honest) -------------------

def test_withheld_move_records_as_not_landed(tmp_path):
    # A withheld move is a legitimate report state (the covered-only sweep previews
    # a green-but-uncovered move instead of landing it). It must be recorded as
    # not-landed for its dreamed direction — never silently dropped, never faked.
    result = CompileResult(objective="implement-stub", fitness_start=1.0,
                           fitness_end=1.0, applied=True)
    result.withheld.append("implement the stub in app/x.py — green but uncovered")
    report = DreamChainReport(goal="ship-value", objectives=["implement-stub"],
                              applied=True, results=[result])

    record_dream_outcomes(report, str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))

    assert "implement-stub" in mem.by_label
    assert mem.by_label["implement-stub"].blocked == 1
    assert mem.by_label["implement-stub"].applied == 0  # honest: nothing landed
    # A withheld move carries no operator in the chain data, so none is invented.
    assert mem.by_operator == {}


def test_landed_and_withheld_in_one_chain(tmp_path):
    landed = CompileStep(operator="fill_stub", target="app/a.py:implement-stub",
                         description="impl a", fitness_before=2.0, fitness_after=1.0,
                         verified=True, coverage="function")
    r_landed = CompileResult(objective="implement-stub", fitness_start=2.0,
                             fitness_end=1.0, applied=True, steps=[landed])
    r_held = CompileResult(objective="cover-gaps", fitness_start=1.0,
                           fitness_end=1.0, applied=True)
    r_held.withheld.append("cover app/b.py — green but uncovered")
    report = DreamChainReport(goal="ship-value",
                              objectives=["implement-stub", "cover-gaps"],
                              applied=True, results=[r_landed, r_held])

    record_dream_outcomes(report, str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_label["implement-stub"].applied == 1
    assert mem.by_label["cover-gaps"].blocked == 1


# --- (3) DRY RUN / empty chain writes NOTHING (byte-identical) ----------------

def test_dry_run_writes_nothing(tmp_path):
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=False, verify=False)  # DRY RUN
    record_dream_outcomes(report, str(tmp_path))
    assert not (tmp_path / ".apex" / "idea-memory.json").exists()


def test_empty_applied_chain_writes_nothing(tmp_path):
    # apply=True but the chain landed/withheld nothing → no outcome rows → no write.
    report = DreamChainReport(goal="ship-value", objectives=["implement-stub"],
                              applied=True, results=[])
    record_dream_outcomes(report, str(tmp_path))
    assert not (tmp_path / ".apex" / "idea-memory.json").exists()


def test_applied_chain_with_only_empty_results_writes_nothing(tmp_path):
    # A result with no steps and no withheld contributes no rows → no write.
    empty = CompileResult(objective="implement-stub", fitness_start=0.0,
                          fitness_end=0.0, applied=True)
    report = DreamChainReport(goal="ship-value", objectives=["implement-stub"],
                              applied=True, results=[empty])
    record_dream_outcomes(report, str(tmp_path))
    assert not (tmp_path / ".apex" / "idea-memory.json").exists()


# --- (4) deterministic + best-effort -----------------------------------------

def test_record_is_idempotent_in_counts_per_call(tmp_path):
    # Two identical reports recorded in sequence accumulate honestly (2 applied),
    # proving the record is deterministic and additive — no clock/random.
    def _make():
        step = CompileStep(operator="fill_stub", target="app/a.py:implement-stub",
                           description="impl", fitness_before=1.0, fitness_after=0.0,
                           verified=True, coverage="function")
        r = CompileResult(objective="implement-stub", fitness_start=1.0,
                          fitness_end=0.0, applied=True, steps=[step])
        return DreamChainReport(goal="ship-value", objectives=["implement-stub"],
                                applied=True, results=[r])

    record_dream_outcomes(_make(), str(tmp_path))
    record_dream_outcomes(_make(), str(tmp_path))
    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_label["implement-stub"].applied == 2
