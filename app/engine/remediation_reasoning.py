"""Remediation-sequencing enricher — orders converging concerns on an idea into
a SAFE remediation sequence grounded in a fixed risk ladder.

Apex's confluence ideas note that several concerns converge on a module, but a
bare list ("hub, untested, deep-nesting") says nothing about what to do FIRST.
Refactoring an untested hub before adding a safety-net test risks silent
regressions; tidying cosmetics before securing an ``eval`` wastes the window.

This enricher reads the converging signal labels and emits a one-line ordering
clause grounded in a four-phase ladder: STABILISE (add tests) before SECURE
(close risky constructs) before STRUCTURAL change (decouple/simplify) before
COSMETIC tidy. It is a pure function with the same contract as
``idea_reasoning._abductive``: it returns ``(clause, ["sequence: <clause>"])``
when there is a meaningful ordering, else ``(None, None)`` so the idea stays
byte-identical. Deterministic: no time, no random, fixed phase order.
"""

from __future__ import annotations

from typing import Any

# Fixed risk ladder. Each phase is (phase_key, action_template, {label: name}).
# The phase order IS the remediation order, and is part of the deterministic
# contract. ``action_template`` formats the comma-joined names of the present
# concerns in that phase into a short imperative fragment. A label not listed on
# any phase is simply skipped (it contributes no ordering signal).
_PHASES: list[tuple[str, str, dict[str, str]]] = [
    (
        "stabilise",
        "add a safety-net test first ({names})",
        {
            "untested": "untested",
            "shallow-coverage": "shallow-coverage",
        },
    ),
    (
        "secure",
        "close the risky construct ({names})",
        {
            "eval": "eval",
            "security-eval": "eval",
            "security-finding": "security-finding",
            "base-exception": "base-exception",
        },
    ),
    (
        "structural",
        "decouple the structure ({names})",
        {
            "hub": "hub",
            "dependency-hub": "hub",
            "symbol-hub": "hub",
            "god-class": "god-class",
            "deep-nesting": "deep-nesting",
            "complexity-hotspot": "complexity-hotspot",
        },
    ),
    (
        "cosmetic",
        "tidy up ({names})",
        {
            "doc-drift": "doc-drift",
            "unused-import": "unused-import",
            "modernization": "modernization",
            "modernization-imports": "modernization",
        },
    ),
]


def _phase_names(basis: dict[str, str], labels: list[str]) -> list[str]:
    """Names of the concerns present in ``labels`` for one phase, in label order.

    Order-preserving and de-duplicated: several labels can map to the same
    display name (``hub``/``symbol-hub`` → ``hub``), but a name is listed once.
    """
    names: list[str] = []
    for label in labels:
        name = basis.get(label)
        if name is not None and name not in names:
            names.append(name)
    return names


def _ordered_fragments(labels: list[str]) -> list[str]:
    """Per-phase imperative fragments for the phases that have present concerns.

    Walks ``_PHASES`` in ladder order, so the returned fragments are already the
    correct remediation sequence. A phase with no present concern is omitted.
    """
    fragments: list[str] = []
    for _key, template, basis in _PHASES:
        names = _phase_names(basis, labels)
        if names:
            fragments.append(template.format(names=", ".join(names)))
    return fragments


def remediation_enrichment(labels: object) -> "tuple[str | None, list[str] | None]":
    """Order converging concerns into a safe remediation sequence, or ``(None, None)``.

    Returns a one-line ``fix order: ...`` clause plus a single
    ``["sequence: <clause>"]`` fact when the converging labels touch at least two
    DIFFERENT phases of the risk ladder (only then is there an ordering to
    explain). A single-phase or single-label idea — which has no meaningful
    ordering — yields ``(None, None)`` and stays byte-identical. Deterministic.
    """
    seq: list[str] = [str(label) for label in (labels or []) if label is not None]
    fragments = _ordered_fragments(seq)
    if len(fragments) < 2:
        return None, None
    clause = (
        "fix order: "
        + ", then ".join(fragments)
        + " — stabilise before you change risky code"
    )
    return clause, [f"sequence: {clause}"]


# Re-export for callers that prefer an explicit type alias on the seam.
_Labels = Any
