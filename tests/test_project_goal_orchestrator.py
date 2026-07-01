"""project_goal_orchestrator — compose a decomposed goal's leaves into ONE gated,
atomically-landed (or wholly-rolled-back) multi-file change.

Covers the North-Star gap this closes: the fractal goal path lands leaves
INDEPENDENTLY (a stub can land without its wiring); the orchestrator composes the
leaves' single-file plans into ONE plan, gates ONCE, and lands them together or
NEITHER. Tests:
  * two leaves (implement-stub + modernize) compose into ONE multi-file plan that
    gates once and lands ATOMICALLY (both files change; the fill and the tidy hold
    together);
  * a composed plan that goes RED rolls back the WHOLE goal — NEITHER file lands,
    both restored byte-for-byte (never-fake-green whole-goal rollback);
  * ``compose_plans``' file-overlap refusal is HONORED — the fold returns a blocked
    plan and the orchestrator lands nothing, rather than forcing a conflicting merge;
  * edge/empty paths: an unknown goal refuses; a goal with <2 landable leaves
    refuses (nothing to compose); a dry run writes nothing; the leaf-plan builder
    keeps the file set disjoint; the result is deterministic.

The atomic gate and rollback are the EXISTING ``apply_rename`` engine — these
tests assert the orchestrator's WIRING of it, not a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.project_goal_orchestrator import (
    GoalLanding,
    LeafPlan,
    ProjectGoalOrchestrator,
    _collect_leaf_plans,
    _compose_all,
    _leaf_single_file_plan,
    orchestrate_goal,
    render_goal_landing_markdown,
)
from app.execution.compose_plans import compose_plans
from app.execution.cross_file_rename import RenamePlan


# --- fixtures ----------------------------------------------------------------

def _stub_plus_modernize_project(tmp_path: Path) -> Path:
    """A project with a fillable stub (implement-stub) AND a separate ``== None``
    file (modernize) — two DISTINCT-file leaves the orchestrator can compose."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # A test-pinned fillable stub -> implement-stub.
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    # A separate module with a `== None` idiom -> modernize.
    (tmp_path / "app" / "m.py").write_text(
        "__all__ = []\ndef r(x):\n    if x == None:\n"
        "        return 0\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import r\ndef test_r():\n"
        "    assert r(None) == 0\n    assert r(3) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _single(rel: str, before: str, after: str) -> RenamePlan:
    """A minimal single-file plan shaped like a real objective's."""
    plan = RenamePlan(old=rel, new="x")
    plan.originals[rel] = before
    plan.new_contents[rel] = after
    plan.edits_by_file[rel] = 1
    return plan


# --- the headline behaviour: the STUB + its WIRING land ATOMICALLY -----------

def test_stub_and_wiring_land_together_atomically(tmp_path):
    # The exact North-Star gap this closes: implement-stub fills the body AND
    # wire-exports surfaces it — composed into ONE plan and landed through ONE gate,
    # so they land TOGETHER (never a body nothing imports). The fixture's stub is
    # unexported, so `ship-value` decomposes into implement-stub (app/s.py) +
    # wire-exports (app/__init__.py) as distinct-file leaves.
    _stub_plus_modernize_project(tmp_path)
    s_before = (tmp_path / "app" / "s.py").read_text()
    init_before = (tmp_path / "app" / "__init__.py").read_text()

    landing = orchestrate_goal(str(tmp_path), "ship-value", apply=True)

    assert landing.applied and landing.verified
    assert not landing.refused and not landing.rolled_back
    # BOTH the fill and its wiring are in the ONE composed landing (membership, not
    # equality — other leaves may also find work; the point is they land as a unit).
    assert "app/s.py" in landing.files_changed
    assert "app/__init__.py" in landing.files_changed
    assert landing.composed_files >= 2
    # Both actually landed on the tree — the stub filled AND the export wired.
    s_after = (tmp_path / "app" / "s.py").read_text()
    init_after = (tmp_path / "app" / "__init__.py").read_text()
    assert s_after != s_before and "return a + b" in s_after
    assert init_after != init_before and "add" in init_after
    # Every contributing leaf owns a DISTINCT file (the disjoint union invariant).
    files = [leaf.file for leaf in landing.contributing_leaves]
    assert len(files) == len(set(files)) and len(files) >= 2


def test_landing_is_one_composed_plan_not_per_leaf(tmp_path):
    # The composed plan the orchestrator lands is a SINGLE multi-file RenamePlan —
    # the whole point (one gate, not one-per-leaf). The dry run exposes that plan:
    # its file set is the UNION of the contributing leaves' files, proving they were
    # composed into one unit BEFORE any gate ran.
    _stub_plus_modernize_project(tmp_path)
    dry = orchestrate_goal(str(tmp_path), "ship-value", apply=False)
    assert not dry.applied  # dry run: composed, not landed
    leaf_files = {leaf.file for leaf in dry.contributing_leaves}
    assert set(dry.files_changed) == leaf_files  # exactly the union of the leaves
    assert "app/s.py" in dry.files_changed and "app/__init__.py" in dry.files_changed
    assert dry.diff and "return a + b" in dry.diff


# --- whole-goal rollback on RED ----------------------------------------------

def test_red_composed_plan_rolls_back_whole_goal(tmp_path):
    # A composed plan whose land REGRESSES the suite must roll back the WHOLE goal:
    # NEITHER file lands. We compose two harmless-looking single-file plans (one per
    # distinct file) where the SECOND breaks a currently-green test, and drive the
    # exact gate the orchestrator uses. This is the never-fake-green core: the
    # single gate reverts every composed file together.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ab.py").write_text(
        "from app.a import f\nfrom app.b import g\n"
        "def test_f():\n    assert f() == 1\n"
        "def test_g():\n    assert g() == 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    a_before = (tmp_path / "app" / "a.py").read_text()
    b_before = (tmp_path / "app" / "b.py").read_text()
    pa = _single("app/a.py", a_before, "def f():\n    return 1  # touched\n")
    pb = _single("app/b.py", b_before, "def g():\n    return 99\n")  # regression!

    # Compose ourselves (the orchestrator's fold) and land through its exact gate.
    landing = GoalLanding(goal="synthetic", objectives=["x", "y"],
                          leaves=[LeafPlan("x", "app/a.py:x", "app/a.py"),
                                  LeafPlan("y", "app/b.py:y", "app/b.py")])
    from app.engine.project_goal_orchestrator import _land_composed
    _land_composed(landing, str(tmp_path), _compose_all([pa, pb]), verify=True)

    assert not landing.applied
    assert landing.rolled_back
    assert not landing.verified
    assert landing.files_changed == []  # nothing stands
    # WHOLE-GOAL rollback: BOTH files back at their pre-change bytes.
    assert (tmp_path / "app" / "a.py").read_text() == a_before
    assert (tmp_path / "app" / "b.py").read_text() == b_before


# --- compose_plans' overlap refusal is honored -------------------------------

def test_overlap_refusal_is_honored_by_the_fold():
    # Two plans on the SAME file: compose_plans refuses, and _compose_all returns
    # that blocked plan verbatim — the orchestrator NEVER forces a conflicting merge.
    a = _single("app/dup.py", "v0\n", "v1\n")
    b = _single("app/dup.py", "v0\n", "v2\n")
    merged = _compose_all([a, b])
    assert merged.blockers  # refused
    assert not merged.new_contents  # lands nothing
    assert any("dup.py" in r and "conflict" in r for r in merged.blockers)


def test_orchestrator_refuses_when_composition_refuses(tmp_path, monkeypatch):
    # If the leaf planner (hypothetically) yielded two plans on the SAME file, the
    # orchestrator must surface compose_plans' refusal and land NOTHING — not force
    # it. We stub the leaf builder to return an overlapping pair and assert the
    # refusal path. (The real builder keeps files disjoint; this proves the HONOR.)
    import app.engine.project_goal_orchestrator as pgo

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "dup.py").write_text("v0\n", encoding="utf-8")

    def _overlapping(root, objectives):
        pa = _single("app/dup.py", "v0\n", "v1\n")
        pb = _single("app/dup.py", "v0\n", "v2\n")
        leaves = [LeafPlan(objectives[0], "app/dup.py:a", "app/dup.py"),
                  LeafPlan(objectives[1], "app/dup.py:b", "app/dup.py")]
        return [pa, pb], leaves

    monkeypatch.setattr(pgo, "_collect_leaf_plans", _overlapping)
    landing = orchestrate_goal(str(tmp_path), "ship-value", apply=True)

    assert landing.refused and not landing.applied and not landing.rolled_back
    assert "conflict" in landing.reason
    assert (tmp_path / "app" / "dup.py").read_text() == "v0\n"  # untouched


# --- edge / empty paths ------------------------------------------------------

def test_unknown_goal_refuses_and_lands_nothing(tmp_path):
    landing = orchestrate_goal(str(tmp_path), "conquer-the-world", apply=True)
    assert landing.refused and not landing.applied
    assert landing.objectives == []
    assert "unknown goal" in landing.reason


def test_fewer_than_two_leaves_refuses(tmp_path):
    # A goal where only ONE leaf can contribute has nothing to COMPOSE — the
    # orchestrator refuses (the per-objective path is the right tool for one change).
    # `finish-code` = implement-stub + tdd-implement + scaffold-from-protocol; on a
    # plain fillable stub only implement-stub contributes -> one leaf -> refuse.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    landing = orchestrate_goal(str(tmp_path), "finish-code", apply=True)
    assert landing.refused and not landing.applied
    assert "fewer than two" in landing.reason
    # Exactly one leaf could contribute; the lone stub was NOT landed (no compose).
    assert len(landing.contributing_leaves) == 1
    assert "NotImplementedError" in (tmp_path / "app" / "s.py").read_text()


def test_dry_run_writes_nothing(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    s_before = (tmp_path / "app" / "s.py").read_text()
    init_before = (tmp_path / "app" / "__init__.py").read_text()

    landing = orchestrate_goal(str(tmp_path), "ship-value", apply=False)

    assert not landing.applied and not landing.refused
    assert landing.composed_files >= 2  # it DID compose a plan, it just didn't write
    # Nothing on disk changed, and no USAGE.md was created by the dry run.
    assert (tmp_path / "app" / "s.py").read_text() == s_before
    assert (tmp_path / "app" / "__init__.py").read_text() == init_before
    assert not (tmp_path / "app" / "USAGE.md").exists()


def test_leaf_plan_builder_keeps_files_disjoint(tmp_path):
    # The plan builder threads `taken`: a file already claimed by an earlier leaf is
    # never offered again, so the fold only ever sees disjoint single-file plans.
    _stub_plus_modernize_project(tmp_path)
    plan, target, reason = _leaf_single_file_plan(
        str(tmp_path), "implement-stub", taken=set())
    assert plan is not None and len(plan.new_contents) == 1
    only = next(iter(plan.new_contents))
    # With that file already taken, the SAME objective yields nothing to add.
    plan2, _t2, reason2 = _leaf_single_file_plan(
        str(tmp_path), "implement-stub", taken={only})
    assert plan2 is None and "no landable single-file move" in reason2


def test_leaf_plan_builder_reports_unknown_objective(tmp_path):
    plan, target, reason = _leaf_single_file_plan(
        str(tmp_path), "not-a-real-objective", taken=set())
    assert plan is None and "unknown objective" in reason


def test_collect_leaf_plans_records_skips_and_contributions(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    plans, leaves = _collect_leaf_plans(
        str(tmp_path), ["implement-stub", "modernize", "dead-params"])
    # implement-stub + modernize contribute; dead-params has no move here -> skipped.
    contributed = [leaf for leaf in leaves if leaf.contributed]
    assert {leaf.objective for leaf in contributed} == {"implement-stub", "modernize"}
    assert len(plans) == len(contributed) == 2
    skipped = [leaf for leaf in leaves if not leaf.contributed]
    assert any(leaf.objective == "dead-params" and leaf.reason for leaf in skipped)


# --- composition equivalence + determinism -----------------------------------

def test_composed_plan_matches_direct_compose_plans(tmp_path):
    # The orchestrator's fold is exactly compose_plans over the leaves' plans — the
    # composed file set equals a direct two-plan compose of the same leaves.
    _stub_plus_modernize_project(tmp_path)
    plans, _leaves = _collect_leaf_plans(str(tmp_path), ["implement-stub", "modernize"])
    direct = compose_plans(plans[0], plans[1])
    folded = _compose_all(plans)
    assert set(folded.new_contents) == set(direct.new_contents)
    assert folded.new_contents == direct.new_contents


def test_deterministic_dry_run(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    a = orchestrate_goal(str(tmp_path), "ship-value", apply=False)
    b = orchestrate_goal(str(tmp_path), "ship-value", apply=False)
    assert a.to_dict() == b.to_dict()
    assert a.files_changed == b.files_changed and a.diff == b.diff


# --- class handle + renderer -------------------------------------------------

def test_orchestrator_class_land_and_preview(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    orch = ProjectGoalOrchestrator(str(tmp_path))
    preview = orch.preview("ship-value")
    assert not preview.applied
    assert {"app/s.py", "app/__init__.py"} <= set(preview.files_changed)
    # Preview wrote nothing.
    assert "NotImplementedError" in (tmp_path / "app" / "s.py").read_text()
    landing = orch.land("ship-value")
    assert landing.applied and landing.verified
    assert "return a + b" in (tmp_path / "app" / "s.py").read_text()


def test_render_landing_markdown_applied(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    md = render_goal_landing_markdown(orchestrate_goal(str(tmp_path), "ship-value",
                                                       apply=True))
    assert "Project-goal orchestration" in md and "ship-value" in md
    assert "one atomic goal" in md or "ONE atomic goal" in md
    assert "## Leaves" in md and "one gated diff" in md
    assert "implement-stub" in md


def test_render_landing_markdown_refused(tmp_path):
    md = render_goal_landing_markdown(
        orchestrate_goal(str(tmp_path), "conquer-the-world", apply=True))
    assert "Refused" in md and "unknown goal" in md


def test_render_landing_markdown_rolled_back():
    landing = GoalLanding(goal="g", objectives=["x", "y"], rolled_back=True,
                          reason="tests failed after rename; all files restored")
    md = render_goal_landing_markdown(landing)
    assert "ROLLED BACK" in md and "pre-change bytes" in md


# --- engine capability, NOT a develop objective ------------------------------

def test_is_not_a_registered_develop_objective():
    # The orchestrator is an ENGINE capability: it registers nothing, so the
    # objective count/parity is untouched (no count-pin change).
    from app.engine.objective_compiler import available_objectives
    names = available_objectives()
    assert "project-goal-orchestrator" not in names
    assert "orchestrate-goal" not in names


def test_no_self_registration_via_landing():
    # Sanity: importing/using the module adds no objective (defensive against an
    # accidental registry side effect).
    from app.engine.objective_compiler import available_objectives
    before = set(available_objectives())
    _ = ProjectGoalOrchestrator(".")
    assert set(available_objectives()) == before
