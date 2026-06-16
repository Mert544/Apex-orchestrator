"""Characterization harness proving the shared-helper consolidation is byte-identical.

The list (:func:`plan_simplify_comprehension`) and dict
(:func:`plan_dict_comprehension`) accumulator-loop transforms each used to carry
private copies of four byte-identical helpers (``_Rewrite``, ``_single_line_segment``,
``_is_name_target``, ``_apply``) plus two byte-identical statement windows (the head
of ``_assign_name`` and of ``_try_accumulator``). Those are now hoisted into
``app.execution._transform_base`` (appended, never altering existing functions).

This harness loads the PRE-refactor modules straight from ``git show HEAD`` and
feeds a broad corpus of source snippets through both the live and the original
``plan_*`` paths, comparing the FULL plan output. Zero mismatches over the corpus
proves the consolidation preserved exact behaviour. It also exercises the new
``_transform_base`` primitives directly, including their empty/skip edge paths.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys

import app.execution._transform_base as base
from app.execution.comprehension import plan_simplify_comprehension
from app.execution.dict_comprehension import plan_dict_comprehension

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_original(rel: str, mod_name: str):
    """Load a pre-refactor module (from ``git show HEAD``) as a standalone module
    so its plan output can be diffed against the live one. The HEAD source imports
    the (appended-only) ``_transform_base``, so its existing primitives resolve to
    the live ones — exactly as before the consolidation."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{rel}"], cwd=_REPO_ROOT, text=True,
    )
    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    exec(compile(src, f"<git:HEAD {rel}>", "exec"), mod.__dict__)
    return mod


_ORIG_LIST = _load_original("app/execution/comprehension.py", "_comp_orig_shared")
_ORIG_DICT = _load_original(
    "app/execution/dict_comprehension.py", "_dictcomp_orig_shared")


# A corpus exercising matches, near-misses, skips, blockers and empty results.
_SNIPPETS = [
    # list matches / near-misses
    "out = []\nfor x in items:\n    out.append(x)\n",
    "out = []\nfor x in items:\n    out.append(x * 2)\n",
    "out = []\nfor a, b in pairs:\n    out.append(a + b)\n",
    "out = []\nfor (a, b) in pairs:\n    out.append(f(a, b))\n",
    "out = [1]\nfor x in items:\n    out.append(x)\n",
    "out = []\nfor x in items:\n    out.append(x)\n    y = 1\n",
    "out = []\nfor x in items:\n    out.append(out)\n",
    "out = []\nfor x in items:\n    out.append(*x)\n",
    "out = []\nfor x in items:\n    out.append(x, y)\n",
    "out = []\nfor x in items:\n    out.append()\n",
    "out = []\nfor x in items:\n    out.append(x)\nelse:\n    pass\n",
    "out = []\nelse_loop = 1\n",
    "out = []\nfor obj.attr in items:\n    out.append(obj.attr)\n",
    "out = []\nfor x in (\n    items):\n    out.append(x)\n",
    "out = []\nfor x in items:\n    out.append(\n        x)\n",
    # dict matches / near-misses
    "d = {}\nfor x in items:\n    d[x] = x\n",
    "d = {}\nfor k in keys:\n    d[k] = compute(k)\n",
    "d = {}\nfor a, b in pairs:\n    d[a] = b\n",
    "d = {1: 2}\nfor x in items:\n    d[x] = x\n",
    "d = {}\nfor x in items:\n    d[x:y] = x\n",
    "d = {}\nfor x in items:\n    d[x] = d\n",
    "d = {}\nfor x in items:\n    d[x] = x\n    z = 1\n",
    "d = {}\nfor x in items:\n    d.update(x)\n",
    "d = {}\nfor x in items:\n    d[x], e = 1, 2\n",
    # nesting / multiple / mixed
    "def f():\n    out = []\n    for x in items:\n        out.append(x)\n    return out\n",
    "res = {}\nfor i in range(10):\n    res[i] = i*i\nout = []\nfor j in range(5):\n    out.append(j)\n",
    "if c:\n    out = []\n    for x in items:\n        out.append(x)\n",
    # blockers / empties
    "broken( syntax",
    "",
    "x = 5\n",
    "{1: 2}\n",
    "[1, 2, 3]\n",
]


def _plan_dict(planfn, tmp_path, rel, src):
    p = (tmp_path / rel)
    p.write_text(src)
    plan = planfn(str(tmp_path), rel)
    return {
        "old": plan.old,
        "new": plan.new,
        "blockers": list(plan.blockers),
        "originals": dict(plan.originals),
        "new_contents": dict(plan.new_contents),
        "edits_by_file": dict(plan.edits_by_file),
    }


def test_list_transform_byte_identical(tmp_path):
    for i, src in enumerate(_SNIPPETS):
        rel = f"m{i}.py"
        live = _plan_dict(plan_simplify_comprehension, tmp_path, rel, src)
        orig = _plan_dict(
            _ORIG_LIST.plan_simplify_comprehension, tmp_path, rel, src)
        assert live == orig, f"list mismatch on snippet {i!r}: {src!r}"


def test_dict_transform_byte_identical(tmp_path):
    for i, src in enumerate(_SNIPPETS):
        rel = f"m{i}.py"
        live = _plan_dict(plan_dict_comprehension, tmp_path, rel, src)
        orig = _plan_dict(_ORIG_DICT.plan_dict_comprehension, tmp_path, rel, src)
        assert live == orig, f"dict mismatch on snippet {i!r}: {src!r}"


def test_fixture_and_missing_paths_match(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "f.py").write_text(
        "out = []\nfor x in items:\n    out.append(x)\n")
    for planfn, orig in (
        (plan_simplify_comprehension, _ORIG_LIST.plan_simplify_comprehension),
        (plan_dict_comprehension, _ORIG_DICT.plan_dict_comprehension),
    ):
        live_fx = planfn(str(tmp_path), "tests/f.py")
        orig_fx = orig(str(tmp_path), "tests/f.py")
        assert list(live_fx.blockers) == list(orig_fx.blockers)
        assert dict(live_fx.new_contents) == dict(orig_fx.new_contents)
        live_missing = planfn(str(tmp_path), "nope.py")
        orig_missing = orig(str(tmp_path), "nope.py")
        assert list(live_missing.blockers) == list(orig_missing.blockers)


# --- direct exercise of the new _transform_base primitives --------------------

def test_single_name_assign_rhs():
    name, rhs = base.single_name_assign_rhs(ast.parse("x = []").body[0])
    assert name == "x" and isinstance(rhs, ast.List)
    name, rhs = base.single_name_assign_rhs(ast.parse("y = {}").body[0])
    assert name == "y" and isinstance(rhs, ast.Dict)
    assert base.single_name_assign_rhs(ast.parse("a, b = []").body[0]) is None
    assert base.single_name_assign_rhs(ast.parse("x: list = []").body[0]) is None
    assert base.single_name_assign_rhs(ast.parse("obj.x = []").body[0]) is None
    assert base.single_name_assign_rhs(ast.parse("x += []").body[0]) is None
    assert base.single_name_assign_rhs(ast.parse("pass").body[0]) is None


def test_is_name_target():
    assert base.is_name_target(ast.parse("x", mode="eval").body)
    assert base.is_name_target(ast.parse("(a, b)", mode="eval").body)
    assert base.is_name_target(ast.parse("[a, b]", mode="eval").body)
    assert not base.is_name_target(ast.parse("()", mode="eval").body)
    assert not base.is_name_target(ast.parse("obj.attr", mode="eval").body)
    assert not base.is_name_target(ast.parse("(a, obj.b)", mode="eval").body)


def test_single_line_segment():
    src = "f(x)"
    node = ast.parse(src, mode="eval").body
    assert base.single_line_segment(src, node) == "f(x)"
    multi = "f(\n    x)"
    call = ast.parse(multi, mode="eval").body
    # the single-line arg is recoverable; the two-line call is rejected
    assert base.single_line_segment(multi, call.args[0]) == "x"
    assert base.single_line_segment(multi, call) is None


def test_accumulator_seed():
    def list_assign(stmt):
        bound = base.single_name_assign_rhs(stmt)
        if bound is None:
            return None
        name, rhs = bound
        return name if isinstance(rhs, ast.List) and not rhs.elts else None

    block = ast.parse(
        "out = []\nfor x in items:\n    out.append(x)\n").body
    seed = base.accumulator_seed(block, 0, list_assign)
    assert seed is not None
    name, for_stmt = seed
    assert name == "out" and isinstance(for_stmt, ast.For)
    # not an empty-list assign -> None
    block2 = ast.parse("out = [1]\nfor x in items:\n    out.append(x)\n").body
    assert base.accumulator_seed(block2, 0, list_assign) is None
    # no next sibling -> None
    block3 = ast.parse("out = []\n").body
    assert base.accumulator_seed(block3, 0, list_assign) is None
    # next sibling not a for -> None
    block4 = ast.parse("out = []\nz = 1\n").body
    assert base.accumulator_seed(block4, 0, list_assign) is None


def test_apply_comprehension_rewrites():
    src = "out = []\nfor x in items:\n    out.append(x)\n"
    rw = base.AccumulatorRewrite(1, 3, 0, "out = [x for x in items]")
    assert base.apply_comprehension_rewrites(src, [rw]) == (
        "out = [x for x in items]\n")
    # empty rewrite list -> source unchanged
    assert base.apply_comprehension_rewrites(src, []) == src
    # no trailing newline on last replaced line is preserved
    src2 = "out = []\nfor x in items:\n    out.append(x)"
    rw2 = base.AccumulatorRewrite(1, 3, 0, "out = [x for x in items]")
    assert base.apply_comprehension_rewrites(src2, [rw2]) == "out = [x for x in items]"
