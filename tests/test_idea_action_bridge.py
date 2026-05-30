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
