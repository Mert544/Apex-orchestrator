import subprocess

from app.engine.budget import BudgetController
from app.engine.self_healing import SelfHealingTestEngine
from app.engine.termination import TerminationEngine
from app.execution.semantic.result import SemanticPatchResult
from app.models.enums import StopReason
from app.models.node import ResearchNode


# --------------------------------------------------------------------------- #
# SelfHealingTestEngine
# --------------------------------------------------------------------------- #


class _FakeProc:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


def test_run_tests_parses_failures_and_dedupes(tmp_path, monkeypatch):
    stdout = (
        "FAILED tests/test_a.py::test_one - AssertionError\n"
        "FAILED tests/test_a.py::test_two - AssertionError\n"
        "some other line\n"
        "FAILED tests/test_b.py::test_three - ValueError\n"
        "FAILED no_marker_here\n"
    )

    def fake_run(*args, **kwargs):
        return _FakeProc(stdout=stdout, stderr="errtail")

    monkeypatch.setattr(subprocess, "run", fake_run)

    engine = SelfHealingTestEngine(tmp_path)
    failures, output = engine._run_tests()

    assert failures == ["tests/test_a.py", "tests/test_b.py"]
    assert output == stdout + "errtail"


def test_run_tests_no_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeProc(stdout="all good\n")
    )
    engine = SelfHealingTestEngine(tmp_path)
    failures, output = engine._run_tests()
    assert failures == []


def test_init_defaults_and_overrides(tmp_path):
    default_engine = SelfHealingTestEngine(tmp_path)
    assert default_engine.test_command == "pytest"
    assert default_engine.max_iterations == 3
    assert default_engine.root == tmp_path.resolve()

    custom = SelfHealingTestEngine(
        tmp_path, max_iterations=5, test_command="pytest tests/"
    )
    assert custom.max_iterations == 5
    assert custom.test_command == "pytest tests/"


def test_heal_passes_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeProc(stdout="passing\n")
    )
    engine = SelfHealingTestEngine(tmp_path)
    result = engine.heal()

    assert result.iterations == 1
    assert result.original_failures == []
    assert result.fixed_failures == []
    assert result.remaining_failures == []
    assert result.patches_applied == []


def test_heal_repairs_failure_then_passes(tmp_path, monkeypatch):
    # First run reports a failure, subsequent runs report none -> fixed.
    calls = {"n": 0}
    failing = "FAILED tests/test_x.py::test_y - AssertionError\n"

    def fake_run(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeProc(stdout=failing)
        return _FakeProc(stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_generate(self, **kwargs):
        return SemanticPatchResult(patch_requests=[{"file": "tests/test_x.py"}])

    monkeypatch.setattr(
        "app.execution.semantic_patch_generator.SemanticPatchGenerator.generate",
        fake_generate,
    )

    engine = SelfHealingTestEngine(tmp_path)
    result = engine.heal()

    assert result.original_failures == ["tests/test_x.py"]
    assert len(result.patches_applied) == 1
    assert result.remaining_failures == []
    assert result.fixed_failures == ["tests/test_x.py"]


def test_heal_stops_when_no_patches_produced(tmp_path, monkeypatch):
    # Every run reports the same failure; generator yields no patch requests,
    # so heal breaks early via the `not fixed_this_round` branch.
    failing = "FAILED tests/test_z.py::test_q - AssertionError\n"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeProc(stdout=failing)
    )

    def fake_generate(self, **kwargs):
        return SemanticPatchResult(patch_requests=[])

    monkeypatch.setattr(
        "app.execution.semantic_patch_generator.SemanticPatchGenerator.generate",
        fake_generate,
    )

    engine = SelfHealingTestEngine(tmp_path)
    result = engine.heal()

    assert result.original_failures == ["tests/test_z.py"]
    assert result.iterations == 1
    assert result.patches_applied == []
    assert result.remaining_failures == ["tests/test_z.py"]
    assert result.fixed_failures == []


def test_heal_exhausts_iterations_when_patch_does_not_fix(tmp_path, monkeypatch):
    # Patches are produced each round but failures persist across all runs.
    failing = "FAILED tests/test_p.py::test_r - AssertionError\n"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeProc(stdout=failing)
    )

    def fake_generate(self, **kwargs):
        return SemanticPatchResult(patch_requests=[{"file": "tests/test_p.py"}])

    monkeypatch.setattr(
        "app.execution.semantic_patch_generator.SemanticPatchGenerator.generate",
        fake_generate,
    )

    engine = SelfHealingTestEngine(tmp_path, max_iterations=2)
    result = engine.heal()

    assert result.iterations == 2
    assert len(result.patches_applied) == 2
    assert result.remaining_failures == ["tests/test_p.py"]
    assert result.fixed_failures == []


# --------------------------------------------------------------------------- #
# TerminationEngine
# --------------------------------------------------------------------------- #


def _config(**overrides):
    cfg = {
        "max_depth": 5,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    }
    cfg.update(overrides)
    return cfg


def test_set_deadline_sets_run_and_node_deadlines():
    engine = TerminationEngine(_config())
    engine.set_deadline(100.0, max_run_seconds=10.0, max_expand_seconds=3.0)
    assert engine._deadline == 110.0
    assert engine._node_deadline == 3.0


def test_set_deadline_ignores_nonpositive_values():
    engine = TerminationEngine(_config())
    engine.set_deadline(100.0, max_run_seconds=0.0, max_expand_seconds=0.0)
    assert engine._deadline is None
    assert engine._node_deadline is None


def test_is_timed_out_false_when_no_deadline():
    engine = TerminationEngine(_config())
    assert engine.is_timed_out() is False


def test_is_timed_out_true_when_deadline_passed(monkeypatch):
    engine = TerminationEngine(_config())
    monkeypatch.setattr(
        "app.engine.termination.time.perf_counter", lambda: 1000.0
    )
    engine._deadline = 500.0
    assert engine.is_timed_out() is True


def test_is_timed_out_false_when_deadline_not_reached(monkeypatch):
    engine = TerminationEngine(_config())
    monkeypatch.setattr(
        "app.engine.termination.time.perf_counter", lambda: 100.0
    )
    engine._deadline = 500.0
    assert engine.is_timed_out() is False


def test_should_stop_before_expansion_timeout(monkeypatch):
    engine = TerminationEngine(_config())
    monkeypatch.setattr(engine, "is_timed_out", lambda: True)
    node = ResearchNode(id="n", claim="c", depth=0)
    budget = BudgetController(max_total_nodes=10)
    assert engine.should_stop_before_expansion(node, budget) == StopReason.TIMEOUT


def test_should_stop_before_expansion_max_depth():
    engine = TerminationEngine(_config(max_depth=2))
    node = ResearchNode(id="n", claim="c", depth=2)
    budget = BudgetController(max_total_nodes=10)
    assert (
        engine.should_stop_before_expansion(node, budget)
        == StopReason.MAX_DEPTH
    )


def test_should_stop_before_expansion_budget_exhausted():
    engine = TerminationEngine(_config(max_depth=10))
    node = ResearchNode(id="n", claim="c", depth=0)
    budget = BudgetController(max_total_nodes=1)
    budget.consume_node()
    assert (
        engine.should_stop_before_expansion(node, budget)
        == StopReason.BUDGET_EXHAUSTED
    )


def test_should_stop_before_expansion_none():
    engine = TerminationEngine(_config(max_depth=10))
    node = ResearchNode(id="n", claim="c", depth=0)
    budget = BudgetController(max_total_nodes=10)
    assert engine.should_stop_before_expansion(node, budget) is None


def test_should_stop_after_scoring_low_security():
    engine = TerminationEngine(_config())
    node = ResearchNode(id="n", claim="c", security=0.1)
    assert engine.should_stop_after_scoring(node) == StopReason.LOW_SECURITY


def test_should_stop_after_scoring_low_quality():
    engine = TerminationEngine(_config())
    node = ResearchNode(id="n", claim="c", security=1.0, quality=0.1)
    assert engine.should_stop_after_scoring(node) == StopReason.LOW_QUALITY


def test_should_stop_after_scoring_low_novelty():
    engine = TerminationEngine(_config())
    node = ResearchNode(
        id="n", claim="c", security=1.0, quality=1.0, novelty=0.0
    )
    assert engine.should_stop_after_scoring(node) == StopReason.LOW_NOVELTY


def test_should_stop_after_scoring_none():
    engine = TerminationEngine(_config())
    node = ResearchNode(
        id="n", claim="c", security=1.0, quality=1.0, novelty=1.0
    )
    assert engine.should_stop_after_scoring(node) is None
