"""Deterministic, mutation-resistant characterization for the fix-risk model.

``app/engine/fix_risk_model.py`` fuses the recorded proof history into a
forward-looking rollback risk in ``[0, 1]`` for a proposed ``(action_type,
module)`` fix. These tests pin the EXACT arithmetic, the neutral baseline, the
clamp boundaries, the deterministic ranking order, and the markdown substrings,
so a surviving mutant cannot silently shift a score.

Fixtures write a fake proof-of-fix JSON to the real on-disk location the loader
reads (``<root>/.apex/*.json`` with ``schema == SCHEMA``), matching the house
style of ``tests/test_proof_history_deep_mutation_eyml.py``. All assertions are
deterministic (no time/random; exact equality on rounded floats and sorted
keys).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.fix_risk_model import (
    fix_risk,
    fix_risk_report,
    rank_fix_risks,
    render_fix_risk_markdown,
)
from app.engine.proof_of_fix import SCHEMA


def _proof(fixes: list[dict], generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": fixes}


def _write(apex_dir: Path, name: str, proof: dict) -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


# --- neutral baseline --------------------------------------------------------


def test_empty_history_scores_exact_neutral_baseline(tmp_path: Path):
    """No ``.apex`` dir at all → every signal abstains → risk is exactly 0.5.

    This pins the documented neutral baseline: with zero evidence a proposed fix
    is neither safe nor risky."""
    assert fix_risk(tmp_path, "rename_symbol", "app/m.py") == 0.5


def test_present_but_empty_proof_still_baseline(tmp_path: Path):
    """A readable proof with no fixes is still no evidence → baseline 0.5."""
    _write(tmp_path / ".apex", "p.json", _proof([]))
    assert fix_risk(tmp_path, "act", "app/m.py") == 0.5


def test_unseen_action_and_module_abstain_to_baseline(tmp_path: Path):
    """A history that records OTHER actions/modules must not punish an unseen
    candidate: reliability and track-record both abstain, no avoid lesson fires,
    so the score is exactly the baseline 0.5."""
    fixes = [_fix("known", "app/known.py", "applied")]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "brand_new", "app/elsewhere.py") == 0.5


# --- reliable history => low risk (exact arithmetic) -------------------------


def test_all_applied_history_scores_exact_low_risk(tmp_path: Path):
    """3 applied fixes for (act, app/m.py): reliability=1.0 → reliability_risk 0,
    track ratio=1.0 → track_risk 0, no avoid → avoid_risk 0.5. Score is
    0.45*0 + 0.25*0 + 0.30*0.5 = 0.15 exactly. Pins all three weights."""
    fixes = [_fix("act", "app/m.py", "applied") for _ in range(3)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "act", "app/m.py") == 0.15


def test_half_reliable_history_scores_exact_midrisk(tmp_path: Path):
    """2 applied + 2 blocked for (act, app/m.py): reliability=0.5 →
    reliability_risk 0.5, track ratio 0.5 → track_risk 0.5, no avoid → 0.5.
    Score = 0.45*0.5 + 0.25*0.5 + 0.30*0.5 = 0.5 exactly (weights sum to 1)."""
    fixes = (
        [_fix("act", "app/m.py", "applied") for _ in range(2)]
        + [_fix("act", "app/m.py", "blocked") for _ in range(2)]
    )
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "act", "app/m.py") == 0.5


# --- should_avoid hit => clamped high risk -----------------------------------


def test_should_avoid_hit_scores_exact_one(tmp_path: Path):
    """4 rolled_back fixes of action 'risky' on a deep test module: reliability=0
    → reliability_risk 1.0, track ratio 0 → track_risk 1.0, AND the
    counterfactual avoid-guard fires (rate 1.0 >= 0.6, attempts 4 >= 3) →
    avoid_risk 1.0. Score = 0.45+0.25+0.30 = 1.0 (the clamp upper bound)."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "risky", "a/b/c/test_x.py") == 1.0


def test_avoid_guard_keys_on_action_so_unseen_action_abstains(tmp_path: Path):
    """The avoid-guard keys on the ACTION too: an unseen action on a deep test
    module does NOT inherit 'risky's avoid verdict (no 'fresh_act | test'
    signature exists), and an unseen action abstains on reliability and track,
    so the score is the neutral baseline 0.5 even on the same risky traits."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "fresh_act", "p/q/r/test_y.py") == 0.5


# --- clamp boundaries --------------------------------------------------------


def test_risk_never_exceeds_one(tmp_path: Path):
    """Worst case stays at the 1.0 upper clamp, never above."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(5)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert fix_risk(tmp_path, "risky", "a/b/c/test_x.py") == 1.0


def test_risk_stays_within_unit_interval_for_all_candidates(tmp_path: Path):
    """Every scored candidate's risk is bounded to [0, 1] (lower and upper)."""
    fixes = (
        [_fix("good", "app/g.py", "applied") for _ in range(3)]
        + [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    )
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    ranked = rank_fix_risks(
        tmp_path,
        [("good", "app/g.py"), ("risky", "a/b/c/test_x.py"), ("x", "y")],
    )
    for row in ranked:
        assert 0.0 <= row["risk"] <= 1.0


# --- ranking order -----------------------------------------------------------


def test_rank_orders_riskiest_first_then_by_key(tmp_path: Path):
    """Ranking is descending risk, then (action_type, module) for ties. The
    risky/avoid candidate (1.0) leads; the two unseen baseline candidates (0.5)
    tie and break by key, so 'a'/'m1' precedes 'b'/'m2'."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    ranked = rank_fix_risks(
        tmp_path,
        [("b", "m2"), ("risky", "a/b/c/test_x.py"), ("a", "m1")],
    )
    keys = [(r["action_type"], r["module"]) for r in ranked]
    assert keys == [
        ("risky", "a/b/c/test_x.py"),
        ("a", "m1"),
        ("b", "m2"),
    ]
    assert ranked[0]["risk"] == 1.0
    assert ranked[1]["risk"] == ranked[2]["risk"] == 0.5


def test_rank_empty_candidates_is_empty(tmp_path: Path):
    """No candidates → empty ranking, never raises."""
    assert rank_fix_risks(tmp_path, []) == []


def test_rank_evidence_lists_which_signals_fired(tmp_path: Path):
    """The riskiest entry names all three signals; a baseline entry names none.
    Evidence is sorted so the order is deterministic."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    ranked = rank_fix_risks(
        tmp_path, [("risky", "a/b/c/test_x.py"), ("unseen", "app/u.py")]
    )
    top = ranked[0]
    assert top["evidence"] == [
        "counterfactual_avoid",
        "reliability",
        "track_record",
    ]
    bottom = ranked[-1]
    assert bottom["evidence"] == []


# --- report ------------------------------------------------------------------


def test_report_empty_history_is_zeroed_and_neutral(tmp_path: Path):
    """Missing history → zero counts, empty lists, 0.0 overall reliability."""
    report = fix_risk_report(tmp_path)
    assert report["proofs"] == 0
    assert report["fixes"] == 0
    assert report["overall_reliability"] == 0.0
    assert report["riskiest_actions"] == []
    assert report["riskiest_modules"] == []
    assert report["avoid_signatures"] == []


def test_report_surfaces_riskiest_and_avoid_signatures(tmp_path: Path):
    """A mixed history: 'risky' all-failed (reliability 0 → risk 1.0) outranks
    'safe' all-applied (reliability 1.0 → risk 0.0); the avoid signatures for
    the deep test module are listed sorted."""
    fixes = (
        [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
        + [_fix("safe", "app/s.py", "applied") for _ in range(3)]
    )
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    report = fix_risk_report(tmp_path)
    assert report["proofs"] == 1
    assert report["fixes"] == 7
    assert report["riskiest_actions"][0] == {"action_type": "risky", "risk": 1.0}
    assert {"action_type": "safe", "risk": 0.0} in report["riskiest_actions"]
    assert report["riskiest_modules"][0]["module"] == "a/b/c/test_x.py"
    assert report["riskiest_modules"][0]["risk"] == 1.0
    assert report["avoid_signatures"] == sorted(report["avoid_signatures"])
    assert "risky | deep" in report["avoid_signatures"]
    assert "risky | test" in report["avoid_signatures"]
    assert report["rolled_back"] == 4


# --- markdown ----------------------------------------------------------------


def test_markdown_empty_history_notes_baseline(tmp_path: Path):
    """Empty history markdown explicitly states the neutral baseline."""
    md = render_fix_risk_markdown(tmp_path)
    assert md.startswith("# Fix-Risk Model")
    assert "No proof history" in md
    assert "0.5" in md


def test_markdown_contains_exact_sections_and_values(tmp_path: Path):
    """Populated markdown carries the headers and the exact scored lines."""
    fixes = (
        [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
        + [_fix("safe", "app/s.py", "applied") for _ in range(3)]
    )
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    md = render_fix_risk_markdown(tmp_path)
    assert "# Fix-Risk Model" in md
    assert "## Riskiest action types" in md
    assert "## Riskiest modules" in md
    assert "## Counterfactual avoid signatures" in md
    assert "- risky: risk 1.0" in md
    assert "- safe: risk 0.0" in md
    assert "- a/b/c/test_x.py: risk 1.0" in md
    assert "- risky | test" in md
    assert "overall reliability:" in md
    assert md.endswith("\n")


def test_markdown_is_deterministic(tmp_path: Path):
    """Same proof files → byte-identical markdown across calls."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes))
    assert render_fix_risk_markdown(tmp_path) == render_fix_risk_markdown(tmp_path)
