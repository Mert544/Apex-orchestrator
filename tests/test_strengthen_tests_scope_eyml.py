"""strengthen-tests opts into impact-scoped gating (the cross-module deadlock).

Commit 544a16b added a per-objective ``scope_verify`` flag to ``ObjectiveSpec``:
when set, ``compile_objective`` gates each move against the IMPACTED tests rather
than the FULL suite, so a correct per-module landing is not vetoed by an
UNRELATED still-red module on a multi-module project. ``implement-stub`` and
``tdd-implement`` opted in; this wave adds ``strengthen-tests``, which has the
SAME exposure: it APPENDS a double-gated mutant-killing assertion to a TEST file,
and if the full baseline suite is RED from OTHER modules' unimplemented stubs the
full-suite gate would roll back that correct landing.

Because the change is to a TEST file, ``impacted_test_files`` includes the
changed test file DIRECTLY, so impact-scoping runs exactly the appended
assertion's own tests (which genuinely pass after the landing — the "verified"
stamp stays honest) and skips the unrelated red modules. The full suite remains
the commit-time backstop, so never-fake-green holds.

These tests prove: (1) the spec flag is set; (2) on a two-module fixture whose
full baseline suite is RED (module B's unsynthesizable stub), strengthen-tests
LANDS its assertion on module A's test; (3) the regression direction via
``apply_rename`` — ``impact_scope=False`` rolls A's correct strengthening back,
``impact_scope=True`` lands it — so the scope flag is exactly what breaks the
deadlock; and (4) determinism.
"""

from __future__ import annotations

from pathlib import Path


# --- the spec flag is set ----------------------------------------------------

def test_strengthen_tests_opts_into_scope_verify():
    from app.engine.develop_registry import registered_specs

    assert registered_specs()["strengthen-tests"].scope_verify is True


def test_strengthen_tests_still_expensive_and_callable():
    # The new flag must not disturb the existing spec wiring.
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["strengthen-tests"]
    assert spec.expensive is True
    assert callable(spec.fitness) and callable(spec.moves)


# --- fixture: a hardenable module A + an unsynthesizable-RED module B ---------

def _two_module_project(root: Path) -> None:
    """A fresh project with TWO modules under one package.

    ``app/a.py``: a ``classify(n)`` whose ``n < 0`` boundary is a SURVIVING
    mutant — ``tests/test_a.py`` only exercises the ``pos`` branch, so flipping
    ``<`` to ``<=`` goes uncaught until strengthen-tests pins the boundary. The
    module IS importable and its one existing test passes (green on its own).

    ``app/b.py``: a ``mystery(n)`` stub NO fixed template can satisfy (witnesses
    0->1, 1->1, 2->9 fit no constant/arithmetic/parity shape), so b stays
    unimplemented and ``tests/test_b.py`` stays RED — the whole baseline suite is
    legitimately RED, mirroring tests/test_cross_module_stub_fill_eyml.py.
    """
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "a.py").write_text(
        'def classify(n):\n    return "neg" if n < 0 else "pos"\n',
        encoding="utf-8")
    (root / "tests" / "test_a.py").write_text(
        "from app.a import classify\n\n\n"
        'def test_pos():\n    assert classify(5) == "pos"\n',
        encoding="utf-8")
    (root / "app" / "b.py").write_text(
        "def mystery(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_b.py").write_text(
        "from app.b import mystery\n"
        "def test_b():\n"
        "    assert mystery(0) == 1\n"
        "    assert mystery(1) == 1\n"
        "    assert mystery(2) == 9\n", encoding="utf-8")


def _full_suite_green(root: Path) -> bool:
    """True iff the project's FULL test suite passes (a fresh pytest process)."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(root / "tests")],
        cwd=str(root), capture_output=True, text=True)
    return proc.returncode == 0


# --- the baseline IS red (the precondition the fix must survive) -------------

def test_baseline_full_suite_is_red(tmp_path: Path):
    # The premise: b's unsynthesizable stub keeps the FULL suite RED. If this were
    # ever green, the deadlock tests below would prove nothing.
    _two_module_project(tmp_path)
    assert _full_suite_green(tmp_path) is False


# --- the fix: strengthen-tests LANDS A's assertion despite the red suite ------

def test_strengthen_tests_lands_a_despite_red_b(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _two_module_project(tmp_path)
    assert _full_suite_green(tmp_path) is False  # red baseline (b)

    original_a_test = (tmp_path / "tests" / "test_a.py").read_text()

    result = compile_objective(str(tmp_path), "strengthen-tests", apply=True)

    # A real mutant-killing assertion landed in A's OWN generated file (a unique
    # ``_apex_mutants`` basename), even though the FULL suite is still red because
    # of b (which was never touched). The idiomatic ``tests/test_a.py`` is left
    # byte-for-byte untouched — Apex only ADDS its own collision-proof file.
    gen = (tmp_path / "tests" / "test_a_apex_mutants.py")
    assert gen.exists()
    assert "def test_a_kills_surviving_mutants():" in gen.read_text()
    assert (tmp_path / "tests" / "test_a.py").read_text() == original_a_test
    assert result.steps  # something landed (the deadlock is broken)
    # The landing is honestly verified: A's REAL test file was exercised scoped.
    assert any(s.verified for s in result.steps)

    # b is untouched — its redness was pre-existing, not caused by A.
    assert "raise NotImplementedError" in (tmp_path / "app" / "b.py").read_text()
    # The full suite is STILL red (b still fails) — we never faked green.
    assert _full_suite_green(tmp_path) is False

    # The generated mutants file passes on its own (the honest, scoped verification).
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(gen)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0


# --- regression direction: the scope flag is WHAT breaks the deadlock --------

def test_full_suite_gate_rolls_back_scoped_gate_lands(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename
    from app.execution.strengthen_tests import plan_strengthen_tests

    _two_module_project(tmp_path)
    original_a_test = (tmp_path / "tests" / "test_a.py").read_text()
    gen = (tmp_path / "tests" / "test_a_apex_mutants.py")

    # The same plan, twice. With impact_scope=False (full-suite gating), the gate
    # sees b still red and ROLLS BACK A's correct strengthening.
    plan = plan_strengthen_tests(tmp_path, "app/a.py")
    assert plan.new_contents  # there IS a real strengthening to gate
    res_full = apply_rename(tmp_path, plan, impact_scope=False)
    assert res_full.get("applied") is False
    assert res_full.get("rolled_back") is True
    # The created file is rolled back (deleted), and the idiomatic test is untouched.
    assert not gen.exists()
    assert (tmp_path / "tests" / "test_a.py").read_text() == original_a_test

    # With impact_scope=True, the gate runs ONLY A's own (generated) test file
    # (which passes), so the SAME strengthening LANDS — the scope flag is what
    # breaks the deadlock.
    plan2 = plan_strengthen_tests(tmp_path, "app/a.py")
    res_scoped = apply_rename(tmp_path, plan2, impact_scope=True)
    assert res_scoped.get("applied") is True
    assert res_scoped.get("verified") is True
    assert "def test_a_kills_surviving_mutants():" in gen.read_text()
    # The idiomatic test is STILL untouched — Apex only added its own file.
    assert (tmp_path / "tests" / "test_a.py").read_text() == original_a_test


# --- determinism: identical fixtures -> byte-identical landed test -----------

def test_strengthen_plan_is_deterministic(tmp_path: Path):
    from app.execution.strengthen_tests import plan_strengthen_tests

    _two_module_project(tmp_path)
    a = plan_strengthen_tests(tmp_path, "app/a.py").new_contents
    b = plan_strengthen_tests(tmp_path, "app/a.py").new_contents
    assert a == b and a != {}
