from __future__ import annotations

from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.registry import SkillAutomationRegistry
from app.execution.patch_planner import PatchPlanner
from app.execution.repair_loop import RepairLoop
from app.execution.task_planner import TaskPlanner
from app.execution.verifier import Verifier
from app.memory.persistent_memory import PersistentMemoryStore
from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch
from app.skills.execution.clone_repo import CloneRepoSkill
from app.skills.execution.prepare_workspace import PrepareWorkspaceSkill
from app.skills.execution.run_tests import RunTestsSkill
from app.skills.safety.check_patch_scope import CheckPatchScopeSkill
from app.skills.safety.detect_sensitive_edit import DetectSensitiveEditSkill
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator
from app.tools.project_profile import ProjectProfiler


def profile_project_skill(context: AutomationContext):
    target_root = _target_root(context)
    profile = ProjectProfiler(target_root).profile()
    result = {
        "root": profile.root,
        "total_files": profile.total_files,
        "entrypoints": profile.entrypoints,
        "dependency_hubs": profile.dependency_hubs,
        "critical_untested_modules": profile.critical_untested_modules,
        "sensitive_paths": profile.sensitive_paths,
        "config_files": profile.config_files,
        "ci_files": profile.ci_files,
    }
    context.state["project_profile"] = result
    return result


def decompose_objective_skill(context: AutomationContext):
    decomposer = Decomposer(project_root=_target_root(context))
    claims = decomposer.decompose(context.objective)
    context.state["decomposed_claims"] = claims
    return {"claims": claims, "claim_count": len(claims)}


def run_research_skill(context: AutomationContext):
    target_root = _target_root(context)
    validator = Validator(evidence_mapper=EvidenceMapper(project_root=target_root))
    decomposer = Decomposer(project_root=target_root)
    memory_store = PersistentMemoryStore(project_root=target_root)
    orchestrator = FractalResearchOrchestrator(
        config=context.config,
        decomposer=decomposer,
        validator=validator,
        synthesizer=Synthesizer(project_root=target_root),
        memory_store=memory_store,
    )
    report = orchestrator.run(context.objective, focus_branch=context.focus_branch)
    report_dict = report.model_dump()
    context.state["final_report"] = report_dict
    return report_dict


def prepare_workspace_skill(context: AutomationContext):
    result = PrepareWorkspaceSkill().run(repo_url=context.repo_url, project_root=context.project_root)
    result_dict = {
        "ok": result.ok,
        "workspace_root": result.workspace_root,
        "project_dir": result.project_dir,
        "repo_name": result.repo_name,
        "error": result.error,
    }
    context.state["workspace"] = result_dict
    if result.ok:
        context.workspace_dir = Path(result.project_dir)
    return result_dict


def clone_repo_skill(context: AutomationContext):
    if not context.repo_url:
        result_dict = {
            "ok": False,
            "repo_url": None,
            "workspace_root": "",
            "project_dir": "",
            "error": "repo_url missing for clone_repo skill",
        }
        context.state["cloned_repo"] = result_dict
        return result_dict

    result = CloneRepoSkill().run(context.repo_url)
    result_dict = {
        "ok": result.ok,
        "repo_url": result.repo_url,
        "workspace_root": result.workspace_root,
        "project_dir": result.project_dir,
        "error": result.error,
    }
    context.state["cloned_repo"] = result_dict
    if result.ok:
        context.workspace_dir = Path(result.project_dir)
    return result_dict


def run_tests_skill(context: AutomationContext):
    target_root = _target_root(context)
    result = RunTestsSkill().run(target_root)
    result_dict = {
        "project_root": result.project_root,
        "commands": result.commands,
        "results": result.results,
        "ok": result.ok,
    }
    context.state["test_run"] = result_dict
    return result_dict


def apply_patch_skill(context: AutomationContext):
    target_root = _target_root(context)
    patch_requests = context.state.get("patch_requests", [])
    if not patch_requests:
        result_dict = {
            "project_root": str(Path(target_root).resolve()),
            "changed_files": [],
            "skipped_files": [],
            "ok": False,
            "error": "No patch_requests provided. Supply context.state['patch_requests'] with patch dictionaries.",
        }
        context.state["patch_apply"] = result_dict
        context.state["changed_files"] = []
        return result_dict

    patches = [
        FilePatch(
            path=item["path"],
            new_content=item["new_content"],
            expected_old_content=item.get("expected_old_content"),
        )
        for item in patch_requests
    ]
    result = ApplyPatchSkill().run(target_root, patches)
    result_dict = {
        "project_root": result.project_root,
        "changed_files": result.changed_files,
        "skipped_files": result.skipped_files,
        "ok": result.ok,
        "error": result.error,
    }
    context.state["patch_apply"] = result_dict
    context.state["changed_files"] = list(result.changed_files)
    return result_dict


def check_patch_scope_skill(context: AutomationContext):
    changed_files = context.state.get("changed_files", [])
    result = CheckPatchScopeSkill().run(changed_files=changed_files)
    result_dict = {
        "ok": result.ok,
        "changed_file_count": result.changed_file_count,
        "max_allowed_files": result.max_allowed_files,
        "touched_sensitive_paths": result.touched_sensitive_paths,
        "reasons": result.reasons,
    }
    context.state["patch_scope"] = result_dict
    return result_dict


def detect_sensitive_edit_skill(context: AutomationContext):
    changed_files = context.state.get("changed_files", [])
    result = DetectSensitiveEditSkill().run(changed_files=changed_files)
    result_dict = {
        "ok": result.ok,
        "touched_sensitive_paths": result.touched_sensitive_paths,
        "detected_hints": result.detected_hints,
    }
    context.state["sensitive_edit"] = result_dict
    return result_dict


def plan_tasks_skill(context: AutomationContext):
    report = context.state.get("final_report", {})
    result = TaskPlanner().plan(report)
    result_dict = result.to_dict()
    context.state["task_plan"] = result_dict
    return result_dict


def plan_patch_skill(context: AutomationContext):
    tasks = context.state.get("task_plan", {}).get("tasks", [])
    task = tasks[0] if tasks else {}
    result = PatchPlanner().plan(task)
    result_dict = result.to_dict()
    context.state["patch_plan"] = result_dict
    return result_dict


def verify_changes_skill(context: AutomationContext):
    target_root = _target_root(context)
    changed_files = context.state.get("changed_files", [])
    patch_apply = context.state.get("patch_apply")
    if patch_apply and not patch_apply.get("ok", True):
        result_dict = {
            "ok": False,
            "project_root": str(Path(target_root).resolve()),
            "test_summary": {"project_root": str(Path(target_root).resolve()), "commands": [], "results": [], "ok": True},
            "patch_scope": {"ok": True, "changed_file_count": 0, "max_allowed_files": 5, "touched_sensitive_paths": [], "reasons": []},
            "sensitive_edit": {"ok": True, "touched_sensitive_paths": [], "detected_hints": {}},
            "patch_apply": patch_apply,
        }
        context.state["verification"] = result_dict
        return result_dict

    result = Verifier().verify(project_root=target_root, changed_files=changed_files)
    result_dict = result.to_dict()
    result_dict["patch_apply"] = patch_apply or {"ok": True, "changed_files": changed_files, "skipped_files": [], "error": None}
    context.state["verification"] = result_dict
    return result_dict


def repair_from_verification_skill(context: AutomationContext):
    verification = context.state.get("verification", {})
    patch_plan = context.state.get("patch_plan", {})
    result = RepairLoop().run(verification=verification, patch_plan=patch_plan)
    result_dict = result.to_dict()
    context.state["repair_loop"] = result_dict
    return result_dict


def _target_root(context: AutomationContext):
    target_root = context.project_root
    if context.workspace_dir is not None:
        target_root = context.workspace_dir
    elif context.state.get("cloned_repo", {}).get("project_dir"):
        target_root = Path(context.state["cloned_repo"]["project_dir"])
    elif context.state.get("workspace", {}).get("project_dir"):
        target_root = Path(context.state["workspace"]["project_dir"])
    return target_root


def build_default_registry() -> SkillAutomationRegistry:
    registry = SkillAutomationRegistry()
    registry.register("profile_project", profile_project_skill)
    registry.register("decompose_objective", decompose_objective_skill)
    registry.register("run_research", run_research_skill)
    registry.register("prepare_workspace", prepare_workspace_skill)
    registry.register("clone_repo", clone_repo_skill)
    registry.register("run_tests", run_tests_skill)
    registry.register("apply_patch", apply_patch_skill)
    registry.register("check_patch_scope", check_patch_scope_skill)
    registry.register("detect_sensitive_edit", detect_sensitive_edit_skill)
    registry.register("plan_tasks", plan_tasks_skill)
    registry.register("plan_patch", plan_patch_skill)
    registry.register("verify_changes", verify_changes_skill)
    registry.register("repair_from_verification", repair_from_verification_skill)
    return registry
