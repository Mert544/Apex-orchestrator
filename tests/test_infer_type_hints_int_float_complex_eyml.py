"""infer-type-hints — sound ``int``/``float`` BUILTIN-CALL and ``complex`` LITERAL
RETURN inference, two code-flagged gaps closed in the existing return oracle.

The module's own comment flagged ``int(...)``/``float(...)`` as "fixed, but
omitted as a conservative initial set; can be added later". They are CALLABLE-FIXED:
``int`` always returns an ``int`` (``int('5')``/``int(3.9)`` ⇒ ``int``) and ``float``
always returns a ``float`` (``float('1.5')``/``float(2)`` ⇒ ``float``) REGARDLESS of
the argument — exactly like the existing ``len``/``str``/``hex`` entries — so they
join :data:`_BUILTIN_CALL_RETURN_TYPES` and route through the SAME builtin-call
resolver (arguments are never inspected). A ``complex`` literal (``3j``) is a pure
``ast.Constant`` whose type is non-overridable, so it joins :func:`_constant_type`
as the literal classification ``complex`` (no inference).

The LOCKED soundness rules are preserved by the SAME machinery: the SHADOWING GUARD
(``func.id not in assigned_names``) still refuses a local ``int = ...`` rebind, and a
bare ``ast.Name`` return (``return x``) is never a builtin call / literal and refuses.
Because both additions route through the existing resolver, they COMPOSE for free:
a ternary whose BOTH branches are ``int(...)`` lands ``-> int``. A fake-green canary
proves the accept path annotates the REAL inferred type (``int`` vs ``float`` vs
``complex`` produce DISTINCT annotations, never a hardcoded one), and a determinism +
byte-identical check pins input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _builtin_call_returns_type,
    _constant_type,
    _infer_return_type,
    _literal_type,
    _return_value_type,
    infer_annotations,
)


# --- int/float builtin calls + complex literal land their type ----------------

def test_infers_int_from_int_call():
    # ``int(...)`` is callable-fixed: it always returns an ``int`` regardless of
    # the argument (``int('5')``/``int(3.9)`` both ⇒ ``int``).
    src = "def f(x):\n    return int(x)\n"
    assert infer_annotations(src) == "def f(x) -> int:\n    return int(x)\n"


def test_infers_float_from_float_call():
    # ``float(...)`` is callable-fixed: it always returns a ``float``.
    src = "def f(x):\n    return float(x)\n"
    assert infer_annotations(src) == "def f(x) -> float:\n    return float(x)\n"


def test_infers_int_from_int_call_arguments_not_inspected():
    # The argument VALUE is irrelevant — a str arg still proves ``int``.
    src = 'def f():\n    return int("5")\n'
    assert infer_annotations(src) == 'def f() -> int:\n    return int("5")\n'


def test_infers_complex_from_complex_literal():
    # A ``complex`` literal (``3j``) is a pure ``ast.Constant`` whose type is
    # non-overridable, so it classifies as ``complex`` (no inference).
    src = "def f():\n    return 3j\n"
    assert infer_annotations(src) == "def f() -> complex:\n    return 3j\n"


def test_infers_int_from_int_ternary_composes():
    # Composition for free: a ternary recurses through the FULL return-value
    # oracle, so two provably-``int`` branches prove the ternary -> ``int``.
    src = "def f(c, x, y):\n    return int(x) if c else int(y)\n"
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c, x, y) -> int:")


# --- refusals (the LOCKED soundness rules, preserved) ------------------------

def test_refuses_shadowed_int_builtin_rebind():
    # SHADOWING GUARD: a local ``int = 5`` rebinds the name in this scope, so
    # ``int(x)`` no longer resolves to the builtin and its type is unknown.
    src = "def f(x):\n    int = 5\n    return int(x)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_float_builtin_rebind():
    src = "def f(x):\n    float = 5\n    return float(x)\n"
    assert infer_annotations(src) is None


def test_refuses_bare_name_return():
    # ``return x`` is a bare name of UNKNOWN type — not a builtin call nor a
    # literal — so it refuses (never assume a value's type).
    src = "def f(x):\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_attribute_int_callee():
    # An attribute callee (``obj.int(...)``) is a DIFFERENT, user-defined method,
    # not the builtin — it must refuse.
    src = "def f(obj, x):\n    return obj.int(x)\n"
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_builtin_helper_accepts_int_and_float_calls():
    int_node = ast.parse("int(x)", mode="eval").body
    float_node = ast.parse("float(x)", mode="eval").body
    assert _builtin_call_returns_type(int_node, frozenset()) == "int"
    assert _builtin_call_returns_type(float_node, frozenset()) == "float"


def test_builtin_helper_refuses_shadowed_int():
    node = ast.parse("int(x)", mode="eval").body
    assert _builtin_call_returns_type(node, frozenset({"int"})) is None


def test_constant_type_classifies_complex_literal():
    assert _constant_type(3j) == "complex"


def test_literal_type_routes_complex_constant():
    node = ast.parse("3j", mode="eval").body
    assert _literal_type(node) == "complex"


def test_return_value_type_routes_int_call_and_complex():
    int_node = ast.parse("int(x)", mode="eval").body
    complex_node = ast.parse("2j", mode="eval").body
    assert _return_value_type(int_node, frozenset()) == "int"
    assert _return_value_type(complex_node, frozenset()) == "complex"


def test_infer_return_type_uses_int_call_and_complex():
    int_fn = ast.parse("def f(x):\n    return int(x)\n").body[0]
    complex_fn = ast.parse("def f():\n    return 1j\n").body[0]
    assert _infer_return_type(int_fn) == "int"
    assert _infer_return_type(complex_fn) == "complex"


# --- fake-green canary + soundness made concrete -----------------------------

def test_int_float_complex_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path must annotate the ACTUAL inferred type,
    # not a hardcoded constant. ``int(x)`` -> int, ``float(x)`` -> float and
    # ``3j`` -> complex therefore produce THREE DISTINCT annotations.
    int_out = infer_annotations("def f(x):\n    return int(x)\n")
    float_out = infer_annotations("def f(x):\n    return float(x)\n")
    complex_out = infer_annotations("def f():\n    return 3j\n")
    assert int_out is not None and "-> int:" in int_out
    assert float_out is not None and "-> float:" in float_out
    assert complex_out is not None and "-> complex:" in complex_out
    assert len({int_out, float_out, complex_out}) == 3  # not one hardcoded text


def test_annotation_preserves_parse_and_runtime_value():
    # The annotation adds `-> T` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, and the runtime return value must be
    # byte-identical to the original's.
    src = 'def f():\n    return int("7")\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> int:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"]() == new_ns["f"]() == 7
    assert "return" in new_ns["f"].__annotations__
    assert "int" in str(new_ns["f"].__annotations__.get("return"))


def test_complex_annotation_preserves_runtime_value():
    src = "def f():\n    return 3j\n"
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> complex:")

    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)
    assert new_ns["f"]() == 3j


def test_int_float_complex_inference_is_deterministic():
    for src in (
        "def f(x):\n    return int(x)\n",
        "def f(x):\n    return float(x)\n",
        "def f():\n    return 3j\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    int = 5\n    return int(x)\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_file_without_qualifying_call_is_byte_identical():
    # A bare-name return alone adds nothing (None), and an already-annotated
    # return is never overwritten.
    assert infer_annotations("def f(x):\n    return x\n") is None
    annotated = "def f(x) -> object:\n    return int(x)\n"
    assert infer_annotations(annotated) is None


def test_int_float_complex_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(x):\n    return int(x\n") is None
