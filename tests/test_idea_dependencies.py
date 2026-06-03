from __future__ import annotations

from app.engine.idea_dependencies import (
    ExecStep,
    critical_path_length,
    execution_order,
    infer_dependencies,
    render_execution_markdown,
)
from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode


def _idea(id, op, subject, value=0.6, kind="permutation", title=None, bp=None):
    return IdeaNode(id=id, operator=op, subject=subject, value=value, kind=kind,
                    title=title or f"{op}: {subject}", branch_path=bp or id)


def test_mutating_lens_depends_on_test_of_same_subject():
    ideas = [
        _idea("t", "test", "app/a.py"),
        _idea("h", "harden", "app/a.py"),
        _idea("o", "harden", "app/other.py"),  # different subject -> no dep
    ]
    deps = infer_dependencies(ideas)
    assert deps["h"] == {"t"}
    assert deps["o"] == set()


def test_document_depends_on_build():
    ideas = [
        _idea("e", "extend", "app/a.py"),
        _idea("d", "document", "app/a.py"),
    ]
    assert infer_dependencies(ideas)["d"] == {"e"}


def test_facet_subject_maps_to_base():
    ideas = [
        _idea("t", "test", "app/a.py"),
        _idea("f", "harden", "app/a.py :: input validation"),  # facet of a.py
    ]
    assert infer_dependencies(ideas)["f"] == {"t"}


def test_execution_order_puts_prereqs_first():
    ideas = [
        _idea("h", "harden", "app/a.py"),
        _idea("t", "test", "app/a.py"),
    ]
    steps = execution_order(ideas)
    order = {s.branch_path: s.order for s in steps}
    assert order["t"] == 0 and order["h"] == 1
    # Step list is sorted so the test comes before the harden.
    paths = [s.branch_path for s in steps]
    assert paths.index("t") < paths.index("h")


def test_critical_path_and_layers():
    # test -> extend -> document : a 3-deep chain.
    ideas = [
        _idea("t", "test", "app/a.py"),
        _idea("e", "extend", "app/a.py"),
        _idea("d", "document", "app/a.py"),
    ]
    steps = execution_order(ideas)
    by_path = {s.branch_path: s for s in steps}
    assert by_path["t"].order == 0
    assert by_path["e"].order == 1
    assert by_path["d"].order == 2  # document depends on extend (layer 1) -> layer 2
    assert critical_path_length(steps) == 3
    assert all(by_path[p].on_critical_path for p in ("t", "e", "d"))


def test_cycle_before_interface():
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair", title="Break the import cycle a.py → b.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    deps = infer_dependencies([cyc, iface])
    assert deps["i"] == {"c"}


def test_empty_and_render():
    assert execution_order([]) == []
    assert "No ideas to sequence" in render_execution_markdown([])
    steps = execution_order([_idea("t", "test", "app/a.py"), _idea("h", "harden", "app/a.py")])
    md = render_execution_markdown(steps)
    assert "Execution plan" in md and "critical path" in md and "Layer 0" in md


def test_end_to_end_from_engine(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def r(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 5}, tmp_path).run()
    steps = execution_order(rep.ideas)
    assert steps and all(isinstance(s, ExecStep) for s in steps)
    # Every dependency points to an earlier-or-equal layer (valid topological order).
    order = {s.branch_path: s.order for s in steps}
    for s in steps:
        for d in s.depends_on:
            assert order[d] < s.order


def test_execution_order_is_deterministic(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def r(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 4}, tmp_path).run()
    a = [s.branch_path for s in execution_order(rep.ideas)]
    b = [s.branch_path for s in execution_order(rep.ideas)]
    assert a == b
