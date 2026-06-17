"""Single canonical binding point for the on-disk ``plan_<name>`` transforms.

Both the develop-engine bridge (``app/engine/idea_action_bridge.py``) and the
simplification scanner (``app/tools/simplification_scan.py``) wire the SAME ~11
``plan_<name>(root, rel) -> RenamePlan`` rewrites that live under
``app/execution/``. Previously each file imported every ``plan_*`` function with
its own per-transform ``from app.execution.<mod> import plan_<name>`` line; those
two identical import lists produced seven duplicate 5-statement windows in the
project's own duplication scan.

This module imports each ``plan_*`` function EXACTLY ONCE and re-exports it as a
module attribute, so each consumer collapses its import list to a single
``from app.execution import _plan_transforms as _pt`` line and references
``_pt.plan_<name>``. Adding a future on-disk transform now touches ONLY this
module — the consumers do not re-duplicate.

The references are the SAME function objects the consumers used before, so the
dispatch tables and scanner output are byte-identical. This is a LEAF module: it
imports only from the ``app.execution.*`` transform modules and never from the
bridge or the scanner, so no import cycle is possible.
"""

from app.execution.bool_return import plan_simplify_bool_return
from app.execution.comprehension import plan_simplify_comprehension
from app.execution.dict_comprehension import plan_dict_comprehension
from app.execution.dict_get import plan_simplify_dict_get
from app.execution.fix_assert_tuple import plan_fix_assert_tuple
from app.execution.nested_with import plan_combine_nested_with
from app.execution.remove_pointless_pass import plan_remove_pointless_pass
from app.execution.simplify_bool_comparison import plan_simplify_bool_comparison
from app.execution.simplify_len_comparison import plan_simplify_len_comparison
from app.execution.simplify_negated_comparison import plan_simplify_negated_comparison
from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool
from app.execution.use_enumerate import plan_use_enumerate

# Canonical name -> callable mapping, for callers that prefer a lookup table over
# attribute access. The module attributes above remain the primary interface; this
# is the same set of callables, by identity.
#
# NOTE: this map is the ORIGINAL eleven plans, pinned as a closed set by a
# characterization test. The module ATTRIBUTES above are the primary interface
# both consumers use (``_pt.plan_<name>``), and they may be a SUPERSET of this
# map — e.g. ``plan_simplify_bool_comparison`` is bound as an attribute (and
# exported in ``__all__``) and wired by the bridge + scanner via attribute
# access, without being added to this pinned lookup table.
PLAN_TRANSFORMS = {
    "plan_simplify_bool_return": plan_simplify_bool_return,
    "plan_simplify_comprehension": plan_simplify_comprehension,
    "plan_dict_comprehension": plan_dict_comprehension,
    "plan_simplify_dict_get": plan_simplify_dict_get,
    "plan_fix_assert_tuple": plan_fix_assert_tuple,
    "plan_combine_nested_with": plan_combine_nested_with,
    "plan_remove_pointless_pass": plan_remove_pointless_pass,
    "plan_simplify_len_comparison": plan_simplify_len_comparison,
    "plan_simplify_negated_comparison": plan_simplify_negated_comparison,
    "plan_simplify_ternary_bool": plan_simplify_ternary_bool,
    "plan_use_enumerate": plan_use_enumerate,
}

# Public surface = the pinned map's plans PLUS the attribute-only additions that
# the consumers reference directly (kept out of the pinned map above).
__all__ = [*PLAN_TRANSFORMS, "plan_simplify_bool_comparison"]
