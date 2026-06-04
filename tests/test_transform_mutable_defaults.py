from __future__ import annotations

import ast

from app.execution.semantic.transforms import mutable_defaults as md


def _apply(src: str) -> str | None:
    r = md.apply("m.py", src, "fix mutable default")
    return r.patch_requests[0]["new_content"] if r else None


def test_fixes_list_default():
    out = _apply("def f(x=[]):\n    x.append(1)\n    return x\n")
    assert out is not None
    assert "def f(x=None):" in out
    assert "if x is None:" in out and "x = []" in out
    ast.parse(out)  # valid Python


def test_fixes_dict_and_set_and_calls():
    # The guard preserves the default's *original* source (behavior-preserving),
    # so dict()/set()/list() stay as written rather than being normalized.
    for default in ("{}", "set()", "list()", "dict()"):
        out = _apply(f"def f(a, b={default}):\n    return b\n")
        assert out is not None, default
        assert "b=None" in out and f"b = {default}" in out
        ast.parse(out)


def test_multiple_defaults_in_one_function():
    out = _apply("def f(x=[], y={}):\n    return x, y\n")
    assert "x=None" in out and "y=None" in out
    assert "x = []" in out and "y = {}" in out
    ast.parse(out)


def test_idempotent():
    out = _apply("def f(x=[]):\n    return x\n")
    assert md.apply("m.py", out, "fix") is None  # already fixed -> no-op


def test_ignores_immutable_and_none_defaults():
    assert _apply("def f(x=0, y='a', z=None, t=()):\n    return x\n") is None


def test_skips_multiline_default_safely():
    # A default spanning multiple lines is left untouched (conservative).
    src = "def f(x=[\n    1,\n    2,\n]):\n    return x\n"
    assert _apply(src) is None  # multi-line default is skipped, not corrupted


def test_preserves_nonempty_default_value():
    # Regression: a non-empty mutable default must keep its real value in the
    # guard, not be replaced by a generic empty literal (would change behavior).
    out = _apply("def f(x=[1, 2]):\n    return x\n")
    assert "x = [1, 2]" in out and "x = []" not in out
    ast.parse(out)
    out2 = _apply("def g(a, b={'k': 1}):\n    return b\n")
    assert "b = {'k': 1}" in out2
    ast.parse(out2)
    # Behavior preserved: each call gets a fresh copy of the real default.
    ns: dict = {}
    exec(_apply("def acc(i, b=[1, 2]):\n    b.append(i)\n    return b\n"), ns)  # noqa: S102
    assert ns["acc"](9) == [1, 2, 9]
    assert ns["acc"](8) == [1, 2, 8]  # not [1, 2, 9, 8] — no shared state


def test_kwonly_default():
    out = _apply("def f(*, cfg={}):\n    return cfg\n")
    assert out is not None and "cfg=None" in out
    ast.parse(out)


def test_behavior_is_fixed():
    # The shared-state bug is gone after the fix: each call gets a fresh list.
    out = _apply("def acc(i, b=[]):\n    b.append(i)\n    return b\n")
    ns: dict = {}
    exec(out, ns)  # noqa: S102 - controlled test code
    assert ns["acc"](1) == [1]
    assert ns["acc"](2) == [2]  # not [1, 2] — no shared state


def test_syntax_error_returns_none():
    assert md.apply("m.py", "def broken(:\n", "fix") is None
