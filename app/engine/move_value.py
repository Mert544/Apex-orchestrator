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
    "scaffold_from_protocol": 0.95,  # a runnable implementer for an unimplemented protocol
    "cover_gaps": 0.90,              # first characterization test for an untested module
    "wire_exports": 0.90,            # the package re-export surface (__all__ + re-exports)
    "strengthen_tests": 0.88,        # a mutant-killing assertion the suite was missing
    "wire_module_exports": 0.80,     # declare a leaf module's explicit __all__
    "infer_type_hints": 0.72,        # PROVABLE return-type hints (never a guess)
    "pin_doctest": 0.70,             # turn worked >>> examples into a suite-enforced test
    "document_signature": 0.68,      # a docstring with proven Returns: type
    "generate_usage_doc": 0.66,      # a USAGE.md from the public API (oracle-checked)
    # --- TIER 2 — real structural improvement (behaviour-shape, not just bytes) ---
    "dedup_extract": 0.60,           # lift a duplicated block into a shared helper
    "dedup_total_return": 0.60,      # lift an always-returning duplicate block
    "dedup_parameterized": 0.60,     # lift near-duplicate variants into one helper
    "extract": 0.55,                 # extract a helper from a long function
    "dataclassify": 0.50,            # boilerplate __init__ -> @dataclass
    "inline": 0.45,                  # fold a single-use helper back into its caller
    "extract_guard_clause": 0.45,    # flatten nesting into early-exit guards
    "guard_clause": 0.45,            # a trailing-guard-after-setup rewrite
    "freeze_dataclass": 0.45,        # add frozen=True to a never-mutated dataclass
    "extract_constant": 0.42,        # name a repeated magic literal
    "drop_param": 0.40,              # drop a never-read parameter
    "remove_dead_code": 0.40,        # delete statically unreachable code
    "remove_unreachable_after_terminator": 0.40,  # drop code after return/raise/break
    "merge_duplicate_imports": 0.35,  # collapse repeated from-imports
    "add_final": 0.34,               # seal a never-subclassed class with @final
    "seal_final_method": 0.34,       # seal a never-overridden method with @final
    "enforce_enum_unique": 0.34,     # lock an all-distinct Enum with @enum.unique
    "add_from_future_annotations": 0.32,  # lazy annotations via a __future__ import
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


def scored_move_value(operator: str, memory: Any | None = None) -> float:
    """:func:`move_value` scaled by the operator's MEASURED reliability on this
    project — the value analogue of the objective board's Wilson reliability.

    Multiplies the static prior by ``memory.feasibility_factor(operator)`` (the
    same bounded ±10% nudge ``rank_objectives`` already trusts, clamped, neutral
    ``1.0`` for too-few samples). With no memory — a fresh project, or a unit
    test driving the value directly — the factor is ``1.0``, so the result is
    byte-identical to the static table. Clamped to ``1.0`` and rounded for a
    stable, total ordering."""
    base = move_value(operator)
    factor = memory.feasibility_factor(operator) if memory is not None else 1.0
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
