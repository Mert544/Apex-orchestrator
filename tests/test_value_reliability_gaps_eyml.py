"""Gap-closing tests for value_reliability.realization_factor's NON-EMPTY map path.

The existing suite (test_value_reliability_eyml.py) exercises ``realization_factor``
only with an EMPTY / ``None`` map (the ``not factors`` early return). This wave adds
the complementary path: a populated ``factors`` map, where a TRACKED operator gets
its computed (possibly demoted) factor and an UNTRACKED operator falls back to the
neutral ``1.0`` — the ``factors.get(operator, 1.0)`` lookup line.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_of_fix import SCHEMA
from app.engine.value_reliability import (
    _REALIZATION_FLOOR,
    operator_realization_factors,
    realization_factor,
)


def _rec(operator, level="none"):
    return {
        "finding": {"operator": operator, "target": "app/m.py"},
        "outcome": "applied",
        "verification": {"strength": {"level": level}},
        "rollback": {"occurred": False},
    }


def _write_proof(root: Path, fixes) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-0001.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01T00:00:00Z",
                    "fixes": fixes}), encoding="utf-8")


def test_realization_factor_returns_tracked_factor_from_map(tmp_path):
    # A populated map: a tracked, demoted operator returns ITS computed factor
    # (not the neutral default) — the non-empty-map lookup branch.
    _write_proof(tmp_path, [_rec("implement_stub") for _ in range(3)])
    factors = operator_realization_factors(str(tmp_path))
    assert "implement_stub" in factors
    got = realization_factor("implement_stub", factors)
    assert got == factors["implement_stub"]
    assert _REALIZATION_FLOOR <= got < 1.0


def test_realization_factor_untracked_operator_falls_back_neutral(tmp_path):
    # A populated map but an operator that is NOT a key: the lookup default is the
    # neutral 1.0, so an untracked operator is never accidentally demoted.
    _write_proof(tmp_path, [_rec("implement_stub") for _ in range(3)])
    factors = operator_realization_factors(str(tmp_path))
    assert factors  # non-empty map (so we exercise the get(...) path, not the guard)
    assert realization_factor("never_recorded_op", factors) == 1.0


def test_realization_factor_deterministic_lookup(tmp_path):
    _write_proof(tmp_path, [_rec("implement_stub") for _ in range(3)])
    factors = operator_realization_factors(str(tmp_path))
    first = realization_factor("implement_stub", factors)
    for _ in range(5):
        assert realization_factor("implement_stub", factors) == first
