"""Extra edge-coverage for the collapse-startswith develop transform.

Targets the conservative-blocker branches, source-recovery guards, the
re-parse-failure guard and the no-op early return that the primary suite does
not exercise. Deterministic, stdlib-only, no network.
"""

from __future__ import annotations

import ast

from app.execution import startswith_tuple as mod
from app.execution.startswith_tuple import (
    _arg_texts,
    _matching_call,
    _try_boolop,
    plan_collapse_startswith,
)


def _write(tmp_path, rel: str, src: str) -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return rel


def _plan(tmp_path, src: str, rel: str = "pkg/mod.py"):
    _write(tmp_path, rel, src)
    return plan_collapse_startswith(str(tmp_path), rel), rel


# --- _matching_call negative branches -----------------------------------

def test_matching_call_non_call_returns_none():
    node = ast.parse("x", mode="eval").body
    assert _matching_call(node, "startswith") is None


def test_matching_call_starred_arg_returns_none():
    node = ast.parse("x.startswith(*a)", mode="eval").body
    assert _matching_call(node, "startswith") is None


def test_matching_call_keyword_returns_none():
    node = ast.parse("x.startswith('a', foo=1)", mode="eval").body
    assert _matching_call(node, "startswith") is None


def test_matching_call_two_positional_returns_none():
    node = ast.parse("x.startswith('a', 0)", mode="eval").body
    assert _matching_call(node, "startswith") is None


def test_starred_arg_in_source_untouched(tmp_path):
    src = "def f(x, a, b):\n    return x.startswith(*a) or x.startswith(*b)\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


# --- _arg_texts source-recovery guards (segment None) -------------------

def test_arg_texts_tuple_elt_unrecoverable_returns_none():
    # A synthetic tuple element with no position info -> get_source_segment None.
    elt = ast.Name(id="A", ctx=ast.Load())
    tup = ast.Tuple(elts=[elt], ctx=ast.Load())
    call = ast.Call(func=ast.Name(id="x", ctx=ast.Load()),
                    args=[tup], keywords=[])
    assert _arg_texts(call, "x.startswith(('A',))") is None


def test_arg_texts_single_arg_unrecoverable_returns_none():
    arg = ast.Constant(value="z")  # no position info
    call = ast.Call(func=ast.Name(id="x", ctx=ast.Load()),
                    args=[arg], keywords=[])
    assert _arg_texts(call, "x.startswith('z')") is None


# --- _try_boolop direct guards ------------------------------------------

def test_try_boolop_non_or_returns_none():
    node = ast.parse("a and b", mode="eval").body
    assert _try_boolop(node, "a and b") is None


def test_try_boolop_single_value_returns_none():
    # A BoolOp can't be parsed with <2 values, so build one synthetically.
    call = ast.parse("x.startswith('a')", mode="eval").body
    node = ast.BoolOp(op=ast.Or(), values=[call])
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 18
    assert _try_boolop(node, "x.startswith('a')") is None


def test_try_boolop_receiver_unrecoverable_returns_none():
    # Two same-method calls whose receiver node lacks position info -> None.
    recv = ast.Name(id="x", ctx=ast.Load())  # no lineno

    def mkcall():
        arg = ast.Constant(value="a", lineno=1, col_offset=0,
                           end_lineno=1, end_col_offset=3)
        return ast.Call(
            func=ast.Attribute(value=recv, attr="startswith", ctx=ast.Load()),
            args=[arg], keywords=[])

    node = ast.BoolOp(op=ast.Or(), values=[mkcall(), mkcall()])
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 40
    # receiver get_source_segment(recv) is None -> early None
    assert _try_boolop(node, "x.startswith('a') or x.startswith('a')") is None


def test_try_boolop_arg_unrecoverable_mid_collection_returns_none():
    # Receiver is recoverable, but one call's argument lacks position info, so
    # _arg_texts returns None inside the collection loop -> whole boolean skipped.
    src = "x.startswith('a') or x.startswith('b')"
    node = ast.parse(src, mode="eval").body
    node.values[1].args[0] = ast.Constant(value="b")  # no position info
    assert _try_boolop(node, src) is None


# --- plan-level scaffolding guards --------------------------------------

def test_unreadable_path_blocks(tmp_path):
    # A directory at the module path makes read_text raise OSError.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").mkdir()
    plan = plan_collapse_startswith(str(tmp_path), "pkg/mod.py")
    assert plan.blockers == ["cannot read pkg/mod.py"]
    assert not plan.new_contents


def test_reparse_failure_blocks(tmp_path, monkeypatch):
    src = "def f(x):\n    return x.startswith('a') or x.startswith('b')\n"
    rel = _write(tmp_path, "pkg/mod.py", src)
    monkeypatch.setattr(mod, "_apply", lambda s, r: "def f(:\n")
    plan = plan_collapse_startswith(str(tmp_path), rel)
    assert plan.blockers
    assert "would not re-parse" in plan.blockers[0]
    assert not plan.new_contents


def test_apply_noop_returns_empty_plan(tmp_path, monkeypatch):
    src = "def f(x):\n    return x.startswith('a') or x.startswith('b')\n"
    rel = _write(tmp_path, "pkg/mod.py", src)
    # _apply returns the original source verbatim -> new_source == source guard.
    monkeypatch.setattr(mod, "_apply", lambda s, r: src)
    plan = plan_collapse_startswith(str(tmp_path), rel)
    assert not plan.new_contents
    assert not plan.blockers
