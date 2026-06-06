from __future__ import annotations

import ast

from app.engine.detectors import has_negated_comparison
from app.execution.semantic.transforms import negated_comparison as nc


def _apply(src: str) -> str | None:
    r = nc.apply("m.py", src, "fix negated comparison")
    return r.patch_requests[0]["new_content"] if r else None


def test_not_in_rewritten():
    out = _apply("def f(x, y):\n    return not x in y\n")
    assert out is not None and "x not in y" in out and "not x in y" not in out
    ast.parse(out)


def test_not_is_rewritten():
    out = _apply("def f(x, y):\n    return not x is y\n")
    assert out is not None and "x is not y" in out
    ast.parse(out)


def test_already_idiomatic_untouched():
    assert _apply("def f(x, y):\n    return x not in y\n") is None
    assert _apply("def f(x, y):\n    return not x\n") is None  # plain negation


def test_detector_agrees_and_idempotent():
    src = "def f(a, b):\n    return not a in b\n"
    assert has_negated_comparison(src)
    assert _apply(_apply(src)) is None
