"""Characterization tests for ``percent_string_concat.apply`` after refactor.

These pin the exact rewrite output, skip conditions, and determinism of the
constant-fold transform so the decomposition into pure helpers stays byte-exact.
"""

from app.execution.semantic.transforms import percent_string_concat as pscc


def _new_content(res):
    assert res is not None
    return res.patch_requests[0]["new_content"]


def test_basic_double_quote_fold():
    res = pscc.apply("m.py", 'x = "a" + "b"\n', "t")
    assert _new_content(res) == 'x = "ab"\n'
    assert res.transform_type == "fold_string_concat"


def test_basic_single_quote_fold():
    res = pscc.apply("m.py", "x = 'a' + 'b'\n", "t")
    assert _new_content(res) == "x = 'ab'\n"


def test_chain_folds_innermost_pair_only():
    # Only the inner ``"a" + "b"`` BinOp has two Constant operands; the outer
    # BinOp's left is itself a BinOp, so it is not foldable in one pass.
    res = pscc.apply("m.py", 'x = "a" + "b" + "c"\n', "t")
    assert _new_content(res) == 'x = "ab" + "c"\n'


def test_multiple_lines_each_folded():
    res = pscc.apply("m.py", 'a = "x" + "y"\nb = "p" + "q"\n', "t")
    assert _new_content(res) == 'a = "xy"\nb = "pq"\n'


def test_rationale_counts_folds():
    res = pscc.apply("pkg/m.py", 'a = "x" + "y"\nb = "p" + "q"\n', "t")
    assert "Folded 2 adjacent" in res.rationale[0]
    assert "pkg/m.py" in res.rationale[0]


def test_path_threaded_into_request():
    res = pscc.apply("some/path.py", 'x = "a" + "b"\n', "t")
    assert res.patch_requests[0]["path"] == "some/path.py"
    assert res.patch_requests[0]["expected_old_content"] == 'x = "a" + "b"\n'


def test_mixed_quotes_refused():
    assert pscc.apply("m.py", 'x = "a" + \'b\'\n', "t") is None


def test_prefixed_literals_refused():
    assert pscc.apply("m.py", 'x = r"a" + "b"\n', "t") is None
    assert pscc.apply("m.py", 'x = b"a" + b"b"\n', "t") is None
    assert pscc.apply("m.py", 'x = f"a" + "b"\n', "t") is None


def test_non_string_operand_refused():
    assert pscc.apply("m.py", 'x = "a" + 2\n', "t") is None
    assert pscc.apply("m.py", 'x = foo + "b"\n', "t") is None


def test_escape_in_literal_refused():
    assert pscc.apply("m.py", 'x = "a\\n" + "b"\n', "t") is None
    assert pscc.apply("m.py", 'x = "quote\\"" + "b"\n', "t") is None


def test_other_quote_char_inside_is_allowed():
    # A single-quote inside a double-quoted literal is fine: only the literal's
    # OWN quote char must not appear inside it.
    res = pscc.apply("m.py", 'x = "I\'m" + "ok"\n', "t")
    assert _new_content(res) == 'x = "I\'mok"\n'


def test_multiline_binop_refused():
    assert pscc.apply("m.py", 'y = (\n    "a"\n    + "b"\n)\n', "t") is None


def test_syntax_error_returns_none():
    assert pscc.apply("m.py", "this is not python +++\n", "t") is None


def test_no_targets_returns_none():
    assert pscc.apply("m.py", 'x = "a" * 3\n', "t") is None


def test_empty_source_returns_none():
    assert pscc.apply("m.py", "", "t") is None


def test_empty_string_fold():
    res = pscc.apply("m.py", 'x = "a" + ""\n', "t")
    assert _new_content(res) == 'x = "a"\n'


def test_determinism_repeated_calls():
    src = 'a = "x" + "y"\nb = "p" + "q"\n'
    first = pscc.apply("m.py", src, "t")
    for _ in range(5):
        again = pscc.apply("m.py", src, "t")
        assert _new_content(again) == _new_content(first)
        assert again.rationale == first.rationale


def test_ascii_fold_preserves_trailing_newline():
    res = pscc.apply("m.py", 'x = "foo" + "bar"\n', "t")
    assert _new_content(res) == 'x = "foobar"\n'
