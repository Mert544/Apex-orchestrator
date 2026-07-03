"""The reviewable objective-soundness manifest constants — a dependency-free leaf.

These two hand-curated tables are the single source of truth for HOW each develop
objective is sound. They live in THIS leaf (imports nothing from the engine) so that
BOTH consumers can read them without forming an import cycle:

* :mod:`app.engine.soundness_audit` re-exports them and runs the forward/reverse
  tripwires + the adversarial corpus over them (the standing ``--soundness`` denetçi);
* :func:`app.engine.develop_registry.register` reads :data:`SOUNDNESS_STRATEGY` at
  registration time to REFUSE any objective that has not declared its soundness
  argument here (the autonomy trust-floor).

``develop_registry`` is imported (transitively) by ``objective_compiler``, which
``soundness_audit`` imports — so ``develop_registry`` importing ``soundness_audit``
would close a static import cycle the architecture grade penalises. Keeping the
manifest in a leaf with NO engine imports breaks that: every reader depends only on
this module, and this module depends on nobody. Stdlib-only, zero-token, deterministic.

The strings are reviewable prose for a human auditor, not parsed by any check; only
their PRESENCE per name is asserted.
"""

from __future__ import annotations

__all__ = ["SOUNDNESS_STRATEGY", "SCOPE_VERIFY_ALLOWLIST"]


# --- the reviewable per-objective soundness-STRATEGY manifest -----------------
#
# The analogue of north_star_audit.OBJECTIVE_MANIFEST: a hand-curated dict literal
# recording, per objective, WHICH soundness sub-case (S2, §1 of the spec) it relies
# on to be safe. The registry carries no soundness metadata, so this is the single
# hand-curated source of truth — and the FORWARD tripwire makes it impossible to
# leave a registered objective undeclared (a new objective MUST state its soundness
# argument here before the soundness check can pass, AND before it can register).
#
# Strategy vocabulary (the S2 sub-cases of a SOUND develop-objective):
#   runtime-noop+<scan>        — @final/@typing.final: a pure runtime no-op, made
#                                honest by a tests-INCLUSIVE over-approximate scan.
#   behavior-identical         — the rewrite cannot change observable behavior
#                                (an idiom modernizer, a star-set-preserving __all__,
#                                a type hint, a docstring, a __future__ import).
#   suite-catches+<scan>       — a runtime mismatch the green suite catches (and
#                                apply_rename rolls back), plus a static refusal scan.
#   additive+oracle-gate       — lands only NEW test code, gated by the env/order/
#                                clock-reproducible value-oracle gate (never pins an
#                                env-fragile oracle; refuses when none is provable).
#   oracle-gated-scaffold      — lands new code/docs gated by an import/usage oracle
#                                in a throwaway copy, then the full suite on top.
SOUNDNESS_STRATEGY: dict[str, str] = {
    # --- CONCRETE: lands working code ---------------------------------------
    "add-final": "runtime-noop+used-as-base-scan(tests-incl)",
    "java-finalize-field": "java-final-modifier-add(runtime-noop)+private-field-never-reassigned-whole-file-scan+reparse-fact-set-identical-or-refuse(no-suite-needed)",
    "java-final-parameter": "java-final-modifier-add(runtime-noop)+parameter-never-reassigned-single-method-body-scan+reparse-fact-set-identical-or-refuse(no-suite-needed)",
    "java-final-local": "java-final-modifier-add(runtime-noop)+direct-block-statement-local-with-initializer-never-reassigned-single-method-body-scan+reparse-fact-set-identical-or-refuse(no-suite-needed)+refuse-for/enhanced-for/try-resources/no-initializer",
    "finalize-module-constant": "typing.Final-annotation-add(runtime-noop,CPython-does-not-enforce)+top-level-UPPER_SNAKE-literal-constant-never-rebound-whole-project-scan(tests-incl)+reparse-or-refuse(no-suite-needed)+refuse-rebound/already-Final/non-literal/non-top-level/tuple-unpack/multi-target/annotation-only/ambiguous-Final-binding+in-place-mutation-is-fine(Final-forbids-rebinding-not-mutation)",
    "java-document-throws": "java-javadoc-throws-from-declared-throws-clause-verbatim+reparse-fact-set-identical-or-refuse(no-suite-needed)+refuse-already-documented",
    "java-document-param": "java-javadoc-param-from-declared-params-verbatim+reparse-fact-set-identical-or-refuse(no-suite-needed)+refuse-already-documented/no-param",
    "java-document-returns": "java-javadoc-return-from-declared-return-type-source-span-verbatim+reparse-fact-set-identical-or-refuse(no-suite-needed)+refuse-void/constructor/already-documented/unreadable-span",
    "seal-final-method": "runtime-noop+transitive-subclass-scan(tests-incl)",
    "wire-module-exports": "behavior-identical-or-star-consumer-scan(tests-incl)",
    "wire-exports": "oracle-gated-scaffold(import-oracle)+additive-init",
    "js-wire-exports": "esm-export-keyword-add(pure-surface-grow)+reparse-exported-name-superset-or-refuse(no-suite-needed)",
    "freeze-dataclass": "suite-catches-runtime+own-module-mutation-scan",
    "add-slots": "behavior-identical-storage+whole-project-closed-attribute-superset-proof-or-refuse",
    "dataclassify": "suite-catches-runtime+behavior-preserving-rewrite",
    "add-from-future-annotations": "behavior-identical-future-import",
    "add-functools-wraps": "behavior-identical(metadata-only)+decorator-closure-shape-proof+refuse-already-wrapped/ambiguous-callee",
    "infer-type-hints": "behavior-identical-annotation-only",
    "annotate-self-returns": "behavior-identical-annotation-only+self/cls-class-bound-forward-ref",
    "document-signature": "behavior-identical-docstring-only",
    "document-raises": "behavior-identical-docstring-only+raises-from-literal-raise-Name-verbatim+escape-only(stop-at-nested-scope,try-with-except-refuses)",
    "document-returns": "behavior-identical-docstring-only+returns-from-declared-annotation-verbatim+refuse-None/NoReturn/generator/overload/setter/already-documented",
    "document-param": "behavior-identical-docstring-only+args-from-declared-annotation-verbatim+refuse-no-declared-param-type/already-documented(incl-partial)/overload/setter/unreadable-collector",
    "document-attributes": "behavior-identical-docstring-only+attributes-from-class-level-annotation-verbatim+refuse-no-annotated-field/instance-only-self-assign/already-documented(incl-partial)/all-unreadable",
    "document-yields": "behavior-identical-docstring-only+yields-element-from-subscripted-iterator-generator-annotation-verbatim+refuse-non-generator/no-recognised-annotation/bare-unsubscripted/already-documented",
    "pin-return-type": "behavior-identical-docstring-only+returns-from-proven-return-oracle",
    "document-export-jsdoc": "jsdoc-leading-trivia-insert+reparse-identical-or-refuse(no-suite-needed)",
    "js-document-param-types": "jsdoc-leading-trivia-insert+declared-param-types-verbatim+reparse-identical-or-refuse(no-suite-needed)",
    "document-raises-jsdoc": "jsdoc-leading-trivia-insert+throws-types-from-literal-new-verbatim+reparse-identical-or-refuse(no-suite-needed)",
    "js-document-returns-inferred": "jsdoc-leading-trivia-insert+returns-from-literal-return-verbatim+reparse-exports-identical-or-refuse(no-suite-needed)+disjoint-from-declared-return-doc(fires-only-when-return_type-None)",
    "generate-usage-doc": "oracle-gated-scaffold(doc-only-no-source-change)",
    "pin-doctest": "additive+oracle-gate(doctest-captured-then-verified)",
    "scaffold-from-protocol": "oracle-gated-scaffold(instantiation-oracle)+impact-scoped-derived-from-gate",
    "strengthen-tests": "additive+env-reproducible-oracle-gate",
    "js-strengthen-tests": "additive-apex-owned-test+mined-witness-divergence(survival-vs-MINED-jest-witnesses,NO-per-mutant-suite-run)+env-reproducible-oracle-gate(js-execution-capture,varied-TZ/cwd/HOME/TMPDIR+wallclock)+green-witness-baseline-or-refuse+never-persist-mutant(in-memory-only)+never-clobber-existing-buyer-test+forced-jest-gate-RED→GREEN+byte-rollback",
    "cover-gaps": "additive+env-reproducible-oracle-gate",
    "implement-stub": "additive-fill+impact-scoped-suite-gate",
    "tdd-implement": "additive-fill+impact-scoped-suite-gate",
    "implement-from-doctest": "additive-fill+doctest-oracle+impact-scoped-suite-gate",
    "js-tdd-implement": "js-failing-test-RED→GREEN-or-refuse+byte-rollback",
    "js-implement-from-jsdoc": "js-jsdoc-example-RED→GREEN-or-refuse+byte-rollback",
    "js-cover-gaps": "additive-characterization-test+env-reproducible-oracle-gate(js-execution-capture,varied-TZ/cwd/HOME/TMPDIR+wallclock)+ast-forbidden-call-refusal+sound-input-slice(zero-arg/all-primitive-typed/all-literal-default-or-refuse)+never-clobber-existing-test+forced-jest-gate-RED→GREEN+byte-rollback",
    "enforce-enum-unique": "runtime-noop(@unique)+static-value-collision-refusal",
    "complete-match-exhaustiveness": "runtime-additive(unreached-arm)+static-closed-set-refusal",
    "synthesize-dunders": "suite-catches-runtime+canonical-total-dunders-over-proven-fields+inherited-eq-refusal",
    "seal-total-ordering": "runtime-additive(filled-comparison-ops)+single-defined-order-op+eq-present+static-refusal",
    "seal-hashable-eq": "runtime-additive(restored-__hash__)+own-body-eq-present+no-__hash__-defined+canonical-over-proven-fields+static-refusal",
    "add-dataclass-order": "runtime-additive(generated-order-ops)+stdlib-dataclass-provenance+no-existing-comparison-dunder+static-refusal",
    "harden": "suite-catches-runtime+security-rewrite(tier1)+behavior-identical-annotation(tier0)+engine-decline-on-unsafe",
    "raise-from": "behavior-preserving-traceback-chain-only+raise-from-except-binding-verbatim+refuse-when-no-binding",
    "modernize-typing": "behavior-identical-annotation-only(PEP585/604)+future-import-gated(has_future_annotations-or-refuse)+annotation-slot-only(AnnAssign/arg/returns-never-expression-position)+typing-binding-scan-or-refuse(star/alias-ambiguity)+shadow-scan-or-refuse(non-import-binding)+Tuple[()]/string-literal-refuse+union-flatten-sound+reparse-or-refuse(no-suite-needed)",
    # --- TIDY: behavior-preserving idiom rewrites ---------------------------
    "modernize": "behavior-preserving-idiom",
    "simplify-bool-return": "behavior-preserving-idiom",
    "simplify-comprehension": "behavior-preserving-idiom",
    "simplify-bool-comparison": "behavior-preserving-idiom",
    "simplify-len-comparison": "behavior-preserving-idiom",
    "simplify-negated-comparison": "behavior-preserving-idiom",
    "simplify-ternary-bool": "behavior-preserving-idiom",
    "simplify-dict-get": "behavior-preserving-idiom",
    "extract-constant": "behavior-preserving-idiom",
    "remove-unused-imports": "behavior-preserving-idiom",
    "sort-imports": "behavior-preserving-idiom",
    "sort-dunder-all": "behavior-preserving-idiom(__all__-order-irrelevant)",
    "dedup-dunder-all": "behavior-preserving-idiom(__all__-membership-is-a-set)+refuse-dynamic/non-string/multiple/comment-loss",
    "remove-dead-code": "behavior-preserving-idiom",
    "remove-double-negation": "behavior-preserving-idiom",
    "remove-pointless-pass": "behavior-preserving-idiom",
    "remove-redundant-else": "behavior-preserving-idiom",
    "remove-redundant-fstring": "behavior-preserving-idiom",
    "remove-unreachable-after-terminator": "behavior-preserving-idiom",
    "dedup": "behavior-preserving-idiom",
    "dedup-parameterized": "behavior-preserving-idiom",
    "dedup-parameterized-total-return": "behavior-preserving-idiom",
    "dedup-total-return": "behavior-preserving-idiom",
    "dedup-guarded-return": ("behavior-preserving-idiom(sentinel-projection:"
                             "unforgeable-object()-marker+verbatim-block-lift)"
                             "+definite-assignment-of-live-out-or-refuse"
                             "+hazard-refuse(yield/await/global/nonlocal/"
                             "nested-def/escaping-jump/super/__class__/del)"),
    "dead-params": "behavior-preserving-idiom",
    "shrink-functions": "behavior-preserving-idiom",
    "inline-helpers": "behavior-preserving-idiom",
    "chain-comparison": "behavior-preserving-idiom",
    "collapse-startswith": "behavior-preserving-idiom",
    "combine-augmented-assign": "behavior-preserving-idiom",
    "combine-nested-with": "behavior-preserving-idiom",
    "dict-comprehension": "behavior-preserving-idiom",
    "extract-guard-clause": "behavior-preserving-idiom",
    "guard-clause": "behavior-preserving-idiom",
    "merge-isinstance": "behavior-preserving-idiom",
    "merge-nested-if": "behavior-preserving-idiom",
    "fix-assert-tuple": "behavior-preserving-idiom",
    "fix-not-in-is": "behavior-preserving-idiom",
    "fold-literal-string-concat": "behavior-preserving-idiom",
    "format-to-fstring": "behavior-preserving-idiom",
    "fstring-convert": "behavior-preserving-idiom",
    "percent-to-fstring": "behavior-preserving-idiom",
    "set-literal": "behavior-preserving-idiom",
    "use-enumerate": "behavior-preserving-idiom",
    "merge-duplicate-imports": "behavior-preserving-idiom",
    "promote-staticmethod": "behavior-preserving-decouple(self-free-method→@staticmethod-stays-class-attribute,no-call-site-change)+refuse-uses-self/decorated/dunder/classmethod/non-self-first/super/name-in->1-class(override-MRO)/name-as-string-literal(dynamic)/nested-class/fixture-non-library",
}

# The ONLY objectives allowed to set ``ObjectiveSpec.scope_verify=True`` (Layer A3).
# Impact-scoped gating is a deliberate, audited exception: each of these has a
# legitimately-RED baseline suite on a multi-module project (an unfilled stub, an
# unwired package, an un-strengthened test file), so the FULL-suite gate would let
# an UNRELATED still-red module veto a correct change. Each runs the IMPACTED tests
# (which genuinely pass after the change, so the "verified" stamp stays honest), and
# the full suite remains the commit-time backstop (``scripts/verify.py``). Silently
# widening this set would let a NEW objective dodge full-suite gating — so a
# ``scope_verify=True`` objective NOT listed here is a FAIL.
SCOPE_VERIFY_ALLOWLIST: frozenset[str] = frozenset({
    "implement-stub", "tdd-implement", "strengthen-tests", "wire-exports",
    "implement-from-doctest", "js-tdd-implement", "js-implement-from-jsdoc",
    # js-cover-gaps lands a brand-new ``<dir>/__tests__/<stem>.cover.test.<ext>`` that
    # no other test imports, so on a multi-module JS project an UNRELATED still-red
    # module would veto the jest-proven characterization test under a full-suite gate.
    # It carries the SOURCE module in ``RenamePlan.derived_from`` so the impact scope
    # is seeded from the tests exercising it; the generated test's own forced jest gate
    # is the independent correctness proof and the full suite the commit-time backstop.
    "js-cover-gaps",
    # js-strengthen-tests lands a brand-new Apex-owned
    # ``<dir>/__tests__/<stem>.apex-mutants.cover.test.<ext>`` that no other test
    # imports, so on a multi-module JS project an UNRELATED still-red module would
    # veto the jest-proven mutant-killing assertion under a full-suite gate. It
    # carries the SOURCE module in ``RenamePlan.derived_from`` so the impact scope is
    # seeded from the tests exercising it; the generated test's own forced jest gate
    # is the independent correctness proof and the full suite the commit-time backstop.
    "js-strengthen-tests",
    # scaffold-from-protocol lands a brand-new ``<stem>_impl.py`` that no test
    # imports yet, so its impact-scope gate would degrade to the full suite and an
    # unrelated still-red module would veto the oracle-proven scaffold on a
    # multi-module RED baseline. It carries the protocol module in
    # ``RenamePlan.derived_from``, so the scope is seeded from the PROTOCOL
    # module's real importing tests; the instantiation oracle stays the
    # independent correctness proof and the full suite the commit-time backstop.
    "scaffold-from-protocol",
})
