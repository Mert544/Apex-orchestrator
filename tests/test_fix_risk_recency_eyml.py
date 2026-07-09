"""Recency-decayed module fragility + the ``explain_fix_risk`` breakdown.

``app/engine/fix_risk_model.py`` already fuses reliability, track-record,
counterfactual-avoid, and native-experience signals into a single risk score.
This pins TWO additions on top of that:

1. The track-record signal can swap its flat, equal-weight module ratio for a
   RANK-DECAYED one (``recency=True``) — the same ``0.85``-family geometric
   forgetting ``learned_reliability_decayed`` already applies to actions,
   reused read-only from ``proof_history``, so a module that USED to roll
   back a lot but has landed cleanly in recent generations is no longer
   punished forever.
2. ``explain_fix_risk``/``render_fix_risk_explanation`` expose a deterministic
   per-signal breakdown of exactly how a score was reached.

Fixtures write fake proof-of-fix JSON to the real on-disk location the loader
reads (``<root>/.apex/*.json`` with ``schema == SCHEMA``), matching the house
style of ``tests/test_fix_risk_model_eyml.py``. All assertions are
deterministic (no time/random; exact/tolerance equality on rounded floats).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.fix_risk_model import (
    _module_fragility_decayed,
    explain_fix_risk,
    fix_risk,
    rank_fix_risks,
    render_fix_risk_explanation,
)
from app.engine.proof_of_fix import SCHEMA


def _proof(fixes: list[dict], generated_at: str) -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": fixes}


def _write(apex_dir: Path, name: str, proof: dict) -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


# --- (1) the decay pin: recent-clean beats stale-fragile with equal totals --


def test_module_fragility_decay_favors_recent_clean(tmp_path: Path):
    """Two modules, IDENTICAL totals (3 rolled_back / 2 applied each), but
    different chronological placement: 'stale' module's rollbacks are OLDEST
    (it has since landed clean), 'fresh' module's rollbacks are NEWEST (it
    just started failing). Rank-decayed risk must score 'stale' LOWER than
    'fresh' even though the flat equal-weight ratio is identical for both —
    this is red on pre-change equal-weight code (both would tie at the same
    ratio)."""
    apex_dir = tmp_path / ".apex"
    # 'stale' module: rollbacks in the oldest 3 generations, applied in the
    # newest 2 — i.e. it USED to be fragile but has recently landed clean.
    for i in range(3):
        _write(apex_dir, f"stale-{i}.json",
               _proof([_fix("act", "app/stale.py", "rolled_back")],
                      generated_at=f"2026-01-0{i + 1}T00:00:00+00:00"))
    for i in range(2):
        _write(apex_dir, f"stale-ok-{i}.json",
               _proof([_fix("act", "app/stale.py", "applied")],
                      generated_at=f"2026-01-0{i + 4}T00:00:00+00:00"))
    # 'fresh' module: applied in the oldest 2 generations, rollbacks in the
    # newest 3 — i.e. it just started rolling back.
    for i in range(2):
        _write(apex_dir, f"fresh-ok-{i}.json",
               _proof([_fix("act", "app/fresh.py", "applied")],
                      generated_at=f"2026-01-0{i + 1}T01:00:00+00:00"))
    for i in range(3):
        _write(apex_dir, f"fresh-{i}.json",
               _proof([_fix("act", "app/fresh.py", "rolled_back")],
                      generated_at=f"2026-01-0{i + 3}T01:00:00+00:00"))

    stale_risk = fix_risk(tmp_path, "act", "app/stale.py", recency=True)
    fresh_risk = fix_risk(tmp_path, "act", "app/fresh.py", recency=True)
    assert stale_risk < fresh_risk

    # And the flat (recency=False) view scores them IDENTICALLY, proving the
    # totals really are equal and the decay is what moves the needle.
    assert fix_risk(tmp_path, "act", "app/stale.py", recency=False) == fix_risk(
        tmp_path, "act", "app/fresh.py", recency=False
    )


# --- (2) empty history is byte-identical, decayed or not --------------------


def test_module_fragility_decay_empty_history_neutral(tmp_path: Path):
    """No proof history at all: ``_module_fragility_decayed`` is exactly
    ``{}``, and ``rank_fix_risks`` with ``recency=True`` is byte-identical to
    ``recency=False`` — no evidence means no divergence, ever."""
    assert _module_fragility_decayed([]) == {}

    candidates = [("act", "app/a.py"), ("act", "app/b.py"), ("other", "app/c.py")]
    flat = rank_fix_risks(tmp_path, candidates, recency=False)
    decayed = rank_fix_risks(tmp_path, candidates, recency=True)
    assert flat == decayed


def test_rank_fix_risks_stable_sort_neutrality_pin(tmp_path: Path):
    """Same candidate list, empty history: ``recency=True`` vs ``False`` must
    produce the IDENTICAL list — order and every value — pinning the
    "no evidence -> identical" contract even with a richer candidate set."""
    candidates = [
        ("z_action", "z/module.py"),
        ("a_action", "a/module.py"),
        ("m_action", "m/module.py"),
    ]
    assert rank_fix_risks(tmp_path, candidates, recency=False) == rank_fix_risks(
        tmp_path, candidates, recency=True
    )


# --- (3) corrupt store degrades to neutral, never raises --------------------


def test_module_fragility_decayed_corrupt_store_neutral(tmp_path: Path):
    """A malformed proof JSON under ``.apex/`` must not blow up either the
    raw reducer or ``fix_risk(recency=True)`` — the existing loader already
    skips unreadable files, so both degrade to empty/neutral."""
    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / "corrupt.json").write_text("{ not json at all", encoding="utf-8")

    from app.engine.proof_history import load_proof_history

    history = load_proof_history(tmp_path)
    assert _module_fragility_decayed(history) == {}
    assert fix_risk(tmp_path, "act", "app/m.py", recency=True) == 0.5


# --- (4) explain_fix_risk: active signals match the returned score ----------


def test_explain_fix_risk_active_signals_match_score(tmp_path: Path):
    """A crafted history where reliability and track-record both carry real
    evidence (all-applied, so both push risk DOWN) but no avoid lesson fires
    and no native experience exists: the signals list must mark EXACTLY
    'reliability' and 'track_record' as active, and summing every signal's
    weighted contribution must reconstruct the returned risk."""
    fixes = [_fix("act", "app/m.py", "applied") for _ in range(3)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes, "2026-01-01T00:00:00+00:00"))

    info = explain_fix_risk("act", "app/m.py", tmp_path, recency=False)
    active_names = {s["name"] for s in info["signals"] if s["active"]}
    assert active_names == {"reliability", "track_record"}

    total = sum(s["contribution"] for s in info["signals"])
    assert abs(round(total, 4) - info["risk"]) < 0.001
    assert info["risk"] == fix_risk(tmp_path, "act", "app/m.py", recency=False)


def test_explain_fix_risk_avoid_signal_active(tmp_path: Path):
    """A should_avoid-triggering history marks 'counterfactual_avoid' active
    alongside reliability/track_record, and the reconstruction still holds."""
    fixes = [_fix("risky", "a/b/c/test_x.py", "rolled_back") for _ in range(4)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes, "2026-01-01T00:00:00+00:00"))

    info = explain_fix_risk("risky", "a/b/c/test_x.py", tmp_path, recency=False)
    active_names = {s["name"] for s in info["signals"] if s["active"]}
    assert active_names == {"reliability", "track_record", "counterfactual_avoid"}
    total = sum(s["contribution"] for s in info["signals"])
    assert abs(round(total, 4) - info["risk"]) < 0.001
    assert info["risk"] == 1.0


# --- (5) honest-empty wording -------------------------------------------------


def test_explain_fix_risk_honest_empty(tmp_path: Path):
    """No ``.apex`` dir at all: every signal abstains (``active is False``),
    the fused risk is exactly the neutral baseline, and the recorded fix
    count is zero (the honest-empty signal a renderer keys off of)."""
    info = explain_fix_risk("act", "app/m.py", tmp_path)
    assert info["fixes"] == 0
    assert info["risk"] == 0.5
    assert all(not s["active"] for s in info["signals"])


def test_render_fix_risk_explanation_honest_empty_text(tmp_path: Path):
    """The Markdown formatter states plainly that there is no proof history
    when there is none — never a table of abstained signals dressed up as
    evidence."""
    text = render_fix_risk_explanation("act", "app/m.py", tmp_path)
    assert "No proof history" in text
    assert "Risk: 0.5" in text


def test_render_fix_risk_explanation_populated_is_deterministic(tmp_path: Path):
    """Same proof files -> byte-identical explanation Markdown across calls,
    and it carries every signal name plus the formula line."""
    fixes = [_fix("act", "app/m.py", "applied") for _ in range(3)]
    _write(tmp_path / ".apex", "p.json", _proof(fixes, "2026-01-01T00:00:00+00:00"))

    first = render_fix_risk_explanation("act", "app/m.py", tmp_path)
    second = render_fix_risk_explanation("act", "app/m.py", tmp_path)
    assert first == second
    assert "reliability" in first
    assert "track_record" in first
    assert "Formula: risk =" in first
