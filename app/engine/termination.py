from app.models.enums import StopReason


class TerminationEngine:
    def __init__(self, config: dict) -> None:
        self.config = config

    def should_stop_before_expansion(self, node, budget_controller):
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
