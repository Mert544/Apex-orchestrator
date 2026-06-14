"""Coverage-aware verification: what a green suite proves about a change."""

from __future__ import annotations

from app.engine.verification_strength import assess_strength, changed_functions


def test_changed_functions_detects_modified_and_new():
    old = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    new = "def a():\n    return 99\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
    assert changed_functions(old, new) == ["a", "c"]


def test_changed_functions_unparsable_side_is_silent():
    assert changed_functions("def broken(:\n", "def ok():\n    return 1\n") == ["ok"]


def _project(tmp_path, test_body: str):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_x.py").write_text(test_body)
    return tmp_path


def _assess(tmp_path):
    old = "def handler(x):\n    return x + 1\n"
    new = 'def handler(x):\n    """D."""\n    return x + 1\n'
    return assess_strength(tmp_path, ["app/svc.py"], {"app/svc.py": old}, {"app/svc.py": new})


def test_function_level_when_a_referencing_test_names_the_function(tmp_path):
    _project(tmp_path, "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n")
    s = _assess(tmp_path)
    assert s["level"] == "function"
    assert s["changed_functions"] == ["app/svc.py::handler"]
    assert s["function_tests"] == ["tests/test_x.py"]


def test_module_level_when_referenced_but_function_unnamed(tmp_path):
    _project(tmp_path, "import app.svc\ndef test_smoke():\n    assert app.svc is not None\n")
    s = _assess(tmp_path)
    assert s["level"] == "module"
    assert s["module_tests"] == ["tests/test_x.py"]
    assert s["function_tests"] == []


def test_none_level_when_suite_never_looks_at_the_module(tmp_path):
    _project(tmp_path, "def test_unrelated():\n    assert 1 + 1 == 2\n")
    assert _assess(tmp_path)["level"] == "none"


def test_test_change_level_when_only_tests_changed(tmp_path):
    _project(tmp_path, "def test_t():\n    assert True\n")
    s = assess_strength(tmp_path, ["tests/test_new.py"], {}, {"tests/test_new.py": "def test_n():\n    assert True\n"})
    assert s["level"] == "test-change"


def test_weakest_link_across_changed_files(tmp_path):
    # One covered file + one uncovered file -> the claim degrades to 'none'.
    _project(tmp_path, "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n")
    (tmp_path / "app" / "ghost.py").write_text("def g():\n    return 1\n")
    s = assess_strength(
        tmp_path, ["app/svc.py", "app/ghost.py"],
        {"app/svc.py": "def handler(x):\n    return x + 1\n", "app/ghost.py": "def g():\n    return 1\n"},
        {"app/svc.py": 'def handler(x):\n    """D."""\n    return x + 1\n',
         "app/ghost.py": 'def g():\n    """D."""\n    return 1\n'},
    )
    assert s["level"] == "none"


def test_apply_step_attaches_strength_and_proof_records_it(tmp_path):
    # End to end: a verified docstring fix on a module whose test names the
    # changed function is recorded as function-level verification.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_svc.py").write_text(
        "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n"
    )
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.proof_of_fix import build_proof
    from app.models.idea import IdeaNode

    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    assert res["applied"] is True
    assert res["verification_strength"]["level"] == "function"

    summary = {"mode": "supervised", "verify": True, "total_executable": 1,
               "applied": 1, "rolled_back": 0, "blocked": 0, "committed": 0,
               "results": [{"branch": "x", "action": "add_docstring", "operator": "document",
                            "label": "dependency-hub", "target": "app/svc.py", **res}]}
    record = build_proof(summary, str(tmp_path))["fixes"][0]
    assert record["verification"]["strength"]["level"] == "function"


def test_maintenance_markdown_says_what_the_suite_proves():
    from app.engine.idea_action_bridge import render_maintenance_markdown

    summary = {"mode": "supervised", "verify": True, "total_executable": 2,
               "applied": 2, "rolled_back": 0, "blocked": 0,
               "results": [
                   {"branch": "a", "action": "add_docstring", "applied": True, "verified": True,
                    "changed_files": ["app/x.py"], "target": "app/x.py",
                    "verification_strength": {"level": "function"}},
                   {"branch": "b", "action": "add_docstring", "applied": True, "verified": True,
                    "changed_files": ["app/y.py"], "target": "app/y.py",
                    "verification_strength": {"level": "none"}},
               ]}
    md = render_maintenance_markdown(summary, ".")
    assert "name the changed function" in md
    assert "⚠️ no test references this module" in md


def _shield_project(tmp_path, with_test_for_danger: bool = False):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    if with_test_for_danger:
        (tmp_path / "tests" / "test_danger.py").write_text(
            "import app.danger\ndef test_d():\n    assert app.danger is not None\n"
        )
    return tmp_path


def _harden_plan(tmp_path):
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan, ActionStep

    step = ActionStep(branch_path="x.a", title="fix app/danger.py", operator="harden",
                      subject="app/danger.py", action_type="harden_security",
                      target="app/danger.py", executable=True,
                      source_facts=["security-finding: app/danger.py"])
    return IdeaActionBridge(), ActionPlan(objective="", steps=[step])


def test_uncovered_fix_is_shielded_by_generated_test_first(tmp_path):
    # No test references app/danger.py -> the pass generates a
    # characterization test FIRST, then fixes eval under its protection.
    _shield_project(tmp_path)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    entry = summary["results"][0]
    assert entry["applied"] is True
    assert entry["shield_test"] == "tests/test_danger.py"
    assert (tmp_path / "tests" / "test_danger.py").exists()
    # The shield upgraded what the green suite proves about the fix.
    assert entry["verification_strength"]["level"] in ("module", "function")
    # The shield is support work: exactly one result row, one applied fix.
    assert summary["total_executable"] == 1 and summary["applied"] == 1
    assert "ast.literal_eval" in (tmp_path / "app" / "danger.py").read_text()


def test_already_referenced_target_is_not_shielded(tmp_path):
    _shield_project(tmp_path, with_test_for_danger=True)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    assert "shield_test" not in summary["results"][0]


def test_shield_disabled_by_flag(tmp_path):
    _shield_project(tmp_path)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised",
                                verify=True, test_first=False)
    assert "shield_test" not in summary["results"][0]
    assert not (tmp_path / "tests" / "test_danger.py").exists()


def test_shield_recorded_in_proof_and_markdown(tmp_path):
    from app.engine.idea_action_bridge import render_maintenance_markdown
    from app.engine.proof_of_fix import build_proof

    _shield_project(tmp_path)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    record = build_proof(summary, str(tmp_path))["fixes"][0]
    assert record["shield_test"] == "tests/test_danger.py"
    assert "🛡️ shielded first by `tests/test_danger.py`" in render_maintenance_markdown(summary, str(tmp_path))


def test_tier_mapping_defaults_unknown_to_cautious():
    from app.execution.risk_tiers import tier_for

    assert tier_for("add_docstring") == 0
    assert tier_for("create_test_stub") == 0
    assert tier_for("harden_security") == 1
    assert tier_for("fix_mutable_defaults") == 1
    assert tier_for("design_task") == 2
    assert tier_for("brand_new_transform") == 1  # unknown -> earn Tier 0


def test_tier1_blocked_when_no_coverage_and_no_shield(tmp_path, monkeypatch):
    # Shield generation disabled -> an uncovered tier-1 fix is blocked, not gambled.
    _shield_project(tmp_path)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised",
                                verify=True, test_first=False)
    entry = summary["results"][0]
    assert entry["applied"] is False
    assert "tier-1 fix requires a covering test" in entry["reason"]
    assert summary["blocked"] == 1 and summary["applied"] == 0
    # The risky file was never touched.
    assert "eval(e)" in (tmp_path / "app" / "danger.py").read_text()


def test_tier0_fix_applies_without_coverage(tmp_path):
    # A docstring fix (tier 0) on an uncovered module applies normally even
    # without the shield: it is semantics-preserving.
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan, ActionStep

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "plain.py").write_text("def f(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    step = ActionStep(branch_path="x.d", title="doc app/plain.py", operator="document",
                      subject="app/plain.py", action_type="add_docstring",
                      target="app/plain.py", executable=True)
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(objective="", steps=[step]), str(tmp_path),
        mode="supervised", verify=True, test_first=False)
    entry = summary["results"][0]
    assert entry["applied"] is True
    assert entry["risk_tier"] == 0


def test_tier_recorded_in_proof(tmp_path):
    from app.engine.proof_of_fix import build_proof

    _shield_project(tmp_path)
    bridge, plan = _harden_plan(tmp_path)
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    record = build_proof(summary, str(tmp_path))["fixes"][0]
    assert record["risk_tier"] == 1


def test_worktree_test_copies_are_ignored(tmp_path):
    # The real suite never names handler (level "none"); a .claude worktree copy
    # whose test DOES reference it must not lift the measured strength.
    _project(tmp_path, "def test_unrelated():\n    assert 1 + 1 == 2\n")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "tests"
    copy.mkdir(parents=True)
    (copy / "test_phantom.py").write_text(
        "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n",
        encoding="utf-8")
    assert _assess(tmp_path)["level"] == "none"   # phantom test ignored
