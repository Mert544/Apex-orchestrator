"""The LSP quick-fix safe registry — the moat for ``textDocument/codeAction``.

An LSP quick-fix applies a ``WorkspaceEdit`` to the editor buffer WITHOUT going
through Apex's suite-gate + auto-rollback. So the *only* transforms that may EVER
be offered here are ones that are behaviour-preserving **by construction on a lone
buffer** — no green run vouches for the edit, the buffer is all the server has.

That safe class is the intersection of three independently-checkable properties,
EVERY operator below satisfies all three (the drift test in
``tests/test_lsp_code_action.py`` re-derives the set and proves each membership):

  1. **TIDY ∩ Tier-0** — a tidy/idiom objective (``north_star_audit.classify_objectives``)
     whose operator is NOT in ``risk_tiers.BEHAVIOUR_CHANGING_OPERATORS``
     (``tier_for_operator == 0``). This drops every CONCRETE objective (implement-stub,
     harden, cover-gaps, …) and any behaviour-introducing operator. The objective
     NAME → operator bridge is the authoritative ``move_value.OBJECTIVE_OPERATOR``
     map (with the drift-tested dash→underscore fallback), NEVER a blind string-munge
     — e.g. ``inline-helpers`` → ``inline``, ``dead-params`` → ``drop_param``.
  2. **In-memory-capable** — the transform reads its subject through
     ``_transform_base.read_module_source``, so ``_plan_transforms.plan_from_source``
     can feed it the buffer string verbatim (it HONORS the ``source_override``). A
     transform that reads the file straight off disk (``sort-imports``,
     ``modernize-typing``, the ``*-dunder-all`` pair, the column-splice f-string
     pair ``percent-to-fstring``/``fstring-convert``, ``extract-constant``,
     ``remove-dead-code``) can't be driven from a buffer at all — it would silently
     no-op (or read a stale file) — so it is excluded.
  3. **Sibling-insensitive** — the plan is a pure function of ``module_rel`` alone:
     it consults NO other module for work-discovery, for ELIGIBILITY, or for
     call-site rewriting. This is the moat-critical filter, because the other two
     do NOT catch it: ``promote-staticmethod`` is TIDY+Tier-0 and reads the buffer,
     but its safety check walks the WHOLE project (``_build_index``) to decide a
     method is safe to promote — on a lone buffer that index is blind, so it could
     offer an unsafe promotion. The cross-module family (``dedup*``, ``dead-params``,
     ``inline-helpers``, ``shrink-functions``, ``promote-staticmethod``) is excluded.

The value is ``operator -> (human-readable title, the bare plan_<x>(root, rel) fn)``.
The title is honest — it describes exactly the rewrite the transform performs (its
module docstring's thesis). The handler runs ``plan_from_source(plan_fn, rel, text)``
and offers the action ONLY when ``plan.ok`` (a refusal/no-op ⇒ empty new_contents ⇒
``ok`` False ⇒ nothing offered — the honesty gate, for free).

Deterministic, offline, zero-token, stdlib-only (``ast`` + ``plan_from_source``):
the same buffer always yields the same actions. This is a LEAF module — it imports
only the transform ``plan_<x>`` functions, never the LSP server or the engine, so
no import cycle is possible.
"""

from __future__ import annotations

from collections.abc import Callable

from app.execution.bool_return import plan_simplify_bool_return
from app.execution.chain_comparison import plan_chain_comparison
from app.execution.combine_augmented_assign import plan_combine_augmented_assign
from app.execution.comprehension import plan_simplify_comprehension
from app.execution.dict_comprehension import plan_dict_comprehension
from app.execution.dict_get import plan_simplify_dict_get
from app.execution.extract_guard_clause import plan_extract_guard_clause
from app.execution.fix_assert_tuple import plan_fix_assert_tuple
from app.execution.fix_not_in_is import plan_fix_not_in_is
from app.execution.fold_literal_string_concat import plan_fold_literal_string_concat
from app.execution.format_to_fstring import plan_format_to_fstring
from app.execution.guard_clause import plan_guard_clause
from app.execution.merge_isinstance import plan_merge_isinstance
from app.execution.merge_nested_if import plan_merge_nested_if
from app.execution.nested_with import plan_combine_nested_with
from app.execution.redundant_else import plan_remove_redundant_else
from app.execution.remove_double_negation import plan_remove_double_negation
from app.execution.remove_pointless_pass import plan_remove_pointless_pass
from app.execution.remove_redundant_fstring import plan_remove_redundant_fstring
from app.execution.remove_unreachable_after_terminator import (
    plan_remove_unreachable_after_terminator,
)
from app.execution.set_literal import plan_set_literal
from app.execution.simplify_bool_comparison import plan_simplify_bool_comparison
from app.execution.simplify_len_comparison import plan_simplify_len_comparison
from app.execution.simplify_negated_comparison import plan_simplify_negated_comparison
from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool
from app.execution.startswith_tuple import plan_collapse_startswith
from app.execution.unused_imports import plan_remove_unused_imports
from app.execution.use_enumerate import plan_use_enumerate

__all__ = ["LSP_QUICKFIX_PLANS"]


# operator -> (title, plan_<x>(project_root, module_rel) -> RenamePlan).
#
# KEYED BY THE Move.operator string (the same identity ``risk_tiers`` /
# ``move_value`` use), so the drift test can check ``tier_for_operator(op) == 0``
# and (BEHAVIOUR_CHANGING_OPERATORS ∪ CONCRETE-operators) ∩ keys == ∅ directly.
# The KEY SET equals the derived TIDY ∩ Tier-0 ∩ in-memory-capable ∩
# sibling-insensitive set (proven, not asserted, by the drift test).
LSP_QUICKFIX_PLANS: dict[str, tuple[str, Callable]] = {
    "simplify_bool_comparison": (
        "Apex: drop redundant '== True' / 'is False' boolean comparison",
        plan_simplify_bool_comparison),
    "simplify_len_comparison": (
        "Apex: simplify len() comparison to a truthiness test",
        plan_simplify_len_comparison),
    "simplify_negated_comparison": (
        "Apex: simplify 'not (a < b)' to its De Morgan inverse",
        plan_simplify_negated_comparison),
    "simplify_ternary_bool": (
        "Apex: collapse 'True if c else False' to the condition",
        plan_simplify_ternary_bool),
    "simplify_bool_return": (
        "Apex: collapse 'if c: return True / return False' to 'return c'",
        plan_simplify_bool_return),
    "simplify_comprehension": (
        "Apex: rewrite an accumulator loop as a list comprehension",
        plan_simplify_comprehension),
    "dict_comprehension": (
        "Apex: rewrite an accumulator loop as a dict comprehension",
        plan_dict_comprehension),
    "simplify_dict_get": (
        "Apex: rewrite 'x[k] if k in x else d' as 'x.get(k, d)'",
        plan_simplify_dict_get),
    "extract_guard_clause": (
        "Apex: flatten a sole-if body into an early-return guard clause",
        plan_extract_guard_clause),
    "guard_clause": (
        "Apex: flatten trailing nesting into an early-return guard clause",
        plan_guard_clause),
    "chain_comparison": (
        "Apex: chain 'a < b and b < c' into 'a < b < c'",
        plan_chain_comparison),
    "collapse_startswith": (
        "Apex: collapse a startswith/endswith or-chain into one tuple call",
        plan_collapse_startswith),
    "combine_augmented_assign": (
        "Apex: rewrite 'x = x + 1' as 'x += 1'",
        plan_combine_augmented_assign),
    "combine_nested_with": (
        "Apex: combine nested 'with' statements into one",
        plan_combine_nested_with),
    "merge_isinstance": (
        "Apex: merge an isinstance or-chain into one isinstance call",
        plan_merge_isinstance),
    "merge_nested_if": (
        "Apex: merge a nested 'if' into one 'and' guard",
        plan_merge_nested_if),
    "fix_assert_tuple": (
        "Apex: fix an always-true assert on a tuple",
        plan_fix_assert_tuple),
    "fix_not_in_is": (
        "Apex: rewrite 'not a in b' as 'a not in b'",
        plan_fix_not_in_is),
    "fold_literal_string_concat": (
        "Apex: fold adjacent string-literal concatenation into one literal",
        plan_fold_literal_string_concat),
    "format_to_fstring": (
        "Apex: convert a '...'.format(...) call into an f-string",
        plan_format_to_fstring),
    "remove_double_negation": (
        "Apex: simplify a double negation",
        plan_remove_double_negation),
    "remove_pointless_pass": (
        "Apex: remove a redundant 'pass'",
        plan_remove_pointless_pass),
    "remove_redundant_else": (
        "Apex: remove a redundant 'else' after a terminating branch",
        plan_remove_redundant_else),
    "remove_redundant_fstring": (
        "Apex: strip an 'f' prefix from a string with no placeholders",
        plan_remove_redundant_fstring),
    "remove_unreachable_after_terminator": (
        "Apex: remove unreachable code after a return/raise/break",
        plan_remove_unreachable_after_terminator),
    "remove_unused_imports": (
        "Apex: remove unused module-level imports",
        plan_remove_unused_imports),
    "set_literal": (
        "Apex: rewrite 'set([...])' as a set literal '{...}'",
        plan_set_literal),
    "use_enumerate": (
        "Apex: rewrite 'for i in range(len(seq))' using enumerate()",
        plan_use_enumerate),
}
