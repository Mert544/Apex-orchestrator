"""The fractal facet vocabulary — pure data, extracted from the engine.

Extracted from idea_permutation.py, the engine's own top confluence target
(4 signals: hub, high-churn, co-change, single-author). Mechanical move:
idea_permutation re-exports every name, so the import surface is unchanged.
"""

from __future__ import annotations

_FACETS: dict[str, list[str]] = {
    "harden": ["input validation", "error handling", "resource limits", "secret handling"],
    "extend": ["new inputs", "new outputs", "configuration surface"],
    "test": ["edge cases", "failure modes", "property invariants"],
    "simplify": ["dead code", "duplicated logic", "deep nesting", "redundant control flow"],
    "document": ["public API", "usage examples", "failure semantics"],
    "integrate": ["data contract", "error propagation", "version skew"],
    "generalize": ["parameters", "extension points", "sensible defaults"],
    "observe": ["key metrics", "structured logs", "trace spans"],
    "decouple": ["dependency inversion", "seam interface", "import direction"],
    "verify": ["stated invariants", "boundary assertions", "proof obligations"],
    "fortify": ["null and empty inputs", "boundary and range limits", "the explicit error path"],
}

# Deeper-than-level-1 facets decompose any aspect into the engineering case
# split that recurs at every grain: the common path, the boundary, the failure.
# This is what makes the zoom *fractal* — the same decomposition applies however
# far down you go (bounded by ``facet_depth`` and by not repeating a case).
_FACET_CASES: list[str] = ["common case", "boundary case", "failure case"]

# Level-2 vocabulary: each level-1 aspect decomposes into *its own* concrete
# sub-concerns, so the zoom keeps carrying real engineering content ("harden →
# input validation → range and length bounds") instead of falling straight to a
# generic case triple. Self-similar but content-aware: the floor is _FACET_CASES
# once an aspect has no finer vocabulary of its own.
_FACET_SUBASPECTS: dict[str, list[str]] = {
    # harden
    "input validation": ["type and shape checks", "range and length bounds", "null or empty handling"],
    "error handling": ["catch specificity", "cleanup on failure", "error propagation"],
    "resource limits": ["size caps", "time and timeout bounds", "concurrency limits"],
    "secret handling": ["no plaintext at rest", "load from env or secret store", "rotation and scope"],
    # extend
    "new inputs": ["accepted formats", "validation of the new input", "backward compatibility"],
    "new outputs": ["output contract", "error and empty results", "consumer migration"],
    "configuration surface": ["sane defaults", "environment override", "validation of config"],
    # test
    "edge cases": ["empty input", "single element", "maximum size"],
    "failure modes": ["dependency unavailable", "partial or interrupted operation", "timeout"],
    "property invariants": ["idempotence", "ordering independence", "round-trip stability"],
    # simplify
    "dead code": ["unreferenced symbols", "unreachable branches", "redundant guards"],
    "duplicated logic": ["extract a shared helper", "parameterize the variants", "single source of truth"],
    "deep nesting": ["early returns", "guard clauses", "extract inner blocks"],
    # The "redundant control flow" aspect splits the same way the other simplify
    # aspects do — into its own concrete sub-concerns. Each L2 label below names a
    # family of always-equivalent-but-noisier control flow; the L3 ladder under it
    # names the specific tidy transform that collapses it. These phrasings are the
    # ones FACET_OBJECTIVE_MAP keys on, so a zoom here reaches a real develop
    # objective (simplify-bool-return, use-enumerate, remove-redundant-else, ...).
    "redundant control flow": ["redundant conditionals", "collapsible structure",
                               "unreachable or no-op statements"],
    # document
    "public API": ["signatures and types", "pre and postconditions", "worked examples"],
    "usage examples": ["happy path", "error handling", "edge usage"],
    "failure semantics": ["raised exceptions", "partial-failure behavior", "retry guidance"],
    # integrate
    "data contract": ["schema and types", "required vs optional fields", "evolution rules"],
    "error propagation": ["mapped error types", "retry vs fail-fast", "partial-failure surfacing"],
    "version skew": ["compatibility window", "feature detection", "graceful degradation"],
    # generalize
    "parameters": ["sensible defaults", "validation", "naming and types"],
    "extension points": ["the hook interface", "registration", "a default no-op"],
    "sensible defaults": ["the safe default", "the override path", "documented rationale"],
    # observe
    "key metrics": ["counters", "latency histograms", "error rates"],
    "structured logs": ["correlation ids", "level discipline", "no secret leakage"],
    "trace spans": ["span boundaries", "attributes", "error recording"],
    # ---- level-3 vocabulary: the level-2 sub-concerns decompose once more ----
    # Same lookup, one key deeper: the zoom stays content-aware for a third
    # level ("harden → resource limits → time and timeout bounds → deadline
    # propagation") before falling to the universal case split. Pure data —
    # _facet_vocab already keys on the most recent facet label.
    # harden ladder
    "type and shape checks": ["explicit type rejection", "nested structure shape", "coercion rules"],
    "range and length bounds": ["minimum and maximum values", "off-by-one at the limit", "unbounded growth"],
    "null or empty handling": ["None versus missing", "empty collection semantics", "whitespace-only input"],
    "catch specificity": ["narrowest exception type", "no silent swallowing", "log before re-raise"],
    "cleanup on failure": ["resource release", "temporary state removal", "rollback of partial writes"],
    "size caps": ["payload size limit", "collection growth bound", "file size ceiling"],
    "time and timeout bounds": ["connect versus read timeout", "retry backoff budget", "deadline propagation"],
    "concurrency limits": ["max parallel workers", "queue depth bound", "lock contention"],
    "no plaintext at rest": ["config files", "logs and tracebacks", "serialized state"],
    "load from env or secret store": ["startup-time validation", "missing secret behavior", "local development path"],
    "rotation and scope": ["expiry handling", "least-privilege scope", "revocation path"],
    # extend ladder
    "accepted formats": ["format detection", "malformed input rejection", "format version marker"],
    "backward compatibility": ["existing caller contract", "deprecation window", "migration shim"],
    "output contract": ["stable field ordering", "optional field semantics", "versioned output"],
    "error and empty results": ["empty versus error distinction", "partial result shape", "error detail surface"],
    "environment override": ["precedence order", "type parsing from strings", "unknown variable detection"],
    "validation of config": ["fail-fast at startup", "helpful error messages", "unknown key handling"],
    # test ladder
    "empty input": ["empty string versus None", "empty collection", "zero value"],
    "maximum size": ["the documented limit", "just past the limit", "memory pressure"],
    "dependency unavailable": ["connection refused", "name resolution failure", "slow versus down"],
    "partial or interrupted operation": ["mid-write interruption", "resume or restart", "duplicate side effects"],
    "timeout": ["timeout during connect", "timeout mid-stream", "cleanup after timeout"],
    "idempotence": ["repeated apply", "retry after partial success", "natural idempotency key"],
    "ordering independence": ["shuffled input", "stable output ordering", "concurrent arrival"],
    "round-trip stability": ["serialize then parse", "unicode and encoding", "precision loss"],
    # simplify ladder
    "unreferenced symbols": ["exported but unused", "dynamic references", "test-only usage"],
    "unreachable branches": ["constant conditions", "shadowed cases", "dead error paths"],
    "redundant guards": ["already-validated input", "duplicate null checks", "tautological conditions"],
    "extract a shared helper": ["naming the concept", "the parameter surface", "where it lives"],
    "parameterize the variants": ["the varying dimension", "flag versus strategy", "the default variant"],
    "single source of truth": ["which copy wins", "derivation direction", "drift detection"],
    "early returns": ["precondition exits", "error exits first", "happy path last"],
    "extract inner blocks": ["loop body extraction", "nested conditional extraction", "naming the step"],
    # redundant-control-flow ladder: each L3 phrase names the exact tidy transform
    # FACET_OBJECTIVE_MAP routes to, so the zoom lands on a real develop objective.
    "redundant conditionals": ["boolean return simplification",
                               "ternary that returns a boolean",
                               "redundant else after return"],
    "collapsible structure": ["collapsible nested conditionals",
                              "get-with-default lookup",
                              "manual index loop"],
    "unreachable or no-op statements": ["redundant pass statement",
                                        "statements after an unconditional return"],
    # document ladder
    "signatures and types": ["parameter meanings", "return type and None", "raised exceptions list"],
    "pre and postconditions": ["required state before", "guaranteed state after", "invariants preserved"],
    "worked examples": ["minimal runnable example", "realistic scenario", "a common mistake shown"],
    "raised exceptions": ["which type when", "recoverable versus fatal", "error message contract"],
    "partial-failure behavior": ["what completed", "what rolled back", "how callers detect it"],
    "retry guidance": ["safe-to-retry conditions", "backoff recommendation", "idempotency requirement"],
    # integrate ladder
    "schema and types": ["field types and nullability", "unknown field policy", "size limits"],
    "required vs optional fields": ["absence semantics", "default values", "validation timing"],
    "evolution rules": ["additive-only changes", "deprecation process", "version negotiation"],
    "mapped error types": ["upstream-to-domain mapping", "lost error detail", "wrapped cause chain"],
    "retry vs fail-fast": ["which errors retry", "the retry budget", "user-visible latency"],
    "compatibility window": ["oldest supported version", "the test matrix", "sunset policy"],
    # generalize ladder
    "the hook interface": ["arguments passed", "return contract", "error isolation"],
    "registration": ["discovery mechanism", "ordering of plugins", "duplicate registration"],
    "a default no-op": ["silent versus logged", "capability detection", "documented absence"],
    # observe ladder
    "counters": ["naming convention", "label cardinality", "reset semantics"],
    "latency histograms": ["bucket boundaries", "percentile targets", "outlier capture"],
    "error rates": ["error classification", "alert thresholds", "burn-rate window"],
    "correlation ids": ["generation point", "propagation across calls", "log field consistency"],
    "level discipline": ["error versus warning", "the noise budget", "debug gating"],
    "no secret leakage": ["redaction rules", "exception payloads", "URL and query params"],
    "span boundaries": ["the unit of work", "async continuation", "batch operations"],
}

# A facet's caveat should interrogate *its* sub-concern, not recite the lens's
# generic scenario. Keyed by theme (first keyword match wins) so the whole facet
# vocabulary is covered with a handful of rules. Order matters: most specific
# first. Empty match → fall back to the lens/operator caveat.
_FACET_CAVEAT_RULES: list[tuple[tuple[str, ...], str]] = [
    # Equivalence-preserving control-flow tidies (boolean returns, redundant else,
    # collapsible ifs, manual index loops, no-op pass, dead tail statements). These
    # multi-word keys match ONLY their own phrases, so they sit first — ahead of the
    # broad "default"/"redundant"/"unreachable" rules whose single words they'd
    # otherwise lose to.
    (("boolean return", "ternary that returns", "redundant else", "collapsible nested",
      "get-with-default", "manual index loop", "redundant pass", "redundant conditionals",
      "collapsible structure", "no-op statements", "statements after an unconditional"),
     "What behavior changes if this 'equivalent' rewrite is wrong about a side effect or falsy edge?"),
    (("null", "empty"), "What does this do with None, an empty value, or a missing key?"),
    (("timeout", "hang", "timeout bounds"), "What if it never returns — is there a bound, and what fires when it trips?"),
    (("concurren", "race"), "What if two callers reach this at the same moment?"),
    (("idempot",), "What breaks if this runs twice on the same input?"),
    (("ordering", "round-trip", "round trip", "invariant"), "What invariant silently breaks under reordering or a round trip?"),
    (("secret", "plaintext", "rotation", "credential", "leakage"), "What leaks if this is logged, committed, or read by the wrong caller?"),
    (("default",), "What goes wrong when the default is wrong for a particular caller?"),
    (("version", "compat", "skew", "degradation"), "What happens when the two sides are on different versions?"),
    (("metric", "log", "trace", "span", "counter", "histogram", "correlation"), "What failure currently happens with no signal to catch it?"),
    (("schema", "contract", "field", "type and shape", "signatures and types"), "What consumer breaks when this contract shifts?"),
    (("cleanup", "rollback", "partial", "interrupted", "failure case", "failure mode", "failure semantics"), "When this fails midway, what partial state or resource is left behind?"),
    (("error handling", "catch specificity", "error propagation"), "What exception type slips past — or gets silently swallowed by — this handler?"),
    (("dependency", "unavailable", "down"), "What if the thing this depends on is down or slow?"),
    (("dead code", "unreferenced", "unreachable", "redundant"), "What dynamic or reflective use makes this 'dead' code actually live?"),
    (("duplicat", "shared helper", "single source", "variants"), "What subtle difference between the copies does merging them erase?"),
    (("nesting", "early return", "guard clause", "extract", "inner block"), "What behavior shifts when the control flow is flattened?"),
    (("range", "bound", "length", "size", "maximum", "limit", "boundary"), "What happens at exactly the limit — and one step past it?"),
    (("registration", "hook", "extension point", "no-op"), "What if a second implementation registers, or none does?"),
    (("backward compat", "migration", "consumer"), "What existing caller breaks the moment this changes?"),
    (("common case", "happy path"), "What ordinary-looking input still slips through the normal path unhandled?"),
    (("edge case", "single element", "single", "maximum size"), "What rare shape — empty, single, or maximum — does the normal path skip?"),
    (("public api", "worked example", "usage example", "pre and postcondition"), "What contract do callers assume here that is written down nowhere?"),
    (("attribute", "error recording"), "What context is missing when this is read during an incident?"),
    (("naming and types", "parameter"), "What caller passes a plausible-but-wrong argument this accepts?"),
    (("validation", "checks"), "What malformed value passes the check but breaks downstream?"),
]


# The fixed permutation alphabet — the "abc" applied to every branch "a".
# Data-driven so breadth is tunable and plugins can extend it later.
