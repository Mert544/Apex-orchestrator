"""Deep mutation-hardening for the docstring-preserving mutable-default guard.

The mutable-default fix replaces ``def f(x=[])`` with a ``None`` sentinel plus an
``if x is None: x = []`` guard. The deep-finding fix this session pins ONE thing
exactly: where the guard is spliced relative to a leading docstring.

  * A function WITH a docstring keeps it as ``body[0]`` (so ``func.__doc__`` and
    ``ast.get_docstring`` stay non-None): the guard goes *after* the docstring.
  * A function WITHOUT a docstring gets the guard at the very top of the body.

The pin lives in ``_guard_insert_index`` / ``_is_docstring``. A flipped predicate
(e.g. demoting the docstring below the guard) lowers the docstringed-function
count and ``_validates`` would refuse the patch — so each branch is asserted on
the ACTUAL re-parsed output, not just on text.

Determinism: every assertion is exact (re-parsed AST docstrings, guard line
positions, full rewritten source equality); no timestamps / ordering.
"""
from __future__ import annotations

import ast

from app.execution.semantic.transforms.mutable_defaults import (
    _guard_insert_index,
    _is_docstring,
    apply,
)


def _rewrite(source: str) -> str:
    result = apply("m.py", source, "Fix mutable defaults")
    assert result is not None
    return result.patch_requests[0]["new_content"]


def _func(tree_or_src):
    tree = tree_or_src if isinstance(tree_or_src, ast.Module) else ast.parse(tree_or_src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise AssertionError("no function in source")


# ---------------------------------------------------------------------------
# Branch A — a function WITH a docstring keeps it; guard inserted AFTER it.
# ---------------------------------------------------------------------------
def test_docstring_function_keeps_docstring_after_rewrite():
    src = (
        "def f(x=[]):\n"
        '    """Original docstring."""\n'
        "    return x\n"
    )
    new = _rewrite(src)
    new_tree = ast.parse(new)
    fn = _func(new_tree)
    # The docstring is still body[0] and still readable via the standard APIs.
    assert ast.get_docstring(fn) == "Original docstring."
    assert _is_docstring(fn.body[0]) is True
    # The guard ``if x is None:`` is body[1] (right after the docstring), not [0].
    guard = fn.body[1]
    assert isinstance(guard, ast.If)
    # The default became the None sentinel.
    assert fn.args.defaults[0].value is None


def test_docstring_function_guard_value_preserves_original_literal():
    src = (
        "def f(x=[1, 2]):\n"
        '    """Doc."""\n'
        "    return x\n"
    )
    new = _rewrite(src)
    # The guard restores the EXACT original literal, not a generic [].
    assert "if x is None:\n        x = [1, 2]\n" in new
    assert ast.get_docstring(_func(ast.parse(new))) == "Doc."


def test_docstring_module_executes_with_preserved_doc():
    src = (
        "def f(x=[]):\n"
        '    """Keep me."""\n'
        "    x.append(1)\n"
        "    return x\n"
    )
    new = _rewrite(src)
    ns: dict = {}
    exec(new, ns)  # noqa: S102 - executing a known-safe rewrite under test
    # __doc__ survives, and the sentinel guard gives each call a fresh list.
    assert ns["f"].__doc__ == "Keep me."
    assert ns["f"]() == [1]
    assert ns["f"]() == [1]  # no shared-state leak across calls


# ---------------------------------------------------------------------------
# Branch B — a function WITHOUT a docstring gets the guard at the top.
# ---------------------------------------------------------------------------
def test_no_docstring_function_guard_is_first_statement():
    src = (
        "def f(x=[]):\n"
        "    return x\n"
    )
    new = _rewrite(src)
    fn = _func(ast.parse(new))
    # No docstring before; the guard is body[0].
    assert isinstance(fn.body[0], ast.If)
    assert ast.get_docstring(fn) is None
    assert fn.args.defaults[0].value is None


def test_no_docstring_rewrite_is_exact_text():
    src = (
        "def f(x=[]):\n"
        "    return x\n"
    )
    new = _rewrite(src)
    assert new == (
        "def f(x=None):\n"
        "    if x is None:\n"
        "        x = []\n"
        "    return x\n"
    )


def test_docstring_rewrite_is_exact_text():
    src = (
        "def f(x=[]):\n"
        '    """D."""\n'
        "    return x\n"
    )
    new = _rewrite(src)
    # Guard appears between the docstring line and the body, never above it.
    assert new == (
        "def f(x=None):\n"
        '    """D."""\n'
        "    if x is None:\n"
        "        x = []\n"
        "    return x\n"
    )


# ---------------------------------------------------------------------------
# _guard_insert_index / _is_docstring — the exact pin, isolated.
# ---------------------------------------------------------------------------
def test_guard_insert_index_after_docstring_uses_end_lineno():
    src = (
        "def f(x=[]):\n"
        '    """One liner."""\n'
        "    return x\n"
    )
    fn = _func(src)
    # Docstring is on line 2 (end_lineno == 2); index is the 0-based line right
    # after it, i.e. 2, so the guard is spliced as the 3rd physical line.
    assert fn.body[0].end_lineno == 2
    assert _guard_insert_index(fn) == 2


def test_guard_insert_index_multiline_docstring_uses_its_end():
    src = (
        "def f(x=[]):\n"
        '    """Line one\n'
        "    line two\n"
        '    line three."""\n'
        "    return x\n"
    )
    fn = _func(src)
    # The triple-quoted docstring ends on line 4 -> insert index 4 (after it).
    assert fn.body[0].end_lineno == 4
    assert _guard_insert_index(fn) == 4


def test_guard_insert_index_no_docstring_is_first_stmt_lineno_minus_one():
    src = (
        "def f(x=[]):\n"
        "    return x\n"
    )
    fn = _func(src)
    # First statement is the return on line 2 -> 0-based index 1 (top of body).
    assert fn.body[0].lineno == 2
    assert _guard_insert_index(fn) == 1


def test_is_docstring_true_only_for_leading_string_expr():
    fn_doc = _func('def f():\n    """d"""\n    return 1\n')
    assert _is_docstring(fn_doc.body[0]) is True
    # A return is not a docstring.
    assert _is_docstring(fn_doc.body[1]) is False
    # A leading non-string constant Expr is not a docstring.
    fn_num = _func("def g():\n    42\n    return 1\n")
    assert _is_docstring(fn_num.body[0]) is False
    # A plain assignment is not a docstring.
    fn_assign = _func("def h():\n    a = 1\n    return a\n")
    assert _is_docstring(fn_assign.body[0]) is False


def test_multiline_docstring_function_keeps_full_docstring():
    src = (
        "def f(x={}):\n"
        '    """Line one\n'
        '    line two."""\n'
        "    return x\n"
    )
    new = _rewrite(src)
    fn = _func(ast.parse(new))
    assert ast.get_docstring(fn) == "Line one\nline two."
    # Guard lands after the multi-line docstring (body[1]), default -> None.
    assert isinstance(fn.body[1], ast.If)
    assert fn.args.defaults[0].value is None
