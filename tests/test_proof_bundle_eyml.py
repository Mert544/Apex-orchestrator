"""Proof BUNDLE: a tamper-evident hash + auditable manifest over proof-of-fix.

The bundle is the buyer/CI-facing surface of the proof-carrying moat: a stable
``proof_hash`` a CI gate can pin, and a ``summary`` manifest a human can read —
both pure functions of the EXISTING proof-of-fix records, so the summary can
never disagree with the evidence and the hash tracks audited facts only.

These tests pin: (1) the existing artifact shape is UNCHANGED (additive), (2)
the hash is STABLE across runs and CHANGES when one recorded fact changes, (3)
the manifest is derived from and consistent with the records, (4) full
determinism, and (5) the edge/empty paths. Deterministic, stdlib-only.
"""

from __future__ import annotations

import json

from app.engine.proof_of_fix import (
    BUNDLE_SCHEMA,
    BUNDLE_VERSION,
    SCHEMA,
    SCHEMA_VERSION,
    build_proof,
    proof_bundle,
    proof_hash,
    proof_manifest,
)
from app.engine.proof_of_value import (
    proof_bundle as pov_bundle,
    write_bundle,
)

# A fixed, representative apply-plan summary: one applied (function-covered),
# one rolled back, one blocked. The bundle is computed over the records this
# yields, so these tests are anchored to the real record shape.
_SUMMARY = {
    "mode": "supervised", "verify": True, "commit": False,
    "total_executable": 3, "applied": 1, "rolled_back": 1,
    "blocked": 1, "committed": 0,
    "results": [
        {"branch": "1", "action": "harden_security", "operator": "harden",
         "label": "security-risk", "target": "app/danger.py", "applied": True,
         "transform_type": "fix_eval", "changed_files": ["app/danger.py"],
         "diff": "--- a/app/danger.py\n+++ b/app/danger.py\n+ast.literal_eval\n",
         "rolled_back": False,
         "test_evidence": {"performed": True, "ok": True, "tests_passed": 3,
                           "duration_seconds": 1.234567},
         "verification_strength": {"level": "function"},
         "commit_hash": "abc123"},
        {"branch": "2", "action": "add_docstring", "operator": "document",
         "label": "dependency-hub", "target": "app/svc.py", "applied": False,
         "rolled_back": True, "reason": "tests failed after patch; rolled back",
         "changed_files": ["app/svc.py"]},
        {"branch": "3", "action": "harden_security", "operator": "harden",
         "label": "", "target": "app/x.py", "applied": False,
         "reason": "blocked by safety gates"},
    ],
}


def _proof():
    return build_proof(_SUMMARY, "/tmp/proj", objective="harden")


# --- HARD GATE: existing artifact is unchanged (additive) -------------------

def test_existing_proof_shape_intact():
    proof = _proof()
    # Every pre-existing top-level key still present and untouched.
    for key in ("schema", "schema_version", "tool", "generated_at",
                "project_root", "objective", "mode", "verify", "totals",
                "fixes"):
        assert key in proof
    assert proof["schema"] == SCHEMA
    assert proof["schema_version"] == SCHEMA_VERSION
    assert proof["totals"] == {"executable": 3, "applied": 1, "rolled_back": 1,
                               "blocked": 1, "committed": 0}
    assert [f["outcome"] for f in proof["fixes"]] == \
        ["applied", "rolled_back", "blocked"]
    # The bundle is a side-car; it does NOT inject keys into the artifact.
    assert "proof_hash" not in proof
    assert "summary" not in proof
    assert "proof_bundle" not in proof


# --- HARD GATE: stable hash, and a different hash when a fact changes --------

def test_proof_hash_is_stable_across_runs():
    h1 = proof_hash(_proof())
    h2 = proof_hash(build_proof(_SUMMARY, "/tmp/proj", objective="harden"))
    assert h1 == h2
    assert h1.startswith("sha256:") and len(h1) == len("sha256:") + 64


def test_generated_at_and_tool_outside_the_seal():
    # The timestamp/tool version live OUTSIDE the hashed content: two artifacts
    # with different generated_at but identical records hash the same.
    a = _proof()
    b = _proof()
    a["generated_at"] = "2020-01-01T00:00:00+00:00"
    b["generated_at"] = "2099-12-31T23:59:59+00:00"
    a["tool"] = {"name": "x", "version": "9.9.9"}
    assert proof_hash(a) == proof_hash(b)


def test_hash_changes_when_a_recorded_fact_changes():
    base = proof_hash(_proof())

    def mutate(mut):
        summary = json.loads(json.dumps(_SUMMARY))
        mut(summary)
        return proof_hash(build_proof(summary, "/tmp/proj", objective="harden"))

    # diff text changed
    assert mutate(lambda s: s["results"][0].__setitem__("diff", "x")) != base
    # outcome flipped (applied -> rolled_back)
    assert mutate(lambda s: s["results"][0].update(
        {"applied": False, "rolled_back": True})) != base
    # coverage/verification changed
    assert mutate(lambda s: s["results"][0].__setitem__(
        "verification_strength", {"level": "none"})) != base
    # finding label changed
    assert mutate(lambda s: s["results"][0].__setitem__(
        "label", "other")) != base
    # changed_files changed
    assert mutate(lambda s: s["results"][0].__setitem__(
        "changed_files", ["app/other.py"])) != base


def test_float_jitter_below_precision_does_not_move_hash():
    base = proof_hash(_proof())
    summary = json.loads(json.dumps(_SUMMARY))
    # A re-measured duration that differs only below 6dp is the same fact.
    summary["results"][0]["test_evidence"]["duration_seconds"] = 1.2345671
    assert proof_hash(build_proof(summary, "/tmp/proj", objective="harden")) == base


# --- the manifest is derived from, and agrees with, the records -------------

def test_manifest_counts_match_records():
    m = proof_manifest(_proof())
    assert m["records"] == 3
    assert m["by_outcome"]["applied"] == 1
    assert m["by_outcome"]["rolled_back"] == 1
    assert m["by_outcome"]["blocked"] == 1
    assert m["by_outcome"]["skipped_learned"] == 0
    # Coverage tally only counts applied fixes; this one is function-covered.
    assert m["by_coverage"]["function"] == 1
    assert m["by_coverage"]["module"] == 0
    assert m["by_coverage"]["none"] == 0
    assert m["auto_fixed"] == 1
    assert m["flagged"] == 2  # rolled_back + blocked
    assert m["auto_fixed"] + m["flagged"] == m["records"]
    assert "1 auto-fixed" in m["verdict"] and "rolled back" in m["verdict"]


def test_manifest_by_outcome_sums_to_records():
    m = proof_manifest(_proof())
    assert sum(m["by_outcome"].values()) == m["records"]


def test_uncovered_applied_fix_counts_as_none_coverage():
    summary = json.loads(json.dumps(_SUMMARY))
    summary["results"][0]["verification_strength"] = {"level": "none"}
    m = proof_manifest(build_proof(summary, "/tmp/proj"))
    assert m["by_coverage"]["none"] == 1
    assert m["by_coverage"]["function"] == 0


# --- the bundle wraps hash + manifest ---------------------------------------

def test_bundle_shape():
    bundle = proof_bundle(_proof())
    assert bundle["schema"] == BUNDLE_SCHEMA
    assert bundle["schema_version"] == BUNDLE_VERSION
    assert bundle["proof_hash"] == proof_hash(_proof())
    assert bundle["summary"] == proof_manifest(_proof())


def test_bundle_accepts_bare_records():
    # A bare list of fix records is equivalent to the artifact's "fixes".
    proof = _proof()
    assert proof_bundle(proof["fixes"]) == proof_bundle(proof)
    assert proof_hash(proof["fixes"]) == proof_hash(proof)


def test_bundle_is_deterministic():
    a = proof_bundle(_proof())
    b = pov_bundle(build_proof(_SUMMARY, "/tmp/proj", objective="harden"))
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_proof_of_value_reexports_one_implementation():
    # proof_of_value is a thin surface over the one implementation.
    assert pov_bundle(_proof()) == proof_bundle(_proof())


# --- edge / empty paths -----------------------------------------------------

def test_empty_artifact_bundle():
    empty = build_proof({"results": []}, "/tmp/proj")
    bundle = proof_bundle(empty)
    assert bundle["summary"]["records"] == 0
    assert bundle["summary"]["auto_fixed"] == 0
    assert bundle["summary"]["flagged"] == 0
    assert bundle["summary"]["verdict"] == "no fixes recorded"
    # Empty is still a stable, well-formed hash.
    assert bundle["proof_hash"].startswith("sha256:")
    assert proof_hash([]) == proof_hash(empty)


def test_empty_list_and_none_equivalent():
    assert proof_bundle([]) == proof_bundle(None)


def test_skipped_learned_is_flagged_not_auto_fixed():
    summary = {"results": [
        {"branch": "1", "applied": False, "skipped_learned": True,
         "target": "app/a.py"},
    ]}
    m = proof_manifest(build_proof(summary, "/tmp/proj"))
    assert m["by_outcome"]["skipped_learned"] == 1
    assert m["auto_fixed"] == 0
    assert m["flagged"] == 1


def test_all_flagged_verdict():
    summary = {"results": [
        {"branch": "1", "applied": False, "target": "app/a.py",
         "reason": "blocked"},
    ]}
    m = proof_manifest(build_proof(summary, "/tmp/proj"))
    assert m["verdict"] == "0 auto-fixed, 1 flagged for review"


def test_write_bundle_default_path(tmp_path):
    path = write_bundle(_proof(), str(tmp_path))
    assert path == tmp_path / ".apex" / "proof-bundle.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema"] == BUNDLE_SCHEMA
    assert written["proof_hash"] == proof_hash(_proof())
    # Side-car only: it never writes the proof-of-fix artifact.
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()


def test_write_bundle_is_byte_stable(tmp_path):
    p1 = write_bundle(_proof(), str(tmp_path), out=tmp_path / "a.json")
    p2 = write_bundle(build_proof(_SUMMARY, "/tmp/proj", objective="harden"),
                      str(tmp_path), out=tmp_path / "b.json")
    assert p1.read_text() == p2.read_text()
