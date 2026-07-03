"""``record_dream_chain_memory`` — the CHAIN-level companion to
``record_dream_outcomes``.

``record_dream_outcomes`` already feeds each dreamed DIRECTION (the chain
objective) back into ``IdeaMemory.by_label``/``by_operator``, but the dream's
own chain campaigns never fed the CHAIN-level learning stores
``chain_compiler`` already writes for an explicit, caller-ordered objective
sequence (``composition_archive``'s MAP-Elites cells + ``idea_memory.by_chain``,
see ``chain_compiler._archive_chain``/``_record_chain_memory``,
chain_compiler.py:292-374). This closes that companion gap: ``dream_develop``
has no caller-supplied sequence to key by, so it groups landed work by the SCOPE
MODULE each move actually touched, and records ONE
``composition_archive.record_campaign`` elite + ONE
``IdeaMemory.record_chain_outcome`` tally per scope, signature
``dream-chain:<scope>``.

These tests pin: (1) a real landed chain records both stores under the correct
signature; (2) multiple moves/objectives on one module dedupe the recipe and sum
the move count; (3) two distinct scope modules record as two separate,
non-cross-contaminated signatures; (4) a withheld move is never grouped/recorded
(never a fabricated success); (5) DRY RUN / empty / all-withheld chains write
NOTHING (byte-identical); (6) the record is additive and deterministic; (7) a
write failure on either store is swallowed.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.composition_archive import ARCHIVE_REL, CompositionArchive
from app.engine.dream_develop import (
    DreamChainReport,
    record_dream_chain_memory,
)
from app.engine.idea_memory import MEMORY_REL, IdeaMemory
from app.engine.objective_compiler import CompileResult, CompileStep


def _step(operator: str, target: str, coverage: str = "module") -> CompileStep:
    return CompileStep(operator=operator, target=target, description=operator,
                      fitness_before=1.0, fitness_after=0.0, verified=True,
                      coverage=coverage)


# --------------------------------------------------------------------------- #
# 1. A real landed chain records both stores under dream-chain:<scope>         #
# --------------------------------------------------------------------------- #
def test_single_landed_move_records_archive_and_chain_outcome(tmp_path):
    step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=0.0, applied=True, steps=[step])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    record_dream_chain_memory(report, str(tmp_path))

    archive = CompositionArchive.load(str(tmp_path))
    cell = archive.cells.get("dream-chain:app/hub.py|wire-module-exports")
    assert cell is not None
    assert cell.objective == "dream-chain:app/hub.py"
    assert cell.operators == ["wire-module-exports"]
    assert cell.moves == 1
    assert cell.fitness_delta == 1.0

    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_chain["dream-chain:app/hub.py"].applied == 1
    assert mem.by_chain["dream-chain:app/hub.py"].rolled_back == 0
    assert mem.by_chain["dream-chain:app/hub.py"].blocked == 0


# --------------------------------------------------------------------------- #
# 2. Two moves, same objective, same module: dedupe the recipe, sum moves.     #
# --------------------------------------------------------------------------- #
def test_two_moves_same_objective_same_module_dedupes_and_sums(tmp_path):
    steps = [_step("wire_module_exports", "app/hub.py:wire-module-exports"),
             _step("wire_module_exports", "app/hub.py:wire-module-exports")]
    result = CompileResult(objective="wire-module-exports", fitness_start=2.0,
                           fitness_end=0.0, applied=True, steps=steps)
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    record_dream_chain_memory(report, str(tmp_path))

    archive = CompositionArchive.load(str(tmp_path))
    cell = archive.cells["dream-chain:app/hub.py|wire-module-exports"]
    # ``ArchiveEntry.moves`` mirrors chain_compiler's own convention (``len`` of
    # the RECIPE, i.e. distinct landed objectives) — deduped to 1 here.
    assert cell.operators == ["wire-module-exports"]
    assert cell.moves == 1
    # The raw per-scope MOVE COUNT (2 landed steps) shows up as the fitness gain.
    assert cell.fitness_delta == 2.0


# --------------------------------------------------------------------------- #
# 3. Two different objectives landing on the same module: chain order kept.    #
# --------------------------------------------------------------------------- #
def test_two_objectives_same_module_preserve_chain_order(tmp_path):
    r1 = CompileResult(objective="implement-stub", fitness_start=1.0,
                       fitness_end=0.0, applied=True,
                       steps=[_step("implement_stub", "app/hub.py:implement-stub")])
    r2 = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                       fitness_end=0.0, applied=True,
                       steps=[_step("wire_module_exports",
                                   "app/hub.py:wire-module-exports")])
    report = DreamChainReport(
        goal="ship-value", objectives=["implement-stub", "wire-module-exports"],
        applied=True, results=[r1, r2])

    record_dream_chain_memory(report, str(tmp_path))

    archive = CompositionArchive.load(str(tmp_path))
    cell = archive.cells["dream-chain:app/hub.py|implement-stub+wire-module-exports"]
    # Chain (value-led) order preserved, not alphabetical/insertion-of-set order.
    assert cell.operators == ["implement-stub", "wire-module-exports"]
    assert cell.moves == 2


# --------------------------------------------------------------------------- #
# 4. Two distinct scope modules: two separate, non-cross-contaminated cells.   #
# --------------------------------------------------------------------------- #
def test_two_different_modules_record_separate_signatures(tmp_path):
    result = CompileResult(
        objective="wire-module-exports", fitness_start=2.0, fitness_end=0.0,
        applied=True,
        steps=[_step("wire_module_exports", "app/hub.py:wire-module-exports"),
              _step("wire_module_exports", "app/other.py:wire-module-exports")])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    record_dream_chain_memory(report, str(tmp_path))

    archive = CompositionArchive.load(str(tmp_path))
    hub_cell = archive.cells["dream-chain:app/hub.py|wire-module-exports"]
    other_cell = archive.cells["dream-chain:app/other.py|wire-module-exports"]
    assert hub_cell.moves == 1 and other_cell.moves == 1  # not summed together

    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_chain["dream-chain:app/hub.py"].applied == 1
    assert mem.by_chain["dream-chain:app/other.py"].applied == 1


# --------------------------------------------------------------------------- #
# 5. A withheld move is never grouped or recorded (no fabricated success).     #
# --------------------------------------------------------------------------- #
def test_withheld_move_is_never_grouped_or_recorded(tmp_path):
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=1.0, applied=True)
    result.withheld.append("declare __all__ in app/friendless.py — green but uncovered")
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    record_dream_chain_memory(report, str(tmp_path))

    assert not (tmp_path / ARCHIVE_REL).exists()
    assert not (tmp_path / MEMORY_REL).exists()


def test_landed_and_withheld_in_one_chain_records_only_the_landed_scope(tmp_path):
    landed = CompileResult(
        objective="wire-module-exports", fitness_start=1.0, fitness_end=0.0,
        applied=True, steps=[_step("wire_module_exports",
                                   "app/hub.py:wire-module-exports")])
    withheld = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                             fitness_end=1.0, applied=True)
    withheld.withheld.append("declare __all__ in app/friendless.py")
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[landed, withheld])

    record_dream_chain_memory(report, str(tmp_path))

    archive = CompositionArchive.load(str(tmp_path))
    assert "dream-chain:app/hub.py|wire-module-exports" in archive.cells
    assert not any(k.startswith("dream-chain:app/friendless.py")
                  for k in archive.cells)


# --------------------------------------------------------------------------- #
# 6. DRY RUN / empty / all-withheld chains write NOTHING (byte-identical).     #
# --------------------------------------------------------------------------- #
def test_dry_run_writes_nothing(tmp_path):
    step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=0.0, applied=False, steps=[step])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=False, results=[result])  # applied=False chain

    record_dream_chain_memory(report, str(tmp_path))

    assert not (tmp_path / ARCHIVE_REL).exists()
    assert not (tmp_path / MEMORY_REL).exists()


def test_empty_applied_chain_writes_nothing(tmp_path):
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[])

    record_dream_chain_memory(report, str(tmp_path))

    assert not (tmp_path / ARCHIVE_REL).exists()
    assert not (tmp_path / MEMORY_REL).exists()


def test_applied_chain_with_only_empty_results_writes_nothing(tmp_path):
    empty = CompileResult(objective="wire-module-exports", fitness_start=0.0,
                          fitness_end=0.0, applied=True)
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[empty])

    record_dream_chain_memory(report, str(tmp_path))

    assert not (tmp_path / ARCHIVE_REL).exists()
    assert not (tmp_path / MEMORY_REL).exists()


# --------------------------------------------------------------------------- #
# 7. Additive + deterministic: two calls accumulate honestly.                  #
# --------------------------------------------------------------------------- #
def test_record_is_additive_across_two_calls(tmp_path):
    def _make() -> DreamChainReport:
        step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
        result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                               fitness_end=0.0, applied=True, steps=[step])
        return DreamChainReport(goal="ship-value",
                                objectives=["wire-module-exports"],
                                applied=True, results=[result])

    record_dream_chain_memory(_make(), str(tmp_path))
    record_dream_chain_memory(_make(), str(tmp_path))

    mem = IdeaMemory.load(str(tmp_path))
    assert mem.by_chain["dream-chain:app/hub.py"].applied == 2


# --------------------------------------------------------------------------- #
# 8. Best-effort: a write failure on either store is swallowed.               #
# --------------------------------------------------------------------------- #
def test_composition_archive_write_oserror_is_silent(tmp_path, monkeypatch):
    step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=0.0, applied=True, steps=[step])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "composition-archive.json":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    record_dream_chain_memory(report, str(tmp_path))  # must not raise
    # The archive write failed before idea-memory's own save is ever reached (one
    # shared try/except), so neither store ends up written this call.
    assert not (tmp_path / ARCHIVE_REL).exists()
    assert not (tmp_path / MEMORY_REL).exists()


def test_idea_memory_write_oserror_is_silent(tmp_path, monkeypatch):
    step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=0.0, applied=True, steps=[step])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "idea-memory.json":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    record_dream_chain_memory(report, str(tmp_path))  # must not raise
    # The composition archive's OWN internal save already completed (it runs
    # before idea-memory's save in the loop), so it holds the recipe even though
    # idea-memory's write failed afterward.
    archive = CompositionArchive.load(str(tmp_path))
    assert "dream-chain:app/hub.py|wire-module-exports" in archive.cells
    assert not (tmp_path / MEMORY_REL).exists()


# --------------------------------------------------------------------------- #
# 9. dream_gate_learn's tighten-only promote-gate contract is untouched.       #
# --------------------------------------------------------------------------- #
def test_does_not_touch_dream_gate_learn_floor(tmp_path):
    from app.engine.dream_gate_learn import _GATE_FACTOR_FLOOR, gate_tighten_factors

    step = _step("wire_module_exports", "app/hub.py:wire-module-exports")
    result = CompileResult(objective="wire-module-exports", fitness_start=1.0,
                           fitness_end=0.0, applied=True, steps=[step])
    report = DreamChainReport(goal="ship-value", objectives=["wire-module-exports"],
                              applied=True, results=[result])

    record_dream_chain_memory(report, str(tmp_path))

    # The promote-gate floor constant is unchanged, and computing tighten
    # factors on the now-populated idea-memory store still returns an empty map
    # for a fresh promote-history-less project (nothing this function writes
    # feeds the promote gate's OWN inputs — a disjoint learn store).
    assert _GATE_FACTOR_FLOOR == 0.15
    assert gate_tighten_factors(str(tmp_path), 3) == {}


# --------------------------------------------------------------------------- #
# End-to-end: real CLI dispatch (`apex dream --land --apply`) wires both.      #
# --------------------------------------------------------------------------- #
def test_cmd_dream_land_apply_wires_record_dream_chain_memory(tmp_path, capsys):
    import argparse

    from app import cli_insight

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

    rc = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=True, apply=True, fast=True,
        json=False))
    capsys.readouterr()
    assert rc == 0

    archive = CompositionArchive.load(str(tmp_path))
    assert any(k.startswith("dream-chain:app/calc.py")
              for k in archive.cells), archive.cells

    mem_data = json.loads((tmp_path / MEMORY_REL).read_text(encoding="utf-8"))
    assert mem_data["by_chain"]["dream-chain:app/calc.py"]["applied"] == 1
