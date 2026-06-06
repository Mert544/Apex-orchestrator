from __future__ import annotations

import ast

from app.engine.detectors import has_identity_literal
from app.execution.semantic.transforms import identity_literal as il


def _apply(src: str) -> str | None:
    r = il.apply("m.py", src, "fix identity-literal")
    return r.patch_requests[0]["new_content"] if r else None


def test_rewrites_is_literal_to_eq():
    out = _apply("def f(x):\n    return x is 5\n")
    assert out is not None and "x == 5" in out and " is " not in out
    ast.parse(out)


def test_rewrites_is_not_literal_to_ne():
    out = _apply('def f(n):\n    return n is not "a"\n')
    assert out is not None and 'n != "a"' in out
    ast.parse(out)


def test_leaves_is_none_and_var_identity_alone():
    assert _apply("def f(x):\n    return x is None\n") is None
    assert _apply("def f(a, b):\n    return a is b\n") is None


def test_detector_agrees_and_fix_is_idempotent():
    src = "def f(x):\n    return x is 7\n"
    assert has_identity_literal(src)
    out = _apply(src)
    assert _apply(out) is None  # nothing left to fix
