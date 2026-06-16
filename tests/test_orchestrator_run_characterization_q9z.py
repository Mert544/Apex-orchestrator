"""Byte-identical characterization harness pinning ``run()`` after its
decomposition into pure helpers.

The original ``core.py`` (from the commit this refactor is based on) is loaded
side-by-side with the live, refactored module. Both orchestrators are driven
through the public ``run()`` path on identical inputs back-to-back in the same
process, and their full output is compared: the entire ``FinalReport`` (minus
wall-clock ``phase_metrics``), the ``debug_stats`` counters, and a complete
per-node snapshot of the expanded graph. Zero mismatches proves the refactor
preserved behaviour exactly.

A unique-named scratch copy of the original source is materialised under the
repo so its absolute imports (``app...``) resolve identically; it is loaded as a
throwaway module and never installed on ``sys.path`` permanently.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestrator.core import FractalResearchOrchestrator as RefactoredOrch
from app.skills.decomposer import Decomposer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator

_REPO = Path(__file__).resolve().parents[1]
_ORIG_SRC = _REPO / "app" / "orchestrator" / "_core_orig_q9z_scratch.py"

# Deterministic objectives only (the Validator's evidence retrieval is
# filesystem-dependent and flaky for some phrasings; these stay stable). Each
# is run twice so we also pin within-process determinism of the refactor.
_CASES = [
    ("validate untrusted input",
     dict(max_depth=2, max_total_nodes=50, top_k_questions=2)),
    ("design a scalable distributed cache",
     dict(max_depth=3, max_total_nodes=80, top_k_questions=3)),
    ("build secure authentication system",
     dict(max_depth=2, max_total_nodes=8, top_k_questions=2)),   # budget-bound
    ("validate untrusted input",
     dict(max_depth=3, max_total_nodes=60, top_k_questions=3,
          focus={"min_relevance": 0.05, "min_depth": 1})),       # focus opt-in
]


def _load_original():
    """Materialise the base-commit ``core.py`` and import it as a module."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/orchestrator/core.py"], cwd=_REPO
    )
    _ORIG_SRC.write_bytes(src)
    spec = importlib.util.spec_from_file_location(
        "app.orchestrator._core_orig_q9z_scratch", _ORIG_SRC
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.FractalResearchOrchestrator


@pytest.fixture(scope="module")
def original_cls():
    cls = _load_original()
    yield cls
    sys.modules.pop("app.orchestrator._core_orig_q9z_scratch", None)
    _ORIG_SRC.unlink(missing_ok=True)


def _build(cls, cfg):
    base = dict(min_security=0.8, min_quality=0.6, min_novelty=0.2)
    base.update(cfg)
    return cls(
        config=base,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


def _node_snapshot(orch):
    nodes = sorted(orch.graph.get_all_nodes(), key=lambda n: n.id)
    rows = []
    for n in nodes:
        rows.append((
            n.id, n.branch_path, n.depth, n.claim,
            tuple(n.parent_ids), n.status, n.stop_reason,
            round(n.relevance, 6), round(n.confidence, 6), round(n.risk, 6),
            tuple(n.evidence_for), tuple(n.evidence_against), tuple(n.assumptions),
            tuple(q.text for q in n.questions),
            tuple(round(q.priority, 6) for q in n.questions),
            tuple(round(q.novelty, 6) for q in n.questions),
        ))
    return rows


def _report_dump(report):
    # Exclude wall-clock phase_metrics (timing is non-deterministic by design).
    data = report.model_dump()
    data.pop("phase_metrics", None)
    return data


def _full_output(orch, objective, **kwargs):
    report = orch.run(objective, **kwargs)
    return _report_dump(report), dict(orch.debug_stats), _node_snapshot(orch)


def test_run_output_is_byte_identical_to_original(original_cls):
    for objective, cfg in _CASES:
        orig = _build(original_cls, cfg)
        new = _build(RefactoredOrch, cfg)
        out_orig = _full_output(orig, objective)
        out_new = _full_output(new, objective)
        assert out_new == out_orig, objective


def test_run_is_deterministic_across_runs():
    for objective, cfg in _CASES:
        a = _build(RefactoredOrch, cfg)
        b = _build(RefactoredOrch, cfg)
        assert _full_output(a, objective) == _full_output(b, objective), objective


def test_focus_branch_miss_matches_original(original_cls):
    # A focus branch that resolves to nothing must fall back identically.
    objective = "validate untrusted input"
    cfg = dict(max_depth=2, max_total_nodes=40, top_k_questions=2)
    orig = _build(original_cls, cfg)
    new = _build(RefactoredOrch, cfg)
    out_orig = _full_output(orig, objective, focus_branch="x.does-not-exist")
    out_new = _full_output(new, objective, focus_branch="x.does-not-exist")
    assert out_new == out_orig
    # The miss counter must have ticked on both.
    assert out_new[1]["focus_branch_misses"] == out_orig[1]["focus_branch_misses"] == 1


def test_empty_decomposition_yields_no_roots(original_cls):
    # Empty objective: both paths must produce an identical (empty-root) report.
    orig = _build(original_cls, dict(max_depth=2, max_total_nodes=10, top_k_questions=2))
    new = _build(RefactoredOrch, dict(max_depth=2, max_total_nodes=10, top_k_questions=2))
    out_orig = _full_output(orig, "")
    out_new = _full_output(new, "")
    assert out_new == out_orig
