"""infer-type-hints develop objective — land PROVABLE type annotations.

Covers: objective registration/reachability, that the transform lands provable
return + default-param hints, skips every ambiguous shape, refuses test/fixture
files, auto-rolls-back a suite-breaking case, is deterministic across two runs,
and strictly increases measured type-hint coverage.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.semantic.transforms.type_annotations import (
    infer_annotations,
    plan_type_annotations,
)


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "infer-type-hints" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["infer-type-hints"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    # A facet phrase must route to it, else `apex objectives` shows it as
    # unreachable and the facet/objective integrity test fails.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the precise type or annotation") == "infer-type-hints"


# --- provable inference (pure transform) -------------------------------------

def test_infers_return_from_agreeing_literal_returns():
    out = infer_annotations("def f():\n    return 1\n")
    assert out == "def f() -> int:\n    return 1\n"


def test_infers_none_return_for_pure_procedure():
    out = infer_annotations("def f():\n    print('x')\n")
    assert out == "def f() -> None:\n    print('x')\n"


def test_infers_bool_before_int():
    out = infer_annotations("def f():\n    return True\n")
    assert "-> bool:" in out and "-> int:" not in out


def test_infers_param_from_literal_default():
    out = infer_annotations("def f(x=0):\n    return x\n")
    assert out is not None and "x: int=0" in out


def test_infers_each_literal_kind():
    cases = {
        "return 's'": "-> str:",
        "return 1.5": "-> float:",
        "return b'a'": "-> bytes:",
        "return [1]": "-> list:",
        "return {1: 2}": "-> dict:",
        "return {1}": "-> set:",
        "return (1, 2)": "-> tuple:",
    }
    for body, expect in cases.items():
        out = infer_annotations(f"def f():\n    {body}\n")
        assert out is not None and expect in out, body


def test_infers_keyword_only_default():
    out = infer_annotations("def f(*, n=3):\n    return n\n")
    assert out is not None and "n: int=3" in out


# --- ambiguity is always skipped (never a guess) -----------------------------

def test_skips_non_literal_return():
    assert infer_annotations("def f(a, b):\n    return a + b\n") is None


def test_skips_mixed_literal_return_types():
    src = "def f(c):\n    if c:\n        return 1\n    return 'x'\n"
    assert infer_annotations(src) is None


def test_skips_bare_return_mixed_with_value_return():
    src = "def f(c):\n    if c:\n        return 1\n    return\n"
    assert infer_annotations(src) is None


def test_skips_none_default_param():
    # None default is Optional[...] — ambiguous, so the param is left alone.
    out = infer_annotations("def f(x=None):\n    return x\n")
    # x stays unannotated; return is non-literal -> nothing provable at all.
    assert out is None


def test_skips_fall_through_value_return():
    # `status_code(False)` reaches the end -> returns None, so the true type is
    # `int | None`, NOT `int`. A bare `-> int` would be a WRONG landing that no
    # runtime test catches (annotations change no values) -> refuse.
    src = "def status_code(ok):\n    if ok:\n        return 200\n"
    out = infer_annotations(src)
    assert out is None or "-> int" not in out


def test_skips_value_return_in_for_loop():
    # A `for` may run zero times -> falls through to an implicit `return None`.
    # The return is a LITERAL (so only the fall-through guard can refuse it).
    src = "def first(xs):\n    for x in xs:\n        return 1\n"
    out = infer_annotations(src)
    assert out is None or "-> int" not in out


def test_skips_value_return_in_while_loop():
    # A non-`while True` loop can complete normally -> fall-through.
    src = "def f(n):\n    while n:\n        return 1\n"
    out = infer_annotations(src)
    assert out is None or "-> int" not in out


def test_infers_when_if_else_both_terminate():
    # Every path returns a literal of the SAME type and the body provably can NOT
    # fall through (the `else` returns too) -> the inference is sound.
    src = "def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n"
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


def test_infers_when_value_return_is_unconditional_tail():
    # The value return is the last statement and always reached -> sound.
    out = infer_annotations("def f(x):\n    x += 1\n    return 1\n")
    assert out is not None and "-> int:" in out


def test_infers_when_while_true_with_no_break_returns():
    # `while True:` with no `break` never completes normally -> the inner return
    # always fires; the body provably terminates.
    src = "def f():\n    while True:\n        return 1\n"
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


def test_skips_while_true_with_break_then_value_return():
    # A reachable `break` lets the loop complete -> the trailing path may be a
    # fall-through, so the bare value-return is no longer guaranteed-reached.
    src = (
        "def f():\n"
        "    while True:\n"
        "        if cond():\n"
        "            break\n"
        "    return 1\n"
    )
    # The tail `return 1` is reached, so this one IS sound -> may infer int.
    out = infer_annotations(src)
    assert out is None or "-> int:" in out


def test_skips_generator():
    assert infer_annotations("def f():\n    yield 1\n") is None


def test_skips_already_annotated_return():
    src = "def f() -> str:\n    return 1\n"
    assert infer_annotations(src) is None


def test_skips_already_annotated_param():
    # param already typed; return non-literal -> nothing to do.
    assert infer_annotations("def f(x: int = 0):\n    return x\n") is None


def test_skips_varargs_and_kwargs():
    src = "def f(*args, **kwargs):\n    return len(args)\n"
    # *args/**kwargs are never inferred; the return is non-literal -> no change.
    assert infer_annotations(src) is None


def test_nested_function_returns_are_not_borrowed():
    # The outer function's own returns are non-literal; the inner literal return
    # must not leak up to annotate the outer one.
    src = (
        "def outer(a):\n"
        "    def inner():\n"
        "        return 1\n"
        "    return a\n"
    )
    out = infer_annotations(src)
    # inner gets -> int; outer stays unannotated (its return is non-literal).
    assert out is not None
    assert "def inner() -> int:" in out
    assert "def outer(a):" in out  # outer header unchanged


# --- plan layer: refusal, no-op, determinism ---------------------------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_lands_provable_hints(tmp_path: Path):
    _project(tmp_path, "app/m.py", "def f():\n    return 1\n")
    plan = plan_type_annotations(str(tmp_path), "app/m.py")
    assert plan.new_contents["app/m.py"] == "def f() -> int:\n    return 1\n"
    assert not plan.blockers


def test_plan_refuses_test_file(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", "def f():\n    return 1\n")
    plan = plan_type_annotations(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents  # refused — empty no-op plan
    assert not plan.blockers


def test_plan_refuses_fixture_file(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", "def f():\n    return 1\n")
    plan = plan_type_annotations(str(tmp_path), "fixtures/sample.py")
    assert not plan.new_contents


def test_plan_is_noop_when_nothing_provable(tmp_path: Path):
    _project(tmp_path, "app/m.py", "def f(a, b):\n    return a + b\n")
    plan = plan_type_annotations(str(tmp_path), "app/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic_across_two_runs(tmp_path: Path):
    src = "def f(x=0):\n    return 1\n\ndef g():\n    return 's'\n"
    _project(tmp_path, "app/m.py", src)
    a = plan_type_annotations(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    b = plan_type_annotations(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert a == b and a is not None and "x: int=0" in a and "-> str:" in a


def test_infer_unparseable_is_none():
    assert infer_annotations("def (:\n") is None


# --- end-to-end: gated apply, coverage delta, rollback -----------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_hints_keeps_green_and_raises_coverage(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective
    from app.tools.type_hint_coverage import analyze_type_hint_coverage

    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(
        "def answer():\n    return 42\n\n"
        "def total(items):\n    return sum(items)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import answer, total\n"
        "def test_it():\n    assert answer() == 42\n"
        "    assert total([1, 2]) == 3\n", encoding="utf-8")

    before = analyze_type_hint_coverage(str(tmp_path)).overall_ratio

    result = compile_objective(str(tmp_path), objective="infer-type-hints",
                               apply=True, verify=True)
    assert result.steps  # a verified move landed
    assert result.steps[0].verified is True

    text = (tmp_path / "app" / "calc.py").read_text()
    assert "def answer() -> int:" in text   # provable hint landed
    assert "def total(items):" in text       # ambiguous skipped, untouched

    after = analyze_type_hint_coverage(str(tmp_path)).overall_ratio
    assert after > before  # measurable fitness gain


def test_end_to_end_auto_rollback_on_breaking_annotation(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "def code():\n    return 7\n"
    (tmp_path / "app" / "mod.py").write_text(original, encoding="utf-8")
    # A suite that REJECTS the (here correct) annotation: when the `-> int`
    # lands, this test fails, so the verified apply must roll the file back.
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from app.mod import code\n"
        "def test_unannotated():\n    assert code() == 7\n"
        "    assert 'return' not in code.__annotations__\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="infer-type-hints",
                               apply=True, verify=True)
    assert not result.steps          # nothing landed
    assert result.blocked            # the move was blocked (rolled back)
    # The file is byte-for-byte restored — never-fake-green.
    assert (tmp_path / "app" / "mod.py").read_text() == original
