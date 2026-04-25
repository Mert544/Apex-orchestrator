from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.execution.pr_summary_generator import PRSummaryGenerator
from app.runtime.command_runner import CommandRunner, CommandSpec
from app.runtime.git_adapter import GitAdapter


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_git_repo(root: Path) -> None:
    runner = CommandRunner()
    runner.run(CommandSpec(command=["git", "init"], cwd=Path(root)))
    runner.run(CommandSpec(command=["git", "config", "user.email", "apex@orchestrator.local"], cwd=Path(root)))
    runner.run(CommandSpec(command=["git", "config", "user.name", "Apex Orchestrator"], cwd=Path(root)))


def _make_context(project_root: Path) -> AutomationContext:
    return AutomationContext(
        project_root=project_root,
        objective="Apply a supervised patch and generate a PR summary.",
        config={
            "max_depth": 2,
            "max_total_nodes": 20,
            "top_k_questions": 2,
            "min_security": 0.8,
            "min_quality": 0.6,
            "min_novelty": 0.2,
            "max_retries": 1,
        },
    )


def test_git_diff_skill_returns_stats(tmp_path: Path):
    _init_git_repo(tmp_path)
    _write(tmp_path / "README.md", "hello\n")

    runner = SkillAutomationRunner(build_default_registry())
    context = _make_context(tmp_path)
    # Stage initial commit so diff shows nothing yet
    git = GitAdapter()
    git.add(tmp_path, ["README.md"])
    git.commit(tmp_path, "initial")

    # Modify file
    _write(tmp_path / "README.md", "hello world\n")

    result = runner.run_plan("git_pr_loop", context)

    assert result.steps[0].step_name == "git_diff"
    assert result.steps[0].status == "ok"
    assert "README.md" in result.steps[0].output["diff_stat"] or result.steps[0].output["status_short"]


def test_git_commit_skill_commits_changes(tmp_path: Path):
    _init_git_repo(tmp_path)
    _write(tmp_path / "app.py", "print('ok')\n")

    runner = SkillAutomationRunner(build_default_registry())
    context = _make_context(tmp_path)
    context.state["changed_files"] = ["app.py"]
    context.state["patch_plan"] = {"title": "Add app entrypoint", "target_files": ["app.py"]}
    context.state["task_plan"] = {"tasks": [{"title": "Add app entrypoint", "id": "t-1"}]}

    # Ensure file exists so git add succeeds
    result = runner.run_plan("git_pr_loop", context)

    commit_step = result.steps[1]
    assert commit_step.step_name == "git_commit"
    assert commit_step.status == "ok"
    assert "Add app entrypoint" in commit_step.output["commit_message"]

    # Verify log shows the commit
    git_adapter = GitAdapter()
    log = git_adapter.log_oneline(tmp_path, count=1)
    assert "Add app entrypoint" in log.stdout


def test_generate_pr_summary_produces_markdown(tmp_path: Path):
    generator = PRSummaryGenerator()
    result = generator.generate(
        project_root=tmp_path,
        changed_files=["app/main.py"],
        patch_plan={
            "title": "Add type annotations",
            "change_strategy": ["Keep the patch minimal"],
        },
        task={"title": "Add type annotations", "rationale": "Improve static analysis coverage."},
        verification={"ok": True},
        git_diff_stat=" app/main.py | 1 +\n",
    )

    assert result.title == "Add type annotations"
    assert "## Add type annotations" in result.body
    assert "`app/main.py`" in result.body
    assert "Diff stat" in result.body
    assert "✅ All checks passed." in result.body
    assert "Changed files:" in result.commit_message


def test_generate_pr_summary_shows_warnings_on_verification_failure(tmp_path: Path):
    generator = PRSummaryGenerator()
    result = generator.generate(
        project_root=tmp_path,
        changed_files=["auth/token.py"],
        patch_plan={"title": "Harden token logic", "change_strategy": []},
        task={},
        verification={
            "ok": False,
            "patch_scope": {"ok": False, "reasons": ["Too many files changed."]},
            "test_summary": {"ok": True},
            "sensitive_edit": {"ok": True},
        },
        git_diff_stat="",
    )

    assert "⚠️  Verification reported issues" in result.body
    assert "Too many files changed." in result.body


def test_full_autonomous_loop_runs_end_to_end(tmp_path: Path):
    _init_git_repo(tmp_path)
    _write(tmp_path / "app" / "__init__.py", "")
    _write(tmp_path / "app" / "math.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path / "tests" / "test_math.py", "def test_add():\n    assert 2 + 3 == 5\n")
    _write(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\nversion = '0.0.1'\n")

    # Initial commit so git has a baseline
    git = GitAdapter()
    git.add(tmp_path, [".",])
    # Commit all initial files
    git.commit(tmp_path, "initial commit")

    runner = SkillAutomationRunner(build_default_registry())
    context = _make_context(tmp_path)

    result = runner.run_plan("full_autonomous_loop", context)

    step_names = [step.step_name for step in result.steps]
    expected = [
        "run_research",
        "plan_tasks",
        "plan_patch",
        "generate_semantic_patch",
        "safety_gate_check",
        "apply_patch",
        "verify_changes",
        "repair_with_retry",
        "git_diff",
        "git_commit",
        "generate_pr_summary",
        "record_telemetry",
        "export_token_report",
    ]
    assert step_names == expected
    assert all(step.status == "ok" for step in result.steps)
    # PR summary should be populated
    pr_step = result.steps[-3]
    assert "title" in pr_step.output or "body" in pr_step.output or "commit_message" in pr_step.output

    # Telemetry steps
    telem_step = result.steps[-2]
    assert telem_step.step_name == "record_telemetry"
    assert telem_step.status == "ok"

    export_step = result.steps[-1]
    assert export_step.step_name == "export_token_report"
    assert export_step.status == "ok"
    assert export_step.output["ok"] is True
