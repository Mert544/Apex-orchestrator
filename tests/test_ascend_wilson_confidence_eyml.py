"""Ascend ranks by EVIDENCE-DAMPED reliability (Wilson lower bound), not raw rate.

The decision layer's priority is ``pending * (1 + payoff) * reliability``. The
reliability term now reads the Wilson score lower bound (``_Stat.confidence``)
instead of the raw ``success_rate``, so among TRACKED operators a thin-but-perfect
2-of-2 (rate 1.000, lb≈0.34) can no longer outrank a well-attested 9-of-10 (rate
0.900, lb≈0.60). (An operator below ``_MIN_SAMPLES`` — e.g. a 1-of-1, whose own
Wilson bound is ≈0.21 — stays absent and neutral at 1.0; that bound is never read.)
These tests are deterministic witnesses: proven beats lucky among tracked ops,
thin/fresh ops stay neutral, and the zero-sample bound never enters the ranking.
"""

from __future__ import annotations

import json

import app.engine.ascend as asc
from app.engine.ascend import land_factors, rank_objectives
from app.engine.idea_memory import _Stat


def _write_memory(tmp_path, by_operator: dict) -> None:
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".apex" / "idea-memory.json").write_text(
        json.dumps({"by_operator": by_operator, "by_label": {}}), encoding="utf-8")


def test_confidence_witness_9of10_beats_1of1():
    """The driving fact: at the SAME perfect/near-perfect rate the larger sample
    wins. A lucky 1-of-1 (rate 1.000) has a Wilson lower bound BELOW a proven
    9-of-10 (rate 0.900) — the raw rate would have ordered these backwards."""
    lucky = _Stat(applied=1, blocked=0)        # 1/1 → rate 1.000
    proven = _Stat(applied=9, blocked=1)        # 9/10 → rate 0.900
    assert lucky.success_rate > proven.success_rate     # raw rate: lucky "wins"
    assert proven.confidence > lucky.confidence         # Wilson: proven wins
    assert round(lucky.confidence, 3) == 0.207
    assert round(proven.confidence, 3) == 0.596


def test_land_factors_uses_wilson_lower_bound(tmp_path):
    """land_factors reports the Wilson lower bound, so a thin-but-perfect 2-of-2
    yields a far SMALLER reliability factor than a proven 9-of-10 — the opposite
    of the raw success_rate (1.000 vs 0.900 would have ranked the 2-of-2 higher).

    (A 1-of-1 is below _MIN_SAMPLES and never reaches land_factors at all —
    covered separately by test_below_min_samples_stays_neutral; here both clear
    the sample gate so the comparison is purely Wilson-vs-raw.)"""
    _write_memory(tmp_path, {
        "sort_imports": {"applied": 2, "blocked": 0},        # thin/lucky 2/2
        "merge_isinstance": {"applied": 9, "blocked": 1},     # proven 9/10
    })
    f = land_factors(str(tmp_path))
    # Raw rate would put the 2/2 (1.000) ABOVE the 9/10 (0.900); Wilson flips it.
    assert f["merge-isinstance"] > f["sort-imports"]
    assert round(f["sort-imports"], 3) == 0.342      # 2/2 Wilson lower bound
    assert round(f["merge-isinstance"], 3) == 0.596  # 9/10 Wilson lower bound


def test_rank_demotes_lucky_below_proven(tmp_path, monkeypatch):
    """End-to-end on rank_objectives: a thin-but-perfect 2-of-2 operator with MORE
    pending debt still ranks BELOW a proven 9-of-10 once reliability is Wilson-damped.

    Pending alone would put ``lucky`` first (6 vs 5). With RAW rates ``lucky``
    (6*1.000=6.0) leads ``proven`` (5*0.900=4.5). With Wilson the lucky 2/2 factor
    (≈0.342) sinks it to 6*0.342≈2.05, below proven's 5*0.596≈2.98 — proven wins.
    This is the whole point of the change: proven evidence beats lucky thin runs."""
    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})

    def fake_map():
        return {"lucky": (lambda r: 6.0, lambda r: []),
                "proven": (lambda r: 5.0, lambda r: [])}

    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["lucky", "proven"])
    _write_memory(tmp_path, {
        "lucky": {"applied": 2, "blocked": 0},        # 2/2 thin/lucky
        "proven": {"applied": 9, "blocked": 1},        # 9/10 proven
    })

    ranked = rank_objectives(str(tmp_path), ["lucky", "proven"])
    assert ranked[0].objective == "proven"
    assert ranked[1].objective == "lucky"
    # The Wilson factors are what produced the flip (not pending, where lucky leads).
    assert round(ranked[0].reliability, 3) == 0.596   # proven 9/10
    assert round(ranked[1].reliability, 3) == 0.342   # lucky 2/2


def test_fresh_zero_sample_op_stays_neutral(tmp_path, monkeypatch):
    """A fresh operator (no recorded outcomes) must NOT be silently dominated: it
    is absent from land_factors (gated by _MIN_SAMPLES) and so ranks at the
    neutral reliability 1.0 — the zero-sample Wilson bound (0.0) never enters."""
    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})

    def fake_map():
        return {"fresh": (lambda r: 4.0, lambda r: []),
                "tracked": (lambda r: 4.0, lambda r: [])}

    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["fresh", "tracked"])
    # Only "tracked" has history; "fresh" has none.
    _write_memory(tmp_path, {"tracked": {"applied": 5, "blocked": 0}})

    factors = land_factors(str(tmp_path))
    assert "fresh" not in factors                     # no samples → absent
    ranked = rank_objectives(str(tmp_path), ["fresh", "tracked"])
    by_name = {r.objective: r for r in ranked}
    assert by_name["fresh"].reliability == 1.0        # neutral, not 0.0
    # Equal pending (4 each): the neutral fresh op (4*1.0=4) actually outranks the
    # evidence-damped 5/5 tracked op (4*0.565≈2.26) — a fresh op is never buried.
    assert by_name["fresh"].priority > by_name["tracked"].priority
    assert ranked[0].objective == "fresh"


def test_below_min_samples_stays_neutral(tmp_path):
    """An operator with a single recorded outcome (below _MIN_SAMPLES=2) is still
    absent from land_factors — the zero/thin-sample guard is unchanged, so a
    1-of-1 contributes a neutral 1.0 to ranking rather than its 0.207 bound."""
    _write_memory(tmp_path, {"sort_imports": {"applied": 1, "blocked": 0}})  # n=1
    assert "sort-imports" not in land_factors(str(tmp_path))


def test_zero_sample_confidence_is_zero_but_never_reached():
    """Documented invariant: the Wilson bound at zero samples is 0.0 and does not
    crash — but the _MIN_SAMPLES gate in land_factors means it is never read, so a
    fresh op cannot be dragged to 0.0 (it stays absent → neutral 1.0)."""
    assert _Stat().confidence == 0.0
    assert _Stat(applied=0, blocked=0).total == 0


def test_proven_blocker_held_at_floor(tmp_path):
    """A proven blocker (0-of-many) has a Wilson lower bound of 0.0, but
    land_factors holds it at _RELIABILITY_FLOOR so it is heavily damped, never
    fully erased (the climb can still reach it once nothing else has work)."""
    _write_memory(tmp_path, {"sort_imports": {"applied": 0, "blocked": 8}})
    f = land_factors(str(tmp_path))
    assert _Stat(applied=0, blocked=8).confidence == 0.0   # raw Wilson bound
    assert f["sort-imports"] == asc._RELIABILITY_FLOOR      # but floored, not 0.0


def test_more_evidence_at_same_rate_outranks(tmp_path, monkeypatch):
    """Determinism + monotonicity: two operators at the SAME rate but different
    sample counts rank by EVIDENCE — 50-of-50 outranks 5-of-5 — and the order is
    identical across repeated calls (no time/random)."""
    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})

    def fake_map():
        return {"thin": (lambda r: 3.0, lambda r: []),
                "thick": (lambda r: 3.0, lambda r: [])}

    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["thin", "thick"])
    _write_memory(tmp_path, {
        "thin": {"applied": 5, "blocked": 0},          # 5/5
        "thick": {"applied": 50, "blocked": 0},         # 50/50, same rate 1.000
    })
    first = [r.objective for r in rank_objectives(str(tmp_path), ["thin", "thick"])]
    second = [r.objective for r in rank_objectives(str(tmp_path), ["thin", "thick"])]
    assert first == ["thick", "thin"]   # more evidence at same rate wins
    assert first == second              # deterministic
