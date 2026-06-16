"""Characterization tests pinning the byte-for-byte output of the two
decomposed transform ``apply`` functions.

Each ``apply`` was split into small pure helpers; these tests exercise the
convertible / must-NOT-convert corpus end to end and assert the exact emitted
``new_content`` (or ``None`` skip) so any future change that alters behaviour
is caught immediately.
"""

from __future__ import annotations

from app.execution.semantic.transforms import not_in_simplify as nis
from app.execution.semantic.transforms import simplify_comparison as sc


def _cmp(src: str) -> str | None:
    r = sc.apply("m.py", src, "simplify comparison")
    return r.patch_requests[0]["new_content"] if r else None


def _not_in(src: str) -> str | None:
    r = nis.apply("m.py", src, "simplify not-in")
    return r.patch_requests[0]["new_content"] if r else None


# --- simplify_comparison: convertible -------------------------------------

def test_cmp_eq_none():
    assert _cmp("x == None\n") == "x is None\n"


def test_cmp_ne_none():
    assert _cmp("x != None\n") == "x is not None\n"


def test_cmp_none_on_left_normalises():
    assert _cmp("None == x\n") == "x is None\n"
    assert _cmp("None != x\n") == "x is not None\n"


def test_cmp_preserves_surrounding_line():
    assert _cmp("if x == None:\n    pass\n") == "if x is None:\n    pass\n"


def test_cmp_preserves_trailing_comment():
    assert _cmp("d == None  # trailing comment\n") == "d is None  # trailing comment\n"


def test_cmp_multiple_on_one_line():
    assert _cmp("lst = [a == None, b != None]\n") == "lst = [a is None, b is not None]\n"


def test_cmp_subscript_operand():
    assert _cmp("config[key] == None\n") == "config[key] is None\n"


def test_cmp_tight_spacing():
    assert _cmp("x==None\n") == "x is None\n"


# --- simplify_comparison: must NOT convert / skip --------------------------

def test_cmp_skips_double_none():
    assert _cmp("None == None\n") is None


def test_cmp_skips_bool_compare():
    assert _cmp("x == True\n") is None
    assert _cmp("x != False\n") is None


def test_cmp_skips_already_identity():
    assert _cmp("x is None\n") is None


def test_cmp_skips_non_eq():
    assert _cmp("x < None\n") is None


def test_cmp_skips_chained():
    assert _cmp("a == None == b\n") is None


def test_cmp_rewrites_compare_on_own_line():
    # The wrapping statement spans lines, but the ``Compare`` node itself is
    # single-line, so the splice applies.
    assert _cmp("if (\n    a == None\n):\n    pass\n") == (
        "if (\n    a is None\n):\n    pass\n"
    )


def test_cmp_skips_syntax_error():
    assert _cmp("this is not valid !!!") is None


def test_cmp_skips_empty():
    assert _cmp("") is None


# --- not_in_simplify: convertible -----------------------------------------

def test_not_in_basic():
    assert _not_in("x = not a in b\n") == "x = a not in b\n"


def test_not_is_basic():
    assert _not_in("y = not a is b\n") == "y = a is not b\n"


def test_not_in_statement_context():
    assert _not_in("if not a in b:\n    pass\n") == "if a not in b:\n    pass\n"


def test_not_in_nested_double_not():
    assert _not_in("not not a in b\n") == "not a not in b\n"


def test_not_in_attribute_operand():
    assert _not_in("not obj.attr is None\n") == "obj.attr is not None\n"


# --- not_in_simplify: must NOT convert / skip ------------------------------

def test_not_in_skips_already_negated():
    assert _not_in("not a not in b\n") is None
    assert _not_in("not a is not b\n") is None


def test_not_in_skips_eq():
    assert _not_in("not a == b\n") is None


def test_not_in_skips_lt():
    assert _not_in("not a < b\n") is None


def test_not_in_skips_chained_compare():
    assert _not_in("not a < b < c\n") is None
    assert _not_in("not a in b in c\n") is None


def test_not_in_skips_non_compare():
    assert _not_in("not (a and b)\n") is None


def test_not_in_skips_already_idiomatic():
    assert _not_in("a not in b\n") is None
    assert _not_in("a is not b\n") is None


def test_not_in_skips_syntax_error():
    assert _not_in("this is not valid !!!") is None


def test_not_in_skips_empty():
    assert _not_in("") is None


# --- shared: rationale count reflects number of rewrites -------------------

def test_cmp_rationale_count():
    r = sc.apply("m.py", "lst = [a == None, b != None]\n", "t")
    assert r is not None
    assert "Rewrote 2 `None` comparison(s)" in r.rationale[0]


def test_not_in_rationale_count():
    r = nis.apply("m.py", "if not k in d and not v is None:\n    pass\n", "t")
    assert r is not None
    assert "Rewrote 2 negated comparison(s)" in r.rationale[0]
