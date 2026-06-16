from __future__ import annotations

import ast

import pytest

from app.execution.semantic.transforms import augmented_assign as aa


def _apply(src: str) -> str | None:
    r = aa.apply("m.py", src)
    return r.patch_requests[0]["new_content"] if r else None


# --- basic rewrites ---------------------------------------------------------


def test_add_one():
    out = _apply("x = x + 1\n")
    assert out == "x += 1\n"
    ast.parse(out)


def test_mult_two():
    out = _apply("n = n * 2\n")
    assert out == "n *= 2\n"


def test_rewrite_with_name_rhs():
    out = _apply("x = x + a\n")
    assert out == "x += a\n"


def test_result_metadata():
    r = aa.apply("pkg/mod.py", "x = x + 1\n")
    assert r is not None
    assert r.transform_type == "augmented_assign"
    assert r.patch_requests[0]["path"] == "pkg/mod.py"
    assert r.patch_requests[0]["expected_old_content"] == "x = x + 1\n"
    assert r.rationale


# --- all arithmetic / bitwise operators -------------------------------------


@pytest.mark.parametrize(
    "op_src,aug",
    [
        ("x + 1", "x += 1"),
        ("x - 1", "x -= 1"),
        ("x * 2", "x *= 2"),
        ("x / 2", "x /= 2"),
        ("x // 2", "x //= 2"),
        ("x % 2", "x %= 2"),
        ("x ** 2", "x **= 2"),
        ("x & 1", "x &= 1"),
        ("x | 1", "x |= 1"),
        ("x ^ 1", "x ^= 1"),
        ("x >> 1", "x >>= 1"),
        ("x << 1", "x <<= 1"),
    ],
)
def test_all_ops(op_src: str, aug: str):
    out = _apply(f"x = {op_src}\n")
    assert out == f"{aug}\n"
    ast.parse(out)


# --- refusals ---------------------------------------------------------------


def test_refuse_name_on_right():
    # x = 1 + x : non-commutative ops differ and __radd__/__iadd__ semantics differ.
    assert _apply("x = 1 + x\n") is None


def test_refuse_name_on_right_with_var():
    assert _apply("x = a + x\n") is None


def test_refuse_attribute_target():
    # obj.x = obj.x + 1 would change obj evaluation count -> unsafe.
    assert _apply("obj.x = obj.x + 1\n") is None


def test_refuse_subscript_target():
    assert _apply("d[k] = d[k] + 1\n") is None


def test_refuse_different_name():
    assert _apply("x = y + 1\n") is None


def test_refuse_plain_assign():
    assert _apply("x = x\n") is None


def test_refuse_multiple_targets():
    assert _apply("x = y = x + 1\n") is None


def test_refuse_tuple_target():
    assert _apply("x, y = x + 1, 2\n") is None


def test_refuse_non_aug_op():
    # matrix-mult @ has no augmented form in our table interactions here;
    # comparison/boolean are not BinOps so simply ignored.
    assert _apply("x = x == 1\n") is None


def test_refuse_call_value():
    assert _apply("x = f(x)\n") is None


# --- robustness -------------------------------------------------------------


def test_syntax_error_returns_none():
    assert _apply("def (:\n") is None


def test_no_op_returns_none():
    assert _apply("y = z + 1\n") is None


def test_determinism():
    src = "x = x + 1\ny = y * 3\n"
    first = _apply(src)
    second = _apply(src)
    assert first == second
    assert first is not None
    ast.parse(first)


def test_never_unparseable():
    samples = [
        "x = x + 1\n",
        "n = n - 5\n",
        "total = total * factor\n",
        "x = 1 + x\n",
        "obj.x = obj.x + 1\n",
        "x = x\n",
    ]
    for s in samples:
        out = _apply(s)
        if out is not None:
            ast.parse(out)  # must always be valid python


def test_mixed_rewrite_and_refusal_in_one_module():
    src = "x = x + 1\nobj.a = obj.a + 1\ny = 1 + y\nz = z * 2\n"
    out = _apply(src)
    assert out is not None
    assert "x += 1" in out
    assert "z *= 2" in out
    # refused ones preserved as-is
    assert "obj.a = obj.a + 1" in out
    assert "y = 1 + y" in out
    ast.parse(out)


# --- semantic equality on plain ints ----------------------------------------


@pytest.mark.parametrize(
    "stmt,start",
    [
        ("x = x + 1", 10),
        ("x = x - 4", 10),
        ("x = x * 3", 7),
        ("x = x // 3", 17),
        ("x = x % 5", 23),
        ("x = x ** 2", 6),
        ("x = x & 6", 12),
        ("x = x | 1", 8),
        ("x = x ^ 3", 9),
        ("x = x >> 1", 40),
        ("x = x << 2", 5),
    ],
)
def test_semantic_equality_ints(stmt: str, start: int):
    out = _apply(stmt + "\n")
    assert out is not None
    env_orig = {"x": start}
    env_new = {"x": start}
    exec(stmt, {}, env_orig)
    exec(out, {}, env_new)
    assert env_orig["x"] == env_new["x"]


def test_semantic_equality_division():
    out = _apply("x = x / 2\n")
    assert out is not None
    env_orig = {"x": 9}
    env_new = {"x": 9}
    exec("x = x / 2", {}, env_orig)
    exec(out, {}, env_new)
    assert env_orig["x"] == env_new["x"] == 4.5
