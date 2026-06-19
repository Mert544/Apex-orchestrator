"""Proof archiving — write_proof accumulates a content-deduped track record.

``write_proof`` keeps ``.apex/proof-of-fix.json`` byte-identical as the "latest"
pointer, but ALSO archives superseded proofs under content-addressed
``.apex/proof-<hash>.json`` files so ``load_proof_history`` (and the fix-risk
model behind it) learns across maintenance runs instead of seeing only the last
run's evidence. These tests pin: byte-identical pointer, end-to-end
accumulation, same-content dedup, fix-risk reflecting fused outcomes, capping,
and determinism. None of this touches the reader or the scoring kernel.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.fix_risk_model import fix_risk
from app.engine.proof_history import (
    load_proof_history,
    summarise_fix_track_record,
)
from app.engine.proof_of_fix import (
    build_proof,
    proof_hash,
    write_proof,
)


def _summary(action: str, outcome: str, target: str = "app/m.py") -> dict:
    """A minimal apply_plan-shaped summary that build_proof turns into one fix
    with the given action/outcome on the given target."""
    row: dict = {
        "branch": "1", "action": action, "operator": "op",
        "label": "lbl", "target": target,
        "transform_type": action, "changed_files": [target],
        "diff": f"--- a/{target}\n+++ b/{target}\n",
    }
    if outcome == "applied":
        row["applied"] = True
        row["test_evidence"] = {"performed": True, "ok": True, "tests_passed": 1}
    elif outcome == "rolled_back":
        row["applied"] = False
        row["rolled_back"] = True
        row["reason"] = "tests failed after patch; changes rolled back"
    else:  # blocked
        row["applied"] = False
        row["reason"] = "blocked by safety gates"
    totals = {"applied": 1 if outcome == "applied" else 0,
              "rolled_back": 1 if outcome == "rolled_back" else 0,
              "blocked": 1 if outcome == "blocked" else 0}
    return {
        "mode": "supervised", "verify": True,
        "total_executable": 1, "committed": 0,
        **totals, "results": [row],
    }


def _proof(action: str, outcome: str, target: str, generated_at: str) -> dict:
    proof = build_proof(_summary(action, outcome, target), "/proj")
    proof["generated_at"] = generated_at  # pin time out of the equation
    return proof


# --- byte-identical latest pointer ----------------------------------------


def test_latest_pointer_is_byte_identical(tmp_path: Path):
    """The pointer file is written exactly as the raw artifact would be — every
    existing consumer/test that reads .apex/proof-of-fix.json is unaffected."""
    proof = _proof("harden_security", "applied", "app/x.py",
                   "2026-01-01T00:00:00+00:00")
    path = write_proof(proof, str(tmp_path))
    assert path == tmp_path / ".apex" / "proof-of-fix.json"
    expected = json.dumps(proof, indent=2) + "\n"
    assert path.read_text(encoding="utf-8") == expected


def test_first_write_does_not_double_count_pointer(tmp_path: Path):
    """A single write leaves exactly one counted proof (no spurious archive of
    its own content alongside the pointer)."""
    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    write_proof(proof, str(tmp_path))
    history = load_proof_history(tmp_path)
    assert len(history) == 1
    assert summarise_fix_track_record(history)["fixes"] == 1


# --- accumulation across runs ---------------------------------------------


def test_two_different_runs_accumulate(tmp_path: Path):
    """End-to-end: build two DIFFERENT proofs, write both, assert the history
    fuses BOTH runs' fixes — not just the last."""
    p1 = _proof("harden_security", "rolled_back", "app/danger.py",
                "2026-01-01T00:00:00+00:00")
    p2 = _proof("add_docstring", "applied", "app/svc.py",
                "2026-02-01T00:00:00+00:00")
    write_proof(p1, str(tmp_path))
    write_proof(p2, str(tmp_path))

    history = load_proof_history(tmp_path)
    summary = summarise_fix_track_record(history)
    # Both runs' single fixes are present.
    assert summary["fixes"] == 2
    assert "harden_security" in summary["by_action"]
    assert "add_docstring" in summary["by_action"]
    # The latest pointer still holds run 2 byte-identically.
    pointer = tmp_path / ".apex" / "proof-of-fix.json"
    assert pointer.read_text(encoding="utf-8") == json.dumps(p2, indent=2) + "\n"


def test_same_content_twice_does_not_double_count(tmp_path: Path):
    """Two writes with the SAME proof content collapse to a single counted
    record — content-addressed archiving dedups, and the pointer is not a
    second copy."""
    proof = _proof("create_test_stub", "applied", "app/m.py",
                   "2026-01-01T00:00:00+00:00")
    # Identical content (same generated_at + same fixes) written twice.
    write_proof(proof, str(tmp_path))
    write_proof(proof, str(tmp_path))

    history = load_proof_history(tmp_path)
    summary = summarise_fix_track_record(history)
    assert summary["fixes"] == 1
    assert summary["by_action"]["create_test_stub"]["applied"] == 1


def test_repeated_then_returning_content_counts_each_distinct_once(tmp_path: Path):
    """C, D, C: the returning content C is still counted exactly once (the
    pointer represents it; its stale archive is dropped)."""
    c = _proof("a", "applied", "app/c.py", "2026-01-01T00:00:00+00:00")
    d = _proof("b", "rolled_back", "app/d.py", "2026-02-01T00:00:00+00:00")
    write_proof(c, str(tmp_path))
    write_proof(d, str(tmp_path))
    write_proof(c, str(tmp_path))

    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    # Distinct contents C and D each counted once → 2 fixes, not 3.
    assert summary["fixes"] == 2
    assert summary["by_action"]["a"]["applied"] == 1
    assert summary["by_action"]["b"]["rolled_back"] == 1


# --- fix-risk reflects FUSED outcomes -------------------------------------


def test_fix_risk_reflects_accumulated_outcomes(tmp_path: Path):
    """A transform rolled back in run 1 but ABSENT from run 2 still carries its
    run-1 evidence into the risk score — the whole point of accumulation."""
    # A control project that ONLY ever sees run 2: harden_security is unknown,
    # so fix_risk reads the neutral baseline (single-run NOISE has no memory).
    control = tmp_path / "control"
    control.mkdir()
    write_proof(
        _proof("add_docstring", "applied", "app/svc.py",
               "2026-02-01T00:00:00+00:00"),
        str(control))
    assert fix_risk(control, "harden_security", "app/danger.py") == 0.5

    # The accumulating project: run 1 rolls back harden_security; run 2 never
    # mentions it. With archiving, run-1's rollback evidence survives.
    learn = tmp_path / "learn"
    learn.mkdir()
    write_proof(
        _proof("harden_security", "rolled_back", "app/danger.py",
               "2026-01-01T00:00:00+00:00"),
        str(learn))
    write_proof(
        _proof("add_docstring", "applied", "app/svc.py",
               "2026-02-01T00:00:00+00:00"),
        str(learn))

    risk_bad = fix_risk(learn, "harden_security", "app/danger.py")
    risk_clean = fix_risk(learn, "add_docstring", "app/svc.py")
    # Run-1's rollback evidence survives the run-2 overwrite into the score.
    assert risk_bad > 0.5
    assert risk_clean < 0.5
    assert risk_bad > risk_clean


# --- capping & determinism -------------------------------------------------


def test_archive_is_capped(tmp_path: Path):
    """Many distinct runs do not grow the archive without bound: the directory
    stays within the deterministic keep cap (+1 for the latest pointer)."""
    from app.engine.proof_of_fix import _ARCHIVE_KEEP

    for i in range(_ARCHIVE_KEEP + 10):
        ts = f"2026-01-{(i % 27) + 1:02d}T00:{i % 60:02d}:00+00:00"
        write_proof(_proof(f"act{i}", "applied", f"app/m{i}.py", ts),
                    str(tmp_path))

    apex = tmp_path / ".apex"
    archives = [p for p in apex.glob("proof-*.json")
                if p.name != "proof-of-fix.json"]
    assert len(archives) <= _ARCHIVE_KEEP


def test_archive_name_is_content_addressed_and_safe(tmp_path: Path):
    """The archive filename is a deterministic, filesystem-safe function of the
    proof's content hash and never collides with the latest pointer."""
    from app.engine.proof_of_fix import _archive_name

    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    name = _archive_name(proof)
    assert name.startswith("proof-") and name.endswith(".json")
    assert name != "proof-of-fix.json"
    # Pure function of content (proof_hash), not time/path/order.
    assert _archive_name(proof) == name
    assert proof_hash(proof).split(":", 1)[-1] in name
    # Filesystem-safe: only hex + the fixed affixes.
    stem = name[len("proof-"):-len(".json")]
    assert all(ch in "0123456789abcdef" for ch in stem)


def test_writes_are_deterministic_end_to_end(tmp_path: Path):
    """Same sequence of writes in two separate projects → identical fused
    history (same input → same output, no time/random in the archive scheme)."""
    seq = [
        _proof("a", "applied", "app/a.py", "2026-01-01T00:00:00+00:00"),
        _proof("b", "rolled_back", "app/b.py", "2026-02-01T00:00:00+00:00"),
        _proof("a", "blocked", "app/c.py", "2026-03-01T00:00:00+00:00"),
    ]
    one = tmp_path / "one"
    two = tmp_path / "two"
    for root in (one, two):
        root.mkdir()
        for proof in seq:
            write_proof(proof, str(root))

    s1 = summarise_fix_track_record(load_proof_history(one))
    s2 = summarise_fix_track_record(load_proof_history(two))
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)


def test_archive_failure_does_not_break_primary_write(tmp_path: Path, monkeypatch):
    """If archiving raises, the latest pointer is still written byte-identically
    — archiving is strictly best-effort."""
    import app.engine.proof_of_fix as pof

    def boom(*_a, **_k):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(pof, "_archive_proof", boom)
    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    path = write_proof(proof, str(tmp_path))
    assert path.read_text(encoding="utf-8") == json.dumps(proof, indent=2) + "\n"
