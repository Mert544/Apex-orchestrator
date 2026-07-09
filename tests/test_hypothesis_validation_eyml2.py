"""Self-validating discovery — parse/guard edge paths (eyml2 wave).

Targets the branches the first wave left uncovered: a ``triple:`` key with no
``>`` (no directional rule), the empty-antecedent guard in the tautology check, a
DIRECT ``validate_hypothesis`` call on a structural tautology (reported, never
confirmed), and ``validate_discoveries`` skipping both a non-directional
discovery and a structural tautology. Deterministic, offline.
"""

from __future__ import annotations

from app.engine import hypothesis_validation as hv
from app.engine.hypothesis_validation import (
    _is_structural_tautology,
    discovery_to_hypothesis,
    validate_discoveries,
    validate_hypothesis,
)
from app.tools.project_profile import ProjectProfile


def test_triple_key_without_arrow_has_no_hypothesis():
    # A ``triple:`` body lacking ``>`` names no consequent -> no if/then rule.
    assert discovery_to_hypothesis({"key": "triple:a&b"}) is None


def test_empty_antecedent_is_not_a_structural_tautology():
    assert _is_structural_tautology({"antecedent": [], "consequent": ["untested"]}) is False
    assert _is_structural_tautology({"antecedent": ["untested"], "consequent": []}) is False


def test_direct_validate_of_structural_tautology_is_reported_not_confirmed():
    # critical-untested is a by-construction subset of untested; validating it
    # directly must yield verdict "tautology" (never "confirmed").
    hypothesis = {
        "kind": "association",
        "antecedent": ["critical-untested"],
        "consequent": ["untested"],
        "claim": "definitional",
        "key": "assoc:critical-untested>untested",
    }
    profile = ProjectProfile(
        root=".",
        critical_untested_modules=["app/a.py", "app/b.py"],
        untested_modules=["app/a.py", "app/b.py"],
    )
    result = validate_hypothesis(hypothesis, profile)
    assert result["tautology"] is True
    assert result["verdict"] == "tautology"


def test_validate_discoveries_skips_nondirectional_and_tautology(monkeypatch):
    # One confluence (no if/then -> hypothesis None), one structural tautology
    # (dropped), one genuine association (kept).
    def _fake_discover(profile):
        return [
            {"key": "confluence:broadmod"},
            {"key": "assoc:critical-untested>untested"},
            {"key": "assoc:security>untested"},
        ]

    monkeypatch.setattr(hv, "discover_emergent", _fake_discover)
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py", "app/b.py"],
        untested_modules=["app/a.py", "app/b.py"],
    )
    results = validate_discoveries(profile, top=5)
    keys = [r["key"] for r in results]
    assert keys == ["assoc:security>untested"]
