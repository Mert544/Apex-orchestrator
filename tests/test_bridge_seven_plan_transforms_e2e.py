"""End-to-end proof that the SEVEN newly-wired on-disk ``plan_*`` transforms are
genuinely EXECUTABLE, not advisory.

For each transform we prove the full develop-loop chain on a positive sample:

  1. ``scan_simplifications`` DETECTS the opportunity on a real source file and
     emits the EXACT fact-label the bridge routes (and fabricates NOTHING on a
     negative sample);
  2. ``IdeaSeeder`` turns that opportunity into an EXECUTABLE root idea whose
     fact_label maps to the transform's action;
  3. ``IdeaActionBridge.plan_idea`` yields an EXECUTABLE ``ActionStep`` whose
     ``action_type`` is the wired action;
  4. ``apply_step(verify=True)`` runs the REAL guarded gate: it APPLIES the
     rewrite when the post-write suite is green, and AUTO-ROLLS-BACK byte-for-byte
     when it is red.

Deterministic: fixed sources, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile
from app.tools.simplification_scan import scan_simplifications


# fact_label -> (action_type, a source the transform WILL act on, a source it
# will REFUSE). One row per newly-wired plan_* transform.
_SEVEN: dict[str, tuple[str, str, str]] = {
    "simplify-bool-return": (
        "simplify_bool_return",
        "def f(c):\n    if c:\n        return True\n    else:\n        return False\n",
        "def f():\n    return 1\n",
    ),
    "ternary-bool": (
        "simplify_ternary_bool",
        "def f(c):\n    return True if c else False\n",
        "def f():\n    return 1\n",
    ),
    "dict-get-ternary": (
        "simplify_dict_get",
        "def f(x, k):\n    return x[k] if k in x else 0\n",
        "def f():\n    return 1\n",
    ),
    "dict-comprehension": (
        "dict_comprehension",
        "def f(xs):\n    out = {}\n    for x in xs:\n        out[x] = x + 1\n    return out\n",
        "def f():\n    return 1\n",
    ),
    "ordering-negation": (
        "simplify_negated_comparison",
        "def f(a, b):\n    return not a < b\n",
        "def f():\n    return 1\n",
    ),
    "pointless-pass": (
        "remove_pointless_pass",
        "def f():\n    x = 1\n    pass\n    return x\n",
        "def f():\n    return 1\n",
    ),
    "assert-tuple": (
        "fix_assert_tuple",
        'def f(c):\n    assert (c, "msg")\n',
        "def f():\n    return 1\n",
    ),
}


def test_seven_facts_route_to_executable_actions() -> None:
    """Each new fact-label is registered, executable, and points at its action."""
    for fact_label, (action_type, *_rest) in _SEVEN.items():
        assert fact_label in _FACT_ACTIONS, fact_label
        mapped_action, _desc, executable = _FACT_ACTIONS[fact_label]
        assert mapped_action == action_type, fact_label
        assert executable is True, fact_label
        # And the action actually has a dispatch entry (truly runnable).
        assert action_type in IdeaActionBridge._simplify_dispatch(), action_type
        assert action_type in IdeaActionBridge._ACTION_STRATEGY, action_type


def test_scanner_detects_each_on_match_and_refuses_on_nonmatch(tmp_path: Path) -> None:
    """The deterministic scanner emits the wired fact-label for a matching file
    and fabricates nothing for a non-matching one."""
    for fact_label, (_action, match_src, no_src) in _SEVEN.items():
        # Positive: a lone matching module is detected with the exact fact-label.
        pos = tmp_path / f"pos_{_action}"
        pos.mkdir()
        (pos / "m.py").write_text(match_src, encoding="utf-8")
        opps = scan_simplifications(pos)
        assert any(o["fact_label"] == fact_label for o in opps), fact_label
        # Two calls -> identical output (deterministic).
        assert opps == scan_simplifications(pos)

        # Negative: the same transform must NOT appear for a non-matching file.
        neg = tmp_path / f"neg_{_action}"
        neg.mkdir()
        (neg / "m.py").write_text(no_src, encoding="utf-8")
        neg_opps = scan_simplifications(neg)
        assert all(o["fact_label"] != fact_label for o in neg_opps), fact_label


def test_seeder_emits_executable_root_then_bridge_plans_executable_step() -> None:
    """A scanner opportunity becomes an EXECUTABLE seeded root, and the bridge
    plans an executable step routing to the wired action."""
    seeder = IdeaSeeder()
    bridge = IdeaActionBridge()
    for fact_label, (action_type, _match, _no) in _SEVEN.items():
        profile = ProjectProfile(root=".")
        profile.simplification_opportunities = [{
            "module": "pkg/mod.py",
            "transform": action_type,
            "fact_label": fact_label,
        }]
        roots = seeder.seed(profile)
        seeded = [r for r in roots if fact_label in "".join(r.source_facts)]
        assert seeded, fact_label
        step = bridge.plan_idea(seeded[0])
        assert step.action_type == action_type, fact_label
        assert step.executable is True, fact_label
        assert step.target == "pkg/mod.py", fact_label


def _step(bridge: IdeaActionBridge, fact_label: str, target: str):
    profile = ProjectProfile(root=".")
    action_type = _SEVEN[fact_label][0]
    profile.simplification_opportunities = [{
        "module": target, "transform": action_type, "fact_label": fact_label,
    }]
    roots = IdeaSeeder().seed(profile)
    seeded = [r for r in roots if fact_label in "".join(r.source_facts)][0]
    return bridge.plan_idea(seeded)


def test_each_applies_through_real_gate_and_keeps_on_green(tmp_path: Path) -> None:
    """Driving the step the SEEDER produced, the real apply gate writes the
    rewrite and KEEPS it when the post-write suite is green."""
    import ast

    bridge = IdeaActionBridge()
    for fact_label, (_action, match_src, _no) in _SEVEN.items():
        root = tmp_path / f"green_{_action_of(fact_label)}"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8")
        rel = "pkg/mod.py"
        (root / "pkg").mkdir()
        (root / rel).write_text(match_src, encoding="utf-8")

        step = _step(bridge, fact_label, rel)
        out = bridge.apply_step(step, str(root), mode="autonomous",
                                verify=True, run_tests=False)
        assert out["applied"] is True, fact_label
        assert out.get("rolled_back") is False, fact_label
        assert out.get("verified") is True, fact_label
        written = (root / rel).read_text(encoding="utf-8")
        assert written != match_src, fact_label
        ast.parse(written)


def test_each_rolls_back_on_red(tmp_path: Path) -> None:
    """If the post-write suite is red, every changed file is restored byte-for-
    byte — the auto-rollback gate holds for all seven."""
    bridge = IdeaActionBridge()
    for fact_label, (_action, match_src, _no) in _SEVEN.items():
        root = tmp_path / f"red_{_action_of(fact_label)}"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_red.py").write_text(
            "def test_red():\n    assert False\n", encoding="utf-8")
        rel = "pkg/mod.py"
        (root / "pkg").mkdir()
        (root / rel).write_text(match_src, encoding="utf-8")

        step = _step(bridge, fact_label, rel)
        out = bridge.apply_step(step, str(root), mode="autonomous",
                                verify=True, run_tests=False)
        assert out["applied"] is False, fact_label
        assert out.get("rolled_back") is True, fact_label
        assert (root / rel).read_text(encoding="utf-8") == match_src, fact_label


def test_negative_sample_fabricates_nothing(tmp_path: Path) -> None:
    """On a non-matching source the step declines (no patch), nothing applied."""
    bridge = IdeaActionBridge()
    for fact_label, (_action, _match, no_src) in _SEVEN.items():
        root = tmp_path / f"none_{_action_of(fact_label)}"
        root.mkdir()
        rel = "mod.py"
        (root / rel).write_text(no_src, encoding="utf-8")
        step = _step(bridge, fact_label, rel)
        before = (root / rel).read_text(encoding="utf-8")
        out = bridge.apply_step(step, str(root), mode="autonomous",
                                verify=True, run_tests=True)
        assert out["applied"] is False, fact_label
        assert (root / rel).read_text(encoding="utf-8") == before, fact_label


def _action_of(fact_label: str) -> str:
    return _SEVEN[fact_label][0]
