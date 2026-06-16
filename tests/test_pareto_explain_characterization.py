"""Byte-identical characterization harness for the refactor of
``idea_pareto.pareto_frontier`` and ``idea_explain.explain_idea``.

We load the *original* HEAD versions of both modules from on-disk snapshots
(captured into temp files) under separate module names, then drive both the
original and the refactored implementations over many inputs that exercise every
branch, asserting the full outputs are identical.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from dataclasses import dataclass

import pytest

from app.engine.idea_pareto import pareto_frontier as new_frontier
from app.engine.idea_explain import explain_idea as new_explain
from app.engine.idea_permutation import IdeaPermutationEngine

# --- Load the original snapshots captured from HEAD --------------------------

_ORIG_PARETO_SRC = "/tmp/orig_pareto.py"
_ORIG_EXPLAIN_SRC = "/tmp/orig_explain.py"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses needs the module registered during exec
    spec.loader.exec_module(mod)
    return mod


_orig_pareto = _load("_orig_idea_pareto", _ORIG_PARETO_SRC)
old_frontier = _orig_pareto.pareto_frontier
_orig_explain = _load("_orig_idea_explain", _ORIG_EXPLAIN_SRC)
old_explain = _orig_explain.explain_idea


# --- pareto_frontier characterization ----------------------------------------


@dataclass
class _Item:
    impact: float
    effort: float
    value: float
    roi: float
    title: str
    branch_path: str
    phase: str = ""


def _items_from_tuples(tuples):
    out = []
    for n, (i, e, v, r) in enumerate(tuples):
        out.append(_Item(i, e, v, r, f"t{n}", f"x.s{n}", phase=("P1" if n % 2 else "")))
    return out


def _vectors():
    """Many input shapes covering: empty, singleton, duplicates, dominance,
    extremes ties, all-equal, balanced trade-offs."""
    cases = []
    cases.append([])  # empty
    cases.append([(0.5, 0.3, 0.6, 1.6)])  # singleton
    # duplicate objective vectors, differing roi/path -> dedup branch
    cases.append([(0.5, 0.3, 0.6, 1.0), (0.5, 0.3, 0.6, 2.0), (0.5, 0.3, 0.6, 2.0)])
    # strict dominance chain
    cases.append([(0.9, 0.1, 0.9, 9.0), (0.5, 0.5, 0.5, 1.0), (0.2, 0.8, 0.2, 0.25)])
    # all equal -> all balanced, ties on every extreme
    cases.append([(0.4, 0.4, 0.4, 1.0), (0.4, 0.4, 0.4, 1.0)])
    # distinct extremes -> each earns a different reason
    cases.append([(0.9, 0.5, 0.5, 1.0), (0.5, 0.1, 0.5, 5.0), (0.5, 0.5, 0.9, 1.8),
                  (0.5, 0.5, 0.5, 9.0)])
    # rounding edge near 4 decimals
    cases.append([(0.50001, 0.3, 0.6, 1.6), (0.50002, 0.3, 0.6, 1.6)])
    # mid balanced point present
    cases.append([(0.9, 0.9, 0.1, 0.1), (0.1, 0.1, 0.9, 9.0), (0.5, 0.5, 0.5, 1.0)])
    return [_items_from_tuples(c) for c in cases]


def _systematic_grid():
    vals = (0.1, 0.5, 0.9)
    combos = list(itertools.product(vals, vals, vals))
    out = []
    for n, (i, e, v) in enumerate(combos):
        out.append(_Item(i, e, v, round(i / max(e, 1e-9), 4), f"g{n}", f"x.g{n:02d}"))
    return out


@pytest.mark.parametrize("items", _vectors() + [_systematic_grid()])
def test_pareto_frontier_byte_identical(items):
    a = [p.to_dict() for p in old_frontier(items)]
    b = [p.to_dict() for p in new_frontier(items)]
    assert a == b


def test_pareto_frontier_path_tiebreak_in_dedup():
    # same vector + same roi -> branch_path lexical tiebreak in dedup
    items = [
        _Item(0.5, 0.3, 0.6, 2.0, "a", "x.b"),
        _Item(0.5, 0.3, 0.6, 2.0, "b", "x.a"),
    ]
    assert [p.to_dict() for p in old_frontier(items)] == [
        p.to_dict() for p in new_frontier(items)
    ]


# --- explain_idea characterization -------------------------------------------


def _build_report(tmp_path, objective=None):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "import os\ndef run(e):\n    return eval(e)\n"
    )
    (tmp_path / "app" / "user.py").write_text(
        "import app.core\ndef u():\n    return app.core.run('1')\n"
    )
    (tmp_path / "app" / "util.py").write_text("def f(x):\n    return x + 1\n")
    eng = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4}, tmp_path
    )
    return eng.run(objective=objective) if objective else eng.run()


@pytest.mark.parametrize("objective", [None, "improve security", "   "])
def test_explain_idea_byte_identical_all_nodes(tmp_path, objective):
    rep = _build_report(tmp_path, objective)
    # every node (roots, permutations, facets, varying depth/operator) + a miss
    paths = [i.branch_path for i in rep.ideas] + ["x.does.not.exist"]
    for bp in paths:
        a = old_explain(rep, bp)
        b = new_explain(rep, bp)
        if a is None or b is None:
            assert a is None and b is None
            continue
        assert a.to_dict() == b.to_dict()


def test_explain_idea_empty_report(tmp_path):
    # An idea-free report: explain on any path -> None for both.
    rep = _build_report(tmp_path)
    rep.ideas = []
    assert old_explain(rep, "x.s0") is None
    assert new_explain(rep, "x.s0") is None
