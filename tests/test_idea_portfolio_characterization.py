"""Characterization: refactored optimize_portfolio must be byte-identical to the
pre-refactor original across every branch (empty, budget-zero, ties, prereq bundles,
missing-item fallbacks, roadmap=None default-build path).

The "original" is loaded at test time straight from the pre-refactor blob in git
(``git show HEAD:app/engine/idea_portfolio.py``), exec'd into a throwaway module that
reuses the live ``app.engine`` package for its imports. This test then diffs the two
implementations' full outputs — no extra source file is committed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types

from app.engine.idea_portfolio import optimize_portfolio as new_optimize
from app.engine.idea_permutation import IdeaPermutationEngine
from app.engine.idea_roadmap import RoadmapItem, RoadmapPhase, Roadmap
from app.models.idea import IdeaNode, IdeaTreeReport


# Pre-refactor base commit. Pinning the SHA (not HEAD) keeps this a real proof even
# after the refactor lands: it always diffs against the original blob, not itself.
_BASE_SHA = "3c69ef6dddfd7018c9b6f6fdda67f449d1b134ac"


def _load_original():
    """Materialize the base commit's idea_portfolio.py as a module; return its fn."""
    src = subprocess.check_output(
        ["git", "show", f"{_BASE_SHA}:app/engine/idea_portfolio.py"], text=True
    )
    name = "_idea_portfolio_base_snapshot"
    mod = types.ModuleType(name)
    # Register before exec: @dataclass resolves cls.__module__ via sys.modules.
    sys.modules[name] = mod
    exec(compile(src, f"<{_BASE_SHA}:app/engine/idea_portfolio.py>", "exec"), mod.__dict__)
    return mod.optimize_portfolio


orig_optimize = _load_original()


def _report_and_roadmap(specs):
    """specs: list of (id, branch_path, operator, subject, impact, effort)."""
    ideas, items = [], []
    for _id, bp, op, subj, impact, effort in specs:
        ideas.append(IdeaNode(id=_id, branch_path=bp, operator=op, subject=subj,
                              title=f"{op}: {subj}", value=impact))
        items.append(RoadmapItem(branch_path=bp, title=f"{op}: {subj}", subject=subj,
                                 phase="Stabilize", impact=impact, effort=effort,
                                 roi=round(impact / effort, 4), value=impact,
                                 kind="permutation", rationale=""))
    report = IdeaTreeReport(ideas=ideas)
    roadmap = Roadmap(objective="", project_root="/p",
                      phases=[RoadmapPhase(name="Stabilize", theme="t", items=items)])
    return report, roadmap


# Scenarios covering every branch in optimize_portfolio:
#  - empty idea set
#  - budget too small (nothing fits)
#  - exact-fit selection / exclusions
#  - ROI ties broken by (impact, branch_path)
#  - harden depends on test -> prereq bundle pulled in
#  - bundle too big -> dependent excluded, cheaper alternative chosen
#  - generous budget -> everything selected
_SCENARIOS = [
    ("empty", [], 1.0),
    ("zero_budget", [("a", "x.a", "test", "app/a.py", 0.9, 0.5)], 0.0),
    ("tiny_budget", [("a", "x.a", "test", "app/a.py", 0.9, 0.5)], 0.1),
    ("exact_two_fit", [
        ("a", "x.a", "test", "app/a.py", 0.9, 0.5),
        ("b", "x.b", "test", "app/b.py", 0.8, 0.5),
        ("c", "x.c", "test", "app/c.py", 0.3, 0.5),
    ], 1.0),
    ("roi_ties", [
        ("a", "x.a", "test", "app/a.py", 0.6, 0.6),
        ("b", "x.b", "test", "app/b.py", 0.6, 0.6),
        ("c", "x.c", "test", "app/c.py", 0.6, 0.6),
    ], 1.2),
    ("impact_tie_break_path", [
        ("a", "x.z", "test", "app/z.py", 0.5, 0.5),
        ("b", "x.a", "test", "app/a.py", 0.5, 0.5),
    ], 0.5),
    ("prereq_pulled_in", [
        ("t", "x.t", "test", "app/a.py", 0.5, 0.3),
        ("h", "x.h", "harden", "app/a.py", 0.95, 0.3),
    ], 1.0),
    ("bundle_too_big", [
        ("t", "x.t", "test", "app/a.py", 0.4, 0.3),
        ("h", "x.h", "harden", "app/a.py", 0.95, 0.3),
        ("c", "x.c", "test", "app/c.py", 0.5, 0.4),
    ], 0.5),
    ("generous", [
        ("a", "x.a", "test", "app/a.py", 0.9, 0.5),
        ("b", "x.b", "test", "app/b.py", 0.8, 0.5),
        ("t", "x.t", "test", "app/d.py", 0.4, 0.3),
        ("h", "x.h", "harden", "app/d.py", 0.95, 0.3),
    ], 10.0),
    ("negative_budget", [("a", "x.a", "test", "app/a.py", 0.9, 0.5)], -1.0),
]


def _normalize(portfolio):
    """Full structural fingerprint: order + every field, plus derived utilization."""
    d = portfolio.to_dict()
    return (
        d["budget"], d["total_impact"], d["total_effort"],
        d["excluded_count"], d["utilization"],
        tuple(tuple(sorted(item.items())) for item in d["selected"]),
    )


def test_byte_identical_across_branches():
    mismatches = []
    for name, specs, budget in _SCENARIOS:
        report, rm = _report_and_roadmap(specs)
        a = _normalize(orig_optimize(report, budget=budget, roadmap=rm))
        b = _normalize(new_optimize(report, budget=budget, roadmap=rm))
        if a != b:
            mismatches.append((name, a, b))
    assert not mismatches, f"output diverged: {mismatches}"


def test_byte_identical_roadmap_none_default_build():
    """Exercise the roadmap=None branch that builds a RoadmapSynthesizer internally."""
    report, _ = _report_and_roadmap([
        ("a", "x.a", "test", "app/a.py", 0.9, 0.5),
        ("b", "x.b", "test", "app/b.py", 0.8, 0.5),
    ])
    for budget in (0.0, 0.5, 1.0, 5.0):
        a = _normalize(orig_optimize(report, budget=budget))
        b = _normalize(new_optimize(report, budget=budget))
        assert a == b, f"diverged at budget={budget}"


def test_byte_identical_end_to_end(tmp_path):
    """A real permutation report drives many missing-item / closure code paths."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def r(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 5}, tmp_path
    ).run()
    for budget in (0.0, 1.0, 2.0, 3.5, 100.0):
        a = _normalize(orig_optimize(rep, budget=budget))
        b = _normalize(new_optimize(rep, budget=budget))
        assert a == b, f"diverged at budget={budget}"


def test_original_snapshot_loaded():
    """Guard: the HEAD-blob original actually loaded as a distinct callable."""
    assert callable(orig_optimize)
    assert orig_optimize is not new_optimize
    # And the live module still imports cleanly (sanity for the refactor).
    assert importlib.util.find_spec("app.engine.idea_portfolio") is not None
