from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Fix Windows console encoding for emoji/unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.agents.skills import (
    SecurityAgent,
    DocstringAgent,
    TestStubAgent,
    DependencyAgent,
)
from app.agents.fractal_agents import (
    FractalSecurityAgent,
    FractalDocstringAgent,
    FractalTestStubAgent,
)
from app.agents.swarm_coordinator import SwarmCoordinator
from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.engine.debug_engine import DebugEngine
from app.engine.rollback_journal import RollbackJournal
from app.engine.checkpoint_manager import CheckpointManager
from app.memory.bridge import CentralMemoryBridge
from app.memory.persistent_memory import PersistentMemoryStore
from app.metrics.exporter import MetricsMiddleware
from app.orchestrator import FractalResearchOrchestrator
from app.plugins.registry import PluginRegistry, PluginEventBridge
from app.policies.mode_policy import ModePolicy, mode_from_string
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.validator import Validator
from app.skills.synthesizer import Synthesizer
from app.utils.json_utils import pretty_json
from app.utils.yaml_utils import load_yaml


def _is_broad_plan(plan_name: str) -> bool:
    """True for read-only sweeps that should run every scanner."""
    return "project_scan" in plan_name or "full" in plan_name or "self" in plan_name


def _wants_security(plan_name: str, broad: bool) -> bool:
    """True when the security scanner applies to this plan."""
    return "security" in plan_name or broad


def _wants_docstring(plan_name: str, broad: bool) -> bool:
    """True when the docstring scanner applies to this plan."""
    return "docstring" in plan_name or "semantic" in plan_name or broad


def _wants_test(plan_name: str, broad: bool) -> bool:
    """True when the test-stub scanner applies to this plan."""
    return (
        "test" in plan_name
        or "coverage" in plan_name
        or "semantic" in plan_name
        or broad
    )


def _wants_dependency(plan_name: str, broad: bool) -> bool:
    """True when the dependency scanner applies to this plan."""
    return "dependency" in plan_name or broad


def _select_agents(plan_name: str, use_fractal: bool) -> list:
    """Build the ordered agent list for a plan (pure, no side effects)."""
    broad = _is_broad_plan(plan_name)
    agents = []
    if _wants_security(plan_name, broad):
        agents.append(FractalSecurityAgent() if use_fractal else SecurityAgent())
    if _wants_docstring(plan_name, broad):
        agents.append(FractalDocstringAgent() if use_fractal else DocstringAgent())
    if _wants_test(plan_name, broad):
        agents.append(FractalTestStubAgent() if use_fractal else TestStubAgent())
    if _wants_dependency(plan_name, broad):
        agents.append(DependencyAgent())
    return agents


def _build_swarm_for_plan(
    plan_name: str, use_fractal: bool = False
) -> SwarmCoordinator:
    """Create a SwarmCoordinator with agents matching the plan.

    When use_fractal=True, registers FractalSecurityAgent,
    FractalDocstringAgent, and FractalTestStubAgent instead of
    the plain variants so every finding gets 5-Whys deep analysis.
    """
    coord = SwarmCoordinator()
    coord.register_agents(_select_agents(plan_name, use_fractal))
    return coord


def _run_swarm_with_plugins(
    swarm: SwarmCoordinator,
    plugins: PluginRegistry,
    *,
    objective: str,
    target: str,
    mode: str,
    plan_name: str,
    report_dir: Path,
):
    """Run the event-driven swarm with plugin hooks wired into the flow.

    Previously the swarm path bypassed the plugin registry entirely. This fires
    the before_scan / after_scan / on_report lifecycle hooks and bridges plugin
    bus subscribers to the swarm bus, so plugins participate in the main path.
    Returns (results, report_path).
    """
    from app.reporting.composer import ReportComposer

    plugins.run_hook(
        "before_scan", {"objective": objective, "target": target, "plan": plan_name}
    )
    # Let plugins react to live agent events during the run.
    PluginEventBridge(plugins, swarm.bus).wire()

    results = swarm.run_autonomous(goal=objective, target=target, mode=mode)

    plugins.run_hook(
        "after_scan", {"objective": objective, "plan": plan_name, "results": results}
    )

    report_dir.mkdir(exist_ok=True)
    md_path = report_dir / "fractal-report.md"
    ReportComposer(results).to_markdown(md_path)
    plugins.run_hook("on_report", {"report_path": str(md_path), "results": results})

    return results, md_path


def _env_flag(value: str | None) -> bool:
    """Truthy when an env value is one of ``1``/``true``/``yes`` (lowercased)."""
    return value.lower() in ("1", "true", "yes") if value else False


def _build_policy() -> ModePolicy:
    """Construct the ModePolicy from APEX_* environment overrides."""
    max_fractal_env = os.getenv("APEX_MAX_FRACTAL_BUDGET")
    return ModePolicy(
        mode=mode_from_string(os.getenv("APEX_MODE")),
        auto_patch=_env_flag(os.getenv("APEX_AUTO_PATCH")),
        auto_commit=_env_flag(os.getenv("APEX_AUTO_COMMIT")),
        max_fractal_budget=int(max_fractal_env)
        if max_fractal_env and max_fractal_env.isdigit()
        else 10,
        safety_policy=os.getenv("APEX_SAFETY_POLICY") or "standard",
    )


def _safety_gates_block(policy: ModePolicy, automation_plan: str | None) -> bool:
    """Print/enforce safety gates; return True iff the run must abort."""
    if automation_plan and policy.permissions.requires_safety_gates:
        print(f"[mode] Running in {policy.mode.value} mode with safety gates enabled")
        if policy.permissions.requires_clean_working_tree:
            result = policy.enforce_clean_working_tree()
            if not result.passed:
                print(f"[mode] BLOCKED: {result.message}")
                return True
    return False


def _load_plugins(config: dict) -> PluginRegistry:
    """Load plugins from config plus the APEX_PLUGIN_PATH environment override."""
    plugin_dirs = config.get("plugin_dirs", [])
    if os.getenv("APEX_PLUGIN_PATH"):
        plugin_dirs.extend(os.getenv("APEX_PLUGIN_PATH", "").split(os.pathsep))
    plugins = PluginRegistry(plugin_dirs=plugin_dirs)
    plugins.load_all()
    return plugins


def _resolve_use_fractal(objective: str) -> bool:
    """True when fractal mode is requested via env or implied by the objective."""
    if _env_flag(os.getenv("APEX_USE_FRACTAL", "")):
        return True
    # Auto-detect fractal mode for security/audit/risk goals.
    return any(kw in objective.lower() for kw in ("security", "audit", "risk", "vuln"))


def _run_swarm_plan(
    swarm: SwarmCoordinator,
    plugins: PluginRegistry,
    *,
    objective: str,
    target_root: Path,
    automation_plan: str,
    use_fractal: bool,
) -> None:
    """Run the event-driven swarm branch (agents available) and print results."""
    print(
        f"[main] Running event-driven swarm with {len(swarm.registry.agents)} agent(s)"
    )
    if use_fractal:
        print(
            "[main] Fractal deep-analysis enabled (5-Whys + counter-evidence + meta-analysis)"
        )
    results, md_path = _run_swarm_with_plugins(
        swarm,
        plugins,
        objective=objective,
        target=str(target_root),
        mode="supervised",
        plan_name=automation_plan,
        report_dir=target_root / ".apex",
    )
    print(pretty_json({"swarm_results": results, "stats": swarm.stats()}))
    print(f"[main] Report written to {md_path}")


def _run_legacy_plan(
    plugins: PluginRegistry,
    config: dict,
    *,
    objective: str,
    target_root: Path,
    focus_branch: str | None,
    automation_plan: str,
) -> None:
    """Run the legacy SkillAutomationRunner fallback for a plan and print result."""
    context = AutomationContext(
        project_root=target_root,
        objective=objective,
        config=config,
        focus_branch=focus_branch,
    )
    runner = SkillAutomationRunner(build_default_registry(), plugins=plugins)
    result = runner.run_plan(automation_plan, context)
    print(pretty_json(result.to_dict()))


def _run_automation_plan(
    plugins: PluginRegistry,
    config: dict,
    policy: ModePolicy,
    *,
    objective: str,
    target_root: Path,
    focus_branch: str | None,
    automation_plan: str,
    use_fractal: bool,
) -> None:
    """Dispatch a plan run: event-driven swarm if agents exist, else legacy."""
    swarm = _build_swarm_for_plan(automation_plan, use_fractal=use_fractal)
    if swarm.registry.agents:
        _run_swarm_plan(
            swarm,
            plugins,
            objective=objective,
            target_root=target_root,
            automation_plan=automation_plan,
            use_fractal=use_fractal,
        )
        return
    _run_legacy_plan(
        plugins,
        config,
        objective=objective,
        target_root=target_root,
        focus_branch=focus_branch,
        automation_plan=automation_plan,
    )


def _build_orchestrator(
    config: dict, policy: ModePolicy, target_root: Path
) -> tuple[FractalResearchOrchestrator, DebugEngine]:
    """Wire up validator/decomposer/memory/debug into a FractalResearchOrchestrator."""
    debug_enabled = bool(config.get("debug_enabled", False)) or policy.mode.value == "autonomous"
    debug = DebugEngine(
        project_root=str(target_root),
        enabled=debug_enabled,
        level=DebugEngine.LEVEL_TRACE if policy.mode.value == "autonomous" else DebugEngine.LEVEL_INFO,
    )
    validator = Validator(evidence_mapper=EvidenceMapper(project_root=target_root))
    decomposer = Decomposer(project_root=target_root)
    memory_store = PersistentMemoryStore(project_root=target_root)
    memory_store.hydrate_graph(validator.evidence_mapper.graph if hasattr(validator.evidence_mapper, "graph") else None)
    orchestrator = FractalResearchOrchestrator(
        config=config,
        decomposer=decomposer,
        validator=validator,
        synthesizer=Synthesizer(project_root=target_root),
        memory_store=memory_store,
        debug=debug,
    )
    return orchestrator, debug


def _run_orchestrator(
    policy: ModePolicy,
    *,
    objective: str,
    target_root: Path,
    focus_branch: str | None,
    config: dict,
) -> None:
    """Run the full orchestrator path: scan, persist, snapshot, write metrics."""
    # Initialize integrated memory, metrics, and safety infrastructure
    memory_bridge = CentralMemoryBridge(str(target_root))
    metrics = MetricsMiddleware()
    rollback = RollbackJournal(project_root=str(target_root))
    checkpoint = CheckpointManager(project_root=str(target_root))

    orchestrator, debug = _build_orchestrator(config, policy, target_root)

    # Record run start
    import time
    run_id = f"run-{int(time.time())}"
    start_time = time.time()

    debug.trace("orchestrator", f"Starting run {run_id} in {policy.mode.value} mode")
    report = orchestrator.run(objective, focus_branch=focus_branch)
    duration = time.time() - start_time
    print(pretty_json(report.model_dump()))

    # Persist findings across runs
    findings = [{"claim": key, "confidence": conf, "branch": ""} for key, conf in report.confidence_map.items()]
    memory_bridge.record_run(run_id, claims=findings)
    checkpoint.save_checkpoint(run_id, mode=policy.mode.value, goal=objective, stats={"claims": len(findings), "duration": duration})

    # Record metrics
    patches_applied_val = getattr(report, "patches_applied", 0)
    patches_blocked_val = getattr(report, "patches_blocked", 0)
    claims_count = len(findings)
    metrics.record_run(
        plan="default",
        duration_seconds=duration,
        claims_found=claims_count,
        patches_applied=patches_applied_val,
    )

    # Rollback journal snapshot
    rollback.snapshot()

    debug.trace("orchestrator", f"Run {run_id} completed in {duration:.1f}s", {
        "claims": claims_count,
        "patches": patches_applied_val,
        "blocked": patches_blocked_val,
    })

    # Persist debug and checkpoint reports
    debug.report()
    metrics_text = metrics.render()
    (target_root / ".apex").mkdir(parents=True, exist_ok=True)
    (target_root / ".apex" / "metrics.prom").write_text(metrics_text, encoding="utf-8")
    print(f"[metrics] Written to .apex/metrics.prom ({claims_count} claims, {patches_applied_val} patches)")

    memory_bridge.close()


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

    policy = _build_policy()

    if _safety_gates_block(policy, automation_plan):
        return

    plugins = _load_plugins(config)
    use_fractal = _resolve_use_fractal(objective)

    if automation_plan:
        _run_automation_plan(
            plugins,
            config,
            policy,
            objective=objective,
            target_root=target_root,
            focus_branch=focus_branch,
            automation_plan=automation_plan,
            use_fractal=use_fractal,
        )
        return

    _run_orchestrator(
        policy,
        objective=objective,
        target_root=target_root,
        focus_branch=focus_branch,
        config=config,
    )


if __name__ == "__main__":
    main()
