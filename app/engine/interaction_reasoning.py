"""Compounding-interaction reasoning lens over an idea's converging signals.

Where the counterfactual lens names the consequence of each concern *in
isolation*, this lens explains HOW two converging concerns AMPLIFY each other —
why the whole is riskier than the sum of its parts. It encodes a small, explicit
table of PAIR interactions: when both labels of a pair are present, the pair's
compounding effect is emitted as a one-line clause.

The function is a pure reasoning-enricher (see ``app/engine/idea_reasoning.py``):
``interaction_enrichment(labels) -> (clause, [f"interaction: {clause}"])`` when a
pair fully matches, or ``(None, None)`` otherwise (so an un-reasoned idea stays
byte-identical). It is NOT registered here — registration is a separate concern.
Deterministic: no time, no randomness; the fixed pair order is the tie-break.
"""

from __future__ import annotations

# Synonymous labels that name the same underlying concern, normalised to a single
# canonical token so the pair table stays small. A converging signal label (a
# confluence family name or an idea ``fact_label``) is matched after this mapping.
_SYNONYMS: dict[str, str] = {
    # central coupling / high blast-radius
    "dependency-hub": "hub",
    "symbol-hub": "hub",
    "god-class": "hub",
    "fragile": "hub",
    # missing tests
    "critical-untested": "untested",
    "shallow-coverage": "untested",
    # complexity
    "complex-function": "complexity-hotspot",
    # dangerous dynamic call
    "eval": "security-finding",
    "security-eval": "security-finding",
    "sensitive-path": "security-finding",
    # frequent change
    "churn": "churn-hotspot",
}


# Explicit PAIR-interaction table. Each entry pairs two canonical concerns with
# the compounding effect of their co-occurrence — the reason the pair is riskier
# than either concern alone. ORDER is the deterministic tie-break: when several
# pairs are fully present, the earliest entry here wins. Order must not move.
_PAIR_INTERACTIONS: list[tuple[frozenset[str], str]] = [
    (
        frozenset({"security-finding", "untested"}),
        "a dangerous call with no test is an unguarded attack surface",
    ),
    (
        frozenset({"untested", "hub"}),
        "an untested hub means every dependent inherits the risk with no safety net",
    ),
    (
        frozenset({"untested", "complexity-hotspot"}),
        "complexity hides bugs the absent tests would have caught",
    ),
    (
        frozenset({"deep-nesting", "complexity-hotspot"}),
        "nesting multiplies the paths the complexity already makes hard to follow",
    ),
    (
        frozenset({"churn-hotspot", "hub"}),
        "frequent change in a hub keeps re-broadcasting instability",
    ),
]


def _canonical_labels(labels: object) -> set[str]:
    """Normalise the converging labels to the canonical concern tokens."""
    present: set[str] = set()
    for label in labels or []:
        present.add(_SYNONYMS.get(label, label))
    return present


def interaction_enrichment(labels: object) -> "tuple[str | None, list[str] | None]":
    """Compounding-interaction reasoning over an idea's converging signals.

    Finds the strongest PAIR of converging concerns that amplify each other and
    emits a one-line clause naming the compounding effect. "Strongest" is decided
    by the fixed order of ``_PAIR_INTERACTIONS`` (earliest fully-present pair
    wins), so the result is deterministic when several pairs co-occur. Mirrors the
    enricher contract: ``(clause, [f"interaction: {clause}"])`` on a match, or
    ``(None, None)`` when no encoded pair is fully present (the un-reasoned idea
    then stays byte-identical). Deterministic — no time/random.
    """
    present = _canonical_labels(labels)
    for pair, effect in _PAIR_INTERACTIONS:
        if pair <= present:
            clause = "compounding: " + effect
            return clause, [f"interaction: {clause}"]
    return None, None
