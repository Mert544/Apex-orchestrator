"""Proof for the ``or_default`` safe simplification transform:
``a if a else b`` -> ``a or b``.

The rewrite is behaviour-preserving ONLY when the ternary's test and true-branch
are the SAME side-effect-free expression (a Name or an attribute chain): the
ternary evaluates ``a`` twice (once as the test, once as the returned value)
where ``a or b`` evaluates it once, so a pure ``a`` makes them value-identical.
A non-pure test (call/subscript/bool-op) must be REFUSED — that is the
false-positive-free contract these tests pin.

This file proves: the transform fires + is byte-correct + characterization-
preserving on a match; declines (None) on every unsafe/non-matching case; and the
bridge plans it as an executable step targeting the right module.

Deterministic: fixed sources, no time/random.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder
from app.execution.semantic.transforms import or_default
from app.models.idea import ActionStep
from app.tools.project_profile import ProjectProfile
from app.tools.simplification_scan import scan_simplifications


# --- the transform itself --------------------------------------------------

def test_fires_on_name_self_default() -> None:
    src = "def f(a, b):\n    return a if a else b\n"
    result = or_default.apply("m.py", src, "t")
    assert result is not None
    assert result.transform_type == "or_default"
    pr = result.patch_requests[0]
    assert pr["path"] == "m.py"
    assert pr["expected_old_content"] == src
    assert pr["new_content"] == "def f(a, b):\n    return a or b\n"
    ast.parse(pr["new_content"])


def test_fires_on_attribute_chain_self_default() -> None:
    src = "def f(o, b):\n    return o.x.y if o.x.y else b\n"
    result = or_default.apply("m.py", src, "t")
    assert result is not None
    assert result.patch_requests[0]["new_content"] == (
        "def f(o, b):\n    return o.x.y or b\n"
    )


def test_byte_correct_inside_assignment() -> None:
    src = "def f(name):\n    label = name if name else 'anon'\n    return label\n"
    result = or_default.apply("m.py", src, "t")
    assert result is not None
    assert result.patch_requests[0]["new_content"] == (
        "def f(name):\n    label = name or 'anon'\n    return label\n"
    )


# --- characterization: identical runtime behaviour before/after ------------

def _run(src: str, *args):
    ns: dict = {}
    exec(compile(src, "<char>", "exec"), ns)  # noqa: S102 - fixed local source
    return ns["f"](*args)


def test_characterization_behaviour_preserved() -> None:
    before = "def f(a, b):\n    return a if a else b\n"
    result = or_default.apply("m.py", before, "t")
    assert result is not None
    after = result.patch_requests[0]["new_content"]
    # Truthy a -> a; falsy a -> b; across types, identical results both ways.
    for a, b in [(5, 9), (0, 9), ("x", "y"), ("", "y"), ([], [1]), ([2], [1])]:
        assert _run(before, a, b) == _run(after, a, b)


# --- declines: ZERO false rewrites on unsafe / non-matching inputs ---------

def test_declines_non_pure_call_test() -> None:
    # ``g()`` may have side effects / differ between the two evaluations.
    assert or_default.apply("m.py", "def f(b):\n    return g() if g() else b\n", "t") is None


def test_declines_subscript_test() -> None:
    # A subscript is not in the pure allow-list (may trigger __getitem__ effects).
    assert or_default.apply("m.py", "def f(d, k, b):\n    return d[k] if d[k] else b\n", "t") is None


def test_declines_when_test_differs_from_body() -> None:
    # ``a if c else b`` is NOT ``c or b`` — only the self-defaulting shape fires.
    assert or_default.apply("m.py", "def f(a, c, b):\n    return a if c else b\n", "t") is None


def test_declines_boolean_literal_ternary() -> None:
    # ``True if c else False`` belongs to ternary-bool, not here (test != body).
    assert or_default.apply("m.py", "def f(c):\n    return True if c else False\n", "t") is None


def test_declines_plain_source() -> None:
    assert or_default.apply("m.py", "def f():\n    return 1\n", "t") is None


def test_declines_syntax_error() -> None:
    assert or_default.apply("m.py", "def f(:\n", "t") is None


# --- scanner detects the opportunity with the exact fact-label -------------

def test_scanner_detects_or_default(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(a, b):\n    return a if a else b\n", encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    hit = next(o for o in opps if o["fact_label"] == "or-default")
    assert hit["module"] == "m.py"
    assert hit["transform"] == "or_default"


def test_scanner_skips_non_pure_test(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(b):\n    return g() if g() else b\n", encoding="utf-8")
    labels = {o["fact_label"] for o in scan_simplifications(tmp_path)}
    assert "or-default" not in labels


# --- bridge: end-to-end executable plan ------------------------------------

def _step(action_type: str, target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.0", title="t", operator="root", subject=target,
        action_type=action_type, target=target, executable=True,
    )


def test_fact_routes_to_executable_action() -> None:
    mapped_action, _desc, executable = _FACT_ACTIONS["or-default"]
    assert mapped_action == "or_default"
    assert executable is True
    assert "or_default" in IdeaActionBridge._simplify_dispatch()
    assert "or_default" in IdeaActionBridge._ACTION_STRATEGY


def test_seeded_root_plans_executable_step() -> None:
    profile = ProjectProfile(root=".", ci_files=["ci.yml"])
    profile.simplification_opportunities = [
        {"module": "app/x.py", "transform": "or_default",
         "fact_label": "or-default"},
    ]
    root = next(r for r in IdeaSeeder().seed(profile)
                if r.subject == "app/x.py::simplify-or_default")
    step = IdeaActionBridge().plan_idea(root)
    assert step.executable is True
    assert step.action_type == "or_default"
    assert step.target == "app/x.py"


def test_bridge_generate_then_guarded_apply(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    rel = "or_default_match.py"
    src = "def f(a, b):\n    return a if a else b\n"
    (tmp_path / rel).write_text(src, encoding="utf-8")
    result = bridge._generate(_step("or_default", rel), str(tmp_path))
    assert result is not None
    assert result.transform_type == "or_default"
    # Run through the same snapshot/apply gate as every other transform.
    out = bridge.apply_step(_step("or_default", rel), str(tmp_path), mode="autonomous")
    assert out["applied"] is True
    assert out["transform_type"] == "or_default"
    written = (tmp_path / rel).read_text(encoding="utf-8")
    assert written == "def f(a, b):\n    return a or b\n"


def test_bridge_declines_unsafe_through_gate(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    rel = "or_default_unsafe.py"
    src = "def f(b):\n    return g() if g() else b\n"
    (tmp_path / rel).write_text(src, encoding="utf-8")
    out = bridge.apply_step(_step("or_default", rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=True)
    assert out["applied"] is False
    assert out["reason"] == "no applicable patch generated"
    assert (tmp_path / rel).read_text(encoding="utf-8") == src
