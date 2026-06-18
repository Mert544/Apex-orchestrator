from __future__ import annotations

# Eagerly bind the behaviour-preserving simplification submodules as package
# attributes so a single ``from app.execution.semantic import transforms as _t``
# import makes ``_t.<name>`` resolve without each consumer re-listing every
# module. This consolidates the formerly-duplicated per-transform import list
# that ``idea_action_bridge`` and ``simplification_scan`` each carried. Pure,
# offline, stdlib-only; no transform module imports this package, so there is no
# import cycle. The names are re-exported only for attribute access (the dispatch
# tables / scanner still reference the exact same callables).
from app.execution.semantic.transforms import (  # noqa: F401
    augmented_assign,
    chained_comparison,
    collection_literal,
    dict_get_default,
    dict_literal,
    double_not,
    fstring,
    isinstance_merge,
    membership_set,
    merge_nested_if,
    mutable_defaults,
    not_in_simplify,
    or_default,
    percent_string_concat,
    redundant_else,
    redundant_lambda,
    set_literal,
    simplify_comparison,
    startswith_tuple,
    swap_via_tuple,
    tuple_membership,
    unreachable_cleanup,
)
