from __future__ import annotations

import ast

from app.execution.semantic.transforms import dict_get_default as dgd


def _apply(src: str) -> str | None:
    r = dgd.apply("m.py", src, "use dict.get default")
    return r.patch_requests[0]["new_content"] if r else None


def _eval_target(src: str, namespace: dict) -> object:
    """Exec ``src`` and return the value bound to ``x`` (the target name)."""
    ns = dict(namespace)
    exec(compile(src, "<eval>", "exec"), ns)  # noqa: S102 - test-controlled source
    return ns["x"]


# --------------------------------------------------------------------------
# Canonical rewrite
# --------------------------------------------------------------------------

def test_canonical_if_else_rewritten():
    src = (
        "def f(d, k):\n"
        "    if k in d:\n"
        "        x = d[k]\n"
        "    else:\n"
        "        x = 0\n"
        "    return x\n"
    )
    out = _apply(src)
    assert out is not None
    assert "d.get(k, 0)" in out
    assert "if k in d:" not in out
    ast.parse(out)  # re-parses


def test_result_reparses_and_is_single_get_assignment():
    src = (
        "if key in cfg:\n"
        "    x = cfg[key]\n"
        "else:\n"
        "    x = DEFAULT\n"
    )
    out = _apply(src)
    assert out is not None
    tree = ast.parse(out)
    body = tree.body
    assert len(body) == 1
    stmt = body[0]
    assert isinstance(stmt, ast.Assign)
    call = stmt.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Attribute) and call.func.attr == "get"
    assert len(call.args) == 2


def test_constant_key_rewritten():
    src = (
        "if 'name' in d:\n"
        "    x = d['name']\n"
        "else:\n"
        "    x = 'anon'\n"
    )
    out = _apply(src)
    assert out is not None
    assert "d.get('name', 'anon')" in out


def test_semantically_equivalent_hit_and_miss():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = 99\n"
    )
    out = _apply(src)
    assert out is not None
    # hit: key present
    assert _eval_target(src, {"d": {"a": 1}, "k": "a"}) == _eval_target(
        out, {"d": {"a": 1}, "k": "a"}
    ) == 1
    # miss: key absent -> default
    assert _eval_target(src, {"d": {}, "k": "a"}) == _eval_target(
        out, {"d": {}, "k": "a"}
    ) == 99


def test_indentation_preserved():
    src = (
        "def f(d, k):\n"
        "    if k in d:\n"
        "        x = d[k]\n"
        "    else:\n"
        "        x = None\n"
        "    return x\n"
    )
    out = _apply(src)
    assert out is not None
    assert "    x = d.get(k, None)\n" in out
    assert "    return x\n" in out


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------

def test_refuse_different_targets():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    y = 0\n"
    )
    assert _apply(src) is None


def test_refuse_extra_statement_in_if_branch():
    src = (
        "if k in d:\n"
        "    log()\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_extra_statement_in_else_branch():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = 0\n"
        "    log()\n"
    )
    assert _apply(src) is None


def test_refuse_side_effectful_subscript_container():
    # container in subscript is a call, not a bare name -> evaluating twice is
    # not safe and the test/subscript containers also differ.
    src = (
        "if k in get_d():\n"
        "    x = get_d()[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_mismatched_container():
    src = (
        "if k in d:\n"
        "    x = e[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_mismatched_key():
    src = (
        "if k in d:\n"
        "    x = d[j]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_if_branch_not_subscript():
    src = (
        "if k in d:\n"
        "    x = 1\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_side_effectful_default():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = compute()\n"
    )
    assert _apply(src) is None


def test_refuse_elif_chain():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "elif other:\n"
        "    x = 1\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_no_else():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
    )
    assert _apply(src) is None


def test_refuse_not_in_membership():
    src = (
        "if k not in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_augmented_assignment():
    src = (
        "if k in d:\n"
        "    x += d[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    assert _apply(src) is None


def test_refuse_tuple_target():
    src = (
        "if k in d:\n"
        "    x, y = d[k]\n"
        "else:\n"
        "    x, y = 0\n"
    )
    assert _apply(src) is None


def test_syntax_error_returns_none():
    assert _apply("def f(:\n    pass\n") is None


def test_empty_source_returns_none():
    assert _apply("") is None


def test_unrelated_source_returns_none():
    assert _apply("x = 1\ny = 2\n") is None


# --------------------------------------------------------------------------
# Determinism & robustness
# --------------------------------------------------------------------------

def test_deterministic():
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = 0\n"
    )
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_never_unparseable_on_match():
    src = (
        "def f(d, k):\n"
        "    if k in d:\n"
        "        x = d[k]\n"
        "    else:\n"
        "        x = fallback\n"
        "    return x\n"
    )
    out = _apply(src)
    assert out is not None
    assert "d.get(k, fallback)" in out
    ast.parse(out)  # must always re-parse


def test_refuse_list_literal_default():
    # An empty-list default is side-effect-free but not a Name/Constant; the
    # conservative transform refuses it rather than reason about mutability.
    src = (
        "if k in d:\n"
        "    x = d[k]\n"
        "else:\n"
        "    x = []\n"
    )
    assert _apply(src) is None


def test_no_trailing_newline_at_eof():
    src = "if k in d:\n    x = d[k]\nelse:\n    x = 0"  # no final newline
    out = _apply(src)
    assert out is not None
    ast.parse(out)
    assert out == "x = d.get(k, 0)"
