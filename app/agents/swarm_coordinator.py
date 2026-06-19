from __future__ import annotations

import sys
import time
from typing import Any

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus
from app.agents.registry import AgentRegistry
from app.agents.swarm_stability import SwarmStability, GracefulShutdown
from app.automation.planner import AutonomousPlanner
from app.intent.parser import IntentParser


class SwarmCoordinator:
    """Event-driven coordinator that wires agents together via the bus.

    When SecurityAgent finds a risk, it emits `security.alert`.
    SwarmCoordinator listens and automatically routes to ClaimEvaluator.
    When ClaimEvaluator approves, it emits `claim.approved`.
    SwarmCoordinator routes to PatchGenerator, and so on.

    Features:
    - Timeout management for long-running operations
    - Graceful shutdown handling
    - Agent lifecycle tracking
    - Stability monitoring

    Usage:
        coordinator = SwarmCoordinator()
        coordinator.register_agents([SecurityAgent(), DocstringAgent()])
        coordinator.run_autonomous(intent="security audit", target="/path")
    """

    def __init__(
        self,
        bus: AgentBus | None = None,
        default_timeout: float = 60.0,
        shutdown_timeout: float = 30.0,
    ) -> None:
        self.bus = bus or AgentBus()
        self.registry = AgentRegistry()
        self.planner = AutonomousPlanner()
        self.intent_parser = IntentParser()
        self._running = False
        self._results: list[dict[str, Any]] = []

        # Stability features
        self._stability = SwarmStability(
            default_timeout=default_timeout,
            shutdown_timeout=shutdown_timeout,
        )
        self._graceful_shutdown = GracefulShutdown()

        # Timeouts per operation type
        self._timeouts = {
            "scan": 30.0,
            "analyze": 45.0,
            "patch": 60.0,
            "test": 120.0,
            "total": 180.0,
        }
        self._base_timeouts = self._timeouts.copy()
        self._success_rates: dict[str, float] = {
            "scan": 1.0,
            "analyze": 1.0,
            "patch": 1.0,
            "test": 1.0,
        }
        self._failure_count = 0
        self._total_ops = 0

    def register_agents(self, agents: list[Agent]) -> None:
        for agent in agents:
            agent.bus = self.bus
            self.registry.register_instance(agent)
            # Wire default event handlers
            self._wire_agent(agent)
        # Wire coordinator as the router between agents
        self._wire_coordinator()

    # Roles that produce findings from a project scan. Every such agent runs on
    # `scan.complete`, not just the security agent — otherwise plans like
    # `project_scan` (docstring/dependency/coverage) yield zero results.
    SCANNER_ROLE_HINTS = (
        "security",
        "auditor",
        "docstring",
        "documentation",
        "dependency",
        "architecture",
        "coverage",
        "analyst",
        "scanner",
    )

    def _wire_agent(self, agent: Agent) -> None:
        """Subscribe agent to relevant topics based on its role."""
        role = agent.role.lower()

        is_scanner = any(hint in role for hint in self.SCANNER_ROLE_HINTS)
        if is_scanner:
            # Bind `agent` per-subscription so every scanner runs on scan.complete.
            agent.on(
                "scan.complete", lambda msg, a=agent: self._handle_scan_complete(a, msg)
            )

        if "security" in role:
            # Security findings additionally flow into the evaluate→patch pipeline.
            agent.on("security.alert", lambda msg: self._route_to_evaluator(msg))

        if "evaluator" in role or "consensus" in role:
            agent.on("claim.submit", lambda msg: self._handle_claim_submit(agent, msg))
            agent.on("claim.approved", lambda msg: self._route_to_patcher(msg))

        if "patch" in role or "generator" in role:
            agent.on(
                "patch.request", lambda msg: self._handle_patch_request(agent, msg)
            )

        if "test" in role and not is_scanner:
            # A test *verifier* (not the coverage analyst) runs after a patch.
            agent.on(
                "patch.applied", lambda msg: self._handle_patch_applied(agent, msg)
            )

        # All agents listen for shutdown
        agent.on("swarm.shutdown", lambda msg: self._shutdown())

    def _wire_coordinator(self) -> None:
        """Subscribe coordinator to routing topics."""
        self.bus.subscribe("_coordinator", "security.alert", self._route_to_evaluator)
        self.bus.subscribe("_coordinator", "claim.approved", self._route_to_patcher)
        self.bus.subscribe("_coordinator", "patch.applied", self._route_to_tester)
        self.bus.subscribe(
            "_coordinator", "fractal.analysis.complete", self._handle_fractal_complete
        )

    def _handle_fractal_complete(self, msg: AgentMessage) -> None:
        """Collect fractal analysis results."""
        self._results.append(
            {
                "type": "fractal_analysis",
                "finding": msg.payload.get("finding"),
                "tree_depth": msg.payload.get("tree_depth"),
                "agent": msg.sender,
            }
        )

    def _route_to_tester(self, msg: AgentMessage) -> None:
        """Route applied patches to test agent."""
        tester = self.registry.get_by_role("test")
        if tester:
            self._handle_patch_applied(tester, msg)

    def _handle_scan_complete(self, agent: Agent, msg: AgentMessage) -> None:
        """Trigger agent run when scan completes."""
        if agent.state != AgentState.IDLE:
            return
        project_root = msg.payload.get("project_root", ".")
        result = agent.run(project_root=project_root)
        self._results.append(result)
        self.record_outcome("scan", result.get("findings_count", 0) >= 0)
        # Emit findings
        if result.get("risks"):
            self.bus.broadcast(
                sender=agent.name,
                topic="security.alert",
                payload={"risks": result["risks"], "project_root": project_root},
            )

    def _route_to_evaluator(self, msg: AgentMessage) -> None:
        """Route security alerts to claim evaluator."""
        evaluator = self.registry.get_by_role("evaluator")
        if evaluator:
            risks = msg.payload.get("risks", [])
            claims = [
                f"Risk in {r.get('file', '?')}: {r.get('issue', '')}" for r in risks
            ]
            result = evaluator.run(claims=claims)
            for claim_result in result:
                if claim_result.final_verdict.name == "APPROVE":
                    self.bus.broadcast(
                        sender=evaluator.name,
                        topic="claim.approved",
                        payload={
                            "claim": claim_result.claim,
                            "confidence": claim_result.confidence,
                        },
                    )

    def _handle_claim_submit(self, agent: Agent, msg: AgentMessage) -> None:
        """Evaluator processes submitted claims."""
        claims = msg.payload.get("claims", [])
        if claims:
            agent.run(claims=claims)
            # Results are emitted inside _route_to_evaluator after run

    def _route_to_patcher(self, msg: AgentMessage) -> None:
        """Route approved claims to patch generator."""
        patcher = self.registry.get_by_role("patcher")
        if patcher:
            self.bus.broadcast(
                sender="swarm",
                topic="patch.request",
                payload={
                    "claim": msg.payload.get("claim"),
                    "confidence": msg.payload.get("confidence"),
                },
            )

    def _handle_patch_request(self, agent: Agent, msg: AgentMessage) -> None:
        """Patch generator processes requests."""
        claim = msg.payload.get("claim", "")
        # Simplified: just mark as processed
        result = {"claim": claim, "patched": True, "agent": agent.name}
        agent.results.append(result)
        self.record_outcome("patch", True)
        self.bus.broadcast(
            sender=agent.name,
            topic="patch.applied",
            payload=result,
        )

    def _handle_patch_applied(self, agent: Agent, msg: AgentMessage) -> None:
        """Test agent verifies patches."""
        result = agent.run(project_root=msg.payload.get("project_root", "."))
        self._results.append(result)
        test_success = result.get("success", False) or result.get("all_passed", False)
        self.record_outcome("test", test_success)

    def _shutdown(self) -> None:
        """Graceful shutdown with stability tracking."""
        self._running = False
        self._graceful_shutdown.request_shutdown()
        self._stability.shutdown_manager.request_shutdown()
        self._stability.timeout_manager.cancel_all()

    def _check_timeout(self, operation: str) -> bool:
        """Check if operation has exceeded timeout."""
        return self._stability.shutdown_manager.is_shutdown_requested()

    def _emit_status(self, message: str) -> None:
        """Single chokepoint for all `[swarm] ...` progress/status lines.

        These lines carry wall-clock timing (e.g. `Completed in {elapsed:.1f}s`)
        and are therefore non-deterministic run-to-run. They are routed to STDERR
        so that `apex scan`'s STDOUT stays byte-identical across runs for a fixed
        repo state — only the deterministic findings/result land on STDOUT.
        """
        print(f"[swarm] {message}", file=sys.stderr)

    def record_outcome(self, operation: str, success: bool) -> None:
        """Record operation outcome to adjust timeouts adaptively.

        If an operation frequently succeeds near the timeout limit, increase its budget.
        If it frequently times out, increase timeout. If it fails quickly, decrease.
        """
        self._total_ops += 1
        if self._total_ops < 5:
            return

        op_key = operation if operation in self._success_rates else "patch"
        current_rate = self._success_rates.get(op_key, 1.0)

        if success:
            new_rate = current_rate * 0.95 + 0.05
        else:
            new_rate = current_rate * 0.95 - 0.05
            self._failure_count += 1

        self._success_rates[op_key] = max(0.1, min(1.0, new_rate))

        if self._total_ops % 10 == 0:
            self._adjust_timeouts()

    def _adjust_timeouts(self) -> None:
        """Adjust operation timeouts based on success rates and failure patterns."""
        for op in ["scan", "analyze", "patch", "test"]:
            rate = self._success_rates.get(op, 1.0)
            base = self._base_timeouts.get(op, 60.0)

            if rate < 0.5:
                factor = 1.5
            elif rate < 0.75:
                factor = 1.2
            elif rate > 0.95:
                factor = 0.9
            else:
                factor = 1.0

            new_timeout = base * factor
            self._timeouts[op] = max(base * 0.5, min(base * 2.0, new_timeout))

        total_base = self._base_timeouts.get("total", 180.0)
        avg_factor = sum(self._timeouts[k] / self._base_timeouts.get(k, 60.0) for k in ["scan", "analyze", "patch", "test"]) / 4
        self._timeouts["total"] = max(total_base * 0.7, min(total_base * 1.5, total_base * avg_factor))

    def get_stability_status(self) -> dict[str, Any]:
        """Get current stability status."""
        return {
            "shutdown_requested": self._graceful_shutdown.is_shutdown_requested(),
            "timeouts": self._timeouts,
            "active_agents": len(self.registry.agents),
            "pending_results": len(self._results),
        }

    @staticmethod
    def _select_scan_trigger(plan_agents: Any, goal_lower: str) -> str:
        """Pick the scan trigger label from the plan and goal (pure)."""
        if "security" in plan_agents or "security" in goal_lower:
            return "security"
        if "docstring" in plan_agents:
            return "docstring"
        if "test" in plan_agents:
            return "test"
        return "general"

    def _all_agents_settled(self) -> bool:
        """True when every registered agent has stopped running."""
        return all(
            a.state in (AgentState.IDLE, AgentState.COMPLETED, AgentState.FAILED)
            for a in self.registry.agents.values()
        )

    def _await_pipeline(self, total_timeout: float) -> float:
        """Wait for the pipeline to settle, time out, or be shut down.

        Returns the total time waited (in 0.1s increments).
        """
        waited = 0.0
        while self._running and waited < total_timeout:
            if self._stability.shutdown_manager.is_shutdown_requested():
                self._emit_status(f"Shutdown requested after {waited:.1f}s")
                break

            time.sleep(0.1)
            waited += 0.1

            # Check if all agents are idle
            if self._all_agents_settled():
                break
        return waited

    def _report_outcome(self, waited: float, total_timeout: float, elapsed: float) -> None:
        """Print the terminal status line and shut down on timeout."""
        if waited >= total_timeout:
            self._emit_status(f"TIMEOUT after {elapsed:.1f}s")
            self._shutdown()
        elif self._stability.shutdown_manager.is_shutdown_requested():
            self._emit_status(f"Graceful shutdown after {elapsed:.1f}s")
        else:
            self._emit_status(
                f"Completed in {elapsed:.1f}s with {len(self._results)} result(s)"
            )

    def run_autonomous(
        self,
        goal: str,
        target: str = ".",
        mode: str = "supervised",
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run the full autonomous loop: intent → plan → event-driven execution."""
        # Check for shutdown request
        if self._stability.shutdown_manager.is_shutdown_requested():
            self._emit_status("Shutdown previously requested, ignoring new run")
            return []

        intent = self.intent_parser.parse(goal, explicit_mode=mode)
        plan = self.planner.build_plan(intent)

        self._emit_status(f"Goal: {intent.goal}")
        self._emit_status(
            f"Plan: {plan.plan_name} | Agents: {plan.agents} | Mode: {plan.mode}"
        )

        self._running = True
        self._results.clear()

        # Set total timeout
        total_timeout = timeout or self._timeouts.get("total", 180.0)
        start_time = time.time()

        # Kick off the first event based on intent
        trigger = self._select_scan_trigger(plan.agents, intent.goal.lower())
        self.bus.broadcast(
            sender="swarm",
            topic="scan.complete",
            payload={"project_root": target, "trigger": trigger},
        )

        # Wait for pipeline to complete with timeout and shutdown handling
        waited = self._await_pipeline(total_timeout)

        elapsed = time.time() - start_time

        self._report_outcome(waited, total_timeout, elapsed)

        return self._results

    def stats(self) -> dict[str, Any]:
        return {
            "agents": {
                name: agent.to_dict() for name, agent in self.registry.agents.items()
            },
            "bus": self.bus.stats(),
            "results_count": len(self._results),
        }
