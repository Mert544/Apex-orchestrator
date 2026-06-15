from __future__ import annotations

import ast

from app.execution.semantic.transforms import redundant_else as re_t


def _apply(src: str) -> str | None:
    r = re_t.apply("m.py", src, "remove redundant else")
    return r.patch_requests[0]["new_content"] if r else None


def _values(src: str, fn: str, *args):
    """Compile ``src``, call ``fn`` with ``args``, return its result.

    Used to confirm the rewrite is behaviour-preserving across input space.
    """
    ns: dict = {}
    exec(compile(src, "<t>", "exec"), ns)  # noqa: S102 - trusted test fixtures
    return ns[fn](*args)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_removes_else_after_return():
    src = "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n"
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    # Body dedented to the if's level (return 2 sits at 4-space indent now).
    assert "    return 2\n" in out
    assert "        return 2" not in out
    # Semantically identical for both branches.
    assert _values(out, "f", True) == _values(src, "f", True) == 1
    assert _values(out, "f", False) == _values(src, "f", False) == 2


def test_removes_else_with_multi_statement_body():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "        y = x + 1\n"
        "        return y\n"
    )
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", 0) == _values(src, "f", 0) == 1
    assert _values(out, "f", False) == _values(src, "f", False) == 1


def test_removes_else_after_raise():
    src = (
        "def f(x):\n"
        "    if x < 0:\n"
        "        raise ValueError('neg')\n"
        "    else:\n"
        "        return x\n"
    )
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", 5) == 5
    assert "    return x\n" in out


def test_removes_else_after_continue_in_loop():
    src = (
        "def f(items):\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if x:\n"
        "            continue\n"
        "        else:\n"
        "            out.append(x)\n"
        "    return out\n"
    )
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", [0, 1, 0, 2]) == _values(src, "f", [0, 1, 0, 2]) == [0, 0]


def test_removes_else_after_break_in_loop():
    src = (
        "def f(items):\n"
        "    seen = []\n"
        "    for x in items:\n"
        "        if x is None:\n"
        "            break\n"
        "        else:\n"
        "            seen.append(x)\n"
        "    return seen\n"
    )
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", [1, 2, None, 3]) == [1, 2]


def test_preserves_surrounding_code_and_indentation():
    src = (
        "def f(x):\n"
        "    before = 1\n"
        "    if x:\n"
        "        return before\n"
        "    else:\n"
        "        return -1\n"
        "    after = 2\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    assert "    before = 1\n" in out
    assert "    after = 2\n" in out  # trailing line untouched
    assert "    return -1\n" in out


# --------------------------------------------------------------------------- #
# Refusals -> None
# --------------------------------------------------------------------------- #
def test_refuses_elif():
    src = (
        "def f(x):\n"
        "    if x == 1:\n"
        "        return 1\n"
        "    elif x == 2:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n"
    )
    # The first `if` has an elif chain in its orelse -> not flattenable by dedent.
    assert _apply(src) is None


def test_refuses_when_if_branch_does_not_terminate():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        y = 1\n"
        "    else:\n"
        "        y = 2\n"
        "    return y\n"
    )
    assert _apply(src) is None


def test_refuses_nested_only_termination():
    # The return is nested inside an inner `if`, so the outer if-branch does NOT
    # unconditionally terminate; the else is not provably dead.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        if x > 10:\n"
        "            return 'big'\n"
        "    else:\n"
        "        return 'small'\n"
    )
    assert _apply(src) is None


def test_refuses_when_terminator_not_last_statement():
    # A return that is not the final statement of the branch does not make the
    # whole branch terminate on the path we care about; stay conservative.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        if x:\n"
        "            return 1\n"
        "        log = 2\n"
        "    else:\n"
        "        return 3\n"
    )
    assert _apply(src) is None


def test_refuses_comment_between_else_and_body():
    # A comment sitting between ``else:`` and its first statement has no
    # unambiguous home after a dedent -> refuse rather than misplace it.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "        # explanation\n"
        "        return 2\n"
    )
    assert _apply(src) is None


def test_blank_line_between_else_and_body_is_allowed():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "\n"
        "        return 2\n"
    )
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", False) == 2


def test_syntax_error_returns_none():
    assert _apply("def f(:\n    return 1\n") is None


def test_no_if_returns_none():
    assert _apply("def f(x):\n    return x\n") is None


def test_if_without_else_returns_none():
    assert _apply("def f(x):\n    if x:\n        return 1\n    return 2\n") is None


# --------------------------------------------------------------------------- #
# Invariants: determinism + never unparseable
# --------------------------------------------------------------------------- #
def test_deterministic():
    src = "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n"
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_idempotent_after_removal():
    # Once the else is gone there is nothing left to transform.
    src = "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n"
    out = _apply(src)
    assert out is not None
    assert _apply(out) is None


def test_never_emits_unparseable_output():
    samples = [
        "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n",
        "def f(x):\n    if x:\n        raise ValueError('e')\n    else:\n        return x\n",
        "def f(x):\n    if x:\n        return 1\n    elif x:\n        return 2\n    else:\n        return 3\n",
        "def f(x):\n    if x:\n        y = 1\n    else:\n        y = 2\n    return y\n",
        "class C:\n    def m(self, x):\n        if x:\n            return 1\n        else:\n            return 2\n",
        "if True:\n    x = 1\nelse:\n    x = 2\n",
        "def f(:\n    bad\n",
        "x = 1\n",
        "",
    ]
    for src in samples:
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # must always re-parse


def test_first_eligible_if_is_transformed():
    # Two eligible ifs; only the first (top-most) is rewritten per call.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
        "\n"
        "def g(x):\n"
        "    if x:\n"
        "        return 3\n"
        "    else:\n"
        "        return 4\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    # g's else survives this single-shot call; f's is gone.
    assert out.count("else:") == 1
    # A second pass removes the remaining one.
    out2 = _apply(out)
    assert out2 is not None
    assert "else:" not in out2


def test_module_level_if():
    src = "if cond:\n    raise SystemExit(1)\nelse:\n    cond = 0\n"
    ns = {"cond": False}
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    # cond is falsey -> the (now dedented) body runs and sets cond = 0.
    exec(compile(out, "<t>", "exec"), ns)  # noqa: S102
    assert ns["cond"] == 0


def test_tab_indented_source():
    src = "def f(x):\n\tif x:\n\t\treturn 1\n\telse:\n\t\treturn 2\n"
    out = _apply(src)
    assert out is not None
    assert "else:" not in out
    ast.parse(out)
    assert _values(out, "f", True) == 1
    assert _values(out, "f", False) == 2
