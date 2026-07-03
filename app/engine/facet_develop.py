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
    # Always-returning near-duplicate variants: the near-dup family's SECOND
    # control-flow rung (dedup-parameterized-total-return) — a near-dup group
    # whose block is TOTAL-RETURN (every exit path returns/raises), the shape
    # bare dedup-parameterized refuses. MUST precede BOTH the "parameterize
    # the variants" near-dup keys below (which "parameterize the returning
    # variants" contains) and the broader ``parameterize`` key further down.
    "always-returning near-duplicate": "dedup-parameterized-total-return",
    "parameterize the returning variants": "dedup-parameterized-total-return",

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

    # Trailing guard after setup: the sibling shape of the early-exit guard. Here
    # an ``if`` wraps the TAIL of a function after some preamble (not a leading
    # precondition) — the standalone guard-clause objective owns exactly this case,
    # distinct from extract-guard-clause's leading-precondition rewrite. MUST
    # precede the broader "guard clause" key below, which "trailing guard" sits
    # apart from but which would otherwise out-rank a similar phrasing.
    "trailing guard after setup": "guard-clause",
    "a trailing guard": "guard-clause",

    # Flatten control flow: turn a nested if/else into early-exit guards. The
    # "early returns / guard clauses" sub-aspects of deep nesting name exactly
    # what the extract-guard-clause transform does (distinct from shrinking the
    # whole function — here the body stays, the nesting goes).
    "guard clause": "extract-guard-clause",
    "early return": "extract-guard-clause",
    "precondition exits": "extract-guard-clause",
    "error exits first": "extract-guard-clause",

    # Fully-returning duplicate block: the control-flow half of dedup. The base
    # ``dedup`` objective only lifts a duplicate that ends in a plain statement or
    # a single tail return; a block whose EVERY exit path returns is the slice
    # dedup-total-return closes — so this phrasing routes there, not to bare dedup.
    # MUST precede the "duplicated logic"/"shared helper" dedup keys below.
    "fully-returning duplicate": "dedup-total-return",

    # Guard-returning duplicate block: the REMAINING control-flow slice — a
    # guard `return` on some path AND a live fall-through (both dedup siblings
    # refuse it; the sentinel-projection objective lifts it). MUST also precede
    # the broad dedup keys below.
    "guard-returning duplicate": "dedup-guarded-return",

    # Import-block hygiene: the "decouple → import direction" sub-aspects name the
    # two mechanical import tidies. An import nothing references is dropped
    # (remove-unused-imports); an unordered import block is sorted (sort-imports).
    "an unused import": "remove-unused-imports",
    "an unsorted import block": "sort-imports",
    # Repeated `from <same-module> import ...` lines collapse into one, first-
    # appearance order, binding-multiset-identical (refuses on any rebind-reorder,
    # comment/noqa loss, or incompatible alias). The "import direction" sub-aspect's
    # third tidy. Phrasing is substring-order-safe vs every other key.
    "the duplicate from-imports to merge": "merge-duplicate-imports",

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

    # Legacy string-formatting idioms: the "legacy idioms → pre-f-string
    # formatting" sub-aspects name each pre-f-string shape and route to the
    # dedicated transform that modernizes it — ``%`` formatting
    # (percent-to-fstring), ``str.format`` calls (fstring-convert / the
    # format-spec variant via format-to-fstring). Each is value-preserving.
    "percent-style string format": "percent-to-fstring",
    "explicit format-spec call": "format-to-fstring",
    "str.format placeholder call": "fstring-convert",

    # Redundant constructor calls: ``set([...])`` is a set literal; a dict built
    # by an append-style loop is a dict comprehension. The "legacy idioms →
    # redundant constructor call" sub-aspects route to those transforms.
    "set from a list literal": "set-literal",
    "dict built by a loop": "dict-comprehension",

    # Adjacent string literals: implicitly concatenated literals ("a" "b") fold
    # into one. The "legacy idioms → adjacent string literals" sub-aspect routes
    # to the fold transform.
    "implicitly concatenated literals": "fold-literal-string-concat",

    # Redundant f-string prefix: an ``f"..."`` with NO ``{...}`` placeholder is a
    # plain string wearing an ``f`` for no reason (ruff F541). The dedicated
    # remove-redundant-fstring transform strips only the noise prefix. This is a
    # narrower, value-identical tidy than the broad ``modernize`` sweep, so the
    # specific "redundant f-string prefix" phrasing routes to it directly. (Kept
    # off the "f-string without placeholders" finding above, which stays on
    # modernize so existing routing is unchanged.)
    "a redundant f-string prefix": "remove-redundant-fstring",
    "an f-string with no placeholders to strip": "remove-redundant-fstring",

    # Expression-level redundancy (the "redundant expressions" aspect). Each phrase
    # names one value-preserving rewrite and routes to its dedicated transform.
    # None of these phrasings is a substring of another key here, so order is free.
    "a double negation": "remove-double-negation",
    "length compared to zero": "simplify-len-comparison",
    "a negated equality comparison": "simplify-negated-comparison",
    "an isinstance or-chain": "merge-isinstance",
    "a startswith or endswith or-chain": "collapse-startswith",
    "an unchained comparison range": "chain-comparison",
    "a magic literal worth naming": "extract-constant",
    "a self-referential augmented assignment": "combine-augmented-assign",
    "nested with statements": "combine-nested-with",
    "a comprehension wrapped in another call": "simplify-comprehension",

    # Always-true tuple assert: ``assert (cond, "msg")`` is a no-op (a non-empty
    # tuple is always truthy) — the author meant ``assert cond, "msg"``. The
    # detector phrases the bug as "assert on a tuple is always true", which the
    # fix-assert-tuple transform resolves by closing the parentheses bug.
    "assert on a tuple": "fix-assert-tuple",

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

    # The JS/TS image of cover-gaps: an UNTESTED exported JS/TS function whose
    # CURRENT behaviour ought to be pinned by a jest test. The js-cover-gaps
    # objective IS that action — it CALLS the function with synthesized inputs at
    # generation time and pins ``expect(fn(...)).toEqual(<captured>)`` (sound by
    # construction within the decidable input slice, env-reproducibility-gated),
    # refusing an env-fragile/uninferable/already-covered target. The JS sibling of
    # cover-gaps for the under-served JS lane. Its phrasing ("the untested jest
    # function to characterize") is not a substring of any cover-gaps test key above
    # (nor any of them of it), so its order versus them is free.
    "the untested jest function to characterize": "js-cover-gaps",

    # Surviving mutant: where cover-gaps writes the FIRST test for an UNTESTED
    # module, strengthen-tests STRENGTHENS an existing-but-thin test — the "a
    # surviving mutant the tests miss" sub-aspect names a seeded fault the suite
    # still passes on (a real test blind spot). The strengthen-tests objective
    # LANDS exactly the fix: a double-gated assertion (passes on real code, fails
    # against that mutant) that kills it. So the surviving-mutant facet becomes the
    # campaign that closes the blind spot. Its phrasing is not a substring of any
    # cover-gaps key above, so order versus them is free.
    "a surviving mutant the tests miss": "strengthen-tests",

    # The JS/TS image of the surviving-mutant facet: an ALREADY-tested exported JS/TS
    # function whose EXISTING jest test (its MINED ``expect(fn(args)).matcher(expected)``
    # witnesses) is BLIND to a single-token mutant. The js-strengthen-tests objective
    # (the LITE, mined-witness sibling of strengthen-tests) LANDS exactly the fix: it
    # seeds a deterministic single-token mutant catalog, keeps the SURVIVORS (every
    # mined witness still matches — no per-mutant buyer-suite run), and pins ONE
    # env-gated ``expect(fn(<input>)).toEqual(<real output>)`` on an input where the
    # real output DIVERGES from a survivor (it kills it), in an Apex-OWNED test file
    # (the buyer's test is never edited). HONESTLY narrower than the Python mirror — it
    # strengthens against the MINED witnesses, NOT arbitrary full-suite blind spots. Its
    # phrasing ("the jest mutant the mined witnesses miss") is not a substring of "a
    # surviving mutant the tests miss" above (nor of "the untested jest function to
    # characterize" / any other key, nor any of them of it), so its order is free.
    "the jest mutant the mined witnesses miss": "js-strengthen-tests",

    # Redundant control flow: equivalence-preserving tidies the ``simplify`` lens
    # now zooms into (the "redundant control flow" aspect's L3 sub-aspects in
    # idea_facets). Each phrase names one provably-equivalent-but-noisier shape and
    # routes to the dedicated transform objective that collapses it. None of these
    # phrasings is a substring of any other key here, so insertion order is free.
    "boolean return simplification": "simplify-bool-return",
    "ternary that returns a boolean": "simplify-ternary-bool",
    "redundant else after return": "remove-redundant-else",
    "collapsible nested conditionals": "merge-nested-if",
    "get-with-default lookup": "simplify-dict-get",
    "manual index loop": "use-enumerate",
    "redundant pass statement": "remove-pointless-pass",
    "statements after an unconditional return": "remove-unreachable-after-terminator",

    # Redundant boolean comparison: the detector flags ``x == True`` / ``is
    # False`` etc. ("compare to True/False directly") but ships no fix; the
    # simplify-bool-comparison transform drops the redundant literal comparison
    # (only when the operand is provably a bool, so it stays value-preserving).
    "compare to true/false directly": "simplify-bool-comparison",

    # Unfinished code: the "missing operation on the contract" aspect names the
    # stub implementation that still has to be written. The implement-stub
    # objective LANDS exactly that — it synthesises a body for a stub
    # (NotImplementedError / `...` / TODO) whose contract is already pinned by
    # tests, deterministically, and refuses when no fixed template satisfies the
    # tests. So the "implement the stub" facet becomes the campaign that finishes
    # the unfinished function.
    "the default or stub implementation": "implement-stub",

    # Test-driven creation: the "missing operation on the contract" aspect also
    # names the function that does NOT EXIST YET but that a RED test already
    # calls (the TDD inner loop: the test is written, the code is not). Where
    # implement-stub FILLS an existing stub, the tdd-implement objective CREATES
    # the absent function — it attributes a missing-symbol failure
    # (AttributeError/NameError/ImportError, or an arity TypeError) to one target
    # module, infers the signature from the RED test's call sites, inserts a
    # stub, and delegates the body to the same overfit-guarded synthesiser, so
    # the RED test flips RED->GREEN under the full-suite gate (refusing when no
    # template proves it). So the "function the red test calls" facet becomes the
    # campaign that writes the not-yet-written function. Listed AFTER the
    # stub-implementation key it shares an aspect with; neither phrase is a
    # substring of the other, so their relative order is free.
    "the function the red test calls": "tdd-implement",
    "the worked example to satisfy": "implement-from-doctest",
    "the failing jest test whose function to write": "js-tdd-implement",
    # The JS/TS image of "the worked example to satisfy": a JS/TS stub whose
    # contract is its OWN JSDoc ``@example`` block and that NO jest test references
    # (the inverse of the failing-jest-test trigger above). The
    # js-implement-from-jsdoc objective LANDS exactly that — it synthesises a body
    # from the fixed template space and keeps it iff a jest spec Apex GENERATES from
    # the ``@example`` lines goes green in a throwaway copy (never writing a test
    # into the real tree), refusing otherwise. Substring-order-safe vs the
    # failing-jest-test key and the Python worked-example key ("jsdoc example" vs
    # "jest test" vs "worked example" — none is a substring of another), so its
    # relative order is free.
    "the jsdoc example whose function to write": "js-implement-from-jsdoc",

    # Missing type hints: the constructive "naming and types" aspect names the
    # precise type/annotation a parameter or return ought to carry. The
    # infer-type-hints objective LANDS exactly that — a ``-> T`` / ``param: T``
    # provable from the AST (agreeing literal returns, non-None literal defaults),
    # never a guess. So the type-annotation facet becomes the campaign that
    # raises the project's type-hint coverage.
    "the precise type or annotation": "infer-type-hints",

    # Fluent / alternative-constructor return type: the "naming and types" aspect
    # also names the return shape the literal type oracle deliberately REFUSES — a
    # method that returns ``self`` (a builder) or a ``@classmethod`` that returns
    # ``cls(...)`` (an alternative constructor). The annotate-self-returns objective
    # LANDS exactly that — a forward-ref ``-> "<Class>"`` provable from the language
    # contract (``self`` is an instance of its class; ``cls(...)`` constructs one),
    # the one return type infer-type-hints cannot reach. Its phrasing is not a
    # substring of "the precise type or annotation" (nor of any other key, nor any
    # of them of it) — "fluent self-return type" vs "precise type or annotation" —
    # so its insertion order is free.
    "the fluent self-return type to annotate": "annotate-self-returns",

    # Unwired public surface: the document lens's "signatures and types" aspect
    # names the package's public re-export surface. The wire-exports objective
    # LANDS exactly that — it populates an empty ``__init__.py`` with
    # ``from .module import Name`` re-exports + a complete ``__all__`` for every
    # public top-level symbol, gated by an import oracle (every export must
    # resolve) and the suite. So the "re-export surface" facet becomes the
    # campaign that makes ``from pkg import X`` work.
    "the public re-export surface to wire": "wire-exports",

    # Leaf module with no __all__ whose public surface is implicit: wire-module-exports
    # declares an explicit __all__ == the current default star set (behaviour-identical;
    # only ``from m import *`` consults __all__) — distinct from wire-exports' package
    # __init__ re-export surface. Phrasing is substring-order-safe vs every other key.
    "the module public surface to declare": "wire-module-exports",

    # An existing module-level __all__ list whose names are out of order: sort-dunder-all
    # sorts + de-duplicates it (behaviour-identical — __all__ order never affects
    # import *). DISTINCT from wire-module-exports above, which CREATES a missing
    # __all__; this SORTS an existing one (the two never act on the same module).
    # Phrasing is substring-order-safe vs every other key.
    "the module __all__ to sort": "sort-dunder-all",

    # An existing module-level __all__ that REPEATS a string entry: dedup-dunder-all
    # removes the duplicate while PRESERVING first-appearance order (behaviour-
    # identical — __all__ membership is a set, so a repeat changes nothing observable).
    # DISTINCT from sort-dunder-all above, which canonically ORDERS __all__ (and
    # de-dupes only as a side effect); this keeps the author's order and removes ONLY
    # the duplicates — a no-op on a duplicate-free list. Phrasing is substring-order-
    # safe vs every other key.
    "the duplicate __all__ entries to remove": "dedup-dunder-all",

    # Undocumented public signature: the document lens's "signatures and types"
    # aspect also names a public function that carries NO docstring. The
    # document-signature objective LANDS exactly that — a docstring listing the
    # parameter names (AST facts) plus a ``Returns: <type>`` line whose type is
    # PROVEN by the existing return-type oracle (the same inference infer-type-hints
    # lands as ``-> T``); it REFUSES when the return type is not provable (lands
    # nothing, never a placeholder), and skips private/dunder/test names. So the
    # "signature to document" facet becomes the campaign that documents the
    # function's surface, honestly and for free. Its phrasing is not a substring of
    # any other key (nor any of them of it), so its order is free.
    "the public signature to document": "document-signature",

    # Undocumented public FAILURE CONTRACT: the "raised exceptions" lens names a
    # public function whose body raises an exception its docstring never records.
    # The document-raises objective LANDS exactly that — a ``Raises:`` block with
    # one line per DISTINCT *escaping* literal ``raise <ErrorName>(...)``, the name
    # read VERBATIM off the AST in source order (the Python sibling of the JS
    # document-raises-jsdoc ``@throws``); it inherits document-signature's honesty
    # gate and lands ONLY when at least one PROVABLE escaping raise exists (a
    # function that raises nothing, or raises an unprovable shape — a variable / a
    # lowercase factory call / a dotted ctor / a bare re-raise / inside a
    # try-with-except that could swallow it — is refused, never a content-free
    # ``Raises:``). A docstring is a string-literal first statement (zero runtime
    # bytes), so it is behaviour-identical by construction. Its phrasing is not a
    # substring of any other key (nor any of them of it) — in particular it is
    # distinct from "the public signature to document" above ("raised exceptions"
    # vs "signature") and from the JS "the thrown error types to document in jsdoc"
    # ("raised exceptions to document" vs "thrown error types … in jsdoc") — so its
    # order is free.
    "the raised exceptions to document": "document-raises",

    # DOCUMENTED Python function missing a return type: the "signatures and types"
    # lens also names a PUBLIC function that HAS a docstring (and so is NOT
    # document-signature's territory) but carries no ``-> T`` annotation and whose
    # docstring records no return. The pin-return-type objective LANDS exactly that
    # — it splices ONE ``Returns: <T>`` line into the existing docstring, the ``<T>``
    # read from the SAME proven return-type oracle infer-type-hints lands as ``-> T``
    # (agreeing literals / fixed-result builtin / pure-procedure ``None``). It is the
    # DOCUMENTED-function image of infer-type-hints, for annotation-averse codebases:
    # it REFUSES an undocumented function (document-signature's lane), an
    # already-annotated function (the oracle returns ``None`` on ``fn.returns``, so
    # the documented return would only echo the signature), a generator / ambiguous /
    # fall-through return (oracle ``None``), and a docstring that already records a
    # return in ANY spelling (``Returns:`` / ``:return:`` / ``@returns`` — never
    # overwrite a human's contract). A ``Returns:`` line is docstring TEXT (zero
    # runtime bytes), so it is behaviour-identical by construction. Its phrasing is
    # not a substring of any other key (nor any of them of it) — in particular it is
    # distinct from "the public signature to document" ("documented return type … to
    # pin" vs "public signature … to document") and "the unenforced doctest examples
    # to pin" ("documented return type" vs "unenforced doctest examples") — so its
    # order is free.
    "the documented return type to pin": "pin-return-type",

    # DOCUMENTED + ANNOTATED Python function whose return is undocumented: the
    # "signatures and types" lens also names a PUBLIC function that HAS a docstring
    # AND carries an explicit ``-> T`` annotation but whose docstring records no
    # return. The document-returns objective LANDS exactly that — it splices a
    # faithful return section into the existing docstring rendering the DECLARED
    # annotation ``T`` VERBATIM (``ast.unparse(fn.returns)``), MATCHING the
    # docstring's convention (a Google ``Returns:`` section, a Sphinx ``:returns:``/
    # ``:rtype:`` field, or the Google default for plain prose). It is the
    # ANNOTATION-sourced, style-matching sibling of pin-return-type (which reads the
    # INFERRED oracle, firing on an UN-annotated function): the two are mutually
    # exclusive by the annotation predicate. It REFUSES an undocumented function
    # (document-signature's lane), a ``-> None`` / ``-> NoReturn`` (incl. aliases), a
    # generator / async-generator return (the value is YIELDED), an ``@overload`` /
    # property setter, and a docstring that already records a return in ANY
    # convention (no double-doc). A return section is docstring TEXT (zero runtime
    # bytes), so it is behaviour-identical by construction. Its phrasing is not a
    # substring of any other key (nor any of them of it) — in particular it is
    # distinct from "the documented return type to pin" ("annotated return type … to
    # document" vs "documented return type … to pin") and "the public signature to
    # document" ("annotated return type" vs "public signature") — so its order is
    # free.
    "the annotated return type to document": "document-returns",

    # DOCUMENTED Python function whose PARAMETER TYPES are undocumented: the
    # "signatures and types" lens also names a PUBLIC function that HAS a docstring
    # and carries at least one DECLARED parameter annotation but whose docstring
    # records no parameters. The document-param objective LANDS exactly that — it
    # splices a faithful ``Args:`` section into the existing docstring listing one
    # ``name (TYPE):`` line per declared-annotated parameter, the type read VERBATIM
    # off ``arg.annotation`` (``ast.unparse``), MATCHING the docstring's convention
    # (a Google ``Args:`` block, or a Sphinx ``:param:``/``:type:`` field list). It is
    # the Python mirror of js-document-param-types (``@param {T} name``) and the
    # input-contract sibling of document-returns (``Returns:``). It inherits the
    # signature-restatement honesty gate — it lands ONLY when a parameter carries a
    # DECLARED annotation and emits a line ONLY for annotated params (an unannotated
    # one is skipped — never a bare ``name`` line). It REFUSES an undocumented
    # function (document-signature's lane), an ``@overload`` / property setter, an
    # unreadable ``*args``/``**kwargs`` annotation, and a docstring that already
    # records its parameters in ANY convention — including the PARTIAL case (some
    # documented, not all), which refuses WHOLE rather than merging into a half-filled
    # block. An ``Args:`` section is docstring TEXT (zero runtime bytes), so it is
    # behaviour-identical by construction. Its phrasing is not a substring of any
    # other key (nor any of them of it) — in particular it is distinct from "the
    # exported parameter types to document in jsdoc" below ("the parameter types" vs
    # "the exported parameter types … in jsdoc") and "the annotated return type to
    # document" above ("parameter" vs "return") — so its order is free.
    "the parameter types to document": "document-param",

    # DOCUMENTED Python CLASS whose CLASS-LEVEL ATTRIBUTES are undocumented: the
    # "signatures and types" lens also names a PUBLIC class that HAS a docstring and at
    # least one class-body annotated field (``ast.AnnAssign``) but whose docstring
    # records no attributes. The document-attributes objective LANDS exactly that — it
    # splices a faithful ``Attributes:`` section into the existing docstring listing one
    # ``name (TYPE)`` line per class-level annotated field, the type read VERBATIM off
    # ``field.annotation`` (``ast.unparse``), MATCHING the docstring's convention (a
    # Google ``Attributes:`` block, or a Sphinx ``:ivar:``/``:vartype:`` field list). It
    # is the CLASS-attribute sibling of document-returns (``Returns:``) and selects only
    # ``ast.ClassDef`` nodes, so it never collides with the function-scoped doc
    # objectives. It REFUSES an undocumented class (document-signature's lane), a class
    # with NO class-level annotated field (an instance-only ``self.x`` class would be
    # inference — out of scope), a class whose every annotated field is unreadable, and a
    # docstring that already records its attributes in ANY convention — including the
    # PARTIAL case (some documented, not all), which refuses WHOLE rather than merging
    # into a half-filled block. An ``Attributes:`` section is docstring TEXT (zero
    # runtime bytes), so it is behaviour-identical by construction. Its phrasing is not a
    # substring of any other key (nor any of them of it) — in particular it is distinct
    # from "the parameter types to document" above ("class attributes" vs "parameter
    # types") — so its order is free.
    "the class attributes to document": "document-attributes",

    # DOCUMENTED Python GENERATOR whose YIELDED element type is undocumented: the
    # "signatures and types" lens also names a PUBLIC generator (a ``yield`` / ``yield
    # from`` in its OWN scope) that HAS a docstring AND a subscripted iterator/generator
    # return annotation (``-> Iterator[T]`` / ``Generator[Y, S, R]`` / async variants,
    # and their ``typing.``/``collections.abc.``/alias spellings) but whose docstring
    # records no yield. The document-yields objective LANDS exactly that — it splices a
    # faithful ``Yields:`` section into the existing docstring rendering the ELEMENT type
    # (the first subscript arg) VERBATIM (``ast.unparse``), MATCHING the docstring's
    # convention (a Google ``Yields:`` section, a Sphinx ``:yields:``/``:ytype:`` field,
    # or the Google default). It is the GENERATOR sibling of document-returns and fires
    # exactly where document-returns REFUSES (its ``_GENERATOR_RETURNS`` refuse-head set):
    # the two are mutually exclusive on a generator, which gets a ``Yields:`` and never a
    # ``Returns:``. It REFUSES a non-generator (no own-scope ``yield``), a non-iterator /
    # missing / bare-unsubscripted annotation, an undocumented function, and a docstring
    # that already records a yield in ANY convention. A ``Yields:`` section is docstring
    # TEXT (zero runtime bytes), so it is behaviour-identical by construction. Its
    # phrasing is not a substring of any other key (nor any of them of it) — in
    # particular it is distinct from "the annotated return type to document"
    # ("yielded type" vs "annotated return type") — so its order is free.
    "the yielded type to document": "document-yields",

    # Undocumented EXPORTED JS/TS signature: the JS/TS sibling of the above. The
    # document-export-jsdoc objective LANDS a minimal JSDoc on an exported
    # function/const-arrow that carries NO leading JSDoc — one ``@param <name>``
    # per declared parameter plus (TS only) an ``@returns {T}`` read VERBATIM off
    # the declared return-type annotation; it inherits document-signature's honesty
    # gate and REFUSES a name+param-only restatement (so it lands only when a
    # declared return type surfaces a fact the bare signature does not). A JSDoc is
    # leading trivia (zero runtime bytes), so it is behaviour-identical by
    # construction, verified by an in-driver re-parse — no jest/tsc run. Its
    # phrasing is not a substring of any other key (nor any of them of it) — in
    # particular it is distinct from "the public signature to document" above
    # ("exported"/"in jsdoc" vs "public") — so its order is free.
    "the exported signature to document in jsdoc": "document-export-jsdoc",

    # Undocumented EXPORTED JS/TS PARAMETER TYPES: the missing HALF of
    # document-export-jsdoc. Where that objective lands only when a declared
    # RETURN type exists (and emits bare ``@param <name>`` lines, no type), the
    # js-document-param-types objective LANDS a JSDoc whose ``@param {T} <name>``
    # lines carry the DECLARED parameter types read VERBATIM off the TS annotation
    # (plus an ``@returns {T}`` when a return type is declared) — a strictly
    # richer, maintainer-valued fact. It inherits the same honesty gate and lands
    # ONLY when at least one parameter carries a declared type (a name-only/untyped
    # ``@param`` restates the signature → refuse). A JSDoc is leading trivia (zero
    # runtime bytes), so it is behaviour-identical by construction, verified by the
    # SAME in-driver re-parse — no jest/tsc run. Its phrasing is not a substring of
    # any other key (nor any of them of it) — in particular it is distinct from
    # "the exported signature to document in jsdoc" above ("parameter types" vs
    # "signature") — so its order is free.
    "the exported parameter types to document in jsdoc": "js-document-param-types",

    # Undocumented EXPORTED JS/TS FAILURE CONTRACT: the third JSDoc-family fact,
    # the sibling of document-export-jsdoc (``@returns``) and js-document-param-types
    # (``@param {T}``). The document-raises-jsdoc objective LANDS a JSDoc whose
    # ``@throws {Ctor}`` lines name the DISTINCT thrown constructors of the body,
    # read VERBATIM off each literal ``throw new <Identifier>(...)`` node in source
    # order; it inherits the same honesty gate and lands ONLY when at least one
    # PROVABLE thrown constructor exists (a function that throws nothing, or throws
    # an unprovable shape — a variable / call / member-ctor / re-throw — is refused,
    # never a content-free ``@throws``). A JSDoc is leading trivia (zero runtime
    # bytes), so it is behaviour-identical by construction, verified by the SAME
    # in-driver re-parse — no jest/tsc run. Its phrasing is not a substring of any
    # other key (nor any of them of it) — in particular it is distinct from "the
    # exported signature to document in jsdoc" and "the exported parameter types to
    # document in jsdoc" above ("thrown error types" vs "signature" vs "parameter
    # types") — so its order is free.
    "the thrown error types to document in jsdoc": "document-raises-jsdoc",

    # Undocumented EXPORTED PLAIN-JS return type: the case the typed JSDoc family
    # CANNOT serve. document-export-jsdoc (and js-document-param-types) emit an
    # ``@returns {T}`` ONLY from a DECLARED TS return annotation, so a plain-JS
    # export (``export function isReady(x){ return true; }``) gets no ``@returns``.
    # The js-document-returns-inferred objective LANDS exactly that — a JSDoc whose
    # single ``@returns {T}`` line carries the type PROVEN from the function's OWN
    # literal ``return`` statements (``true``/``false`` → boolean, a string/number/
    # array/object literal → string/number/Array/Object, ``new <Ctor>()`` → that
    # ctor), read VERBATIM off the AST literal kind (never inferred from a value flow
    # / call result). It inherits the same honesty gate and lands ONLY when a literal
    # return type is provable (a non-literal / void / ``null`` / heterogeneous return,
    # or none, is refused). DISJOINT from document-export-jsdoc by THE typed-vs-
    # untyped split: it fires ONLY when NO TS return type is declared, so no node ever
    # gets an ``@returns`` from two planners. NO ``@param`` lines (that is
    # js-document-param-types' surface). A JSDoc is leading trivia (zero runtime
    # bytes), so it is behaviour-identical by construction, verified by the SAME
    # in-driver re-parse — no jest/tsc run. Its phrasing is not a substring of any
    # other key (nor any of them of it) — in particular it is distinct from "the
    # exported signature to document in jsdoc" / "the exported parameter types to
    # document in jsdoc" / "the thrown error types to document in jsdoc" above
    # ("inferred return type" vs "signature"/"parameter types"/"thrown error types")
    # and from the Python "the annotated return type to document" / "the documented
    # return type to pin" ("inferred return type … in jsdoc" vs "annotated"/
    # "documented return type") — so its order is free.
    "the inferred return type to document in jsdoc": "js-document-returns-inferred",

    # Defined-but-unexported public JS/TS function: the "signatures and types" lens
    # also names a top-level public function/const-arrow a clean-ESM module DEFINES
    # but never exports. The js-wire-exports objective LANDS exactly that — it
    # prepends the ONE missing ESM ``export`` keyword (a pure export-surface GROW:
    # publishing an already-defined binding can never break an existing importer),
    # proven by an in-driver re-parse that the exported-name set grew by exactly that
    # name; it REFUSES a CJS/``export default``/``export =`` module (the deferred
    # surface). The JS/TS sibling of wire-exports. Its phrasing is not a substring of
    # any other key (nor any of them of it) — distinct from "the public re-export
    # surface to wire" (package index) and "the exported signature to document in
    # jsdoc" (already exported) — so its order is free.
    "the unexported public function to export": "js-wire-exports",

    # Missing usage doc: the document lens's "worked examples" aspect names the
    # package's USAGE.md — the minimal runnable examples a newcomer needs. The
    # generate-usage-doc objective LANDS exactly that — a USAGE.md generated from
    # the public API (signatures + docstring summaries + the docstrings' own
    # ``>>>`` examples), with every example EXECUTED against the package and
    # omitted if it does not run green. So the "usage doc" facet becomes the
    # campaign that documents how to call the package, honestly and for free.
    "the package usage doc to generate": "generate-usage-doc",

    # Unenforced worked examples: the document lens's "worked examples" aspect also
    # names a function whose ``>>>`` docstring examples are a CONTRACT a reader
    # trusts but NOTHING in the suite runs — documentation that can silently rot to
    # red. The pin-doctest objective LANDS exactly that — a new
    # ``tests/test_<stem>_doctest.py`` that EXECUTES those (already-green) examples
    # so the project's own test run keeps them honest; it refuses when the examples
    # are already enforced (a pinned test, or ``pytest --doctest-modules``) or are
    # red today. So the "examples to pin" facet becomes the campaign that turns the
    # worked examples into a suite-enforced contract. Its phrasing is not a substring
    # of any other key (nor any of them of it), so its insertion order is free.
    "the unenforced doctest examples to pin": "pin-doctest",

    # Boilerplate constructor: the "unreachable or no-op statements" simplify
    # sub-aspect names a hand-written ``__init__`` that does nothing but copy its
    # parameters onto ``self`` — pure ceremony. The dataclassify objective LANDS
    # exactly that tidy: it adds ``@dataclass`` + fields (order/annotation/default
    # preserved, mutable defaults via ``field(default_factory=...)``) and deletes
    # the redundant ``__init__``, behaviour-equivalent and suite-gated. So the
    # "boilerplate constructor" facet becomes the campaign that modernizes it.
    "a boilerplate constructor to make a dataclass": "dataclassify",

    # Never-mutated dataclass: the same "unreachable or no-op statements" simplify
    # sub-aspect also names a ``@dataclass`` whose fields are NEVER mutated anywhere
    # in the project's own source — its mutability is dead surface. The
    # freeze-dataclass objective LANDS exactly that modernization: it adds
    # ``frozen=True`` (immutable + hashable, behaviour-preserving), proving across
    # the WHOLE project that no field is ever assigned/augmented/deleted/``setattr``-ed
    # before touching the decorator, and is suite-gated + auto-rollback for the
    # dynamic residual. So the "dataclass to freeze" facet becomes the campaign that
    # makes it immutable. Its phrasing is not a substring of the dataclassify key
    # above (nor it of this), so their relative order is free.
    "a never-mutated dataclass to freeze": "freeze-dataclass",

    # Closed-attribute class: the same "unreachable or no-op statements" simplify
    # sub-aspect also names a class whose instance attributes are PROVABLY closed —
    # only ever the ones its ``__init__`` (or ``@dataclass`` field list) declares,
    # never an off-field attribute stored anywhere. The add-slots objective LANDS
    # exactly that storage/shape lock: it splices ``__slots__ = (...)`` naming the
    # proven instance-attribute set in source order (smaller per-instance memory + a
    # typo-attribute becomes a loud AttributeError), proving across the WHOLE project
    # (tests included) that the slot set is a SUPERSET of every attribute ever stored
    # on the class, and is suite-gated + auto-rollback for the dynamic residual. So
    # the "class to give slots" facet becomes the campaign that closes its shape. The
    # structural DUAL of freeze-dataclass; its phrasing shares no whole-key substring
    # with the freeze/dataclassify keys above (nor any of them with it), so the
    # relative order is free.
    "the closed-attribute class to give slots": "add-slots",

    # A non-@dataclass plumbing class MISSING __repr__/__eq__: the SAME
    # "unreachable or no-op statements" simplify sub-aspect also names a regular class
    # whose __init__ is pure ``self.x = x`` copies but that — because it has a base, an
    # extra method, or a real __init__ body — dataclassify must REFUSE. synthesize-dunders
    # LANDS exactly the value semantics dataclassify would have given it: the canonical
    # TOTAL __repr__/__eq__/__hash__ ``@dataclass`` itself emits, over the PROVEN
    # pure-copy field set, gated by an inherited-__eq__ refusal (no resolvable base may
    # define __eq__) + suite + auto-rollback. The sibling of dataclassify; its phrasing
    # ("the repr and eq to synthesize from fields") shares no whole-key substring with the
    # dataclassify / freeze / slots keys above (nor any of them with it), so the relative
    # order is free.
    "the repr and eq to synthesize from fields": "synthesize-dunders",

    # A non-@dataclass regular class that defines __eq__ AND exactly one of the
    # ordering dunders __lt__/__le__/__gt__/__ge__ but is MISSING the other three:
    # the SAME "unreachable or no-op statements" simplify sub-aspect also names such a
    # class, and seal-total-ordering LANDS the stdlib @functools.total_ordering that
    # fills the three absent comparison operators from the one the author wrote plus
    # __eq__ (the comparison-dunder sibling of synthesize-dunders). RUNTIME-ADDITIVE
    # (@total_ordering never overwrites a defined method); the false-fill risk is closed
    # STATICALLY (refuse unless __eq__ + exactly one order op are defined in this body
    # and the other three are absent) + suite + auto-rollback. Its phrasing ("the
    # comparison operators to complete from one") shares no whole-key substring with the
    # dunders / dataclassify / freeze / slots keys above (nor any of them with it), so
    # the relative order is free.
    "the comparison operators to complete from one": "seal-total-ordering",

    # A non-@dataclass regular class that defines __eq__ in its OWN body but does NOT
    # define __hash__ and is NOT already deliberately unhashable: the SAME "unreachable
    # or no-op statements" simplify sub-aspect also names such a class. THE PYTHON RULE
    # — defining __eq__ sets __hash__ = None implicitly, so instances become UNHASHABLE
    # (TypeError in a set/dict-key). seal-hashable-eq LANDS the canonical
    # `def __hash__(self): return hash((self.f1, ...))` over the SAME proven pure-copy
    # field set synthesize-dunders trusts (the __hash__ sibling of synthesize-dunders),
    # RESTORING set/dict-key usability where instances currently raise. RUNTIME-ADDITIVE
    # (it re-enables a hard TypeError on an unhashable instance); the residual (a field
    # whose own value is unhashable) is caught by the suite + auto-rollback. PURELY
    # intra-module (no base allowed -> the hash contract is the class's OWN), so strictly
    # simpler than synthesize-dunders. Its phrasing ("the hash to restore from the eq
    # fields") shares no whole-key substring with the dunders / comparison-ops /
    # dataclassify / freeze / slots keys above (nor any of them with it), so the relative
    # order is free.
    "the hash to restore from the eq fields": "seal-hashable-eq",

    # A project's own @dataclass that does NOT set order= and defines NONE of the
    # comparison dunders __lt__/__le__/__gt__/__ge__ itself: the SAME "unreachable or
    # no-op statements" simplify sub-aspect also names such a class, and
    # add-dataclass-order LANDS order=True on the decorator (@dataclass ->
    # @dataclass(order=True), or splices into an existing call), which generates the
    # four comparison operators from the field tuple — the dataclass sibling of
    # freeze-dataclass (frozen=True) and seal-total-ordering. RUNTIME-ADDITIVE
    # (order=True only ADDS the four ops, absent today -> TypeError); the false-fill
    # risk is closed STATICALLY (stdlib-dataclass provenance, no existing comparison
    # dunder, eq not disabled, single-line-rewritable) + suite + auto-rollback. Its
    # phrasing ("the dataclass to make orderable") shares no whole-key substring with
    # the freeze / dataclassify / dunders / slots keys above (nor any of them with it),
    # so the relative order is free.
    "the dataclass to make orderable": "add-dataclass-order",

    # A leaf class proven never subclassed anywhere: add-final seals it with
    # @typing.final (a type-checker-only no-op — behaviour-preserving; the false-final
    # risk is closed STRUCTURALLY by the whole-project subclass scan, not the suite).
    # Phrasing is substring-order-safe vs every other key.
    "a class to seal as final": "add-final",

    # A PRIVATE Java field proven never reassigned anywhere in its file: the Java
    # sibling of add-final. java-finalize-field seals it with the `final` modifier (a
    # RUNTIME no-op — the field already obeys it; the false-final risk is closed
    # STRUCTURALLY by a whole-file assignment scan over a parse-only tree, not a
    # Maven/JUnit run, then a re-parse fact-set-identity check). Its phrasing shares
    # no whole key with "a class to seal as final" / "the method to seal as final"
    # above (in either direction — "java field to finalize" vs "to seal as final"),
    # so its relative order is free.
    "the never-reassigned java field to finalize": "java-finalize-field",

    # A DECLARED Java method/constructor parameter proven never reassigned anywhere
    # in that SAME method's own body: the parameter-level sibling of
    # java-finalize-field, and a STRONGER soundness case — a parameter's assignment
    # surface is closed to its own method body (no reflection/Serializable escape
    # hatch exists for a stack-local), so java-final-parameter needs only a
    # PER-METHOD scan (never a whole-unit refusal) to seal it with `final` (a RUNTIME
    # no-op, verified by the same re-parse fact-set-identity check). Its phrasing
    # shares no whole key with "the never-reassigned java field to finalize" (in
    # either direction — "java method parameter to finalize" vs "java field to
    # finalize"), so its relative order is free.
    "the never-reassigned java method parameter to finalize": "java-final-parameter",

    # A LOCAL Java variable declared as a DIRECT statement of a method body block and
    # proven never reassigned anywhere in that SAME method's own body: the local-level
    # sibling of java-final-parameter, one step deeper into the same never-reassigned
    # proof (a local, like a parameter, is a stack-local whose assignment surface is
    # closed to its own method body — no reflection/Serializable escape hatch). It seals
    # such a local with `final` (a RUNTIME no-op, verified by the same re-parse
    # fact-set-identity check), paying down Checkstyle FinalLocalVariable / SonarQube
    # S3008. It EXCLUDES a for-loop / enhanced-for / try-with-resources variable (none is
    # a direct block statement) and a no-initializer split local. Its phrasing shares no
    # whole key with "the never-reassigned java method parameter to finalize" (in either
    # direction — "java local variable to finalize" vs "java method parameter to
    # finalize"), so its relative order is free.
    "the never-reassigned java local variable to finalize": "java-final-local",

    # A top-level PYTHON module CONSTANT (`NAME = <literal>`, UPPER_SNAKE) proven never
    # REBOUND anywhere in the project: the Python analogue of add-final (a class @final)
    # and the java-final-* family, one level up — a whole MODULE-scope binding rather
    # than a class/method. finalize-module-constant annotates it `typing.Final` (a PURE
    # runtime no-op — CPython does not enforce Final; the false-final risk is closed
    # STRUCTURALLY by a whole-project rebind scan, tests-incl, not the suite). Its
    # phrasing shares no whole key with "the never-reassigned java local variable to
    # finalize" (in either direction — "python module constant to seal" vs "java local
    # variable to finalize"), so its relative order is free.
    "the never-rebound python module constant to seal as final": "finalize-module-constant",

    # A Java method that DECLARES a `throws` clause but carries NO Javadoc: the Java
    # sibling of document-raises / document-raises-jsdoc. java-document-throws lands a
    # FRESH Javadoc block with one `@throws <Type>` line per DECLARED checked-exception
    # type (the method's `throws` clause verbatim, NOT inferred from `throw new X()`).
    # A Javadoc is a COMMENT, so the edit is BEHAVIOUR-IDENTICAL (zero declared
    # structure changes; a re-parse fact-set-identity check, no Maven/JUnit run);
    # already-documented methods are refused (merging is out of scope). Its phrasing
    # shares no whole key with "the never-reassigned java field to finalize" (in either
    # direction — "throws clause to document" vs "field to finalize"), so its relative
    # order is free.
    "the undocumented java throws clause to document": "java-document-throws",

    # A Java method that DECLARES at least one parameter but carries NO Javadoc: the
    # Java mirror of Python document-param / JS js-document-param-types.
    # java-document-param lands a FRESH Javadoc block with one bare `@param <name>` line
    # per DECLARED parameter (the method's parameter names verbatim off
    # `VariableTree.getName()`, no types — the standard Javadoc form). A Javadoc is a
    # COMMENT, so the edit is BEHAVIOUR-IDENTICAL (zero declared structure changes; a
    # re-parse fact-set-identity check, no Maven/JUnit run); an already-documented method
    # is refused (merging is out of scope) AND a zero-parameter method is refused (a
    # `@param`-less block is content-free). The already-documented refusal keeps it
    # disjoint from java-document-throws (whichever lands first documents the method, the
    # other then refuses). Its phrasing shares no whole key with "the undocumented java
    # throws clause to document" (in either direction — "method params to document" vs
    # "throws clause to document") nor with any param-doc key ("the parameter types to
    # document" / "the exported parameter types to document in jsdoc" — neither is a
    # substring of "the undocumented java method params to document" nor vice versa), so
    # its relative order is free.
    "the undocumented java method params to document": "java-document-param",

    # A Java method that DECLARES a non-void, non-constructor return type but carries NO
    # Javadoc: the Java mirror of Python document-returns / JS js-document-returns-inferred,
    # completing the Java Javadoc contract triad (@param + @throws + @return).
    # java-document-returns lands a FRESH Javadoc block with one `@return <type>` line
    # carrying the DECLARED return type read VERBATIM off the return-type tree's SOURCE SPAN
    # (the byte slice of the source — NOT Tree.toString(), which can normalize generics —
    # so the author's generics/whitespace survive exactly; unlike the JS lane it is
    # DECLARED, never inferred). A Javadoc is a COMMENT, so the edit is BEHAVIOUR-IDENTICAL
    # (zero declared structure changes; a re-parse fact-set-identity check, no Maven/JUnit
    # run); an already-documented method is refused (keeping it disjoint from
    # java-document-param / java-document-throws), a `void`-returning method is refused (a
    # `@return void` is content-free) and a constructor is refused (no return type). Its
    # phrasing shares no whole key with "the undocumented java method params to document"
    # (in either direction — "method return type to document" vs "method params to
    # document") nor with any return-doc key ("the annotated return type to document" / "the
    # documented return type to pin" / "the inferred return type to document in jsdoc" —
    # none is a substring of "the undocumented java method return type to document" nor vice
    # versa), so its relative order is free.
    "the undocumented java method return type to document": "java-document-returns",

    # A method proven never overridden anywhere: seal-final-method seals it with
    # @typing.final (the method-level sibling of add-final — a type-checker-only
    # no-op, behaviour-preserving; the false-final risk is closed STRUCTURALLY by a
    # whole-project, transitive subclass-method scan, not the suite). Phrasing is
    # substring-order-safe vs every other key (it shares no whole key with "a class
    # to seal as final" in either direction).
    "the method to seal as final": "seal-final-method",

    # An Enum whose members are PROVEN all-distinct simple literals: enforce-enum-unique
    # seals it with @enum.unique (a no-op TODAY that locks the invariant — it raises
    # ValueError only on a future duplicate-value alias). Behaviour-preserving; the
    # false-enforce risk is closed STATICALLY (refuse unless every value is a distinct
    # literal), not by the suite. Phrasing is substring-order-safe vs every other key.
    "an enum to enforce unique values on": "enforce-enum-unique",

    # A dispatch (match/case or if/elif) over a PROVABLY-CLOSED discriminant set (an
    # in-module Enum, a Literal[...] of constants, or bool) that is missing a member
    # arm and carries NO catch-all: complete-match-exhaustiveness appends a loud
    # `case _:`/`else:` sentinel (raise AssertionError) so the silent fall-through
    # becomes loud. The inserted arm runs only on a value the old code didn't handle,
    # so it is dead code or a fixed silent bug — never a regression; the false-fill
    # risk is closed STATICALLY (refuse on any open/uncertain set), not by the suite.
    # Phrasing is substring-order-safe vs every other key.
    "a closed-set dispatch missing an exhaustiveness arm": "complete-match-exhaustiveness",

    # Missing lazy-annotation import: the document lens's "signatures and types"
    # aspect names a module that USES type annotations (a return type, an
    # annotated param, an ``x: T`` assignment) but lacks ``from __future__ import
    # annotations`` — so every annotation is eagerly evaluated at import time. The
    # add-from-future-annotations objective LANDS exactly that one-line, lazy-by-
    # default modernization (insert a fresh ``__future__`` import, or widen an
    # existing one to add ``annotations``), behaviour-preserving and suite-gated.
    # So the "annotations to make lazy" facet becomes the campaign that defers
    # them. Its phrasing is not a substring of any other key (nor any of them of
    # it), so its insertion order is free.
    "annotations to make lazy with a future import": "add-from-future-annotations",

    # Missing decorator metadata: the document lens's "signatures and types" aspect
    # names a decorator-factory's inner WRAPPER function that calls its outer's
    # single parameter (the wrapped callee) but carries no `functools.wraps` yet —
    # so every decorated function silently loses its identity (`__name__`,
    # `__doc__`, introspection). The add-functools-wraps objective LANDS exactly
    # that one-line fix (`@functools.wraps(<callee>)`), metadata-only and
    # BEHAVIOUR-IDENTICAL (zero control-flow/return/exception change) — refusing an
    # already-wrapped wrapper, an ambiguous callee (more than one outer parameter
    # called inside the wrapper), or a callee name reassigned/shadowed before the
    # wrapper closes over it. So the "wrapper missing functools.wraps" facet
    # becomes the campaign that restores its identity. Its phrasing is not a
    # substring of any other key (nor any of them of it), so its insertion order is
    # free.
    "the wrapper missing functools.wraps": "add-functools-wraps",

    # Unimplemented protocol: the generalize lens's "the shared interface to
    # extract" aspect names a ``typing.Protocol`` the project declares but has NO
    # concrete implementer for — the interface is shelf-ware until a class
    # satisfies it. The scaffold-from-protocol objective LANDS exactly that — a NEW
    # ``<pkgdir>/<stem>_impl.py`` with ``class <P>Impl(<P>):`` redeclaring each
    # fillable member with a ``...`` body (decorators preserved, ``@abstractmethod``
    # dropped, annotations stripped), gated by an INSTANTIATION ORACLE (``<P>Impl()``
    # must construct in a clean subprocess — a missed abstract member is refused) and
    # the suite. So the "protocol stub to scaffold" facet becomes the campaign that
    # gives the interface a runnable implementer to fill in. Its phrasing is not a
    # substring of any other key (nor any of them of it), so its order is free.
    "the protocol stub to scaffold": "scaffold-from-protocol",

    # A detected security vulnerability: the "harden" lens's sub-aspect names a
    # specific security FINDING in the project's own code. The harden objective
    # LANDS exactly the fix the built security engine produces for that finding —
    # Tier-1 rewrites the vulnerability away (eval → ast.literal_eval, os.system →
    # subprocess, yaml.load → safe_load, bare/Base except → Exception, hashlib.new
    # weak → usedforsecurity=False), Tier-0 inserts a reviewable ``# SECURITY``
    # annotation where no safe auto-rewrite exists (pickle / f-string SQL /
    # tempfile.mktemp / os.popen / verify=False / Zip-Slip / weak hash). Each is
    # routed through the same suite-gated, auto-rollback engine. Its phrasing is not
    # a substring of any other key (nor any of them of it), so its order is free.
    "the security vulnerability to harden": "harden",

    # An unchained re-raise inside an except block: the "raised exceptions" lens's
    # exception-chaining sub-aspect names a ``raise X(...)`` raised inside an
    # ``except E as err:`` handler WITHOUT ``from`` — which discards the original
    # traceback (flake8 B904). The raise-from objective LANDS exactly that fix — it
    # appends ``from err`` so the re-raised exception is chained to its cause,
    # restoring the traceback; the SAME exception ``X`` is still raised with the same
    # control flow (only ``__cause__`` changes), so it is behaviour-preserving by
    # construction. It REFUSES when the handler has no ``as`` binding to chain from
    # (inventing one is a bigger edit than this promises), no fixable raise, or a
    # multi-line raise. Routed through the same suite-gated, auto-rollback engine. Its
    # phrasing is not a substring of any other key (nor any of them of it) — distinct
    # in particular from "the raised exceptions to document" ("unchained re-raise …
    # from its cause" vs "raised exceptions to document") — so its order is free.
    "the unchained re-raise to chain from its cause": "raise-from",

    # A god-class / coupled class with methods that provably never touch ``self``:
    # the decouple lens's "the incidental coupling to remove" L3 phrase deepens into
    # this concrete, EXECUTABLE first slice. promote-staticmethod LANDS the
    # ``@staticmethod`` promotion on each such self-free method (two AST line edits:
    # +``@staticmethod`` and a dropped leading ``self``) — a real coupling-surface
    # reduction that changes NO call site (a ``@staticmethod`` stays a class
    # attribute, so ``self.m()``/``Cls.m()``/``inst.m()`` all keep resolving).
    # THE OVER-CLAIM GUARD: it does NOT reduce the method count or split
    # responsibilities (the full decomposition into collaborators stays a design
    # task), so the phrase names the @staticmethod promotion, never a decomposition.
    # Its refusal set blocks anything unsafe (uses-self / decorated / dunder /
    # classmethod / non-self-first / super / name-defined-in->1-class (override/MRO)
    # / name-as-string-literal (dynamic) / nested-class), and a class with no
    # self-free method is an HONEST no-op. Routed through the same suite-gated,
    # auto-rollback engine. Its phrasing ("self-free methods to promote to
    # staticmethod") is not a substring of any other key (nor any of them of it), so
    # its order is free.
    "the self-free methods to promote to staticmethod": "promote-staticmethod",

    # Legacy typing spellings: the "signatures and types" / modernize lens's
    # PEP-585/604 sub-aspect names a module whose ANNOTATIONS still spell
    # ``typing.List[x]`` / ``Optional[X]`` / ``Union[A, B]`` instead of the modern
    # builtins (``list[x]``) and ``|`` union. The modernize-typing objective LANDS
    # exactly that migration in ANNOTATION positions, gated by the SAME
    # ``from __future__ import annotations`` the add-from-future-annotations facet
    # establishes (under PEP 563 the deferred annotations are version-safe on any
    # parsing Python) — so the natural composition is "make lazy with a future
    # import" first, then "upgrade the typing imports". It refuses without the gate,
    # on a star/aliased/shadowed binding, and on a ``Tuple[()]`` / string-literal
    # annotation; an expression-position typing use is never touched. Routed through
    # the same suite-gated, auto-rollback engine. THREE distinct phrasings reach it;
    # none is a substring of any other key (nor any of them of it) — in particular
    # none contains the broader ``modernize`` key — so their insertion order is free.
    "the typing imports to upgrade to pep 585 and pep 604": "modernize-typing",
    "pep 585 generics": "modernize-typing",
    "optional to union syntax": "modernize-typing",
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


def facet_objective_value(phrase: str) -> float:
    """The BUYER VALUE of the develop objective ``phrase`` routes to, or 0.0.

    Routes ``phrase`` through :func:`facet_to_objective`, then reads the shared
    ``move_value`` model via ``move_value.objective_value`` — so a facet that
    NAMES a concrete high-value contribution ("the function the red test calls" →
    tdd-implement, value 1.0) scores higher than one naming a low-value tidy, and
    a phrase that routes to NOTHING scores 0.0. The single place the facet zoom
    asks "how much would a buyer value finishing this facet?", grounded in the
    same value table the move loop uses (Layers a and b never disagree).
    Deterministic and pure: a fixed-map lookup, no clock/randomness."""
    from app.engine.move_value import objective_value

    objective = facet_to_objective(phrase)
    if objective is None:
        return 0.0
    return objective_value(objective)


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
