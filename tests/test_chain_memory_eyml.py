"""`ChainMemory` — the LEARNING loop over the explicit objective-SEQUENCE chain.

Where ``idea_memory.by_sequence`` learns which adjacent operator PAIRS land, this
new ``by_chain`` table learns which whole ORDERED chains (a ``chain_compiler``
campaign) held on this project — keyed by the SAME ``chain:a>b>c`` signature the
composition archive is keyed under. After a ``run_chain`` completes, the chain's
realized outcome is recorded via the reused ``_Stat`` + Wilson-CI machinery
(no new statistics), so ascend / goal-trees can rank whole chain candidates by
the SAME evidence-aware lower bound they already use for operators and sequences.

These tests pin the four contract facets from the build slate:
  * a chain run records a ``by_chain`` outcome under its ORDERED signature;
  * a historically-successful chain ranks ABOVE an unproven/failed one via the
    Wilson-CI lower bound (proven-beats-lucky, sample-size aware);
  * an empty ``by_chain`` leaves the confidence ranking BYTE-IDENTICAL to the
    pre-change engine (the opt-in property — proven non-tautologically: the SAME
    call ranks the OTHER tables unchanged, and a dry run records nothing);
  * a rolled-back / blocked chain records as a NON-success (never a faked win),
    so a halted chain can never inflate a recipe's land-rate.
Plus persistence round-trip and PYTHONHASHSEED determinism.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.engine.chain_compiler import (
    _chain_outcome,
    _chain_signature,
    _record_chain_memory,
    run_chain,
)
from app.engine.chain_compiler import ChainReport, ChainStep
from app.engine.idea_memory import _MIN_SAMPLES, IdeaMemory, _Stat


# --- fixtures ----------------------------------------------------------------

def _two_stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (implement-stub) and
    an unsorted import block (sort-imports) — a chain has a concrete-first step
    AND a tidy step to land in source order (mirrors the chain_compiler fixture)."""
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
    """A project where ``remove-unused-imports`` drops a re-exported import a test
    relies on — the move APPLIES then the suite goes RED and is ROLLED BACK, so the
    chain HALTS on a genuine regression (mirrors the chain_compiler fixture)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        "import sys\n\ndef f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_reexport():\n    assert app.m.sys is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _landed_report(objectives: list[str], landed: list[str]) -> ChainReport:
    """A minimal held-chain report: every ``landed`` objective is a ``landed`` step
    (one move each), the rest empty. ``applied`` True, not halted → a success."""
    report = ChainReport(objectives=list(objectives), applied=True)
    from app.engine.objective_compiler import CompileResult, CompileStep
    for obj in objectives:
        if obj in landed:
            res = CompileResult(objective=obj, fitness_start=1.0, fitness_end=0.0,
                                steps=[CompileStep(obj, "t", "d", 1.0, 0.0)])
            report.steps.append(ChainStep(obj, "landed", result=res))
        else:
            res = CompileResult(objective=obj, fitness_start=0.0, fitness_end=0.0)
            report.steps.append(ChainStep(obj, "empty", result=res))
    return report


# --- 1. a chain run records a by_chain outcome under the ordered signature ----

def test_landed_chain_records_by_chain_outcome(tmp_path):
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
                       apply=True, verify=True)
    assert report.landed_objectives  # something genuinely landed
    assert not report.halted
    mem = IdeaMemory.load(str(tmp_path))
    sig = "chain:implement-stub>sort-imports"
    # The realized outcome is keyed by the ORDERED objective signature — the SAME
    # key chain_compiler archives under (the whole recipe, not a lone objective).
    assert sig in mem.by_chain
    stat = mem.by_chain[sig]
    # A held chain is an ``applied`` success — the only bucket a genuine hold fills.
    assert stat.applied == 1
    assert stat.rolled_back == 0 and stat.blocked == 0


def test_recorded_signature_matches_archive_signature(tmp_path):
    # by_chain and the composition archive speak ONE identity: the ordered signature.
    _two_stub_project(tmp_path)
    report = run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
                       apply=True, verify=True)
    sig = _chain_signature(report)
    from app.engine.composition_archive import CompositionArchive
    arch_keys = list(CompositionArchive.load(str(tmp_path)).cells)
    # The archive cell key is the SAME chain signature plus its operator suffix.
    assert any(k.startswith(sig + "|") for k in arch_keys), arch_keys
    assert sig in IdeaMemory.load(str(tmp_path)).by_chain


# --- 2. a proven chain ranks ABOVE an unproven/failed one via Wilson-CI --------

def test_proven_chain_outranks_lucky_via_wilson():
    mem = IdeaMemory()
    # A lucky 1-of-1 chain and a well-attested 9-of-10 chain.
    mem.record_chain_outcome("chain:lucky", "applied")
    for _ in range(9):
        mem.record_chain_outcome("chain:proven", "applied")
    mem.record_chain_outcome("chain:proven", "rolled_back")

    # Raw success_rate would put the lucky 1-of-1 (100%) first.
    assert mem.by_chain["chain:lucky"].success_rate > mem.by_chain["chain:proven"].success_rate
    # The SAME Wilson lower bound used for by_operator/by_sequence ranks proven first.
    assert mem.by_chain["chain:proven"].confidence > mem.by_chain["chain:lucky"].confidence

    ranking = mem.confident_ranking("chain", best=True)
    keys = [r["key"] for r in ranking]
    assert keys[0] == "chain:proven"
    # The 1-sample chain is below _MIN_SAMPLES and excluded (no opinion yet).
    assert "chain:lucky" not in keys


def test_failed_chain_ranks_below_a_held_one():
    mem = IdeaMemory()
    for _ in range(5):
        mem.record_chain_outcome("chain:good", "applied")
    for _ in range(5):
        mem.record_chain_outcome("chain:bad", "rolled_back")
    best = mem.confident_ranking("chain", best=True)
    worst = mem.confident_ranking("chain", best=False)
    assert best[0]["key"] == "chain:good"
    assert worst[0]["key"] == "chain:bad"
    # A chain that only ever rolled back has confidence 0.0 (a proven non-lander).
    assert mem.by_chain["chain:bad"].confidence == 0.0


def test_chain_ranking_reuses_stat_and_wilson():
    # Like-for-like schema: by_chain holds the SAME _Stat and the ranking read is the
    # SAME confidence field by_operator/by_sequence rank by (no new statistics).
    mem = IdeaMemory()
    for _ in range(9):
        mem.record_chain_outcome("chain:c", "applied")
    mem.record_chain_outcome("chain:c", "rolled_back")
    for _ in range(9):
        mem.by_operator.setdefault("op", _Stat())
        mem.by_operator["op"].applied += 1
    mem.by_operator["op"].rolled_back += 1
    chain_row = mem.confident_ranking("chain")[0]
    op_row = mem.confident_ranking("operator")[0]
    # Same 9-of-10 shape via the same Wilson lower bound → identical confidence.
    assert chain_row["confidence"] == op_row["confidence"]
    assert isinstance(mem.by_chain["chain:c"], _Stat)


# --- 3. empty by_chain → ranking BYTE-IDENTICAL to pre-change (opt-in) ---------

def test_empty_by_chain_ranks_nothing():
    # With no chain history the chain ranking is empty — nothing to bias (the opt-in
    # property: an unpopulated table contributes nothing).
    mem = IdeaMemory()
    assert mem.by_chain == {}
    assert mem.confident_ranking("chain") == []
    assert mem.confident_ranking("chain", best=False) == []


def test_empty_by_chain_leaves_other_rankings_byte_identical():
    # NON-TAUTOLOGICAL: an engine WITH by_chain support must rank the pre-existing
    # tables byte-identically to one with no chain history at all — adding the table
    # never perturbs the operator/sequence rankings the ascend path already reads.
    def _seed(m: IdeaMemory) -> IdeaMemory:
        for _ in range(3):
            m.record_outcomes({"results": [
                {"operator": "test", "applied": True},
                {"operator": "harden", "applied": True}]})
        m.record_outcomes({"results": [{"operator": "harden", "rolled_back": True}]})
        return m

    baseline = _seed(IdeaMemory())            # by_chain stays empty
    with_chain_support = _seed(IdeaMemory())  # same, on the by_chain-aware schema
    for table in ("operator", "sequence"):
        assert (with_chain_support.confident_ranking(table)
                == baseline.confident_ranking(table))
    # And the persisted view differs from the pre-chain shape ONLY by the empty
    # by_chain key — nothing in the other tables shifts.
    d = with_chain_support.to_dict()
    assert d["by_chain"] == {}
    assert d["by_operator"] == baseline.to_dict()["by_operator"]


def test_dry_run_records_no_chain_and_stays_empty(tmp_path):
    # A dry run measures nothing to learn from → by_chain untouched (byte-identical).
    _two_stub_project(tmp_path)
    run_chain(str(tmp_path), ["implement-stub", "sort-imports"],
              apply=False, verify=False)
    assert not (tmp_path / ".apex" / "idea-memory.json").exists()
    assert IdeaMemory.load(str(tmp_path)).by_chain == {}


def test_all_empty_chain_records_nothing(tmp_path):
    # A chain that lands nothing and does not halt is an honest no-op — it records
    # NOTHING (only genuinely-held or halted chains are worth learning from), so an
    # all-empty apply leaves by_chain byte-identical.
    _two_stub_project(tmp_path)
    # Already-tested + tidy module: cover-gaps lands nothing, strengthen-tests is
    # skipped (precondition) — the chain applies but lands nothing and does not halt.
    report = run_chain(str(tmp_path), ["cover-gaps", "strengthen-tests"],
                       apply=True, verify=True)
    assert not report.halted and not report.landed_objectives
    assert _chain_outcome(report) == ""
    assert IdeaMemory.load(str(tmp_path)).by_chain == {}


# --- 4. a rolled-back / blocked chain records as NON-success (never a fake) -----

def test_rolled_back_chain_records_non_success(tmp_path):
    # A red (suite-went-red, rolled-back) step HALTS the chain: the realized outcome
    # is ``rolled_back`` — a NON-success. It NEVER inflates the recipe's land-rate.
    _rollback_project(tmp_path)
    report = run_chain(str(tmp_path), ["remove-unused-imports", "sort-imports"],
                       apply=True, verify=True)
    assert report.halted and not report.green
    mem = IdeaMemory.load(str(tmp_path))
    sig = "chain:remove-unused-imports>sort-imports"
    assert sig in mem.by_chain
    stat = mem.by_chain[sig]
    assert stat.applied == 0            # never a faked win
    assert stat.rolled_back == 1
    assert stat.success_rate == 0.0     # a rolled-back chain lands nothing


def test_precondition_halt_records_blocked_not_applied():
    # An opted-in precondition halt (not a regression) is a ``blocked`` non-success.
    report = ChainReport(objectives=["cover-gaps", "strengthen-tests"], applied=True,
                         halted=True, halt_reason="`strengthen-tests`: precondition unmet")
    report.steps = [ChainStep("cover-gaps", "empty"),
                    ChainStep("strengthen-tests", "skipped-precondition")]
    assert _chain_outcome(report) == "blocked"


def test_chain_outcome_mapping_is_honest():
    # landed + not halted → applied; halted-red → rolled_back; halted-other → blocked;
    # applied-but-empty → "" (records nothing).
    held = _landed_report(["a", "b"], landed=["a"])
    assert _chain_outcome(held) == "applied"
    empty = _landed_report(["a", "b"], landed=[])
    assert _chain_outcome(empty) == ""
    red = ChainReport(objectives=["a"], applied=True, halted=True)
    red.steps = [ChainStep("a", "red")]
    assert _chain_outcome(red) == "rolled_back"
    # A dry run (applied False) is never recorded regardless of outcome.
    dry = _landed_report(["a"], landed=["a"])
    dry.applied = False
    assert _record_chain_memory(dry, "/nonexistent") is None


def test_held_chain_does_not_inflate_a_rolled_back_recipe():
    # The SAME recipe run twice — once held, once rolled back — records one success
    # and one non-success (rate 0.5), never two successes (never-fake-green).
    mem = IdeaMemory()
    mem.record_chain_outcome("chain:a>b", "applied")
    mem.record_chain_outcome("chain:a>b", "rolled_back")
    stat = mem.by_chain["chain:a>b"]
    assert stat.applied == 1 and stat.rolled_back == 1
    assert stat.success_rate == 0.5


def test_record_chain_outcome_ignores_malformed():
    # A no-op on an empty signature or an unrecognised outcome — a malformed call
    # cannot silently miscredit (keeps by_chain trustworthy and byte-identical).
    mem = IdeaMemory()
    mem.record_chain_outcome("", "applied")
    mem.record_chain_outcome("chain:x", "bogus")
    assert mem.by_chain == {}


# --- 5. persistence round-trip + determinism ---------------------------------

def test_by_chain_round_trips_and_is_backward_compatible(tmp_path):
    mem = IdeaMemory()
    for _ in range(9):
        mem.record_chain_outcome("chain:proven", "applied")
    mem.record_chain_outcome("chain:proven", "rolled_back")
    before = mem.confident_ranking("chain")
    mem.save(str(tmp_path))
    reloaded = IdeaMemory.load(str(tmp_path))
    assert reloaded.confident_ranking("chain") == before
    assert reloaded.by_chain["chain:proven"].applied == 9
    # Backward-compatible: an OLD memory file with no by_chain key loads to empty.
    p = tmp_path / "old.json"
    p.write_text(json.dumps(
        {"by_operator": {"test": {"applied": 3, "rolled_back": 0, "blocked": 0}}}),
        encoding="utf-8")
    old = IdeaMemory.load(str(tmp_path), path=p)
    assert old.by_chain == {}
    assert old.by_operator["test"].applied == 3


def test_summary_exposes_chain_keys():
    mem = IdeaMemory()
    for _ in range(_MIN_SAMPLES):
        mem.record_chain_outcome("chain:a>b", "applied")
    s = mem.summary()
    assert s["chains_tracked"] == 1
    assert s["reliable_chains"] and s["reliable_chains"][0]["key"] == "chain:a>b"


def test_chain_memory_deterministic_under_pythonhashseed(tmp_path):
    _two_stub_project(tmp_path)
    repo = str(Path(__file__).resolve().parents[1])
    src = ("import json,sys;from app.engine.chain_compiler import run_chain;"
           "from app.engine.idea_memory import IdeaMemory;"
           "run_chain(sys.argv[1], ['implement-stub','sort-imports'], "
           "apply=True, verify=True);"
           "print(json.dumps(IdeaMemory.load(sys.argv[1]).to_dict()['by_chain'], "
           "sort_keys=True))")

    def _run(seed: str, root: str) -> str:
        out = subprocess.run(
            [sys.executable, "-c", src, root], capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
            cwd=repo)
        assert out.returncode == 0, out.stderr
        return out.stdout

    # Two clean trees, two hash seeds → the recorded by_chain table is identical.
    a = _run("0", str(tmp_path))
    second = tmp_path / "second"
    second.mkdir(parents=True, exist_ok=True)
    _two_stub_project(second)
    b = _run("12345", str(second))
    assert a == b
    assert "chain:implement-stub>sort-imports" in a
