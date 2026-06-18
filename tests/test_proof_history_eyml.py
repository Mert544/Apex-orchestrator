"""Proof-of-Fix history learning — aggregation, reliability, and tolerance."""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_history import (
    learned_reliability,
    load_proof_history,
    summarise_fix_track_record,
)
from app.engine.proof_of_fix import SCHEMA


def _fix(action: str, outcome: str, target: str = "app/m.py",
         changed: list[str] | None = None) -> dict:
    return {
        "finding": {"label": "untested", "action": action,
                    "operator": "test", "target": target},
        "transform_type": action,
        "outcome": outcome,
        "changed_files": changed if changed is not None else [target],
    }


def _proof(fixes: list[dict], generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": fixes}


def _write(apex_dir: Path, name: str, proof: dict) -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


# --- load_proof_history ----------------------------------------------------


def test_load_reads_all_valid_proofs(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "proof-of-fix.json", _proof([_fix("create_test_stub", "applied")]))
    _write(apex, "archive-1.json", _proof([_fix("harden_security", "blocked")]))
    history = load_proof_history(tmp_path)
    assert len(history) == 2


def test_load_missing_dir_is_empty(tmp_path: Path):
    assert load_proof_history(tmp_path / "nope") == []
    assert load_proof_history(tmp_path) == []


def test_load_skips_malformed_and_wrong_schema(tmp_path: Path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "good.json").write_text(json.dumps(_proof([_fix("x", "applied")])), "utf-8")
    (apex / "broken.json").write_text("{not json", "utf-8")
    (apex / "other.json").write_text(json.dumps({"schema": "something-else"}), "utf-8")
    (apex / "list.json").write_text(json.dumps([1, 2, 3]), "utf-8")
    history = load_proof_history(tmp_path)
    assert len(history) == 1
    assert history[0]["schema"] == SCHEMA


def test_load_sorted_by_timestamp_then_filename(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "b.json", _proof([_fix("late", "applied")], "2026-03-01T00:00:00+00:00"))
    _write(apex, "a.json", _proof([_fix("early", "applied")], "2026-01-01T00:00:00+00:00"))
    # Same timestamp -> filename breaks the tie.
    _write(apex, "z.json", _proof([_fix("tie_z", "applied")], "2026-01-01T00:00:00+00:00"))
    _write(apex, "c.json", _proof([_fix("tie_c", "applied")], "2026-01-01T00:00:00+00:00"))
    actions = [p["fixes"][0]["finding"]["action"] for p in load_proof_history(tmp_path)]
    assert actions == ["early", "tie_c", "tie_z", "late"]


# --- summarise_fix_track_record --------------------------------------------


def test_summarise_aggregates_per_action_and_module(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p1.json", _proof([
        _fix("create_test_stub", "applied", "app/a.py"),
        _fix("create_test_stub", "applied", "app/b.py"),
        _fix("create_test_stub", "rolled_back", "app/a.py"),
        _fix("harden_security", "blocked", "app/a.py"),
    ]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["proofs"] == 1
    assert summary["fixes"] == 4
    assert summary["totals"]["applied"] == 2
    assert summary["totals"]["rolled_back"] == 1
    assert summary["totals"]["blocked"] == 1
    assert summary["totals"]["reliability"] == 0.5

    stub = summary["by_action"]["create_test_stub"]
    assert stub == {"applied": 2, "rolled_back": 1, "blocked": 0,
                    "total": 3, "reliability": round(2 / 3, 4)}
    assert summary["by_action"]["harden_security"]["reliability"] == 0.0

    mod_a = summary["by_module"]["app/a.py"]
    assert mod_a["applied"] == 1 and mod_a["total"] == 3


def test_summarise_module_falls_back_to_changed_files(tmp_path: Path):
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "x", "target": ""}, "outcome": "applied",
           "changed_files": ["tests/test_gen.py"]}
    _write(apex, "p.json", _proof([fix]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert "tests/test_gen.py" in summary["by_module"]


def test_summarise_spans_multiple_proofs(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p1.json", _proof([_fix("act", "applied")], "2026-01-01T00:00:00+00:00"))
    _write(apex, "p2.json", _proof([_fix("act", "rolled_back")], "2026-02-01T00:00:00+00:00"))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["proofs"] == 2
    assert summary["by_action"]["act"] == {
        "applied": 1, "rolled_back": 1, "blocked": 0,
        "total": 2, "reliability": 0.5}


def test_summarise_empty_history_is_neutral(tmp_path: Path):
    summary = summarise_fix_track_record([])
    assert summary["proofs"] == 0
    assert summary["fixes"] == 0
    assert summary["totals"]["reliability"] == 0.0
    assert summary["by_action"] == {}
    assert summary["by_module"] == {}


def test_summarise_unknown_outcome_counts_as_blocked(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p.json", _proof([_fix("act", "weird-future-outcome")]))
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["by_action"]["act"]["blocked"] == 1
    assert summary["by_action"]["act"]["reliability"] == 0.0


# --- learned_reliability ----------------------------------------------------


def test_learned_reliability_per_action_bounded(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p.json", _proof([
        _fix("good", "applied"), _fix("good", "applied"), _fix("good", "applied"),
        _fix("flaky", "applied"), _fix("flaky", "rolled_back"),
        _fix("bad", "blocked"),
    ]))
    rel = learned_reliability(load_proof_history(tmp_path))
    assert rel == {"good": 1.0, "flaky": 0.5, "bad": 0.0}
    assert all(0.0 <= v <= 1.0 for v in rel.values())


def test_learned_reliability_empty_history(tmp_path: Path):
    assert learned_reliability([]) == {}
    assert learned_reliability(load_proof_history(tmp_path / "nope")) == {}


def test_learned_reliability_omits_actionless_fixes(tmp_path: Path):
    apex = tmp_path / ".apex"
    fix = {"finding": {"action": "", "target": "app/a.py"}, "outcome": "applied"}
    _write(apex, "p.json", _proof([fix, _fix("real", "applied")]))
    rel = learned_reliability(load_proof_history(tmp_path))
    assert rel == {"real": 1.0}


# --- determinism ------------------------------------------------------------


def test_determinism_same_input_same_output(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p1.json", _proof([
        _fix("a", "applied", "app/x.py"), _fix("b", "rolled_back", "app/y.py")],
        "2026-01-01T00:00:00+00:00"))
    _write(apex, "p2.json", _proof([
        _fix("a", "blocked", "app/z.py")], "2026-02-01T00:00:00+00:00"))
    first = summarise_fix_track_record(load_proof_history(tmp_path))
    second = summarise_fix_track_record(load_proof_history(tmp_path))
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert learned_reliability(load_proof_history(tmp_path)) == \
        learned_reliability(load_proof_history(tmp_path))
