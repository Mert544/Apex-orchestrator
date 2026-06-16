"""Characterization tests pinning ``execution_order`` after its helper decomposition.

These exercise every branch of the topological layering, the critical-path walk
(deepest-node start, deepest-prereq steps, tie-breaks), self-exclusion of missing
prereqs, and the final layer/value/branch-path sort — asserting the full ordered
output (order + every ExecStep field), so any future refactor that perturbs
determinism is caught.
"""
from __future__ import annotations

from dataclasses import asdict

from app.engine.idea_dependencies import (
    critical_path_length,
    execution_order,
    render_execution_markdown,
)
from app.models.idea import IdeaNode


def _idea(id, op, subject, kind="permutation", title=None, bp=None, value=0.6):
    return IdeaNode(id=id, operator=op, subject=subject, kind=kind,
                    title=title or f"{op}: {subject}", branch_path=bp or id, value=value)


def _rows(steps):
    return [asdict(s) for s in steps]


def test_empty_input_returns_empty():
    assert execution_order([]) == []


def test_single_idea_is_layer_zero_and_critical():
    steps = execution_order([_idea("a", "test", "m.py", value=0.7)])
    assert len(steps) == 1
    s = steps[0]
    assert s.order == 0
    assert s.depends_on == []
    assert s.on_critical_path is True


def test_mutating_after_test_two_layers():
    steps = execution_order([
        _idea("t", "test", "m.py", value=0.3, bp="x.t"),
        _idea("h", "harden", "m.py", value=0.9, bp="x.h"),
    ])
    by_bp = {s.branch_path: s for s in steps}
    assert by_bp["x.t"].order == 0 and by_bp["x.h"].order == 1
    assert by_bp["x.h"].depends_on == ["x.t"]
    # The deeper node and its prereq are both on the critical path.
    assert by_bp["x.t"].on_critical_path and by_bp["x.h"].on_critical_path


def test_sort_is_layer_then_value_then_branch_path():
    steps = execution_order([
        _idea("a", "test", "m.py", value=0.6, bp="x.a"),
        _idea("z", "test", "m.py", value=0.6, bp="x.z"),
        _idea("b", "test", "m.py", value=0.9, bp="x.b"),
    ])
    # All layer 0: higher value first, then branch_path ascending on ties.
    assert [s.branch_path for s in steps] == ["x.b", "x.a", "x.z"]


def test_after_build_depends_on_both_builds_sorted():
    steps = execution_order([
        _idea("e", "extend", "m.py", bp="bp.e"),
        _idea("g", "generalize", "m.py", bp="bp.g"),
        _idea("d", "document", "m.py", bp="bp.d"),
    ])
    d = next(s for s in steps if s.branch_path == "bp.d")
    assert d.depends_on == ["bp.e", "bp.g"]
    assert d.order == 1


def test_cycle_before_interface_layering_and_critical_path():
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair", bp="x.c",
                title="Break the import cycle a.py to b.py", value=0.4)
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair", bp="x.i",
                  title="Standardize the interface between a.py and b.py", value=0.8)
    steps = execution_order([cyc, iface])
    by_bp = {s.branch_path: s for s in steps}
    assert by_bp["x.c"].order == 0 and by_bp["x.i"].order == 1
    assert by_bp["x.i"].depends_on == ["x.c"]
    assert critical_path_length(steps) == 2


def test_independent_groups_stay_layer_zero():
    steps = execution_order([
        _idea("h", "harden", "a.py", bp="bp.h"),   # no test in group
        _idea("o", "harden", "b.py", bp="bp.o"),
    ])
    assert all(s.order == 0 for s in steps)
    assert all(s.depends_on == [] for s in steps)


def test_deep_chain_critical_path_length():
    steps = execution_order([
        _idea("t", "test", "app/svc.py", value=0.3),
        _idea("e", "extend", "app/svc.py", value=0.8),
        _idea("d", "document", "app/svc.py", value=0.2),
    ])
    # t(0) -> e(1) -> d(2): three sequential steps on the critical path.
    assert critical_path_length(steps) == 3
    rows = _rows(steps)
    orders = {r["branch_path"]: r["order"] for r in rows}
    assert orders["t"] == 0 and orders["e"] == 1 and orders["d"] == 2


def test_render_markdown_runs_over_layers():
    steps = execution_order([
        _idea("t", "test", "m.py", value=0.3),
        _idea("h", "harden", "m.py", value=0.9),
    ])
    md = render_execution_markdown(steps)
    assert "Execution plan" in md
    assert "Layer 0" in md and "Layer 1" in md
    assert "critical path 2 step(s) deep" in md
