class ModelRouter:
    """Simple placeholder router for future model routing decisions."""

    def route(self, task_name: str) -> str:
        if task_name in {"validation", "synthesis", "decomposition"}:
            return "deep_model"
        return "cheap_model"
