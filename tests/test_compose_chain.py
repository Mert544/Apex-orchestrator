"""compose_chain — the N-plan atomic FOLD of the pairwise compose_plans, plus the
per-module chain builder it powers.

compose_chain left-folds compose_plans over a whole list so a whole-file-DISJOINT
set of single-file plans merges into ONE multi-file RenamePlan (gated once,
unit-rolled-back by the existing engine). Covers:
  * N (>=3) disjoint single-file plans -> ONE plan whose new_contents is the whole
    union (originals / edits_by_file / derived_from / scoped nodes merged too);
  * the SOUNDNESS gate: ANY two plans sharing a file -> REFUSE (no clobber) — both
    an adjacent pair AND a non-adjacent pair (proving the fold re-checks against
    the ACCUMULATED union, not just the previous plan);
  * an empty OR blocked sub-plan anywhere -> REFUSE;
  * a list of fewer than two plans -> REFUSE (nothing to merge);
  * determinism (same list -> byte-identical plan) and that a 2-plan chain is
    exactly the pairwise compose_plans (so plan_implement_and_wire is unchanged);
  * the per-module builder (plan_module_chain / plan_implement_and_wire) collects a
    module's applicable single-file plans and composes them — end-to-end through
    the real objective planners and the EXISTING apply_rename gate.

Pure/IO-free unit tests for the fold; tmp-project integration tests for the
builder (which drives the one gated writer, never a reimplementation).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.compose_plans import compose_chain, compose_plans
from app.execution.cross_file_rename import RenamePlan, apply_rename
from app.execution.multifile_landing import (
    _module_objective_plan,
    plan_implement_and_wire,
    plan_module_chain,
)


def _single(rel: str, before: str, after: str, *, edits: int = 1) -> RenamePlan:
    """A minimal single-file plan shaped exactly like a real objective's."""
    plan = RenamePlan(old=rel, new="x")
    plan.originals[rel] = before
    plan.new_contents[rel] = after
    plan.edits_by_file[rel] = edits
    return plan


# --- the headline: N disjoint plans -> ONE multi-file plan -------------------

def test_folds_three_disjoint_plans_into_one():
    # implement a stub in A, wire an export in B, infer hints in C -> ONE plan.
    a = _single("app/a.py", "old a\n", "new a\n", edits=2)
    b = _single("app/pkg/__init__.py", "", "from .a import add\n", edits=1)
    c = _single("app/c.py", "def f(x):\n    ...\n", "def f(x: int) -> int:\n    ...\n")

    merged = compose_chain([a, b, c])

    assert merged.ok and not merged.blockers
    # The whole union of all three files is present.
    assert set(merged.new_contents) == {"app/a.py", "app/pkg/__init__.py", "app/c.py"}
    assert merged.new_contents["app/a.py"] == "new a\n"
    assert merged.new_contents["app/pkg/__init__.py"] == "from .a import add\n"
    assert "def f(x: int)" in merged.new_contents["app/c.py"]
    # originals + edits_by_file are the union too — apply_rename can roll all back.
    assert set(merged.originals) == {"app/a.py", "app/pkg/__init__.py", "app/c.py"}
    assert merged.edits_by_file == {
        "app/a.py": 2, "app/pkg/__init__.py": 1, "app/c.py": 1}


def test_fold_equals_left_associated_pairwise():
    # compose_chain IS a left fold of compose_plans: [a,b,c] == (a+b)+c.
    a = _single("app/a.py", "a0\n", "a1\n")
    b = _single("app/b.py", "b0\n", "b1\n")
    c = _single("app/c.py", "c0\n", "c1\n")

    folded = compose_chain([a, b, c])
    pairwise = compose_plans(compose_plans(_single("app/a.py", "a0\n", "a1\n"),
                                           _single("app/b.py", "b0\n", "b1\n")),
                             _single("app/c.py", "c0\n", "c1\n"))

    assert folded.new_contents == pairwise.new_contents
    assert folded.originals == pairwise.originals
    assert folded.edits_by_file == pairwise.edits_by_file


def test_two_plan_chain_is_the_pairwise_compose():
    # A 2-plan chain must be byte-identical to the pairwise compose_plans — this is
    # what keeps plan_implement_and_wire's contract unchanged.
    a = _single("app/a.py", "a0\n", "a1\n", edits=3)
    b = _single("app/b.py", "b0\n", "b1\n")

    chained = compose_chain([a, b])
    direct = compose_plans(_single("app/a.py", "a0\n", "a1\n", edits=3),
                           _single("app/b.py", "b0\n", "b1\n"))

    assert chained.new_contents == direct.new_contents
    assert chained.originals == direct.originals
    assert chained.edits_by_file == direct.edits_by_file
    assert chained.new == direct.new


def test_scoped_and_derived_fields_merge_across_the_chain():
    a = _single("app/a.py", "a0\n", "a1\n")
    a.scoped_test_nodes = ["tests/t.py::test_a"]
    a.derived_from = ["app/proto.py"]
    b = _single("app/b.py", "b0\n", "b1\n")
    b.scoped_excluded_nodes = ["tests/t.py::test_a", "tests/t.py::test_red"]
    b.derived_from = ["app/base.py", "app/proto.py"]
    c = _single("app/c.py", "c0\n", "c1\n")
    c.scoped_test_nodes = ["tests/t.py::test_c"]

    merged = compose_chain([a, b, c])

    # Every side's needed nodes survive; the never-deselect-a-needed-node invariant
    # (a node in ANY included set is dropped from excluded) carries across the fold.
    assert merged.scoped_test_nodes == ["tests/t.py::test_a", "tests/t.py::test_c"]
    assert "tests/t.py::test_a" not in merged.scoped_excluded_nodes
    assert merged.scoped_excluded_nodes == ["tests/t.py::test_red"]
    # derived_from is the sorted, de-duplicated union across all plans.
    assert merged.derived_from == ["app/base.py", "app/proto.py"]


# --- SOUNDNESS: any two plans sharing a file -> refuse (no clobber) -----------

def test_refuses_on_adjacent_file_overlap():
    a = _single("app/a.py", "a0\n", "a1\n")
    b = _single("app/a.py", "a0\n", "a2\n")  # SAME file as a
    c = _single("app/c.py", "c0\n", "c1\n")

    merged = compose_chain([a, b, c])

    assert not merged.ok
    assert not merged.new_contents  # nothing merged — never a silent clobber
    assert any("app/a.py" in r and "conflict" in r for r in merged.blockers)


def test_refuses_on_non_adjacent_overlap_via_accumulated_union():
    # The critical N-way property: the fold re-checks disjointness against the
    # ACCUMULATED union, not just the previous plan. A and C share a file with B in
    # between; because the accumulator carries A's file, C's overlap is caught.
    a = _single("app/a.py", "a0\n", "a1\n")
    b = _single("app/b.py", "b0\n", "b1\n")
    c = _single("app/a.py", "a0\n", "a2\n")  # SAME file as a (non-adjacent)

    merged = compose_chain([a, b, c])

    assert not merged.ok
    assert not merged.new_contents
    assert any("app/a.py" in r and "conflict" in r for r in merged.blockers)


def test_refuses_when_any_subplan_is_empty():
    a = _single("app/a.py", "a0\n", "a1\n")
    empty = RenamePlan(old="app/pkg/__init__.py", new="wire-exports")  # no-op
    c = _single("app/c.py", "c0\n", "c1\n")

    merged = compose_chain([a, empty, c])

    assert not merged.ok and not merged.new_contents and merged.blockers
    # A leading empty plan is caught too (the first fold step refuses).
    leading = compose_chain([empty, a, c])
    assert not leading.ok and not leading.new_contents and leading.blockers


def test_refuses_when_any_subplan_is_blocked():
    a = _single("app/a.py", "a0\n", "a1\n")
    blocked = RenamePlan(old="app/x.py", new="x")
    blocked.blockers.append("x: ambiguous witnesses")
    c = _single("app/c.py", "c0\n", "c1\n")

    merged = compose_chain([a, blocked, c])

    assert not merged.ok and not merged.new_contents
    assert any("blocked" in r or "refused" in r for r in merged.blockers)


def test_refuses_fewer_than_two_plans():
    # A chain needs at least two plans to compose — a lone/empty list is a refusal.
    only = compose_chain([_single("app/a.py", "a0\n", "a1\n")])
    assert not only.ok and not only.new_contents
    assert any("at least two" in r for r in only.blockers)

    none = compose_chain([])
    assert not none.ok and not none.new_contents
    assert any("at least two" in r for r in none.blockers)


def test_never_clobbers_the_shared_file_on_refusal():
    # Belt-and-suspenders: on an overlap refusal, the merged plan carries NEITHER
    # side's bytes for the shared file — the union is abandoned, not silently picked.
    a = _single("app/dup.py", "v0\n", "AAA\n")
    b = _single("app/other.py", "o0\n", "o1\n")
    c = _single("app/dup.py", "v0\n", "CCC\n")

    merged = compose_chain([a, b, c])

    assert merged.new_contents == {}  # no file — no "AAA", no "CCC", no "o1"


# --- determinism -------------------------------------------------------------

def _triple() -> list[RenamePlan]:
    return [_single("app/a.py", "a0\n", "a1\n"),
            _single("app/b.py", "b0\n", "b1\n"),
            _single("app/c.py", "c0\n", "c1\n")]


def test_deterministic():
    first = compose_chain(_triple())
    second = compose_chain(_triple())
    assert first.new_contents == second.new_contents
    assert first.originals == second.originals
    assert first.edits_by_file == second.edits_by_file
    assert first.render_diff() == second.render_diff()


# --- the per-module chain builder (end-to-end through the real planners) ------

def _pkg_project(tmp_path: Path) -> Path:
    """A tmp project with a package holding a tested fillable stub and an EMPTY
    ``__init__.py`` waiting to be wired — the canonical implement+wire chain."""
    (tmp_path / "app" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_module_chain_collects_and_composes_module_plans(tmp_path: Path):
    _pkg_project(tmp_path)
    # The general builder collects the module's applicable single-file plans for the
    # named objectives and composes them into ONE multi-file plan.
    plan = plan_module_chain(str(tmp_path), "app/pkg/calc.py",
                             ["implement-stub", "wire-exports"])
    assert plan.ok
    assert set(plan.new_contents) == {"app/pkg/calc.py", "app/pkg/__init__.py"}
    assert "return a + b" in plan.new_contents["app/pkg/calc.py"]
    assert "from .calc import add" in plan.new_contents["app/pkg/__init__.py"]


def test_module_chain_default_objectives(tmp_path: Path):
    # Called with no explicit objective list, the builder uses the canonical
    # implement-stub + wire-exports chain.
    _pkg_project(tmp_path)
    default = plan_module_chain(str(tmp_path), "app/pkg/calc.py")
    explicit = plan_module_chain(str(tmp_path), "app/pkg/calc.py",
                                 ["implement-stub", "wire-exports"])
    assert default.new_contents == explicit.new_contents


def test_module_chain_refuses_unknown_objective(tmp_path: Path):
    _pkg_project(tmp_path)
    # An objective with no per-module builder yields a blocked sub-plan, so the
    # chain refuses honestly (never a silent drop / never a guess).
    plan = plan_module_chain(str(tmp_path), "app/pkg/calc.py",
                             ["implement-stub", "no-such-objective"])
    assert not plan.ok and not plan.new_contents
    assert any("no-such-objective" in r for r in plan.blockers)


def test_module_objective_plan_unknown_is_blocked(tmp_path: Path):
    plan = _module_objective_plan(Path(tmp_path), "app/pkg/calc.py", "bogus")
    assert plan.blockers and not plan.new_contents
    assert any("bogus" in r for r in plan.blockers)


def test_module_objective_plan_dispatches_to_real_planner(tmp_path: Path):
    _pkg_project(tmp_path)
    plan = _module_objective_plan(Path(tmp_path), "app/pkg/calc.py", "implement-stub")
    assert set(plan.new_contents) == {"app/pkg/calc.py"}
    assert "return a + b" in plan.new_contents["app/pkg/calc.py"]


def test_plan_implement_and_wire_behavior_preserved(tmp_path: Path):
    # The existing entry point still builds the SAME implement+wire plan (now a thin
    # call into the general builder) — its contract is unchanged.
    _pkg_project(tmp_path)
    thin = plan_implement_and_wire(str(tmp_path), "app/pkg/calc.py")
    general = plan_module_chain(str(tmp_path), "app/pkg/calc.py",
                                ["implement-stub", "wire-exports"])
    assert thin.new_contents == general.new_contents
    assert thin.originals == general.originals


def test_module_chain_lands_atomically_through_the_one_gate(tmp_path: Path):
    # End-to-end: the composed chain flows through the EXISTING apply_rename gate —
    # both files land together, verified, no reimplementation of the gate here.
    _pkg_project(tmp_path)
    plan = plan_module_chain(str(tmp_path), "app/pkg/calc.py")

    res = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)

    assert res["applied"] is True and res["verified"] is True
    assert res["rolled_back"] is False
    calc = (tmp_path / "app" / "pkg" / "calc.py").read_text()
    assert "raise NotImplementedError" not in calc and "return a + b" in calc
    init = (tmp_path / "app" / "pkg" / "__init__.py").read_text()
    assert "from .calc import add" in init


def test_module_chain_refuses_when_stub_unsynthesizable(tmp_path: Path):
    # A module whose stub cannot be synthesized yields an empty implement-stub plan,
    # so the chain refuses honestly and nothing is written.
    (tmp_path / "app" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "calc.py").write_text(
        "def weird(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import weird\n"
        "def test_w():\n    assert weird(2, 3) == 7\n    assert weird(4, 4) == 99\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")

    plan = plan_module_chain(str(tmp_path), "app/pkg/calc.py")
    assert not plan.ok and not plan.new_contents and plan.blockers
