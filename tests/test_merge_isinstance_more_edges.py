"""Extra edge-coverage for the merge-isinstance develop transform.

Targets the conservative-blocker branches, the source-recovery guards in
``_type_texts`` / ``_try_boolop``, the re-parse-failure guard and the no-op
early return that the primary suite does not exercise. Deterministic,
stdlib-only, no network.
"""

from __future__ import annotations

import ast

from app.execution import merge_isinstance as mod
from app.execution.merge_isinstance import (
    _is_isinstance_call,
    _try_boolop,
    _type_texts,
    plan_merge_isinstance,
)


def _write(tmp_path, rel: str, src: str) -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return rel


def _plan(tmp_path, src: str, rel: str = "pkg/mod.py"):
    _write(tmp_path, rel, src)
    return plan_merge_isinstance(str(tmp_path), rel), rel


# --- _is_isinstance_call negative branches ------------------------------

def test_is_isinstance_keyword_rejected():
    node = ast.parse("isinstance(x, A, foo=1)", mode="eval").body
    assert _is_isinstance_call(node) is False


def test_is_isinstance_starred_rejected():
    node = ast.parse("isinstance(x, *A)", mode="eval").body
    assert _is_isinstance_call(node) is False


def test_keyword_isinstance_in_source_untouched(tmp_path):
    src = "def f(x):\n    return isinstance(x, A) or isinstance(x, *B)\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


# --- _type_texts source-recovery guards ---------------------------------

def test_type_texts_tuple_elt_unrecoverable_returns_none():
    elt = ast.Name(id="A", ctx=ast.Load())  # no position info
    tup = ast.Tuple(elts=[elt], ctx=ast.Load())
    assert _type_texts(tup, "isinstance(x, (A,))") is None


def test_type_texts_single_unrecoverable_returns_none():
    node = ast.Name(id="Z", ctx=ast.Load())  # no position info
    assert _type_texts(node, "x") is None


def test_type_texts_recovers_tuple_elements():
    arg = ast.parse("isinstance(x, (A, B))", mode="eval").body.args[1]
    assert _type_texts(arg, "isinstance(x, (A, B))") == ["A", "B"]


# --- _try_boolop direct guards ------------------------------------------

def test_try_boolop_non_or_returns_none():
    node = ast.parse("a and b", mode="eval").body
    assert _try_boolop(node, "a and b") is None


def test_try_boolop_multiline_returns_none():
    src = "(isinstance(x, A)\n or isinstance(x, B))"
    node = ast.parse(src, mode="eval").body
    assert node.lineno != node.end_lineno
    assert _try_boolop(node, src) is None


def test_try_boolop_single_value_returns_none():
    call = ast.parse("isinstance(x, A)", mode="eval").body
    node = ast.BoolOp(op=ast.Or(), values=[call])
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 16
    assert _try_boolop(node, "isinstance(x, A)") is None


def test_try_boolop_different_targets_returns_none():
    src = "isinstance(x, A) or isinstance(y, B)"
    node = ast.parse(src, mode="eval").body
    assert _try_boolop(node, src) is None


def test_try_boolop_target_unrecoverable_returns_none():
    # Same target node (shared, no position) in both calls -> target_src None.
    target = ast.Name(id="x", ctx=ast.Load())  # no lineno

    def mkcall(tname):
        typ = ast.Name(id=tname, ctx=ast.Load(), lineno=1, col_offset=0,
                       end_lineno=1, end_col_offset=1)
        return ast.Call(func=ast.Name(id="isinstance", ctx=ast.Load()),
                        args=[target, typ], keywords=[])

    node = ast.BoolOp(op=ast.Or(), values=[mkcall("A"), mkcall("B")])
    node.lineno = 1
    node.end_lineno = 1
    node.col_offset = 0
    node.end_col_offset = 40
    assert _try_boolop(node, "isinstance(x, A) or isinstance(x, B)") is None


def test_try_boolop_type_arg_unrecoverable_mid_collection_returns_none():
    # Target is recoverable, but one call's type argument lacks position info,
    # so _type_texts returns None inside the collection loop -> boolean skipped.
    src = "isinstance(x, A) or isinstance(x, B)"
    node = ast.parse(src, mode="eval").body
    node.values[1].args[1] = ast.Name(id="B", ctx=ast.Load())  # no position
    assert _try_boolop(node, src) is None


# --- plan-level scaffolding guards --------------------------------------

def test_unreadable_path_blocks(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").mkdir()
    plan = plan_merge_isinstance(str(tmp_path), "pkg/mod.py")
    assert plan.blockers == ["cannot read pkg/mod.py"]
    assert not plan.new_contents


def test_reparse_failure_blocks(tmp_path, monkeypatch):
    src = "def f(x):\n    return isinstance(x, A) or isinstance(x, B)\n"
    rel = _write(tmp_path, "pkg/mod.py", src)
    monkeypatch.setattr(mod, "_apply", lambda s, r: "def f(:\n")
    plan = plan_merge_isinstance(str(tmp_path), rel)
    assert plan.blockers
    assert "would not re-parse" in plan.blockers[0]
    assert not plan.new_contents


def test_apply_noop_returns_empty_plan(tmp_path, monkeypatch):
    src = "def f(x):\n    return isinstance(x, A) or isinstance(x, B)\n"
    rel = _write(tmp_path, "pkg/mod.py", src)
    monkeypatch.setattr(mod, "_apply", lambda s, r: src)
    plan = plan_merge_isinstance(str(tmp_path), rel)
    assert not plan.new_contents
    assert not plan.blockers
