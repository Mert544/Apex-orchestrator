"""Bridge from a fractal FACET (a concern phrase) to the DEVELOP OBJECTIVE
that resolves it.

The brain's fractal decomposition speaks in concern phrases — "extract a
shared helper", "parameterize", "modernize", "dead code". The hands run
verified develop campaigns keyed by objective name — ``dedup``,
``dead-params``, ``modernize``, ``remove-dead-code``, ``shrink-functions``,
``inline-helpers``. This module is the deterministic dictionary between the
two halves: given a facet phrase, name the objective whose campaign would
actually resolve it.

Every value here MUST be a real objective the compiler can pursue (see
``objective_compiler.available_objectives``); a test asserts the map can't
drift out of sync. No wiring into brief/develop in this module — it is just
the mapping library. Deterministic, stdlib-only.
"""

from __future__ import annotations

# Concern phrase (lowercased substring) -> resolving develop objective.
#
# Keys are drawn from the facet/concern vocabulary (see
# ``facet_evidence._LENGTH_KEYS``, ``_SIGNATURE_KEYS``, ``_COMPLEXITY_KEYS``,
# and the detector rule phrases). Matching is substring-based, so a key fires
# whenever it appears anywhere inside a phrase. Order matters: the first key
# (in insertion order) whose text is a substring of the phrase wins, so the
# more specific phrasings are listed before the broader ones they contain.
FACET_OBJECTIVE_MAP: dict[str, str] = {
    # Near-duplicate variants: blocks identical but for a few leaves are lifted
    # into ONE parameterized helper. These phrasings (the "parameterize the
    # variants" sub-aspect of "duplicated logic") describe the varying axis, so
    # they route to the near-dup objective rather than the parameter-list one.
    # MUST precede the broader ``parameterize`` key below, which they contain.
    "parameterize the variants": "dedup-parameterized",
    "the varying dimension": "dedup-parameterized",
    "flag versus strategy": "dedup-parameterized",
    "the default variant": "dedup-parameterized",

    # Duplication: the concern is "say it once".
    "extract a shared helper": "dedup",
    "single source of truth": "dedup",
    "duplicated logic": "dedup",
    "shared helper": "dedup",
    "copy-paste": "dedup",

    # Over-long functions: the concern is "split it into smaller units". The
    # "extract this block out" sub-aspects of deep nesting fold in here too —
    # naming an inner loop/conditional as its own function IS shrinking.
    "smaller unit": "shrink-functions",
    "extract inner": "shrink-functions",
    "nested conditional extraction": "shrink-functions",
    "loop body extraction": "shrink-functions",
    "deep nesting": "shrink-functions",
    "long function": "shrink-functions",

    # Flatten control flow: turn a nested if/else into early-exit guards. The
    # "early returns / guard clauses" sub-aspects of deep nesting name exactly
    # what the extract-guard-clause transform does (distinct from shrinking the
    # whole function — here the body stays, the nesting goes).
    "guard clause": "extract-guard-clause",
    "early return": "extract-guard-clause",
    "precondition exits": "extract-guard-clause",
    "error exits first": "extract-guard-clause",

    # Signatures / API surface: the concern is the parameter list itself.
    "unused parameter": "dead-params",
    "parameterize": "dead-params",
    "api surface": "dead-params",
    "interface": "dead-params",

    # Surface modernization: legacy idioms, ``== None`` comparisons. The
    # detector's own wordings (the tidy-debt findings the modernize objective
    # sweeps: dead f-string prefixes, ``== None``, ``dict()``/``list()``) route
    # here too, so an evidenced finding becomes the campaign that clears it.
    "none comparison": "modernize",
    "compare to none": "modernize",
    "f-string without placeholders": "modernize",
    "use a literal": "modernize",
    "modernize": "modernize",

    # Negated membership/identity: ``not (a in b)`` / ``not (a is b)`` should be
    # ``a not in b`` / ``a is not b``. The detector phrases this as "negating the
    # comparison", which the fix-not-in-is transform resolves. (Kept off the bare
    # ``is not`` substring, which also appears in the None-comparison finding.)
    "negating the comparison": "fix-not-in-is",

    # Dead / unreachable code. The "unreachable branches" and "redundant guards"
    # sub-aspects of dead code (constant/tautological conditions, shadowed cases,
    # duplicate null checks) are all provably-never-run or always-true — exactly
    # what the dead-code scan flags.
    "unreachable": "remove-dead-code",
    "dead error paths": "remove-dead-code",
    "constant conditions": "remove-dead-code",
    "tautological conditions": "remove-dead-code",
    "duplicate null checks": "remove-dead-code",
    "shadowed cases": "remove-dead-code",
    "redundant guard": "remove-dead-code",
    "dead code": "remove-dead-code",

    # Needless indirection: fold a one-call helper back into its caller.
    "indirection": "inline-helpers",
    "inline": "inline-helpers",

    # Missing tests: the ``test`` lens's concerns ("edge cases", "failure modes",
    # "property invariants" and their case sub-aspects) all name behaviour that
    # ought to be pinned by a test. The cover-gaps objective IS that action — it
    # writes a characterization test for an untested module — so a test-lens
    # facet becomes the campaign that closes the coverage gap.
    "edge case": "cover-gaps",
    "failure mode": "cover-gaps",
    "property invariant": "cover-gaps",
    "round-trip stability": "cover-gaps",
    "ordering independence": "cover-gaps",
    "idempotence": "cover-gaps",
}


def facet_to_objective(phrase: str) -> str | None:
    """The develop objective that resolves ``phrase``, or ``None``.

    Lowercases ``phrase`` and returns the first objective whose key is a
    substring of it (insertion order, so specific phrasings win)."""
    p = phrase.lower()
    for key, objective in FACET_OBJECTIVE_MAP.items():
        if key in p:
            return objective
    return None


def facets_to_objectives(phrases: list[str]) -> list[str]:
    """The objectives ``phrases`` map to: de-duplicated and order-preserved.

    Phrases that map to nothing are skipped; an objective named by more than
    one phrase appears once, at the position of its first occurrence."""
    out: list[str] = []
    for phrase in phrases:
        objective = facet_to_objective(phrase)
        if objective is not None and objective not in out:
            out.append(objective)
    return out


def render_facet_plan_markdown(phrases: list[str]) -> str:
    """Render "these facets map to these develop objectives" as a table."""
    lines = ["# Facet → develop plan", ""]
    rows = [(phrase, facet_to_objective(phrase)) for phrase in phrases]
    mapped = [(phrase, obj) for phrase, obj in rows if obj is not None]

    if not mapped:
        lines.append("_No facet maps to a develop objective._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Facet | Objective |")
    lines.append("| --- | --- |")
    for phrase, obj in mapped:
        lines.append(f"| {phrase} | `{obj}` |")

    objectives = facets_to_objectives(phrases)
    lines.append("")
    lines.append("Resolves to: " + ", ".join(f"`{o}`" for o in objectives) + ".")
    lines.append("")
    return "\n".join(lines)
