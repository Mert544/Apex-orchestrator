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

    # Import-block hygiene: the "decouple → import direction" sub-aspects name the
    # two mechanical import tidies. An import nothing references is dropped
    # (remove-unused-imports); an unordered import block is sorted (sort-imports).
    "an unused import": "remove-unused-imports",
    "an unsorted import block": "sort-imports",

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

    # Missing type hints: the constructive "naming and types" aspect names the
    # precise type/annotation a parameter or return ought to carry. The
    # infer-type-hints objective LANDS exactly that — a ``-> T`` / ``param: T``
    # provable from the AST (agreeing literal returns, non-None literal defaults),
    # never a guess. So the type-annotation facet becomes the campaign that
    # raises the project's type-hint coverage.
    "the precise type or annotation": "infer-type-hints",

    # Unwired public surface: the document lens's "signatures and types" aspect
    # names the package's public re-export surface. The wire-exports objective
    # LANDS exactly that — it populates an empty ``__init__.py`` with
    # ``from .module import Name`` re-exports + a complete ``__all__`` for every
    # public top-level symbol, gated by an import oracle (every export must
    # resolve) and the suite. So the "re-export surface" facet becomes the
    # campaign that makes ``from pkg import X`` work.
    "the public re-export surface to wire": "wire-exports",

    # Boilerplate constructor: the "unreachable or no-op statements" simplify
    # sub-aspect names a hand-written ``__init__`` that does nothing but copy its
    # parameters onto ``self`` — pure ceremony. The dataclassify objective LANDS
    # exactly that tidy: it adds ``@dataclass`` + fields (order/annotation/default
    # preserved, mutable defaults via ``field(default_factory=...)``) and deletes
    # the redundant ``__init__``, behaviour-equivalent and suite-gated. So the
    # "boilerplate constructor" facet becomes the campaign that modernizes it.
    "a boilerplate constructor to make a dataclass": "dataclassify",
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
