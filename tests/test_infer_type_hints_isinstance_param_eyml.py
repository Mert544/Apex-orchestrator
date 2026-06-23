"""infer-type-hints — sound PARAMETER inference from an UNCONDITIONAL runtime
``isinstance`` guard at function entry (a NOVEL capability, distinct from the
LOCKED default-value refusal).

A guard is a runtime-ENFORCED type bound: when

  - ``assert isinstance(x, str)`` or
  - ``if not isinstance(x, int): raise TypeError``

opens a function body UNCONDITIONALLY, every path that continues past it has
PROVEN ``x`` is an instance of that class. Recording ``x: str`` / ``x: int``
therefore only states a fact the runtime already enforces — it changes no
runtime value, and any value the guard would reject already raises today, so the
annotation cannot contradict a passing test. This is sound exactly where a
default value (``def f(x=0)``) is NOT — a default is the value used when the arg
is omitted, never a bound on the type accepted (that path stays REMOVED).

The suite pins every SOUND-CONDITION refusal: a CONDITIONAL guard (nested under
another ``if``), a TUPLE of classes (would need a ``Union``), a parameter
REASSIGNED or USED before its guard (the guard must bind the ORIGINAL
parameter), a parameter that already has an annotation (never overwrite), and a
DOTTED/unknown class (not a bare known-builtin type). A fake-green canary proves
the landed annotation changes no runtime value, and a determinism test pins
input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _annotatable_params,
    _entry_guard_binding,
    _isinstance_single_class,
    infer_annotations,
)


# --- entry guards land a parameter type --------------------------------------

def test_infers_int_from_if_not_isinstance_raise():
    src = (
        "def f(x):\n"
        "    if not isinstance(x, int):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    assert infer_annotations(src) == (
        "def f(x: int):\n"
        "    if not isinstance(x, int):\n"
        "        raise TypeError\n"
        "    return x\n"
    )


def test_infers_str_from_assert_isinstance_with_docstring():
    # A leading docstring may precede the guard — it is still the entry guard.
    src = (
        "def g(x):\n"
        '    """doc"""\n'
        "    assert isinstance(x, str)\n"
        "    return x\n"
    )
    assert infer_annotations(src) == (
        "def g(x: str):\n"
        '    """doc"""\n'
        "    assert isinstance(x, str)\n"
        "    return x\n"
    )


def test_infers_from_assert_with_message():
    # The assert's optional message does not affect the bound.
    src = 'def g(x):\n    assert isinstance(x, str), "must be str"\n    return x\n'
    assert infer_annotations(src) == (
        'def g(x: str):\n    assert isinstance(x, str), "must be str"\n    return x\n')


def test_infers_multiple_params_from_consecutive_guards():
    # Two consecutive entry guards bind two params; both annotations land.
    src = (
        "def h(x, y):\n"
        "    assert isinstance(x, int)\n"
        "    if not isinstance(y, str):\n"
        "        raise TypeError\n"
        "    return None\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def h(x: int, y: str)")


def test_infers_only_the_guarded_param_not_its_neighbour():
    # Only `x` is guarded; `y` (unguarded) stays unannotated.
    src = "def f(x, y):\n    assert isinstance(x, int)\n    return y\n"
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(x: int, y):")


def test_infers_across_builtin_class_group():
    for cls in ("int", "float", "str", "bytes", "bool", "list", "dict", "tuple"):
        src = f"def f(x):\n    assert isinstance(x, {cls})\n    return None\n"
        out = infer_annotations(src)
        assert out is not None, cls
        assert out.startswith(f"def f(x: {cls})"), cls


def test_param_guard_and_provable_return_compose():
    # A param guard AND a provable return (`len(x)` -> int) land together.
    src = "def f(x):\n    assert isinstance(x, int)\n    return len(x)\n"
    assert infer_annotations(src) == (
        "def f(x: int) -> int:\n    assert isinstance(x, int)\n    return len(x)\n")


# --- sound-condition refusals (the whole point) ------------------------------

def test_refuses_conditional_guard_nested_under_if():
    # The guard is NOT unconditional — it is nested under `if y:`, so a path can
    # reach past it with `x` of any type. REFUSE.
    src = (
        "def f(x, y):\n"
        "    if y:\n"
        "        assert isinstance(x, int)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_tuple_of_classes():
    # `isinstance(x, (int, float))` is a Union bound, not a single type -> refuse.
    src = "def f(x):\n    assert isinstance(x, (int, float))\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_param_reassigned_before_guard():
    # `x` is rebound before the guard, so the guard does not bind the ORIGINAL
    # parameter -> the reassignment ends the entry prologue -> refuse.
    src = "def f(x):\n    x = x or 0\n    assert isinstance(x, int)\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_param_used_before_guard():
    # A non-guard statement (a use of `x`) precedes the guard -> prologue ends
    # before the guard is reached -> refuse.
    src = "def f(x):\n    print(x)\n    assert isinstance(x, int)\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_param_already_annotated():
    # Never overwrite an existing annotation.
    src = "def f(x: object):\n    assert isinstance(x, int)\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_dotted_class():
    # A dotted/complex class expr is not a bare type Name -> refuse conservatively.
    src = "def f(x):\n    assert isinstance(x, numbers.Integral)\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_unknown_bare_class_name():
    # A bare Name outside the known-builtin set (a possible user alias whose
    # identity is not AST-resolvable) -> refuse.
    src = "def f(x):\n    assert isinstance(x, Foo)\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_if_body_does_not_raise():
    # The if-body must raise on the negation; a body that falls through (here a
    # bare `pass`) does NOT enforce the type -> refuse.
    src = (
        "def f(x):\n"
        "    if not isinstance(x, int):\n"
        "        pass\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_if_with_else_branch():
    # An `else` branch means the if is not a clean negation-raise guard -> refuse
    # conservatively (the body must be exactly a raise with no else).
    src = (
        "def f(x):\n"
        "    if not isinstance(x, int):\n"
        "        raise TypeError\n"
        "    else:\n"
        "        x = 0\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_if_without_negation():
    # `if isinstance(x, int): ...` (no `not`) is not a negation-raise guard.
    src = (
        "def f(x):\n"
        "    if isinstance(x, int):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_guard_after_a_non_guard_statement():
    # A non-guard statement before the (otherwise valid) guard ends the prologue.
    src = (
        "def f(x):\n"
        "    y = 1\n"
        "    assert isinstance(x, int)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_default_value_still_refused():
    # LOCKED refusal preserved: a default value is NOT a type bound -> no param
    # annotation from `x=0` (and the bare-name return is unprovable too).
    assert infer_annotations("def f(x=0):\n    return x\n") is None


# --- direct helper unit checks -----------------------------------------------

def test_isinstance_single_class_accepts_known_builtin():
    node = ast.parse("isinstance(x, int)", mode="eval").body
    assert _isinstance_single_class(node) == ("x", "int")


def test_isinstance_single_class_refuses_tuple_second_arg():
    node = ast.parse("isinstance(x, (int, float))", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_isinstance_single_class_refuses_non_isinstance_call():
    node = ast.parse("issubclass(x, int)", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_isinstance_single_class_refuses_keyword_arg():
    node = ast.parse("isinstance(x, cls=int)", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_entry_guard_binding_assert_and_if_forms():
    assert_stmt = ast.parse("assert isinstance(x, str)").body[0]
    assert _entry_guard_binding(assert_stmt) == ("x", "str")
    if_stmt = ast.parse(
        "if not isinstance(y, int):\n    raise TypeError\n").body[0]
    assert _entry_guard_binding(if_stmt) == ("y", "int")


def test_entry_guard_binding_returns_none_for_plain_statement():
    stmt = ast.parse("y = 1").body[0]
    assert _entry_guard_binding(stmt) is None


def test_annotatable_params_returns_empty_without_guard():
    fn = ast.parse("def f(x):\n    return x\n").body[0]
    assert _annotatable_params(fn) == []


def test_annotatable_params_reports_arg_and_class():
    fn = ast.parse(
        "def f(x):\n    assert isinstance(x, int)\n    return x\n").body[0]
    params = _annotatable_params(fn)
    assert len(params) == 1
    arg, class_name = params[0]
    assert isinstance(arg, ast.arg) and arg.arg == "x" and class_name == "int"


# --- behaviour preservation (fake-green canary) + soundness made concrete ----

def test_guard_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the annotation adds `: T` TEXT only and never changes
    # runtime behaviour. The annotated source must still parse, and the runtime
    # return value must be byte-identical to the original's.
    src = (
        "def f(x):\n"
        "    if not isinstance(x, int):\n"
        "        raise TypeError\n"
        "    return x + 1\n"
    )
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(x: int):")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"](5) == new_ns["f"](5) == 6   # value unchanged
    assert "x" not in orig_ns["f"].__annotations__
    assert "int" in str(new_ns["f"].__annotations__.get("x"))


def test_guard_enforces_type_so_annotation_cannot_lie():
    # SOUNDNESS made concrete: the guard REJECTS a wrong-typed arg at runtime, so
    # the inferred `x: int` records a fact the runtime already enforces — there
    # is no input for which the annotation is false-but-green.
    src = (
        "def f(x):\n"
        "    if not isinstance(x, int):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None

    ns: dict[str, object] = {}
    exec(compile(out, "<n>", "exec"), ns)
    assert ns["f"](3) == 3
    raised = False
    try:
        ns["f"]("not an int")
    except TypeError:
        raised = True
    assert raised  # a non-int is rejected, so `x: int` never contradicts a run


def test_guard_param_inference_is_deterministic():
    for src in (
        "def f(x):\n    assert isinstance(x, str)\n    return x\n",
        "def f(x):\n    if not isinstance(x, int):\n        raise TypeError\n    return x\n",
        "def f(x, y):\n    assert isinstance(x, int)\n    return y\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    assert isinstance(x, (int, float))\n    return x\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_guard_param_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(x:\n    assert isinstance(x, int)\n") is None
