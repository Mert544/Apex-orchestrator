"""Reasoning-enricher seam — pluggable causal / impact / hypothesis reasoning
over an idea's converging signal labels.

Each *enricher* inspects the converging signal labels of a high-signal idea and
returns an optional rationale CLAUSE plus optional extra ``source_facts``. The
contract is purely ADDITIVE: an idea for which no enricher fires is byte-identical
to one built without this seam, and an enricher only ever APPENDS to an idea — it
never reorders, replaces, or drops an existing fact, subject, title, or the
routing-critical ``source_facts[0]``.

Enrichers run in a fixed registry order, so the combined output is deterministic.
This is how Apex turns a mechanical "these signals converge" finding into a
REASONED one ("...; root cause: <why> (confidence c); risk if unaddressed: ...").
New reasoning lenses (counterfactual, blast-radius, hypothesis, …) register by
appending their own pure function to ``REASONING_ENRICHERS`` — each lives in its
own engine module, so the seam grows without touching the seeder.
"""

from collections.abc import Callable

# An enricher maps the converging signal labels to an optional one-line rationale
# clause and an optional list of extra source_facts (each appended AFTER
# ``source_facts[0]``). Returning ``(None, None)`` means "no grounded reasoning
# for these signals" — the idea then stays byte-identical.
Enricher = Callable[[object], "tuple[str | None, list[str] | None]"]


def _abductive(labels: object) -> "tuple[str | None, list[str] | None]":
    """Root-cause (abductive) reasoning: WHY do these signals co-occur?"""
    from app.engine.abductive_reasoning import explain_signals, explanation_clause

    result = explain_signals(labels)
    if result is None:
        return None, None
    clause = explanation_clause(result)
    if not clause:
        return None, None
    return clause, [f"abductive: {clause}"]


def _interaction(labels: object) -> "tuple[str | None, list[str] | None]":
    """Interaction reasoning: HOW the converging concerns compound each other."""
    from app.engine.interaction_reasoning import interaction_enrichment

    return interaction_enrichment(labels)


def _counterfactual(labels: object) -> "tuple[str | None, list[str] | None]":
    """Counterfactual reasoning: the RISK if these concerns stay unaddressed."""
    from app.engine.counterfactual_generator import counterfactual_enrichment

    return counterfactual_enrichment(labels)


def _remediation(labels: object) -> "tuple[str | None, list[str] | None]":
    """Sequencing reasoning: the safe ORDER to address the converging concerns."""
    from app.engine.remediation_reasoning import remediation_enrichment

    return remediation_enrichment(labels)


def _effort(labels: object) -> "tuple[str | None, list[str] | None]":
    """Effort/ROI reasoning: the COST to fix and the payoff."""
    from app.engine.effort_reasoning import effort_enrichment

    return effort_enrichment(labels)


def _hypothesis(labels: object) -> "tuple[str | None, list[str] | None]":
    """Hypothesis reasoning: a falsifiable claim + how to TEST it."""
    from app.engine.hypothesis_mapper import hypothesis_enrichment

    return hypothesis_enrichment(labels)


# Fixed-order registry — a coherent reasoning narrative over an idea's converging
# signals: WHY (root cause) -> HOW THEY COMPOUND (interaction) -> WHAT IF
# UNADDRESSED (counterfactual) -> IN WHAT ORDER to fix (remediation) -> AT WHAT
# COST (effort/ROI) -> HOW TO VERIFY (hypothesis). The order is the order their
# clauses/facts are concatenated, so it is part of the deterministic contract.
# New reasoning lenses (each in its own engine module) append their pure enricher.
REASONING_ENRICHERS: list[Enricher] = [
    _abductive,
    _interaction,
    _counterfactual,
    _remediation,
    _effort,
    _hypothesis,
]


def enrich_converging(labels: object) -> "tuple[str | None, list[str] | None]":
    """Combine every registered enricher's output over the converging labels.

    Runs each enricher in registry order and concatenates the clauses (space
    separated) and extends the facts. Returns ``(None, None)`` when no enricher
    fires, so the idea is byte-identical to the un-enriched build. With a single
    enricher registered the output is exactly that enricher's own output.
    """
    clauses: list[str] = []
    facts: list[str] = []
    for enricher in REASONING_ENRICHERS:
        clause, extra = enricher(labels)
        if clause:
            clauses.append(clause)
        if extra:
            facts.extend(extra)
    if not clauses and not facts:
        return None, None
    return (" ".join(clauses) if clauses else None), (facts or None)
