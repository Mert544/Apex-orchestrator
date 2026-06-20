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
    _binding_for,
    _existing_bindings,
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
    # The third arg is now the exact CALL TARGET the rendered line uses (so a
    # caller can address the function however its import binding resolves).
    line = _killing_assertion(real, mutant, "x.f", "f", 1)
    assert line is not None and line.startswith("assert x.f(")


def test_killing_assertion_honours_an_arbitrary_call_target():
    """The emitted assertion addresses the function through whatever ``call_target``
    the caller chose — a bare name, an alias, a dotted prefix — while the double
    gate still runs against ``fn_name`` in-process (target only shapes the text)."""
    real = _load_module_from_source(
        "def f(n):\n    return n + 1\n", "x")
    mutant = _load_module_from_source(
        "def f(n):\n    return n - 1\n", "x")
    bare = _killing_assertion(real, mutant, "_apex_fn_f", "f", 1)
    assert bare is not None and bare.startswith("assert _apex_fn_f(")
    aliased = _killing_assertion(real, mutant, "alias.f", "f", 1)
    assert aliased is not None and aliased.startswith("assert alias.f(")


# --- import-binding detection (reuse existing / alias fallback) ---------------

def test_existing_bindings_detects_module_import():
    """``import pkg.mod`` / ``import pkg.mod as alias`` are read as MODULE prefixes
    usable for any function; a ``from . import`` relative form is ignored."""
    src = (
        "import pkg.mod\n"
        "import pkg.mod as pm\n"
        "from pkg.mod import letter\n"
        "from . import sibling\n"
    )
    prefixes, fn_bindings = _existing_bindings(src, "pkg.mod")
    assert prefixes == ["pkg.mod", "pm"]
    assert fn_bindings == {"letter": "letter"}


def test_existing_bindings_detects_from_import_alias():
    """``from pkg.mod import fn as bound`` binds ``fn -> bound`` for a bare call;
    a star import and an unrelated module are not treated as bindings."""
    src = (
        "from pkg.mod import grade as g\n"
        "from pkg.mod import *\n"
        "from other.mod import thing\n"
    )
    prefixes, fn_bindings = _existing_bindings(src, "pkg.mod")
    assert prefixes == []
    assert fn_bindings == {"grade": "g"}


def test_existing_bindings_empty_for_unreadable_or_unparseable():
    assert _existing_bindings(None, "pkg.mod") == ([], {})
    assert _existing_bindings("def (:\n", "pkg.mod") == ([], {})


def test_binding_for_reuses_from_import_bare():
    """A function the existing test imported with ``from pkg.mod import fn`` is
    called BARE; nothing new is emitted, but it is still verified by an import."""
    emit, verify, target = _binding_for("fn", "pkg.mod", [], {"fn": "fn"})
    assert emit is None
    assert target == "fn"
    assert verify == "from pkg.mod import fn as fn"


def test_binding_for_reuses_module_prefix():
    emit, verify, target = _binding_for("fn", "pkg.mod", ["pm"], {})
    assert emit is None
    assert target == "pm.fn"
    assert verify == "import pkg.mod as pm"


def test_binding_for_falls_back_to_private_alias_import():
    """With no usable existing binding, an unambiguous ``from``-import of the
    SUBMODULE is emitted (immune to an ``__init__`` re-export shadowing the
    module attribute), with a private, name-derived (deterministic) alias."""
    emit, verify, target = _binding_for("classify", "pkg.classify", [], {})
    assert emit == "from pkg.classify import classify as _apex_fn_classify"
    assert verify == emit
    assert target == "_apex_fn_classify"


def test_binding_for_alias_is_deterministic():
    a = _binding_for("classify", "pkg.classify", [], {})
    b = _binding_for("classify", "pkg.classify", [], {})
    assert a == b


# --- the field-test repros: rolled-back -> landed ----------------------------

def _grades_project(root: Path) -> None:
    """A package whose existing test imports via ``from pkg.grades import letter``
    (the idiomatic form). The OLD code appended ``assert pkg.grades.letter(...)``
    with no ``import pkg.grades`` -> NameError -> suite red -> rolled back."""
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "grades.py").write_text(
        "def letter(score):\n"
        "    if score < 60:\n"
        "        return \"F\"\n"
        "    return \"P\"\n",
        encoding="utf-8")
    (root / "tests" / "test_grades.py").write_text(
        "from pkg.grades import letter\n\n\n"
        "def test_pass():\n    assert letter(90) == \"P\"\n",
        encoding="utf-8")


def _suite_passes(root: Path) -> bool:
    """Run the project's own pytest in a subprocess — the real full-suite gate the
    verified-apply engine uses; green here means the plan LANDS (no rollback)."""
    import subprocess

    proc = subprocess.run(
        ["python", "-m", "pytest", "-q"], cwd=str(root),
        capture_output=True, text=True)
    return proc.returncode == 0


def test_append_to_from_import_file_lands(tmp_path: Path):
    """REPRO 1: the appended assertion reuses the file's ``from pkg.grades import
    letter`` binding (bare ``letter(...)``), so it RESOLVES and the suite stays
    green — the contribution lands instead of being rolled back."""
    _grades_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "pkg/grades.py")
    content = plan.new_contents["tests/test_grades.py"]

    # The existing test is preserved; the appended assertion uses the bare binding
    # and NEVER the un-imported fully-qualified `pkg.grades.letter` form.
    assert "def test_pass():" in content
    assert "assert letter(" in content
    assert "pkg.grades.letter(" not in content
    ast.parse(content)

    # Apply and prove the real suite is GREEN (was red/rolled-back before the fix).
    (tmp_path / "tests" / "test_grades.py").write_text(content, encoding="utf-8")
    assert _suite_passes(tmp_path)


def _shadow_project(root: Path) -> None:
    """A package whose ``__init__`` re-exports ``from .classify import classify``,
    so the module attribute ``pkg.classify`` resolves to the FUNCTION. The OLD
    fresh-file form ``import pkg.classify; pkg.classify.classify(...)`` broke with
    AttributeError. The existing test imports ``from pkg import classify`` (the
    package re-export), which is NOT a binding for the submodule ``pkg.classify``,
    so the fix falls back to a shadow-immune ``from pkg.classify import ...``."""
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text(
        "from .classify import classify\n", encoding="utf-8")
    (root / "pkg" / "classify.py").write_text(
        "def classify(n):\n    return \"neg\" if n < 0 else \"pos\"\n",
        encoding="utf-8")
    (root / "tests" / "test_classify.py").write_text(
        "from pkg import classify\n\n\n"
        "def test_pos():\n    assert classify(5) == \"pos\"\n",
        encoding="utf-8")


def test_shadowing_package_lands(tmp_path: Path):
    """REPRO 2: with ``pkg.classify`` shadowed by a re-exported function, the
    appended assertion uses a ``from pkg.classify import classify as _apex_...``
    alias of the SUBMODULE, which resolves; the suite stays green and lands."""
    _shadow_project(tmp_path)
    plan = plan_strengthen_tests(tmp_path, "pkg/classify.py")
    content = plan.new_contents["tests/test_classify.py"]

    # It uses the shadow-immune submodule alias, never `pkg.classify.classify`.
    assert "from pkg.classify import classify as _apex_fn_classify" in content
    assert "_apex_fn_classify(" in content
    assert "pkg.classify.classify(" not in content
    ast.parse(content)

    (tmp_path / "tests" / "test_classify.py").write_text(content, encoding="utf-8")
    assert _suite_passes(tmp_path)


def test_fresh_file_uses_resolvable_alias_and_lands(tmp_path: Path):
    """REPRO 3: a module with no ``tests/test_<stem>.py`` gets a FRESH file whose
    top-level import is the unambiguous submodule alias, and the called name is
    that alias — a fresh file still works and resolves."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "calc.py").write_text(
        "def sign(n):\n    if n < 0:\n        return -1\n    return 1\n",
        encoding="utf-8")
    # An unrelated passing test so the mutation baseline is sound (green).
    (tmp_path / "tests" / "test_other.py").write_text(
        "from pkg.calc import sign\n\n\n"
        "def test_sign():\n    assert sign(5) == 1\n",
        encoding="utf-8")

    plan = plan_strengthen_tests(tmp_path, "pkg/calc.py")
    assert list(plan.new_contents) == ["tests/test_calc.py"]
    # A fresh file -> no original recorded (nothing to roll back to).
    assert "tests/test_calc.py" not in plan.originals
    content = plan.new_contents["tests/test_calc.py"]
    assert "from pkg.calc import sign as _apex_fn_sign" in content
    assert "_apex_fn_sign(" in content
    ast.parse(content)

    (tmp_path / "tests" / "test_calc.py").write_text(content, encoding="utf-8")
    assert _suite_passes(tmp_path)


def test_repro_plans_are_deterministic(tmp_path: Path):
    """Both repros re-plan to the byte-identical content across two runs (the
    alias is name-derived; nothing clock/random enters the rendered file)."""
    _grades_project(tmp_path)
    a = plan_strengthen_tests(tmp_path, "pkg/grades.py").new_contents
    b = plan_strengthen_tests(tmp_path, "pkg/grades.py").new_contents
    assert a == b and a != {}


def test_non_resolving_binding_lands_nothing(tmp_path: Path, monkeypatch):
    """If the emitted import+call cannot be made to resolve, the assertion is
    DROPPED and nothing lands — a broken test is never landed (the resolution
    guard, complementing the double gate)."""
    import app.execution.strengthen_tests as st

    _grades_project(tmp_path)
    # Force the in-process resolution oracle to report failure for every binding.
    monkeypatch.setattr(st, "_import_call_resolves", lambda *a, **k: False)
    plan = plan_strengthen_tests(tmp_path, "pkg/grades.py")
    assert plan.new_contents == {}
    assert plan.blockers == []
