"""Characterization tests for the shared ``plan_*`` binding module.

The on-disk ``plan_<name>(root, rel) -> RenamePlan`` transforms used to be
imported with an identical per-transform ``from app.execution.<mod> import
plan_<name>`` list in BOTH ``app.engine.idea_action_bridge`` and
``app.tools.simplification_scan``. That duplicated import list produced seven
duplicate 5-statement windows in the project's own duplication scan.

The refactor consolidated those imports into a single leaf module,
``app.execution._plan_transforms``, that imports each ``plan_*`` function ONCE
and re-exports it. Both consumers now reference ``_pt.plan_<name>``.

These tests pin the refactor's contract:

  * the shared module is a LEAF (no import cycle back to its consumers);
  * every ``plan_*`` callable both consumers wire is the SAME function object as
    the shared module's attribute (identity, not just equality), so the bridge's
    dispatch table and the scanner's transform list are behaviour-identical;
  * a sample ``plan_*`` transform still drives the full develop-loop end to end
    (apply on green, byte-for-byte rollback on red).

Deterministic: fixed sources, no clock, no randomness.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_seeder import IdeaSeeder
from app.execution import _plan_transforms as _pt
from app.tools.project_profile import ProjectProfile
from app.tools.simplification_scan import _transforms, scan_simplifications


# action_type (bridge dispatch key) -> the shared module's attribute name.
_PLAN_DISPATCH_KEYS: dict[str, str] = {
    "combine_nested_with": "plan_combine_nested_with",
    "simplify_comprehension": "plan_simplify_comprehension",
    "use_enumerate": "plan_use_enumerate",
    "simplify_len_comparison": "plan_simplify_len_comparison",
    "simplify_bool_return": "plan_simplify_bool_return",
    "simplify_ternary_bool": "plan_simplify_ternary_bool",
    "simplify_dict_get": "plan_simplify_dict_get",
    "dict_comprehension": "plan_dict_comprehension",
    "simplify_negated_comparison": "plan_simplify_negated_comparison",
    "remove_pointless_pass": "plan_remove_pointless_pass",
    "fix_assert_tuple": "plan_fix_assert_tuple",
}

# scanner fact-label -> the shared module's attribute name (same eleven plans).
_PLAN_FACT_LABELS: dict[str, str] = {
    "nested-with": "plan_combine_nested_with",
    "comprehension": "plan_simplify_comprehension",
    "use-enumerate": "plan_use_enumerate",
    "len-comparison": "plan_simplify_len_comparison",
    "simplify-bool-return": "plan_simplify_bool_return",
    "ternary-bool": "plan_simplify_ternary_bool",
    "dict-get-ternary": "plan_simplify_dict_get",
    "dict-comprehension": "plan_dict_comprehension",
    "ordering-negation": "plan_simplify_negated_comparison",
    "pointless-pass": "plan_remove_pointless_pass",
    "assert-tuple": "plan_fix_assert_tuple",
}


def _unwrap(closure):
    """Extract the ``plan_*`` callable captured by ``plan_to_apply(plan_fn)``."""
    freevars = closure.__code__.co_freevars
    if "plan_fn" in freevars:
        return closure.__closure__[freevars.index("plan_fn")].cell_contents
    return None


def test_shared_module_exposes_every_plan_transform() -> None:
    """The shared module binds all eleven plans as attributes AND in its map."""
    for attr in set(_PLAN_DISPATCH_KEYS.values()):
        fn = getattr(_pt, attr)
        assert callable(fn), attr
        # The canonical mapping holds the SAME object, by identity.
        assert _pt.PLAN_TRANSFORMS[attr] is fn, attr
    assert set(_pt.PLAN_TRANSFORMS) == set(_PLAN_DISPATCH_KEYS.values())


def test_no_import_cycle_in_any_order() -> None:
    """The leaf module and its two consumers import cleanly in any order."""
    names = [
        "app.execution._plan_transforms",
        "app.engine.idea_action_bridge",
        "app.tools.simplification_scan",
    ]
    for first in names:
        for mod in names:
            sys.modules.pop(mod, None)
        # Importing any one first must not deadlock or raise.
        importlib.import_module(first)
        for mod in names:
            importlib.import_module(mod)
    # The shared module must NOT import its consumers (parse the imports, so a
    # mention in the docstring does not count). Every import target must live
    # under ``app.execution.*``.
    src = Path(_pt.__file__).read_text(encoding="utf-8")
    targets: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
    assert targets, "expected the shared module to import its plan_* sources"
    for target in targets:
        assert target.startswith("app.execution"), target
        assert "idea_action_bridge" not in target
        assert "simplification_scan" not in target


def test_bridge_dispatch_references_shared_plan_objects() -> None:
    """Each plan_* dispatch entry wraps the SAME function object the shared
    module exposes — proof the consolidation changed only HOW the callable is
    referenced, not WHICH callable runs."""
    dispatch = IdeaActionBridge._simplify_dispatch()
    for action_type, attr in _PLAN_DISPATCH_KEYS.items():
        assert action_type in dispatch, action_type
        wrapped = _unwrap(dispatch[action_type])
        assert wrapped is getattr(_pt, attr), action_type


def test_scanner_transforms_reference_shared_plan_objects() -> None:
    """Each scanner plan_* transform pair wraps the SAME shared function
    object — the scanner and the bridge agree, by identity, on every plan."""
    pairs = dict(_transforms())
    for fact_label, attr in _PLAN_FACT_LABELS.items():
        assert fact_label in pairs, fact_label
        wrapped = _unwrap(pairs[fact_label])
        assert wrapped is getattr(_pt, attr), fact_label


def test_scan_simplifications_is_deterministic() -> None:
    """Two scans of the repo's own source return the identical list."""
    first = scan_simplifications(".")
    second = scan_simplifications(".")
    assert first == second


def test_sample_plan_transform_applies_then_rolls_back(tmp_path: Path) -> None:
    """A shared plan_* transform still drives the full develop-loop: it APPLIES
    when the post-write suite is green and AUTO-ROLLS-BACK byte-for-byte on red.
    """
    fact_label = "simplify-bool-return"
    action_type = "simplify_bool_return"
    match_src = (
        "def f(c):\n    if c:\n        return True\n"
        "    else:\n        return False\n"
    )

    def _step(root: Path):
        profile = ProjectProfile(root=str(root))
        profile.simplification_opportunities = [{
            "module": "pkg/mod.py",
            "transform": action_type,
            "fact_label": fact_label,
        }]
        roots = IdeaSeeder().seed(profile)
        seeded = [r for r in roots if fact_label in "".join(r.source_facts)][0]
        return IdeaActionBridge().plan_idea(seeded)

    # Green: the rewrite is applied and kept.
    green = tmp_path / "green"
    (green / "tests").mkdir(parents=True)
    (green / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (green / "pkg").mkdir()
    (green / "pkg" / "mod.py").write_text(match_src, encoding="utf-8")
    out = IdeaActionBridge().apply_step(
        _step(green), str(green), mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    written = (green / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert written != match_src
    ast.parse(written)

    # Red: the rewrite is rolled back byte-for-byte.
    red = tmp_path / "red"
    (red / "tests").mkdir(parents=True)
    (red / "tests" / "test_red.py").write_text(
        "def test_red():\n    assert False\n", encoding="utf-8")
    (red / "pkg").mkdir()
    (red / "pkg" / "mod.py").write_text(match_src, encoding="utf-8")
    out = IdeaActionBridge().apply_step(
        _step(red), str(red), mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is False
    assert out.get("rolled_back") is True
    assert (red / "pkg" / "mod.py").read_text(encoding="utf-8") == match_src
