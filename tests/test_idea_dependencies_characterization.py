"""Characterization tests pinning ``infer_dependencies`` behavior branch-by-branch.

These exercise every rule path (mutating→test, after-build→build, facet folding,
self-exclusion, cycle→interface overlap, no-overlap, missing prereqs) and assert
both the contents AND the dict-key insertion order of the returned mapping, so any
future refactor that changes determinism or ordering is caught.
"""
from __future__ import annotations

from app.engine.idea_dependencies import infer_dependencies
from app.models.idea import IdeaNode


def _idea(id, op, subject, kind="permutation", title=None, bp=None, value=0.6):
    return IdeaNode(id=id, operator=op, subject=subject, kind=kind,
                    title=title or f"{op}: {subject}", branch_path=bp or id, value=value)


def _serialize(deps):
    """Key order preserved; each prerequisite set sorted for stable comparison."""
    return [(k, sorted(v)) for k, v in deps.items()]


def test_empty_input():
    assert infer_dependencies([]) == {}


def test_single_idea_has_no_deps():
    assert infer_dependencies([_idea("a", "test", "app/a.py")]) == {"a": set()}


def test_every_mutating_lens_waits_on_test():
    for op in ("harden", "simplify", "extend", "generalize", "integrate"):
        ideas = [_idea("t", "test", "m.py"), _idea("x", op, "m.py")]
        assert infer_dependencies(ideas)["x"] == {"t"}, op


def test_mutating_without_test_has_no_dep():
    ideas = [_idea("h", "harden", "a.py"), _idea("s", "simplify", "a.py")]
    deps = infer_dependencies(ideas)
    assert deps["h"] == set() and deps["s"] == set()


def test_after_build_lenses_wait_on_builds():
    for op in ("document", "observe"):
        ideas = [_idea("e", "extend", "m.py"), _idea("g", "generalize", "m.py"),
                 _idea("x", op, "m.py")]
        assert infer_dependencies(ideas)["x"] == {"e", "g"}, op


def test_after_build_without_builds_has_no_dep():
    ideas = [_idea("d", "document", "a.py"), _idea("o", "observe", "a.py")]
    deps = infer_dependencies(ideas)
    assert deps["d"] == set() and deps["o"] == set()


def test_facet_subject_folds_into_base():
    ideas = [_idea("t", "test", "app/a.py"),
             _idea("f", "harden", "app/a.py :: input validation")]
    assert infer_dependencies(ideas)["f"] == {"t"}


def test_different_subject_no_cross_dep():
    ideas = [_idea("t", "test", "app/a.py"), _idea("o", "harden", "app/other.py")]
    assert infer_dependencies(ideas)["o"] == set()


def test_self_reference_excluded():
    # Two tests + a harden: the harden waits on both tests, never on itself.
    ideas = [_idea("t1", "test", "a.py"), _idea("t2", "test", "a.py"),
             _idea("h", "harden", "a.py")]
    deps = infer_dependencies(ideas)
    assert deps["h"] == {"t1", "t2"}
    assert deps["t1"] == set() and deps["t2"] == set()


def test_cycle_before_interface_overlap():
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair",
                title="Break the import cycle a.py → b.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    assert infer_dependencies([cyc, iface])["i"] == {"c"}


def test_interface_without_overlapping_cycle():
    cyc = _idea("c", "synthesis", "x.py↔y.py", kind="pair",
                title="Break the import cycle x.py → y.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    assert infer_dependencies([cyc, iface])["i"] == set()


def test_interface_with_no_cycles_at_all():
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    assert infer_dependencies([iface])["i"] == set()


def test_interface_kind_must_be_pair():
    # 'interface' in title but kind != pair -> no cycle dependency wiring.
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair",
                title="Break the import cycle a.py → b.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="permutation",
                  title="Standardize the interface between a.py and b.py")
    assert infer_dependencies([cyc, iface])["i"] == set()


def test_multiple_cycles_union_on_overlap():
    cyc1 = _idea("c1", "synthesis", "a.py↔b.py", kind="pair",
                 title="Break the import cycle a.py → b.py")
    cyc2 = _idea("c2", "synthesis", "a.py↔x.py", kind="pair",
                 title="Break the import cycle a.py → x.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    # iface overlaps both cycles via module 'a.py'.
    assert infer_dependencies([cyc1, cyc2, iface])["i"] == {"c1", "c2"}


def test_key_order_follows_input_order():
    ideas = [_idea("z", "test", "a.py"), _idea("m", "harden", "a.py"),
             _idea("a", "extend", "a.py")]
    assert list(infer_dependencies(ideas).keys()) == ["z", "m", "a"]


def test_combined_rules_serialized_snapshot():
    cyc = _idea("c", "synthesis", "a.py↔b.py", kind="pair",
                title="Break the import cycle a.py → b.py")
    iface = _idea("i", "synthesis", "a.py↔b.py", kind="pair",
                  title="Standardize the interface between a.py and b.py")
    ideas = [
        _idea("t", "test", "app/svc.py"),
        _idea("h", "harden", "app/svc.py"),
        _idea("e", "extend", "app/svc.py"),
        _idea("d", "document", "app/svc.py"),
        _idea("g", "generalize", "app/svc.py :: facet"),
        _idea("ob", "observe", "app/svc.py"),
        cyc, iface,
    ]
    assert _serialize(infer_dependencies(ideas)) == [
        ("t", []),
        ("h", ["t"]),
        ("e", ["t"]),
        ("d", ["e", "g"]),
        ("g", ["t"]),
        ("ob", ["e", "g"]),
        ("c", []),
        ("i", ["c"]),
    ]
