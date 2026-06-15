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
    # extend — the constructive "grow the contract" lens. Existing L2 lists are
    # EXTENDED (originals FIRST) with the concrete extension moves: add the missing
    # operation to the contract, support the next input shape, expose a
    # configuration seam. Appended, so the beam is undisturbed.
    "new inputs": ["accepted formats", "validation of the new input", "backward compatibility",
                   # added: the next shape the input surface should accept.
                   "the next input shape to support", "the optional argument to add"],
    "new outputs": ["output contract", "error and empty results", "consumer migration",
                    # added: the missing operation the contract should expose.
                    "the missing operation on the contract", "the new return shape"],
    "configuration surface": ["sane defaults", "environment override", "validation of config",
                              # added: the configuration seam to expose.
                              "the configuration seam to expose", "the feature flag to add"],
    # extend L3 ladders — each appended L2 move decomposes into concrete edits.
    "the next input shape to support": ["the new type or schema to accept",
                                        "the normalization to a common shape",
                                        "the rejection of the still-unsupported"],
    "the optional argument to add": ["the backward-compatible default",
                                     "the validation of the new argument",
                                     "the documentation of the new option"],
    "the missing operation on the contract": ["the operation signature",
                                              "the default or stub implementation",
                                              "the consumers to update"],
    "the new return shape": ["the additive field or variant",
                             "the empty and error result",
                             "the consumer migration path"],
    "the configuration seam to expose": ["the setting name and type",
                                         "the precedence and override order",
                                         "the safe default"],
    "the feature flag to add": ["the on and off behaviour",
                                "the default state",
                                "the removal or cleanup plan"],
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
    # integrate — the constructive "wire two sides together" lens. Existing L2
    # lists are EXTENDED (originals FIRST) with the concrete edge moves: define the
    # boundary contract, adapt the data shape at the seam, add the error/timeout
    # handling at the edge. Appended, so the beam is undisturbed.
    "data contract": ["schema and types", "required vs optional fields", "evolution rules",
                      # added: the boundary contract to pin and the shape to adapt.
                      "the boundary contract to define", "the data shape to adapt at the seam"],
    "error propagation": ["mapped error types", "retry vs fail-fast", "partial-failure surfacing",
                          # added: the error and timeout handling at the edge.
                          "the error handling at the edge", "the timeout and retry at the edge"],
    "version skew": ["compatibility window", "feature detection", "graceful degradation"],
    # integrate L3 ladders — each appended edge move decomposes into concrete edits.
    "the boundary contract to define": ["the request and response types",
                                        "the required versus optional fields",
                                        "the documented invariants of the seam"],
    "the data shape to adapt at the seam": ["the field mapping and renames",
                                            "the type and unit conversions",
                                            "the missing-field defaults"],
    "the error handling at the edge": ["the upstream-to-domain error mapping",
                                       "the partial-failure surfacing",
                                       "the fail-fast versus degrade choice"],
    "the timeout and retry at the edge": ["the connect and read timeout",
                                          "the retry budget and backoff",
                                          "the idempotency the retry needs"],
    # generalize — the constructive "lift the common shape" lens. Each existing
    # L2 list is EXTENDED (originals stay FIRST, never displaced) with the
    # concrete moves a generalization is actually made of: extract the shared
    # interface, parameterize the varying part, introduce a strategy/hook for the
    # difference, lift the common helper. Appending keeps the per-level beam
    # undisturbed — no new L1 aspect competes — so existing phrases keep emitting.
    "parameters": ["sensible defaults", "validation", "naming and types",
                   # added: the generalize moves that turn a fixed value into a knob.
                   "parameterize the varying part", "the shared interface to extract",
                   "lift the common helper"],
    "extension points": ["the hook interface", "registration", "a default no-op",
                         # added: the seam that lets callers vary behaviour.
                         "a strategy for the difference", "the variation point to name"],
    "sensible defaults": ["the safe default", "the override path", "documented rationale"],
    # generalize L3 ladders — the appended L2 moves decompose once more into the
    # concrete edits an engineer performs, then bottom out in the case split.
    "parameterize the varying part": ["the constant to promote to an argument",
                                      "the default that preserves today's behaviour",
                                      "the call sites to thread it through"],
    "the shared interface to extract": ["the common method signatures",
                                        "the protocol or abstract base",
                                        "the implementations to conform"],
    "lift the common helper": ["the duplicated block to name",
                               "where the helper should live",
                               "the parameters that capture the variants"],
    "a strategy for the difference": ["the strategy interface",
                                      "the dispatch or selection point",
                                      "the default strategy"],
    "the variation point to name": ["the hook signature",
                                    "the registration surface",
                                    "the no-op fallback"],
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
    "extract a shared helper": ["naming the concept", "the parameter surface", "where it lives",
                                "a fully-returning duplicate block"],
    "parameterize the variants": ["the varying dimension", "flag versus strategy", "the default variant"],
    "single source of truth": ["which copy wins", "derivation direction", "drift detection"],
    "early returns": ["precondition exits", "error exits first", "happy path last"],
    # The "guard clauses" sub-aspect splits into the two distinct guard shapes:
    # the leading precondition (handled by extract-guard-clause, reached via the
    # "early return"/"guard clause" keys) and the TRAILING guard after setup —
    # an ``if`` wrapping the tail of a function after some preamble — which is the
    # sibling shape the standalone guard-clause objective owns.
    "guard clauses": ["a trailing guard after setup", "the leading precondition",
                      "one exit per branch"],
    "extract inner blocks": ["loop body extraction", "nested conditional extraction", "naming the step"],
    # redundant-control-flow ladder: each L3 phrase names the exact tidy transform
    # FACET_OBJECTIVE_MAP routes to, so the zoom lands on a real develop objective.
    # This wave EXTENDS each L2 group's L3 list with more provably-equivalent-but-
    # noisier shapes (doubled negation, len-vs-zero, or-chains, legacy formatting,
    # redundant constructors, magic literals, ...). They hang off the EXISTING L2
    # groups rather than a new top-level aspect on purpose: adding no new L2 node
    # keeps the per-level beam undisturbed, so the original control-flow phrases
    # still reach L3 (guarded by test_idea_facets::test_engine_emits_every_new_l3).
    # The original phrases stay FIRST in each list so their emission is preserved.
    "redundant conditionals": ["boolean return simplification",
                               "ternary that returns a boolean",
                               "redundant else after return",
                               # added: condition-level value-preserving rewrites.
                               "a double negation",
                               "a negated equality comparison",
                               "length compared to zero"],
    "collapsible structure": ["collapsible nested conditionals",
                              "get-with-default lookup",
                              "manual index loop",
                              # added: or-chains, comparison chains, and nested
                              # statements that collapse into one equivalent form.
                              "an isinstance or-chain",
                              "a startswith or endswith or-chain",
                              "an unchained comparison range",
                              "nested with statements",
                              "a self-referential augmented assignment",
                              "a comprehension wrapped in another call"],
    "unreachable or no-op statements": ["redundant pass statement",
                                        "statements after an unconditional return",
                                        # added: legacy surface idioms and magic
                                        # literals — equivalent shapes a tidy sweeps.
                                        "percent-style string format",
                                        "explicit format-spec call",
                                        "str.format placeholder call",
                                        "set from a list literal",
                                        "dict built by a loop",
                                        "implicitly concatenated literals",
                                        "a magic literal worth naming"],
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
    # decouple ladder: the "import direction" aspect zooms into the import block's
    # own hygiene — imports nothing references, and an unordered import block. Both
    # L3 phrases route (via FACET_OBJECTIVE_MAP) to the import-hygiene develop
    # objectives (remove-unused-imports, sort-imports), so a zoom here lands on a
    # real campaign rather than the generic case split.
    "import direction": ["an unused import", "an unsorted import block"],
    # decouple — the constructive "break the knot" lens. Its two structural L1
    # aspects ("dependency inversion", "seam interface") previously had NO L2
    # vocabulary, so zooming "Decouple X → dependency inversion" fell straight to
    # the generic common/boundary/failure case split — no concrete sub-direction.
    # We give EACH of those two existing L1 facet nodes its own L2 ladder of the
    # concrete moves a decoupling is actually made of: invert the dependency,
    # introduce an interface at the seam, move the shared type to a neutral module.
    # CRUCIAL for the beam: these are new keys for facet phrases that ALREADY emit
    # at L1 — no new L1/L2 node is introduced, so nothing competes in any per-level
    # beam and the existing decouple phrases keep emitting in their existing order.
    # We only replace the generic case-split floor with content-aware sub-aspects.
    "dependency inversion": ["invert the dependency",
                             "introduce an interface at the seam",
                             "move the shared type to a neutral module"],
    "seam interface": ["introduce an interface at the seam",
                       "move the shared type to a neutral module",
                       "narrow the seam to a single contract"],
    # decouple L3 ladders — each L2 move decomposes once more into the concrete
    # edits an engineer performs, then bottoms out in the universal case split.
    "invert the dependency": ["the abstraction both sides depend on",
                              "the concrete wiring to push to the edge",
                              "the construction or injection point"],
    "introduce an interface at the seam": ["the methods the seam actually uses",
                                           "the protocol or abstract base to name",
                                           "the implementations to conform"],
    "move the shared type to a neutral module": ["the type the two modules share",
                                                 "the neutral home it should live in",
                                                 "the imports to redirect"],
    "narrow the seam to a single contract": ["the one responsibility to keep",
                                             "the incidental coupling to remove",
                                             "the callers to migrate"],
    # ---- constructive-lens L3 deepening: existing L2 facets that previously fell
    # to the generic case split now carry their own concrete sub-directions. Each
    # key below is a facet phrase that ALREADY emits at L2 for its lens; adding an
    # L3 entry only enriches what zooming INTO it offers next — it introduces no
    # new L1/L2 node, so the per-level beam (and every pinned phrase's order) is
    # untouched. The floor stays the case split for anything still without finer
    # vocabulary; we are just lowering that floor for the constructive lenses.
    # generalize: round out the "parameters" and "sensible defaults" sub-aspects.
    "validation": ["the precondition the parameter must meet",
                   "the rejection of the out-of-range value",
                   "the error the caller sees on a bad argument"],
    "naming and types": ["the intent-revealing parameter name",
                         "the precise type or annotation",
                         "the unit or invariant the type encodes"],
    "the safe default": ["the value that preserves today's behaviour",
                         "the least-surprising choice for a new caller",
                         "the documented reason it is safe"],
    "the override path": ["how a caller supplies a non-default",
                          "the precedence when several sources set it",
                          "the validation of the override"],
    "documented rationale": ["why this default and not another",
                             "the scenario where it is wrong",
                             "the knob to reach for instead"],
    # extend: round out the remaining "grow the contract" sub-aspects.
    "validation of the new input": ["the accepted shape to assert",
                                    "the malformed input to reject",
                                    "the error the new path returns"],
    "consumer migration": ["the deprecation window to announce",
                           "the compatibility shim to keep old callers working",
                           "the cut-over the consumers follow"],
    "sane defaults": ["the value that needs no configuration",
                      "the override the power user reaches for",
                      "the documented rationale for the choice"],
    # integrate: round out the remaining "wire the seam" sub-aspects.
    "partial-failure surfacing": ["what completed versus what did not",
                                  "how the caller detects the partial state",
                                  "the compensating or cleanup action"],
    "feature detection": ["the capability to probe before use",
                          "the negotiation when both sides differ",
                          "the fallback when the feature is absent"],
    "graceful degradation": ["the reduced-capability path",
                             "the signal that degradation kicked in",
                             "the recovery when the far side returns"],
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
    # Surface-level / expression-level tidies (legacy formatting idioms, doubled
    # negation, len-vs-zero, isinstance/startswith or-chains, magic literals,
    # collapsible statements). Multi-word keys match only their own phrases, so
    # they sit ahead of the broad single-word rules below.
    (("string format", "format placeholder", "format-spec", "string literals",
      "concatenated literals", "list literal", "dict built", "double negation",
      "negated equality", "isinstance or-chain", "startswith", "endswith",
      "compared to zero", "unchained comparison", "magic literal",
      "augmented assignment", "nested with", "comprehension wrapped",
      "trailing guard", "fully-returning duplicate"),
     "What behavior changes if this 'equivalent' rewrite is wrong about a side effect or evaluation order?"),
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
