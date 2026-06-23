"""infer-type-hints — sound RETURN inference for printf-style ``%`` formatting.

Capability C2 (expand sound return-type inference): a ``return <str|bytes> % x``
(an ``ast.Mod`` BinOp) whose LEFT operand is PROVABLY ``str`` or ``bytes``
resolves to that type — ``'%s' % x`` ⇒ ``str``, ``b'%s' % x`` ⇒ ``bytes``,
``'%d' % 5`` ⇒ ``str``. ``str.__mod__`` / ``bytes.__mod__`` are non-overridable
C-slot operations that ALWAYS return the LHS's own type when they return at all
(a malformed format string raises, a never-returns path that keeps ``-> str`` /
``-> bytes`` sound), so the RIGHT operand is deliberately NOT inspected.

This is DISJOINT from the same-type-literal rule: ``int % int`` ⇒ ``int`` and
``n % 2`` (bare-Name LHS) ⇒ refuse are both UNCHANGED. The suite pins the new
lands, the locked refusals, the ``5 % 2 -> int`` non-regression, a fake-green
parse+runtime canary, and the ``_percent_format_type`` helper directly.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _percent_format_type,
    infer_annotations,
)


def _expr(src: str) -> ast.expr:
    """Parse a single expression string into its ``ast.expr`` node."""
    return ast.parse(src, mode="eval").body


# --- the new printf shape lands ---------------------------------------------

def test_infers_str_from_str_percent_name():
    assert infer_annotations("def f(x):\n    return '%s' % x\n") == (
        "def f(x) -> str:\n    return '%s' % x\n")


def test_infers_str_from_str_percent_tuple():
    # ``'%s=%s' % (a, b)`` — a tuple RHS; LHS is a str literal -> str.
    assert infer_annotations("def f(a, b):\n    return '%s=%s' % (a, b)\n") == (
        "def f(a, b) -> str:\n    return '%s=%s' % (a, b)\n")


def test_infers_str_from_str_percent_int_literal():
    # The headline gap: ``str % int`` (mixed types) -> str. The same-type rule
    # refuses this (operands differ); the percent rule lands it.
    assert infer_annotations("def f():\n    return '%d' % 5\n") == (
        "def f() -> str:\n    return '%d' % 5\n")


def test_infers_bytes_from_bytes_percent_name():
    assert infer_annotations("def f(x):\n    return b'%s' % x\n") == (
        "def f(x) -> bytes:\n    return b'%s' % x\n")


def test_infers_str_from_fstring_lhs_percent():
    # An f-string LHS is provably str (recursively) -> the ``%`` lands str.
    out = infer_annotations("def f(n, x):\n    return f'{n}%s' % x\n")
    assert out is not None and "-> str:" in out


def test_percent_agrees_across_arms():
    # Two arms, each a str-percent format -> agree on str.
    src = (
        "def f(x, y):\n"
        "    if x:\n"
        "        return '%s' % x\n"
        "    return '%d' % y\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> str:" in out


# --- soundness refusals + disjointness from the same-type rule --------------

def test_refuses_name_percent_int():
    # ``n % 2`` — a bare-Name LHS is NOT provably str/bytes (and not provably
    # int either) -> refuse. The percent rule must not over-claim on a name.
    assert infer_annotations("def f(n):\n    return n % 2\n") is None


def test_refuses_two_names_percent():
    assert infer_annotations("def f(x, y):\n    return x % y\n") is None


def test_int_percent_int_still_infers_int_no_regression():
    # NON-REGRESSION: ``5 % 2`` stays ``int`` via the same-type rule (the percent
    # rule returns None because the LHS is int, not str/bytes).
    assert infer_annotations("def f():\n    return 5 % 2\n") == (
        "def f() -> int:\n    return 5 % 2\n")


def test_str_percent_str_still_infers_str():
    # Both rules agree on str here; order is harmless.
    out = infer_annotations("def f():\n    return '%s' % 'x'\n")
    assert out is not None and "-> str:" in out


def test_float_percent_float_still_infers_float():
    # ``1.5 % 2.0`` -> float via the same-type rule (LHS float, not str/bytes).
    out = infer_annotations("def f():\n    return 1.5 % 2.0\n")
    assert out is not None and "-> float:" in out


def test_non_mod_binop_unaffected():
    # A non-Mod BinOp on a str literal (``'a' + x``) is not the percent rule and
    # the same-type rule refuses (x is a name) -> refuse.
    assert infer_annotations("def f(x):\n    return 'a' + x\n") is None


# --- _percent_format_type unit (the new helper) -----------------------------

def test_helper_str_lhs_returns_str():
    assert _percent_format_type(_expr("'%s' % x")) == "str"


def test_helper_bytes_lhs_returns_bytes():
    assert _percent_format_type(_expr("b'%s' % x")) == "bytes"


def test_helper_int_lhs_returns_none():
    # LHS provable but int (not str/bytes) -> None (lets same-type handle it).
    assert _percent_format_type(_expr("5 % 2")) is None


def test_helper_name_lhs_returns_none():
    assert _percent_format_type(_expr("n % 2")) is None


def test_helper_non_mod_binop_returns_none():
    # ``'a' + 'b'`` is a BinOp but NOT ast.Mod -> None.
    assert _percent_format_type(_expr("'a' + 'b'")) is None


def test_helper_non_binop_returns_none():
    # A non-BinOp node (a bare str constant) -> None.
    assert _percent_format_type(_expr("'a'")) is None


# --- behaviour preservation (fake-green canary) + determinism ---------------

def test_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the rewrite adds ``-> str`` TEXT only and never changes
    # runtime behaviour. The annotated source must still parse, and the runtime
    # return value must be byte-identical to the original's.
    src = "def f(x):\n    return '%s' % x\n"
    out = infer_annotations(src)
    assert out == "def f(x) -> str:\n    return '%s' % x\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"](7) == new_ns["f"](7) == "7"  # value unchanged
    assert "return" not in orig_ns["f"].__annotations__
    assert "str" in str(new_ns["f"].__annotations__.get("return"))
    assert type(new_ns["f"](7)) is str


def test_bytes_annotation_preserves_runtime_value():
    src = "def f(x):\n    return b'%s' % x\n"
    out = infer_annotations(src)
    assert out == "def f(x) -> bytes:\n    return b'%s' % x\n"

    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs
    assert new_ns["f"](b"hi") == b"hi"
    assert type(new_ns["f"](b"hi")) is bytes


def test_percent_inference_is_deterministic():
    src = "def f(x):\n    return '%s' % x\n"
    assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(n):\n    return n % 2\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_empty_and_unparseable_paths():
    assert infer_annotations("") is None
    assert infer_annotations("def (:\n") is None
