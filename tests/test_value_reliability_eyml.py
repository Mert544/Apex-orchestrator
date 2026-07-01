"""Value-realized reranker — correct the move-value prior by PROVEN outcomes.

``value_reliability.operator_realization_factors`` folds the proof-of-fix history
through ``value_landed``'s never-fake-green bucketer into a per-operator
VALUE-REALIZATION factor (realized-verified / predicted across HELD moves), Wilson
lower-bounded on the held sample count and clamped to the bounded band
``[_REALIZATION_FLOOR, 1.0]``. ``scored_move_value`` folds it as a SUBORDINATE,
neutral-default tiebreak multiplier. These tests pin the whole soundness story:

  * DEMOTE-ONLY — an over-promiser (high predicted, low verified-held realization)
    is dragged DOWN vs its neutral prior;
  * NEVER-INFLATE — a reliably-realized operator's factor is at most 1.0, so its
    scored value never exceeds its static prior (the band ceiling is the point);
  * NEVER off unverified work — a rolled-back / blocked "win" is INVISIBLE (``_held``
    excludes it), so it contributes zero and cannot inflate selection;
  * BYTE-IDENTITY — with no proof history ``scored_move_value`` is byte-identical
    to the pre-change static-table behaviour (a non-tautological witness);
  * the ``_MIN_SAMPLES`` sample gate — below it an operator stays neutral 1.0;
  * recency — the SAME ``_DECAY`` lets a recently-verified family climb back;
  * full DETERMINISM — same proof content → same factors.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.move_value import move_value, scored_move_value
from app.engine.proof_of_fix import SCHEMA
from app.engine.value_reliability import (
    _MIN_SAMPLES,
    _REALIZATION_FLOOR,
    operator_realization_factors,
    realization_factor,
)


# --------------------------------------------------------------------------- #
# helpers — build proof-of-fix records the exact way _fix_record shapes them   #
# --------------------------------------------------------------------------- #
def _rec(operator, outcome="applied", level="function", rolled_back=False,
         target="app/m.py"):
    """One fix record, matching proof_of_fix._fix_record's shape (finding.operator,
    verification.strength.level, rollback.occurred) — the exact fields the
    value_landed bucketer this module reuses reads."""
    return {
        "finding": {"operator": operator, "target": target},
        "outcome": outcome,
        "verification": {"strength": {"level": level}},
        "rollback": {"occurred": rolled_back},
    }


def _write_proof(root: Path, fixes, name="proof-0001.json",
                 generated_at="2026-01-01T00:00:00Z") -> None:
    """Persist a single apex-proof-of-fix artifact under ``<root>/.apex/`` — the
    same store load_proof_history / value_landed read."""
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / name).write_text(
        json.dumps({"schema": SCHEMA, "generated_at": generated_at,
                    "fixes": fixes}), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. demote-only: an over-promiser is dragged DOWN vs its neutral prior        #
# --------------------------------------------------------------------------- #
def test_over_promiser_is_demoted(tmp_path):
    # implement_stub PROMISES 1.00 but every held landing is weak (coverage 'none',
    # green-but-uncovered) — it never realizes the verified value it promised, so
    # its factor drops and scored_move_value is demoted below the static prior.
    _write_proof(tmp_path, [_rec("implement_stub", level="none") for _ in range(8)])
    factors = operator_realization_factors(str(tmp_path))
    prior = move_value("implement_stub")
    scored = scored_move_value("implement_stub", None, factors)
    assert factors["implement_stub"] < 1.0          # the factor demotes
    assert scored < prior                            # scored value is dragged down
    # never below the bounded floor's effect: factor stays in the band.
    assert factors["implement_stub"] >= _REALIZATION_FLOOR


def test_chronic_over_promiser_is_floored_not_erased(tmp_path):
    # A mixed record with a poor verified rate damps toward the floor but NEVER to
    # zero — the operator is heavily demoted, not starved out of selection.
    fixes = ([_rec("harden", level="none") for _ in range(9)]
             + [_rec("harden", level="function")])
    _write_proof(tmp_path, fixes)
    factors = operator_realization_factors(str(tmp_path))
    assert factors["harden"] == _REALIZATION_FLOOR   # damped to the floor
    scored = scored_move_value("harden", None, factors)
    assert 0.0 < scored < move_value("harden")       # demoted but never erased


# --------------------------------------------------------------------------- #
# 2. never-inflate: a reliably-realized operator stays at most neutral         #
# --------------------------------------------------------------------------- #
def test_reliable_operator_never_inflated_above_prior(tmp_path):
    # drop_param realizes every held move as VERIFIED — a perfect realized rate.
    # Its factor is bounded at 1.0, so its scored value NEVER exceeds its prior
    # (the reranker corrects a prior, it never boosts one above the table).
    _write_proof(tmp_path, [_rec("drop_param", level="function") for _ in range(8)])
    factors = operator_realization_factors(str(tmp_path))
    prior = move_value("drop_param")
    scored = scored_move_value("drop_param", None, factors)
    assert factors["drop_param"] <= 1.0              # never above the neutral band ceiling
    assert scored <= prior + 1e-9                    # scored value never exceeds the prior


def test_well_attested_realizer_approaches_neutral(tmp_path):
    # With ample verified evidence the Wilson lower bound climbs toward 1.0, so a
    # well-attested realizer sits ~neutral (correcting nothing) — proven, not lucky.
    _write_proof(tmp_path, [_rec("cover_gaps", level="function") for _ in range(60)])
    factors = operator_realization_factors(str(tmp_path))
    assert factors["cover_gaps"] > 0.9              # ample verified evidence ≈ neutral
    assert factors["cover_gaps"] <= 1.0


# --------------------------------------------------------------------------- #
# 3. never off unverified work: a rolled-back "win" is INVISIBLE               #
# --------------------------------------------------------------------------- #
def test_rolled_back_win_contributes_zero(tmp_path):
    # Nine "verified" landings that ALL rolled back are not held (never-fake-green):
    # zero samples, so the operator is absent → neutral 1.0. Unverified/reverted
    # work can never inflate selection.
    _write_proof(tmp_path,
                 [_rec("harden", outcome="rolled_back", level="function",
                       rolled_back=True) for _ in range(9)])
    factors = operator_realization_factors(str(tmp_path))
    assert "harden" not in factors                   # rolled back → not held → absent
    assert realization_factor("harden", factors) == 1.0
    assert scored_move_value("harden", None, factors) == scored_move_value("harden")


def test_blocked_win_contributes_zero(tmp_path):
    # A blocked move never applied → not held → invisible, so a wall of blocked
    # attempts cannot demote OR inflate the operator (it stays neutral).
    _write_proof(tmp_path,
                 [_rec("extract", outcome="blocked") for _ in range(9)])
    factors = operator_realization_factors(str(tmp_path))
    assert "extract" not in factors


# --------------------------------------------------------------------------- #
# 4. byte-identity: no proof history → scored_move_value is UNCHANGED           #
# --------------------------------------------------------------------------- #
def test_no_proofs_is_byte_identical_to_static_table(tmp_path):
    # A fresh repo (no .apex proofs) yields an EMPTY factor map, so every operator
    # is neutral 1.0 and scored_move_value equals the static move_value — the
    # exact pre-change behaviour. Non-tautological: assert both the empty map AND
    # the equality across a spread of tiers, and that the 3-arg call matches the
    # historical 1-arg call (the byte-identity the wiring promises).
    factors = operator_realization_factors(str(tmp_path))
    assert factors == {}
    for op in ("implement_stub", "drop_param", "sort_imports", "unknown_op_xyz"):
        assert scored_move_value(op, None, factors) == move_value(op)
        assert scored_move_value(op, None, factors) == scored_move_value(op)
        assert scored_move_value(op) == move_value(op)   # the historical contract


def test_none_realization_map_is_neutral():
    # The default (no realization arg) and an explicit None are both neutral, so
    # every existing caller — none passes the arg — is byte-identical.
    for op in ("tdd_implement", "modernize", "raise_from"):
        assert scored_move_value(op, None, None) == move_value(op)
        assert realization_factor(op, None) == 1.0


# --------------------------------------------------------------------------- #
# 5. sample gate: below _MIN_SAMPLES the reranker refuses to move              #
# --------------------------------------------------------------------------- #
def test_below_min_samples_stays_neutral(tmp_path):
    # A single held-but-weak landing (1 sample < _MIN_SAMPLES=2) is not enough
    # evidence to demote: the operator is absent → neutral, so one fluke never
    # moves selection. The next identical landing (2 samples) crosses the gate.
    assert _MIN_SAMPLES == 2
    _write_proof(tmp_path, [_rec("implement_stub", level="none")])
    one = operator_realization_factors(str(tmp_path))
    assert "implement_stub" not in one               # 1 sample: refuses to move
    assert scored_move_value("implement_stub", None, one) == move_value("implement_stub")

    _write_proof(tmp_path, [_rec("implement_stub", level="none") for _ in range(2)])
    two = operator_realization_factors(str(tmp_path))
    assert "implement_stub" in two                   # 2 samples: now it bites
    assert two["implement_stub"] < 1.0


def test_fixes_without_operator_are_skipped(tmp_path):
    # A held record with no finding.operator carries no key to credit and must be
    # dropped (never bucketed under ""), so the map stays clean.
    _write_proof(tmp_path,
                 [_rec("", level="function"), _rec("", level="function")])
    factors = operator_realization_factors(str(tmp_path))
    assert factors == {}
    assert "" not in factors


# --------------------------------------------------------------------------- #
# 6. recency: the SAME _DECAY lets a recently-verified family climb back        #
# --------------------------------------------------------------------------- #
def test_recency_lets_recent_verified_climb(tmp_path):
    # Same operator, same counts, opposite generation order: when the NEWEST proof
    # is the all-verified one it out-scores the world where the newest is all-weak.
    recent = tmp_path / "recent"
    _write_proof(recent, [_rec("extract", level="none") for _ in range(4)],
                 name="a.json", generated_at="2026-01-01T00:00:00Z")
    _write_proof(recent, [_rec("extract", level="function") for _ in range(4)],
                 name="b.json", generated_at="2026-06-01T00:00:00Z")

    stale = tmp_path / "stale"
    _write_proof(stale, [_rec("extract", level="function") for _ in range(4)],
                 name="a.json", generated_at="2026-01-01T00:00:00Z")
    _write_proof(stale, [_rec("extract", level="none") for _ in range(4)],
                 name="b.json", generated_at="2026-06-01T00:00:00Z")

    f_recent = operator_realization_factors(str(recent))
    f_stale = operator_realization_factors(str(stale))
    assert f_recent["extract"] > f_stale["extract"]  # recent-verified climbs above recent-weak


# --------------------------------------------------------------------------- #
# 7. determinism: same proof content → same factors                            #
# --------------------------------------------------------------------------- #
def test_deterministic_same_history_same_factors(tmp_path):
    fixes = ([_rec("drop_param", level="function") for _ in range(3)]
             + [_rec("drop_param", level="none") for _ in range(2)]
             + [_rec("implement_stub", level="function") for _ in range(4)])
    one = tmp_path / "one"
    two = tmp_path / "two"
    _write_proof(one, fixes)
    _write_proof(two, fixes)
    assert operator_realization_factors(str(one)) \
        == operator_realization_factors(str(two))
    # And stable across repeated reads of the same tree.
    assert operator_realization_factors(str(one)) \
        == operator_realization_factors(str(one))


def test_empty_and_missing_history_are_neutral(tmp_path):
    # No .apex at all → {}; an empty fixes list → {}; both leave every operator
    # neutral. Never raises on the empty/absent edge.
    assert operator_realization_factors(str(tmp_path)) == {}
    _write_proof(tmp_path, [])
    assert operator_realization_factors(str(tmp_path)) == {}
