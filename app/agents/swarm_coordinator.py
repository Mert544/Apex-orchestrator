from __future__ import annotations

from typing import Any

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus
from app.agents.registry import AgentRegistry
from app.automation.planner import AutonomousPlanner
from app.intent.parser import IntentParser


class SwarmCoordinator:
    """Event-driven coordinator that wires agents together via the bus.

    When SecurityAgent finds a risk, it emits `security.alert`.
    SwarmCoordinator listens and automatically routes to ClaimEvaluator.
    When ClaimEvaluator approves, it emits `claim.approved`.
    SwarmCoordinator routes to PatchGenerator, and so on.

    Usage:
        coordinator = SwarmCoordinator()
        coordinator.register_agents([SecurityAgent(), DocstringAgent()])
        coordinator.run_autonomous(intent="security audit", target="/path")
    """

    def __init__(self, bus: AgentBus | None = None) -> None:
        self.bus = bus or AgentBus()
        self.registry = AgentRegistry()
        self.planner = AutonomousPlanner()
        self.intent_parser = IntentParser()
        self._running = False
        self._results: list[dict[str, Any]] = []

    def register_agents(self, agents: list[Agent]) -> None:
        for agent in agents:
            agent.bus = self.bus
            self.registry.register_instance(agent)
            # Wire default event handlers
            self._wire_agent(agent)
        # Wire coordinator as the router between agents
        self._wire_coordinator()

    def _wire_agent(self, agent: Agent) -> None:
        """Subscribe agent to relevant topics based on its role."""
        role = agent.role.lower()

        if "security" in role:
            # When scan completes, security agent runs
            agent.on("scan.complete", lambda msg: self._handle_scan_complete(agent, msg))
            # When security alert emitted, route to evaluator
            agent.on("security.alert", lambda msg: self._route_to_evaluator(msg))

        if "evaluator" in role or "consensus" in role:
            agent.on("claim.submit", lambda msg: self._handle_claim_submit(agent, msg))
            agent.on("claim.approved", lambda msg: self._route_to_patcher(msg))

        if "patch" in role or "generator" in role:
            agent.on("patch.request", lambda msg: self._handle_patch_request(agent, msg))

        if "test" in role:
            agent.on("patch.applied", lambda msg: self._handle_patch_applied(agent, msg))

        # All agents listen for shutdown
        agent.on("swarm.shutdown", lambda msg: self._shutdown())

    def _wire_coordinator(self) -> None:
        """Subscribe coordinator to routing topics."""
        self.bus.subscribe("_coordinator", "security.alert", self._route_to_evaluator)
        self.bus.subscribe("_coordinator", "claim.approved", self._route_to_patcher)
        self.bus.subscribe("_coordinator", "patch.applied", self._route_to_tester)

    def _route_to_tester(self, msg: AgentMessage) -> None:
        """Route applied patches to test agent."""
        tester = self.registry.get_by_role("test")
        if tester:
            self._handle_patch_applied(tester, msg)

    def _handle_scan_complete(self, agent: Agent, msg: AgentMessage) -> None:
        """Trigger agent run when scan completes."""
        if agent.state == AgentState.IDLE:
            project_root = msg.payload.get("project_root", ".")
            result = agent.run(project_root=project_root)
            self._results.append(result)
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
            claims = [f"Risk in {r.get('file', '?')}: {r.get('issue', '')}" for r in risks]
            result = evaluator.run(claims=claims)
            for claim_result in result:
                if claim_result.final_verdict.name == "APPROVE":
                    self.bus.broadcast(
                        sender=evaluator.name,
                        topic="claim.approved",
                        payload={"claim": claim_result.claim, "confidence": claim_result.confidence},
                    )

    def _handle_claim_submit(self, agent: Agent, msg: AgentMessage) -> None:
        """Evaluator processes submitted claims."""
        claims = msg.payload.get("claims", [])
        if claims:
            result = agent.run(claims=claims)
            # Results are emitted inside _route_to_evaluator after run

    def _route_to_patcher(self, msg: AgentMessage) -> None:
        """Route approved claims to patch generator."""
        patcher = self.registry.get_by_role("patcher")
        if patcher:
            self.bus.broadcast(
                sender="swarm",
                topic="patch.request",
                payload={"claim": msg.payload.get("claim"), "confidence": msg.payload.get("confidence")},
            )

    def _handle_patch_request(self, agent: Agent, msg: AgentMessage) -> None:
        """Patch generator processes requests."""
        claim = msg.payload.get("claim", "")
        # Simplified: just mark as processed
        result = {"claim": claim, "patched": True, "agent": agent.name}
        agent.results.append(result)
        self.bus.broadcast(
            sender=agent.name,
            topic="patch.applied",
            payload=result,
        )

    def _handle_patch_applied(self, agent: Agent, msg: AgentMessage) -> None:
        """Test agent verifies patches."""
        result = agent.run(project_root=msg.payload.get("project_root", "."))
        self._results.append(result)

    def _shutdown(self) -> None:
        self._running = False

    def run_autonomous(self, goal: str, target: str = ".", mode: str = "supervised") -> list[dict[str, Any]]:
        """Run the full autonomous loop: intent → plan → event-driven execution."""
        intent = self.intent_parser.parse(goal, explicit_mode=mode)
        plan = self.planner.build_plan(intent)

        print(f"[swarm] Goal: {intent.goal}")
        print(f"[swarm] Plan: {plan.plan_name} | Agents: {plan.agents} | Mode: {plan.mode}")

        self._running = True
        self._results.clear()

        # Kick off the first event based on intent
        if "security" in plan.agents or "security" in intent.goal.lower():
            self.bus.broadcast(
                sender="swarm",
                topic="scan.complete",
                payload={"project_root": target, "trigger": "security"},
            )
        elif "docstring" in plan.agents:
            self.bus.broadcast(
                sender="swarm",
                topic="scan.complete",
                payload={"project_root": target, "trigger": "docstring"},
            )
        elif "test" in plan.agents:
            self.bus.broadcast(
                sender="swarm",
                topic="scan.complete",
                payload={"project_root": target, "trigger": "test"},
            )
        else:
            # Generic scan trigger
            self.bus.broadcast(
                sender="swarm",
                topic="scan.complete",
                payload={"project_root": target, "trigger": "general"},
            )

        # Wait for pipeline to complete (simplified synchronous version)
        import time
        max_wait = 60.0 if mode == "autonomous" else 30.0
        waited = 0.0
        while self._running and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
            # Check if all agents are idle
            if all(a.state in (AgentState.IDLE, AgentState.COMPLETED, AgentState.FAILED) for a in self.registry.agents.values()):
                break

        print(f"[swarm] Completed in {waited:.1f}s with {len(self._results)} result(s)")
        return self._results

    def stats(self) -> dict[str, Any]:
        return {
            "agents": {name: agent.to_dict() for name, agent in self.registry.agents.items()},
            "bus": self.bus.stats(),
            "results_count": len(self._results),
        }
