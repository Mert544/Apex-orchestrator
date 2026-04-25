from __future__ import annotations

import os
from pathlib import Path

from app.agents.skills import SecurityAgent, DocstringAgent, TestStubAgent, DependencyAgent
from app.agents.fractal_agents import FractalSecurityAgent, FractalDocstringAgent, FractalTestStubAgent
from app.agents.swarm_coordinator import SwarmCoordinator
from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.engine.debug_engine import DebugEngine
from app.memory.persistent_memory import PersistentMemoryStore
from app.orchestrator import FractalResearchOrchestrator
from app.plugins.registry import PluginRegistry
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.validator import Validator
from app.skills.synthesizer import Synthesizer
from app.utils.json_utils import pretty_json
from app.utils.yaml_utils import load_yaml


def _build_swarm_for_plan(plan_name: str, use_fractal: bool = False) -> SwarmCoordinator:
    """Create a SwarmCoordinator with agents matching the plan.

    When use_fractal=True, registers FractalSecurityAgent,
    FractalDocstringAgent, and FractalTestStubAgent instead of
    the plain variants so every finding gets 5-Whys deep analysis.
    """
    coord = SwarmCoordinator()

    agents = []
    if "security" in plan_name or "full" in plan_name or "self" in plan_name:
        agents.append(FractalSecurityAgent() if use_fractal else SecurityAgent())
    if "docstring" in plan_name or "semantic" in plan_name or "full" in plan_name or "self" in plan_name:
        agents.append(FractalDocstringAgent() if use_fractal else DocstringAgent())
    if "test" in plan_name or "coverage" in plan_name or "semantic" in plan_name or "full" in plan_name or "self" in plan_name:
        agents.append(FractalTestStubAgent() if use_fractal else TestStubAgent())
    if "dependency" in plan_name or "project_scan" in plan_name or "full" in plan_name or "self" in plan_name:
        agents.append(DependencyAgent())

    coord.register_agents(agents)
    return coord


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = load_yaml(repo_root / "config" / "default.yaml")

    target_root = Path(os.getenv("EPISTEMIC_TARGET_ROOT", str(repo_root))).resolve()
    focus_branch = os.getenv("EPISTEMIC_FOCUS_BRANCH") or None
    objective = os.getenv(
        "EPISTEMIC_OBJECTIVE",
        "Scan the target project, extract meaningful implementation claims, and continue with constitution-driven fractal questioning.",
    )
    automation_plan = os.getenv("EPISTEMIC_AUTOMATION_PLAN")

    # Load plugins from config or environment
    plugin_dirs = config.get("plugin_dirs", [])
    if os.getenv("APEX_PLUGIN_PATH"):
        plugin_dirs.extend(os.getenv("APEX_PLUGIN_PATH", "").split(os.pathsep))
    plugins = PluginRegistry(plugin_dirs=plugin_dirs)
    plugins.load_all()

    use_fractal = os.getenv("APEX_USE_FRACTAL", "").lower() in ("1", "true", "yes")
    if not use_fractal:
        # Auto-detect fractal mode for security/audit/risk goals
        use_fractal = any(kw in objective.lower() for kw in ("security", "audit", "risk", "vuln"))

    if automation_plan:
        # Try event-driven swarm first if agents are available
        swarm = _build_swarm_for_plan(automation_plan, use_fractal=use_fractal)
        if swarm.registry.agents:
            mode = "supervised"
            print(f"[main] Running event-driven swarm with {len(swarm.registry.agents)} agent(s)")
            if use_fractal:
                print("[main] Fractal deep-analysis enabled (5-Whys + counter-evidence + meta-analysis)")
            results = swarm.run_autonomous(
                goal=objective,
                target=str(target_root),
                mode=mode,
            )
            print(pretty_json({"swarm_results": results, "stats": swarm.stats()}))

            # Auto-generate fractal-aware report
            from app.reporting.composer import ReportComposer
            composer = ReportComposer(results)
            report_dir = target_root / ".apex"
            report_dir.mkdir(exist_ok=True)
            md_path = report_dir / "fractal-report.md"
            composer.to_markdown(md_path)
            print(f"[main] Report written to {md_path}")
            return

        # Fallback to legacy runner
        context = AutomationContext(
            project_root=target_root,
            objective=objective,
            config=config,
            focus_branch=focus_branch,
        )
        runner = SkillAutomationRunner(build_default_registry(), plugins=plugins)
        result = runner.run_plan(automation_plan, context)
        print(pretty_json(result.to_dict()))
        return

    validator = Validator(evidence_mapper=EvidenceMapper(project_root=target_root))
    decomposer = Decomposer(project_root=target_root)
    memory_store = PersistentMemoryStore(project_root=target_root)
    debug = DebugEngine(project_root=str(target_root), enabled=bool(config.get("debug_enabled", False)))

    orchestrator = FractalResearchOrchestrator(
        config=config,
        decomposer=decomposer,
        validator=validator,
        synthesizer=Synthesizer(project_root=target_root),
        memory_store=memory_store,
        debug=debug,
    )

    report = orchestrator.run(objective, focus_branch=focus_branch)
    print(pretty_json(report.model_dump()))


if __name__ == "__main__":
    main()
