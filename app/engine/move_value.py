"""Buyer-value model for develop moves — the shared "zeka" spine.

A single, deterministic, append-only table answering one question both the idea
tree (``idea_permutation``) and the move loop (``objective_compiler``) need to
agree on: **how much would a buyer value this class of change?** The North Star
(`CLAUDE.md`) says Apex's job is to LAND working code — "generate real tests…
implement simple functions… complete TODO/NotImplementedError" — and to value
that *above* "modernize idioms". This module encodes exactly that thesis as a
frozen operator → value score in [0,1], grouped into three buyer tiers:

  - **Tier 1** — lands NEW working code / closes a real gap (a function body, a
    safety-net test, a wired surface). The North Star itself.
  - **Tier 2** — real structural improvement (changes behaviour-shape, not just
    bytes: extract/inline/dedup/dataclassify/drop-param).
  - **Tier 3** — surface tidy / idiom (lowest buyer value; pure ceremony:
    modernize/sort-imports/remove-pointless-pass).

Why a STATIC table and not a measured diff/size metric: it is deterministic and
zero-cost *by construction* (no plan build, no AST, no clock, no randomness), it
cannot drift with line numbers, and the tiers ARE the buyer thesis. The only
project-specific input is the operator's own *measured* reliability on this repo
(``scored_move_value``), which is neutral ``1.0`` on a fresh project — so the
static table is what a new repo sees, byte-for-byte.

Like ``_OBJECTIVE_SYNONYMS`` and ``FACET_OBJECTIVE_MAP``, the table is
APPEND-ONLY and DRIFT-TESTED (``tests/test_move_value.py``): every operator any
move generator emits — built-in (``objective_compiler``) or self-registered
(``app/execution/objectives/*``) — must carry a tier, so adding an operator can
only ADD a value, never silently re-rank a built-in. Stdlib-only, no LLM.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "move_value",
    "scored_move_value",
    "objective_value",
    "OPERATOR_VALUE",
    "OBJECTIVE_OPERATOR",
    "DEFAULT_VALUE",
]


# Operator string (as set on ``Move.operator`` by every move generator) -> the
# buyer value of that CLASS of change, in [0,1]. APPEND-ONLY: a new operator adds
# a row; an existing row's value is part of the frozen contract two layers share.
OPERATOR_VALUE: dict[str, float] = {
    # --- TIER 1 — lands NEW working code / closes a real gap (the North Star) ---
    "implement_stub": 1.00,          # synthesise a test-pinned function body
    "tdd_implement": 1.00,           # write the not-yet-written function a red test calls
    "implement_from_doctest": 1.00,  # synthesise a body from the stub's own doctest examples
    "js_tdd_implement": 1.00,        # write the JS function a red jest test calls (first non-Python landing)
    "js_implement_from_jsdoc": 1.00,  # JS image of implement_from_doctest — fill a JS stub from its own jsdoc @example (no jest test)
    "scaffold_from_protocol": 0.95,  # a runnable implementer for an unimplemented protocol
    "cover_gaps": 0.90,              # first characterization test for an untested module
    "js_cover_gaps": 0.90,           # JS/TS sibling of cover_gaps — first jest characterization test for an untested function (same tier as cover_gaps)
    "wire_exports": 0.90,            # the package re-export surface (__all__ + re-exports)
    "js_wire_exports": 0.90,         # JS/TS sibling of wire_exports — add a missing ESM export (same tier as wire_exports)
    "strengthen_tests": 0.88,        # a mutant-killing assertion the suite was missing
    "js_strengthen_tests": 0.80,     # JS/TS LITE sibling of strengthen_tests — kill a mutant the fn's MINED jest witnesses miss with an env-gated assertion (below cover_gaps 0.90 / strengthen_tests 0.88: strengthens against MINED witnesses, NOT full-suite blind spots — no per-mutant suite run)
    "wire_module_exports": 0.80,     # declare a leaf module's explicit __all__
    "infer_type_hints": 0.72,        # PROVABLE return-type hints (never a guess)
    "annotate_self_returns": 0.70,   # PROVABLE -> "<Class>" self/cls return-type forward-ref (a return-type the literal oracle refuses; infer_type_hints' tier)
    "pin_doctest": 0.70,             # turn worked >>> examples into a suite-enforced test
    "document_signature": 0.68,      # a docstring with proven Returns: type
    "document_raises": 0.68,         # a docstring Raises: set from proven literal raise <Name>(...) (Python sibling of document_raises_jsdoc)
    "document_export_jsdoc": 0.68,   # the JS/TS sibling: a JSDoc with a proven @returns {T} (same tier as document_signature)
    "js_document_param_types": 0.68,  # the missing half of document_export_jsdoc: a JSDoc with @param {T} from declared param types (same tier)
    "document_param": 0.68,          # the Python mirror of js_document_param_types: an Args: section with name (T): lines from declared param annotations verbatim (same doc-surface cluster tier)
    "document_attributes": 0.68,     # the CLASS-ATTRIBUTE sibling of document_returns: an Attributes: section with name (T) lines from class-level AnnAssign annotations verbatim (same doc-surface existing-docstring-splice tier)
    "document_yields": 0.68,         # the GENERATOR sibling of document_returns: a Yields: section rendering the element type of a subscripted iterator/generator return verbatim, fired where document_returns refuses (same doc-surface tier)
    "document_raises_jsdoc": 0.68,   # JSDoc @throws set from proven throw-new-Identifier (the failure-contract sibling of document_export_jsdoc / js_document_param_types)
    "js_document_returns_inferred": 0.68,  # JSDoc @returns {T} inferred from a function's own literal return statements — for PLAIN JS the typed doc family can't serve (fires only when no TS return is declared; disjoint from document_export_jsdoc; same doc-surface cluster tier)
    "pin_return_type": 0.66,         # one Returns: <T> line spliced into an EXISTING docstring from the proven return oracle (a doc-surface line, not a minted docstring — generate_usage_doc's tier, below the docstring-MINTING document_signature/document_raises)
    "document_returns": 0.66,        # a :returns:/Returns: section spliced into an EXISTING docstring from the DECLARED return annotation verbatim (the annotation-sourced, style-matching sibling of pin_return_type; same doc-surface existing-docstring-splice tier)
    "java_document_throws": 0.66,    # a Javadoc with @throws lines from a method's DECLARED throws clause (the Java sibling of document_raises_jsdoc; doc-surface tier — a comment-only, behaviour-identical insert)
    "java_document_param": 0.66,     # a Javadoc with bare @param <name> lines from a method's DECLARED parameters (the Java mirror of document_param / js_document_param_types; same doc-surface tier — a comment-only, behaviour-identical insert)
    "java_document_returns": 0.66,   # a Javadoc with one @return <type> line from a method's DECLARED return type read verbatim off the source span (the Java mirror of document_returns / js_document_returns_inferred; same doc-surface tier — a comment-only, behaviour-identical insert)
    "generate_usage_doc": 0.66,      # a USAGE.md from the public API (oracle-checked)
    "harden": 0.65,                  # land a real security fix per finding — Tier-1 rewrites the vulnerability away (eval/os.system/yaml/bare-except/hashlib-new), Tier-0 annotates a reviewable # SECURITY comment where no safe auto-rewrite exists (pickle/sql/tempfile/popen/tls/zip-slip/weak-hash)
    "raise_from": 0.64,              # chain a re-raised exception to its cause (raise X(...) from err — the B904 fix): a real but small behaviour-preserving traceback-hygiene fix, below the doc-surface cluster
    # --- TIER 2 — real structural improvement (behaviour-shape, not just bytes) ---
    "dedup_extract": 0.60,           # lift a duplicated block into a shared helper
    "dedup_total_return": 0.60,      # lift an always-returning duplicate block
    "dedup_guarded_return": 0.60,    # lift a guard-return+fall-through duplicate block (sentinel projection)
    "dedup_parameterized": 0.60,     # lift near-duplicate variants into one helper
    "dedup_parameterized_total_return": 0.60,  # lift an always-returning near-duplicate group into one helper (dedup_parameterized's total-return sibling)
    "dedup_parameterized_guarded_return": 0.60,  # lift a guard-return near-duplicate group into one sentinel-projecting helper (dedup_parameterized's guarded-return sibling)
    "extract": 0.55,                 # extract a helper from a long function
    "dataclassify": 0.50,            # boilerplate __init__ -> @dataclass
    "synthesize_dunders": 0.50,      # canonical __repr__/__eq__/__hash__ over a class's proven field set (dataclassify's sibling)
    "seal_total_ordering": 0.50,     # @functools.total_ordering fills 3 comparison ops from one (synthesize_dunders' comparison-dunder sibling)
    "seal_hashable_eq": 0.50,        # canonical __hash__ restoring set/dict usability where __eq__ made instances unhashable (synthesize_dunders' hash sibling)
    "inline": 0.45,                  # fold a single-use helper back into its caller
    "promote_staticmethod": 0.45,    # promote a class's self-free methods to @staticmethod (a real coupling-surface decoupling that changes no call site; the full responsibility-split stays a design task)
    "extract_guard_clause": 0.45,    # flatten nesting into early-exit guards
    "guard_clause": 0.45,            # a trailing-guard-after-setup rewrite
    "freeze_dataclass": 0.45,        # add frozen=True to a never-mutated dataclass
    "add_slots": 0.45,               # add __slots__ to a closed-attribute class
    "add_dataclass_order": 0.45,     # add order=True to a @dataclass with no comparison dunder (freeze_dataclass's orderable sibling)
    "extract_constant": 0.42,        # name a repeated magic literal
    "drop_param": 0.40,              # drop a never-read parameter
    "remove_dead_code": 0.40,        # delete statically unreachable code
    "remove_unreachable_after_terminator": 0.40,  # drop code after return/raise/break
    "merge_duplicate_imports": 0.35,  # collapse repeated from-imports
    "add_final": 0.34,               # seal a never-subclassed class with @final
    "java_finalize_field": 0.34,     # Java sibling of add_final: seal a never-reassigned private field with `final` (same runtime-noop tier)
    "java_final_parameter": 0.34,    # parameter-level sibling of java_finalize_field: seal a never-reassigned method/constructor parameter with `final` (same runtime-noop tier — a stronger soundness case, since a parameter's assignment surface is closed to its own method body)
    "java_final_local": 0.34,        # local-variable sibling of java_final_parameter: seal a never-reassigned direct-block-statement local with `final` (same runtime-noop tier — a local's assignment surface is likewise closed to its own method body; refuses for/enhanced-for/try-resources/no-initializer shapes)
    "finalize_module_constant": 0.34,  # Python sibling of add_final: seal a never-rebound top-level UPPER_SNAKE literal module constant with typing.Final (same runtime-noop tier — CPython does not enforce Final; the false-final risk is closed by a whole-project rebind scan, tests-incl)
    "seal_final_method": 0.34,       # seal a never-overridden method with @final
    "enforce_enum_unique": 0.34,     # lock an all-distinct Enum with @enum.unique
    "complete_match_exhaustiveness": 0.34,   # fill a closed-set dispatch's missing arm with a loud exhaustiveness sentinel
    "add_from_future_annotations": 0.32,  # lazy annotations via a __future__ import
    "add_functools_wraps": 0.32,     # @functools.wraps(callee) on a decorator-factory wrapper missing it (metadata-only, behaviour-identical — same tier as add_from_future_annotations)
    "modernize_typing": 0.42,        # land PEP 585/604 annotation modernization (typing.List[x]->list[x], Optional[X]->X | None) — future-import-gated; a real annotation rewrite, sits with the annotation/structural modernizers above the bare-idiom tidies
    # --- TIER 3 — surface tidy / idiom (lowest buyer value; pure ceremony) ---
    "modernize": 0.25,               # == None -> is None, dead f-prefix, dict()/list()
    "fix_fstring": 0.25,             # drop dead f-string prefixes (modernize family)
    "fix_collection": 0.25,          # empty-constructor -> collection literal (modernize family)
    "remove_redundant_fstring": 0.24,  # strip an f-prefix with no placeholders
    "fix_not_in_is": 0.24,           # not a in b -> a not in b
    "fix_assert_tuple": 0.24,        # close the always-true assert-tuple bug
    "simplify_bool_return": 0.22,    # if c: return True ... -> return c
    "simplify_ternary_bool": 0.22,   # ternary returning a bool -> the bool
    "remove_redundant_else": 0.22,   # drop a redundant else after a terminating branch
    "simplify_comprehension": 0.22,  # accumulator loop -> comprehension
    "dict_comprehension": 0.22,      # accumulator loop -> dict comprehension
    "simplify_dict_get": 0.22,       # if k in d: ... else: ... -> d.get(k, default)
    "merge_nested_if": 0.22,         # collapse nested if into one `and` guard
    "merge_isinstance": 0.21,        # merge isinstance or-chain into one call
    "chain_comparison": 0.21,        # a < b and b < c -> a < b < c
    "simplify_negated_comparison": 0.21,  # not (a < b) -> a >= b
    "simplify_len_comparison": 0.21,  # len(x) > 0 -> truthiness
    "simplify_bool_comparison": 0.21,  # x == True -> x
    "collapse_startswith": 0.20,     # startswith/endswith or-chain -> one tuple call
    "combine_nested_with": 0.20,     # nested with -> one with
    "combine_augmented_assign": 0.20,  # x = x + 1 -> x += 1
    "remove_unused_imports": 0.20,   # drop a dead top-level import
    "remove_double_negation": 0.20,  # not not x -> bool(x)
    "use_enumerate": 0.20,           # manual index loop -> enumerate
    "set_literal": 0.20,             # set([...]) -> {...}
    "fold_literal_string_concat": 0.20,  # "a" "b" -> "ab"
    "dedup_dunder_all": 0.20,        # de-dup an existing __all__, keep first-seen order
    "percent_to_fstring": 0.19,      # %-format -> f-string
    "format_to_fstring": 0.19,       # str.format(spec) -> f-string
    "fstring_convert": 0.19,         # str.format placeholder -> f-string
    "sort_imports": 0.18,            # sort the import block
    "sort_dunder_all": 0.18,         # sort + de-dup an existing __all__
    "remove_pointless_pass": 0.15,   # drop a redundant pass
}

# An unknown / newly-registered operator lands MID-TIER — never 0, so the move
# loop never STARVES a brand-new ability before the drift test catches it (the
# table is the prior, not a gate). Matches the "no starvation" soundness clause.
DEFAULT_VALUE = 0.30


# Built-in objective NAME -> the operator its moves emit, for the FEW built-ins
# whose objective name is not its operator's dash form. Self-registered specs
# (``app/execution/objectives/*``) all map name->operator by dash->underscore
# (drift-tested), so they need no row here — ``objective_value`` derives them.
OBJECTIVE_OPERATOR: dict[str, str] = {
    "dead-params": "drop_param",
    "shrink-functions": "extract",
    "inline-helpers": "inline",
    "dedup": "dedup_extract",
    "modernize": "modernize",
    "simplify-bool-return": "simplify_bool_return",
    "simplify-comprehension": "simplify_comprehension",
    "extract-constant": "extract_constant",
    "remove-unused-imports": "remove_unused_imports",
    "sort-imports": "sort_imports",
    "remove-dead-code": "remove_dead_code",
}


def move_value(operator: str) -> float:
    """The buyer value of an operator's class of change, in [0,1].

    A frozen dict lookup — deterministic, zero-cost, no IO/clock/randomness. An
    operator with no tier returns :data:`DEFAULT_VALUE` (mid-tier), so a new
    ability is never starved before its drift test lands."""
    return OPERATOR_VALUE.get(operator, DEFAULT_VALUE)


def scored_move_value(operator: str, memory: Any | None = None,
                      realization: dict[str, float] | None = None) -> float:
    """:func:`move_value` scaled by the operator's MEASURED reliability on this
    project — the value analogue of the objective board's Wilson reliability.

    Multiplies the static prior by ``memory.feasibility_factor(operator)`` (the
    same bounded ±10% nudge ``rank_objectives`` already trusts, clamped, neutral
    ``1.0`` for too-few samples). With no memory — a fresh project, or a unit
    test driving the value directly — the factor is ``1.0``, so the result is
    byte-identical to the static table. Clamped to ``1.0`` and rounded for a
    stable, total ordering.

    A SUBORDINATE, demote-only VALUE-REALIZATION multiplier layers on when a
    precomputed ``realization`` factors map is passed in (built by
    ``value_reliability.operator_realization_factors`` from the proof-of-fix
    history — passed as DATA, never imported here, so this stays a pure leaf): it
    corrects the static prior by how much value an operator PROVENLY realized
    (verified-and-held) here. Each factor is in ``[_REALIZATION_FLOOR, 1.0]`` — at
    most neutral, at worst damped — so it can only DEMOTE an over-promiser and
    never inflate selection off unverified work. With no map (a fresh repo / no
    proofs) or an untracked operator the factor is ``1.0`` too, so the result
    stays byte-identical to the static table. Both multipliers are
    neutral-default; the product is re-clamped to ``1.0`` and rounded, so the
    ``[0,1]`` range and determinism are unchanged."""
    base = move_value(operator)
    factor = memory.feasibility_factor(operator) if memory is not None else 1.0
    if realization and operator:
        factor *= realization.get(operator, 1.0)
    return round(min(1.0, base * factor), 4)


def objective_value(objective: str) -> float:
    """The buyer value of a develop OBJECTIVE, by its name — the bridge the idea
    tree uses (it routes by objective name, the move loop by operator).

    Resolves the objective's operator (the explicit built-in map, else the
    self-registering dash->underscore convention) and returns its
    :func:`move_value`. An unknown objective lands at :data:`DEFAULT_VALUE`, like
    an unknown operator."""
    operator = OBJECTIVE_OPERATOR.get(objective, objective.replace("-", "_"))
    return move_value(operator)
