"""Characterization tests pinning the byte-exact output and skip/refuse
behaviour of ``guard_clause.apply`` after its decomposition into pure helpers.

Each case asserts the full ``SemanticPatchResult`` payload (new_content,
expected_old_content, transform_type, rationale) or the ``None`` skip, so any
drift in the rewrite string or a refusal condition fails loudly.
"""
from __future__ import annotations

import ast

import pytest

from app.execution.semantic.transforms import guard_clause as gc


def _apply(src: str, rel: str = "m.py"):
    return gc.apply(rel, src, "add input guard")


# --------------------------------------------------------------------------- #
# Cases that MUST produce a rewrite, pinned byte-for-byte.
# --------------------------------------------------------------------------- #

CONVERTIBLE = [
    (
        "def add(a, b):\n    return a + b\n",
        "def add(a, b):\n"
        "    if not a:\n"
        '        raise ValueError("a is required")\n'
        "    return a + b\n",
        "a",
    ),
    (
        "def f(self, x):\n    return x\n",
        "def f(self, x):\n"
        "    if not x:\n"
        '        raise ValueError("x is required")\n'
        "    return x\n",
        "x",
    ),
    (
        "def cls_only(cls, q):\n    return q\n",
        "def cls_only(cls, q):\n"
        "    if not q:\n"
        '        raise ValueError("q is required")\n'
        "    return q\n",
        "q",
    ),
    (
        "async def af(x):\n    return x\n",
        "async def af(x):\n"
        "    if not x:\n"
        '        raise ValueError("x is required")\n'
        "    return x\n",
        "x",
    ),
    (
        "class C:\n    def m(self, x):\n        return x\n",
        "class C:\n"
        "    def m(self, x):\n"
        "        if not x:\n"
        '            raise ValueError("x is required")\n'
        "        return x\n",
        "x",
    ),
    (
        'def g(x):\n    """Doc."""\n    return x\n',
        'def g(x):\n'
        '    """Doc."""\n'
        '    if not x:\n'
        '        raise ValueError("x is required")\n'
        '    return x\n',
        "x",
    ),
    (
        'def g(x):\n    """Doc."""\n',
        'def g(x):\n'
        '    """Doc."""\n'
        '    if not x:\n'
        '        raise ValueError("x is required")\n',
        "x",
    ),
    (
        "def f(x):\n    if not x_other:\n        pass\n    return x\n",
        "def f(x):\n"
        "    if not x:\n"
        '        raise ValueError("x is required")\n'
        "    if not x_other:\n"
        "        pass\n"
        "    return x\n",
        "x",
    ),
]


@pytest.mark.parametrize("src,expected,arg", CONVERTIBLE)
def test_convertible_byte_exact(src, expected, arg):
    r = _apply(src, "app/sub/x.py")
    assert r is not None
    req = r.patch_requests[0]
    assert req["new_content"] == expected
    assert req["expected_old_content"] == src
    assert req["path"] == "app/sub/x.py"
    assert r.transform_type == "add_guard_clause"
    assert r.rationale == [f"Added input guard for '{arg}' in app/sub/x.py."]


# --------------------------------------------------------------------------- #
# Cases that MUST be skipped (no finding -> None).
# --------------------------------------------------------------------------- #

MUST_NOT = [
    "x = 1\n",                                       # no function
    "",                                              # empty source
    "def f(:\n    pass\n",                           # syntax error
    "def noargs():\n    return 1\n",                 # no real args
    "def justself(self):\n    return 1\n",           # only receiver
    "def f(*args, x):\n    return x\n",              # kw-only, no positional arg
    "def f(x):\n    if not x:\n        pass\n",      # guard already present
    (
        "def already(x):\n"
        "    if not x:\n"
        "        raise ValueError('no')\n"
        "    return x\n"
    ),                                               # exact guard substring present
]


@pytest.mark.parametrize("src", MUST_NOT)
def test_must_not_convert(src):
    assert _apply(src) is None


# --------------------------------------------------------------------------- #
# First matching function wins; the result re-parses.
# --------------------------------------------------------------------------- #

def test_first_function_in_walk_order_is_guarded():
    src = (
        "def outer(x):\n"
        "    def inner(y):\n"
        "        return y\n"
        "    return x\n"
    )
    r = _apply(src)
    assert r is not None
    new = r.patch_requests[0]["new_content"]
    # ast.walk yields outer before inner, so 'x' (outer's arg) is guarded.
    assert 'raise ValueError("x is required")' in new
    ast.parse(new)


def test_docstring_only_keeps_doc_above_guard():
    r = _apply('def g(x):\n    """Doc."""\n')
    new = r.patch_requests[0]["new_content"]
    assert new.index('"""Doc."""') < new.index("if not x:")
    ast.parse(new)
