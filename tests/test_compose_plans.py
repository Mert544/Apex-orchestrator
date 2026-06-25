"""compose_plans — the multi-file plan COMPOSITION primitive.

Covers: a clean UNION of two disjoint single-file plans (new_contents /
originals / edits_by_file all merged); the file-overlap conflict refusal (the key
soundness gate); refusal when either sub-plan is blocked or empty; the
never-deselect-a-needed-node invariant under the scoped-node union; the sorted /
deterministic derived_from union; and render_diff covering BOTH files. Pure,
IO-free unit tests — no project, no apply gate.
"""

from __future__ import annotations

from app.execution.compose_plans import compose_plans
from app.execution.cross_file_rename import RenamePlan


def _single(rel: str, before: str, after: str, *, edits: int = 1) -> RenamePlan:
    """A minimal single-file plan shaped exactly like a real objective's."""
    plan = RenamePlan(old=rel, new="x")
    plan.originals[rel] = before
    plan.new_contents[rel] = after
    plan.edits_by_file[rel] = edits
    return plan


def test_union_merges_disjoint_files():
    a = _single("app/calc.py", "old a\n", "new a\n", edits=2)
    b = _single("app/pkg/__init__.py", "", "from .calc import add\n", edits=1)

    merged = compose_plans(a, b)

    assert merged.ok
    assert not merged.blockers
    assert set(merged.new_contents) == {"app/calc.py", "app/pkg/__init__.py"}
    assert merged.new_contents["app/calc.py"] == "new a\n"
    assert merged.new_contents["app/pkg/__init__.py"] == "from .calc import add\n"
    assert set(merged.originals) == {"app/calc.py", "app/pkg/__init__.py"}
    assert merged.originals["app/calc.py"] == "old a\n"
    assert merged.edits_by_file == {"app/calc.py": 2, "app/pkg/__init__.py": 1}
    assert merged.new == "compose"


def test_refuses_on_file_overlap():
    # Two plans editing the SAME file would each clobber the other's bytes — the
    # union is ill-defined, so the composition refuses and lands nothing.
    a = _single("app/calc.py", "v0\n", "v1\n")
    b = _single("app/calc.py", "v0\n", "v2\n")

    merged = compose_plans(a, b)

    assert not merged.ok
    assert not merged.new_contents  # nothing merged
    assert merged.blockers
    assert any("app/calc.py" in r and "conflict" in r for r in merged.blockers)


def test_refuses_when_either_subplan_blocked():
    good = _single("app/calc.py", "v0\n", "v1\n")
    blocked = RenamePlan(old="app/x.py", new="x")
    blocked.blockers.append("x: ambiguous witnesses")

    # Blocked on the right...
    m1 = compose_plans(good, blocked)
    assert not m1.ok and not m1.new_contents and m1.blockers
    # ...and blocked on the left.
    m2 = compose_plans(blocked, good)
    assert not m2.ok and not m2.new_contents and m2.blockers


def test_refuses_when_either_subplan_empty():
    good = _single("app/calc.py", "v0\n", "v1\n")
    empty = RenamePlan(old="app/pkg/__init__.py", new="wire-exports")  # no-op

    m1 = compose_plans(good, empty)
    assert not m1.ok and not m1.new_contents and m1.blockers
    m2 = compose_plans(empty, good)
    assert not m2.ok and not m2.new_contents and m2.blockers


def test_scoped_node_union_excludes_needed():
    # The implement-stub invariant (never deselect a node a landed stub depends
    # on), composed: a node in EITHER side's scoped_test_nodes must never appear
    # in the merged scoped_excluded_nodes — even if the OTHER side excluded it.
    a = _single("app/calc.py", "v0\n", "v1\n")
    a.scoped_test_nodes = ["tests/test_calc.py::test_add"]
    a.scoped_excluded_nodes = ["tests/test_calc.py::test_unfilled"]
    b = _single("app/pkg/__init__.py", "", "from .calc import add\n")
    # b redundantly excludes a node that a's fill NEEDS — the union must drop it.
    b.scoped_excluded_nodes = ["tests/test_calc.py::test_add",
                               "tests/test_other.py::test_red"]

    merged = compose_plans(a, b)

    assert merged.scoped_test_nodes == ["tests/test_calc.py::test_add"]
    # The needed node is gone; the genuinely-red sibling nodes survive, sorted.
    assert "tests/test_calc.py::test_add" not in merged.scoped_excluded_nodes
    assert merged.scoped_excluded_nodes == [
        "tests/test_calc.py::test_unfilled", "tests/test_other.py::test_red"]


def _derived_pair() -> tuple[RenamePlan, RenamePlan]:
    a = _single("app/calc.py", "v0\n", "v1\n")
    a.derived_from = ["app/proto.py", "app/calc.py"]
    b = _single("app/pkg/__init__.py", "", "from .calc import add\n")
    b.derived_from = ["app/calc.py", "app/base.py"]
    return a, b


def test_derived_from_union_sorted_deterministic():
    merged = compose_plans(*_derived_pair())

    # Sorted union, no duplicates — byte-stable across runs.
    assert merged.derived_from == ["app/base.py", "app/calc.py", "app/proto.py"]
    again = compose_plans(*_derived_pair())
    assert again.derived_from == merged.derived_from


def test_render_diff_covers_both_files():
    a = _single("app/calc.py", "def add(a, b):\n    raise NotImplementedError\n",
                "def add(a, b):\n    return a + b\n")
    b = _single("app/pkg/__init__.py", "", "from .calc import add\n\n__all__ = ['add']\n")

    diff = compose_plans(a, b).render_diff()

    assert "a/app/calc.py" in diff and "b/app/calc.py" in diff
    assert "a/app/pkg/__init__.py" in diff and "b/app/pkg/__init__.py" in diff
    assert "return a + b" in diff
    assert "from .calc import add" in diff
