from __future__ import annotations

import ast

from app.execution.semantic.transforms import unreachable_cleanup as uc


def _apply(src: str) -> str | None:
    r = uc.apply("m.py", src, "remove unreachable code")
    return r.patch_requests[0]["new_content"] if r else None


def _dump(src: str) -> str:
    """Structural fingerprint of the parsed module, robust to line numbers."""
    return ast.dump(ast.parse(src))


# --- core removal ---------------------------------------------------------


def test_removes_statement_after_return():
    out = _apply("def f():\n    return 1\n    x = 2\n")
    assert out is not None
    assert "x = 2" not in out
    # Re-parses and the reachable behaviour is unchanged.
    ast.parse(out)
    assert _dump(out) == _dump("def f():\n    return 1\n")


def test_removes_multiple_dead_statements():
    src = "def f():\n    return 1\n    x = 2\n    y = 3\n    z = 4\n"
    out = _apply(src)
    assert out is not None
    for dead in ("x = 2", "y = 3", "z = 4"):
        assert dead not in out
    assert _dump(out) == _dump("def f():\n    return 1\n")


def test_removes_after_raise():
    src = "def f():\n    raise ValueError('boom')\n    cleanup()\n"
    out = _apply(src)
    assert out is not None
    assert "cleanup()" not in out
    ast.parse(out)


def test_removes_after_break_in_loop():
    src = (
        "def f(items):\n"
        "    for i in items:\n"
        "        break\n"
        "        do(i)\n"
    )
    out = _apply(src)
    assert out is not None
    assert "do(i)" not in out
    ast.parse(out)


def test_removes_after_continue_in_loop():
    src = (
        "def f(items):\n"
        "    for i in items:\n"
        "        continue\n"
        "        do(i)\n"
    )
    out = _apply(src)
    assert out is not None
    assert "do(i)" not in out
    ast.parse(out)


def test_dead_code_in_else_branch():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
        "        unreachable()\n"
    )
    out = _apply(src)
    assert out is not None
    assert "unreachable()" not in out
    ast.parse(out)


def test_only_tail_after_first_terminator_removed():
    # The reachable statement before the return stays; only the tail goes.
    src = "def f():\n    a = 1\n    return a\n    b = 2\n"
    out = _apply(src)
    assert out is not None
    assert "a = 1" in out
    assert "b = 2" not in out
    assert _dump(out) == _dump("def f():\n    a = 1\n    return a\n")


# --- refusals -------------------------------------------------------------


def test_refuses_when_nested_def_follows_return():
    # A nested def could still be referenced / imported; never silently drop it.
    src = (
        "def f():\n"
        "    return 1\n"
        "    def helper():\n"
        "        return 2\n"
    )
    out = _apply(src)
    assert out is None


def test_refuses_when_nested_class_follows_return():
    src = (
        "def f():\n"
        "    return 1\n"
        "    class Inner:\n"
        "        pass\n"
    )
    assert _apply(src) is None


def test_refuses_when_comment_follows_return():
    # Removing would silently drop the comment -> back off entirely.
    src = "def f():\n    return 1\n    # keep me\n    x = 2\n"
    out = _apply(src)
    assert out is None or "# keep me" in out


def test_refuses_inline_comment_on_dead_statement():
    src = "def f():\n    return 1\n    x = 2  # explain x\n"
    out = _apply(src)
    assert out is None or "# explain x" in out


def test_refuses_global_after_return():
    src = "def f():\n    return 1\n    global G\n"
    assert _apply(src) is None


def test_refuses_nonlocal_after_return():
    src = (
        "def outer():\n"
        "    x = 0\n"
        "    def inner():\n"
        "        return 1\n"
        "        nonlocal x\n"
        "    return inner\n"
    )
    assert _apply(src) is None


def test_no_unreachable_code_returns_none():
    assert _apply("def f():\n    x = 1\n    return x\n") is None


def test_terminator_is_last_statement_returns_none():
    assert _apply("def f():\n    return 1\n") is None


def test_syntax_error_returns_none():
    assert _apply("def f(:\n    return 1\n") is None


def test_module_level_code_after_return_is_untouched():
    # A return at module scope is itself a syntax error, but a bare statement
    # after, e.g., a raise at module level is left alone (we only touch blocks).
    src = "raise SystemExit\nx = 1\n"
    out = _apply(src)
    assert out is None


def test_hash_in_string_is_not_a_comment():
    # The '#' lives inside a string, so it is NOT a comment -> removal proceeds.
    src = 'def f():\n    return 1\n    x = "# not a comment"\n'
    out = _apply(src)
    assert out is not None
    assert "# not a comment" not in out
    ast.parse(out)


# --- robustness -----------------------------------------------------------


def test_empty_source_returns_none():
    assert _apply("") is None


def test_whitespace_only_returns_none():
    assert _apply("\n\n   \n") is None


def test_deterministic():
    src = "def f():\n    return 1\n    x = 2\n    y = 3\n"
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_result_always_parses_or_is_none():
    samples = [
        "def f():\n    return 1\n    x = 2\n",
        "def g(items):\n    for i in items:\n        continue\n        z()\n",
        "def h():\n    raise X\n    # c\n    y = 2\n",
        "def j():\n    return 1\n    def k():\n        pass\n",
        "not python {",
        "",
    ]
    for src in samples:
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # must always parse


def test_multiline_dead_statement_fully_removed():
    src = (
        "def f():\n"
        "    return 1\n"
        "    x = (\n"
        "        1\n"
        "        + 2\n"
        "    )\n"
    )
    out = _apply(src)
    assert out is not None
    assert "+ 2" not in out and "x = (" not in out
    assert _dump(out) == _dump("def f():\n    return 1\n")
