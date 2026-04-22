from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SwarmTask:
    task_id: str
    branch: str
    objective: str
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "objective": self.objective,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class SwarmResult:
    tasks: list[SwarmTask] = field(default_factory=list)
    completed_count: int = 0
    failed_count: int = 0
    aggregated_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "aggregated_output": self.aggregated_output,
        }


class SwarmCoordinator:
    """Coordinate multiple Apex agents working on different branches in parallel.

    Each agent gets its own branch and runs the focused_branch plan.
    Results are aggregated into a single report.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max_workers

    def run(self, branches: list[str], objective: str, runner_factory: Callable[[str], dict[str, Any]]) -> SwarmResult:
        """Run agents in parallel for each branch.

        Args:
            branches: List of branch paths like ["x.a", "x.b"]
            objective: Shared objective for all agents
            runner_factory: Callable that takes a branch and returns the agent result dict
        """
        tasks = [SwarmTask(task_id=f"swarm-{i}", branch=b, objective=objective) for i, b in enumerate(branches)]
        result = SwarmResult(tasks=tasks)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._run_agent, task, runner_factory): task
                for task in tasks
            }
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    task.result = future.result()
                    task.status = "completed"
                    result.completed_count += 1
                except Exception as exc:
                    task.error = str(exc)
                    task.status = "failed"
                    result.failed_count += 1

        # Aggregate branch maps and actions
        all_branch_maps: dict[str, str] = {}
        all_actions: list[str] = []
        for task in tasks:
            if task.status == "completed":
                res = task.result
                if isinstance(res, dict):
                    bm = res.get("branch_map", {})
                    if isinstance(bm, dict):
                        all_branch_maps.update(bm)
                    acts = res.get("recommended_actions", [])
                    if isinstance(acts, list):
                        all_actions.extend(acts)

        result.aggregated_output = {
            "branches_covered": [t.branch for t in tasks if t.status == "completed"],
            "branch_map": all_branch_maps,
            "recommended_actions": list(dict.fromkeys(all_actions)),  # dedup preserve order
        }
        return result

    @staticmethod
    def _run_agent(task: SwarmTask, runner_factory: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        return runner_factory(task.branch)
