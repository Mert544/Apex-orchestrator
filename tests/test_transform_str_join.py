"""Tests for the adjacent string-literal constant-fold transform.

``"a" + "b"`` -> ``"ab"`` ONLY when both operands are simple, escape-free string
literals sharing the same quote. Everything else refuses; the file is never
corrupted and folded values are always equivalent under ``literal_eval``.
"""

import ast

from app.execution.semantic.transforms import percent_string_concat as T


def _apply(source: str):
    return T.apply("m.py", source, "title")


def _new_content(source: str) -> str | None:
    res = _apply(source)
    if res is None:
        return None
    return res.patch_requests[0]["new_content"]


# --- Folds -------------------------------------------------------------------

def test_double_quote_fold():
    out = _new_content('x = "a" + "b"\n')
    assert out == 'x = "ab"\n'


def test_single_quote_fold():
    out = _new_content("x = 'x' + 'y'\n")
    assert out == "x = 'xy'\n"


def test_fold_with_spaces_inside():
    out = _new_content('x = "hello " + "world"\n')
    assert out == 'x = "hello world"\n'


def test_result_parses_and_is_value_equivalent():
    src = 'x = "foo" + "bar"\n'
    out = _new_content(src)
    assert out is not None
    new_val = ast.literal_eval(out.split("=", 1)[1].strip())
    assert new_val == "foobar"


def test_transform_type_and_rationale():
    res = _apply('x = "a" + "b"\n')
    assert res is not None
    assert res.transform_type == "fold_string_concat"
    assert res.rationale and "m.py" in res.rationale[0]


# --- Refusals ----------------------------------------------------------------

def test_refuse_name_operand():
    assert _apply('x = a + "b"\n') is None


def test_refuse_name_operand_right():
    assert _apply('x = "a" + b\n') is None


def test_refuse_number_operand():
    assert _apply('x = "a" + 1\n') is None


def test_refuse_fstring_operand():
    assert _apply('x = "a" + f"b{q}"\n') is None


def test_refuse_mixed_quotes():
    assert _apply('''x = "a" + 'b'\n''') is None


def test_refuse_string_with_escape():
    # Backslash escape in a literal — refuse rather than re-derive escaping.
    assert _apply(r'x = "a\n" + "b"' + "\n") is None


def test_refuse_string_with_embedded_quote():
    # Folding would put a `"` inside a `"`-quoted literal.
    assert _apply(r'''x = "a\"q" + "b"''' + "\n") is None


def test_refuse_aug_assign():
    # `+=` is an AugAssign, never a foldable BinOp pair.
    assert _apply('x = "a"\nx += "b"\n') is None


def test_refuse_multiline_span():
    src = 'x = ("a"\n     + "b")\n'
    assert _apply(src) is None


def test_refuse_bytes_operand():
    assert _apply('x = b"a" + b"b"\n') is None


def test_refuse_raw_string_prefix():
    # Raw-string prefix means the segment isn't a bare quote; refuse.
    assert _apply('x = r"a" + r"b"\n') is None


def test_nested_chain_folds_only_inner_pair():
    # `"a" + "b" + "c"` parses as `("a" + "b") + "c"`. The inner pair is a
    # foldable Constant/Constant BinOp; the outer's left operand is a BinOp
    # (not a Constant), so the outer refuses. Result is value-equivalent and
    # still parses cleanly.
    out = _new_content('x = "a" + "b" + "c"\n')
    assert out == 'x = "ab" + "c"\n'
    ast.parse(out)


def test_no_targets_returns_none():
    assert _apply("x = 1 + 2\n") is None


def test_syntax_error_returns_none():
    assert _apply("def (:\n") is None


# --- Determinism & robustness ------------------------------------------------

def test_determinism():
    src = 'x = "a" + "b"\ny = "c" + "d"\n'
    first = _new_content(src)
    for _ in range(5):
        assert _new_content(src) == first


def test_output_always_parses():
    src = 'x = "a" + "b"\ny = "p" + "q"\n'
    out = _new_content(src)
    assert out is not None
    ast.parse(out)  # must not raise


def test_multiple_folds_on_distinct_lines():
    src = 'x = "a" + "b"\ny = "c" + "d"\n'
    out = _new_content(src)
    assert out == 'x = "ab"\ny = "cd"\n'
