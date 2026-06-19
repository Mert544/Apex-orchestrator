"""Regression: the mutable-default guard must preserve a leading docstring.

A red-team found that ``fix_mutable_defaults`` inserted the ``if x is None``
guard ABOVE a function's docstring, demoting the docstring to a dead bare
string-literal statement and setting ``__doc__`` to None — a silent behaviour
change. These tests pin that the guard lands AFTER any leading docstring (so the
docstring stays ``body[0]`` and ``__doc__`` is preserved) and that a function
without a docstring still gets the guard at the very top.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import mutable_defaults as md


def _apply(src: str) -> str | None:
    r = md.apply("m.py", src, "fix mutable default")
    return r.patch_requests[0]["new_content"] if r else None


def _compiled_doc(src: str, name: str) -> str | None:
    """Compile ``src`` and return ``__doc__`` of the named function."""
    ns: dict = {}
    exec(compile(src, "<test>", "exec"), ns)  # noqa: S102 - controlled test code
    return ns[name].__doc__


def test_docstring_preserved_as_function_docstring():
    src = 'def f(x=[]):\n    """the docstring"""\n    x.append(1)\n    return x\n'
    out = _apply(src)
    assert out is not None
    tree = ast.parse(out)
    func = tree.body[0]
    # Docstring is still recognised by the AST helper (i.e. still body[0]).
    assert ast.get_docstring(func) == "the docstring"
    # And the runtime __doc__ is preserved after compilation.
    assert _compiled_doc(out, "f") == "the docstring"


def test_guard_lands_after_the_docstring():
    src = 'def f(x=[]):\n    """doc"""\n    return x\n'
    out = _apply(src)
    assert out is not None
    func = ast.parse(out).body[0]
    # body[0] is the docstring; the guard (an If) comes after it.
    assert md._is_docstring(func.body[0])
    assert isinstance(func.body[1], ast.If)
    assert "x=None" in out and "x = []" in out


def test_fix_still_applied_with_docstring():
    src = 'def f(x=[]):\n    """doc"""\n    return x\n'
    out = _apply(src)
    assert out is not None
    assert "def f(x=None):" in out
    assert "if x is None:" in out and "x = []" in out
    ast.parse(out)


def test_behaviour_preserved_with_docstring():
    src = 'def acc(i, b=[]):\n    """accumulate"""\n    b.append(i)\n    return b\n'
    out = _apply(src)
    assert out is not None
    ns: dict = {}
    exec(out, ns)  # noqa: S102 - controlled test code
    assert ns["acc"].__doc__ == "accumulate"
    assert ns["acc"](1) == [1]
    assert ns["acc"](2) == [2]  # not [1, 2] — no shared state


def test_no_docstring_guard_still_at_top():
    # Regression guard: a function WITHOUT a docstring gets the guard first.
    src = "def f(x=[]):\n    return x\n"
    out = _apply(src)
    assert out is not None
    func = ast.parse(out).body[0]
    assert isinstance(func.body[0], ast.If)  # guard is the first statement
    assert _compiled_doc(out, "f") is None


def test_multiline_docstring_preserved():
    src = 'def f(x=[]):\n    """line one\n\n    line two\n    """\n    return x\n'
    out = _apply(src)
    assert out is not None
    func = ast.parse(out).body[0]
    assert ast.get_docstring(func) is not None
    assert isinstance(func.body[1], ast.If)
    assert _compiled_doc(out, "f") is not None


def test_async_function_docstring_preserved():
    src = 'async def f(x=[]):\n    """async doc"""\n    return x\n'
    out = _apply(src)
    assert out is not None
    func = ast.parse(out).body[0]
    assert ast.get_docstring(func) == "async doc"
    assert isinstance(func.body[1], ast.If)


def test_multiple_defaults_with_docstring():
    src = 'def f(x=[], y={}):\n    """doc"""\n    return x, y\n'
    out = _apply(src)
    assert out is not None
    func = ast.parse(out).body[0]
    assert ast.get_docstring(func) == "doc"
    assert "x=None" in out and "y=None" in out
    assert "x = []" in out and "y = {}" in out
    ast.parse(out)


def test_deterministic():
    src = 'def f(x=[]):\n    """doc"""\n    return x\n'
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_idempotent_with_docstring():
    src = 'def f(x=[]):\n    """doc"""\n    return x\n'
    out = _apply(src)
    assert out is not None
    assert md.apply("m.py", out, "fix") is None  # already fixed -> no-op


def test_docstringed_function_count_helper():
    # Empty/edge path: no functions -> zero docstringed functions, no crash.
    assert md._docstringed_functions(ast.parse("x = 1\n")) == 0
    assert md._docstringed_functions(ast.parse('def f():\n    """d"""\n    pass\n')) == 1
    assert md._docstringed_functions(ast.parse("def f():\n    pass\n")) == 0
