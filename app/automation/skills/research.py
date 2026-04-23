from __future__ import annotations

from app.automation.models import AutomationContext
from app.execution.task_planner import TaskPlanner
from app.memory.persistent_memory import PersistentMemoryStore
from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator
from app.tools.project_profile import ProjectProfiler

from ._context import _target_root


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


def plan_tasks_skill(context: AutomationContext):
    report = context.state.get("final_report", {})
    result = TaskPlanner().plan(report)
    result_dict = result.to_dict()
    context.state["task_plan"] = result_dict
    return result_dict
