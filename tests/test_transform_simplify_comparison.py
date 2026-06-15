from __future__ import annotations

import ast

from app.execution.semantic.transforms import simplify_comparison as sc


def _apply(src: str) -> str | None:
    r = sc.apply("m.py", src, "simplify comparison")
    return r.patch_requests[0]["new_content"] if r else None


def _eval(src: str, x):
    """Evaluate the boolean test of the single ``if`` in ``src`` for a given x."""
    ns: dict = {}
    exec(compile(ast.parse(src + "result = bool(_cond)\n"), "<t>", "exec"),
         {"x": x}, ns)
    return ns["result"]


# --- the two safe rewrites -------------------------------------------------

def test_eq_none_rewritten():
    out = _apply("def f(x):\n    if x == None:\n        return 1\n")
    assert out is not None
    assert "x is None" in out
    assert "== None" not in out
    ast.parse(out)


def test_ne_none_rewritten():
    out = _apply("def f(x):\n    if x != None:\n        return 1\n")
    assert out is not None
    assert "x is not None" in out
    assert "!= None" not in out
    ast.parse(out)


def test_none_on_left_normalised():
    out = _apply("def f(x):\n    return None == x\n")
    assert out is not None
    assert "x is None" in out
    ast.parse(out)
    out2 = _apply("def f(x):\n    return None != x\n")
    assert out2 is not None and "x is not None" in out2


def test_rewrite_is_semantically_equal():
    # Across truthy / falsy / None operands the rewritten form behaves identically.
    for x in (None, 0, 1, "", "s", [], [0], object()):
        assert _eval("_cond = (x == None)\n", x) == _eval("_cond = (x is None)\n", x)
        assert _eval("_cond = (x != None)\n", x) == _eval("_cond = (x is not None)\n", x)
    # And the produced source matches that hand-checked identity form.
    out = _apply("_cond = (x == None)\n")
    assert out == "_cond = (x is None)\n"


def test_multiple_occurrences_on_one_line():
    out = _apply("def f(a, b):\n    return a == None or b != None\n")
    assert out is not None
    assert "a is None" in out and "b is not None" in out
    assert "== None" not in out and "!= None" not in out
    ast.parse(out)


# --- refusals (bool comparisons left untouched) ----------------------------

def test_eq_true_refused():
    # `== True` is NOT semantics-preserving for non-bool operands -> untouched.
    assert _apply("def f(x):\n    if x == True:\n        return 1\n") is None


def test_eq_false_refused():
    assert _apply("def f(x):\n    if x == False:\n        return 1\n") is None


def test_ne_true_refused():
    assert _apply("def f(x):\n    if x != True:\n        return 1\n") is None


# --- no-op / edge / safety paths -------------------------------------------

def test_no_match_returns_none():
    assert _apply("def f(x, y):\n    return x == y\n") is None
    assert _apply("def f(x):\n    return x is None\n") is None  # already idiomatic
    assert _apply("x = 1\n") is None


def test_none_eq_none_not_rewritten():
    # Degenerate `None == None` has no simple operand -> left alone.
    assert _apply("flag = None == None\n") is None


def test_syntax_error_returns_none():
    assert _apply("def f(:\n    pass\n") is None
    assert _apply("if x == None\n    pass\n") is None  # missing colon


def test_idempotent():
    src = "def f(x):\n    return x == None\n"
    once = _apply(src)
    assert once is not None
    assert _apply(once) is None


def test_deterministic():
    src = "def f(a, b):\n    return a == None and b != None\n"
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_never_unparseable():
    samples = [
        "def f(x):\n    if x == None:\n        return 1\n",
        "def f(x):\n    return None != x\n",
        "y = (a == None) or (b != None)\n",
        "def f(x):\n    return x == True\n",  # refused, but must stay valid
        "def f(x, y):\n    return x == y\n",
    ]
    for src in samples:
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # must always parse
