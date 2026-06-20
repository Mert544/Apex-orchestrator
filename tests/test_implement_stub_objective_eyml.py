"""implement-stub develop objective — make UNFINISHED code finished.

Covers: objective registration/reachability + facet route; stub detection across
shapes (NotImplementedError / ``...`` / ``pass`` / empty-with-TODO) and
idempotence on a non-stub; pinned-test discovery; each template lands real
working code from its tests (constant, passthrough, arithmetic, recursion);
REFUSAL when a stub has no tests or an unsatisfiable contract; refusal of
test/fixture files; the end-to-end gated apply that lands factorial/add and
keeps the suite green; full-suite auto-rollback on a synthetic regression; and
determinism (same project -> same body twice).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.stub_synthesis import (
    StubFunction,
    candidate_bodies,
    find_stub_functions,
    pinned_test_files,
)


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "implement-stub" in set(available_objectives())


def test_objective_spec_is_callable_and_expensive():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["implement-stub"]
    assert callable(spec.fitness) and callable(spec.moves)
    # Its fitness scan runs tests per candidate — flagged expensive so the fast
    # plan/ascend board skips it (it stays runnable explicitly).
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the default or stub implementation") == "implement-stub"


# --- stub detection (pure AST) -----------------------------------------------

def test_detects_not_implemented_raise():
    stubs = find_stub_functions("def f(a, b):\n    raise NotImplementedError\n")
    assert [s.name for s in stubs] == ["f"]
    assert stubs[0].params == ("a", "b")


def test_detects_ellipsis_and_pass_bodies():
    assert [s.name for s in find_stub_functions("def f():\n    ...\n")] == ["f"]
    assert [s.name for s in find_stub_functions("def g():\n    pass\n")] == ["g"]


def test_detects_not_implemented_called():
    stubs = find_stub_functions("def f():\n    raise NotImplementedError('soon')\n")
    assert [s.name for s in stubs] == ["f"]


def test_detects_stub_with_docstring_then_ellipsis():
    src = 'def f(n):\n    """Do it."""\n    ...\n'
    assert [s.name for s in find_stub_functions(src)] == ["f"]


def test_detects_method_drops_self_param():
    src = "class C:\n    def m(self, x):\n        raise NotImplementedError\n"
    stubs = find_stub_functions(src)
    assert len(stubs) == 1 and stubs[0].params == ("x",) and stubs[0].is_method


def test_non_stub_is_not_detected_idempotence():
    # A real body is never a stub, so the objective leaves it untouched.
    assert find_stub_functions("def f(a, b):\n    return a + b\n") == []


def test_real_body_with_todo_comment_is_not_a_stub():
    # A TODO marker only makes an EMPTY body a stub; a real statement is finished.
    src = "def f(a):\n    # TODO: implement later\n    return a * 2\n"
    assert find_stub_functions(src) == []


def test_unparseable_source_yields_no_stubs():
    assert find_stub_functions("def (:\n") == []


# --- candidate template space (fixed order, deterministic) -------------------

def test_two_arg_templates_fixed_order():
    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    labels = [lbl for lbl, _ in candidate_bodies(stub)]
    assert labels[:5] == ["+", "-", "*", "//", "%"]


def test_one_arg_templates_include_recursion_and_reductions():
    stub = StubFunction("f", ("n",), 1, 2, "", False)
    labels = [lbl for lbl, _ in candidate_bodies(stub)]
    assert "passthrough" in labels and "factorial" in labels and "len" in labels


# --- pinned-test discovery ---------------------------------------------------

def _write(root: Path, rel: str, src: str) -> None:
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")


def test_pinned_tests_link_by_import_and_name(tmp_path: Path):
    _write(tmp_path, "app/m.py", "def add(a, b):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import add\ndef test_it():\n    assert add(2, 3) == 5\n")
    _write(tmp_path, "tests/test_other.py",
           "def test_unrelated():\n    assert True\n")
    found = pinned_test_files(tmp_path, "app/m.py", "add")
    assert found == ["tests/test_m.py"]


def test_pinned_tests_empty_when_unreferenced(tmp_path: Path):
    _write(tmp_path, "app/m.py", "def add(a, b):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "def test_nothing():\n    assert True\n")
    assert pinned_test_files(tmp_path, "app/m.py", "add") == []


# --- plan layer: refusal / no-op ---------------------------------------------

def test_plan_refuses_test_file(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _write(tmp_path, "tests/test_x.py", "def f():\n    raise NotImplementedError\n")
    plan = plan_implement_stub(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_plan_noop_when_no_stub(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _write(tmp_path, "app/m.py", "def f(a, b):\n    return a + b\n")
    plan = plan_implement_stub(str(tmp_path), "app/m.py")
    assert not plan.new_contents


def test_plan_refuses_stub_with_no_tests(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A stub nothing pins — no spec to satisfy, so REFUSE (land nothing).
    _write(tmp_path, "app/m.py", "def f(a, b):\n    raise NotImplementedError\n")
    plan = plan_implement_stub(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


# --- end-to-end gated apply: real bodies land, suite stays green -------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_implements_arithmetic_stub(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "    assert add(10, 1) == 11\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    text = (tmp_path / "app" / "calc.py").read_text()
    assert "raise NotImplementedError" not in text
    assert "return a + b" in text


def test_end_to_end_implements_factorial_recursion(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "math2.py").write_text(
        "def factorial(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_math2.py").write_text(
        "from app.math2 import factorial\n"
        "def test_fac():\n"
        "    assert factorial(0) == 1\n"
        "    assert factorial(5) == 120\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    text = (tmp_path / "app" / "math2.py").read_text()
    assert "raise NotImplementedError" not in text
    # The recursion template resolves __apex_self__ to the function's own name.
    assert "factorial(n - 1)" in text


def test_end_to_end_implements_constant_stub(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "k.py").write_text(
        "def answer():\n    ...\n", encoding="utf-8")
    (tmp_path / "tests" / "test_k.py").write_text(
        "from app.k import answer\n"
        "def test_k():\n    assert answer() == 42\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    assert "return 42" in (tmp_path / "app" / "k.py").read_text()


def test_end_to_end_implements_passthrough_stub(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "p.py").write_text(
        "def echo(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_p.py").write_text(
        "from app.p import echo\n"
        "def test_p():\n    assert echo(7) == 7\n"
        "    assert echo('hi') == 'hi'\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    assert "return x" in (tmp_path / "app" / "p.py").read_text()


def test_end_to_end_refuses_unsatisfiable_stub(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "def weird(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "w.py").write_text(original, encoding="utf-8")
    # Two examples that NO fixed template (constant or binary op) satisfies:
    # 2,3 -> 7 rules out +, -, *, //, %, /, and/or; and the differing results
    # rule out a constant. REFUSE, land nothing, stay honest.
    (tmp_path / "tests" / "test_w.py").write_text(
        "from app.w import weird\n"
        "def test_w():\n    assert weird(2, 3) == 7\n"
        "    assert weird(4, 4) == 99\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (tmp_path / "app" / "w.py").read_text() == original  # untouched


def test_end_to_end_refuses_unpinned_stub(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "def lonely(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "l.py").write_text(original, encoding="utf-8")
    # No test references it at all — no spec, so refuse.
    (tmp_path / "tests" / "test_l.py").write_text(
        "def test_unrelated():\n    assert True\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps
    assert (tmp_path / "app" / "l.py").read_text() == original


# --- GAP 1: constant overfit fixed (parameter beats constant; >=2-tuple floor) -

def test_constant_is_tried_last_not_first():
    # The constant template must be the LAST resort: a parameter-shaped body that
    # also passes the pinned tests has to win over a bare literal. So the
    # constant-pinning candidate list ends (not starts) with the "constant" entry.
    import tempfile
    from pathlib import Path as _P

    from app.execution.stub_synthesis import (
        StubFunction, ordered_candidate_exprs,
    )
    with tempfile.TemporaryDirectory() as d:
        root = _P(d)
        _write(root, "tests/test_c.py",
               "def test():\n    assert const(1) == 9\n    assert const(2) == 9\n")
        stub = StubFunction("const", ("x",), 1, 2, "", False)
        labels = [lbl for lbl, _ in
                  ordered_candidate_exprs(root, ["tests/test_c.py"], stub)]
        assert "constant" in labels  # two distinct tuples agree -> it is offered
        assert labels[-1] == "constant"  # ...but only as the LAST resort
        assert labels[0] != "constant"  # a parameter template is tried first


def test_single_example_prefers_parameter_template(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # ONE pinned example, add(3, 4) == 7. The constant template would overfit to
    # `return 7`; the parameter template `a + b` ALSO passes and, tried first,
    # wins — landing the intent a human meant, not the single-test literal.
    _write(tmp_path, "app/m.py", "def add(a, b):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import add\ndef test():\n    assert add(3, 4) == 7\n")
    body = plan_implement_stub(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert body is not None
    assert "return a + b" in body
    assert "return 7" not in body  # never overfit the single example to a literal


def test_single_example_no_template_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # ONE pinned example, f(2) == 5, that NO parameter template fits (passthrough
    # gives 2, len/min/max/... don't apply to an int). A single example cannot
    # determine intent, so the >=2-distinct-tuples floor forbids the constant
    # too: REFUSE (land nothing) rather than overfit to `return 5`. This is the
    # honesty assertion — it must NOT be weakened into landing a constant.
    _write(tmp_path, "app/m.py", "def f(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import f\ndef test():\n    assert f(2) == 5\n")
    plan = plan_implement_stub(str(tmp_path), "app/m.py")
    assert not plan.new_contents  # refused: one example can't pin a constant
    assert not plan.blockers      # an honest no-op, not a failure


def test_two_distinct_tuples_constant_accepted(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # TWO DISTINCT argument tuples agree on one literal: const(1) == 9 AND
    # const(2) == 9. No parameter template yields a constant 9 from a varying
    # input, so the constant (now witnessed by >=2 inputs) legitimately lands.
    _write(tmp_path, "app/m.py", "def const(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import const\n"
           "def test():\n    assert const(1) == 9\n    assert const(2) == 9\n")
    body = plan_implement_stub(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert body is not None and "return 9" in body


def test_no_arg_single_example_constant_accepted(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A no-arg function's single empty-tuple call IS its whole input space, so
    # k() == 0 fully determines the result: the >=2-distinct-tuples floor does
    # not apply (there are no arguments to vary) and the constant lands.
    _write(tmp_path, "app/m.py", "def k():\n    ...\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import k\ndef test():\n    assert k() == 0\n")
    body = plan_implement_stub(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert body is not None and "return 0" in body


# --- GAP 2: a module's sibling stubs all land in one atomic move --------------

def test_two_stubs_one_module_separate_test_files_both_land(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # arith.py holds add + mul, each pinned by its OWN test file. The single plan
    # must implement BOTH in one write — implementing only one would be rolled
    # back because the sibling's test is still red under the impact-scoped gate.
    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def mul(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.arith import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_mul.py").write_text(
        "from app.arith import mul\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n    assert mul(4, 5) == 20\n",
        encoding="utf-8")

    plan = plan_implement_stub(str(tmp_path), "app/arith.py")
    body = plan.new_contents.get("app/arith.py")
    assert body is not None
    assert "return a + b" in body and "return a * b" in body  # BOTH landed
    assert plan.edits_by_file["app/arith.py"] == 1  # one atomic file write


def test_two_stubs_one_module_shared_test_file_both_land(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The MUTUAL deadlock: ONE test file asserts both add and mul, so neither
    # file goes green until BOTH are implemented. The batch planner must resolve
    # them together (coordinate descent) and land both.
    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def mul(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_arith.py").write_text(
        "from app.arith import add, mul\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n    assert mul(4, 5) == 20\n",
        encoding="utf-8")

    body = plan_implement_stub(str(tmp_path), "app/arith.py").new_contents.get("app/arith.py")
    assert body is not None
    assert "return a + b" in body and "return a * b" in body  # BOTH landed


def test_two_stubs_one_module_both_land_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # End-to-end: the gated apply lands BOTH stubs in one verified move and the
    # full suite stays green (no sibling-deadlock rollback).
    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def mul(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.arith import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_mul.py").write_text(
        "from app.arith import mul\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n    assert mul(4, 5) == 20\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    text = (tmp_path / "app" / "arith.py").read_text()
    assert "raise NotImplementedError" not in text  # NEITHER stub left behind
    assert "return a + b" in text and "return a * b" in text


def test_partial_module_lands_satisfiable_leaves_unsatisfiable(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # One stub is determinable (add, two examples -> a + b); the other has no
    # satisfiable template (weird's examples rule out every fixed shape). The
    # determinable one still lands; the unsatisfiable one is left as a stub.
    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def weird(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.arith import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_weird.py").write_text(
        "from app.arith import weird\n"
        "def test_weird():\n    assert weird(2, 3) == 7\n    assert weird(4, 4) == 99\n",
        encoding="utf-8")

    body = plan_implement_stub(str(tmp_path), "app/arith.py").new_contents.get("app/arith.py")
    assert body is not None
    assert "return a + b" in body            # the satisfiable stub landed...
    assert "def weird(a, b):" in body
    assert "raise NotImplementedError" in body  # ...the unsatisfiable one stays


def test_multi_stub_plan_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def mul(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.arith import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_mul.py").write_text(
        "from app.arith import mul\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n    assert mul(4, 5) == 20\n",
        encoding="utf-8")

    a = plan_implement_stub(str(tmp_path), "app/arith.py").new_contents.get("app/arith.py")
    b = plan_implement_stub(str(tmp_path), "app/arith.py").new_contents.get("app/arith.py")
    assert a == b and a is not None and "return a + b" in a and "return a * b" in a


# --- full-suite auto-rollback on a synthetic regression ----------------------

def test_full_suite_rollback_on_regression(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    # The module has the stub AND a source-line invariant an unrelated test pins.
    original = (
        "MARKER = 'present'\n\n"
        "def add(a, b):\n    raise NotImplementedError\n")
    (tmp_path / "app" / "calc.py").write_text(original, encoding="utf-8")
    # `add`'s OWN pinned test is satisfied by `a + b`, so synthesis accepts it...
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "    assert add(10, 1) == 11\n", encoding="utf-8")
    # ...but a SEPARATE suite test (which never references `add` by name, so it is
    # NOT one of the pinned tests the inner gate runs) pins a module-source
    # invariant: "this module contains no implemented return". Implementing the
    # stub breaks it, so the FULL-suite backstop must roll the file back
    # byte-for-byte — never-fake-green.
    (tmp_path / "tests" / "test_guard.py").write_text(
        "import inspect, app.calc as calc\n"
        "def test_guard():\n"
        "    assert 'return' not in inspect.getsource(calc)\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed (the full suite rejected it)
    assert (tmp_path / "app" / "calc.py").read_text() == original  # restored


# --- determinism: same project -> same body twice ----------------------------

def test_synthesis_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "    assert add(10, 1) == 11\n", encoding="utf-8")

    a = plan_implement_stub(str(tmp_path), "app/calc.py").new_contents.get("app/calc.py")
    b = plan_implement_stub(str(tmp_path), "app/calc.py").new_contents.get("app/calc.py")
    assert a == b and a is not None and "return a + b" in a


# --- WIDENED TEMPLATE SPACE: scalar / string / composite (GAP 1) -------------

def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    rel = f"app/{module}"
    return plan_implement_stub(str(tmp_path), rel).new_contents.get(rel)


def test_double_lands_scalar_multiply(tmp_path: Path):
    # The headline gap the field-tests hit: `double(n) -> n*2`. TWO witnesses
    # (3->6 AND 4->8) so it is no overfit; the value-free `n * 2` (or `n + n`)
    # template lands real working code where the old space honestly refused.
    body = _plan_body(
        tmp_path, "d.py",
        "def double(n):\n    raise NotImplementedError\n",
        "from app.d import double\n"
        "def test():\n    assert double(3) == 6\n    assert double(4) == 8\n")
    assert body is not None
    assert "return n * 2" in body or "return n + n" in body


def test_scale_lands_inferred_constant(tmp_path: Path):
    # `triple(n) -> n*3`: the multiplier k=3 is DERIVED from two consistent
    # witnesses (2->6, 5->15) and only then offered. The run gate still confirms.
    body = _plan_body(
        tmp_path, "t.py",
        "def triple(n):\n    raise NotImplementedError\n",
        "from app.t import triple\n"
        "def test():\n    assert triple(2) == 6\n    assert triple(5) == 15\n")
    assert body is not None and "return n * 3" in body


def test_is_even_lands_parity(tmp_path: Path):
    # `is_even(n) -> n % 2 == 0` from two boolean witnesses.
    body = _plan_body(
        tmp_path, "e.py",
        "def is_even(n):\n    raise NotImplementedError\n",
        "from app.e import is_even\n"
        "def test():\n    assert is_even(2) is True\n    assert is_even(3) is False\n")
    assert body is not None and "return n % 2 == 0" in body


def test_lower_lands_string_method(tmp_path: Path):
    # `shout_down(s) -> s.lower()` from a single string witness — string-method
    # chains carry no derived arithmetic, so one example is enough (gate-verified).
    body = _plan_body(
        tmp_path, "low.py",
        "def shout_down(s):\n    raise NotImplementedError\n",
        "from app.low import shout_down\n"
        "def test():\n    assert shout_down('HELLO') == 'hello'\n")
    assert body is not None and "return s.lower()" in body


def test_slugify_lands_lower_replace(tmp_path: Path):
    # The buyer moment: `slugify(s) -> s.lower().replace(' ', '-')`. The ' ' and
    # '-' constants are structurally present in the witness, so one example lands.
    body = _plan_body(
        tmp_path, "slug.py",
        "def slugify(s):\n    raise NotImplementedError\n",
        "from app.slug import slugify\n"
        "def test():\n    assert slugify('Hello World') == 'hello-world'\n")
    assert body is not None
    assert ".lower().replace(' ', '-')" in body


def test_mean_lands_composite(tmp_path: Path):
    # `mean(xs) -> sum(xs) / len(xs)` — a composite reduction the old space could
    # not express. Two witnesses keep it honest.
    body = _plan_body(
        tmp_path, "avg.py",
        "def mean(xs):\n    raise NotImplementedError\n",
        "from app.avg import mean\n"
        "def test():\n    assert mean([1, 2, 3]) == 2\n    assert mean([2, 4]) == 3\n")
    assert body is not None and "return sum(xs) / len(xs)" in body


def test_join_lands_two_arg(tmp_path: Path):
    # `join_with(sep, xs) -> sep.join(xs)` — the new two-arg `a.join(b)` shape.
    body = _plan_body(
        tmp_path, "j.py",
        "def join_with(sep, xs):\n    raise NotImplementedError\n",
        "from app.j import join_with\n"
        "def test():\n    assert join_with('-', ['a', 'b']) == 'a-b'\n")
    assert body is not None and "return sep.join(xs)" in body


def test_less_than_lands_comparison(tmp_path: Path):
    # `lt(a, b) -> a < b` — the new two-arg comparison shape.
    body = _plan_body(
        tmp_path, "lt.py",
        "def lt(a, b):\n    raise NotImplementedError\n",
        "from app.lt import lt\n"
        "def test():\n    assert lt(1, 2) is True\n    assert lt(5, 3) is False\n")
    assert body is not None and "return a < b" in body


def test_abs_lands_for_negative(tmp_path: Path):
    # `mag(n) -> abs(n)`: passthrough fails (-3 != 3), abs is reached and lands.
    body = _plan_body(
        tmp_path, "ab.py",
        "def mag(n):\n    raise NotImplementedError\n",
        "from app.ab import mag\n"
        "def test():\n    assert mag(-3) == 3\n    assert mag(4) == 4\n")
    assert body is not None and "return abs(n)" in body


# --- GAP 1 honesty: recursion needs >=2 distinct witnesses -------------------

def test_single_witness_does_not_land_recursion(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The red-team case: `double(3) == 6` as a LONE witness. factorial(3) == 6
    # too, so the old space could land a factorial body off one example. The
    # >=2-witness floor forbids recursion here; a value-free shape (`n * 2`) that
    # also passes may land, but NEVER the overfit factorial/fibonacci recursion.
    _suite_project(tmp_path)
    (tmp_path / "app" / "d.py").write_text(
        "def double(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "from app.d import double\n"
        "def test():\n    assert double(3) == 6\n", encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/d.py").new_contents.get("app/d.py")
    # Whatever lands (or nothing), it must not be a recursion body.
    if body is not None:
        assert "double(n - 1)" not in body and "double(n - 2)" not in body


def test_recursion_offered_only_with_two_witnesses():
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("n",), 1, 2, "", False)
    one = [("3", "6")]
    two = [("0", "1"), ("5", "120")]
    labels_one = [lbl for lbl, _ in candidate_bodies(stub, one)]
    labels_two = [lbl for lbl, _ in candidate_bodies(stub, two)]
    assert "factorial" not in labels_one  # a single witness withholds recursion
    assert "factorial" in labels_two      # two distinct witnesses allow it


def test_derived_constant_needs_two_consistent_witnesses():
    from app.execution.stub_synthesis import _numeric_constants

    # One example f(2)==5 must NOT derive k=3 (it would overfit to n+3)...
    assert "3" not in _numeric_constants([("2", "5")])
    # ...but two consistent examples (n+3) legitimately derive k=3.
    assert "3" in _numeric_constants([("2", "5"), ("10", "13")])
    # An inconsistent pair (5-2=3 but 99-10=89) derives no offset.
    assert "3" not in _numeric_constants([("2", "5"), ("10", "99")])


# --- GAP 2: mutual stubs land via INDEPENDENT per-witness synthesis -----------

def test_total_and_maximum_shared_file_both_land(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The field-test P0: total + maximum share ONE test file, needing DIFFERENT
    # bodies. The old coordinate-descent-from-passthrough deadlocked (no single
    # move greens the shared file); independent per-witness synthesis lands BOTH.
    _suite_project(tmp_path)
    (tmp_path / "app" / "agg.py").write_text(
        "def total(xs):\n    raise NotImplementedError\n\n\n"
        "def maximum(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_agg.py").write_text(
        "from app.agg import total, maximum\n"
        "def test_total():\n    assert total([1, 2, 3]) == 6\n    assert total([4]) == 4\n"
        "def test_max():\n    assert maximum([1, 5, 2]) == 5\n    assert maximum([7, 3]) == 7\n",
        encoding="utf-8")

    body = plan_implement_stub(str(tmp_path), "app/agg.py").new_contents.get("app/agg.py")
    assert body is not None
    assert "return sum(xs)" in body and "return max(xs)" in body  # BOTH landed


def test_total_and_maximum_shared_file_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "agg.py").write_text(
        "def total(xs):\n    raise NotImplementedError\n\n\n"
        "def maximum(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_agg.py").write_text(
        "from app.agg import total, maximum\n"
        "def test_total():\n    assert total([1, 2, 3]) == 6\n    assert total([4]) == 4\n"
        "def test_max():\n    assert maximum([1, 5, 2]) == 5\n    assert maximum([7, 3]) == 7\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    text = (tmp_path / "app" / "agg.py").read_text()
    assert "raise NotImplementedError" not in text
    assert "return sum(xs)" in text and "return max(xs)" in text


def test_add_and_mul_shared_file_independent_synthesis(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # add + mul share one file and need a + b vs a * b — the canonical mutual case
    # the independent synthesis must resolve (the union passes only when BOTH are
    # filled with their own bodies).
    _suite_project(tmp_path)
    (tmp_path / "app" / "arith.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def mul(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_arith.py").write_text(
        "from app.arith import add, mul\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n    assert mul(4, 5) == 20\n",
        encoding="utf-8")

    body = plan_implement_stub(str(tmp_path), "app/arith.py").new_contents.get("app/arith.py")
    assert body is not None
    assert "return a + b" in body and "return a * b" in body


# --- refusal cases held under the wider space --------------------------------

def test_contradictory_witnesses_refuse(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # double(3)==6 but double(4)==99: no scalar/parity/comparison/recursion shape
    # fits both, and the literals disagree so no constant. REFUSE (honest no-op).
    _suite_project(tmp_path)
    original = "def f(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "c.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_c.py").write_text(
        "from app.c import f\n"
        "def test():\n    assert f(3) == 6\n    assert f(4) == 99\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/c.py")
    assert not plan.new_contents and not plan.blockers


def test_wider_space_is_deterministic(tmp_path: Path):
    body1 = _plan_body(
        tmp_path, "s.py",
        "def slugify(s):\n    raise NotImplementedError\n",
        "from app.s import slugify\n"
        "def test():\n    assert slugify('Hello World') == 'hello-world'\n")
    # Second independent project, identical inputs -> identical body.
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(
            _P(d), "s.py",
            "def slugify(s):\n    raise NotImplementedError\n",
            "from app.s import slugify\n"
            "def test():\n    assert slugify('Hello World') == 'hello-world'\n")
    assert body1 == body2 and body1 is not None


# --- DEFECT 1: xfail/skip witnesses pin NO enforceable contract --------------

def test_xfail_only_contract_is_refused(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The field-test P0: slugify's ONLY test is @pytest.mark.xfail. An xfail
    # assertion is ALLOWED to fail, so it pins no enforceable contract — the
    # suite stays green for ANY body. The old path landed `return text`
    # (identity, WRONG) and stamped it "verified". With xfail witnesses excluded
    # and the enforceable-contract floor, we REFUSE: land nothing.
    _suite_project(tmp_path)
    original = "def slugify(text):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "slug.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_slug.py").write_text(
        "import pytest\nfrom app.slug import slugify\n"
        "@pytest.mark.xfail\n"
        "def test_slug():\n    assert slugify('Hello World') == 'hello-world'\n",
        encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/slug.py")
    assert not plan.new_contents and not plan.blockers  # refused, nothing landed
    assert (tmp_path / "app" / "slug.py").read_text() == original  # untouched


def test_xfail_only_contract_refused_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # End-to-end proof the identity body never lands: even though `return text`
    # would keep the (xfail) suite green, the objective refuses outright.
    _suite_project(tmp_path)
    original = "def slugify(text):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "slug.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_slug.py").write_text(
        "import pytest\nfrom app.slug import slugify\n"
        "@pytest.mark.xfail\n"
        "def test_slug():\n    assert slugify('Hello World') == 'hello-world'\n",
        encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (tmp_path / "app" / "slug.py").read_text() == original  # untouched


def test_skip_only_contract_is_refused(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # @pytest.mark.skip never runs, so it enforces nothing either — refuse.
    _suite_project(tmp_path)
    original = "def double(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "d.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "import pytest\nfrom app.d import double\n"
        "@pytest.mark.skip\n"
        "def test_d():\n    assert double(3) == 6\n    assert double(4) == 8\n",
        encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/d.py")
    assert not plan.new_contents and not plan.blockers


def test_skipif_only_contract_is_refused(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # @pytest.mark.skipif likewise may not run — no enforced contract.
    _suite_project(tmp_path)
    original = "def double(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "d.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "import pytest\nfrom app.d import double\n"
        "@pytest.mark.skipif(True, reason='x')\n"
        "def test_d():\n    assert double(3) == 6\n    assert double(4) == 8\n",
        encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/d.py")
    assert not plan.new_contents and not plan.blockers


def test_xfail_witness_excluded_real_test_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A poison xfail assertion (double(0)==999, deliberately wrong) sits beside a
    # REAL enforcing test. The xfail witness must be EXCLUDED (so it can't break
    # synthesis), and the real contract must still land `n * 2`.
    _suite_project(tmp_path)
    (tmp_path / "app" / "d.py").write_text(
        "def double(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "import pytest\nfrom app.d import double\n"
        "@pytest.mark.xfail\n"
        "def test_future():\n    assert double(0) == 999\n"
        "def test_real():\n    assert double(3) == 6\n    assert double(4) == 8\n",
        encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/d.py").new_contents.get("app/d.py")
    assert body is not None
    assert "return n * 2" in body or "return n + n" in body
    assert "999" not in body  # the xfail's bogus literal never reaches synthesis


def test_function_witnesses_exclude_xfail(tmp_path: Path):
    from app.execution.stub_synthesis import StubFunction, _function_witnesses

    # Direct check on the extractor: only the enforced witness is mined.
    _write(tmp_path, "tests/test_w.py",
           "import pytest\n"
           "@pytest.mark.xfail\n"
           "def test_a():\n    assert f(1) == 99\n"
           "def test_b():\n    assert f(2) == 4\n")
    stub = StubFunction("f", ("n",), 1, 2, "", False)
    wits = _function_witnesses(tmp_path, ["tests/test_w.py"], stub)
    assert wits == [("2", "4")]  # the xfail witness (1, 99) is dropped


# --- DEFECT 2: ambiguity guard + value-free-after-derived reorder ------------

def test_thin_ambiguous_contract_is_refused(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The red-team repro: is_big intent is `n >= 100`, but the only witnesses are
    # is_big(5)==False and is_big(200)==True. BOTH `n % 2 == 0` (parity) and a
    # threshold (`n >= 200` / `n > 5`) pass those two points yet DISAGREE on
    # is_big(50)/is_big(99). The witnesses don't determine intent, so REFUSE
    # rather than stamp an arbitrary body verified.
    _suite_project(tmp_path)
    original = "def is_big(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "b.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "from app.b import is_big\n"
        "def test():\n    assert is_big(5) == False\n    assert is_big(200) == True\n",
        encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/b.py")
    assert not plan.new_contents and not plan.blockers  # ambiguity -> honest no-op
    assert (tmp_path / "app" / "b.py").read_text() == original


def test_ambiguous_contract_refused_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # End-to-end: the parity body `n % 2 == 0` (wrong for is_big(50)) must NOT
    # land even though it passes the two thin witnesses — the guard refuses.
    _suite_project(tmp_path)
    original = "def is_big(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "b.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "from app.b import is_big\n"
        "def test():\n    assert is_big(5) == False\n    assert is_big(200) == True\n",
        encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps
    assert (tmp_path / "app" / "b.py").read_text() == original


def test_unambiguous_parity_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A GENUINE parity contract: is_even(2)==True, is_even(3)==False,
    # is_even(4)==True. No `n OP k` comparison can produce True,False,True (a
    # comparison is monotonic), so parity is the ONLY shape that fits — not
    # ambiguous — and `n % 2 == 0` still lands.
    _suite_project(tmp_path)
    (tmp_path / "app" / "e.py").write_text(
        "def is_even(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_e.py").write_text(
        "from app.e import is_even\n"
        "def test():\n"
        "    assert is_even(2) == True\n"
        "    assert is_even(3) == False\n"
        "    assert is_even(4) == True\n", encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/e.py").new_contents.get("app/e.py")
    assert body is not None and "return n % 2 == 0" in body


def test_equivalent_shapes_are_not_ambiguous(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # `n * 2` and `n + n` both pass double(3)==6, double(4)==8 but compute the
    # SAME function everywhere — that is NOT a harmful ambiguity, so the guard
    # must NOT refuse. A doubling body still lands.
    _suite_project(tmp_path)
    (tmp_path / "app" / "d.py").write_text(
        "def double(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_d.py").write_text(
        "from app.d import double\n"
        "def test():\n    assert double(3) == 6\n    assert double(4) == 8\n",
        encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/d.py").new_contents.get("app/d.py")
    assert body is not None
    assert "return n * 2" in body or "return n + n" in body


def test_witness_derived_comparison_ordered_before_parity():
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    # DEFECT-2 reorder: when a numeric constant is inferable, the witness-derived
    # comparison/arithmetic shapes (`n>=k`, `n==k`, `n*k`...) must precede the
    # value-free parity / `n*2` so an intent-shaped body wins when both fit.
    stub = StubFunction("f", ("n",), 1, 2, "", False)
    witnesses = [("5", "1"), ("200", "1")]  # ints present -> k in {1, 5, 200}
    labels = [lbl for lbl, _ in candidate_bodies(stub, witnesses)]
    assert "even" in labels and "n>=5" in labels
    assert labels.index("n>=5") < labels.index("even")   # derived before parity
    assert labels.index("n*5") < labels.index("n*2")     # derived before n*2


def test_ambiguity_guard_does_not_break_clear_arithmetic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # triple(2)==6, triple(5)==15: only `n * 3` fits (n*2/n+n give 4,10), so it is
    # unambiguous and lands — the guard must not over-refuse a determined intent.
    _suite_project(tmp_path)
    (tmp_path / "app" / "t.py").write_text(
        "def triple(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_t.py").write_text(
        "from app.t import triple\n"
        "def test():\n    assert triple(2) == 6\n    assert triple(5) == 15\n",
        encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/t.py").new_contents.get("app/t.py")
    assert body is not None and "return n * 3" in body


# --- DEFECT 3: a no-positional-param METHOD is NOT a genuine no-arg function ---

def test_zero_param_method_single_example_refuses_constant(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The field-test P0: a METHOD with no positional params (``self`` dropped, so
    # ``params == ()``) whose result depends on instance state. ONE example
    # ``Record(1, "abcd").width() == 4`` must NOT pin ``return 4`` — a second
    # instance ``Record(2, "hello world!!").width()`` would expect 13. The no-arg
    # constant exemption (one empty tuple IS the whole input space) is for a
    # GENUINE module-level no-arg function only; a method's output varies with
    # ``self``, and the positional templates cannot read it, so REFUSE.
    _suite_project(tmp_path)
    original = (
        "class Record:\n"
        "    def __init__(self, id, payload):\n"
        "        self.id = id\n"
        "        self.payload = payload\n\n"
        "    def width(self):\n        raise NotImplementedError\n")
    (tmp_path / "app" / "r.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_r.py").write_text(
        "from app.r import Record\n"
        "def test_w():\n    assert Record(1, 'abcd').width() == 4\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/r.py")
    body = plan.new_contents.get("app/r.py")
    assert body is None  # refused: one example can't pin a self-dependent constant
    assert "return 4" not in (tmp_path / "app" / "r.py").read_text()
    assert (tmp_path / "app" / "r.py").read_text() == original  # untouched
    assert not plan.blockers  # an honest no-op, not a failure


def test_zero_param_method_single_example_refused_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # End-to-end proof the self-state overfit never lands: even though the suite
    # (one example) would go green on ``return 4``, the objective refuses outright.
    _suite_project(tmp_path)
    original = (
        "class Record:\n"
        "    def __init__(self, id, payload):\n"
        "        self.id = id\n"
        "        self.payload = payload\n\n"
        "    def width(self):\n        raise NotImplementedError\n")
    (tmp_path / "app" / "r.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_r.py").write_text(
        "from app.r import Record\n"
        "def test_w():\n    assert Record(1, 'abcd').width() == 4\n", encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (tmp_path / "app" / "r.py").read_text() == original  # untouched


def test_expected_constant_gates_method_on_is_method(tmp_path: Path):
    from app.execution.stub_synthesis import StubFunction, _expected_constant

    # Direct check on the gate: a METHOD (``is_method=True``) with no positional
    # params and ONE witness yields no constant — the >=2-distinct-tuples floor
    # still applies because ``self`` makes a method NOT a genuine no-arg function.
    _write(tmp_path, "tests/test_r.py",
           "from app.r import Record\n"
           "def test_w():\n    assert Record(1, 'abcd').width() == 4\n")
    method = StubFunction("width", (), 1, 2, "    ", True)
    assert _expected_constant(tmp_path, ["tests/test_r.py"], method) is None


def test_no_arg_module_function_keeps_single_example_exemption(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The exemption survives for a GENUINE module-level no-arg function: its single
    # empty-tuple call IS the whole input space (no ``self``, no args to vary), so
    # ``answer() == 42`` still legitimately lands ``return 42``. The fix must not
    # regress this honest single-example landing.
    _suite_project(tmp_path)
    (tmp_path / "app" / "ans.py").write_text(
        "def answer():\n    ...\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ans.py").write_text(
        "from app.ans import answer\n"
        "def test_a():\n    assert answer() == 42\n", encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/ans.py").new_contents.get("app/ans.py")
    assert body is not None and "return 42" in body


def test_expected_constant_module_no_arg_single_example_lands(tmp_path: Path):
    from app.execution.stub_synthesis import StubFunction, _expected_constant

    # The gate's other side: a module no-arg function (``is_method=False``,
    # ``params=()``) with one witness DOES yield the constant — the exemption.
    _write(tmp_path, "tests/test_ans.py",
           "from app.ans import answer\n"
           "def test_a():\n    assert answer() == 42\n")
    fn = StubFunction("answer", (), 1, 2, "", False)
    assert _expected_constant(tmp_path, ["tests/test_ans.py"], fn) == "42"


def test_zero_param_method_constant_gating_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # Same method + single example twice -> identically refused (no constant). The
    # gate adds no time/random; the refusal is stable across runs.
    _suite_project(tmp_path)
    original = (
        "class Record:\n"
        "    def __init__(self, id, payload):\n"
        "        self.payload = payload\n\n"
        "    def width(self):\n        raise NotImplementedError\n")
    (tmp_path / "app" / "r.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_r.py").write_text(
        "from app.r import Record\n"
        "def test_w():\n    assert Record(1, 'abcd').width() == 4\n", encoding="utf-8")
    a = plan_implement_stub(str(tmp_path), "app/r.py").new_contents.get("app/r.py")
    b = plan_implement_stub(str(tmp_path), "app/r.py").new_contents.get("app/r.py")
    assert a is None and b is None and a == b
