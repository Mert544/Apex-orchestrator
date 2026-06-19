"""Recency-weighted generational reliability — the "çağ atlatma" learning leap.

``app/engine/proof_history.py`` learns a flat lifetime landing ratio per action
(:func:`learned_reliability`): every recorded outcome weighs the same forever, so
a fix family that stopped rolling back several runs ago is dragged down by
ancient failures with no generational forgetting. The additive, OPT-IN
:func:`learned_reliability_decayed` fixes that — it orders proofs by the loader's
EXISTING deterministic key (``generated_at`` then filename) and weights proof
position ``i`` (0=oldest) by ``_DECAY ** (n-1-i)``, so recent generations weigh
more. ``app/engine/fix_risk_model.fix_risk`` consumes it behind a default-off
``recency`` switch.

These tests pin: byte-determinism (rank arithmetic, no wall-clock); the
generational point (recent successes after old failures score STRICTLY higher
than the flat ratio, and the inverse STRICTLY lower); empty-history safety; and
that the ``recency=False`` path stays byte-identical to today. A deep-mutation
section hardens the decay EXPONENT and the proof ORDERING against surviving
AST mutants, matching the house style of the ``_deep_mutation_eyml`` suites.

All assertions are deterministic (no time/random; exact equality on rounded
floats and sorted keys; fixtures write real proof JSON to ``<root>/.apex/``).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.fix_risk_model import fix_risk
from app.engine.proof_history import (
    _DECAY,
    _reliability_weighted,
    learned_reliability,
    learned_reliability_decayed,
    load_proof_history,
)
from app.engine.proof_of_fix import SCHEMA


def _proof(fixes: list[dict], generated_at: str) -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": fixes}


def _write(apex_dir: Path, name: str, proof: dict) -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


def _fix(outcome: str, action: str = "a", module: str = "app/m.py") -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


def _ts(day: int) -> str:
    return f"2026-01-{day:02d}T00:00:00+00:00"


# --- determinism: rank arithmetic, no wall-clock -----------------------------


def test_decayed_is_byte_identical_across_two_calls(tmp_path: Path):
    """Same proof content → identical decayed mapping across two calls. The
    score reads ranks (proof ORDER), never the wall clock, so repeated calls on
    unchanged files are byte-for-byte equal."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("rolled_back")] * 2, _ts(1)))
    _write(apex, "02.json", _proof([_fix("applied")] * 2, _ts(5)))
    history = load_proof_history(tmp_path)
    first = learned_reliability_decayed(history)
    second = learned_reliability_decayed(history)
    assert first == second
    assert first == {"a": _reliability_weighted(
        _DECAY ** 0 * 2, _DECAY ** 1 * 2 + _DECAY ** 0 * 2)}


# --- the generational point: recent wins outgrow ancient failures ------------


def test_recent_successes_score_strictly_higher_than_flat(tmp_path: Path):
    """OLD generations all rolled back, RECENT generations all applied: the flat
    lifetime ratio averages them to 0.5, but the decayed ratio weights the
    recent successes more, so it scores STRICTLY HIGHER. This is the whole point
    — a fix family that stopped rolling back can climb out from under its past."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("rolled_back")] * 3, _ts(1)))
    _write(apex, "02.json", _proof([_fix("rolled_back")] * 3, _ts(2)))
    _write(apex, "03.json", _proof([_fix("applied")] * 3, _ts(5)))
    _write(apex, "04.json", _proof([_fix("applied")] * 3, _ts(6)))
    history = load_proof_history(tmp_path)
    flat = learned_reliability(history)["a"]
    decayed = learned_reliability_decayed(history)["a"]
    assert flat == 0.5
    assert decayed > flat


def test_recent_failures_score_strictly_lower_than_flat(tmp_path: Path):
    """The inverse: OLD generations all applied, RECENT generations all rolled
    back. Flat ratio is again 0.5, but recency weights the fresh failures, so the
    decayed ratio is STRICTLY LOWER — recent regressions are not forgiven by an
    old clean streak."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("applied")] * 3, _ts(1)))
    _write(apex, "02.json", _proof([_fix("applied")] * 3, _ts(2)))
    _write(apex, "03.json", _proof([_fix("rolled_back")] * 3, _ts(5)))
    _write(apex, "04.json", _proof([_fix("rolled_back")] * 3, _ts(6)))
    history = load_proof_history(tmp_path)
    flat = learned_reliability(history)["a"]
    decayed = learned_reliability_decayed(history)["a"]
    assert flat == 0.5
    assert decayed < flat


def test_uniform_history_decayed_equals_flat(tmp_path: Path):
    """When every generation has the SAME landing ratio, recency weighting
    cannot move the score: the decayed ratio equals the flat ratio. (All-applied
    across all generations → both exactly 1.0.) This pins that decay is a
    re-weighting, not an arbitrary offset."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("applied")] * 2, _ts(1)))
    _write(apex, "02.json", _proof([_fix("applied")] * 2, _ts(5)))
    history = load_proof_history(tmp_path)
    assert learned_reliability_decayed(history) == {"a": 1.0}
    assert learned_reliability(history) == {"a": 1.0}


# --- empty / malformed: safe default, never raises ---------------------------


def test_empty_history_is_empty_mapping(tmp_path: Path):
    """Empty history → ``{}`` (mirrors ``learned_reliability``); never raises."""
    assert learned_reliability_decayed([]) == {}
    assert learned_reliability_decayed(load_proof_history(tmp_path)) == {}


def test_action_less_fixes_are_omitted(tmp_path: Path):
    """A fix with no action cites the ``<unknown>`` placeholder, which is dropped
    from the decayed mapping just as it is from the flat one — callers only see
    real action types."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof(
        [{"finding": {"target": "app/m.py"}, "outcome": "applied"}], _ts(1)))
    history = load_proof_history(tmp_path)
    assert learned_reliability_decayed(history) == {}


def test_zero_weighted_total_is_neutral_zero():
    """The weighted-ratio helper returns a neutral 0.0 on a non-positive total,
    never a ZeroDivisionError — mirroring ``_reliability``'s zero-total guard."""
    assert _reliability_weighted(0.0, 0.0) == 0.0
    assert _reliability_weighted(0.0, -1.0) == 0.0


# --- fix_risk opt-in wiring: default-off is byte-identical --------------------


def test_fix_risk_recency_false_is_byte_identical_default(tmp_path: Path):
    """The opt-in ``recency`` switch defaults to ``False`` and the explicit
    ``recency=False`` call MUST equal the historical default call byte-for-byte:
    the flat reliability signal is used unchanged. This guards every existing
    fix-risk score against drift."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("rolled_back")] * 3, _ts(1)))
    _write(apex, "02.json", _proof([_fix("applied")] * 3, _ts(5)))
    default = fix_risk(tmp_path, "a", "app/m.py")
    explicit_off = fix_risk(tmp_path, "a", "app/m.py", recency=False)
    assert explicit_off == default


def test_fix_risk_recency_true_lowers_risk_for_recovered_family(tmp_path: Path):
    """A fix family that rolled back long ago but lands cleanly now: flat
    reliability is 0.5 (mid risk), but with ``recency=True`` the reliability
    signal sees mostly-recent successes, so the fused risk is STRICTLY LOWER than
    the flat (recency-off) score. The track-record and avoid signals are shared
    by both modes, so the gap is attributable to the reliability signal alone."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("rolled_back")] * 3, _ts(1)))
    _write(apex, "02.json", _proof([_fix("rolled_back")] * 3, _ts(2)))
    _write(apex, "03.json", _proof([_fix("applied")] * 3, _ts(5)))
    _write(apex, "04.json", _proof([_fix("applied")] * 3, _ts(6)))
    flat_risk = fix_risk(tmp_path, "a", "app/m.py", recency=False)
    recent_risk = fix_risk(tmp_path, "a", "app/m.py", recency=True)
    assert recent_risk < flat_risk


def test_fix_risk_recency_true_empty_history_is_baseline(tmp_path: Path):
    """With no history the recency path still abstains to the neutral baseline
    0.5 — the opt-in never raises on empty/missing proofs."""
    assert fix_risk(tmp_path, "a", "app/m.py", recency=True) == 0.5


# --- deep-mutation hardening: the decay exponent and the ordering ------------


def test_decay_constant_is_below_one_so_forgetting_happens(tmp_path: Path):
    """A decay of exactly 1.0 would make every generation weigh the same, i.e.
    no forgetting — the decayed ratio would collapse onto the flat ratio. The
    constant must be a real discount in (0, 1) so the generational tests above
    can ever diverge from flat."""
    assert 0.0 < _DECAY < 1.0


def test_newest_proof_weighs_one_oldest_weighs_least(tmp_path: Path):
    """Pins the EXPONENT direction ``_DECAY ** (n-1-i)``: the newest proof
    (i=n-1) weighs ``_DECAY**0 == 1`` and the oldest (i=0) weighs the most
    discounted ``_DECAY**(n-1)``. Constructed so a REVERSED exponent
    (``_DECAY ** i``, weighting the OLD generation) would flip the comparison and
    fail. Here one old rolled_back and one recent applied: weighting the recent
    one (correct) gives reliability == 1/(1+_DECAY); a reversed exponent would
    give _DECAY/(_DECAY+1), a strictly different, lower value."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof([_fix("rolled_back")], _ts(1)))
    _write(apex, "02.json", _proof([_fix("applied")], _ts(5)))
    history = load_proof_history(tmp_path)
    got = learned_reliability_decayed(history)["a"]
    correct = round(1.0 / (1.0 + _DECAY), 4)
    reversed_exponent = round(_DECAY / (_DECAY + 1.0), 4)
    assert got == correct
    assert got != reversed_exponent
    assert got > reversed_exponent


def test_ordering_follows_loader_key_not_file_listing(tmp_path: Path):
    """The decay must rank by the LOADER's deterministic order (generated_at then
    filename), not raw glob/file order. Here the lexically-LATER filename holds
    the OLDER timestamp (and the failures); the lexically-earlier file holds the
    newer successes. Correct timestamp ordering weights the successes, scoring
    STRICTLY above flat; ranking by filename instead would weight the failures
    and score at-or-below flat. Catches a mutant that drops the timestamp key."""
    apex = tmp_path / ".apex"
    # filename "aaa" is lexically first but is the OLD, failing generation
    _write(apex, "zzz_new.json", _proof([_fix("applied")] * 3, _ts(9)))
    _write(apex, "aaa_old.json", _proof([_fix("rolled_back")] * 3, _ts(1)))
    history = load_proof_history(tmp_path)
    flat = learned_reliability(history)["a"]
    decayed = learned_reliability_decayed(history)["a"]
    assert flat == 0.5
    assert decayed > flat


def test_single_generation_decay_equals_flat(tmp_path: Path):
    """With a single proof generation n==1, the exponent ``n-1-i`` is 0 for the
    lone proof → weight 1.0 → the decayed ratio is exactly the flat ratio. Pins
    the ``n-1`` term (an off-by-one like ``n-i`` would still weight 1.0 here, but
    ``-1-i`` vs ``-i`` is separated by the multi-generation tests above)."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof(
        [_fix("applied"), _fix("rolled_back"), _fix("blocked")], _ts(1)))
    history = load_proof_history(tmp_path)
    assert learned_reliability_decayed(history) == learned_reliability(history)


def test_per_action_buckets_are_independent_and_sorted(tmp_path: Path):
    """Two distinct actions are weighted and reported independently, and the
    mapping keys are emitted sorted (deterministic order). Action 'a' recovers
    (old fail, new pass → above flat); action 'b' is uniformly applied (1.0)."""
    apex = tmp_path / ".apex"
    _write(apex, "01.json", _proof(
        [_fix("rolled_back", action="a"), _fix("applied", action="b")], _ts(1)))
    _write(apex, "02.json", _proof(
        [_fix("applied", action="a"), _fix("applied", action="b")], _ts(5)))
    history = load_proof_history(tmp_path)
    decayed = learned_reliability_decayed(history)
    assert list(decayed) == sorted(decayed)
    assert decayed["b"] == 1.0
    assert decayed["a"] > learned_reliability(history)["a"]
