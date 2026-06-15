"""Edge- and error-path coverage for FractalResearchOrchestrator (core.py).

Targets the previously-uncovered branches: focus-branch hit/miss, on_progress
callbacks, deep-reasoning failure isolation, empty-graph mean relevance, the
optional LLM summary block, the per-question dedup/spam/memory guards, the
no-fresh-questions stop, and the mid-expansion budget-exhaustion stops.

Deterministic, offline, stdlib-only. Heavy collaborators are monkeypatched so
each test isolates exactly one branch.
"""

from app.models.enums import NodeStatus, StopReason
from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.relevance_scorer import RelevanceScorer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _orch(memory_store=None, **overrides):
    config = {
        "max_depth": 2,
        "max_total_nodes": 50,
        "top_k_questions": 2,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    }
    config.update(overrides)
    return FractalResearchOrchestrator(
        config=config,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
        memory_store=memory_store,
    )


def _root(orch, claim="The system should validate all untrusted input thoroughly.", depth=0):
    orch.relevance_scorer = RelevanceScorer(claim)
    return orch.node_factory.make_node(id="root", claim=claim, depth=depth, branch_path="x")


# --------------------------------------------------------------------------- #
# run(): focus-branch resolution
# --------------------------------------------------------------------------- #


class _FocusMemoryStore:
    """Memory store that hydrates a branch_map so a focus branch resolves."""

    def __init__(self, branch, claim, question):
        self._state = {
            "last_full_report": {
                "branch_map": {branch: claim},
                "branch_questions": {branch: question},
            }
        }

    def hydrate_graph(self, graph):
        return self._state

    def persist_run(self, objective, report, nodes):
        return {}


def test_run_focus_branch_hit_seeds_focus_root():
    store = _FocusMemoryStore("x.0", "Cached focus claim about input validation.", "What about it?")
    orch = _orch(memory_store=store)

    report = orch.run("Validate input", focus_branch="x.0")

    assert orch.debug_stats["focus_branch_hits"] == 1
    assert orch.debug_stats["focus_branch_misses"] == 0
    # A focus-root node was created and explored.
    ids = [n.id for n in orch.graph.get_all_nodes()]
    assert "focus-root" in ids
    assert report.objective == "Validate input"


def test_run_focus_branch_miss_falls_back_to_full_scan():
    # Memory state has no matching branch -> resolver returns (None, None).
    store = _FocusMemoryStore("other.branch", "Unrelated", "Q")
    orch = _orch(memory_store=store)

    report = orch.run("Validate input", focus_branch="x.0")

    assert orch.debug_stats["focus_branch_misses"] == 1
    assert orch.debug_stats["focus_branch_hits"] == 0
    assert "focus-root" not in [n.id for n in orch.graph.get_all_nodes()]
    assert report.objective == "Validate input"


# --------------------------------------------------------------------------- #
# run(): on_progress callback
# --------------------------------------------------------------------------- #


def test_run_invokes_on_progress_through_all_phases():
    orch = _orch()
    events = []

    def on_progress(phase, current, total):
        events.append((phase, current, total))

    orch.run("Validate untrusted input thoroughly", on_progress=on_progress)

    phases = [e[0] for e in events]
    assert "decompose" in phases
    assert "expand" in phases
    assert "complete" in phases
    # The terminal event reports graph size on both axes.
    complete = [e for e in events if e[0] == "complete"][-1]
    assert complete[1] == complete[2] == orch.graph.size()


# --------------------------------------------------------------------------- #
# _mean_relevance: empty graph
# --------------------------------------------------------------------------- #


def test_mean_relevance_empty_graph_returns_one():
    orch = _orch()
    assert orch._mean_relevance() == 1.0


# --------------------------------------------------------------------------- #
# _apply_deep_reasoning: failure isolation
# --------------------------------------------------------------------------- #


def test_deep_reasoning_failure_is_isolated(monkeypatch):
    orch = _orch()
    node = _root(orch)

    def boom(*_a, **_k):
        raise RuntimeError("counterfactual blew up")

    monkeypatch.setattr(orch.counterfactual_generator, "generate", boom)
    traces = []
    monkeypatch.setattr(orch.debug, "trace", lambda kind, *a, **k: traces.append(kind))

    # Must not raise even though the engine throws.
    orch._apply_deep_reasoning(node)

    assert "deep_reasoning_error" in traces


# --------------------------------------------------------------------------- #
# _attach_llm_summary: optional LLM enrichment block
# --------------------------------------------------------------------------- #


class _Report:
    def __init__(self, findings):
        self.main_findings = findings
        self.llm_summary = None


def test_attach_llm_summary_noop_when_unavailable(monkeypatch):
    orch = _orch()
    monkeypatch.setattr(orch.llm_adapter, "is_available", lambda: False)
    report = _Report(["finding a"])

    orch._attach_llm_summary(report)

    assert report.llm_summary is None


def test_attach_llm_summary_noop_when_no_findings(monkeypatch):
    orch = _orch()
    monkeypatch.setattr(orch.llm_adapter, "is_available", lambda: True)
    report = _Report([])

    orch._attach_llm_summary(report)

    assert report.llm_summary is None


def test_attach_llm_summary_sets_summary_when_available(monkeypatch):
    orch = _orch()
    monkeypatch.setattr(orch.llm_adapter, "is_available", lambda: True)
    monkeypatch.setattr(orch.llm_adapter, "summarize_results", lambda f: "EXEC SUMMARY")
    report = _Report(["finding a", "finding b"])

    orch._attach_llm_summary(report)

    assert report.llm_summary == "EXEC SUMMARY"


def test_attach_llm_summary_degrades_on_provider_error(monkeypatch):
    orch = _orch()
    monkeypatch.setattr(orch.llm_adapter, "is_available", lambda: True)

    def boom(_f):
        raise RuntimeError("provider down")

    monkeypatch.setattr(orch.llm_adapter, "summarize_results", boom)
    report = _Report(["finding a"])

    # Silently degrades back to the deterministic report.
    orch._attach_llm_summary(report)
    assert report.llm_summary is None


def test_attach_llm_summary_ignores_empty_summary(monkeypatch):
    orch = _orch()
    monkeypatch.setattr(orch.llm_adapter, "is_available", lambda: True)
    monkeypatch.setattr(orch.llm_adapter, "summarize_results", lambda f: "")
    report = _Report(["finding a"])

    orch._attach_llm_summary(report)
    assert report.llm_summary is None


# --------------------------------------------------------------------------- #
# _expand: per-question guards (dup / spam / memory)
# --------------------------------------------------------------------------- #


def test_expand_blocks_duplicate_questions(monkeypatch):
    orch = _orch()
    node = _root(orch)
    # Every generated question looks already-seen -> no fresh questions.
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: True)

    before = orch.debug_stats["run_question_duplicates_blocked"]
    orch._expand(node)

    assert orch.debug_stats["run_question_duplicates_blocked"] > before
    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.DUPLICATE_BRANCH


def test_expand_filters_low_value_questions(monkeypatch):
    orch = _orch()
    node = _root(orch)
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: False)
    monkeypatch.setattr(orch.spam_guard, "is_low_value_question", lambda _q, _c: True)

    before = orch.debug_stats["spam_questions_filtered"]
    orch._expand(node)

    assert orch.debug_stats["spam_questions_filtered"] > before
    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.DUPLICATE_BRANCH


def test_expand_degrades_memory_question_repeats(monkeypatch):
    orch = _orch()
    node = _root(orch)
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: False)
    monkeypatch.setattr(orch.spam_guard, "is_low_value_question", lambda _q, _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_question", lambda _t: True)

    before = orch.debug_stats["memory_question_repeats_degraded"]
    orch._expand(node)

    assert orch.debug_stats["memory_question_repeats_degraded"] > before


# --------------------------------------------------------------------------- #
# _expand: budget exhaustion mid-expansion
# --------------------------------------------------------------------------- #


def test_expand_stops_when_budget_exhausts_before_child_decompose(monkeypatch):
    orch = _orch()
    node = _root(orch)
    # Allow questions through, then report budget exhausted at the question loop.
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: False)
    monkeypatch.setattr(orch.spam_guard, "is_low_value_question", lambda _q, _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_question", lambda _t: False)

    # The pre-expansion guard reads budget first and must see it NOT exhausted;
    # the question-loop guard (line 363) then trips on the second read.
    traces = []
    orig_trace = orch.debug.trace
    monkeypatch.setattr(orch.debug, "trace", lambda k, *a, **kw: (traces.append((k, a[0] if a else "")), orig_trace(k, *a, **kw)))
    state = {"reads": 0}

    def exhausted(self):
        state["reads"] += 1
        return state["reads"] >= 2

    monkeypatch.setattr(type(orch.budget), "exhausted", property(exhausted))

    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.BUDGET_EXHAUSTED
    assert any("mid-expansion" in msg for _k, msg in traces)


def test_expand_stops_when_budget_exhausts_during_child_creation(monkeypatch):
    orch = _orch(top_k_questions=1)
    node = _root(orch)
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: False)
    monkeypatch.setattr(orch.spam_guard, "is_low_value_question", lambda _q, _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_question", lambda _t: False)
    # Guarantee a child claim survives into the child-creation loop.
    monkeypatch.setattr(orch.decomposer, "decompose", lambda _q: ["A concrete child claim about validating input."])
    monkeypatch.setattr(orch.claim_normalizer, "is_viable", lambda _c: True)
    monkeypatch.setattr(orch.spam_guard, "filter_claims", lambda claims, parent_claim=None: list(claims))
    monkeypatch.setattr(orch.graph, "has_similar_claim", lambda _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_claim", lambda _c: False)

    # Budget reads False at the question-loop guard (line 363) but flips to True
    # at the inner child-creation guard (line 398).
    # The question-loop guard reads `exhausted` first (line 363) and proceeds;
    # the child-creation guard (line 398) then trips on the third read.
    traces = []
    orig_trace = orch.debug.trace
    monkeypatch.setattr(orch.debug, "trace", lambda k, *a, **kw: (traces.append((k, a[0] if a else "")), orig_trace(k, *a, **kw)))

    state = {"reads": 0}

    def exhausted(self):
        state["reads"] += 1
        return state["reads"] >= 3

    monkeypatch.setattr(type(orch.budget), "exhausted", property(exhausted))

    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.BUDGET_EXHAUSTED
    # Confirm we stopped at the child-creation guard, not the question-loop guard.
    assert any("child creation" in msg for _k, msg in traces)


# --------------------------------------------------------------------------- #
# _expand: memory-claim repeat degradation + on_progress during child expand
# --------------------------------------------------------------------------- #


def test_expand_degrades_memory_claim_repeats_and_reports_progress(monkeypatch):
    orch = _orch()
    node = _root(orch)
    monkeypatch.setattr(orch.graph, "has_similar_question", lambda _t: False)
    monkeypatch.setattr(orch.spam_guard, "is_low_value_question", lambda _q, _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_question", lambda _t: False)
    monkeypatch.setattr(orch.graph, "has_similar_claim", lambda _c: False)
    monkeypatch.setattr(orch.graph, "has_memory_claim", lambda _c: True)

    events = []
    before = orch.debug_stats["memory_claim_repeats_degraded"]

    orch._expand(node, on_progress=lambda *a: events.append(a), current_root=0, total_roots=3)

    assert orch.debug_stats["memory_claim_repeats_degraded"] > before
    # on_progress fired for child expansion with the (phase, root+1, total) shape.
    assert any(e[0] == "expand" and e[2] == 3 for e in events)
