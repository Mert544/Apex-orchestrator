from __future__ import annotations

import ast

from app.execution.semantic.transforms import guard_clause as gc


def _apply(src: str) -> str | None:
    r = gc.apply("m.py", src, "add input guard")
    return r.patch_requests[0]["new_content"] if r else None


def test_guards_first_real_arg():
    out = _apply("def add(a, b):\n    return a + b\n")
    assert out is not None
    assert "if not a:" in out and 'raise ValueError("a is required")' in out
    ast.parse(out)


def test_self_is_not_guarded():
    # `if not self` in a method is meaningless (self is never None) and could
    # call __bool__/__len__ on a half-built object. Guard the real arg instead.
    # (Found running Apex's maintain on paramiko's SFTPAttributes.__init__.)
    out = _apply("class A:\n    def __init__(self, name):\n        self.name = name\n")
    assert out is not None
    assert "if not self" not in out
    assert "if not name:" in out
    ast.parse(out)


def test_cls_is_not_guarded():
    out = _apply(
        "class A:\n"
        "    @classmethod\n"
        "    def make(cls, spec):\n"
        "        return cls()\n"
    )
    assert out is not None
    assert "if not cls" not in out
    assert "if not spec:" in out
    ast.parse(out)


def test_self_only_method_produces_no_patch():
    # No real input to guard -> no patch (never a bogus self-guard).
    out = _apply("class A:\n    def __init__(self):\n        self.x = 1\n")
    assert out is None


def test_guard_inserted_after_docstring_preserves_doc():
    # Inserting the guard before the docstring would demote it to dead code and
    # lose __doc__. It must go AFTER the docstring.
    src = (
        "class A:\n"
        "    def __init__(self, name):\n"
        '        """Make an A."""\n'
        "        self.name = name\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    init = [
        n for n in ast.walk(ast.parse(out))
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    ][0]
    assert ast.get_docstring(init) == "Make an A."
    # And the guard is present in the body.
    assert "if not name:" in out


def test_idempotent_when_guard_present():
    src = "def f(x):\n    if not x:\n        raise ValueError('x is required')\n    return x\n"
    assert _apply(src) is None
