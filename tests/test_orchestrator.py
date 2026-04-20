from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def make_orchestrator():
    return FractalResearchOrchestrator(
        config={
            "max_depth": 2,
            "max_total_nodes": 10,
            "top_k_questions": 2,
            "min_security": 0.8,
            "min_quality": 0.6,
            "min_novelty": 0.2,
        },
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


def test_orchestrator_returns_report():
    orchestrator = make_orchestrator()
    report = orchestrator.run("Test objective")
    assert report.objective == "Test objective"
    assert len(report.main_findings) >= 1
    assert isinstance(report.confidence_map, dict)
