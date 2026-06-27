"""Risk tiers — how much evidence an autonomous fix must earn before applying.

The transform catalog can only grow into riskier territory if the risk is
priced explicitly. Three tiers:

  - **Tier 0** — semantics-preserving or additive-only (docstrings, import
    tidying, ``== None`` → ``is None``, new test files, a scaffolded CI
    workflow): auto-apply under the normal verify/rollback loop. A brand-new
    file that touches no existing source cannot change behaviour, so it earns
    Tier 0 the same way a new test file does. A pure-ANNOTATION security flag
    (``flag_tls_verify``/``flag_pickle_loads``/``flag_sql_injection``) is Tier 0
    too — it inserts a single ``# SECURITY`` comment and changes no executable
    code, so it cannot need a covering test (see ``tier_for_transform``).
  - **Tier 1** — behavior-adjacent (security rewrites like ``eval`` →
    ``literal_eval``, mutable-default fixes): auto-apply **only when the test
    suite actually covers the target** — either it already references the
    module, or the test-first shield just created a characterization test.
    No coverage and no shield → the fix is *blocked*, not gambled.
  - **Tier 2** — design-level work (``design_task``): never auto-applied;
    surfaced as proposals for a human or a drafting agent.

The tier is part of every apply record, so the proof-of-fix artifact shows
not just what was done but what class of risk it carried.
"""

from __future__ import annotations

TIER_BY_ACTION: dict[str, int] = {
    # Tier 0 — semantics-preserving / additive-only
    "create_test_stub": 0,
    "add_docstring": 0,
    "organize_imports": 0,
    "modernize_comparisons": 0,
    # Additive-only: a new CI workflow file touches no existing source.
    "add_ci": 0,
    # Tier 1 — behavior-adjacent rewrites
    "harden_security": 1,
    "fix_mutable_defaults": 1,
    # Wrapping a static raw-SQL literal in SQLAlchemy text() makes the call the
    # API actually accepts — behaviour-adjacent, so it earns the coverage gate
    # (needs a covering test via the shield; withheld when uncovered, never
    # auto-applied blind). Dynamic SQL is refused by the transform and stays a
    # flag, so this never lands an unprovable fix.
    "sql_text_wrap": 1,
    # Tier 2 — design-level (not auto-applied anyway; recorded for honesty)
    "design_task": 2,
}

# An action type we've never classified is treated as behavior-adjacent:
# new transforms must *earn* Tier 0, not default into it.
_UNKNOWN_TIER = 1

# Pure-ANNOTATION security flags — Tier 0 by the SAME rule as a new test file or
# a docstring: they insert ONE ``# SECURITY (...)`` comment above the call site
# and change NO executable code (the dangerous call is left byte-for-byte intact,
# the AST of the runnable program is unchanged). A comment cannot change
# behaviour, so it cannot need a covering test — gating it behind Tier 1's
# "requires a covering test" rule (and the network-calling shield that gate
# spins up) means a real finding on an untested module is neither applied nor
# surfaced. These three are routed through the ``harden_security`` action, which
# STAYS Tier 1 for its behaviour-CHANGING siblings (eval -> literal_eval,
# yaml.load -> safe_load): only the comment-only transform earns Tier 0, resolved
# per-fix from the concrete transform_type, never from the action type.
ANNOTATION_FLAG_TRANSFORMS: frozenset[str] = frozenset({
    "flag_tls_verify",     # requests/httpx verify=False — annotate, don't flip
    "flag_pickle_loads",   # pickle.loads — annotate, no safe drop-in
    "flag_sql_injection",  # f-string into execute() — annotate, needs bound params
})


def tier_for(action_type: str) -> int:
    """The risk tier of an action type (unknown actions are cautious Tier 1)."""
    return TIER_BY_ACTION.get(action_type, _UNKNOWN_TIER)


def tier_for_transform(transform_type: str | None, action_type: str) -> int:
    """The EFFECTIVE risk tier of a concrete fix.

    A pure-annotation security flag (``flag_tls_verify``/``flag_pickle_loads``/
    ``flag_sql_injection``) is Tier 0 regardless of the carrying action: it only
    inserts a ``# SECURITY`` comment, so it is additive/semantics-preserving and
    must not earn the coverage gate. Every other fix falls back to its action's
    tier — so a behaviour-changing harden (eval -> literal_eval) stays Tier 1.
    """
    if transform_type in ANNOTATION_FLAG_TRANSFORMS:
        return 0
    return tier_for(action_type)


# The objective-compiler ``Move.operator`` strings whose change is
# BEHAVIOUR-ADJACENT (Tier 1) — a green suite that merely IMPORTS the module
# (``coverage == "module"``) does NOT prove the new behaviour; only a test that
# exercises the changed function (``coverage == "function"``) does. Two families:
#   * security REWRITES — ``harden`` (eval -> literal_eval, yaml.load ->
#     safe_load, os.system -> subprocess, …) literally changes what the call
#     does;
#   * code SYNTHESIS — operators that mint a real executable BODY where there was
#     a stub / missing symbol (implement-stub, tdd-implement, the doctest/JSDoc
#     synthesisers, protocol scaffolding, dunder synthesis, test strengthening,
#     cover-gaps) introduce behaviour the suite must actually run to vouch for;
#   * ``raise_from`` rewrites a re-raise into ``raise X from err`` — a real
#     (if small) runtime traceback-chaining change.
# Every OTHER compiler operator is a provably semantics-preserving refactor or
# idiom (modernize, sort-imports, drop never-read param, inline/extract, dedup,
# the doc-surface comment inserts, …): a test that references the module is a
# sound proof, so those stay Tier 0. New behaviour-changing operators MUST be
# added here (the soundness audit + the covered-only matrix test guard this).
BEHAVIOUR_CHANGING_OPERATORS: frozenset[str] = frozenset({
    "harden",
    "raise_from",
    "implement_stub", "tdd_implement", "implement_from_doctest",
    "js_tdd_implement", "js_implement_from_jsdoc",
    "scaffold_from_protocol", "synthesize_dunders",
    "strengthen_tests", "cover_gaps",
})


def tier_for_operator(operator: str) -> int:
    """The risk tier of an objective-compiler ``Move.operator``.

    Tier 1 for the behaviour-adjacent operators (security rewrites + body
    synthesis + ``raise_from`` — see ``BEHAVIOUR_CHANGING_OPERATORS``), where a
    mere module import can't vouch for the change; Tier 0 for every other
    operator, which is a semantics-preserving refactor / idiom / doc-surface
    insert that a module-referencing test soundly proves. Pure + deterministic."""
    return 1 if operator in BEHAVIOUR_CHANGING_OPERATORS else 0


def coverage_verifies(tier: int, coverage: str) -> bool:
    """Does ``coverage`` let a green suite actually VOUCH for a tier-``tier``
    change? The SINGLE honest verdict shared by every apply path (the bridge's
    ``apply_step`` and the develop-core ``apply_rename`` / ``compile_objective``),
    so the two sweeps can never disagree (the covered-only matrix invariant).

    A green run only verifies what it exercised:
      * ``test-change`` — only test files changed (they ARE the suite);
      * Tier 0 (semantics-preserving / additive) — a test that references the
        module (``module``) or names the change (``function``) suffices;
      * Tier 1+ (behaviour-adjacent) — require ``function``: a mere import (a
        smoke-import shield) is NOT a test of the changed behaviour and must
        never green-light it.

    ``none`` (no test references the change at all) never verifies anything.
    """
    if coverage == "test-change":
        return True
    if tier <= 0:
        return coverage in ("function", "module")
    return coverage == "function"
