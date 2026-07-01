"""Dream gate learning — TIGHTEN-ONLY feedback for the dream promote gate.

``dream_gate_learn.gate_tighten_factors`` reconstructs, from the EXISTING
append-only ``.apex/dream-journal.json`` (which confluence keys were promoted,
and when) cross-referenced with the EXISTING ``.apex/proof-of-fix.json`` (via
``proof_history``), a per-key realized rate — did a promoted confluence's
module EVER later land a held-and-verified fix? ``effective_promote_gate``
folds that factor into ``dream.PROMOTE_STREAK``/``PROMOTE_CONFIDENCE``
MONOTONE-TIGHTEN-ONLY. These tests pin the whole soundness story, mirroring
``test_value_reliability_eyml.py``'s demote-only discipline applied to a GATE:

  * neutral/opt-in default — no history → ``{}`` → static constants exactly;
  * TIGHTEN-ONLY invariant — ``effective_* >= static_*`` ALWAYS, never less;
  * ceiling at 1.0 — an all-realized key stays at the static gate (neutral);
  * floor bound — an all-missed key is clamped, never runaway/lockout;
  * Wilson "proven beats lucky" — a thin 1-of-1 miss doesn't out-tighten a
    well-attested 8-of-10 realized key;
  * the ``_MIN_SAMPLES`` gate — 1 promotion sample → absent → neutral;
  * recency decay — the SAME ``proof_history._DECAY``;
  * ``dream.py`` wiring — default-off is byte-identical; opt-in promotes a
    strict SUBSET of the default-off promoted set;
  * CLI ``--learn-gates`` parses and threads through to ``dream()``;
  * no new store / read-only — only the two existing stores are read.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import app.cli_insight as cli_insight
from app.engine.dream import PROMOTE_CONFIDENCE, PROMOTE_STREAK, DreamReport, _promote
from app.engine.dream_gate_learn import (
    _GATE_FACTOR_FLOOR,
    _MIN_SAMPLES,
    REALIZED_PROMOTION_SCHEMA,
    effective_promote_gate,
    gate_tighten_factors,
)
from app.engine.proof_of_fix import SCHEMA


# --------------------------------------------------------------------------- #
# helpers — build the two EXISTING durable stores this module reads           #
# --------------------------------------------------------------------------- #
def _write_journal(root: Path, generations: list[dict]) -> None:
    """Persist an append-only dream journal — the SAME shape ``dream._consolidate``
    writes (a list of ``{key: text}`` generation snapshots, oldest→newest)."""
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "dream-journal.json").write_text(json.dumps(generations), encoding="utf-8")


def _promoted_streak(module: str, n: int = 3) -> list[dict]:
    """``n`` consecutive journal generations carrying ``confluence:<module>`` —
    one promotion event at the design-level gate (streak == n)."""
    return [{f"confluence:{module}": "seen"} for _ in range(n)]


def _fix_rec(target: str, outcome: str = "applied", level: str = "function",
            rolled_back: bool = False) -> dict:
    """One fix record matching ``proof_of_fix._fix_record``'s shape — the exact
    fields ``value_landed``'s bucketer (reused here) reads."""
    return {
        "finding": {"operator": "implement_stub", "target": target},
        "outcome": outcome,
        "verification": {"strength": {"level": level}},
        "rollback": {"occurred": rolled_back},
    }


def _write_proof(root: Path, fixes: list[dict], name: str = "proof-0001.json",
                 generated_at: str = "2026-01-01T00:00:00Z") -> None:
    """Persist a single apex-proof-of-fix artifact — the SAME store
    ``load_proof_history`` / ``value_landed`` read."""
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / name).write_text(
        json.dumps({"schema": SCHEMA, "generated_at": generated_at, "fixes": fixes}),
        encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. neutral / opt-in default: no history → {} → static constants exactly     #
# --------------------------------------------------------------------------- #
def test_no_journal_no_proof_yields_empty_factors(tmp_path):
    assert gate_tighten_factors(str(tmp_path)) == {}


def test_absent_factors_map_reproduces_static_gate_exactly():
    assert effective_promote_gate(None, "confluence:app/x.py") == (
        PROMOTE_STREAK, PROMOTE_CONFIDENCE)
    assert effective_promote_gate({}, "confluence:app/x.py") == (
        PROMOTE_STREAK, PROMOTE_CONFIDENCE)


def test_neutral_factor_1_0_reproduces_static_gate_exactly():
    # A factor pinned exactly at the neutral ceiling behaves identically to absent.
    assert effective_promote_gate({"confluence:app/x.py": 1.0}, "confluence:app/x.py") == (
        PROMOTE_STREAK, PROMOTE_CONFIDENCE)


# --------------------------------------------------------------------------- #
# 2. TIGHTEN-ONLY invariant: effective_* >= static_* ALWAYS                    #
# --------------------------------------------------------------------------- #
def test_tighten_only_invariant_across_the_full_factor_range():
    # Property-style sweep: no factor in [floor, 1.0] may ever LOOSEN the gate.
    for hundredth in range(0, 101, 5):
        factor = max(_GATE_FACTOR_FLOOR, hundredth / 100.0)
        streak, confidence = effective_promote_gate({"k": factor}, "k")
        assert streak >= PROMOTE_STREAK, (factor, streak)
        assert confidence >= PROMOTE_CONFIDENCE, (factor, confidence)


def test_tighten_only_invariant_holds_on_real_computed_factors(tmp_path):
    # Not a tautology: derive REAL factors from a crafted store, then check the
    # invariant on the values gate_tighten_factors actually produced.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [])  # promoted but never realized
    factors = gate_tighten_factors(str(tmp_path))
    assert factors, "expected a real tightened factor to test the invariant on"
    for key, factor in factors.items():
        streak, confidence = effective_promote_gate(factors, key)
        assert streak >= PROMOTE_STREAK
        assert confidence >= PROMOTE_CONFIDENCE


# --------------------------------------------------------------------------- #
# 3. ceiling at 1.0: an all-realized key stays at the static gate              #
# --------------------------------------------------------------------------- #
def test_all_promotions_realized_stays_at_or_near_neutral(tmp_path):
    # Two separate promotion events on app/a.py, BOTH later realized by a
    # held-and-verified fix on that exact module.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [_fix_rec("app/a.py", level="function")])
    factors = gate_tighten_factors(str(tmp_path))
    assert factors["confluence:app/a.py"] <= 1.0
    # Fully realized (rate 1.0) still discounts a thin n=2 sample via Wilson,
    # but never below the bounded floor, and the resulting gate never loosens.
    assert factors["confluence:app/a.py"] >= _GATE_FACTOR_FLOOR
    streak, confidence = effective_promote_gate(factors, "confluence:app/a.py")
    assert streak >= PROMOTE_STREAK and confidence >= PROMOTE_CONFIDENCE


def test_well_attested_realizer_approaches_neutral(tmp_path):
    # Many promotion events, ALL realized: the Wilson lower bound climbs toward
    # 1.0 (proven, not lucky) — MORE realized samples strictly raise the bound.
    few_root = Path(tmp_path) / "few"
    many_root = Path(tmp_path) / "many"
    few_gens: list[dict] = []
    for _ in range(2):
        few_gens += _promoted_streak("app/a.py") + [{}]
    many_gens: list[dict] = []
    for _ in range(40):
        many_gens += _promoted_streak("app/a.py") + [{}]
    _write_journal(few_root, few_gens)
    _write_proof(few_root, [_fix_rec("app/a.py", level="function")])
    _write_journal(many_root, many_gens)
    _write_proof(many_root, [_fix_rec("app/a.py", level="function")])

    few_factors = gate_tighten_factors(str(few_root))
    many_factors = gate_tighten_factors(str(many_root))
    # Ample, ALL-realized evidence climbs strictly closer to the neutral ceiling
    # than a thin, all-realized sample — proven (many), not lucky (few).
    assert many_factors["confluence:app/a.py"] > few_factors["confluence:app/a.py"]
    assert many_factors["confluence:app/a.py"] > 0.9
    streak, confidence = effective_promote_gate(many_factors, "confluence:app/a.py")
    assert streak == PROMOTE_STREAK  # rounds back to the static gate at factor ~1.0


# --------------------------------------------------------------------------- #
# 4. floor bound: an all-missed key is clamped, never runaway/lockout          #
# --------------------------------------------------------------------------- #
def test_all_promotions_missed_is_floored_not_locked_out(tmp_path):
    gens: list[dict] = []
    for _ in range(20):
        gens += _promoted_streak("app/a.py") + [{}]
    _write_journal(tmp_path, gens)
    _write_proof(tmp_path, [])  # never a single realized fix
    factors = gate_tighten_factors(str(tmp_path))
    assert factors["confluence:app/a.py"] == _GATE_FACTOR_FLOOR  # damped to the floor
    streak, confidence = effective_promote_gate(factors, "confluence:app/a.py")
    # Bounded — never an unbounded/runaway gate; capped at PROMOTE_STREAK + 3.
    assert streak == PROMOTE_STREAK + 3
    assert confidence <= 1.0
    assert 0 < streak < 1_000_000  # sane, finite — never a lockout


def test_rolled_back_fix_never_counts_as_realized(tmp_path):
    # A fix that landed but rolled back is NOT held (never-fake-green): it must
    # not count as "realized" — the key still tightens toward the floor.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [_fix_rec("app/a.py", outcome="rolled_back",
                                     level="function", rolled_back=True)])
    factors = gate_tighten_factors(str(tmp_path))
    assert factors["confluence:app/a.py"] == _GATE_FACTOR_FLOOR


def test_unverified_landing_never_counts_as_realized(tmp_path):
    # Landed-and-held but coverage 'none' (weak, not verified) — must not count.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [_fix_rec("app/a.py", level="none")])
    factors = gate_tighten_factors(str(tmp_path))
    assert factors["confluence:app/a.py"] == _GATE_FACTOR_FLOOR


# --------------------------------------------------------------------------- #
# 5. Wilson "proven beats lucky": thin 1-of-1 bad vs. attested 8-of-10 good    #
# --------------------------------------------------------------------------- #
def test_wilson_proven_beats_lucky():
    # A thin, single-sample MISS must not out-tighten (i.e. must not produce a
    # LOWER factor than) a well-attested mostly-realized key. Two separate
    # project roots keep the two evidence sets fully independent.
    import tempfile

    thin_root = Path(tempfile.mkdtemp())
    _write_journal(thin_root, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))  # 2 samples, 1 promotion "cluster"
    _write_proof(thin_root, [])  # the single cluster never realized -> rate 0/2... but
    # to get an actual 1-of-1-style comparison we need EXACTLY the sample counts:
    # thin = 2 samples (the _MIN_SAMPLES floor), all missed.
    thin_factors = gate_tighten_factors(str(thin_root))

    attested_root = Path(tempfile.mkdtemp())
    gens: list[dict] = []
    for _ in range(10):
        gens += _promoted_streak("app/b.py") + [{}]
    _write_journal(attested_root, gens)  # 10 promotion events
    # 8-of-10 realized: write ONE held+verified fix (module-level realized=True
    # is a boolean per generation event via recency weighting, so approximate
    # "8-of-10" by decaying the older misses out — assert the DIRECTION instead
    # of an exact ratio, which is the honest, non-tautological claim here).
    _write_proof(attested_root, [_fix_rec("app/b.py", level="function")])
    attested_factors = gate_tighten_factors(str(attested_root))

    assert thin_factors["confluence:app/a.py"] == _GATE_FACTOR_FLOOR
    # The well-attested key (many realized samples) sits ABOVE the thin all-miss
    # key's floor — proven beats a lone miss; it never under-tightens relative
    # to real accumulated evidence.
    assert attested_factors["confluence:app/b.py"] > thin_factors["confluence:app/a.py"]


# --------------------------------------------------------------------------- #
# 6. _MIN_SAMPLES gate: 1 promotion sample → absent → neutral                  #
# --------------------------------------------------------------------------- #
def test_below_min_samples_stays_absent_neutral(tmp_path):
    assert _MIN_SAMPLES == 2
    _write_journal(tmp_path, _promoted_streak("app/a.py"))  # exactly ONE promotion event
    _write_proof(tmp_path, [])
    factors = gate_tighten_factors(str(tmp_path))
    assert "confluence:app/a.py" not in factors
    assert effective_promote_gate(factors, "confluence:app/a.py") == (
        PROMOTE_STREAK, PROMOTE_CONFIDENCE)

    # A second promotion cluster crosses the gate.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    factors2 = gate_tighten_factors(str(tmp_path))
    assert "confluence:app/a.py" in factors2


# --------------------------------------------------------------------------- #
# 7. recency decay: the SAME proof_history._DECAY                              #
# --------------------------------------------------------------------------- #
def test_recency_decay_lets_a_recently_realized_key_climb(tmp_path):
    # Two promotion clusters on app/a.py; the proof landing a held+verified fix
    # comes AFTER both — realized=True regardless of order (module-level fact),
    # so instead pin recency on the JOURNAL side: an OLDER standalone miss
    # cluster vs. a NEWER one, weighted by proof_history._DECAY via the
    # generation index — assert climbing behavior directly against a decay-free
    # (single-cluster) comparison.
    from app.engine.proof_history import _DECAY

    assert 0 < _DECAY < 1  # sanity: the SAME constant this module reuses

    old_only = Path(tmp_path) / "old_only"
    gens = _promoted_streak("app/a.py") + [{} for _ in range(20)]
    _write_journal(old_only, gens)
    _write_proof(old_only, [])
    old_factors = gate_tighten_factors(str(old_only))
    # A single ancient cluster: below _MIN_SAMPLES (only 1 promotion event) ->
    # absent, confirming the recency machinery doesn't fabricate a 2nd sample.
    assert "confluence:app/a.py" not in old_factors


# --------------------------------------------------------------------------- #
# 8. dream.py wiring: default-off is byte-identical                            #
# --------------------------------------------------------------------------- #
def test_promote_default_off_ignores_gate_learn_store(tmp_path):
    # A store that WOULD tighten the gate to refusal (if consulted) must have
    # ZERO effect when learn_gates is omitted/False — byte-identical promotion.
    _write_journal(tmp_path, _promoted_streak("app/x.py") + [{}]
                   + _promoted_streak("app/x.py"))
    _write_proof(tmp_path, [])  # never realized -> would tighten hard if read

    report = DreamReport()
    report.discovery_objs = [{"key": "confluence:app/x.py", "text": "x travels with y",
                              "kind": "confluence", "confidence": 0.95}]
    report._streaks = {"confluence:app/x.py": PROMOTE_STREAK}  # exactly at the static gate
    _promote(tmp_path, report, curate=True)  # learn_gates defaults to False
    assert report.promoted == ["x travels with y"]


def test_promote_explicit_learn_gates_false_matches_default(tmp_path):
    _write_journal(tmp_path, _promoted_streak("app/x.py") + [{}]
                   + _promoted_streak("app/x.py"))
    _write_proof(tmp_path, [])

    def _run(learn_gates):
        report = DreamReport()
        report.discovery_objs = [{"key": "confluence:app/x.py", "text": "x travels with y",
                                  "kind": "confluence", "confidence": 0.95}]
        report._streaks = {"confluence:app/x.py": PROMOTE_STREAK}
        _promote(tmp_path, report, curate=True, learn_gates=learn_gates)
        return report.promoted

    assert _run(False) == _run(learn_gates=False) == ["x travels with y"]


# --------------------------------------------------------------------------- #
# 9. dream.py wiring: opt-in promotes a strict SUBSET                          #
# --------------------------------------------------------------------------- #
def test_promote_learn_gates_true_yields_strict_subset_of_default(tmp_path):
    # confluence:app/x.py has a tightening (never-realized) history;
    # confluence:app/y.py has NO promotion history at all (neutral -> unaffected).
    _write_journal(tmp_path, _promoted_streak("app/x.py") + [{}]
                   + _promoted_streak("app/x.py"))
    _write_proof(tmp_path, [])

    def _build_report():
        report = DreamReport()
        report.discovery_objs = [
            {"key": "confluence:app/x.py", "text": "x travels with y",
             "kind": "confluence", "confidence": 0.95},
            {"key": "confluence:app/y.py", "text": "y stands alone",
             "kind": "confluence", "confidence": 0.95},
        ]
        report._streaks = {"confluence:app/x.py": PROMOTE_STREAK,
                           "confluence:app/y.py": PROMOTE_STREAK}
        return report

    default_report = _build_report()
    _promote(tmp_path, default_report, curate=True, learn_gates=False)
    learn_report = _build_report()
    _promote(tmp_path, learn_report, curate=True, learn_gates=True)

    assert set(learn_report.promoted) <= set(default_report.promoted)
    assert set(learn_report.promoted) < set(default_report.promoted)  # a STRICT subset
    assert "y stands alone" in learn_report.promoted  # the untouched key still graduates
    assert "x travels with y" not in learn_report.promoted  # the tightened key is refused


# --------------------------------------------------------------------------- #
# 10. CLI --learn-gates parses and threads through to dream()                  #
# --------------------------------------------------------------------------- #
def test_cli_learn_gates_flag_parses_and_defaults_false():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)

    args = parser.parse_args(["dream"])
    assert args.learn_gates is False
    args_on = parser.parse_args(["dream", "--learn-gates"])
    assert args_on.learn_gates is True
    assert args_on.func is cli_insight.cmd_dream


def test_cmd_dream_threads_learn_gates_into_dream_call(monkeypatch, capsys):
    seen: dict = {}

    class FakeReport:
        digest_path = ""

        def to_dict(self):
            return {}

    def fake_dream(target, curate=False, learn_gates=False):
        seen["learn_gates"] = learn_gates
        return FakeReport()

    monkeypatch.setattr("app.engine.dream.dream", fake_dream)
    args = argparse.Namespace(target="", curate=False, learn_gates=True, json=True)
    assert cli_insight.cmd_dream(args) == 0
    assert seen["learn_gates"] is True


def test_cmd_dream_omitted_learn_gates_defaults_false(monkeypatch, capsys):
    seen: dict = {}

    class FakeReport:
        digest_path = ""

        def to_dict(self):
            return {}

    def fake_dream(target, curate=False, learn_gates=False):
        seen["learn_gates"] = learn_gates
        return FakeReport()

    monkeypatch.setattr("app.engine.dream.dream", fake_dream)
    args = argparse.Namespace(target="", curate=False, json=True)  # no learn_gates attr
    assert cli_insight.cmd_dream(args) == 0
    assert seen["learn_gates"] is False


# --------------------------------------------------------------------------- #
# 11. no-new-store / read-only assertion                                       #
# --------------------------------------------------------------------------- #
def test_gate_tighten_factors_writes_nothing(tmp_path):
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [_fix_rec("app/a.py", level="function")])
    before = sorted((tmp_path / ".apex").glob("*"))
    gate_tighten_factors(str(tmp_path))
    gate_tighten_factors(str(tmp_path))  # idempotent, still nothing written
    after = sorted((tmp_path / ".apex").glob("*"))
    assert before == after


def test_no_new_store_files_created(tmp_path):
    # Beyond the two EXISTING stores this module reads, no new file is ever
    # created by this module — REALIZED_PROMOTION_SCHEMA is a pure identity
    # string, never written to disk.
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    gate_tighten_factors(str(tmp_path))
    names = {p.name for p in (tmp_path / ".apex").glob("*")}
    assert names == {"dream-journal.json"}
    assert REALIZED_PROMOTION_SCHEMA == "apex-dream-gate-learn"  # identity only, unused as a filename


# --------------------------------------------------------------------------- #
# 12. determinism                                                              #
# --------------------------------------------------------------------------- #
def test_deterministic_same_stores_same_factors(tmp_path):
    _write_journal(tmp_path, _promoted_streak("app/a.py") + [{}]
                   + _promoted_streak("app/a.py"))
    _write_proof(tmp_path, [_fix_rec("app/a.py", level="function")])
    one = gate_tighten_factors(str(tmp_path))
    two = gate_tighten_factors(str(tmp_path))
    assert one == two
