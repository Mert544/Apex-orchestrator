"""infer-type-hints — sound RETURN inference for ``divmod``/``complex``/
``bytearray`` BUILTIN CALLS whose result type is FIXED by the callable, WITH the
existing shadowing + bare-Name-callee guards.

Three more callable-fixed builtins join :data:`_BUILTIN_CALL_RETURN_TYPES` and
route through the SAME builtin-call resolver (arguments are never inspected):

  - ``divmod(a, b)`` ALWAYS returns a ``tuple`` (a 2-tuple ``(q, r)``), regardless
    of the argument values — exactly like the existing ``sorted`` ⇒ ``list`` entry;
  - ``complex(...)`` ALWAYS returns a ``complex`` (``complex(1, 2)`` /
    ``complex('1j')`` ⇒ ``complex``);
  - ``bytearray(...)`` ALWAYS returns a ``bytearray`` (its OWN container type,
    like ``list``/``dict``).

Each lands the BARE container/scalar name (``tuple``/``complex``/``bytearray``) —
a builtin CALL result is never routed through ``_parametrized_display_type`` (that
parametrizes only literal displays), so ``divmod(a, b)`` is ``-> tuple``, NOT
``tuple[...]``. The LOCKED soundness rules are preserved by the SAME machinery: a
SHADOWED builtin (a local ``divmod = ...`` rebind) and an ATTRIBUTE callee
(``obj.divmod(...)`` is a user-defined method, NOT the builtin) both refuse. A
fake-green canary proves the landed annotation matches the REAL runtime type, and
a determinism + byte-identical check pins input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _BUILTIN_CALL_RETURN_TYPES,
    _builtin_call_returns_type,
    _infer_return_type,
    _return_value_type,
    infer_annotations,
)


# --- fixed-result builtin calls land their type ------------------------------

def test_infers_tuple_from_divmod_call():
    # ``divmod(a, b)`` ALWAYS returns a (2-element) ``tuple`` regardless of args.
    src = "def f(a, b):\n    return divmod(a, b)\n"
    assert infer_annotations(src) == (
        "def f(a, b) -> tuple:\n    return divmod(a, b)\n")


def test_infers_tuple_from_divmod_with_unpacking_body():
    # A function that first UNPACKS ``q, r = divmod(a, b)`` and then returns the
    # ``divmod`` call still proves ``-> tuple`` (the return is the builtin call;
    # the unpack assignment is just body context, not a shadow of ``divmod``).
    src = (
        "def f(a, b):\n"
        "    q, r = divmod(a, b)\n"
        "    return divmod(a, b)\n"
    )
    assert infer_annotations(src) == (
        "def f(a, b) -> tuple:\n"
        "    q, r = divmod(a, b)\n"
        "    return divmod(a, b)\n"
    )


def test_infers_complex_from_complex_call():
    # ``complex(...)`` is callable-fixed: always a ``complex`` (``complex(1, 2)``).
    src = "def f(a, b):\n    return complex(a, b)\n"
    assert infer_annotations(src) == (
        "def f(a, b) -> complex:\n    return complex(a, b)\n")


def test_infers_bytearray_from_bytearray_call():
    # ``bytearray(...)`` returns its OWN container type, like ``list``/``dict``.
    src = "def f(x):\n    return bytearray(x)\n"
    assert infer_annotations(src) == (
        "def f(x) -> bytearray:\n    return bytearray(x)\n")


def test_divmod_complex_bytearray_arguments_not_inspected():
    # The argument VALUES are irrelevant — each builtin's result type is fixed by
    # the callable, so even a string literal arg proves the same type.
    cases = {
        "divmod": "tuple", "complex": "complex", "bytearray": "bytearray",
    }
    for builtin, type_name in cases.items():
        src = f'def f():\n    return {builtin}("x")\n'
        assert infer_annotations(src) == (
            f'def f() -> {type_name}:\n    return {builtin}("x")\n'), builtin


def test_divmod_result_is_bare_tuple_not_parametrized():
    # A builtin CALL result emits the BARE container — never routed through the
    # display-parametrizer — so ``divmod`` is ``-> tuple``, NOT ``tuple[int, int]``.
    out = infer_annotations("def f(a, b):\n    return divmod(a, b)\n")
    assert out is not None
    assert "-> tuple:" in out and "tuple[" not in out


# --- the table holds the three new entries -----------------------------------

def test_table_maps_new_builtins_to_their_types():
    assert _BUILTIN_CALL_RETURN_TYPES["divmod"] == "tuple"
    assert _BUILTIN_CALL_RETURN_TYPES["complex"] == "complex"
    assert _BUILTIN_CALL_RETURN_TYPES["bytearray"] == "bytearray"


# --- the LOCKED guards REFUSE ------------------------------------------------

def test_refuses_shadowed_divmod():
    # SHADOWING GUARD: a local ``divmod = ...`` rebinds the name, so ``divmod(a,
    # b)`` no longer resolves to the builtin and its result type is unknown.
    src = "def f(a, b):\n    divmod = a\n    return divmod(a, b)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_complex():
    src = "def f(a, b):\n    complex = a\n    return complex(a, b)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_bytearray():
    src = "def f(x):\n    bytearray = x\n    return bytearray(x)\n"
    assert infer_annotations(src) is None


def test_refuses_attribute_divmod_callee():
    # ``obj.divmod(a, b)`` is an attribute callee — a DIFFERENT, user-defined
    # method, NOT the builtin — so it must refuse even though the name matches.
    src = "def f(obj, a, b):\n    return obj.divmod(a, b)\n"
    assert infer_annotations(src) is None


def test_refuses_attribute_complex_callee():
    src = "def f(obj, a, b):\n    return obj.complex(a, b)\n"
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_builtin_helper_accepts_new_calls():
    divmod_node = ast.parse("divmod(a, b)", mode="eval").body
    complex_node = ast.parse("complex(a, b)", mode="eval").body
    bytearray_node = ast.parse("bytearray(x)", mode="eval").body
    assert _builtin_call_returns_type(divmod_node, frozenset()) == "tuple"
    assert _builtin_call_returns_type(complex_node, frozenset()) == "complex"
    assert _builtin_call_returns_type(bytearray_node, frozenset()) == "bytearray"


def test_builtin_helper_refuses_shadowed_new_builtins():
    node = ast.parse("divmod(a, b)", mode="eval").body
    assert _builtin_call_returns_type(node, frozenset({"divmod"})) is None


def test_return_value_type_routes_new_calls():
    node = ast.parse("complex(a, b)", mode="eval").body
    assert _return_value_type(node, frozenset()) == "complex"


def test_infer_return_type_uses_divmod_call():
    fn = ast.parse("def f(a, b):\n    return divmod(a, b)\n").body[0]
    assert _infer_return_type(fn) == "tuple"


# --- fake-green canary + soundness made concrete -----------------------------

def test_new_builtin_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path annotates the ACTUAL inferred type, not a
    # hardcoded constant — divmod -> tuple, complex -> complex, bytearray ->
    # bytearray produce THREE DISTINCT annotations.
    divmod_out = infer_annotations("def f(a, b):\n    return divmod(a, b)\n")
    complex_out = infer_annotations("def f(a, b):\n    return complex(a, b)\n")
    bytearray_out = infer_annotations("def f(x):\n    return bytearray(x)\n")
    assert divmod_out is not None and "-> tuple:" in divmod_out
    assert complex_out is not None and "-> complex:" in complex_out
    assert bytearray_out is not None and "-> bytearray:" in bytearray_out
    assert len({divmod_out, complex_out, bytearray_out}) == 3


def test_divmod_annotation_matches_runtime_type():
    # The annotation adds `-> T` TEXT only and never changes runtime behaviour;
    # the runtime return type is EXACTLY the annotated ``tuple``.
    src = "def f(a, b):\n    return divmod(a, b)\n"
    out = infer_annotations(src)
    assert out == "def f(a, b) -> tuple:\n    return divmod(a, b)\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"](7, 2) == new_ns["f"](7, 2) == (3, 1)  # value unchanged
    assert type(new_ns["f"](7, 2)) is tuple
    assert "tuple" in str(new_ns["f"].__annotations__.get("return"))


def test_complex_and_bytearray_annotations_match_runtime_type():
    complex_out = infer_annotations("def f(a, b):\n    return complex(a, b)\n")
    bytearray_out = infer_annotations("def f(x):\n    return bytearray(x)\n")
    assert complex_out is not None and bytearray_out is not None

    cns: dict[str, object] = {}
    exec(compile(complex_out, "<c>", "exec"), cns)
    assert cns["f"](1, 2) == (1 + 2j) and type(cns["f"](1, 2)) is complex

    bns: dict[str, object] = {}
    exec(compile(bytearray_out, "<b>", "exec"), bns)
    assert bns["f"](b"ab") == bytearray(b"ab")
    assert type(bns["f"](b"ab")) is bytearray


def test_shadowed_divmod_canary_runtime_matches_refusal():
    # The guard's soundness, made concrete: when ``divmod`` is shadowed the call
    # returns the LOCAL's value, NOT a tuple — so inferring ``-> tuple`` would be a
    # wrong-but-verified lie. We refuse, and prove the runtime really diverges.
    src = "def f(a, b):\n    divmod = a\n    return divmod(a, b)\n"
    assert infer_annotations(src) is None

    ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), ns)
    # ``divmod`` is rebound to ``a``; call with a 2-arg callable that returns a
    # NON-tuple (an int here), so a naive ``-> tuple`` would have been a lie.
    assert ns["f"](lambda p, q: 7, 0) == 7  # the local, not the builtin -> int
    assert type(ns["f"](lambda p, q: 7, 0)) is int


def test_new_builtin_inference_is_deterministic():
    for src in (
        "def f(a, b):\n    return divmod(a, b)\n",
        "def f(a, b):\n    return complex(a, b)\n",
        "def f(x):\n    return bytearray(x)\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(a, b):\n    divmod = a\n    return divmod(a, b)\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_new_builtin_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(a, b):\n    return divmod(a, b\n") is None
