from __future__ import annotations

import ast

from app.execution.semantic.transforms import startswith_tuple


def _apply(source: str):
    return startswith_tuple.apply("mod.py", source, "title")


def _new_content(source: str) -> str | None:
    result = _apply(source)
    if result is None:
        return None
    return result.patch_requests[0]["new_content"]


def _normalize(source: str) -> str:
    return ast.unparse(ast.parse(source))


# --- rewrites ---------------------------------------------------------------

def test_two_way_startswith():
    out = _new_content('x.startswith("a") or x.startswith("b")\n')
    assert out is not None
    assert _normalize(out) == _normalize("x.startswith(('a', 'b'))")


def test_three_way_startswith():
    out = _new_content('x.startswith("a") or x.startswith("b") or x.startswith("c")\n')
    assert out is not None
    assert _normalize(out) == _normalize("x.startswith(('a', 'b', 'c'))")


def test_endswith():
    out = _new_content('name.endswith(".py") or name.endswith(".pyi")\n')
    assert out is not None
    assert _normalize(out) == _normalize("name.endswith(('.py', '.pyi'))")


def test_attribute_chain_receiver():
    out = _new_content('self.x.startswith("a") or self.x.startswith("b")\n')
    assert out is not None
    assert _normalize(out) == _normalize("self.x.startswith(('a', 'b'))")


def test_non_constant_args_merge():
    out = _new_content("x.startswith(a) or x.startswith(b)\n")
    assert out is not None
    assert _normalize(out) == _normalize("x.startswith((a, b))")


# --- refusals ---------------------------------------------------------------

def test_refuse_different_receiver():
    assert _apply('x.startswith("a") or y.startswith("b")\n') is None


def test_refuse_side_effectful_receiver():
    assert _apply('f().startswith("a") or f().startswith("b")\n') is None


def test_refuse_subscript_receiver():
    assert _apply('d[0].startswith("a") or d[0].startswith("b")\n') is None


def test_refuse_mixed_methods():
    assert _apply('x.startswith("a") or x.endswith("b")\n') is None


def test_refuse_already_tuple_arg():
    assert _apply('x.startswith(("a", "b")) or x.startswith("c")\n') is None


def test_refuse_unrelated_or_term():
    assert _apply('x.startswith("a") or flag\n') is None


def test_refuse_multi_arg_call():
    assert _apply('x.startswith("a", 0) or x.startswith("b")\n') is None


def test_refuse_keyword_arg_call():
    # keywords are not valid for str.startswith, but guard regardless
    assert _apply('x.startswith(prefix="a") or x.startswith("b")\n') is None


def test_no_op_returns_none():
    assert _apply("x.startswith('a')\n") is None
    assert _apply("a or b\n") is None


def test_syntax_error_returns_none():
    assert _apply("def (:\n") is None


# --- properties -------------------------------------------------------------

def test_determinism():
    src = 'x.startswith("a") or x.startswith("b") or x.startswith("c")\n'
    first = _new_content(src)
    for _ in range(5):
        assert _new_content(src) == first


def test_never_unparseable():
    samples = [
        'x.startswith("a") or x.startswith("b")\n',
        'p.q.r.startswith("a") or p.q.r.startswith("b")\n',
        "x.startswith(a) or x.startswith(b) or x.startswith(c)\n",
    ]
    for src in samples:
        out = _new_content(src)
        assert out is not None
        # must parse cleanly
        ast.parse(out)


def test_semantic_equality():
    namespaces = [
        {"x": "apple"},
        {"x": "banana"},
        {"x": "cherry"},
    ]
    src = 'x.startswith("a") or x.startswith("b")\n'
    out = _new_content(src)
    assert out is not None
    for ns in namespaces:
        before = eval(compile(ast.parse('x.startswith("a") or x.startswith("b")', mode="eval"), "<b>", "eval"), {}, ns)
        after = eval(compile(ast.parse(out.strip(), mode="eval"), "<a>", "eval"), {}, ns)
        assert bool(before) == bool(after)


def test_semantic_equality_endswith():
    src = 'name.endswith(".py") or name.endswith(".txt")\n'
    out = _new_content(src)
    assert out is not None
    for name in ["a.py", "a.txt", "a.md"]:
        ns = {"name": name}
        before = eval(compile(ast.parse(src.strip(), mode="eval"), "<b>", "eval"), {}, dict(ns))
        after = eval(compile(ast.parse(out.strip(), mode="eval"), "<a>", "eval"), {}, dict(ns))
        assert bool(before) == bool(after)


def test_nested_rewrite_inside_if():
    src = 'if x.startswith("a") or x.startswith("b"):\n    pass\n'
    out = _new_content(src)
    assert out is not None
    assert "(('a', 'b'))" in out.replace('"', "'") or _normalize(out) == _normalize(
        "if x.startswith(('a', 'b')):\n    pass\n"
    )
