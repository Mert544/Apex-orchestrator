"""strengthen-tests develop objective — generate assertions that KILL mutants.

Covers: objective registration/reachability + facet route + the facet invariant;
the survivor -> double-gated-assertion pipeline that LANDS a real mutant-killing
assertion (passes on real code AND fails against the recorded mutant); the no-op
when a module's tests already kill every mutant (saturated); the honest refusal
when no survivor can be killed (lands nothing); refusal of a test/fixture file as
the MODULE target; determinism (same project -> identical plan twice); and
idempotence (a saturated module re-plans to a no-op).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.strengthen_tests import (
    _killing_assertion,
    _load_module_from_source,
    plan_strengthen_tests,
)


# --- registration / reachability / invariant ---------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "strengthen-tests" in set(available_objectives())


def test_objective_spec_is_callable_and_expensive():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["strengthen-tests"]
    assert callable(spec.fitness) and callable(spec.moves)
    # Its fitness probe runs the mutation engine per module — flagged expensive so
    # the fast plan/ascend board skips it (it stays runnable explicitly).
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "a surviving mutant the tests miss") == "strengthen-tests"


def test_facet_objective_map_invariant_still_holds():
    """The map's value set must equal the registered objective set — adding
    strengthen-tests must not break that invariant."""
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_idea_facets_phrase_is_present():
    """The append-only L2 phrase that routes to strengthen-tests is in the
    fractal vocabulary, so a zoom can actually reach the objective."""
    from app.engine.idea_facets import _FACET_SUBASPECTS

    assert "a surviving mutant the tests miss" in _FACET_SUBASPECTS[
        "property invariants"]


# --- fixtures ----------------------------------------------------------------

def _thin_project(root: Path) -> None:
    """A module whose ``n < 0`` boundary is a surviving mutant: the only test
    exercises the ``pos`` branch, so flipping ``<`` to ``<=`` (and ``0`` to ``1``)
    goes uncaught until strengthen-tests pins the boundary."""
    (root / "tests").mkdir()
    (root / "m.py").write_text(
        'def classify(n):\n    return "neg" if n < 0 else "pos"\n',
        encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "import m\n\n\ndef test_pos():\n    assert m.classify(5) == \"pos\"\n",
        encoding="utf-8")


# --- the survivor -> double-gated assertion pipeline -------------------------

def test_lands_a_mutant_killing_assertion(tmp_path: Path):
    _thin_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "m.py")

    # It extends the EXISTING thin test (originals recorded so it can roll back).
    assert list(plan.new_contents) == ["tests/test_m.py"]
    assert "tests/test_m.py" in plan.originals
    content = plan.new_contents["tests/test_m.py"]
    # The pre-existing test is preserved; a new mutant-killing test is appended.
    assert "def test_pos():" in content
    assert "def test_m_kills_surviving_mutants():" in content
    assert "m.classify(" in content
    # The emitted file parses.
    ast.parse(content)


def test_emitted_assertion_is_double_gated(tmp_path: Path):
    """The landed assertion PASSES on the real code AND would FAIL on the mutant
    it targets — the never-fake-green double gate, asserted directly."""
    _thin_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "m.py")
    content = plan.new_contents["tests/test_m.py"]

    # Gate (a): the appended assertion passes against the REAL module.
    (tmp_path / "tests" / "test_m.py").write_text(content, encoding="utf-8")
    import subprocess
    proc = subprocess.run(
        ["python", "-m", "pytest", "-q"], cwd=str(tmp_path),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Gate (b): the SAME assertion fails against the boundary mutant (< -> <=).
    mutated = 'def classify(n):\n    return "neg" if n <= 0 else "pos"\n'
    (tmp_path / "m.py").write_text(mutated, encoding="utf-8")
    proc2 = subprocess.run(
        ["python", "-m", "pytest", "-q"], cwd=str(tmp_path),
        capture_output=True, text=True)
    assert proc2.returncode != 0  # the mutant is caught -> proven kill


def test_mutation_score_improves_after_landing(tmp_path: Path):
    from app.engine.mutation_tester import mutation_score

    _thin_project(tmp_path)
    before = mutation_score(tmp_path, "m.py")
    assert before.survivors  # there IS a blind spot to close

    plan = plan_strengthen_tests(tmp_path, "m.py")
    for rel, text in plan.new_contents.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")

    after = mutation_score(tmp_path, "m.py")
    assert after.score > before.score
    assert not after.survivors  # every survivor killed -> saturated


# --- no-op / refusal paths ---------------------------------------------------

def test_no_op_when_no_survivors(tmp_path: Path):
    """A module whose tests already kill every mutant has no survivors, so the
    plan is empty (a no-op, not a failure)."""
    _thin_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "m.py")
    for rel, text in plan.new_contents.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")

    saturated = plan_strengthen_tests(tmp_path, "m.py")
    assert saturated.new_contents == {}
    assert saturated.blockers == []


def test_refuses_when_survivor_unkillable_lands_nothing(tmp_path: Path):
    """A module that genuinely HAS surviving mutants but whose function returns a
    non-literal (so no reproducible oracle exists) is left UNKILLED: the plan
    lands nothing rather than fabricate an oracle — honest never-fake-green."""
    from app.engine.mutation_tester import mutation_score

    (tmp_path / "tests").mkdir()
    # `pick` returns a Box() on either branch — a real object, not a simple
    # literal — so even though its `n < 0` boundary mutant survives, there is no
    # reproducible value to assert.
    (tmp_path / "u.py").write_text(
        "class Box:\n    pass\n\n\n"
        "def pick(n):\n    if n < 0:\n        return Box()\n    return Box()\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_u.py").write_text(
        "import u\n\n\ndef test_runs():\n    assert isinstance(u.pick(5), u.Box)\n",
        encoding="utf-8")

    # There ARE survivors (the blind spot is real)...
    assert mutation_score(tmp_path, "u.py").survivors
    # ...but none can be killed with an honest literal oracle -> land nothing.
    plan = plan_strengthen_tests(tmp_path, "u.py")
    assert plan.new_contents == {}
    assert plan.blockers == []


def test_refuses_test_fixture_module_target(tmp_path: Path):
    _thin_project(tmp_path)
    # The MODULE target is never a test/fixture file (Apex writes INTO tests).
    assert plan_strengthen_tests(tmp_path, "tests/test_m.py").new_contents == {}
    assert plan_strengthen_tests(tmp_path, "m.py:notpy").new_contents == {}


def test_refuses_dunder_module(tmp_path: Path):
    (tmp_path / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    assert plan_strengthen_tests(tmp_path, "__init__.py").new_contents == {}


def test_unreadable_module_is_no_op(tmp_path: Path):
    assert plan_strengthen_tests(tmp_path, "missing.py").new_contents == {}


# --- determinism / idempotence ----------------------------------------------

def test_plan_is_deterministic(tmp_path: Path):
    _thin_project(tmp_path)
    a = plan_strengthen_tests(tmp_path, "m.py").new_contents
    b = plan_strengthen_tests(tmp_path, "m.py").new_contents
    assert a == b and a != {}


def test_idempotent_after_apply(tmp_path: Path):
    """Re-planning after the killing assertions land is a no-op — there is no
    surviving mutant left to kill."""
    _thin_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "m.py")
    for rel, text in plan.new_contents.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    assert plan_strengthen_tests(tmp_path, "m.py").new_contents == {}


# --- helper-level double gate ------------------------------------------------

def test_killing_assertion_rejects_equivalent_mutant():
    """When the mutant agrees with the real function on every probe input, no
    assertion is emitted (it would add no signal) — _killing_assertion returns
    None."""
    real = _load_module_from_source(
        "def f(n):\n    return n + 0\n", "x")
    # `n + 0` vs `n - 0` are equal on every numeric probe -> equivalent mutant.
    mutant = _load_module_from_source(
        "def f(n):\n    return n - 0\n", "x")
    assert _killing_assertion(real, mutant, "x", "f", 1) is None


def test_killing_assertion_emits_for_a_real_divergence():
    real = _load_module_from_source(
        "def f(n):\n    return n + 1\n", "x")
    mutant = _load_module_from_source(
        "def f(n):\n    return n - 1\n", "x")
    line = _killing_assertion(real, mutant, "x", "f", 1)
    assert line is not None and line.startswith("assert x.f(")
