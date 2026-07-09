"""4th sense organ fused into the risk brain — native-lane landing EXPERIENCE.

``app/engine/fix_risk_model.py`` already fuses three read-only signals
(reliability, track record, counterfactual avoid) into a forward-looking
rollback risk. This pins the 4th signal: the native synthesis lane's
recency-weighted landing confidence (``native_proof_memory.decayed_reliability``),
re-normalized into the existing weighted average.

The critical property under test is the BYTE-IDENTICAL guarantee: with no
native experience recorded, ``fix_risk`` must return EXACTLY what it returned
before this signal existed, for every action type and module — the new
weight only ever joins the average when there is real evidence to use, and
the gate is on the ACTION TYPE (only the native lane's own mechanism,
``implement_stub``), not merely on whether some unrelated native experience
happens to exist in the project.

Fixtures write a fake proof-of-fix JSON (matching
``tests/test_fix_risk_model_eyml.py``'s house style) and a fake
``.apex/native-mind-experience.json`` (matching
``tests/test_native_proof_memory_eyml.py``'s house style, via
``record_native_landing``) to the real on-disk locations the loaders read.
All assertions are deterministic (no time/random; exact equality on rounded
floats).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.fix_risk_model import (
    _W_AVOID,
    _W_AVOID_NO_EXPERIENCE,
    _W_EXPERIENCE,
    _W_RELIABILITY,
    _W_RELIABILITY_NO_EXPERIENCE,
    _W_TRACK,
    _W_TRACK_NO_EXPERIENCE,
    fix_risk,
)
from app.engine.native_proof_memory import record_native_landing
from app.engine.proof_of_fix import SCHEMA


def _proof(fixes: list[dict]) -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": "2026-01-01T00:00:00+00:00", "fixes": fixes}


def _write_proof(root: Path, fixes: list[dict]) -> None:
    apex_dir = root / ".apex"
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / "p.json").write_text(json.dumps(_proof(fixes)), encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


# --- (d) weights sum to 1.0 ---------------------------------------------------


def test_weights_sum_to_one_in_both_modes():
    """Both the experience-active and the fallback weight sets sum to 1.0, so
    a weighted average always stays inside [0, 1] regardless of which set the
    fusion picks."""
    assert round(_W_RELIABILITY + _W_TRACK + _W_AVOID + _W_EXPERIENCE, 10) == 1.0
    assert round(
        _W_RELIABILITY_NO_EXPERIENCE + _W_TRACK_NO_EXPERIENCE
        + _W_AVOID_NO_EXPERIENCE, 10
    ) == 1.0
    # reliability stays dominant in the 4-signal blend too
    assert _W_RELIABILITY > _W_TRACK
    assert _W_RELIABILITY > _W_AVOID
    assert _W_RELIABILITY > _W_EXPERIENCE


# --- (a) byte-identical when no native experience -----------------------------


def test_empty_project_scores_the_historical_baseline_across_action_types(
    tmp_path: Path,
):
    """No proof history and no native experience at all: every action type and
    module still scores the exact neutral baseline 0.5, for a NATIVE-relevant
    action type ('implement_stub') just as much as an ordinary one."""
    for action, module in [
        ("rename_symbol", "app/m.py"),
        ("harden_security", "app/sec.py"),
        ("implement_stub", "app/stub.py"),
        ("implement-stub", "app/other.py"),
    ]:
        assert fix_risk(tmp_path, action, module) == 0.5


def test_proof_history_score_is_unchanged_with_no_native_experience(
    tmp_path: Path,
):
    """A proof history that would move reliability/track/avoid away from
    baseline scores EXACTLY the pre-existing 3-weight arithmetic (0.45/0.25/
    0.30) when there is no native experience recorded — even for the
    native-relevant action type itself, whose experience term must abstain
    (not silently apply the new 4-weight blend with a baseline placeholder,
    which would shift the number)."""
    fixes = [_fix("act", "app/m.py", "applied") for _ in range(3)]
    _write_proof(tmp_path, fixes)
    # ordinary action: reliability=1.0->0, track=1.0->0, avoid abstains->0.5
    # raw = 0.45*0 + 0.25*0 + 0.30*0.5 = 0.15 (pins the historical weights)
    assert fix_risk(tmp_path, "act", "app/m.py") == 0.15

    native_fixes = [_fix("implement_stub", "app/stub.py", "applied") for _ in range(3)]
    _write_proof(tmp_path, native_fixes)
    # SAME arithmetic for the native-relevant action type: with zero recorded
    # native experience the gate must not activate, so this is also 0.15 —
    # NOT 0.19 (which is what 0.40/0.22/0.26/0.12 with a 0.5 placeholder
    # would give: 0.40*0 + 0.22*0 + 0.26*0.5 + 0.12*0.5 = 0.19).
    assert fix_risk(tmp_path, "implement_stub", "app/stub.py") == 0.15


def test_mixed_history_scores_are_byte_identical_regardless_of_action(
    tmp_path: Path,
):
    """A richer mixed history (some applied, some rolled back) still resolves
    to the plain historical formula for several distinct (action, module)
    pairs when no native experience exists — a broad regression pin, not just
    a single lucky case."""
    fixes = (
        [_fix("safe", "app/s.py", "applied") for _ in range(3)]
        + [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    )
    _write_proof(tmp_path, fixes)
    assert fix_risk(tmp_path, "safe", "app/s.py") == 0.15
    assert fix_risk(tmp_path, "risky", "a/b/c/test_x.py") == 1.0
    assert fix_risk(tmp_path, "unseen", "app/elsewhere.py") == 0.5


# --- (b) strong native experience LOWERS risk for a native-relevant action ---


def test_strong_native_experience_lowers_risk_for_implement_stub(tmp_path: Path):
    """A single, freshly recorded native landing gives that shape a decayed
    reliability of exactly 1.0 (one generation, full weight) -> native
    confidence 1.0 -> the experience term contributes 0 risk. With no other
    proof history (everything else at baseline), the fused score must be
    STRICTLY LOWER than the same call before any native experience existed."""
    risk_without = fix_risk(tmp_path, "implement_stub", "app/work.py")
    assert risk_without == 0.5

    record_native_landing(tmp_path, ["3:max(p1, min(p0, p2))"])
    risk_with = fix_risk(tmp_path, "implement_stub", "app/work.py")

    assert risk_with < risk_without
    # pins the exact arithmetic: 0.40*0.5 + 0.22*0.5 + 0.26*0.5 + 0.12*0.0
    assert risk_with == 0.44


def test_strong_native_experience_lowers_risk_for_hyphenated_spelling(
    tmp_path: Path,
):
    """The develop-loop's ``Move.operator`` spells this objective with a
    hyphen ('implement-stub'); the gate must recognize it exactly like the
    underscored action-type spelling."""
    record_native_landing(tmp_path, ["2:p0 + p1"])
    assert fix_risk(tmp_path, "implement-stub", "app/work.py") == 0.44


# --- (c) native experience does NOT move risk for a non-native action -------


def test_native_experience_does_not_move_risk_for_unrelated_action(tmp_path: Path):
    """Strong native experience recorded, but the action type in question
    ('rename_symbol') is not one the native lane drives: the risk must be
    IDENTICAL to a project with no native experience at all."""
    risk_without = fix_risk(tmp_path, "rename_symbol", "app/m.py")
    record_native_landing(tmp_path, ["3:max(p1, min(p0, p2))"])
    risk_with = fix_risk(tmp_path, "rename_symbol", "app/m.py")
    assert risk_with == risk_without == 0.5


def test_native_experience_does_not_move_risk_with_real_proof_history(
    tmp_path: Path,
):
    """Same non-native-action invariance, but against a REAL, non-baseline
    proof-of-fix history, so the equality isn't just two baseline 0.5s."""
    fixes = [_fix("harden_security", "app/sec.py", "applied") for _ in range(3)]
    _write_proof(tmp_path, fixes)
    risk_without = fix_risk(tmp_path, "harden_security", "app/sec.py")
    assert risk_without == 0.15

    record_native_landing(tmp_path, ["3:max(p1, min(p0, p2))"])
    risk_with = fix_risk(tmp_path, "harden_security", "app/sec.py")
    assert risk_with == risk_without == 0.15


# --- tolerance: a corrupt experience store never raises and abstains --------


def test_corrupt_native_experience_store_abstains_to_baseline(tmp_path: Path):
    """A malformed ``.apex/native-mind-experience.json`` must not crash
    ``fix_risk`` — the loader tolerates it and the experience term abstains,
    falling back to the historical weights."""
    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / "native-mind-experience.json").write_text("{ not json")
    assert fix_risk(tmp_path, "implement_stub", "app/work.py") == 0.5
