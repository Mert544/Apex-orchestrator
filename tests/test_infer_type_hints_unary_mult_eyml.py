"""infer-type-hints — sound RETURN inference for UNARY numeric ops and a
SEQUENCE/str ``*`` int literal product (Goal #E follow-ups).

Two NEW sound return-type rules, both LITERAL-operand only (no scope analysis):

  - a UNARY op on a numeric literal keeps the numeric type: ``-1``/``+1`` ⇒
    ``int``, ``-1.5``/``+1.5`` ⇒ ``float``, and ``~5`` ⇒ ``int`` — but ``~``
    is defined on ``int`` ONLY (``~1.5`` is a ``TypeError``), so a float under
    ``Invert`` REFUSES. See :func:`_unaryop_numeric_literal`.
  - a SEQUENCE/str ``*`` int literal product keeps the sequence's type:
    ``'a' * 3`` ⇒ ``str``, ``b'x' * 3`` ⇒ ``bytes``, ``[0] * 3`` ⇒ ``list``,
    ``(1,) * 2`` ⇒ ``tuple`` (either operand order). This is a MIXED-type
    product, so the existing SAME-type rule correctly does not cover it. See
    :func:`_mixed_sequence_int_mult`.

Both are SOUND because ``ast.Constant``/display operands are built-ins whose
dunders (``__neg__``/``__invert__``/``__mul__``/``__rmul__``) are not
instance-overridable, so the result type is provable from the AST. The suite
also pins every REFUSAL the soundness argument requires: a non-literal operand
(a name — a value is NOT a type bound, the LOCKED refusal), ``~`` on a float,
and a locked-untouched ``/`` (Div). A fake-green canary proves the landed
annotation changes no runtime value, and a determinism test pins input →
output stability.
"""

from __future__ import annotations

from app.execution.semantic.transforms.type_annotations import infer_annotations


# --- unary numeric literal lands --------------------------------------------

def test_infers_int_from_negated_int_literal():
    assert infer_annotations("def f():\n    return -1\n") == (
        "def f() -> int:\n    return -1\n")


def test_infers_float_from_negated_float_literal():
    assert infer_annotations("def f():\n    return -1.5\n") == (
        "def f() -> float:\n    return -1.5\n")


def test_infers_int_from_inverted_int_literal():
    # `~5` is an int — `~` (Invert) is defined on int.
    assert infer_annotations("def f():\n    return ~5\n") == (
        "def f() -> int:\n    return ~5\n")


def test_infers_int_from_unary_plus_int_literal():
    out = infer_annotations("def f():\n    return +7\n")
    assert out is not None and "-> int:" in out


def test_infers_float_from_unary_plus_float_literal():
    out = infer_annotations("def f():\n    return +2.5\n")
    assert out is not None and "-> float:" in out


# --- sequence/str * int literal lands ---------------------------------------

def test_infers_str_from_str_times_int():
    assert infer_annotations("def f():\n    return 'a' * 3\n") == (
        "def f() -> str:\n    return 'a' * 3\n")


def test_infers_list_from_list_times_int():
    assert infer_annotations("def f():\n    return [0] * 3\n") == (
        "def f() -> list:\n    return [0] * 3\n")


def test_infers_tuple_from_tuple_times_int():
    assert infer_annotations("def f():\n    return (1,) * 2\n") == (
        "def f() -> tuple:\n    return (1,) * 2\n")


def test_infers_bytes_from_bytes_times_int():
    out = infer_annotations("def f():\n    return b'x' * 3\n")
    assert out is not None and "-> bytes:" in out


def test_infers_str_from_int_times_str_reversed_order():
    # Either operand order: `3 * 'a'` is still a str.
    out = infer_annotations("def f():\n    return 3 * 'a'\n")
    assert out is not None and "-> str:" in out


def test_infers_list_from_int_times_list_reversed_order():
    out = infer_annotations("def f():\n    return 3 * [0]\n")
    assert out is not None and "-> list:" in out


# --- soundness refusals (the whole point) -----------------------------------

def test_refuses_unary_minus_on_name():
    # `-x` — `x` is a parameter of unknown type, a value is NOT a type bound.
    assert infer_annotations("def f(x):\n    return -x\n") is None


def test_refuses_invert_on_name():
    assert infer_annotations("def f(x):\n    return ~x\n") is None


def test_refuses_invert_on_float_literal():
    # `~1.5` is a TypeError — `~` is defined on int only, so Invert REFUSES a
    # float operand (no `-> float`, no `-> int`).
    assert infer_annotations("def f():\n    return ~1.5\n") is None


def test_refuses_unary_not_is_not_numeric_here():
    # `not x` is a bool via the certain-bool rule, NOT this numeric rule; and a
    # bare `not <name>` still resolves to bool (sanity: stays the bool path).
    out = infer_annotations("def f(x):\n    return not x\n")
    assert out is not None and "-> bool:" in out


def test_refuses_name_times_int():
    # `x * 3` — `x` is a value of unknown type, not a sequence type bound.
    assert infer_annotations("def f(x):\n    return x * 3\n") is None


def test_refuses_str_times_name():
    # `'a' * n` — the count is a name, but the rule needs an int LITERAL count.
    assert infer_annotations("def f(n):\n    return 'a' * n\n") is None


def test_refuses_division_stays_untouched():
    # Locked refusal preserved: `int / int` is a float, Div is excluded -> None.
    assert infer_annotations("def f():\n    return 1 / 2\n") is None


def test_refuses_bool_times_int_is_int_arithmetic():
    # `True * 3 == 3` is an int, not a bool; bool is not a sequence type, so the
    # sequence rule refuses, and the same-type rule refuses bool too -> None.
    assert infer_annotations("def f():\n    return True * 3\n") is None


# --- behaviour preservation (fake-green canary) + determinism ----------------

def test_unary_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the annotation adds `-> T` TEXT only and never changes
    # runtime behaviour. The annotated source must still parse, and the runtime
    # return value must be byte-identical to the original's.
    src = "def f():\n    return -1\n"
    out = infer_annotations(src)
    assert out == "def f() -> int:\n    return -1\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"]() == new_ns["f"]() == -1    # value unchanged
    assert "return" not in orig_ns["f"].__annotations__
    assert "int" in str(new_ns["f"].__annotations__.get("return"))
    assert type(new_ns["f"]()) is int


def test_mult_annotation_preserves_parse_and_runtime_value():
    src = "def f():\n    return 'a' * 3\n"
    out = infer_annotations(src)
    assert out == "def f() -> str:\n    return 'a' * 3\n"

    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)
    assert new_ns["f"]() == "aaa"
    assert type(new_ns["f"]()) is str


def test_unary_mult_inference_is_deterministic():
    for src in (
        "def f():\n    return -1\n",
        "def f():\n    return ~5\n",
        "def f():\n    return 'a' * 3\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    return -x\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_unary_mult_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def (:\n") is None
