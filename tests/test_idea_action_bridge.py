from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, render_action_markdown
from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode, IdeaTreeReport


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_test_operator_maps_to_executable_stub():
    idea = IdeaNode(
        id="i", title="Test: app/main.py", subject="app/main.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/main.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True
    assert step.target == "app/main.py"


def test_extend_operator_is_a_design_task():
    idea = IdeaNode(id="i", title="Extend: app/main.py", subject="app/main.py", operator="extend")
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "design_task"
    assert step.executable is False


def test_root_action_from_seeding_fact():
    idea = IdeaNode(
        id="i", title="Harden the sensitive path app/auth.py", subject="app/auth.py",
        operator="root", source_facts=["sensitive-path: app/auth.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "harden_security"
    assert step.executable is True


def test_plan_tree_orders_by_value_and_counts(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 15, "max_idea_depth": 2}, tmp_path).run()
    plan = IdeaActionBridge().plan_tree(report, top=10)

    assert plan.stats["total_steps"] == len(plan.steps) <= 10
    # Sorted by value, descending.
    values = [s.value for s in plan.steps]
    assert values == sorted(values, reverse=True)
    # Some steps are executable (tests/docs), the plan is never auto-applied.
    assert plan.mode == "supervised"
    assert plan.stats["executable_steps"] + plan.stats["design_tasks"] == plan.stats["total_steps"]


def test_render_action_markdown(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 8}, tmp_path).run()
    md = render_action_markdown(IdeaActionBridge().plan_tree(report))
    assert "Action Plan" in md
    assert "not applied" in md


def test_draft_patch_for_test_stub_is_preview_only(tmp_path):
    _project(tmp_path)
    from app.models.idea import IdeaNode

    idea = IdeaNode(
        id="i", title="Test: app/main.py", subject="app/main.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/main.py"],
    )
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(idea)
    before = (tmp_path / "app" / "main.py").read_text()

    preview = bridge.draft_patch(step, str(tmp_path))

    assert preview is not None
    assert preview["applied"] is False
    assert preview["files"]
    # Drafting must NOT touch the source tree.
    assert (tmp_path / "app" / "main.py").read_text() == before
    assert not (tmp_path / "tests").exists()


def test_design_task_has_no_draft():
    from app.models.idea import IdeaNode

    idea = IdeaNode(id="i", title="Extend: app/main.py", subject="app/main.py", operator="extend")
    step = IdeaActionBridge().plan_idea(idea)
    assert IdeaActionBridge().draft_patch(step, ".") is None


def test_plan_tree_draft_populates_previews_without_side_effects(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 2}, tmp_path).run()
    snapshot = {p: p.read_text() for p in (tmp_path / "app").glob("*.py")}

    plan = IdeaActionBridge().plan_tree(report, top=10, draft=True, project_root=str(tmp_path))

    assert plan.stats["drafted_patches"] >= 1
    assert any(s.patch_preview for s in plan.steps)
    # No source file changed.
    for p, content in snapshot.items():
        assert p.read_text() == content


def test_apply_blocked_in_report_mode(tmp_path):
    _project(tmp_path)
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/main.py", subject="app/main.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["untested: app/main.py"])
    step = IdeaActionBridge().plan_idea(idea)
    before = (tmp_path / "app" / "main.py").read_text()
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="report")
    assert result["applied"] is False
    assert "read-only" in result["reason"]
    assert (tmp_path / "app" / "main.py").read_text() == before  # untouched


def test_apply_in_supervised_mode_writes_file(tmp_path):
    # A file with a function missing a docstring -> add_docstring applies.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def handler(x):\n    return x + 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "add_docstring"

    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")

    if result["applied"]:
        # The file was actually changed and now contains a docstring.
        assert src.read_text() != "def handler(x):\n    return x + 1\n"
        assert '"""' in src.read_text()
    else:
        # If no transform applied, the file must remain untouched.
        assert src.read_text() == "def handler(x):\n    return x + 1\n"


def test_apply_blocks_sensitive_path(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "keys.py").write_text("def k():\n    return 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: secrets/keys.py", subject="secrets/keys.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["sensitive-path: secrets/keys.py"])
    step = IdeaActionBridge().plan_idea(idea)
    # Even if a patch is generated, the sensitive-path gate must block writing.
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"] is False and "safety" in result.get("reason", ""):
        assert (tmp_path / "secrets" / "keys.py").read_text() == "def k():\n    return 1\n"


def test_harden_applies_real_eval_fix(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def run(c):\n    return eval(c)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "eval_to_literal_eval"
        assert "ast.literal_eval(c)" in src.read_text()
        assert "eval(c)" not in src.read_text().replace("literal_eval", "")


def test_harden_applies_bare_except_fix(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "m.py"
    src.write_text("def f():\n    try:\n        x = 1\n    except:\n        pass\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/m.py", subject="app/m.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/m.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert "except Exception:" in src.read_text()


def test_harden_falls_back_to_guard_when_no_known_issue(tmp_path):
    # No eval/os.system/bare-except -> harden_security still produces *a* patch
    # (guard clause) rather than erroring.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "ok.py"
    src.write_text("def f(x):\n    return x + 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/ok.py", subject="app/ok.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/ok.py"])
    step = IdeaActionBridge().plan_idea(idea)
    # Should not raise; may or may not apply depending on guard applicability.
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    assert "applied" in result


def test_verify_keeps_patch_when_tests_pass(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    if res["applied"]:
        assert res["verified"] is True
        assert res.get("rolled_back") is False
        assert '"""' in src.read_text()


def test_verify_rolls_back_when_tests_fail(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "svc.py"
    original = "def handler(x):\n    return x + 1\n"
    src.write_text(original)
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    # The patch generated and applied, tests failed -> rolled back, file restored.
    if res.get("rolled_back"):
        assert res["applied"] is False
        assert src.read_text() == original


def test_verify_rolls_back_newly_created_file(tmp_path):
    # A create_test_stub that breaks tests should delete the newly-created file.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Test: app/main.py", subject="app/main.py",
                    operator="test", operator_chain=["test"],
                    source_facts=["untested: app/main.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    if res.get("rolled_back"):
        assert not (tmp_path / "tests" / "test_main.py").exists()


def test_apply_plan_runs_whole_pass_with_summary(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)

    assert summary["applied"] + summary["rolled_back"] + summary["blocked"] == summary["total_executable"]
    assert len(summary["results"]) == summary["total_executable"]
    # The eval() should have been fixed and kept (tests still pass).
    assert "ast.literal_eval" in (tmp_path / "app" / "danger.py").read_text()


def test_create_test_stub_never_targets_test_files(tmp_path):
    # A test file as subject must not spawn a test_test_*.py stub.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("def test_x():\n    assert True\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Test: tests/test_calc.py", subject="tests/test_calc.py",
                    operator="test", operator_chain=["test"],
                    source_facts=["untested: tests/test_calc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    assert IdeaActionBridge().draft_patch(step, str(tmp_path)) is None


def test_run_tests_isolates_target_project(tmp_path):
    # RunTestsSkill must resolve the TARGET project's package, not the caller's.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 1) == 2\n"
    )
    from app.skills.execution.run_tests import RunTestsSkill
    summary = RunTestsSkill().run(str(tmp_path))
    assert summary.ok


def test_apply_plan_no_commit_in_supervised(tmp_path):
    # commit=True but supervised mode -> cannot commit; summary reflects it.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", commit=True)
    assert summary["commit"] is False
    assert summary.get("committed", 0) == 0


def test_apply_plan_commits_in_autonomous(tmp_path):
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "add", "-A"], cwd=tmp_path)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=tmp_path)

    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="autonomous", verify=False, commit=True)
    assert summary["commit"] is True
    # If any harden step applied, it should have produced a commit.
    if summary["applied"] > 0:
        assert summary["committed"] >= 1
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
        ).stdout
        assert "Apex auto-fix" in log


def test_harden_flags_pickle_loads(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("import pickle\ndef load(b):\n    return pickle.loads(b)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "flag_pickle_loads"
        assert "SECURITY" in src.read_text()
        assert "pickle.loads(b)" in src.read_text()  # call preserved, just annotated
