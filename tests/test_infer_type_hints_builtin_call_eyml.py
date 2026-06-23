"""infer-type-hints — sound RETURN inference for ``return <builtin>(...)`` whose
result type is FIXED regardless of args, WITH a shadowing guard.

A NEW sound return-type rule: a ``return <builtin>(...)`` call resolves to a
provable type ONLY when the callee is a bare ``ast.Name`` naming a builtin whose
result type does not depend on its arguments AND that name is NOT rebound in the
function's own scope:

  - int:  ``len``/``ord``/``id``/``hash`` ⇒ ``int``;
  - str:  ``str``/``repr``/``ascii``/``hex``/``oct``/``bin``/``chr`` ⇒ ``str``;
  - bool: ``bool`` ⇒ ``bool``;
  - container: ``list``/``dict``/``set``/``tuple``/``frozenset`` ⇒ that type,
    and ``sorted`` ⇒ ``list``.

SOUND because a non-shadowed builtin's result type is fixed by the callable
itself, independent of the argument values, and the callee dunders are not
instance-overridable. The suite pins every REFUSAL the soundness argument
requires: a SHADOWED builtin (a local ``len = ...`` then ``return len(x)`` no
longer resolves to the builtin), an attribute callee (``x.foo()`` is a
user-defined method, NOT a builtin), and a user call (``user_fn(x)``). It also
keeps the LOCKED refusals intact (a builtin call as a BINOP operand —
``len(x) + 1`` — still refuses, since the binop recursion never sees this rule).
A fake-green canary proves the landed annotation changes no runtime value, and a
determinism test pins input → output stability.
"""

from __future__ import annotations

from app.execution.semantic.transforms.type_annotations import (
    _builtin_call_returns_type,
    infer_annotations,
)


# --- fixed-result builtin calls land -----------------------------------------

def test_infers_int_from_len_call():
    assert infer_annotations("def f(xs):\n    return len(xs)\n") == (
        "def f(xs) -> int:\n    return len(xs)\n")


def test_infers_str_from_str_call():
    assert infer_annotations("def f(x):\n    return str(x)\n") == (
        "def f(x) -> str:\n    return str(x)\n")


def test_infers_bool_from_bool_call():
    assert infer_annotations("def f(x):\n    return bool(x)\n") == (
        "def f(x) -> bool:\n    return bool(x)\n")


def test_infers_list_from_list_call():
    assert infer_annotations("def f(x):\n    return list(x)\n") == (
        "def f(x) -> list:\n    return list(x)\n")


def test_infers_list_from_sorted_call():
    # `sorted(...)` ALWAYS returns a list (not the input's container type).
    assert infer_annotations("def f(x):\n    return sorted(x)\n") == (
        "def f(x) -> list:\n    return sorted(x)\n")


def test_infers_int_from_ord_call():
    assert infer_annotations("def f(c):\n    return ord(c)\n") == (
        "def f(c) -> int:\n    return ord(c)\n")


def test_infers_container_types_across_the_group():
    # Each container builtin lands its OWN type; sorted lands list.
    cases = {
        "dict": "dict", "set": "set", "tuple": "tuple", "frozenset": "frozenset",
    }
    for builtin, type_name in cases.items():
        src = f"def f(x):\n    return {builtin}(x)\n"
        assert infer_annotations(src) == (
            f"def f(x) -> {type_name}:\n    return {builtin}(x)\n")


def test_infers_str_group_builtins():
    # repr/ascii/hex/oct/bin/chr all return str regardless of args.
    for builtin in ("repr", "ascii", "hex", "oct", "bin", "chr"):
        src = f"def f(x):\n    return {builtin}(x)\n"
        out = infer_annotations(src)
        assert out is not None and "-> str:" in out


def test_infers_int_group_builtins():
    # id/hash join len/ord in the int group.
    for builtin in ("id", "hash"):
        src = f"def f(x):\n    return {builtin}(x)\n"
        out = infer_annotations(src)
        assert out is not None and "-> int:" in out


# --- the shadowing guard REFUSES ---------------------------------------------

def test_refuses_shadowed_len():
    # A local rebinds `len`, so `len(x)` no longer resolves to the builtin.
    src = "def f(x):\n    len = x\n    return len(x)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_str():
    src = "def f(x):\n    str = x\n    return str(x)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_bool():
    src = "def f(x):\n    bool = x\n    return bool(x)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_list():
    src = "def f(x):\n    list = []\n    return list(x)\n"
    assert infer_annotations(src) is None


def test_refuses_builtin_shadowed_by_loop_target():
    # The shadow can come from any Store binding in the body, e.g. a for target.
    src = "def f(items):\n    for ord in items:\n        pass\n    return ord(items)\n"
    assert infer_annotations(src) is None


def test_refuses_builtin_shadowed_by_with_target():
    src = (
        "def f(x):\n"
        "    with open('p') as sorted:\n"
        "        pass\n"
        "    return sorted(x)\n"
    )
    assert infer_annotations(src) is None


def test_nested_scope_binding_does_not_count_as_shadow():
    # A `len` bound only inside a NESTED function does NOT shadow the outer
    # builtin (the outer `return len(x)` still resolves to the builtin) -> int.
    src = (
        "def f(x):\n"
        "    def g():\n"
        "        len = 1\n"
        "        return len\n"
        "    return len(x)\n"
    )
    out = infer_annotations(src)
    assert out is not None
    # The OUTER function is annotated -> int (its len is the builtin).
    assert out.startswith("def f(x) -> int:")


# --- non-builtin / non-Name callees REFUSE -----------------------------------

def test_refuses_attribute_call():
    # `x.foo()` is a user-defined method, not a builtin -> refuse.
    assert infer_annotations("def f(x):\n    return x.foo()\n") is None


def test_refuses_user_function_call():
    # `user_fn(x)` is not in the approved builtin set -> refuse.
    assert infer_annotations("def f(x):\n    return user_fn(x)\n") is None


def test_refuses_attribute_named_like_builtin():
    # `m.sorted(x)` is an attribute callee — a DIFFERENT callable than the
    # builtin `sorted`, so it must refuse even though the name matches.
    assert infer_annotations("def f(m, x):\n    return m.sorted(x)\n") is None


def test_refuses_non_fixed_result_builtin():
    # `max(x)`'s result type depends on its args (not in the approved set).
    assert infer_annotations("def f(x):\n    return max(x)\n") is None


# --- LOCKED refusals stay intact ---------------------------------------------

def test_builtin_call_as_binop_operand_still_refuses():
    # LOCKED: `len(x) + 1` — the binop recursion uses the pure literal oracle,
    # which does NOT see the builtin-call rule, so it stays unprovable.
    assert infer_annotations("def f(x):\n    return len(x) + 1\n") is None


def test_mixed_builtin_return_types_refuse():
    # Two value returns of DIFFERING provable types (int vs str) -> ambiguous.
    src = (
        "def f(c, x):\n"
        "    if c:\n"
        "        return len(x)\n"
        "    return str(x)\n"
    )
    assert infer_annotations(src) is None


def test_matching_builtin_return_types_agree():
    # Two value returns of the SAME provable type (both int) -> int.
    src = (
        "def f(c, x):\n"
        "    if c:\n"
        "        return len(x)\n"
        "    return ord(x)\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


# --- direct helper unit checks -----------------------------------------------

def test_helper_returns_none_for_non_call():
    import ast

    node = ast.parse("len", mode="eval").body  # a bare Name, not a Call
    assert _builtin_call_returns_type(node, frozenset()) is None


def test_helper_respects_assigned_names_arg():
    import ast

    node = ast.parse("len(x)", mode="eval").body
    assert _builtin_call_returns_type(node, frozenset()) == "int"
    assert _builtin_call_returns_type(node, frozenset({"len"})) is None


# --- behaviour preservation (fake-green canary) + determinism ----------------

def test_builtin_call_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the annotation adds `-> T` TEXT only and never changes
    # runtime behaviour. The annotated source must still parse, and the runtime
    # return value must be byte-identical to the original's.
    src = "def f(xs):\n    return len(xs)\n"
    out = infer_annotations(src)
    assert out == "def f(xs) -> int:\n    return len(xs)\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"]([1, 2, 3]) == new_ns["f"]([1, 2, 3]) == 3  # value unchanged
    assert "return" not in orig_ns["f"].__annotations__
    assert "int" in str(new_ns["f"].__annotations__.get("return"))
    assert type(new_ns["f"]([1, 2, 3])) is int


def test_shadowed_canary_runtime_matches_refusal():
    # The guard's soundness, made concrete: when `len` is shadowed the call
    # returns the LOCAL's value (here a str), NOT an int — so inferring `-> int`
    # would be a wrong-but-verified lie. We refuse, and prove the runtime really
    # would have diverged from the naive `-> int`.
    src = "def f(x):\n    len = x\n    return len(x)\n"
    assert infer_annotations(src) is None

    ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), ns)
    # `len` is rebound to the parameter, so `len(x)` here is `x(x)`; call with a
    # callable to observe the non-builtin result type.
    assert ns["f"](str) == "<class 'str'>"  # x(x) == str(str), a str not an int


def test_builtin_call_inference_is_deterministic():
    for src in (
        "def f(xs):\n    return len(xs)\n",
        "def f(x):\n    return sorted(x)\n",
        "def f(x):\n    return bool(x)\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    len = x\n    return len(x)\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_builtin_call_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(:\n    return len(x)\n") is None
