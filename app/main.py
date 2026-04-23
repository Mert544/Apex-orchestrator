from __future__ import annotations

import os
from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.engine.debug_engine import DebugEngine
from app.memory.persistent_memory import PersistentMemoryStore
from app.orchestrator import FractalResearchOrchestrator
from app.plugins.registry import PluginRegistry
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator
from app.utils.json_utils import pretty_json
from app.utils.yaml_utils import load_yaml


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

    if automation_plan:
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
