"""Deep-mutation characterization for proof-of-fix history learning.

These tests pin down behaviours that the existing proof-history suite left
exposed to surviving AST mutants (past the 30-mutant cap). Each test below
targets a specific surviving mutation in ``app/engine/proof_history.py`` so the
behaviour it documents can no longer silently change:

* ``_module_of`` truthy-``finding`` coalesce (``fix.get("finding") or {}``) and
  the ``isinstance(changed, list) and changed`` guard, and its ``_UNKNOWN``
  fallback return.
* the schema/outcome classification and the reliability-ratio math.

All assertions are deterministic (no time/random; sorted/keyed comparisons).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_history import (
    learned_reliability,
    load_proof_history,
    summarise_fix_track_record,
)
from app.engine.proof_of_fix import SCHEMA


def _proof(fixes: list[dict], generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": fixes}


def _write(apex_dir: Path, name: str, proof: dict) -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


# --- _module_of: truthy finding is preserved (kills L105 `or`->`and`) -------


def test_module_uses_target_from_a_real_finding(tmp_path: Path):
    """A fix whose ``finding`` is a truthy dict with a real ``target`` and NO
    ``changed_files`` must bucket under that target. The ``fix.get("finding")
    or {}`` coalesce must keep the real finding: an ``and`` there would replace
    a truthy finding with ``{}``, dropping the target and (with no changed
    files) collapsing the module to the ``<unknown>`` placeholder."""
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "x", "target": "app/real_target.py"},
           "outcome": "applied"}  # no changed_files key at all
    _write(apex, "p.json", _proof([fix]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert "app/real_target.py" in summary["by_module"]
    assert "<unknown>" not in summary["by_module"]
    assert summary["by_module"]["app/real_target.py"]["applied"] == 1


# --- _module_of: changed_files guard (kills L110 `and`->`or`) ----------------


def test_empty_changed_files_falls_through_to_unknown(tmp_path: Path):
    """With no target and an *empty* ``changed_files`` list the module must be
    the ``<unknown>`` placeholder. The ``isinstance(changed, list) and changed``
    guard must require a non-empty list: an ``or`` there would treat an empty
    list as indexable and raise ``IndexError`` on ``changed[0]``."""
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "y", "target": ""}, "outcome": "applied",
           "changed_files": []}
    _write(apex, "p.json", _proof([fix]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert "<unknown>" in summary["by_module"]
    assert summary["by_module"]["<unknown>"]["applied"] == 1


def test_non_list_changed_files_falls_through_to_unknown(tmp_path: Path):
    """A non-list (truthy) ``changed_files`` must NOT be indexed — the
    ``isinstance(...) and ...`` guard rejects it and the module is
    ``<unknown>``. (An ``or`` mutant would short-circuit on the truthy value
    and try ``changed[0]``, here a string subscript, changing the bucket.)"""
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "z", "target": ""}, "outcome": "blocked",
           "changed_files": "app/not_a_list.py"}
    _write(apex, "p.json", _proof([fix]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert "<unknown>" in summary["by_module"]
    # The string was not indexed into a per-char or whole-string key.
    assert "app/not_a_list.py" not in summary["by_module"]
    assert summary["by_module"]["<unknown>"]["blocked"] == 1


# --- _module_of: the placeholder return (kills L112 return _UNKNOWN->None) ---


def test_module_placeholder_is_unknown_string_not_none(tmp_path: Path):
    """When neither target nor changed_files yields a module, the bucket key is
    the literal ``"<unknown>"`` string — not ``None``. A ``None`` key would be
    a different, falsy bucket (and break the sorted-key emission contract)."""
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "w", "target": ""}, "outcome": "rolled_back"}
    _write(apex, "p.json", _proof([fix]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    keys = list(summary["by_module"])
    assert keys == ["<unknown>"]
    assert None not in summary["by_module"]
    assert summary["by_module"]["<unknown>"]["rolled_back"] == 1


# --- reliability-ratio math: denominator counts every outcome ----------------


def test_reliability_denominator_counts_all_three_outcomes(tmp_path: Path):
    """The reliability ratio is ``applied / (applied + rolled_back + blocked)``.
    With 1 applied + 1 rolled_back + 2 blocked the denominator must be all 4
    decided outcomes -> 0.25, exactly. This pins the ratio so a mutated
    denominator (dropping or mis-weighting an outcome) is caught."""
    apex = tmp_path / ".apex"
    fixes = [
        {"finding": {"action": "act", "target": "app/m.py"}, "outcome": "applied"},
        {"finding": {"action": "act", "target": "app/m.py"}, "outcome": "rolled_back"},
        {"finding": {"action": "act", "target": "app/m.py"}, "outcome": "blocked"},
        {"finding": {"action": "act", "target": "app/m.py"}, "outcome": "blocked"},
    ]
    _write(apex, "p.json", _proof(fixes))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    stats = summary["by_action"]["act"]
    assert stats["applied"] == 1
    assert stats["rolled_back"] == 1
    assert stats["blocked"] == 2
    assert stats["total"] == 4
    assert stats["reliability"] == 0.25
    assert summary["totals"]["reliability"] == 0.25


def test_reliability_is_exactly_one_when_all_applied(tmp_path: Path):
    """All-applied -> reliability 1.0 (upper bound). Distinguishes the math
    from any constant or off-by-one denominator perturbation."""
    apex = tmp_path / ".apex"
    fixes = [{"finding": {"action": "a", "target": "app/m.py"}, "outcome": "applied"}
             for _ in range(3)]
    _write(apex, "p.json", _proof(fixes))
    rel = learned_reliability(load_proof_history(tmp_path))
    assert rel == {"a": 1.0}


def test_reliability_rounds_to_four_places(tmp_path: Path):
    """1 applied of 3 decided -> 0.3333 (rounded to 4dp). Pins both the
    rounding and the exact denominator (3, not 4)."""
    apex = tmp_path / ".apex"
    fixes = [
        {"finding": {"action": "r", "target": "app/m.py"}, "outcome": "applied"},
        {"finding": {"action": "r", "target": "app/m.py"}, "outcome": "rolled_back"},
        {"finding": {"action": "r", "target": "app/m.py"}, "outcome": "blocked"},
    ]
    _write(apex, "p.json", _proof(fixes))
    rel = learned_reliability(load_proof_history(tmp_path))
    assert rel == {"r": round(1 / 3, 4)}
    assert rel == {"r": 0.3333}


def test_reliability_zero_total_is_neutral_zero(tmp_path: Path):
    """No decided outcomes -> neutral 0.0, never a division error. An empty
    history produces empty breakdowns and a 0.0 totals reliability."""
    summary = summarise_fix_track_record([])
    assert summary["totals"]["reliability"] == 0.0
    assert summary["fixes"] == 0
    assert summary["by_action"] == {}


# --- schema / outcome classification ----------------------------------------


def test_wrong_schema_proof_is_skipped_entirely(tmp_path: Path):
    """Only proofs whose ``schema`` equals the canonical SCHEMA constant are
    loaded; a near-miss schema string is dropped, contributing zero fixes."""
    apex = tmp_path / ".apex"
    good = _proof([{"finding": {"action": "g", "target": "app/m.py"},
                    "outcome": "applied"}])
    bad = json.loads(json.dumps(good))
    bad["schema"] = SCHEMA + "-v2"
    _write(apex, "good.json", good)
    _write(apex, "bad.json", bad)
    history = load_proof_history(tmp_path)
    assert len(history) == 1
    assert history[0]["schema"] == SCHEMA
    summary = summarise_fix_track_record(history)
    assert summary["proofs"] == 1
    assert summary["fixes"] == 1


def test_known_outcomes_are_not_folded_into_blocked(tmp_path: Path):
    """The three canonical outcomes (applied / rolled_back / blocked) are each
    counted under their own slot; only out-of-vocabulary values fold into
    ``blocked``. This pins the membership classification so a mutated outcome
    set can't silently reclassify a real ``applied`` as ``blocked``."""
    apex = tmp_path / ".apex"
    fixes = [
        {"finding": {"action": "c", "target": "app/m.py"}, "outcome": "applied"},
        {"finding": {"action": "c", "target": "app/m.py"}, "outcome": "rolled_back"},
        {"finding": {"action": "c", "target": "app/m.py"}, "outcome": "blocked"},
        {"finding": {"action": "c", "target": "app/m.py"}, "outcome": "??future??"},
    ]
    _write(apex, "p.json", _proof(fixes))
    stats = summarise_fix_track_record(load_proof_history(tmp_path))["by_action"]["c"]
    assert stats["applied"] == 1
    assert stats["rolled_back"] == 1
    # the canonical blocked plus the folded unknown
    assert stats["blocked"] == 2
    assert stats["total"] == 4


def test_missing_outcome_key_folds_to_blocked(tmp_path: Path):
    """A fix with no ``outcome`` key at all is treated as ``blocked`` (a
    non-landing), not dropped."""
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "n", "target": "app/m.py"}}
    _write(apex, "p.json", _proof([fix]))
    stats = summarise_fix_track_record(load_proof_history(tmp_path))["by_action"]["n"]
    assert stats["blocked"] == 1
    assert stats["applied"] == 0
    assert stats["reliability"] == 0.0
