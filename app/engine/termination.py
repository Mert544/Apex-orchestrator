import time

from app.models.enums import StopReason


class TerminationEngine:
    def __init__(self, config: dict) -> None:
        self.config = config
        self._deadline: float | None = None
        self._node_deadline: float | None = None

    def set_deadline(self, start_time: float, max_run_seconds: float = 0.0, max_expand_seconds: float = 0.0) -> None:
        if max_run_seconds > 0:
            self._deadline = start_time + max_run_seconds
        if max_expand_seconds > 0:
            self._node_deadline = max_expand_seconds

    def is_timed_out(self) -> bool:
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            return True
        return False

    def should_stop_before_expansion(self, node, budget_controller):
        if self.is_timed_out():
            return StopReason.TIMEOUT
        if node.depth >= int(self.config["max_depth"]):
            return StopReason.MAX_DEPTH
        if budget_controller.exhausted:
            return StopReason.BUDGET_EXHAUSTED
        return None

    def should_stop_after_scoring(self, node):
        if node.security < float(self.config["min_security"]):
            return StopReason.LOW_SECURITY
        if node.quality < float(self.config["min_quality"]):
            return StopReason.LOW_QUALITY
        if node.novelty < float(self.config["min_novelty"]):
            return StopReason.LOW_NOVELTY
        return None
