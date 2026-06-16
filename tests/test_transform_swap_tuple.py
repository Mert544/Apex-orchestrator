from __future__ import annotations

import ast

from app.execution.semantic.transforms import swap_via_tuple as swap_t


def _apply(src: str) -> str | None:
    r = swap_t.apply("m.py", src, "swap via tuple")
    return r.patch_requests[0]["new_content"] if r else None


def _run(src: str, fn: str, *args):
    """Compile ``src``, call ``fn`` with ``args``, return its result.

    Used to confirm the rewrite is behaviour-preserving across input space.
    """
    ns: dict = {}
    exec(compile(src, "<t>", "exec"), ns)  # noqa: S102 - trusted test fixtures
    return ns[fn](*args)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_canonical_swap_collapses_to_tuple():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
    )
    out = _apply(src)
    assert out is not None
    assert "a, b = b, a\n" in out
    assert "tmp" not in out
    ast.parse(out)
    # Three lines collapsed into one.
    assert out.count("\n") == src.count("\n") - 2


def test_semantically_equal_after_swap():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
    )
    out = _apply(src)
    assert out is not None
    for a, b in [(1, 2), ("x", "y"), (None, 0), ([1], [2])]:
        assert _run(out, "f", a, b) == _run(src, "f", a, b) == (b, a)


def test_indentation_preserved_in_nested_block():
    src = (
        "def f(a, b, flag):\n"
        "    if flag:\n"
        "        tmp = a\n"
        "        a = b\n"
        "        b = tmp\n"
        "    return a, b\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    assert "        a, b = b, a\n" in out
    assert _run(out, "f", 1, 2, True) == (2, 1)
    assert _run(out, "f", 1, 2, False) == (1, 2)


def test_custom_temp_name():
    src = (
        "def f(x, y):\n"
        "    spare = x\n"
        "    x = y\n"
        "    y = spare\n"
        "    return x, y\n"
    )
    out = _apply(src)
    assert out is not None
    assert "x, y = y, x\n" in out
    assert "spare" not in out
    assert _run(out, "f", 3, 4) == (4, 3)


# --------------------------------------------------------------------------- #
# Refusals -> None
# --------------------------------------------------------------------------- #
def test_refuses_attribute_target():
    # obj.a = ... can double-evaluate / re-order under a tuple swap -> refuse.
    src = (
        "def f(obj, b):\n"
        "    tmp = obj.a\n"
        "    obj.a = b\n"
        "    b = tmp\n"
        "    return b\n"
    )
    assert _apply(src) is None


def test_refuses_subscript_target():
    src = (
        "def f(d, b):\n"
        "    tmp = d['a']\n"
        "    d['a'] = b\n"
        "    b = tmp\n"
        "    return b\n"
    )
    assert _apply(src) is None


def test_refuses_tmp_reused_later():
    # tmp survives the swap and is read again -> not a throwaway -> refuse.
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return tmp\n"
    )
    assert _apply(src) is None


def test_refuses_tmp_assigned_later():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    tmp = 99\n"
        "    return a, b, tmp\n"
    )
    assert _apply(src) is None


def test_refuses_non_consecutive_statements():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    log = 1\n"
        "    b = tmp\n"
        "    return a, b, log\n"
    )
    assert _apply(src) is None


def test_refuses_wrong_pattern():
    # stmt3 is `b = a` not `b = tmp` -> not the swap idiom.
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = a\n"
        "    return a, b\n"
    )
    assert _apply(src) is None


def test_refuses_only_two_lines():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    return a, b, tmp\n"
    )
    assert _apply(src) is None


def test_refuses_tmp_equals_a():
    # tmp and a are the same name -> not three distinct names.
    src = (
        "def f(a, b):\n"
        "    a = a\n"
        "    a = b\n"
        "    b = a\n"
        "    return a, b\n"
    )
    assert _apply(src) is None


def test_refuses_module_level_swap():
    # Outside any function we cannot bound where tmp might be referenced later.
    src = (
        "a = 1\n"
        "b = 2\n"
        "tmp = a\n"
        "a = b\n"
        "b = tmp\n"
    )
    assert _apply(src) is None


def test_refuses_multi_target_assign():
    # stmt1 is a chained assignment `tmp = a = ...` shape -> not a simple swap.
    src = (
        "def f(a, b):\n"
        "    tmp = c = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b, c\n"
    )
    assert _apply(src) is None


def test_refuses_tuple_value():
    src = (
        "def f(a, b):\n"
        "    tmp = a, b\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
    )
    assert _apply(src) is None


# --------------------------------------------------------------------------- #
# Invariants: determinism + never unparseable
# --------------------------------------------------------------------------- #
def test_deterministic():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
    )
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_idempotent_after_rewrite():
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
    )
    out = _apply(src)
    assert out is not None
    assert _apply(out) is None


def test_first_eligible_swap_only():
    # Two independent swaps in two functions; only the first is rewritten.
    src = (
        "def f(a, b):\n"
        "    tmp = a\n"
        "    a = b\n"
        "    b = tmp\n"
        "    return a, b\n"
        "\n"
        "def g(c, d):\n"
        "    tmp = c\n"
        "    c = d\n"
        "    d = tmp\n"
        "    return c, d\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    assert out.count("= b, a") == 1
    # g's swap still present; a second pass collapses it too.
    out2 = _apply(out)
    assert out2 is not None
    assert "tmp" not in out2


def test_syntax_error_returns_none():
    assert _apply("def f(:\n    return 1\n") is None


def test_no_swap_returns_none():
    assert _apply("def f(a, b):\n    return a + b\n") is None


def test_never_emits_unparseable_output():
    samples = [
        "def f(a, b):\n    tmp = a\n    a = b\n    b = tmp\n    return a, b\n",
        "def f(obj, b):\n    tmp = obj.a\n    obj.a = b\n    b = tmp\n",
        "def f(a, b):\n    tmp = a\n    a = b\n    log = 1\n    b = tmp\n",
        "a = 1\nb = 2\ntmp = a\na = b\nb = tmp\n",
        "class C:\n    def m(self, a, b):\n        tmp = a\n        a = b\n        b = tmp\n        return a, b\n",
        "def f(:\n    bad\n",
        "x = 1\n",
        "",
    ]
    for src in samples:
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # must always re-parse


def test_method_body_swap():
    src = (
        "class C:\n"
        "    def m(self, a, b):\n"
        "        tmp = a\n"
        "        a = b\n"
        "        b = tmp\n"
        "        return a, b\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    assert "        a, b = b, a\n" in out
    # Confirm method still swaps.
    ns: dict = {}
    exec(compile(out, "<t>", "exec"), ns)  # noqa: S102
    assert ns["C"]().m(1, 2) == (2, 1)
