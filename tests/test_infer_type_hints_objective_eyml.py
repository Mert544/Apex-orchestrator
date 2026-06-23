"""infer-type-hints develop objective — land PROVABLE type annotations.

Covers: objective registration/reachability, that the transform lands provable
RETURN hints, NEVER infers a parameter type from its default value (an unsound,
wrong-but-verified landing — see ``test_does_not_infer_param_from_literal_default``
and the ``def add(x=0)`` repro), skips every ambiguous shape, refuses test/fixture
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


def test_does_not_infer_param_from_literal_default():
    # WRONG-BUT-VERIFIED FIX: a default value does NOT constrain the type a
    # parameter accepts, so `x=0` must NOT yield `x: int`. `def f(x=0)` is
    # legitimately called `f("s")`; inferring `int` would contradict such a call
    # while still passing (an annotation changes no runtime value) -> a verified
    # lie. The return here is non-literal, so NOTHING is provable -> None.
    assert infer_annotations("def f(x=0):\n    return x\n") is None


def test_add_repro_does_not_land_contradicting_param_hint():
    # The confirmed P1 repro. The repo's own tests call `add("ab")` / `add([1])`
    # (str/list concatenation) and PASS, so `x` provably accepts more than `int`.
    # Inferring `x: int` from the `0` default was wrong-but-verified. The return
    # `x + x` is non-literal (not provable) -> the honest outcome is NO change.
    src = "def add(x=0):\n    return x + x\n"
    out = infer_annotations(src)
    assert out is None
    # Belt-and-braces: even if a future sound return signal ever lands here, the
    # parameter must never gain a type from its default.
    if out is not None:
        assert "x: int" not in out


def test_sound_return_still_lands_with_a_defaulted_param_present():
    # Removing the unsound param path must NOT regress the sound RETURN path: a
    # provable literal return is still annotated even when the function has a
    # defaulted parameter — the param is simply left untouched.
    out = infer_annotations("def f(x=0):\n    return 1\n")
    assert out == "def f(x=0) -> int:\n    return 1\n"


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


def test_does_not_infer_keyword_only_param_from_default():
    # A keyword-only default is no more type-constraining than a positional one:
    # `f(n="x")` is valid, so `n=3` must NOT yield `n: int`. The non-literal
    # return leaves nothing else provable -> None. (Was a param-from-default bug.)
    assert infer_annotations("def f(*, n=3):\n    return n\n") is None


# --- widened sound shapes: str / bool / numeric / collection ----------------

def test_infers_str_from_fstring_return():
    # An f-string (JoinedStr) always evaluates to a str -> sound -> str.
    out = infer_annotations("def f(n):\n    return f'n={n}'\n")
    assert out == "def f(n) -> str:\n    return f'n={n}'\n"


def test_infers_str_from_multiple_string_returns():
    src = "def f(c):\n    if c:\n        return 'a'\n    else:\n        return 'b'\n"
    out = infer_annotations(src)
    assert out is not None and "-> str:" in out


def test_infers_str_from_mixed_str_literal_and_fstring():
    # Both arms are str (a plain literal and an f-string) -> agree on str.
    src = (
        "def f(c, n):\n"
        "    if c:\n"
        "        return 'plain'\n"
        "    else:\n"
        "        return f'{n}'\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> str:" in out


def test_refuses_bool_from_rich_comparison_return():
    # SOUNDNESS: `a < b` dispatches to `__lt__`, which is overridable and may
    # return any type (numpy arrays, sentinels) -> NOT provably a bool -> refuse.
    assert infer_annotations("def f(a, b):\n    return a < b\n") is None


def test_refuses_bool_from_equality_comparison_return():
    # `a == b` / `a != b` dispatch to `__eq__`/`__ne__` (overridable) -> refuse.
    assert infer_annotations("def f(a, b):\n    return a == b\n") is None
    assert infer_annotations("def f(a, b):\n    return a != b\n") is None
    # `value == None` (the exact modernizable idiom) must NOT gain `-> bool`.
    assert infer_annotations("def f(value):\n    return value == None\n") is None


def test_infers_bool_from_is_comparison():
    # `is`/`is not` are identity checks -> always a bool (not overridable).
    out = infer_annotations("def f(x):\n    return x is None\n")
    assert out is not None and "-> bool:" in out
    out2 = infer_annotations("def f(x):\n    return x is not None\n")
    assert out2 is not None and "-> bool:" in out2


def test_infers_bool_from_membership_comparison():
    # `in`/`not in` coerce `__contains__` to a bool -> always a bool.
    out = infer_annotations("def f(x, xs):\n    return x in xs\n")
    assert out is not None and "-> bool:" in out
    out2 = infer_annotations("def f(x, xs):\n    return x not in xs\n")
    assert out2 is not None and "-> bool:" in out2


def test_refuses_mixed_is_and_rich_comparison():
    # A chained comparison mixing a certain op (`is`) with a rich op (`<`) is
    # only certain if EVERY op is certain -> the `<` poisons it -> refuse.
    assert infer_annotations("def f(a, b):\n    return a is None < b\n") is None


def test_infers_bool_from_not_expression():
    out = infer_annotations("def f(x):\n    return not x\n")
    assert out is not None and "-> bool:" in out


def test_refuses_mixed_literal_and_rich_comparison():
    # `True` is certainly bool but `a == b` is NOT (overridable `__eq__`); a
    # function mixing them is not provably bool -> refuse, no annotation.
    src = (
        "def f(c, a, b):\n"
        "    if c:\n"
        "        return True\n"
        "    else:\n"
        "        return a == b\n"
    )
    assert infer_annotations(src) is None


def test_infers_bool_from_mixed_literal_and_identity_comparison():
    # `True` and `x is None` are BOTH certainly bool -> bool.
    src = (
        "def f(c, x):\n"
        "    if c:\n"
        "        return True\n"
        "    else:\n"
        "        return x is None\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> bool:" in out


def test_refuses_and_or_boolop_return():
    # `a and b` returns an OPERAND (e.g. `1 and 2 == 2`), NOT necessarily a bool;
    # it is not statically certain -> refuse.
    assert infer_annotations("def f(a, b):\n    return a and b\n") is None
    assert infer_annotations("def f(a, b):\n    return a or b\n") is None


def test_infers_int_from_agreeing_int_literals():
    src = "def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n"
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


def test_infers_float_from_agreeing_float_literals():
    src = "def f(c):\n    if c:\n        return 1.0\n    else:\n        return 2.5\n"
    out = infer_annotations(src)
    assert out is not None and "-> float:" in out


def test_refuses_int_float_mix():
    # int + float disagree on concrete type -> never guess (refuse), even though
    # an int is "a kind of" float at runtime; statically the names differ.
    src = "def f(c):\n    if c:\n        return 1\n    else:\n        return 2.0\n"
    assert infer_annotations(src) is None


def test_infers_list_from_comprehension():
    out = infer_annotations("def f(xs):\n    return [x for x in xs]\n")
    assert out is not None and "-> list:" in out


def test_infers_dict_from_comprehension():
    out = infer_annotations("def f(xs):\n    return {x: 1 for x in xs}\n")
    assert out is not None and "-> dict:" in out


def test_infers_set_from_comprehension():
    out = infer_annotations("def f(xs):\n    return {x for x in xs}\n")
    assert out is not None and "-> set:" in out


def test_refuses_generator_expression_return():
    # A generator expression yields a `generator` object, not a list/set/etc. —
    # not a concrete container we name -> refuse.
    assert infer_annotations("def f(xs):\n    return (x for x in xs)\n") is None


def test_infers_list_when_display_and_comprehension_agree():
    # A list DISPLAY and a list COMPREHENSION both produce `list` -> agree.
    src = (
        "def f(c, xs):\n"
        "    if c:\n"
        "        return [1, 2]\n"
        "    else:\n"
        "        return [x for x in xs]\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> list:" in out


def test_refuses_disagreeing_comprehension_types():
    # A list comprehension and a set comprehension disagree -> refuse.
    src = (
        "def f(c, xs):\n"
        "    if c:\n"
        "        return [x for x in xs]\n"
        "    else:\n"
        "        return {x for x in xs}\n"
    )
    assert infer_annotations(src) is None


def test_refuses_str_mixed_with_bool():
    # An f-string (str) and a comparison (bool) disagree -> refuse.
    src = (
        "def f(c, a, b):\n"
        "    if c:\n"
        "        return f'{a}'\n"
        "    else:\n"
        "        return a == b\n"
    )
    assert infer_annotations(src) is None


def test_refuses_name_return_even_amid_certain_returns():
    # One arm returns a bare name (not statically certain) -> the whole function
    # is refused, even though the other arm is a certain str.
    src = (
        "def f(c, x):\n"
        "    if c:\n"
        "        return 'a'\n"
        "    else:\n"
        "        return x\n"
    )
    assert infer_annotations(src) is None


def test_infers_int_from_fixed_result_builtin_call_return():
    # `len(x)` is a FIXED-result builtin (result is always int regardless of
    # args) and `len` is not shadowed here -> provably `-> int`. (Previously
    # this refused as a generic call; the builtin-call rule now proves it.
    # A SHADOWED builtin still refuses — see the builtin-call suite.)
    assert infer_annotations("def f(x):\n    return len(x)\n") == (
        "def f(x) -> int:\n    return len(x)\n")


def test_widened_inference_is_deterministic():
    src = "def f(a, b):\n    return a < b\n"
    assert infer_annotations(src) == infer_annotations(src)


# --- provably-str-rooted method calls (-> str) -------------------------------

def test_infers_str_from_str_literal_join():
    # `','.join(xs)` — the receiver is a str CONSTANT and `join` always returns
    # a str -> provably str.
    out = infer_annotations("def f(xs):\n    return ','.join(xs)\n")
    assert out == "def f(xs) -> str:\n    return ','.join(xs)\n"


def test_infers_str_from_empty_str_join():
    out = infer_annotations("def f(parts):\n    return ''.join(parts)\n")
    assert out is not None and "-> str:" in out


def test_infers_str_from_str_literal_format():
    out = infer_annotations("def f(x):\n    return \"{}\".format(x)\n")
    assert out is not None and "-> str:" in out


def test_infers_str_from_fstring_method_call():
    # The receiver is an f-string (provably str) and `strip` returns str.
    out = infer_annotations("def f(n):\n    return f'a{n}'.strip()\n")
    assert out is not None and "-> str:" in out


def test_infers_str_from_chained_str_method_calls():
    # `','.join(xs).upper()` — the inner join is provably str, so the chained
    # `.upper()` on it is provably str too (recursive receiver rule).
    out = infer_annotations("def f(xs):\n    return ','.join(xs).upper()\n")
    assert out is not None and "-> str:" in out


def test_refuses_str_method_on_name_receiver():
    # SOUNDNESS: `name` is a parameter of UNKNOWN type — `name.strip()` is only
    # str if `name` is a str, which is not provable -> refuse. Never assume a
    # parameter is a str.
    assert infer_annotations("def f(name):\n    return name.strip()\n") is None


def test_refuses_split_returns_list_not_str():
    # `s.split(',')` returns a LIST; even with a str-literal-looking receiver,
    # `split` is not in the str-returning whitelist -> refuse.
    assert infer_annotations("def f():\n    return 's'.split(',')\n") is None


def test_refuses_encode_returns_bytes_not_str():
    assert infer_annotations("def f():\n    return 's'.encode()\n") is None


def test_refuses_find_returns_int_not_str():
    assert infer_annotations("def f():\n    return 's'.find('x')\n") is None


def test_refuses_str_method_on_non_str_rooted_receiver():
    # `obj` is an unknown-typed name, so `obj.method()` is not provably str even
    # though `method` were whitelisted-shaped -> refuse on the receiver.
    assert infer_annotations("def f(obj):\n    return obj.upper()\n") is None


def test_str_method_call_inference_is_deterministic():
    src = "def f(xs):\n    return ','.join(xs).upper()\n"
    assert infer_annotations(src) == infer_annotations(src)


def test_str_literal_and_fstring_return_no_regression():
    # Control: the pre-existing str-literal / f-string return shapes still land
    # exactly as before alongside the new method-call shape.
    assert infer_annotations("def f():\n    return 'x'\n") == (
        "def f() -> str:\n    return 'x'\n")
    assert infer_annotations("def f(n):\n    return f'n={n}'\n") == (
        "def f(n) -> str:\n    return f'n={n}'\n")


def test_refuses_str_method_call_mixed_with_non_str_return():
    # One arm is a provably-str join, the other a bare name (not provable) ->
    # the whole function refuses (existing disagreement rule preserved).
    src = (
        "def f(c, xs, y):\n"
        "    if c:\n"
        "        return ','.join(xs)\n"
        "    else:\n"
        "        return y\n"
    )
    assert infer_annotations(src) is None


def test_str_method_call_agrees_with_str_literal():
    # A str-literal arm and a provably-str method-call arm agree on str -> str.
    src = (
        "def f(c, xs):\n"
        "    if c:\n"
        "        return 'a'\n"
        "    else:\n"
        "        return ','.join(xs)\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> str:" in out


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
    # No parameter is ever inferred from its default now (a default is not a type
    # bound); a None default is doubly skipped. Return is non-literal -> nothing
    # provable at all.
    out = infer_annotations("def f(x=None):\n    return x\n")
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
    # *args/**kwargs params are never annotated. The return is a subscript
    # (non-provable, and NOT a fixed-result builtin call) -> nothing to add, so
    # the function — params included — is left exactly as-is.
    src = "def f(*args, **kwargs):\n    return args[0]\n"
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
    # Two provable RETURN hints land identically on repeated runs; the defaulted
    # param `x` is left alone (a default is not a sound type bound).
    src = "def f(x=0):\n    return 1\n\ndef g():\n    return 's'\n"
    _project(tmp_path, "app/m.py", src)
    a = plan_type_annotations(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    b = plan_type_annotations(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert a == b and a is not None
    assert "-> int:" in a and "-> str:" in a  # both sound returns landed
    assert "x: int" not in a                  # param NOT inferred from default
    assert "def f(x=0)" in a                  # the param spelling is untouched


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


def test_end_to_end_add_repro_never_lands_contradicting_param_hint(tmp_path: Path):
    # The wrong-but-verified P1, end-to-end: `add(x=0)` whose tests call
    # `add("ab")`/`add([1])` (str/list concat) and PASS. The old default-value
    # inference stamped `x: int` as verified — provably wrong, since the param
    # accepts str/list. The objective must now land NO param hint here. The
    # non-literal return `x + x` is also not provable, so nothing lands for this
    # function at all — the honest under-claim.
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "def add(x=0):\n    return x + x\n"
    (tmp_path / "app" / "concat.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_concat.py").write_text(
        "from app.concat import add\n"
        "def test_it():\n"
        "    assert add(2) == 4\n"
        "    assert add('ab') == 'abab'\n"   # str concat — x is NOT int-only
        "    assert add([1]) == [1, 1]\n",   # list concat — x is NOT int-only
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="infer-type-hints",
                               apply=True, verify=True)

    text = (tmp_path / "app" / "concat.py").read_text()
    # The contradicting hint must never appear; the function is left byte-identical.
    assert "x: int" not in text
    assert text == original
    # And no step claims to have verified a (non-existent, would-be-wrong) hint.
    assert not result.steps


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
