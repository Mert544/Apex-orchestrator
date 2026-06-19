"""End-to-end proof for the two newly-wired safe simplification transforms:
``collection_literal`` (empty ``dict()``/``list()``/``tuple()`` -> literal) and
``fstring`` (drop a dead, placeholder-less ``f`` prefix).

Both are behaviour-preserving, self-validating (refuse via ``None``), pure
3-arg ``apply(rel, src, title)`` transforms. These tests prove the whole
develop-loop wiring for them:

  scanner detects the opportunity → seeder emits an executable-labelled root →
  bridge plans/dispatches an executable action that routes to the right
  transform and runs through the SAME guarded apply gate (mode policy →
  snapshot → write → verify → auto-rollback).

Mirrors the existing ``test_simplification_scan`` / ``test_bridge_new_transforms``
patterns. Deterministic: fixed sources, no time/random.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder
from app.models.idea import ActionStep
from app.tools.project_profile import ProjectProfile
from app.tools.simplification_scan import scan_simplifications


# (fact_label, transform key, action_type, transform_type the transform stamps,
#  a source it WILL rewrite, a source it will REFUSE).
_NEW = {
    "collection_literal": (
        "collection-literal",
        "collection_literal",
        "collection_literal",
        "modernize_collection_literal",
        "x = dict()\ny = list()\nz = tuple()\n",
        # dict(a=1) carries a real arg; set() has no empty literal -> refuse.
        "x = dict(a=1)\ny = set()\n",
    ),
    "fstring_no_placeholder": (
        "fstring-no-placeholder",
        "fstring",
        "fstring_no_placeholder",
        "fix_fstring_no_placeholder",
        'msg = f"hello world"\n',
        # A real placeholder -> must be left untouched.
        'msg = f"hi {name}"\n',
    ),
    "or_default": (
        "or-default",
        "or_default",
        "or_default",
        "or_default",
        "def f(a, b):\n    return a if a else b\n",
        # A non-pure test (a call, evaluated for side effects) -> must be refused.
        "def f(b):\n    return g() if g() else b\n",
    ),
}


# --- scanner ---------------------------------------------------------------

def test_scanner_detects_collection_literal(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("x = dict()\n", encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    hit = next(o for o in opps if o["fact_label"] == "collection-literal")
    assert hit["module"] == "m.py"
    assert hit["transform"] == "collection_literal"


def test_scanner_detects_fstring_no_placeholder(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text('msg = f"hello"\n', encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    hit = next(o for o in opps if o["fact_label"] == "fstring-no-placeholder")
    assert hit["module"] == "m.py"
    assert hit["transform"] == "fstring_no_placeholder"


def test_scanner_refuses_when_no_opportunity(tmp_path: Path) -> None:
    # dict(a=1) and a real placeholder f-string: neither transform fires.
    (tmp_path / "clean.py").write_text(
        'x = dict(a=1)\nmsg = f"hi {x}"\n', encoding="utf-8")
    labels = {o["fact_label"] for o in scan_simplifications(tmp_path)}
    assert "collection-literal" not in labels
    assert "fstring-no-placeholder" not in labels


# --- seeder family ---------------------------------------------------------

def test_seeder_emits_executable_root_for_each_new_label() -> None:
    for _key, (fact_label, transform, *_rest) in _NEW.items():
        profile = ProjectProfile(root=".", ci_files=["ci.yml"])
        profile.simplification_opportunities = [
            {"module": "app/x.py", "transform": transform,
             "fact_label": fact_label},
        ]
        roots = IdeaSeeder().seed(profile)
        # The simplification root carries a ``::simplify-<transform>`` subject
        # suffix (additive — never deduped by a family owning the bare module),
        # but the bridge still resolves the file from the part before ``::``.
        hit = next(r for r in roots if r.subject == f"app/x.py::simplify-{transform}")
        assert hit.operator == "root"
        assert hit.depth == 0
        assert hit.title == f"Apply {transform} to simplify app/x.py"
        assert any(fact_label in f for f in hit.source_facts)
        # No 'untested' token (would mis-route to a test action).
        assert "untested" not in hit.source_facts[0]


# --- bridge registration ---------------------------------------------------

def test_new_labels_route_to_executable_action() -> None:
    dispatch = IdeaActionBridge._simplify_dispatch()
    for action_type, (fact_label, _t, mapped, *_rest) in _NEW.items():
        # Registered in BOTH the strategy hint table and the direct dispatch.
        assert action_type in IdeaActionBridge._ACTION_STRATEGY, action_type
        assert action_type in dispatch, action_type
        hint = IdeaActionBridge._ACTION_STRATEGY[action_type]
        assert isinstance(hint, list) and hint and hint[0]
        # The seeding fact maps to this action_type and is executable.
        assert fact_label in _FACT_ACTIONS, fact_label
        mapped_action, _desc, executable = _FACT_ACTIONS[fact_label]
        assert mapped_action == action_type == mapped
        assert executable is True


def test_planned_idea_for_new_label_is_executable() -> None:
    # A seeded root for each new label plans an EXECUTABLE step routed to the
    # right action_type with the module as its target.
    for _key, (fact_label, transform, mapped, *_rest) in _NEW.items():
        profile = ProjectProfile(root=".", ci_files=["ci.yml"])
        profile.simplification_opportunities = [
            {"module": "app/x.py", "transform": transform,
             "fact_label": fact_label},
        ]
        root = next(r for r in IdeaSeeder().seed(profile)
                    if r.subject == f"app/x.py::simplify-{transform}")
        step = IdeaActionBridge().plan_idea(root)
        assert step.executable is True, fact_label
        assert step.action_type == mapped, fact_label
        # The bridge resolves the target file from the part before ``::``, so the
        # additive subject suffix does not disturb where the transform applies.
        assert step.target == "app/x.py", fact_label


# --- bridge dispatch behaviour --------------------------------------------

def _step(action_type: str, target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.0", title="t", operator="root", subject=target,
        action_type=action_type, target=target, executable=True,
    )


def test_dispatch_returns_patch_on_match(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type, (_f, _t, _m, transform_type, match_src, _no) in _NEW.items():
        rel = f"{action_type}_match.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        result = bridge._generate(_step(action_type, rel), str(tmp_path))
        assert result is not None, action_type
        assert result.transform_type == transform_type, action_type
        pr = result.patch_requests[0]
        assert pr["path"] == rel
        assert pr["new_content"] != match_src
        assert pr["expected_old_content"] == match_src
        ast.parse(pr["new_content"])


def test_dispatch_returns_none_on_non_match(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type, (*_pre, no_src) in _NEW.items():
        rel = f"{action_type}_nomatch.py"
        (tmp_path / rel).write_text(no_src, encoding="utf-8")
        assert bridge._generate(_step(action_type, rel), str(tmp_path)) is None, action_type


def test_dispatch_returns_none_on_missing_file(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type in _NEW:
        assert bridge._generate(
            _step(action_type, "missing.py"), str(tmp_path)) is None, action_type


def test_dispatch_returns_none_on_non_python_target(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    rel = "notes.txt"
    (tmp_path / rel).write_text("x = dict()\n", encoding="utf-8")
    assert bridge._generate(_step("collection_literal", rel), str(tmp_path)) is None


# --- the guarded apply gate, end-to-end -----------------------------------

def test_new_transforms_apply_through_guarded_gate(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type, (_f, _t, _m, transform_type, match_src, _no) in _NEW.items():
        rel = f"{action_type}_apply.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="autonomous")
        assert out["applied"] is True, action_type
        assert out["transform_type"] == transform_type, action_type
        written = (tmp_path / rel).read_text(encoding="utf-8")
        assert written != match_src, action_type
        ast.parse(written)


def test_new_transforms_verify_and_keep_on_green(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    _f, _t, _m, _tt, match_src, _no = _NEW["collection_literal"]
    rel = "mod_under_change.py"
    (tmp_path / rel).write_text(match_src, encoding="utf-8")
    out = bridge.apply_step(_step("collection_literal", rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    # Kept because the suite stayed green, but honestly NOT verified: the suite
    # never imports the changed module (coverage-aware proof, no faked green).
    assert out.get("suite_green") is True
    assert out.get("verified") is False
    assert out.get("coverage") == "none"
    assert (tmp_path / rel).read_text(encoding="utf-8") != match_src


def test_new_transforms_rollback_on_red(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_red.py").write_text(
        "def test_red():\n    assert False\n", encoding="utf-8")

    _f, _t, _m, _tt, match_src, _no = _NEW["fstring_no_placeholder"]
    rel = "mod_rollback.py"
    (tmp_path / rel).write_text(match_src, encoding="utf-8")
    out = bridge.apply_step(_step("fstring_no_placeholder", rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is False
    assert out.get("rolled_back") is True
    assert (tmp_path / rel).read_text(encoding="utf-8") == match_src


def test_new_transforms_unsafe_input_declines(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type, (*_pre, no_src) in _NEW.items():
        rel = f"{action_type}_unsafe.py"
        (tmp_path / rel).write_text(no_src, encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="autonomous", verify=True, run_tests=True)
        assert out["applied"] is False, action_type
        assert out["reason"] == "no applicable patch generated", action_type
        assert (tmp_path / rel).read_text(encoding="utf-8") == no_src, action_type


def test_new_transforms_report_mode_never_applies(tmp_path: Path) -> None:
    bridge = IdeaActionBridge()
    for action_type, (_f, _t, _m, _tt, match_src, _no) in _NEW.items():
        rel = f"{action_type}_report.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="report")
        assert out["applied"] is False, action_type
        assert (tmp_path / rel).read_text(encoding="utf-8") == match_src, action_type
