"""Proof-replay internal-consistency verifier — second, independent honesty check.

Complements the tamper hash: where ``proof_hash`` proves a record is immutable,
``replay_proof`` proves a record's own claims agree with each other. These tests
pin the well-formed / forged / malformed / determinism / empty paths and
mutation-harden each consistency check (loosening any one must fail a test).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_of_fix import SCHEMA
from app.engine.proof_replay import (
    DIFF_FILE_MISMATCH,
    MALFORMED_HUNK,
    MALFORMED_RECORD,
    TIER_MISMATCH,
    replay_history,
    replay_proof,
)
from app.execution.risk_tiers import tier_for


def _diff(rel: str) -> str:
    """A minimal, well-formed one-file unified diff touching ``rel``."""
    return (
        f"--- a/{rel}\n"
        f"+++ b/{rel}\n"
        "@@ -1,3 +1,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
    )


def _record(action: str = "create_test_stub", rel: str = "app/m.py",
            diff: str | None = None, changed: list[str] | None = None,
            tier: int | None = None) -> dict:
    """A well-formed fix record; tier defaults to the policy tier for ``action``."""
    return {
        "finding": {"label": "f", "action": action, "operator": "op",
                    "target": rel},
        "transform_type": action,
        "risk_tier": tier_for(action) if tier is None else tier,
        "outcome": "applied",
        "changed_files": [rel] if changed is None else changed,
        "diff": _diff(rel) if diff is None else diff,
    }


def _proof(records: list[dict],
           generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": generated_at, "fixes": records}


# --- well-formed -----------------------------------------------------------


def test_wellformed_proof_replays_ok():
    proof = _proof([_record("create_test_stub"), _record("harden_security")])
    result = replay_proof(proof)
    assert result["replay_ok"] is True
    assert result["discrepancies"] == []
    assert result["records"] == 2


def test_wellformed_multifile_diff_ok():
    rel1, rel2 = "app/a.py", "app/b.py"
    diff = _diff(rel1) + "\n" + _diff(rel2)
    rec = _record(changed=[rel1, rel2], diff=diff)
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is True


def test_wellformed_new_file_placeholder_ok():
    rec = _record(diff="(new file) b/app/m.py\n", changed=["app/m.py"])
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is True


def test_record_without_diff_is_ok():
    rec = _record(diff="", changed=[])
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is True


def proof_with(record: dict) -> dict:
    return _proof([record])


# --- diff/changed_files mismatch -------------------------------------------


def test_diff_touches_unlisted_file_flagged():
    # Diff header names app/secret.py but changed_files only lists app/m.py.
    rec = _record(diff=_diff("app/secret.py"), changed=["app/m.py"])
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is False
    kinds = {d["kind"] for d in result["discrepancies"]}
    assert DIFF_FILE_MISMATCH in kinds


def test_changed_files_not_in_diff_flagged():
    # changed_files claims a second file the diff never touches.
    rec = _record(diff=_diff("app/m.py"), changed=["app/m.py", "app/ghost.py"])
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is False
    assert any(d["kind"] == DIFF_FILE_MISMATCH and "ghost" in d["detail"]
               for d in result["discrepancies"])


def test_diff_with_body_but_no_header_flagged():
    rec = _record(diff="@@ -1 +1 @@\n-a\n+b\n", changed=["app/m.py"])
    result = replay_proof(proof_with(rec))
    assert any(d["kind"] == DIFF_FILE_MISMATCH
               for d in result["discrepancies"])


# --- tier mismatch ----------------------------------------------------------


def test_forged_tier_flagged():
    # harden_security is policy Tier 1; forge it as Tier 0.
    assert tier_for("harden_security") == 1
    rec = _record("harden_security", tier=0)
    result = replay_proof(proof_with(rec))
    assert result["replay_ok"] is False
    assert any(d["kind"] == TIER_MISMATCH for d in result["discrepancies"])


def test_matching_tier_not_flagged():
    rec = _record("design_task", tier=tier_for("design_task"))
    result = replay_proof(proof_with(rec))
    assert not any(d["kind"] == TIER_MISMATCH for d in result["discrepancies"])


def test_unknown_action_uses_policy_default_tier():
    # Unknown action → policy Tier 1; a record honestly recording 1 is fine,
    # a record forging 0 is flagged.
    assert tier_for("brand_new_action") == 1
    ok = _record("brand_new_action", tier=1)
    assert not any(d["kind"] == TIER_MISMATCH
                   for d in replay_proof(proof_with(ok))["discrepancies"])
    forged = _record("brand_new_action", tier=0)
    assert any(d["kind"] == TIER_MISMATCH
               for d in replay_proof(proof_with(forged))["discrepancies"])


def test_non_integer_tier_flagged():
    rec = _record(tier="zero")  # type: ignore[arg-type]
    result = replay_proof(proof_with(rec))
    assert any(d["kind"] == TIER_MISMATCH for d in result["discrepancies"])


def test_absent_tier_not_cross_checked():
    rec = _record()
    rec.pop("risk_tier")
    rec["risk_tier"] = None
    result = replay_proof(proof_with(rec))
    assert not any(d["kind"] == TIER_MISMATCH for d in result["discrepancies"])


# --- malformed hunks --------------------------------------------------------


def test_malformed_hunk_header_flagged():
    diff = (
        "--- a/app/m.py\n"
        "+++ b/app/m.py\n"
        "@@ nonsense @@\n"
        "+x\n"
    )
    rec = _record(diff=diff, changed=["app/m.py"])
    result = replay_proof(proof_with(rec))
    assert any(d["kind"] == MALFORMED_HUNK for d in result["discrepancies"])


def test_wellformed_hunk_variants_not_flagged():
    for header in ("@@ -1 +1 @@", "@@ -1,3 +1,3 @@", "@@ -10,0 +11,2 @@"):
        diff = f"--- a/app/m.py\n+++ b/app/m.py\n{header}\n+x\n"
        rec = _record(diff=diff, changed=["app/m.py"])
        result = replay_proof(proof_with(rec))
        assert not any(d["kind"] == MALFORMED_HUNK
                       for d in result["discrepancies"]), header


def test_hunk_missing_plus_range_flagged():
    diff = "--- a/app/m.py\n+++ b/app/m.py\n@@ -1,3 @@\n+x\n"
    rec = _record(diff=diff, changed=["app/m.py"])
    result = replay_proof(proof_with(rec))
    assert any(d["kind"] == MALFORMED_HUNK for d in result["discrepancies"])


# --- malformed / empty records ---------------------------------------------


def test_non_dict_proof_is_safe_discrepancy():
    result = replay_proof(None)  # type: ignore[arg-type]
    assert result["replay_ok"] is False
    assert result["records"] == 0
    assert result["discrepancies"] == [
        {"kind": MALFORMED_RECORD, "detail": "proof is not a dict"}]


def test_empty_proof_replays_ok():
    result = replay_proof(_proof([]))
    assert result["replay_ok"] is True
    assert result["records"] == 0
    assert result["discrepancies"] == []


def test_proof_with_no_fixes_key_replays_ok():
    result = replay_proof({"schema": SCHEMA})
    assert result["replay_ok"] is True
    assert result["records"] == 0


def test_non_dict_record_flagged_not_raised():
    proof = {"schema": SCHEMA, "fixes": ["not a dict", 42, None]}
    result = replay_proof(proof)
    assert result["replay_ok"] is False
    assert result["records"] == 0
    assert all(d["kind"] == MALFORMED_RECORD for d in result["discrepancies"])


def test_fixes_not_a_list_replays_ok():
    result = replay_proof({"schema": SCHEMA, "fixes": "oops"})
    assert result["replay_ok"] is True
    assert result["records"] == 0


# --- determinism ------------------------------------------------------------


def test_determinism_byte_identical():
    proof = _proof([
        _record("harden_security", tier=0, rel="app/z.py"),  # tier mismatch
        _record(diff=_diff("app/x.py"), changed=["app/y.py"]),  # file mismatch
        _record(diff="--- a/app/q.py\n+++ b/app/q.py\n@@ bad @@\n+1\n",
                changed=["app/q.py"]),  # malformed hunk
    ])
    first = replay_proof(proof)
    second = replay_proof(proof)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    # And the discrepancy list is itself sorted by (kind, detail).
    keys = [(d["kind"], d["detail"]) for d in first["discrepancies"]]
    assert keys == sorted(keys)


# --- replay_history ---------------------------------------------------------


def _write(apex: Path, name: str, proof: dict) -> None:
    apex.mkdir(parents=True, exist_ok=True)
    (apex / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


def test_replay_history_empty_root_is_empty(tmp_path: Path):
    assert replay_history(str(tmp_path)) == []
    assert replay_history(str(tmp_path / "nope")) == []


def test_replay_history_reads_archive(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "proof-of-fix.json",
           _proof([_record()], "2026-01-01T00:00:00+00:00"))
    _write(apex, "proof-deadbeef.json",
           _proof([_record("harden_security", tier=0)],
                  "2026-02-01T00:00:00+00:00"))
    results = replay_history(str(tmp_path))
    assert len(results) == 2
    # Loader order: oldest first → clean proof, then the tier-forged one.
    assert results[0]["replay_ok"] is True
    assert results[1]["replay_ok"] is False
    assert any(d["kind"] == TIER_MISMATCH
               for d in results[1]["discrepancies"])


def test_replay_history_skips_malformed_files(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "good.json", _proof([_record()]))
    (apex / "broken.json").write_text("{not json", encoding="utf-8")
    (apex / "other.json").write_text(
        json.dumps({"schema": "something-else"}), encoding="utf-8")
    results = replay_history(str(tmp_path))
    assert len(results) == 1
    assert results[0]["replay_ok"] is True


def test_replay_history_determinism(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write(apex, "p1.json", _proof([_record()], "2026-01-01T00:00:00+00:00"))
    _write(apex, "p2.json",
           _proof([_record("harden_security", tier=0)],
                  "2026-02-01T00:00:00+00:00"))
    first = replay_history(str(tmp_path))
    second = replay_history(str(tmp_path))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- mutation hardening -----------------------------------------------------
# Each asserts that a SPECIFIC tightening is load-bearing: loosening the check
# in the module (dropping a branch) would make one of these fail.


def test_mutation_diff_direction_both_ways():
    # Both directions of the file-set comparison must be enforced.
    extra_in_diff = _record(diff=_diff("app/x.py"), changed=[])
    extra_in_changed = _record(diff="", changed=["app/m.py"])
    # diff names a file, changed_files empty → flagged.
    assert any(d["kind"] == DIFF_FILE_MISMATCH
               for d in replay_proof(proof_with(extra_in_diff))["discrepancies"])
    # changed_files lists a file but there's no diff → nothing to compare, ok.
    assert replay_proof(proof_with(extra_in_changed))["replay_ok"] is True


def test_mutation_tier_must_equal_not_just_bounded():
    # A tier that is a valid integer but wrong must still be flagged (the check
    # is equality against the policy, not a range membership).
    rec = _record("create_test_stub", tier=2)  # policy says 0
    assert tier_for("create_test_stub") == 0
    assert any(d["kind"] == TIER_MISMATCH
               for d in replay_proof(proof_with(rec))["discrepancies"])
