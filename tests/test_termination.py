from app.engine.budget import BudgetController
from app.engine.termination import TerminationEngine
from app.models.enums import StopReason
from app.models.node import ResearchNode


def test_termination_stops_on_depth():
    engine = TerminationEngine({
        "max_depth": 1,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    })
    node = ResearchNode(id="n1", claim="claim", depth=1)
    budget = BudgetController(max_total_nodes=10)
    assert engine.should_stop_before_expansion(node, budget) == StopReason.MAX_DEPTH
