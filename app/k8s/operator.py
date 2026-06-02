from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApexRunSpec:
    """Spec for ApexRun CRD."""

    target_repo: str
    goal: str = "scan project"
    mode: str = "report"
    schedule: str = ""
    image: str = "apex-orchestrator:latest"


@dataclass
class ApexRunStatus:
    """Status for ApexRun CRD."""

    last_run_time: str = ""
    last_result: str = ""
    phase: str = "Pending"


@dataclass
class ApexRunResource:
    """In-memory representation of an ApexRun custom resource."""

    name: str
    namespace: str
    spec: ApexRunSpec
    status: ApexRunStatus = field(default_factory=ApexRunStatus)


class ApexOperator:
    """Mock Kubernetes operator for ApexRun CRD.

    Reconciles ApexRun resources by running Apex and updating status.
    In production this would use kubernetes-client/python to watch CRDs.

    Usage:
        op = ApexOperator()
        op.add_resource(ApexRunResource(name="daily-scan", namespace="default", spec=...))
        op.reconcile_all()
    """

    def __init__(self) -> None:
        self.resources: dict[str, ApexRunResource] = {}
        self.reconcile_count = 0

    def add_resource(self, resource: ApexRunResource) -> None:
        key = f"{resource.namespace}/{resource.name}"
        self.resources[key] = resource

    def remove_resource(self, namespace: str, name: str) -> None:
        key = f"{namespace}/{name}"
        if key in self.resources:
            del self.resources[key]

    def reconcile_all(self) -> list[dict[str, Any]]:
        """Run reconciliation loop over all resources."""
        results = []
        for key, resource in list(self.resources.items()):
            result = self._reconcile(resource)
            results.append({"resource": key, "result": result})
            self.reconcile_count += 1
        return results

    def _reconcile(self, resource: ApexRunResource) -> dict[str, Any]:
        resource.status.phase = "Running"
        try:
            # Simulate Apex run
            from app.intent.parser import IntentParser
            from app.automation.planner import AutonomousPlanner

            intent = IntentParser().parse(resource.spec.goal, explicit_mode=resource.spec.mode)
            plan = AutonomousPlanner().build_plan(intent)

            resource.status.phase = "Succeeded"
            resource.status.last_run_time = str(time.time())
            resource.status.last_result = f"Plan: {plan.plan_name}, Steps: {len(plan.steps)}"
            return {"ok": True, "plan": plan.plan_name}
        except Exception as exc:
            resource.status.phase = "Failed"
            resource.status.last_result = str(exc)
            return {"ok": False, "error": str(exc)}

    def get_resource(self, namespace: str, name: str) -> ApexRunResource | None:
        return self.resources.get(f"{namespace}/{name}")

    def to_manifest(self, resource: ApexRunResource) -> dict[str, Any]:
        """Export resource as Kubernetes-style manifest."""
        return {
            "apiVersion": "apex.io/v1",
            "kind": "ApexRun",
            "metadata": {"name": resource.name, "namespace": resource.namespace},
            "spec": {
                "targetRepo": resource.spec.target_repo,
                "goal": resource.spec.goal,
                "mode": resource.spec.mode,
                "schedule": resource.spec.schedule,
                "image": resource.spec.image,
            },
            "status": {
                "lastRunTime": resource.status.last_run_time,
                "lastResult": resource.status.last_result,
                "phase": resource.status.phase,
            },
        }
