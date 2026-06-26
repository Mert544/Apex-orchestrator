"""Proof-of-VALUE — the buyer/CI-facing surface of the proof-carrying moat.

Proof-of-FIX records the evidence; proof-of-VALUE makes it *consumable* by a
party that does not trust the prose: a single deterministic, tamper-evident
bundle (a content hash to pin + a manifest to read), derived entirely from the
existing proof-of-fix records. No competitor ships verifiable, deterministic
fix evidence — this module is where that evidence becomes a pinnable artifact.

This is a thin, additive surface: it re-exports the bundle API that lives next
to the record builder in :mod:`app.engine.proof_of_fix`, so the hash and the
manifest have exactly one implementation and can never drift from the records
they summarize. Nothing here mutates, re-orders, or re-keys an existing proof
artifact; the buyer view is computed alongside it, on demand.

Pure and deterministic: same records in → identical bundle out (no time, no
randomness, no hash-order dependence). The artifact's ``generated_at`` and tool
version stay OUTSIDE the hashed content, so the seal tracks audited facts only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.engine.proof_of_fix import (
    BUNDLE_SCHEMA,
    BUNDLE_VERSION,
    proof_bundle,
    proof_hash,
    proof_manifest,
)
from app.engine.value_landed import value_landed

__all__ = [
    "BUNDLE_SCHEMA",
    "BUNDLE_VERSION",
    "proof_bundle",
    "proof_hash",
    "proof_manifest",
    "write_bundle",
    "value_bundle",
    "write_value_bundle",
]


def write_bundle(
    artifact_or_records: Any,
    project_root: str | Path,
    out: str | Path | None = None,
) -> Path:
    """Write the buyer-facing bundle (default: ``.apex/proof-bundle.json``).

    Additive side-car: it sits beside ``proof-of-fix.json`` and never touches
    it. Returns the path written."""
    bundle = proof_bundle(artifact_or_records)
    path = Path(out) if out else Path(project_root) / ".apex" / "proof-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    return path


def value_bundle(artifact_or_records: Any) -> dict:
    """The proof bundle PLUS a buyer ``value`` block — the realized-value view.

    The existing :func:`proof_bundle` UNCHANGED (its ``proof_hash`` and
    ``summary`` byte-identical), with a ``value`` block from
    :func:`app.engine.value_landed.value_landed` added ALONGSIDE it. The value
    block is a DERIVED view of the same records, so it stays OUTSIDE
    ``proof_hash`` (which seals audited facts only) — the tamper seal and every
    existing bundle consumer are unaffected. Deterministic: same records in →
    identical bundle out (no time, no randomness, no hash-order)."""
    bundle = proof_bundle(artifact_or_records)
    bundle["value"] = value_landed(artifact_or_records)
    return bundle


def write_value_bundle(
    artifact_or_records: Any,
    project_root: str | Path,
    out: str | Path | None = None,
) -> Path:
    """Write the value-augmented bundle (default: ``.apex/value-bundle.json``).

    Additive side-car beside ``proof-bundle.json`` / ``proof-of-fix.json`` — it
    never touches either. Returns the path written."""
    bundle = value_bundle(artifact_or_records)
    path = Path(out) if out else Path(project_root) / ".apex" / "value-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    return path
