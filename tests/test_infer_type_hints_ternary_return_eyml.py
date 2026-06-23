"""infer-type-hints — sound RETURN inference from a conditional expression
(``ast.IfExp`` / ternary, a NOVEL capability layered on the LOCKED return-value
oracle).

A ternary's runtime value is EXACTLY one of its two branches — ``return X if C
else Y`` evaluates to ``X`` or to ``Y``, never to ``C`` — so its concrete type
is provable IFF BOTH branches independently prove to the SAME sound type via the
EXISTING return-value logic. ``return 'a' if c else 'b'`` ⇒ ``str``; otherwise
the ternary contributes NO type (refuse). The condition ``C`` is never inspected
(it does not affect the result type), and because each branch recurses through
the same resolver, every LOCKED soundness rule applies to each branch unchanged:
a branch that is an unsound ``==`` comparison, a ``/``/``**`` binop, a bare name,
or an unknown call refuses the whole ternary, two branches of DIFFERENT provable
types refuse, and a NESTED ternary proves only when every leaf agrees on type.

This composes with the existing logic with NO new top-level branching: a function
mixing a plain ``return 'x'`` and a ``return 'y' if c else 'z'`` lands ``-> str``
because all returns still resolve to the same type. A fake-green canary proves
the accept path annotates the REAL inferred type (str vs list produce different
annotations, never a hardcoded one), and a determinism + byte-identical check pin
input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _ifexp_same_type,
    _infer_return_type,
    _return_value_type,
    infer_annotations,
)


# --- ternary returns land a return type --------------------------------------

def test_infers_str_from_str_branches():
    src = "def f(c):\n    return 'a' if c else 'b'\n"
    assert infer_annotations(src) == (
        "def f(c) -> str:\n    return 'a' if c else 'b'\n")


def test_infers_list_from_list_branches():
    src = "def f(c):\n    return [1] if c else []\n"
    assert infer_annotations(src) == (
        "def f(c) -> list:\n    return [1] if c else []\n")


def test_infers_int_from_int_branches():
    src = "def f(c):\n    return 1 if c else 2\n"
    assert infer_annotations(src) == (
        "def f(c) -> int:\n    return 1 if c else 2\n")


def test_infers_when_plain_return_and_ternary_agree():
    # A plain ``return 'x'`` mixed with a same-type ternary: all returns resolve
    # to ``str``, so the function lands ``-> str`` (composes, no new branching).
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 'x'\n"
        "    return 'y' if c else 'z'\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c) -> str:")


def test_infers_nested_same_type_ternary():
    # A nested ternary proves by recursion when EVERY leaf is the same type.
    src = "def f(c, d):\n    return 1 if c else (2 if d else 3)\n"
    assert infer_annotations(src) == (
        "def f(c, d) -> int:\n    return 1 if c else (2 if d else 3)\n")


def test_infers_ternary_over_builtin_call_branches():
    # Each branch recurses through the FULL return-value oracle, so two same-type
    # FIXED-result builtin calls (both ``-> int``) prove the ternary -> int.
    src = "def f(c, x, y):\n    return len(x) if c else ord(y)\n"
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c, x, y) -> int:")


# --- refusals (the whole point: an unsound/mismatched branch refuses) --------

def test_refuses_mismatched_branch_types():
    # ``int`` vs ``str`` — the branches disagree, so NO annotation is added.
    src = "def f(c):\n    return 1 if c else 'x'\n"
    assert infer_annotations(src) is None


def test_refuses_branch_of_unknown_type():
    # ``foo()`` is an unknown call (not a FIXED-result builtin) -> that branch is
    # unprovable -> the whole ternary refuses.
    src = "def f(c):\n    return foo() if c else 'x'\n"
    assert infer_annotations(src) is None


def test_refuses_branch_that_is_unsound_eq_comparison():
    # ``a == b`` dispatches to an overridable ``__eq__`` (may return any type), so
    # a rich-comparison branch is NOT provably bool -> the ternary refuses (LOCKED
    # refusal preserved through the recursion).
    src = "def f(c, a, b):\n    return (a == b) if c else False\n"
    assert infer_annotations(src) is None


def test_refuses_branch_that_is_division():
    # ``/`` (Div) is not type-closed (``4 / 2 == 2.0``), so the literal-binop rule
    # refuses that branch -> the ternary refuses.
    src = "def f(c):\n    return (1 / 2) if c else 3\n"
    assert infer_annotations(src) is None


def test_refuses_branch_that_is_power():
    # ``**`` (Pow) escapes the operand type (``2 ** -1 == 0.5``) -> branch refuses
    # -> ternary refuses.
    src = "def f(c):\n    return (2 ** 3) if c else 4\n"
    assert infer_annotations(src) is None


def test_refuses_bare_name_branch():
    # A bare name is a value, not a type bound (the LOCKED no-param-from-use rule)
    # -> that branch is unprovable -> the ternary refuses.
    src = "def f(c, x):\n    return x if c else 'a'\n"
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_ifexp_same_type_accepts_matching_branches():
    node = ast.parse("'a' if c else 'b'", mode="eval").body
    assert _ifexp_same_type(node, frozenset()) == "str"


def test_ifexp_same_type_refuses_mismatched_branches():
    node = ast.parse("1 if c else 'x'", mode="eval").body
    assert _ifexp_same_type(node, frozenset()) is None


def test_ifexp_same_type_returns_none_for_non_ifexp():
    node = ast.parse("'a'", mode="eval").body
    assert _ifexp_same_type(node, frozenset()) is None


def test_ifexp_refuses_when_a_branch_uses_shadowed_builtin():
    # A branch builtin call is gated by the shadowing guard threaded through the
    # resolver: when ``len`` is shadowed, ``len(x)`` no longer resolves to the
    # builtin -> that branch is unprovable -> the ternary refuses.
    node = ast.parse("len(x) if c else 5", mode="eval").body
    assert _ifexp_same_type(node, frozenset({"len"})) is None
    # Without the shadow it proves -> int.
    assert _ifexp_same_type(node, frozenset()) == "int"


def test_return_value_type_routes_ifexp():
    # The new IfExp path lives INSIDE _return_value_type so it composes.
    node = ast.parse("[1] if c else [2]", mode="eval").body
    # Both branches prove to list[int] and JOIN to the precise parametrized type
    # (round 8); a mixed/empty branch would widen to bare `list`.
    assert _return_value_type(node, frozenset()) == "list[int]"


def test_infer_return_type_uses_ternary():
    fn = ast.parse("def f(c):\n    return 1 if c else 2\n").body[0]
    assert _infer_return_type(fn) == "int"


# --- fake-green canary + soundness made concrete -----------------------------

def test_ternary_annotation_reflects_real_inferred_type_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path must annotate the ACTUAL inferred type,
    # not a hardcoded constant. A str-branch ternary and a list-branch ternary
    # therefore produce DIFFERENT annotations (str vs list).
    str_src = "def f(c):\n    return 'a' if c else 'b'\n"
    list_src = "def f(c):\n    return [1] if c else [2]\n"
    str_out = infer_annotations(str_src)
    list_out = infer_annotations(list_src)
    assert str_out is not None and "-> str:" in str_out
    # [1] if c else [2] -> both list[int] -> joins to the parametrized type.
    assert list_out is not None and "-> list[int]:" in list_out
    assert str_out != list_out  # not a single hardcoded annotation


def test_ternary_annotation_preserves_parse_and_runtime_value():
    # The annotation adds `-> T` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, and the runtime return value must be
    # byte-identical to the original's for BOTH branches.
    src = "def f(c):\n    return 'a' if c else 'b'\n"
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(c) -> str:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"](True) == new_ns["f"](True) == "a"
    assert orig_ns["f"](False) == new_ns["f"](False) == "b"
    assert "return" in new_ns["f"].__annotations__
    assert "str" in str(new_ns["f"].__annotations__.get("return"))


def test_ternary_return_inference_is_deterministic():
    for src in (
        "def f(c):\n    return 'a' if c else 'b'\n",
        "def f(c):\n    return [1] if c else []\n",
        "def f(c, d):\n    return 1 if c else (2 if d else 3)\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(c):\n    return 1 if c else 'x'\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_file_without_qualifying_ternary_is_byte_identical():
    # A module with NO qualifying provable annotation is unchanged (None). A
    # mismatched-branch ternary alone adds nothing.
    src = "def f(c):\n    return 1 if c else 'x'\n"
    assert infer_annotations(src) is None
    # An already-annotated ternary return is never overwritten.
    annotated = "def f(c) -> object:\n    return 'a' if c else 'b'\n"
    assert infer_annotations(annotated) is None


def test_ternary_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(c):\n    return 'a' if c else\n") is None
