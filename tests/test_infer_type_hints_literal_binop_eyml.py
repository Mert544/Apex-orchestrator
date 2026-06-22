"""infer-type-hints — sound RETURN inference for a SAME-TYPE-LITERAL binary op.

Goal #E (expand sound return-type inference): a ``return <lit> <op> <lit>`` whose
two operands are PROVABLY the same concrete type and whose operator is type-closed
(``+``/``-``/``*``/``%``/``//``) resolves to that type — ``1 + 2`` ⇒ ``int``,
``'a' + 'b'`` ⇒ ``str``, ``[1] + [2]`` ⇒ ``list``, ``(1,) + (2,)`` ⇒ ``tuple``.

These are SOUND because ``ast.Constant``/display operands are built-ins whose dunder
ops are not instance-overridable, so the result type is provable from the AST. The
suite below also pins every REFUSAL the soundness argument requires: a non-literal
operand (a name/call/attr — a value is NOT a type bound), a mixed-type pair, ``/``
(``int/int`` ⇒ float), ``**`` (``2 ** -1`` ⇒ float, ``(-2.0) ** 0.5`` ⇒ complex —
both escape the operand type), bitwise/shift ops, and a ``bool`` operand
(``True + True == 2`` is an int, so bool must NOT be reported). A fake-green canary
proves the landed annotation changes no runtime value, and a determinism test pins
input → output stability.
"""

from __future__ import annotations

from app.execution.semantic.transforms.type_annotations import infer_annotations


# --- the new sound shape lands ----------------------------------------------

def test_infers_int_from_two_int_literals():
    assert infer_annotations("def f():\n    return 1 + 2\n") == (
        "def f() -> int:\n    return 1 + 2\n")


def test_infers_str_from_two_str_literals():
    assert infer_annotations("def f():\n    return 'a' + 'b'\n") == (
        "def f() -> str:\n    return 'a' + 'b'\n")


def test_infers_list_from_two_list_displays():
    # `[1] + [2]` — the operands are `ast.List` (NOT `ast.Constant`), but both
    # are provably `list` and `+` is type-closed over lists -> list.
    assert infer_annotations("def f():\n    return [1] + [2]\n") == (
        "def f() -> list:\n    return [1] + [2]\n")


def test_infers_tuple_from_two_tuple_displays():
    assert infer_annotations("def f():\n    return (1,) + (2,)\n") == (
        "def f() -> tuple:\n    return (1,) + (2,)\n")


def test_infers_float_from_two_float_literals():
    out = infer_annotations("def f():\n    return 1.5 * 2.0\n")
    assert out is not None and "-> float:" in out


def test_infers_bytes_from_two_bytes_literals():
    out = infer_annotations("def f():\n    return b'a' + b'b'\n")
    assert out is not None and "-> bytes:" in out


def test_infers_each_safe_operator():
    # Every type-closed op resolves over two int literals.
    for op in ("+", "-", "*", "%", "//"):
        out = infer_annotations(f"def f():\n    return 4 {op} 2\n")
        assert out is not None and "-> int:" in out, op


def test_binop_inference_agrees_across_arms():
    # Two arms, both same-type-literal binops of the same kind -> agree on int.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1 + 2\n"
        "    else:\n"
        "        return 3 * 4\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


def test_binop_agrees_with_plain_literal_arm():
    # A plain int literal and an int binop agree on int.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 5\n"
        "    else:\n"
        "        return 1 + 2\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> int:" in out


# --- soundness refusals (the whole point) -----------------------------------

def test_refuses_name_operand():
    # `x` is a parameter of unknown type — a value is NOT a type bound -> refuse.
    assert infer_annotations("def f(x):\n    return x + 1\n") is None


def test_refuses_two_name_operands():
    # The locked existing refusal: `a + b` (both names) stays None.
    assert infer_annotations("def f(a, b):\n    return a + b\n") is None


def test_refuses_call_operand():
    assert infer_annotations("def f(x):\n    return len(x) + 1\n") is None


def test_refuses_attribute_operand():
    assert infer_annotations("def f(o):\n    return o.n + 1\n") is None


def test_refuses_mixed_type_literals():
    # `int` + `str` operands disagree -> not provably one type -> refuse.
    assert infer_annotations("def f():\n    return 1 + 'a'\n") is None


def test_refuses_int_float_mixed_literals():
    assert infer_annotations("def f():\n    return 1 + 2.0\n") is None


def test_refuses_division():
    # `int / int` is ALWAYS a float (`4 / 2 == 2.0`) -> not same-type -> Div is
    # left out of the safe set entirely -> refuse.
    assert infer_annotations("def f():\n    return 1 / 2\n") is None


def test_refuses_power():
    # `2 ** -1 == 0.5` (float from two ints) and `(-2.0) ** 0.5` is complex —
    # Pow escapes the operand type, so it is unsound and excluded -> refuse.
    assert infer_annotations("def f():\n    return 2 ** 3\n") is None


def test_refuses_bool_operands():
    # `True + True == 2` is an `int`, so a bool operand must NOT be reported as
    # `bool` for `+` -> refuse rather than land a wrong `-> bool`.
    assert infer_annotations("def f():\n    return True + True\n") is None


def test_refuses_bitwise_and_shift_operators():
    for op in ("|", "&", "^", "<<", ">>"):
        assert infer_annotations(f"def f():\n    return 1 {op} 2\n") is None, op


def test_refuses_binop_mixed_with_non_literal_arm():
    # One arm is a sound int binop, the other a bare name (not provable) -> the
    # whole function refuses (the existing disagreement rule is preserved).
    src = (
        "def f(c, y):\n"
        "    if c:\n"
        "        return 1 + 2\n"
        "    else:\n"
        "        return y\n"
    )
    assert infer_annotations(src) is None


def test_refuses_binop_mixed_with_disagreeing_literal():
    # An int binop arm and a str literal arm disagree -> refuse.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1 + 2\n"
        "    else:\n"
        "        return 'x'\n"
    )
    assert infer_annotations(src) is None


# --- behaviour preservation (fake-green canary) + determinism ----------------

def test_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the annotation must add `-> T` TEXT only and never
    # change runtime behaviour. The annotated source must still parse, and the
    # function's runtime return value must be byte-identical to the original's.
    src = "def f():\n    return 1 + 2\n"
    out = infer_annotations(src)
    assert out == "def f() -> int:\n    return 1 + 2\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"]() == new_ns["f"]() == 3     # value unchanged
    # The original had NO annotation; the rewrite adds a `return` hint as TEXT
    # only (its repr names `int`) — the runtime value stays a plain `int`.
    assert "return" not in orig_ns["f"].__annotations__
    assert "int" in str(new_ns["f"].__annotations__.get("return"))
    assert type(new_ns["f"]()) is int


def test_binop_inference_is_deterministic():
    src = "def f():\n    return 1 + 2\n"
    assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    return x + 1\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def (:\n") is None
