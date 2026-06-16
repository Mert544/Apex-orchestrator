"""Characterization harness proving the refactor of ``analyze_tree_shape`` is
byte-identical to the pre-refactor implementation.

The original ``app/engine/idea_tree_shape.py`` is loaded fresh from ``git show
HEAD:`` into an isolated module, and its ``analyze_tree_shape`` /
``render_tree_shape_markdown`` outputs are compared field-by-field (and as a
rendered markdown string) against the current implementation across a battery of
trees that exercise every branch: empty trees, roots-only, deep chains, wide
bushes, blank/duplicate subjects, missing operators, anchors, source_facts,
varied values, and assorted metric/stats payloads.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from dataclasses import asdict

import pytest

from app.engine import idea_tree_shape as current
from app.models.idea import IdeaNode, IdeaTreeReport

_ORIGINAL_PATH = "app/engine/idea_tree_shape.py"


def _load_original() -> types.ModuleType:
    """Import the HEAD version of the module under a private name."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_ORIGINAL_PATH}"], text=True
    )
    spec = importlib.util.spec_from_loader("_orig_idea_tree_shape", loader=None)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_orig_idea_tree_shape"] = mod
    exec(compile(src, "<orig idea_tree_shape>", "exec"), mod.__dict__)
    return mod


original = _load_original()


def _node(idx: int, **kw) -> IdeaNode:
    base = {"id": f"n{idx}", "title": f"idea {idx}"}
    base.update(kw)
    return IdeaNode(**base)


def _reports() -> list[IdeaTreeReport]:
    reports: list[IdeaTreeReport] = []

    # 1. Empty tree, no stats.
    reports.append(IdeaTreeReport(ideas=[], stats={}))

    # 2. Empty tree but with metric stats (exercises _measured_loc in empty path).
    reports.append(
        IdeaTreeReport(
            ideas=[],
            stats={"metrics": {"a.py": {"loc": 10}, "b.py": {"loc": 30}}},
        )
    )

    # 3. Single root, minimal.
    reports.append(IdeaTreeReport(ideas=[_node(0, subject="s0", operator="root")]))

    # 4. Roots only, several distinct subjects (breadth observation).
    reports.append(
        IdeaTreeReport(
            ideas=[
                _node(i, subject=f"s{i}", operator=f"op{i % 2}", value=i / 10)
                for i in range(5)
            ]
        )
    )

    # 5. Deep chain (depth balance, leaf ratio low, branching).
    chain = []
    for i in range(6):
        chain.append(
            _node(
                i,
                subject="same" if i % 2 else "other",
                parent_id=f"n{i - 1}" if i else None,
                depth=i,
                operator="lensA",
                value=0.5,
                kind="facet" if i > 3 else "permutation",
                source_facts=["f"] if i % 2 else [],
                anchors=[{"module": "m", "symbol": "f", "line": 1, "metric": "cx 9"}]
                if i % 3 == 0
                else [],
            )
        )
    reports.append(IdeaTreeReport(ideas=chain))

    # 6. Wide bush: one root, many depth-1 children (flat frontier, leaf ratio high).
    bush = [_node(0, subject="root_s", depth=0, operator="root")]
    for i in range(1, 11):
        bush.append(
            _node(
                i,
                subject="root_s",
                parent_id="n0",
                depth=1,
                operator="lensB",
                value=0.9,
            )
        )
    reports.append(IdeaTreeReport(ideas=bush))

    # 7. One subject dominates (>50%) with synthesis/pair kinds present.
    dom = [
        _node(0, subject="big", value=0.1, kind="synthesis"),
        _node(1, subject="big", value=0.2, kind="pair"),
        _node(2, subject="big", value=0.3),
        _node(3, subject="small", value=0.4),
    ]
    reports.append(IdeaTreeReport(ideas=dom))

    # 8. Blank subjects, blank operators (labelled==0, operators empty).
    blank = [_node(i, subject="", operator="", value=0.0) for i in range(3)]
    reports.append(IdeaTreeReport(ideas=blank))

    # 9. Moderate concentration on a handful of subjects (no top dominance).
    conc_subjects = ["a", "a", "b", "b", "c", "c", "d", "e"]
    reports.append(
        IdeaTreeReport(
            ideas=[
                _node(i, subject=s, value=i / 20, operator=f"op{i % 4}")
                for i, s in enumerate(conc_subjects)
            ]
        )
    )

    # 10. Heavy LOC concentration in one module (>40% of total).
    reports.append(
        IdeaTreeReport(
            ideas=[_node(0, subject="x"), _node(1, subject="y", parent_id="n0", depth=1)],
            stats={
                "metrics": {
                    "heavy.py": {"loc": 500},
                    "light.py": {"loc": 50},
                    "mid.py": {"loc": 100},
                }
            },
        )
    )

    # 11. Malformed metrics (non-dict, bad loc values) + all-grounded/all-anchored.
    reports.append(
        IdeaTreeReport(
            ideas=[
                _node(
                    i,
                    subject=f"sub{i}",
                    operator="oneLens",
                    value=0.5,
                    source_facts=["fact"],
                    anchors=[{"module": "m", "symbol": "s", "line": i, "metric": "x"}],
                )
                for i in range(4)
            ],
            stats={"metrics": {"a.py": {"loc": "bad"}, "b.py": {"loc": None}, "c.py": None}},
        )
    )

    # 12. metrics not a dict at all.
    reports.append(
        IdeaTreeReport(
            ideas=[_node(0, subject="z", value=0.7)],
            stats={"metrics": "garbage"},
        )
    )

    # 13. All zero loc metrics (best_loc <= 0 branch -> returns total).
    reports.append(
        IdeaTreeReport(
            ideas=[_node(0, subject="z", value=0.7)],
            stats={"metrics": {"a.py": {"loc": 0}, "b.py": {}}},
        )
    )

    # 14. distinct values clustered (limited prioritization signal).
    reports.append(
        IdeaTreeReport(
            ideas=[_node(i, subject=f"s{i}", value=0.5) for i in range(9)]
        )
    )

    # 15. High anchor coverage (>=0.5) and weak grounding (<0.5).
    mixed = []
    for i in range(6):
        mixed.append(
            _node(
                i,
                subject=f"s{i % 3}",
                operator=f"op{i % 3}",
                value=i / 12,
                source_facts=["f"] if i == 0 else [],
                anchors=[{"module": "m", "symbol": "f", "line": i, "metric": "cx"}]
                if i < 4
                else [],
            )
        )
    reports.append(IdeaTreeReport(ideas=mixed))

    return reports


@pytest.mark.parametrize("report", _reports())
def test_analyze_tree_shape_byte_identical(report: IdeaTreeReport) -> None:
    orig_shape = original.analyze_tree_shape(report)
    new_shape = current.analyze_tree_shape(report)

    orig_dict = asdict(orig_shape)
    new_dict = asdict(new_shape)

    # Exact field-by-field equality, including key order.
    assert list(orig_dict.keys()) == list(new_dict.keys())
    assert orig_dict == new_dict
    assert orig_shape.to_dict() == new_shape.to_dict()

    # Observation list identical, order included.
    assert orig_shape.observations == new_shape.observations

    # Rendered markdown byte-identical.
    assert original.render_tree_shape_markdown(orig_shape) == (
        current.render_tree_shape_markdown(new_shape)
    )
    assert current.render_tree_shape_markdown(orig_shape) == (
        current.render_tree_shape_markdown(new_shape)
    )
