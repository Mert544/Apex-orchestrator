"""`chain_compiler` — the EXPLICIT objective-SEQUENCE chain (per-step
preconditions + halt + archival), the DELTA over ``dream_develop``'s hardcoded
``ship-value`` flatten.

Where ``dream_develop`` sequences ONE goal, this runs an ARBITRARY caller-ordered
list of objectives in SOURCE order, each gated through the EXISTING
``compile_objective`` verified-with-rollback loop (zero new gate logic), with two
additions: a per-step PRECONDITION check grounded in the frozen
``idea_composition`` grammar (a step whose earlier producer landed nothing is
SKIPPED — or the chain HALTS — never faked), and a chain-level halt on a
rolled-back (suite-red) step plus archival of the landed chain to
``composition_archive``.

These tests pin: explicit two-objective source order + per-step gating; an
unmet-precondition step skips honestly (and HALTS under the opt-in policy); a red
(rolled-back) step halts the chain (chain green IFF all landed steps held);
archival recorded on apply; the honest empty/dry-run paths; and a clock-free,
hashseed-invariant report body. The chain registers NO develop objective (it
COMPOSES existing ones), so there is no objective-count / Facet-parity obligation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.engine.chain_compiler import (
    ChainReport,
    ChainStep,
    _precondition_producer,
    _precondition_unmet,
    _step_is_red,
    render_chain_markdown,
    run_chain,
)
from app.engine.objective_compiler import CompileResult


# --- fixtures ----------------------------------------------------------------

def _two_stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (implement-stub) and
    an unsorted import block (sort-imports) — so an explicit two-objective chain
    has a concrete-first step AND a tidy step to run in SOURCE order."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "import os\nimport collections\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _rollback_project(tmp_path: Path) -> Path:
    """A project where ``remove-unused-imports`` would drop a re-exported import a
    test relies on — so the move APPLIES then the suite goes RED and ``apply_rename``
    ROLLS IT BACK (a genuine suite-gate rollback, not an upstream refusal)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        "import sys\n\ndef f():\n    return 1\n", encoding="utf-8")
    # The test depends on app.m re-exporting sys — removing the import breaks it.
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_reexport():\n    assert app.m.sys is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- 1. explicit two-objective chain runs in SOURCE order, each gated ---------

def test_chain_runs_explicit_order_each_gated(tmp_path):
    # The DELTA: an ARBITRARY explicit list runs verbatim in source order — no goal
    # flatten, no value re-sort. sort-imports is placed FIRST here (the opposite of
    # dream_develop's value-led order), and the chain honours it.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["sort-imports", "implement-stub"],
                       apply=False, verify=False)
    assert report.objectives == ["sort-imports", "implement-stub"]
    assert [s.objective for s in report.steps] == ["sort-imports", "implement-stub"]
    # A dry run still previews the moves each gated step WOULD land.
    assert report.total_moves >= 1
    assert not report.applied
    # Each step carries its own compile_objective campaign (the reused sub-engine).
    assert all(s.result is not None for s in report.steps)


def test_chain_dry_run_writes_nothing(tmp_path):
    # Off-by-default byte-identity: a dry run writes nothing and archives nothing.
    _two_stub_project(tmp_path)
    before = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.py")}
    run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
              apply=False, verify=False)
    after = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.py")}
    assert after == before
    from app.engine.composition_archive import CompositionArchive
    assert CompositionArchive.load(str(tmp_path)).cells == {}


# --- 2. a precondition-unmet step SKIPS honestly (no partial fake-green) -------

def test_unmet_precondition_step_is_skipped_honestly(tmp_path):
    # strengthen-tests' precondition (per the frozen idea_composition grammar) is
    # cover-gaps' success. On an ALREADY-COVERED project cover-gaps lands nothing,
    # so strengthen-tests has nothing to build on → it is SKIPPED honestly, never
    # faked. (verify=False keeps it fast; the skip is decided BEFORE the gate.)
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["cover-gaps", "strengthen-tests"],
                       apply=False, verify=False)
    cover = report.steps[0]
    strengthen = report.steps[1]
    # cover-gaps landed nothing on the already-tested module (an honest empty).
    assert not cover.landed
    # strengthen-tests is SKIPPED for the unmet precondition — not attempted, not
    # faked; its reason quotes the grammar's own rationale.
    assert strengthen.status == "skipped-precondition"
    assert "cover-gaps" in strengthen.reason
    assert strengthen.result is None  # never ran the gate
    # A default chain SKIPS past the unmet precondition (does not halt).
    assert not report.halted
    assert report.green  # skipping is honest, not a fake-green


def test_unmet_precondition_can_halt_when_opted_in(tmp_path):
    # With ``halt_on_unmet_precondition`` the chain HALTS at the first unmet
    # precondition instead of skipping past it — an explicit, honest stop.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["cover-gaps", "strengthen-tests"],
                       apply=False, verify=False,
                       halt_on_unmet_precondition=True)
    assert report.steps[1].status == "skipped-precondition"
    assert report.halted
    assert "strengthen-tests" in report.halt_reason


def test_precondition_met_when_producer_lands(tmp_path):
    # When the producer LANDS, the successor's precondition is met and it RUNS.
    # implement-stub lands the stub fill; cover-gaps (its declared successor) is
    # then attempted rather than skipped.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "cover-gaps"],
                       apply=True, verify=True)
    stub = report.steps[0]
    cover = report.steps[1]
    assert stub.landed  # the fill landed
    # cover-gaps ran (it was NOT skipped) — its precondition was met.
    assert cover.status != "skipped-precondition"
    assert cover.result is not None


# --- 3. a RED (rolled-back) step HALTS the chain; chain green IFF all held -----

def test_red_step_rolls_back_and_halts_chain(tmp_path):
    # remove-unused-imports would drop a re-exported import a test needs: the move
    # APPLIES, the suite goes RED, apply_rename ROLLS IT BACK. The chain detects the
    # rollback, HALTS, and never counts a faked move. A LATER step never runs.
    _rollback_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text(encoding="utf-8")
    report = run_chain(str(tmp_path),
                       ["remove-unused-imports", "sort-imports"],
                       apply=True, verify=True)
    red = report.steps[0]
    assert red.status == "red"
    assert red.moves == 0  # nothing landed — the move was rolled back
    # The file is restored byte-for-byte (the inherited never-fake-green rollback).
    assert (tmp_path / "app" / "m.py").read_text(encoding="utf-8") == before
    # The chain HALTED — the later step was NEVER reached (recorded as ``halted``).
    assert report.halted
    assert not report.green
    assert report.steps[1].status == "halted"
    assert report.steps[1].result is None


def test_chain_green_iff_every_landed_step_held(tmp_path):
    # A chain with no rollback and no unmet-halt is GREEN, even if some steps were
    # honest no-ops. Two tidy objectives on an already-clean-enough tree: whatever
    # lands, holds; nothing rolls back → green.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
                       apply=True, verify=True)
    assert not report.halted
    assert report.green
    # No step is red; every recorded step is landed/empty (never faked).
    assert all(s.status in ("landed", "empty") for s in report.steps)


# --- 4. archival: the LANDED chain is recorded under its sequence signature ----

def test_landed_chain_is_archived(tmp_path):
    # On an apply that lands moves, the chain is archived to composition_archive
    # under its ORDERED objective signature (chain:a>b) — a learned recipe distinct
    # from any single objective's cell.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
                       apply=True, verify=True)
    assert report.landed_objectives  # something landed
    from app.engine.composition_archive import CompositionArchive
    arch = CompositionArchive.load(str(tmp_path))
    keys = list(arch.cells)
    # The archived cell is keyed by the chain SEQUENCE signature, not a lone objective.
    assert any(k.startswith("chain:implement-stub>sort-imports|") for k in keys), keys
    entry = arch.cells[next(k for k in keys if k.startswith("chain:"))]
    # Its recipe is the landed objectives in chain order; the gain is the move count.
    assert entry.operators == report.landed_objectives
    assert entry.fitness_delta == float(report.total_moves)


def test_dry_run_and_empty_chain_archive_nothing(tmp_path):
    # A dry run archives nothing; an all-skipped/empty chain archives nothing.
    _two_stub_project(tmp_path)
    run_chain(str(tmp_path), ["implement-stub"], apply=False, verify=False)
    from app.engine.composition_archive import CompositionArchive
    assert CompositionArchive.load(str(tmp_path)).cells == {}
    # An empty objective list lands nothing and archives nothing on apply.
    empty = run_chain(str(tmp_path), [], apply=True, verify=False)
    assert empty.total_moves == 0
    assert CompositionArchive.load(str(tmp_path)).cells == {}


# --- 5. carry-across: state flows step→step through the shared tree -----------

def test_state_carries_across_steps(tmp_path):
    # The producer's landed edit is VISIBLE to the successor's fitness measure: after
    # implement-stub fills the body, cover-gaps measures against the FILLED tree (the
    # baseline carried forward), so the chain composes over a genuinely shared state.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "cover-gaps"],
                       apply=True, verify=True)
    # The stub body is actually filled on disk (the shared tree carried the edit).
    assert "raise NotImplementedError" not in (
        tmp_path / "app" / "s.py").read_text(encoding="utf-8")
    assert report.steps[0].landed


# --- 6. determinism: hashseed-invariant report body --------------------------

def test_chain_report_deterministic_under_pythonhashseed(tmp_path):
    _two_stub_project(tmp_path)
    repo = str(Path(__file__).resolve().parents[1])
    src = ("import json,sys;from app.engine.chain_compiler import run_chain;"
           "print(json.dumps(run_chain(sys.argv[1], "
           "['implement-stub','sort-imports'], apply=False, verify=False)"
           ".to_dict(), sort_keys=True))")
    out0 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    out1 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    assert out0.returncode == 0 and out1.returncode == 0, (out0.stderr, out1.stderr)
    assert out0.stdout == out1.stdout  # the report body is hashseed-invariant
    assert out0.stdout.strip()


# --- 7. grade proof: recorded on apply, -1 on a dry run ----------------------

def test_chain_grade_before_after(tmp_path):
    _two_stub_project(tmp_path)
    applied = run_chain(str(tmp_path), ["implement-stub"], apply=True, verify=True)
    assert applied.grade_before >= 0 and applied.grade_after >= 0
    assert applied.grade_after >= applied.grade_before  # filling can only help/hold
    fresh = run_chain(str(tmp_path), ["implement-stub"], apply=False, verify=False)
    assert fresh.grade_before == -1 and fresh.grade_after == -1
    assert fresh.grade_delta == 0


# --- 8. the renderer is CLOCK-FREE and honest --------------------------------

def test_chain_render_clock_free_and_honest(tmp_path):
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
                       apply=False, verify=False)
    md = render_chain_markdown(report)
    assert "UTC" not in md
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}", md)  # no YYYY-MM-DD timestamp
    assert render_chain_markdown(report) == md  # byte-stable across renders
    assert "Develop chain" in md
    assert "implement-stub → sort-imports" in md


def test_render_empty_chain_is_honest_refusal():
    md = render_chain_markdown(ChainReport(objectives=[]))
    assert "Empty chain" in md


def test_render_halted_chain_discloses_halt():
    # A halted chain renders the honest halt disclosure (no partial fake-green).
    report = ChainReport(objectives=["a", "b"], halted=True,
                         halt_reason="`a`: a move rolled back — the suite went red")
    report.steps = [ChainStep("a", "red"), ChainStep("b", "halted")]
    md = render_chain_markdown(report)
    assert "HALTED" in md
    assert "no partial fake-green" in md.lower() or "no\npartial" in md.lower()


# --- 9. unit: the precondition classifier and red-step detector --------------

def test_precondition_producer_uses_frozen_grammar():
    # strengthen-tests depends on cover-gaps (a real edge in _COMPOSITION_EDGES).
    assert _precondition_producer("strengthen-tests", ["cover-gaps"]) == "cover-gaps"
    # No earlier producer named → no precondition here.
    assert _precondition_producer("strengthen-tests", ["modernize"]) is None
    # The NEAREST earlier producer wins if several are present.
    assert _precondition_producer(
        "sort-imports", ["modernize", "implement-stub"]) == "modernize"


def test_precondition_unmet_reason_quotes_grammar():
    unmet = _precondition_unmet("strengthen-tests", ["cover-gaps"], set())
    assert "cover-gaps" in unmet and "strengthen-tests" in unmet
    # Met when the producer landed, or when no producer is named earlier.
    assert _precondition_unmet("strengthen-tests", ["cover-gaps"],
                               {"cover-gaps"}) == ""
    assert _precondition_unmet("strengthen-tests", ["modernize"], set()) == ""


def test_step_is_red_reads_rollback_disclosure():
    # A rolled-back gate surfaces a "tests failed ... restored" blocker and no step.
    rolled = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0,
                           blocked=["app/m.py: tests failed after rename; "
                                    "all files restored"])
    assert _step_is_red(rolled) is True
    # An honest empty step (a blocker that is NOT a rollback, or none) is NOT red.
    empty = CompileResult(objective="x", fitness_start=0.0, fitness_end=0.0)
    assert _step_is_red(empty) is False
    unknown = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0,
                            blocked=["app/m.py: unknown objective 'x'"])
    assert _step_is_red(unknown) is False
    # A step that LANDED something is never red (it held).
    from app.engine.objective_compiler import CompileStep
    landed = CompileResult(objective="x", fitness_start=1.0, fitness_end=0.0,
                           steps=[CompileStep("op", "t", "d", 1.0, 0.0)],
                           blocked=["y: tests failed after rename; all files restored"])
    assert _step_is_red(landed) is False


# --- 10. report shape sanity -------------------------------------------------

def test_chain_report_to_dict_shape():
    report = ChainReport(objectives=["implement-stub", "cover-gaps"])
    d = report.to_dict()
    for key in ("objectives", "steps", "landed_objectives", "grade_before",
                "grade_after", "grade_delta", "total_moves", "verified_moves",
                "green", "applied", "halted", "halt_reason"):
        assert key in d
    assert d["objectives"] == ["implement-stub", "cover-gaps"]
    assert d["green"] is True and d["applied"] is False
    assert d["steps"] == [] and d["landed_objectives"] == []
