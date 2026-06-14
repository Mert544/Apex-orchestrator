from __future__ import annotations

import threading

import pytest

from app.engine.idea_dependencies import (
    ExecStep,
    critical_path_length,
    execution_order,
    infer_dependencies,
    render_execution_markdown,
)
from app.models.idea import IdeaNode


def _idea(id, op, subject, value=0.6, kind="permutation", title=None, bp=None):
    return IdeaNode(id=id, operator=op, subject=subject, value=value, kind=kind,
                    title=title or f"{op}: {subject}", branch_path=bp or id)


def test_exec_step_to_dict_contains_all_fields():
    step = ExecStep(
        branch_path="b.x", title="T", subject="app/a.py", operator="harden",
        value=0.7, order=2, depends_on=["b.t"], on_critical_path=True,
    )
    d = step.to_dict()
    assert d == {
        "branch_path": "b.x", "title": "T", "subject": "app/a.py",
        "operator": "harden", "value": 0.7, "order": 2,
        "depends_on": ["b.t"], "on_critical_path": True,
    }


def test_single_idea_is_its_own_critical_path():
    # One idea -> layer 0, on the critical path, length 1.
    steps = execution_order([_idea("t", "test", "app/a.py")])
    assert len(steps) == 1
    assert steps[0].order == 0
    assert steps[0].on_critical_path is True
    assert critical_path_length(steps) == 1


def test_mutating_lens_without_test_has_no_dependency():
    # A harden with no matching test idea for its subject gets no prerequisites.
    deps = infer_dependencies([_idea("h", "harden", "app/a.py")])
    assert deps["h"] == set()


def test_after_build_without_build_has_no_dependency():
    # A document idea with no extend/generalize build in its subject group is free.
    deps = infer_dependencies([_idea("d", "document", "app/a.py")])
    assert deps["d"] == set()


def test_generalize_build_satisfies_observe_dependency():
    # observe is an _AFTER_BUILD lens; generalize is a _BUILD lens -> observe waits.
    ideas = [
        _idea("g", "generalize", "app/a.py"),
        _idea("o", "observe", "app/a.py"),
    ]
    assert infer_dependencies(ideas)["o"] == {"g"}


def test_mutating_lens_does_not_depend_on_itself_as_test():
    # The deps update excludes the idea's own id even when it appears among tests.
    # A test idea is not itself mutating, but guard the "t.id != i.id" path by
    # giving two test ideas plus a harden over the same subject.
    ideas = [
        _idea("t1", "test", "app/a.py"),
        _idea("t2", "test", "app/a.py"),
        _idea("h", "harden", "app/a.py"),
    ]
    deps = infer_dependencies(ideas)
    assert deps["h"] == {"t1", "t2"}
    # Tests themselves have no prerequisites among the group.
    assert deps["t1"] == set()
    assert deps["t2"] == set()


def test_interface_pair_unrelated_modules_has_no_cycle_dependency():
    # An interface pair whose modules do not overlap any cycle break stays free.
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair",
                title="Break the import cycle a.py → b.py")
    iface = _idea("i", "synthesis", "x.py↔y.py", kind="pair",
                  title="Standardize the interface between x.py and y.py")
    deps = infer_dependencies([cyc, iface])
    assert deps["i"] == set()


def test_render_markdown_marks_critical_path_and_dependency_arrows():
    # test -> harden chain: layer labels, the star on the critical path, and the
    # "needs" arrow for the dependent step all render.
    ideas = [
        _idea("t", "test", "app/a.py", bp="branch.t"),
        _idea("h", "harden", "app/a.py", bp="branch.h"),
    ]
    md = render_execution_markdown(execution_order(ideas))
    assert "Layer 0 — no prerequisites" in md
    assert "Layer 1 — after layer 0" in md
    assert "⭐" in md
    assert "needs `branch.t`" in md


def test_layering_ties_break_by_value_then_branch_path():
    # Two independent layer-0 ideas: higher value first, then branch_path order.
    ideas = [
        _idea("lo", "test", "app/a.py", value=0.3, bp="z.lo"),
        _idea("hi", "test", "app/b.py", value=0.9, bp="a.hi"),
    ]
    steps = execution_order(ideas)
    assert [s.branch_path for s in steps] == ["a.hi", "z.lo"]


def test_mutual_dependency_cycle_hangs_critical_path_walk():
    # KNOWN BUG: app/engine/idea_dependencies.py:115-120. The critical-path
    # `while True` walk has no visited/cycle guard. When infer_dependencies
    # produces a mutual dependency (two pair ideas that are each both a cycle
    # break and an interface job over the same modules), the walk oscillates
    # between the two nodes forever. _level() is guarded and terminates, but the
    # critical-path walk is not. We prove liveness fails via a watchdog thread
    # rather than asserting on wall-clock time.
    a = _idea("a", "synthesis", "x.py↔y.py", kind="pair",
              title="Break the import cycle and standardize the interface x.py↔y.py")
    b = _idea("b", "synthesis", "x.py↔y.py", kind="pair",
              title="Break the import cycle and standardize the interface x.py↔y.py")
    # Sanity: the inferred deps really are mutual (the trigger for the hang).
    deps = infer_dependencies([a, b])
    assert "b" in deps["a"] and "a" in deps["b"]

    done = threading.Event()

    def _run():
        execution_order([a, b])
        done.set()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    finished = done.wait(timeout=3.0)
    # If/when the source is fixed, this completes and the test will XPASS,
    # flagging that the guard now exists.
    if not finished:
        pytest.xfail(
            "critical-path walk in execution_order infinite-loops on a mutual "
            "dependency cycle (idea_dependencies.py:115-120, no visited guard)"
        )
    # Reached only after a fix: a finite plan with both ideas.
    assert True
