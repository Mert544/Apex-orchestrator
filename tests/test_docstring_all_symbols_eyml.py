"""Idempotency / convergence tests for the ``add_docstring`` transform.

Red-team found that ``add_docstring`` only documented the FIRST undocumented
symbol per run, so a module with N undocumented functions needed N separate
``maintain`` runs (N near-identical commits) to converge. These tests pin the
fixed behaviour: ONE apply pass documents EVERY undocumented function / class /
method, and a second pass on the result is a no-op.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.docstring import apply


def _new_content(result):
    assert result is not None
    assert len(result.patch_requests) == 1
    return result.patch_requests[0]["new_content"]


def _undocumented(source: str) -> list[str]:
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node) is None:
                out.append(node.name)
    return out


# ── all symbols documented in ONE pass ───────────────────────────────────────

def test_three_functions_documented_in_one_pass():
    source = (
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def beta():\n"
        "    return 2\n"
        "\n"
        "\n"
        "def gamma():\n"
        "    return 3\n"
    )
    assert _undocumented(source) == ["alpha", "beta", "gamma"]
    new = _new_content(apply("m.py", source, "stub"))
    # Every function now carries a docstring.
    assert _undocumented(new) == []
    tree = ast.parse(new)
    docs = {
        n.name: ast.get_docstring(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    }
    assert docs == {"alpha": "alpha.", "beta": "beta.", "gamma": "gamma."}


def test_mixed_class_method_function_all_documented():
    source = (
        "def top():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class C:\n"
        "    def method(self):\n"
        "        return self\n"
        "\n"
        "    def other(self):\n"
        "        return 0\n"
    )
    new = _new_content(apply("m.py", source, "stub"))
    assert _undocumented(new) == []


def test_already_documented_symbols_untouched():
    source = (
        "def kept():\n"
        '    """Original."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "def needs():\n"
        "    return 2\n"
    )
    new = _new_content(apply("m.py", source, "stub"))
    tree = ast.parse(new)
    docs = {
        n.name: ast.get_docstring(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    }
    assert docs["kept"] == "Original."  # untouched
    # Single undocumented symbol → title-based body (existing convention).
    assert docs["needs"] == "stub."


def test_docstrings_are_name_derived_not_identical_boilerplate():
    source = (
        "def one():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def two():\n"
        "    return 2\n"
    )
    new = _new_content(apply("m.py", source, "boilerplate"))
    tree = ast.parse(new)
    texts = [
        ast.get_docstring(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    ]
    # Distinct, name-derived — not the same module-level title repeated.
    assert len(set(texts)) == len(texts)
    assert "boilerplate." not in texts


# ── idempotency ──────────────────────────────────────────────────────────────

def test_second_pass_is_noop():
    source = (
        "def a():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def b():\n"
        "    return 2\n"
    )
    first = _new_content(apply("m.py", source, "stub"))
    # Re-applying on the fully-documented result yields None (no change).
    assert apply("m.py", first, "stub") is None


def test_fully_documented_module_is_noop():
    source = (
        '"""Module."""\n'
        "\n"
        "\n"
        "def f():\n"
        '    """f."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "class C:\n"
        '    """C."""\n'
        "\n"
        "    def m(self):\n"
        '        """m."""\n'
        "        return 2\n"
    )
    assert apply("m.py", source, "stub") is None


# ── edge / empty paths ───────────────────────────────────────────────────────

def test_empty_source_is_noop():
    assert apply("m.py", "", "stub") is None


def test_no_symbols_is_noop():
    assert apply("m.py", "x = 1\ny = 2\n", "stub") is None


def test_invalid_syntax_returns_none():
    assert apply("m.py", "def broken(:\n", "stub") is None


def test_indentation_preserved_for_nested_methods():
    source = (
        "class Outer:\n"
        "    def inner(self):\n"
        "        return 1\n"
        "\n"
        "    def other(self):\n"
        "        return 2\n"
    )
    new = _new_content(apply("m.py", source, "stub"))
    assert ast.parse(new) is not None
    assert _undocumented(new) == []
    # Multi-symbol → name-derived; method docstring indented under the method
    # body (8 spaces). The class itself is also undocumented and documented.
    assert '        """inner."""' in new
    assert '        """other."""' in new


def test_existing_code_and_comments_preserved():
    source = (
        "# leading comment\n"
        "def f():\n"
        "    x = 1  # inline\n"
        "    return x\n"
    )
    new = _new_content(apply("m.py", source, "stub"))
    assert "# leading comment" in new
    assert "x = 1  # inline" in new


def test_async_function_documented():
    source = (
        "async def fetch():\n"
        "    return 1\n"
    )
    new = _new_content(apply("m.py", source, "stub"))
    tree = ast.parse(new)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
    )
    # Single symbol → title-based body.
    assert ast.get_docstring(fn) == "stub."


def test_deterministic_same_input_same_output():
    source = (
        "def p():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def q():\n"
        "    return 2\n"
    )
    r1 = _new_content(apply("m.py", source, "stub"))
    r2 = _new_content(apply("m.py", source, "stub"))
    assert r1 == r2
