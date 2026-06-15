from __future__ import annotations

import ast

from app.execution.semantic.transforms import isinstance_merge as im


def _apply(src: str) -> str | None:
    r = im.apply("m.py", src, "merge isinstance")
    return r.patch_requests[0]["new_content"] if r else None


def _reparses(src: str) -> bool:
    try:
        ast.parse(src)
    except SyntaxError:
        return False
    return True


def _semantically_equal(orig: str, new: str, values: list[object]) -> bool:
    """``f`` from each source must agree on every probe value."""
    ns_old: dict[str, object] = {}
    ns_new: dict[str, object] = {}
    exec(orig, ns_old)
    exec(new, ns_new)
    f_old, f_new = ns_old["f"], ns_new["f"]
    return all(f_old(v) == f_new(v) for v in values)


# --- merges --------------------------------------------------------------


def test_two_way_merge():
    src = "def f(x):\n    return isinstance(x, int) or isinstance(x, float)\n"
    out = _apply(src)
    assert out is not None
    assert "isinstance(x, (int, float))" in out
    assert " or " not in out
    assert _reparses(out)
    assert _semantically_equal(src, out, [1, 1.5, "s", None, True])


def test_three_way_merge():
    src = (
        "def f(x):\n"
        "    return isinstance(x, int) or isinstance(x, float) or isinstance(x, complex)\n"
    )
    out = _apply(src)
    assert out is not None
    assert "isinstance(x, (int, float, complex))" in out
    assert " or " not in out
    assert _reparses(out)
    assert _semantically_equal(src, out, [1, 1.5, 2j, "s", None])


def test_attribute_chain_target_merges():
    src = "def f(a):\n    return isinstance(a.b, int) or isinstance(a.b, str)\n"
    out = _apply(src)
    assert out is not None
    assert "isinstance(a.b, (int, str))" in out
    assert _reparses(out)


def test_result_is_semantically_equal_and_short_circuits_target_once():
    # `or` evaluates the target twice; the merged form evaluates it once. For a
    # pure target both observe the same value, so behaviour is preserved.
    src = "def f(x):\n    return isinstance(x, bool) or isinstance(x, int)\n"
    out = _apply(src)
    assert out is not None
    assert _semantically_equal(src, out, [True, 0, 1, "s", 3.0])


# --- refusals (return None) ---------------------------------------------


def test_refuses_different_targets():
    src = "def f(x, y):\n    return isinstance(x, int) or isinstance(y, str)\n"
    assert _apply(src) is None


def test_refuses_mixed_unrelated_or_term():
    src = "def f(x):\n    return isinstance(x, int) or x is None\n"
    assert _apply(src) is None


def test_refuses_mixed_unrelated_term_between_isinstances():
    src = (
        "def f(x):\n"
        "    return isinstance(x, int) or x > 0 or isinstance(x, float)\n"
    )
    assert _apply(src) is None


def test_refuses_side_effect_target():
    src = "def f(g):\n    return isinstance(g(), int) or isinstance(g(), str)\n"
    assert _apply(src) is None


def test_refuses_subscript_target():
    src = "def f(d):\n    return isinstance(d[0], int) or isinstance(d[0], str)\n"
    assert _apply(src) is None


def test_refuses_already_tuple_form_mixed_in():
    src = "def f(x):\n    return isinstance(x, (int, float)) or isinstance(x, str)\n"
    assert _apply(src) is None


def test_refuses_single_isinstance():
    src = "def f(x):\n    return isinstance(x, int)\n"
    assert _apply(src) is None


def test_refuses_and_not_or():
    src = "def f(x):\n    return isinstance(x, int) and isinstance(x, float)\n"
    assert _apply(src) is None


def test_refuses_keyword_isinstance():
    # `isinstance(x, int, foo=1)` is not a plain 2-arg call.
    src = "def f(x):\n    return isinstance(x, int) or isinstance(x, str, foo=1)\n"
    assert _apply(src) is None


def test_no_change_returns_none():
    src = "def f(x):\n    return x or None\n"
    assert _apply(src) is None


# --- robustness ----------------------------------------------------------


def test_syntax_error_returns_none():
    assert im.apply("m.py", "def f(:\n    pass\n", "t") is None


def test_multiline_or_is_skipped():
    src = (
        "def f(x):\n"
        "    return (\n"
        "        isinstance(x, int)\n"
        "        or isinstance(x, float)\n"
        "    )\n"
    )
    # Multi-line spans are skipped to keep the splice exact; nothing changes.
    assert _apply(src) is None


def test_determinism():
    src = "def f(x):\n    return isinstance(x, int) or isinstance(x, float)\n"
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_idempotent():
    src = "def f(x):\n    return isinstance(x, int) or isinstance(x, float)\n"
    out = _apply(src)
    assert out is not None
    assert _apply(out) is None  # merged form has no `or` left to merge


def test_never_emits_unparseable_output():
    # A spread of inputs: whatever comes back must always parse.
    cases = [
        "def f(x):\n    return isinstance(x, int) or isinstance(x, float)\n",
        "def f(x):\n    return isinstance(x, int) or isinstance(x, float) or isinstance(x, str)\n",
        "def f(a):\n    return isinstance(a.b.c, int) or isinstance(a.b.c, str)\n",
        "def f(x, y):\n    return isinstance(x, int) or isinstance(y, str)\n",
        "x = isinstance(v, int) or isinstance(v, float)\n",
        "if isinstance(v, int) or isinstance(v, str):\n    pass\n",
    ]
    for src in cases:
        out = _apply(src)
        if out is not None:
            assert _reparses(out)


def test_empty_source_returns_none():
    assert _apply("") is None


def test_multiple_independent_merges_on_one_line():
    src = (
        "def f(x, y):\n"
        "    return (isinstance(x, int) or isinstance(x, float)) "
        "and (isinstance(y, int) or isinstance(y, str))\n"
    )
    out = _apply(src)
    assert out is not None
    assert "isinstance(x, (int, float))" in out
    assert "isinstance(y, (int, str))" in out
    assert _reparses(out)
