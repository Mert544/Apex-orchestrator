"""Cross-module apply-deadlock fix — per-objective ``scope_verify`` gate.

The HEADLINE buyer blocker: ``apex develop --objective implement-stub`` lands 0
contributions on a realistic MULTI-MODULE project. Root cause: the per-move gate
ran the FULL suite. On a project where several modules each hold an unimplemented
stub, the full suite is RED at baseline. When implement-stub fills module A's stub
correctly (A's own tests now pass), a full-suite gate STILL sees RED — because
module B's still-unimplemented stub keeps ITS tests failing — so it ROLLS BACK A's
correct change. Every module gets vetoed by every OTHER module's pre-existing
redness; nothing lands.

The fix is a per-objective ``scope_verify`` flag on ``ObjectiveSpec``. When set
(only on the stub-FILLING objectives ``implement-stub`` / ``tdd-implement``),
``compile_objective`` gates each move against the IMPACTED tests (the ones that
import the changed module / its package) instead of the full suite. The full
suite stays the commit-time backstop, so the never-fake-green moat holds: A's
REAL importing tests genuinely pass after the fill, while B's PRE-EXISTING redness
(not caused by A) no longer vetoes it.

These tests build a fresh two-module fixture where ``app/a.py`` is satisfiable and
``app/b.py`` is genuinely unsynthesizable (so its test stays RED, the baseline
suite stays RED), and prove: (1) the fix LANDS a's fill end-to-end even though the
full suite is red because of b; (2) the regression direction — ``impact_scope=
False`` rolls a's correct fill back, ``impact_scope=True`` lands it — so the scope
flag is exactly what breaks the deadlock; (3) the spec-flag defaults and the two
opted-in objectives; and (4) determinism (two identical fixtures → byte-identical
``a.py``).
"""

from __future__ import annotations

from pathlib import Path


# --- fixture: two modules, one satisfiable, one unsynthesizable --------------

def _two_module_project(root: Path) -> None:
    """A fresh project with TWO stub-holding modules under one package.

    ``app/a.py``: a ``double(n)`` stub a fixed template CAN fill (``n * 2``),
    pinned by ``tests/test_a.py`` with two consistent witnesses (3->6, 2->4).

    ``app/b.py``: a ``mystery(n)`` stub NO fixed template can satisfy — the
    witnesses 0->1, 1->1, 2->9 fit no constant (they disagree) and no ``n OP k``
    arithmetic/parity/comparison/recursion shape. So b stays unimplemented and
    ``tests/test_b.py`` stays RED — the whole baseline suite is legitimately RED.
    """
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "a.py").write_text(
        "def double(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_a.py").write_text(
        "from app.a import double\n"
        "def test_a():\n    assert double(3) == 6\n    assert double(2) == 4\n",
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
    # The whole premise: b's unsynthesizable stub keeps the FULL suite RED. If
    # this baseline were ever green, the deadlock test below would prove nothing.
    _two_module_project(tmp_path)
    assert _full_suite_green(tmp_path) is False  # b's test fails at baseline


# --- the fix: implement-stub LANDS a's fill despite the red suite ------------

def test_implement_stub_lands_a_despite_red_b(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _two_module_project(tmp_path)
    # Sanity: the baseline really is red (b is unsatisfiable).
    assert _full_suite_green(tmp_path) is False

    result = compile_objective(str(tmp_path), "implement-stub", apply=True)

    # a.py's stub is implemented ON DISK and its own tests pass — even though the
    # FULL suite is still red because of b (which was never touched).
    a_text = (tmp_path / "app" / "a.py").read_text()
    assert "raise NotImplementedError" not in a_text
    assert "return n * 2" in a_text or "return n + n" in a_text
    assert result.steps  # something landed (the deadlock is broken)
    # The change is honestly verified: a's REAL importing test exercised the fill.
    assert any(s.verified for s in result.steps)

    # b is untouched — its redness was pre-existing, not caused by a.
    b_text = (tmp_path / "app" / "b.py").read_text()
    assert "raise NotImplementedError" in b_text
    # The full suite is STILL red (b still fails) — the moat: we never faked green.
    assert _full_suite_green(tmp_path) is False

    # tests/test_a.py now passes on its own (the honest, scoped verification).
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(tmp_path / "tests" / "test_a.py")],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0


# --- regression direction: the scope flag is WHAT breaks the deadlock --------

def test_full_suite_gate_rolls_back_scoped_gate_lands(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename
    from app.execution.objectives.implement_stub import plan_implement_stub

    _two_module_project(tmp_path)
    original_a = (tmp_path / "app" / "a.py").read_text()

    # The same plan, twice. With impact_scope=False (the OLD default), the
    # full-suite gate sees b still red and ROLLS BACK a's correct fill.
    plan = plan_implement_stub(str(tmp_path), "app/a.py")
    assert plan.new_contents  # a IS satisfiable — there is a real plan to gate
    res_full = apply_rename(tmp_path, plan, impact_scope=False)
    assert res_full.get("applied") is False
    assert res_full.get("rolled_back") is True
    assert (tmp_path / "app" / "a.py").read_text() == original_a  # restored

    # With impact_scope=True, the gate runs ONLY a's importing tests (which pass),
    # so the SAME fill LANDS — proving the scope flag is what breaks the deadlock.
    plan2 = plan_implement_stub(str(tmp_path), "app/a.py")
    res_scoped = apply_rename(tmp_path, plan2, impact_scope=True)
    assert res_scoped.get("applied") is True
    assert res_scoped.get("verified") is True
    a_text = (tmp_path / "app" / "a.py").read_text()
    assert "raise NotImplementedError" not in a_text
    assert "return n * 2" in a_text or "return n + n" in a_text


# --- the spec flag: default + the two opted-in objectives --------------------

def test_objective_spec_scope_verify_defaults_false():
    from app.engine.develop_registry import ObjectiveSpec

    spec = ObjectiveSpec(name="x", fitness=lambda r: 0.0, moves=lambda r: [])
    assert spec.scope_verify is False  # cheap tidy objectives keep full-suite gating


def test_stub_filling_objectives_opt_into_scope_verify():
    from app.engine.develop_registry import registered_specs

    specs = registered_specs()
    assert specs["implement-stub"].scope_verify is True
    assert specs["tdd-implement"].scope_verify is True


def test_tidy_objective_does_not_opt_into_scope_verify():
    # A representative cheap "tidy" objective must NOT have opted in — existing
    # full-suite gating (and thus existing behaviour) is unchanged for it.
    from app.engine.develop_registry import registered_specs

    specs = registered_specs()
    if "modernize" in specs:
        assert specs["modernize"].scope_verify is False


# --- determinism: identical fixtures -> byte-identical a.py ------------------

def test_compile_is_deterministic_across_fresh_fixtures(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _two_module_project(tmp_path)
    compile_objective(str(tmp_path), "implement-stub", apply=True)
    first = (tmp_path / "app" / "a.py").read_text()

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root2 = Path(d)
        _two_module_project(root2)
        compile_objective(str(root2), "implement-stub", apply=True)
        second = (root2 / "app" / "a.py").read_text()

    assert first == second  # no clock/random — same input, byte-identical output
    assert "raise NotImplementedError" not in first
