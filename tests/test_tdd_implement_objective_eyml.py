"""tdd-implement develop objective — write the function a RED test calls.

The everyday TDD inner loop a budget-limited student/team otherwise pays an LLM
for: "I wrote the test — now write the code." Given a FAILING test that calls a
function that does NOT EXIST YET, this objective synthesises a real ``def foo``
in the correct module so the RED test goes GREEN, landing working code only when
the full suite verifies it.

Covers: registration / reachability + facet route; the
detect→locate→infer→insert→synthesise→gate pipeline; each missing-symbol shape
(ImportError / AttributeError / NameError / arity TypeError); signature inference
(positional arity + keyword names); REFUSAL of an unprovable single example, of
an assertion failure on existing code (out of scope), and of a test/fixture file
as a write target; the end-to-end gated apply that lands ``add`` and keeps the
suite green; full-suite auto-rollback; determinism; and idempotence
(already-green -> no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.tdd_implement import (
    MissingSymbol,
    _attributed_names,
    _infer_signature,
    _insert_stub,
    detect_missing_symbols,
    plan_tdd_implement,
)


# --- project fixtures --------------------------------------------------------

def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _red_project(root: Path, module: str, module_src: str, test_src: str) -> None:
    """A project whose target ``module`` is missing the function the test calls."""
    _write(root, module, module_src)
    _write(root, "tests/test_target.py", test_src)


def _add_project(root: Path) -> None:
    """The canonical demo: ``mymath.add`` does not exist; the RED test pins it
    with TWO examples so a parameter template (``a + b``), not a constant, wins."""
    _red_project(
        root, "mymath.py",
        '"""tiny math module"""\n\n\ndef double(x):\n    return x * 2\n',
        "from mymath import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
    )


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "tdd-implement" in set(available_objectives())


def test_objective_spec_is_callable_and_expensive():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["tdd-implement"]
    assert callable(spec.fitness) and callable(spec.moves)
    # Detection runs the full suite then probes templates — flagged expensive so
    # the fast plan/ascend board skips it (it stays runnable explicitly).
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the function the red test calls") == "tdd-implement"


def test_facet_map_invariant_holds_for_this_objective():
    """tdd-implement appears on BOTH sides of the facet/objective coherence: it is
    a registered objective AND a facet routes to it."""
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert "tdd-implement" in set(available_objectives())
    assert "tdd-implement" in set(FACET_OBJECTIVE_MAP.values())


# --- detection: each missing-symbol shape ------------------------------------

def test_attributed_names_recognises_each_shape():
    out = _attributed_names(
        "AttributeError: module 'x' has no attribute 'foo'\n"
        "NameError: name 'bar' is not defined\n"
        "ImportError: cannot import name 'baz'\n"
        "TypeError: qux() takes 1 positional argument but 2 were given\n"
    )
    assert out == [("foo", "attribute"), ("bar", "name"),
                   ("baz", "import"), ("qux", "arity")]


def test_attributed_names_ignores_assertion_failures():
    """A plain assertion failure on existing code is NOT a missing symbol."""
    assert _attributed_names("assert add(2, 3) == 5\nAssertionError\n") == []


def test_detect_import_error_shape(tmp_path):
    _add_project(tmp_path)
    found = detect_missing_symbols(tmp_path)
    assert [(m.name, m.shape, m.module_rel) for m in found] == [
        ("add", "import", "mymath.py")]


def test_detect_attribute_error_shape(tmp_path):
    _red_project(
        tmp_path, "geo.py", '"""geo"""\n',
        "import geo\n\n\ndef test_area():\n"
        "    assert geo.area(2, 3) == 5\n    assert geo.area(10, 1) == 11\n",
    )
    found = detect_missing_symbols(tmp_path)
    assert [(m.name, m.shape) for m in found] == [("area", "attribute")]


def test_detect_name_error_shape(tmp_path):
    # `from util import scale` raises ImportError on collection; to exercise the
    # NameError branch directly, the function is referenced bare inside the test.
    out = _attributed_names("NameError: name 'scale' is not defined")
    assert out == [("scale", "name")]


# --- signature inference -----------------------------------------------------

def test_infer_signature_positional_arity(tmp_path):
    _write(tmp_path, "tests/test_t.py",
           "from m import f\n\n\ndef test_f():\n    assert f(1, 2, 3) == 6\n")
    assert _infer_signature(tmp_path, "f", ("tests/test_t.py",)) == "a0, a1, a2"


def test_infer_signature_keyword_names(tmp_path):
    _write(tmp_path, "tests/test_t.py",
           "from m import g\n\n\ndef test_g():\n    assert g(1, key=2) == 3\n")
    assert _infer_signature(tmp_path, "g", ("tests/test_t.py",)) == "a0, *, key"


def test_infer_signature_no_call_site_is_none(tmp_path):
    _write(tmp_path, "tests/test_t.py", "def test_nothing():\n    assert True\n")
    assert _infer_signature(tmp_path, "absent", ("tests/test_t.py",)) is None


# --- insertion ---------------------------------------------------------------

def test_insert_stub_appends_a_parseable_def():
    out = _insert_stub("def existing():\n    return 1\n", "foo", "a0, a1")
    assert out is not None
    assert "def foo(a0, a1):" in out
    assert "raise NotImplementedError" in out
    # the original definition is untouched (appended only)
    assert out.startswith("def existing():\n    return 1\n")


def test_insert_stub_into_empty_module():
    out = _insert_stub("", "foo", "")
    assert out is not None and "def foo():" in out


# --- the headline: a missing function is created from a RED test -------------

def test_creates_missing_function_and_test_goes_green(tmp_path):
    _add_project(tmp_path)
    missing = detect_missing_symbols(tmp_path)[0]
    plan = plan_tdd_implement(tmp_path, missing)
    assert plan.new_contents, "a fixed template should satisfy add(2,3)==5 & (10,1)==11"
    landed = plan.new_contents["mymath.py"]
    # the parameter template wins over a constant (two distinct tuples)
    assert "def add(a0, a1):" in landed
    assert "return a0 + a1" in landed


def test_end_to_end_gated_apply_lands_and_keeps_suite_green(tmp_path):
    _add_project(tmp_path)
    missing = detect_missing_symbols(tmp_path)[0]
    plan = plan_tdd_implement(tmp_path, missing)
    result = apply_rename(tmp_path, plan)
    assert result.get("verified") is True
    assert result.get("rolled_back") is False
    # the function actually landed on disk and the suite is now green
    assert "def add(" in (tmp_path / "mymath.py").read_text(encoding="utf-8")


# --- refusals (honest, never-fake-green) -------------------------------------

def test_refuses_unprovable_single_example(tmp_path):
    """ONE example ``mystery(3, 4) == 99`` cannot be proven by any parameter
    template, and the constant guard needs two distinct tuples — so nothing
    lands."""
    _red_project(
        tmp_path, "mymod.py", "def existing():\n    return 1\n",
        "from mymod import mystery\n\n\n"
        "def test_one():\n    assert mystery(3, 4) == 99\n",
    )
    found = detect_missing_symbols(tmp_path)
    assert [m.name for m in found] == ["mystery"]  # detected...
    plan = plan_tdd_implement(tmp_path, found[0])
    assert not plan.new_contents  # ...but refused: no template proves it


def test_refuses_assertion_failure_on_existing_code(tmp_path):
    """An assertion failure on an EXISTING function is out of scope — it is not a
    missing symbol, so detection yields nothing (we never touch existing logic)."""
    _red_project(
        tmp_path, "calc.py", "def add(a, b):\n    return a - b\n",
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    assert detect_missing_symbols(tmp_path) == []


def test_refuses_writing_into_a_test_file(tmp_path):
    """A test/fixture path is REFUSED as a write target — Apex writes the module
    under test, never the test it is gated by."""
    ms = MissingSymbol(name="foo", module_rel="tests/test_target.py",
                       test_files=("tests/test_target.py",), shape="import")
    plan = plan_tdd_implement(tmp_path, ms)
    assert not plan.new_contents


# --- full-suite auto-rollback ------------------------------------------------

def test_full_suite_rollback_restores_on_regression(tmp_path):
    """A second, ALREADY-GREEN test that the new function would break forces the
    full-suite gate to roll the change back byte-for-byte. We synthesise that by
    pinning a contradictory second test on the same symbol so no single body
    satisfies both — the gate must reject and restore the original file."""
    _write(tmp_path, "mymath.py",
           '"""m"""\n\n\ndef double(x):\n    return x * 2\n')
    # Two tests on `add` whose examples no fixed template can BOTH satisfy.
    _write(tmp_path, "tests/test_a.py",
           "from mymath import add\n\n\n"
           "def test_a():\n    assert add(2, 3) == 5\n    assert add(1, 1) == 2\n")
    _write(tmp_path, "tests/test_b.py",
           "from mymath import add\n\n\n"
           "def test_b():\n    assert add(2, 3) == 99\n    assert add(1, 1) == 99\n")
    original = (tmp_path / "mymath.py").read_text(encoding="utf-8")
    found = detect_missing_symbols(tmp_path)
    # Either no template proves the union (empty plan), or a plan is rolled back
    # by the gate; both outcomes leave the module byte-for-byte unchanged.
    for ms in found:
        plan = plan_tdd_implement(tmp_path, ms)
        if plan.new_contents:
            result = apply_rename(tmp_path, plan)
            assert result.get("rolled_back") is not False or result.get("verified")
    assert (tmp_path / "mymath.py").read_text(encoding="utf-8") == original


# --- determinism + idempotence -----------------------------------------------

def test_determinism_same_project_same_body(tmp_path):
    bodies = []
    for sub in ("run1", "run2"):
        root = tmp_path / sub
        _add_project(root)
        missing = detect_missing_symbols(root)[0]
        plan = plan_tdd_implement(root, missing)
        bodies.append(plan.new_contents["mymath.py"])
    assert bodies[0] == bodies[1]  # byte-for-byte identical across runs


def test_idempotent_already_green_is_noop(tmp_path):
    """A project whose function ALREADY exists (suite green) yields no missing
    symbol — nothing to do."""
    _write(tmp_path, "mymath.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/test_target.py",
           "from mymath import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    assert detect_missing_symbols(tmp_path) == []


def test_fitness_counts_implementable_missing_symbols(tmp_path):
    from app.engine.develop_registry import registered_specs

    _add_project(tmp_path)
    spec = registered_specs()["tdd-implement"]
    assert spec.fitness(tmp_path) == 1.0


def test_moves_offers_one_move_per_missing_symbol(tmp_path):
    from app.engine.develop_registry import registered_specs

    _add_project(tmp_path)
    spec = registered_specs()["tdd-implement"]
    moves = spec.moves(tmp_path)
    assert len(moves) == 1
    assert moves[0].operator == "tdd_implement"
    assert "add" in moves[0].target
