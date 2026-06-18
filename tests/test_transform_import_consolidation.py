"""Characterization tests pinning the consolidated transform-import wiring.

``idea_action_bridge`` and ``simplification_scan`` formerly each carried the same
~20-line ``from app.execution.semantic.transforms import <name>`` list; both now
reference the transforms through a single namespace import
(``from app.execution.semantic import transforms as _t``), which only works
because the transforms package ``__init__`` eagerly binds each submodule.

These tests guard that consolidation against regression: every transform a
namespace import is expected to expose must resolve as a package attribute with a
real ``apply`` (so ``_t.<name>.apply`` never silently breaks), the bridge's
dispatch table and the scanner's transform list must stay exactly the registered
shape, and the full develop-loop (scanner detects -> bridge plans -> apply_step
applies, then auto-rolls-back on a red suite) must still run end-to-end.

Deterministic: fixed sources, no time/random, no network.
"""

from __future__ import annotations

import os
import tempfile

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.execution.semantic import transforms as _t
from app.models.idea import ActionStep
from app.tools.simplification_scan import scan_simplifications

# The submodules the consolidated namespace import must expose so that
# ``_t.<name>.apply`` resolves in both consumers. (mutable_defaults is used by
# the scanner only; the rest by both files.)
_EXPECTED_TRANSFORM_NAMES = (
    "augmented_assign",
    "chained_comparison",
    "collection_literal",
    "dict_get_default",
    "dict_literal",
    "double_not",
    "fstring",
    "isinstance_merge",
    "membership_set",
    "merge_nested_if",
    "mutable_defaults",
    "not_in_simplify",
    "percent_string_concat",
    "redundant_else",
    "redundant_lambda",
    "set_literal",
    "simplify_comparison",
    "startswith_tuple",
    "swap_via_tuple",
    "tuple_membership",
    "unreachable_cleanup",
)


def test_namespace_import_exposes_every_transform_apply():
    """A bare ``import transforms as _t`` resolves every consolidated submodule
    and each exposes a callable ``apply`` (the contract both consumers rely on)."""
    for name in _EXPECTED_TRANSFORM_NAMES:
        mod = getattr(_t, name, None)
        assert mod is not None, f"_t.{name} did not resolve from the package import"
        assert callable(getattr(mod, "apply", None)), f"_t.{name}.apply is not callable"


def test_no_import_cycle_between_consolidated_modules():
    """Importing both consolidated modules (in either order) must not cycle."""
    import importlib

    for mod in ("app.tools.simplification_scan", "app.engine.idea_action_bridge"):
        assert importlib.import_module(mod) is not None
    for mod in ("app.engine.idea_action_bridge", "app.tools.simplification_scan"):
        assert importlib.import_module(mod) is not None


def test_simplify_dispatch_values_are_callable_and_reference_transforms():
    """Every dispatch entry is callable, and the direct (non-adapted) ones point
    at the same ``apply`` objects the namespace import exposes."""
    dispatch = IdeaActionBridge._simplify_dispatch()
    assert dispatch, "dispatch table is empty"
    for action_type, fn in dispatch.items():
        assert callable(fn), f"dispatch[{action_type}] is not callable"
    # A representative set of direct (un-adapted) entries must be the EXACT
    # transform.apply objects, proving the namespace rewrite kept identity.
    assert dispatch["merge_nested_if"] is _t.merge_nested_if.apply
    assert dispatch["membership_set"] is _t.membership_set.apply
    assert dispatch["tuple_membership"] is _t.tuple_membership.apply
    assert dispatch["simplify_none_compare"] is _t.simplify_comparison.apply


def test_scan_is_deterministic_and_stable():
    """Scanning the same tree twice yields the identical opportunity list.

    Scoped to ``app/execution`` (real product code the transforms actually target)
    rather than the whole repo: scanning the entire, ever-growing tree twice ran
    ~100s and flaked against the 120s timeout under parallel load. The determinism
    contract ``scan(X) == scan(X)`` holds for any X, so a bounded real subtree
    proves it identically and stays fast.
    """
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "execution")
    first = scan_simplifications(root)
    second = scan_simplifications(root)
    assert first == second
    # Shape contract: each opportunity carries the three keys the seeder reads.
    for opp in first:
        assert set(opp) == {"module", "transform", "fact_label"}


def _make_project() -> tuple[str, str, str]:
    """A throwaway project with one tuple-membership opportunity and a test that
    references the module (so verify can run a green/red suite)."""
    proj = tempfile.mkdtemp(prefix="apex_consolidation_")
    os.makedirs(os.path.join(proj, "pkg"))
    src_rel = "pkg/sample.py"
    src = (
        'def classify(x):\n'
        '    if x == "a" or x == "b" or x == "c":\n'
        '        return 1\n'
        '    return 0\n'
    )
    with open(os.path.join(proj, src_rel), "w", encoding="utf-8") as f:
        f.write(src)
    os.makedirs(os.path.join(proj, "tests"))
    with open(os.path.join(proj, "tests", "test_sample.py"), "w", encoding="utf-8") as f:
        f.write(
            "from pkg.sample import classify\n\n"
            "def test_classify():\n"
            "    assert classify('a') == 1\n"
            "    assert classify('z') == 0\n"
        )
    return proj, src_rel, src


def test_develop_loop_applies_through_consolidated_wiring():
    """Scanner detects -> bridge routes the fact -> apply_step applies, verified
    against a green suite. Proves the consolidated callables still drive the loop."""
    proj, src_rel, src = _make_project()
    opp = next(o for o in scan_simplifications(proj) if o["module"] == src_rel)
    assert opp["fact_label"] == "tuple-membership"
    action_type, _desc, executable = _FACT_ACTIONS[opp["fact_label"]]
    assert executable is True
    step = ActionStep(
        branch_path="x.1", title="t", operator="root", subject=src_rel,
        action_type=action_type, target=src_rel, executable=True,
        source_facts=[f"{opp['fact_label']}: {src_rel}"],
    )
    res = IdeaActionBridge().apply_step(
        step, proj, mode="autonomous", run_tests=False, verify=True
    )
    assert res.get("applied") is True
    assert res.get("verified") is True
    assert res.get("rolled_back") in (False, None)
    after = open(os.path.join(proj, src_rel), encoding="utf-8").read()
    assert after != src  # a real change landed


def test_develop_loop_auto_rolls_back_on_red_suite():
    """Same loop, but a forced-red suite must auto-roll-back to the exact bytes."""
    proj, src_rel, src = _make_project()
    # Break the test so the post-apply suite fails.
    with open(os.path.join(proj, "tests", "test_sample.py"), "w", encoding="utf-8") as f:
        f.write(
            "from pkg.sample import classify\n\n"
            "def test_classify():\n"
            "    assert classify('a') == 999\n"
        )
    step = ActionStep(
        branch_path="x.1", title="t", operator="root", subject=src_rel,
        action_type="tuple_membership", target=src_rel, executable=True,
        source_facts=[f"tuple-membership: {src_rel}"],
    )
    res = IdeaActionBridge().apply_step(
        step, proj, mode="autonomous", run_tests=False, verify=True
    )
    assert res.get("applied") is False
    assert res.get("rolled_back") is True
    restored = open(os.path.join(proj, src_rel), encoding="utf-8").read()
    assert restored == src  # byte-identical restore
