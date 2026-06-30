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
                                              # the TDD case: the function a RED
                                              # test already calls but that does
                                              # not exist yet (tdd-implement).
                                              "the function the red test calls",
                                              "the failing jest test whose function to write",
                                              "the worked example to satisfy",
                                              # the JS/TS image of the worked example:
                                              # a JS/TS stub whose contract is its OWN
                                              # JSDoc @example and that NO jest test
                                              # references (js-implement-from-jsdoc).
                                              "the jsdoc example whose function to write",
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
    "property invariants": ["idempotence", "ordering independence", "round-trip stability",
                            # added: a seeded fault the suite still passes on — a
                            # real blind spot the strengthen-tests objective closes
                            # with a double-gated mutant-killing assertion.
                            "a surviving mutant the tests miss",
                            # added: an Enum whose member values are PROVABLY all
                            # distinct — enforce-enum-unique locks that invariant with
                            # @enum.unique (a no-op today, a loud import-time error on a
                            # future duplicate alias). Appended, originals still lead.
                            "an enum to enforce unique values on",
                            # added: a dispatch over a PROVABLY-CLOSED set (an in-module
                            # Enum / Literal[...] / bool) missing an arm and lacking a
                            # catch-all — complete-match-exhaustiveness appends a loud
                            # sentinel so the silent fall-through becomes loud (total
                            # dispatch = an exhaustiveness invariant). Originals lead.
                            "a closed-set dispatch missing an exhaustiveness arm",
                            # added: an UNTESTED exported JS/TS function whose current
                            # behaviour ought to be pinned — js-cover-gaps writes the
                            # FIRST jest characterization test for it (the JS sibling of
                            # cover-gaps), calling it with synthesized inputs and pinning
                            # the real return, env-reproducibility-gated. Appended, so the
                            # originals still lead and emit first.
                            "the untested jest function to characterize",
                            # added: an ALREADY-tested exported JS/TS function whose
                            # EXISTING jest test (its MINED witnesses) misses a
                            # single-token mutant — js-strengthen-tests (the LITE
                            # mined-witness sibling of strengthen-tests) lands ONE
                            # env-gated characterization assertion that kills it,
                            # strengthening against the MINED witnesses (NOT a full-suite
                            # blind spot). Appended last, so the originals still lead.
                            "the jest mutant the mined witnesses miss"],
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
    # version skew is the natural home for the constructive "sequencing / what
    # lands first" lens. Across the WHOLE facet set, no lens named the DEPENDENCY
    # ORDER between pieces of work: every other lens names WHAT to build or how to
    # make it safe/observable, none named what must ship BEFORE a change and what
    # shipping it UNBLOCKS downstream. version skew already coordinates two sides
    # across time, so the L2 list is EXTENDED (originals stay FIRST, never
    # displaced) with the two ordering moves: the prerequisite that must land
    # first, and the downstream work this change unblocks. Appended, so the beam
    # is undisturbed — no new L1 aspect competes and the pinned phrases keep
    # emitting in their existing order.
    "version skew": ["compatibility window", "feature detection", "graceful degradation",
                     # added: the work-ordering moves a coordinated change needs.
                     "the prerequisite change that must land first",
                     "the downstream work this change unblocks",
                     # added: the MIGRATION moves a coordinated change needs. The
                     # whole facet set's only migration vocabulary lived under the
                     # EXTEND lens (new inputs/outputs), i.e. how to grow ADDITIVE
                     # surface — nothing named how the EXISTING callers cross a
                     # version-skewed change safely. "version skew" is the natural
                     # home: it is the one aspect whose job is two sides on different
                     # versions. Distinct from the sequencing moves above (order
                     # between pieces of work) — these name how a caller moves from
                     # old to new without breaking: a deprecation shim, a
                     # backward-compatible default, and a staged rollout across
                     # cohorts. Appended (originals stay FIRST), so the per-level
                     # beam is undisturbed.
                     "the deprecation shim that keeps old callers working",
                     "the backward-compatible default for existing callers",
                     "the staged rollout across caller cohorts"],
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
    # integrate sequencing L3 ladders — each ordering move decomposes once more
    # into the concrete planning decisions an engineer makes, then bottoms out in
    # the universal case split. The "prerequisite" move asks what blocks the change
    # and how to land that first; the "unblocks" move asks what becomes possible
    # once it ships and how to hand that off.
    "the prerequisite change that must land first": ["the dependency that blocks this work today",
                                                     "the smaller change to land ahead of it",
                                                     "the check that the prerequisite is in place"],
    "the downstream work this change unblocks": ["the follow-up this change makes possible",
                                                 "the consumer ready to build on it once it ships",
                                                 "the handoff note that names what is now unblocked"],
    # integrate migration L3 ladders — each migration move decomposes once more
    # into the concrete decisions an engineer makes to carry the existing callers
    # across the change, then bottoms out in the universal case split. The "shim"
    # move asks what old shape to keep alive and when to drop it; the "default"
    # move asks how to preserve today's behaviour while offering the new path; the
    # "rollout" move asks who gets it first, what is watched, and when to back out.
    "the deprecation shim that keeps old callers working": ["the old signature the shim must preserve",
                                                            "the warning that tells a caller to migrate",
                                                            "the removal date the shim is retired on"],
    "the backward-compatible default for existing callers": ["the default that reproduces the prior behaviour for a caller",
                                                             "the opt-in switch a caller flips for the new behaviour",
                                                             "the caller migration the default lets you defer"],
    "the staged rollout across caller cohorts": ["the first caller cohort to receive it",
                                                 "the metric watched as the rollout widens",
                                                 "the rollback trigger if a cohort regresses"],
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
                         "a strategy for the difference", "the variation point to name",
                         # added: the INVERSE of an extension point — a class PROVABLY
                         # never subclassed (a leaf), which add-final seals with
                         # `@typing.final` to document/enforce the intent. Appended,
                         # originals still lead.
                         "a class to seal as final",
                         # added: the method-level sibling — a METHOD provably never
                         # overridden anywhere, which seal-final-method seals with
                         # `@typing.final` (the per-method inverse of an extension
                         # point). Appended, originals still lead.
                         "the method to seal as final",
                         # added: the JAVA sibling of add-final — a PRIVATE Java field
                         # provably never reassigned anywhere in its file, which
                         # java-finalize-field seals with the `final` modifier (a
                         # runtime no-op the field already obeys; the false-final risk
                         # is closed by a whole-file assignment scan over a parse-only
                         # tree + a re-parse fact-set-identity check, no Maven/JUnit
                         # run). Appended last, so the originals still lead and emit
                         # first.
                         "the never-reassigned java field to finalize"],
    "sensible defaults": ["the safe default", "the override path", "documented rationale"],
    # generalize L3 ladders — the appended L2 moves decompose once more into the
    # concrete edits an engineer performs, then bottom out in the case split.
    "parameterize the varying part": ["the constant to promote to an argument",
                                      "the default that preserves today's behaviour",
                                      "the call sites to thread it through"],
    "the shared interface to extract": ["the common method signatures",
                                        "the protocol or abstract base",
                                        "the implementations to conform",
                                        # added: scaffold a concrete implementer
                                        # for a declared-but-unimplemented Protocol.
                                        "the protocol stub to scaffold"],
    "lift the common helper": ["the duplicated block to name",
                               "where the helper should live",
                               "the parameters that capture the variants"],
    "a strategy for the difference": ["the strategy interface",
                                      "the dispatch or selection point",
                                      "the default strategy"],
    "the variation point to name": ["the hook signature",
                                    "the registration surface",
                                    "the no-op fallback"],
    # observe — the constructive "close the measurement loop" lens. Every existing
    # observe sub-aspect names a signal to EMIT (a counter, a log field, a span),
    # but across the WHOLE observe lens nothing named what the signal is actually
    # FOR: instrumentation with no question to answer, no baseline to compare
    # against, and no action when it trips is shelf-ware. So each observe L1 list is
    # EXTENDED (originals stay FIRST, never displaced) with the three measurement
    # moves that turn a raw signal into a decision: the question this should answer,
    # the baseline or threshold that makes it actionable, and the action taken when
    # it crosses that line. Appended, so the per-level beam is undisturbed — no new
    # L1 aspect competes and the pinned emit-the-signal phrases keep their order.
    "key metrics": ["counters", "latency histograms", "error rates",
                    # added: the measurement-loop moves a metric needs to be useful.
                    "the question this metric should answer",
                    "the baseline or threshold that makes it actionable",
                    "the action taken when it crosses the threshold"],
    "structured logs": ["correlation ids", "level discipline", "no secret leakage",
                        # added: what a log line is FOR once it is emitted.
                        "the question a search of these logs should answer",
                        "the action taken when the log pattern appears"],
    "trace spans": ["span boundaries", "attributes", "error recording",
                    # added: the latency question a span is meant to settle.
                    "the latency question this span should answer",
                    "the baseline or threshold that makes it actionable"],
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
    "single source of truth": ["which copy wins", "derivation direction", "drift detection",
                               "two sibling functions to merge"],
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
                                        "a magic literal worth naming",
                                        # added: a boilerplate __init__ that does
                                        # nothing but copy params onto self — the
                                        # dataclassify objective collapses it to a
                                        # @dataclass (behaviour-equivalent). Appended,
                                        # so the originals still lead and emit first.
                                        "a boilerplate constructor to make a dataclass",
                                        # added: a @dataclass whose fields are NEVER
                                        # mutated anywhere — the freeze-dataclass
                                        # objective adds frozen=True (immutable +
                                        # hashable, behaviour-preserving), proving no
                                        # whole-project mutation first. Appended, so
                                        # the originals still lead and emit first.
                                        "a never-mutated dataclass to freeze",
                                        # added: a class whose instance attributes are
                                        # PROVABLY closed — the add-slots objective
                                        # splices __slots__ naming the proven field set
                                        # (the structural dual of freeze-dataclass),
                                        # proving across the WHOLE project that the slot
                                        # set is a superset of every stored attribute.
                                        # Appended last, so the originals still lead and
                                        # emit first.
                                        "the closed-attribute class to give slots",
                                        # added: a non-@dataclass plumbing class MISSING
                                        # __repr__/__eq__ — the synthesize-dunders objective
                                        # splices the canonical __repr__/__eq__/__hash__
                                        # @dataclass itself emits over the proven pure-copy
                                        # field set (dataclassify's sibling for classes
                                        # dataclassify must refuse), gated by an
                                        # inherited-__eq__ refusal. Appended last, so the
                                        # originals still lead and emit first.
                                        "the repr and eq to synthesize from fields",
                                        # added: a non-@dataclass class that defines __eq__
                                        # AND exactly one of __lt__/__le__/__gt__/__ge__ but
                                        # is MISSING the other three — the seal-total-ordering
                                        # objective lands @functools.total_ordering, which
                                        # fills the three absent comparison operators from the
                                        # one the author wrote plus __eq__ (the comparison-dunder
                                        # sibling of synthesize-dunders), runtime-additive and
                                        # statically gated. Appended last, so the originals still
                                        # lead and emit first.
                                        "the comparison operators to complete from one",
                                        # added: a project's own @dataclass that does NOT set
                                        # order= and defines NONE of __lt__/__le__/__gt__/__ge__
                                        # itself — the add-dataclass-order objective lands
                                        # order=True on the decorator, generating the four
                                        # comparison operators from the field tuple (the
                                        # dataclass sibling of freeze-dataclass and
                                        # seal-total-ordering), runtime-additive and statically
                                        # gated (stdlib-dataclass provenance + no existing
                                        # comparison dunder). Appended last, so the originals
                                        # still lead and emit first.
                                        "the dataclass to make orderable",
                                        # added: a non-@dataclass class that defines __eq__ in
                                        # its OWN body but does NOT define __hash__ and is NOT
                                        # already deliberately unhashable — the seal-hashable-eq
                                        # objective lands the canonical
                                        # `def __hash__(self): return hash((self.f1, ...))` over
                                        # the proven pure-copy field set, RESTORING set/dict-key
                                        # usability where defining __eq__ made instances
                                        # unhashable (__hash__ = None implicitly). The __hash__
                                        # sibling of synthesize-dunders; runtime-additive and
                                        # statically gated (no base -> the hash contract is the
                                        # class's own). Appended last, so the originals still
                                        # lead and emit first.
                                        "the hash to restore from the eq fields"],
    # document ladder
    "signatures and types": ["parameter meanings", "return type and None", "raised exceptions list",
                             # added: the package's public re-export surface — the
                             # wire-exports develop objective wires it (`__init__`
                             # re-exports + `__all__`). Appended, so the originals
                             # still lead and emit in their existing order.
                             "the public re-export surface to wire",
                             # added: a public function with NO docstring — the
                             # document-signature develop objective lands one (param
                             # names + a PROVEN `Returns: <type>`), refusing when
                             # the return type is not provable. Appended, so the
                             # originals still lead and emit in their order.
                             "the public signature to document",
                             # added: a module that USES type annotations but lacks
                             # `from __future__ import annotations` — the
                             # add-from-future-annotations objective lands the
                             # one-line lazy-annotation import (insert fresh, or
                             # widen an existing `__future__` import). Appended, so
                             # the originals still lead and emit in their order.
                             "annotations to make lazy with a future import",
                             # added: a leaf module with no `__all__` — wire-module-exports
                             # declares `__all__` == the current default star set
                             # (behaviour-identical). Appended, originals still lead.
                             "the module public surface to declare",
                             # added: an EXPORTED JS/TS function/const-arrow with no
                             # leading JSDoc — the document-export-jsdoc objective
                             # lands a minimal JSDoc (`@param` names + a TS
                             # `@returns {T}` read verbatim), the JS/TS sibling of
                             # document-signature, refusing a name+param-only
                             # restatement. Appended, so the originals still lead
                             # and emit in their order.
                             "the exported signature to document in jsdoc",
                             # added: a DEFINED-but-unexported public JS/TS
                             # function/const-arrow in a clean-ESM module — the
                             # js-wire-exports objective lands the ONE missing ESM
                             # `export` keyword (a pure export-surface grow proven by
                             # an in-driver re-parse name-superset), the JS/TS sibling
                             # of wire-exports, refusing a CJS/`export default` module.
                             # Appended, so the originals still lead and emit first.
                             "the unexported public function to export",
                             # added: an EXPORTED JS/TS function/const-arrow whose
                             # parameters carry DECLARED types but with no leading
                             # JSDoc — the js-document-param-types objective lands a
                             # JSDoc whose `@param {T} name` lines carry the declared
                             # types read verbatim (the missing half of
                             # document-export-jsdoc), refusing a name-only/untyped
                             # restatement. Appended, so the originals still lead and
                             # emit first.
                             "the exported parameter types to document in jsdoc",
                             # added: an EXPORTED JS/TS function/const-arrow whose
                             # body throws a PROVEN constructor set (literal
                             # `throw new <Identifier>(...)`) but with no leading
                             # JSDoc — the document-raises-jsdoc objective lands a
                             # JSDoc whose `@throws {Ctor}` lines name the distinct
                             # thrown constructors read verbatim in source order (the
                             # failure-contract sibling of document-export-jsdoc and
                             # js-document-param-types), refusing a zero-throw or
                             # unprovable-throw shape. Appended, so the originals still
                             # lead and emit first.
                             "the thrown error types to document in jsdoc",
                             # added: an EXPORTED PLAIN-JS function/const-arrow with no
                             # leading JSDoc and NO declared TS return type whose
                             # return type is PROVABLE from its own literal `return`
                             # statements — the js-document-returns-inferred objective
                             # lands a JSDoc with one `@returns {T}` line (the literal
                             # kind read verbatim: boolean/string/number/Array/Object/
                             # ctor), the case document-export-jsdoc can't serve (it
                             # needs a DECLARED TS return). DISJOINT by the typed-vs-
                             # untyped split (fires only when no TS return is declared),
                             # refusing a non-literal/void/null/heterogeneous return.
                             # Appended, so the originals still lead and emit first.
                             "the inferred return type to document in jsdoc",
                             # added: a DOCUMENTED public Python function with no
                             # `-> T` annotation whose docstring records no return —
                             # the pin-return-type objective splices ONE `Returns: <T>`
                             # line into the existing docstring, the <T> from the same
                             # proven return oracle infer-type-hints lands as `-> T`
                             # (the document-signature-but-DOCUMENTED sibling: it fires
                             # where document-signature refuses, on a function that
                             # already has a docstring). Refuses an undocumented /
                             # already-annotated / generator / ambiguous function and a
                             # docstring that already states a return. Appended, so the
                             # originals still lead and emit first.
                             "the documented return type to pin",
                             # added: a DOCUMENTED public Python function that DOES
                             # carry an explicit `-> T` annotation whose docstring
                             # records no return — the document-returns objective
                             # splices a faithful return section into the existing
                             # docstring rendering the DECLARED annotation `T`
                             # VERBATIM, MATCHING the docstring's convention (Google
                             # `Returns:` / Sphinx `:returns:`+`:rtype:` / the Google
                             # default for plain prose). The annotation-sourced,
                             # style-matching sibling of pin-return-type (which reads
                             # the INFERRED oracle on an UN-annotated function);
                             # mutually exclusive by the annotation predicate. Refuses
                             # `-> None`/`NoReturn` (incl. aliases), a generator
                             # return, an @overload/property setter, and a docstring
                             # already recording a return in ANY convention. Appended
                             # after its inferred-oracle sibling, so the originals lead.
                             "the annotated return type to document",
                             # added: a DOCUMENTED public Python function carrying at
                             # least one DECLARED parameter annotation whose docstring
                             # records no parameters — the document-param objective
                             # splices a faithful `Args:` section into the existing
                             # docstring, one `name (TYPE):` line per declared-annotated
                             # parameter, the type read VERBATIM off `arg.annotation`,
                             # MATCHING the docstring's convention (Google `Args:` /
                             # Sphinx `:param:`+`:type:` / the Google default). The
                             # Python mirror of js-document-param-types and the
                             # input-contract sibling of document-returns; inherits the
                             # signature-restatement honesty gate (lands only when a
                             # param is annotated, a line only for annotated params).
                             # Refuses an undocumented function, an @overload/property
                             # setter, an unreadable *args/**kwargs annotation, and a
                             # docstring already recording params in ANY convention
                             # (incl. the PARTIAL case — refuses whole). Appended after
                             # its return sibling, so the originals lead.
                             "the parameter types to document",
                             # added: a DOCUMENTED public Python CLASS with at least one
                             # class-level annotated field (`ast.AnnAssign`) whose
                             # docstring records no attributes — the document-attributes
                             # objective splices a faithful `Attributes:` section into
                             # the existing docstring, one `name (TYPE)` line per
                             # class-level annotated field, the type read VERBATIM off
                             # `field.annotation`, MATCHING the docstring's convention
                             # (Google `Attributes:` / Sphinx `:ivar:`+`:vartype:` / the
                             # Google default). The CLASS-attribute sibling of
                             # document-returns; selects only `ast.ClassDef`, so it never
                             # collides with the function-scoped doc objectives. Refuses
                             # an undocumented class, a class with no class-level
                             # annotated field (instance-only `self.x` is inference, out
                             # of scope), an all-unreadable class, and a docstring already
                             # recording attributes in ANY convention (incl. the PARTIAL
                             # case — refuses whole). Appended, so the originals lead.
                             "the class attributes to document",
                             # added: a DOCUMENTED public Python GENERATOR (a `yield` in
                             # its own scope) carrying a subscripted iterator/generator
                             # return annotation whose docstring records no yield — the
                             # document-yields objective splices a faithful `Yields:`
                             # section into the existing docstring rendering the ELEMENT
                             # type (the first subscript arg) VERBATIM, MATCHING the
                             # docstring's convention (Google `Yields:` / Sphinx
                             # `:yields:`+`:ytype:` / the Google default). The GENERATOR
                             # sibling of document-returns; fires exactly where
                             # document-returns refuses (its `_GENERATOR_RETURNS`
                             # refuse-head set), so a generator gets a `Yields:` and never
                             # a `Returns:` (mutually exclusive). Refuses a non-generator,
                             # a non-iterator / missing / bare-unsubscripted annotation,
                             # an undocumented function, and a docstring already recording
                             # a yield in ANY convention. Appended, so the originals lead.
                             "the yielded type to document"],
    "pre and postconditions": ["required state before", "guaranteed state after", "invariants preserved"],
    "worked examples": ["minimal runnable example", "realistic scenario", "a common mistake shown",
                        # added: the package's USAGE.md generated from its public
                        # API — the generate-usage-doc objective lands it (sigs +
                        # docstring summaries + verified doctest examples). Appended,
                        # so the originals still lead and emit in their existing order.
                        "the package usage doc to generate",
                        # added: a function's unenforced ``>>>`` examples — the
                        # pin-doctest objective lands a gating test that EXECUTES them
                        # so the suite keeps them honest. Appended, so the originals
                        # still lead and emit in their existing order.
                        "the unenforced doctest examples to pin"],
    "raised exceptions": ["which type when", "recoverable versus fatal", "error message contract",
                          # added: a public function whose body raises a PROVEN
                          # escaping ``raise <ErrorName>(...)`` set but whose
                          # docstring records none of it — the document-raises
                          # objective lands a ``Raises:`` block naming the distinct
                          # escaping exceptions read verbatim in source order (the
                          # Python sibling of document-raises-jsdoc), refusing a
                          # zero-raise or unprovable-raise shape. Appended, so the
                          # originals still lead and emit first.
                          "the raised exceptions to document",
                          # added: the JAVA sibling of document-raises — a method that
                          # DECLARES a ``throws`` clause but carries NO Javadoc, which
                          # java-document-throws documents with a fresh Javadoc block of
                          # one ``@throws <Type>`` line per DECLARED checked-exception
                          # type (the throws clause verbatim, NOT inferred from
                          # ``throw new X()``). A Javadoc is a COMMENT, so the edit is
                          # behaviour-identical (a re-parse fact-set-identity check, no
                          # Maven/JUnit run); an already-documented method is refused.
                          # Appended after its Python sibling, so the originals lead.
                          "the undocumented java throws clause to document",
                          # added: a ``raise X(...)`` inside an ``except E as err:``
                          # handler with no ``from`` — which discards the original
                          # traceback (B904). The raise-from objective appends
                          # ``from err`` so the re-raised exception is chained to its
                          # cause (behaviour-preserving: the same exception is raised,
                          # only __cause__ changes), refusing when the handler has no
                          # ``as`` binding to chain from. Appended last, so the
                          # originals still lead and emit first.
                          "the unchained re-raise to chain from its cause"],
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
    # observe measurement-loop L3 ladders — each appended measurement move
    # decomposes once more into the concrete decisions an engineer makes to close
    # the loop, then bottoms out in the universal case split. Distinct phrasings so
    # no ladder loops on a shared key, and none reuses a literal metric token.
    "the question this metric should answer": ["the decision this number informs",
                                               "the owner who reads it",
                                               "the dashboard or query it lives on"],
    "the baseline or threshold that makes it actionable": ["the normal range observed today",
                                                           "the value that means trouble",
                                                           "the window the threshold is measured over"],
    "the action taken when it crosses the threshold": ["the page or ticket it raises",
                                                       "the runbook step it points to",
                                                       "the automatic response it can trigger"],
    "the question a search of these logs should answer": ["the incident question to reconstruct",
                                                          "the field to filter or group on",
                                                          "the time range that bounds the search"],
    "the action taken when the log pattern appears": ["the alert this pattern should raise",
                                                      "the responder it routes to",
                                                      "the follow-up it queues for review"],
    "the latency question this span should answer": ["the slow path to attribute time to",
                                                     "the percentile that matters here",
                                                     "the comparison against the budget"],
    # decouple ladder: the "import direction" aspect zooms into the import block's
    # own hygiene — imports nothing references, and an unordered import block. Both
    # L3 phrases route (via FACET_OBJECTIVE_MAP) to the import-hygiene develop
    # objectives (remove-unused-imports, sort-imports), so a zoom here lands on a
    # real campaign rather than the generic case split.
    "import direction": ["an unused import", "an unsorted import block",
                         # added: repeated from-same-module imports the
                         # merge-duplicate-imports objective collapses into one
                         # (binding-identical). Appended, originals still lead.
                         "the duplicate from-imports to merge",
                         # added: an existing module-level __all__ whose names are out
                         # of order — sort-dunder-all sorts + de-duplicates it
                         # (behaviour-identical). Appended, originals still lead.
                         "the module __all__ to sort",
                         # added: an existing module-level __all__ that REPEATS an
                         # entry — dedup-dunder-all removes the duplicate, preserving
                         # first-appearance order (behaviour-identical — __all__
                         # membership is a set). Appended, originals still lead.
                         "the duplicate __all__ entries to remove"],
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
    # decouple L4: "the incidental coupling to remove" (an L3 phrase that already
    # emits under "narrow the seam to a single contract") deepens once more into the
    # CONCRETE, EXECUTABLE first slice of that removal — promoting a class's
    # self-free methods to @staticmethod. THE OVER-CLAIM GUARD (Autonomous-39 W3a):
    # this phrase routes (via FACET_OBJECTIVE_MAP) to the promote-staticmethod
    # objective, which promotes ONLY the methods that provably never touch `self` —
    # a real coupling-surface reduction that changes no call site. It does NOT
    # reduce the method count or split responsibilities (the full decomposition
    # stays a design task), so the phrase names the @staticmethod promotion, not a
    # decomposition. This is a new key for an L3 phrase that ALREADY emits — no new
    # L1/L2 node is introduced, so the per-level beam and every pinned phrase's
    # order are untouched; it only lowers the case-split floor under this one L3
    # phrase. Appended as the sole sub-aspect, so the case split still follows.
    "the incidental coupling to remove": ["the self-free methods to promote to staticmethod"],
    # verify — the constructive "make it reversible" lens. The three verify L1
    # aspects ("stated invariants", "boundary assertions", "proof obligations")
    # previously had NO L2 vocabulary, so zooming "Verify X → proof obligations"
    # fell straight to the generic common/boundary/failure case split — no concrete
    # sub-direction. The angle the whole facet set was MISSING is rollback/safety:
    # *before* a change ships, what is the undo path if it turns out wrong, and what
    # signal confirms it is working? "proof obligations" is the natural home — the
    # strongest obligation a change must meet is that it can be safely backed out.
    # We give it (and the two sibling verify aspects) their own L2 ladders of the
    # concrete moves that make a change reversible and observable: define the undo
    # path, gate it behind a safe toggle, and name the signal that confirms it.
    # CRUCIAL for the beam: these are new keys for verify phrases that ALREADY emit
    # at L1 — no new L1/L2 node competes in any per-level beam, so the existing
    # verify phrases keep emitting in their existing order; we only replace the
    # generic case-split floor with content-aware sub-aspects.
    "proof obligations": ["the undo path if this turns out wrong",
                          "the safe toggle that gates the change",
                          "the signal that confirms the change is working"],
    "stated invariants": ["the invariant to write down as an assertion",
                          "the precondition a caller must already meet",
                          "the postcondition the change must preserve"],
    "boundary assertions": ["the assertion at the entry of the change",
                            "the assertion at the exit of the change",
                            "the check that fails loudly when the boundary is crossed"],
    # verify L3 ladders — each L2 move decomposes once more into the concrete edits
    # an engineer performs, then bottoms out in the universal case split.
    "the undo path if this turns out wrong": ["the inverse operation that backs it out",
                                              "the saved prior state to restore from",
                                              "the steps to reverse, in order"],
    "the safe toggle that gates the change": ["the off state that keeps today's behaviour",
                                              "the default the toggle ships in",
                                              "the cleanup once the change is trusted"],
    "the signal that confirms the change is working": ["the before-and-after to compare",
                                                       "the threshold that means success",
                                                       "the alert when it regresses"],
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
                         "the unit or invariant the type encodes",
                         "the fluent self-return type to annotate"],
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
    # fortify — the constructive "cost / effort sequencing" lens. The whole facet
    # set previously had NO angle on *how much* of a change to do now versus later:
    # every other lens names WHAT to build, none names the cheapest order to build
    # it in. The fortify lens — whose operator already asks for the SMALLEST guard
    # that removes an edge-input failure — is the natural home for that angle. Its
    # three L1 aspects ("null and empty inputs", "boundary and range limits",
    # "the explicit error path") previously had NO L2 vocabulary, so zooming
    # "Fortify X -> the explicit error path" fell straight to the generic
    # common/boundary/failure case split — no concrete sub-direction. We give EACH
    # of those existing L1 aspects its own L2 ladder of the cost/effort moves a
    # sequenced hardening is actually made of: the cheapest first slice that earns
    # its keep, what to defer to a later pass, and the smallest probe that would
    # catch a regression before it ships.
    # CRUCIAL for the beam: these are new keys for fortify phrases that ALREADY
    # emit at L1 — no new L1/L2 node is introduced, so nothing competes in any
    # per-level beam and the existing fortify phrases keep emitting in their
    # existing order; we only replace the generic case-split floor with
    # content-aware, cost-aware sub-aspects.
    "null and empty inputs": ["the cheapest first slice that earns its keep",
                              "the rarer shape to defer to a later pass",
                              "the smallest probe that would catch a regression"],
    "boundary and range limits": ["the cheapest first slice that earns its keep",
                                  "the costlier guard to defer to a later pass",
                                  "the smallest probe that would catch a regression"],
    "the explicit error path": ["the cheapest first slice that earns its keep",
                                "the harder failure to defer to a later pass",
                                "the smallest probe that would catch a regression"],
    # fortify L3 ladders — each cost/effort move decomposes once more into the
    # concrete decisions an engineer makes, then bottoms out in the case split.
    "the cheapest first slice that earns its keep": ["the one input that breaks most often today",
                                                     "the guard that is a few lines, not a rewrite",
                                                     "the slice to land before touching the rest"],
    "the rarer shape to defer to a later pass": ["the shape that is real but seldom hit",
                                                 "the follow-up to file once the first slice lands",
                                                 "the marker left so the deferred work is not lost"],
    "the costlier guard to defer to a later pass": ["the guard whose payoff does not justify it yet",
                                                    "the follow-up to file once the first slice lands",
                                                    "the marker left so the deferred work is not lost"],
    "the harder failure to defer to a later pass": ["the failure that needs a broader change",
                                                    "the follow-up to file once the first slice lands",
                                                    "the marker left so the deferred work is not lost"],
    "the smallest probe that would catch a regression": ["the one assertion that proves the slice holds",
                                                         "the fast check to wire into the test path",
                                                         "the cheapest watch on the way back in"],
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
    (("prerequisite", "unblock", "downstream", "lands first", "land first", "handoff"), "What stays blocked, or ships out of order, if this lands before its prerequisite?"),
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
