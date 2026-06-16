"""Characterization: refactored ``_generalize`` is byte-identical to the original.

The original implementation of ``_generalize`` (pre-refactor) is inlined below
verbatim. We drive both the original and the current implementation through a
wide bank of inputs that exercise every branch (type mismatch, list-length
mismatch, non-list vs list, AST vs non-AST, scalar mismatch, nested holes,
metavariable reuse, and the ``learn_rule`` public entry) and assert the
produced trees and rules match exactly. Zero mismatches == proof.
"""

from __future__ import annotations

import ast

import pytest

from app.execution.pattern_rewrite import _MV_PREFIX
from app.execution.rule_learn import (
    _Holes,
    _hole,
    _MustHole,
    _generalize as _generalize_new,
    learn_rule,
)


# --- The original _generalize, inlined verbatim from HEAD for comparison. ----
def _generalize_orig(nodes, sources, holes):
    first = nodes[0]
    if any(type(n) is not type(first) for n in nodes):
        return _hole(nodes, sources, holes)
    try:
        out = type(first)()
        for fname, fvalue in ast.iter_fields(first):
            values = [getattr(n, fname) for n in nodes]
            if isinstance(fvalue, list):
                if any(not isinstance(v, list) or len(v) != len(fvalue) for v in values):
                    return _hole(nodes, sources, holes)
                items = []
                for group in zip(*values):
                    if isinstance(group[0], ast.AST):
                        items.append(_generalize_orig(list(group), sources, holes))
                    elif any(g != group[0] for g in group):
                        raise _MustHole
                    else:
                        items.append(group[0])
                setattr(out, fname, items)
            elif isinstance(fvalue, ast.AST):
                if any(not isinstance(v, ast.AST) for v in values):
                    return _hole(nodes, sources, holes)
                setattr(out, fname, _generalize_orig(values, sources, holes))
            elif any(v != fvalue for v in values):
                return _hole(nodes, sources, holes)
            else:
                setattr(out, fname, fvalue)
        return out
    except _MustHole:
        return _hole(nodes, sources, holes)


# --- Input bank: each entry is a list of BEFORE expression strings. ----------
_EXPR_GROUPS = [
    ["len(xs) == 0", "len(a.b) == 0"],
    ["x + x", "y + y"],
    ["a + 1", "b - 2"],            # operator mismatch -> bare hole
    ["f(a)", "f(c)"],
    ["f(a, b)", "f(c, d)"],
    ["f(a, b)", "f(c)"],          # arg-count (list-length) mismatch
    ["a.b.c", "x.y.z"],
    ["a and b", "c and d"],
    ["a and b", "c or d"],        # boolop scalar mismatch
    ["[1, 2, 3]", "[4, 5, 6]"],
    ["[1, 2]", "[3, 4, 5]"],      # list length differs
    ["{'k': v}", "{'k': w}"],
    ["{'k': v}", "{'j': w}"],     # constant key mismatch
    ["a if b else c", "x if y else z"],
    ["-a", "-b"],
    ["-a", "+b"],                 # unaryop mismatch
    ["f(x=1)", "f(x=2)"],
    ["f(x=1)", "f(y=1)"],         # keyword arg name mismatch
    ["a[0]", "a[1]"],
    ["a[b:c]", "a[d:e]"],
    ["lambda p: p", "lambda q: q"],
    ["a == b == c", "d == e == f"],
    ["a == b", "a < b"],          # cmpop list scalar mismatch
    ["g(a)(b)", "g(c)(d)"],
    ["f(a)", "f(a)"],             # identical -> no holes at all
    ["1", "2"],                   # bare constants -> single hole
    ["x", "y"],                   # bare names -> single hole
    ["a + b", "a + b"],           # identical binop
    ["f(*args)", "f(*xs)"],
    ["str(x).strip()", "str(y).strip()"],
    ["{1, 2}", "{3, 4}"],
    ["(a, b)", "(c, d)"],
    ["not x", "not y"],
]


def _dump_group(group):
    sources = list(group)
    nodes = [ast.parse(s, mode="eval").body for s in group]
    holes_o = _Holes()
    holes_n = _Holes()
    tree_o = _generalize_orig(list(nodes), sources, holes_o)
    # re-parse to get fresh nodes (generalize may mutate via setattr on copies,
    # but it builds new nodes; still, use independent parses to be safe).
    nodes2 = [ast.parse(s, mode="eval").body for s in group]
    tree_n = _generalize_new(list(nodes2), sources, holes_n)
    return (
        ast.dump(tree_o),
        ast.dump(tree_n),
        dict(holes_o.by_pair),
        dict(holes_n.by_pair),
    )


@pytest.mark.parametrize("group", _EXPR_GROUPS)
def test_generalize_tree_byte_identical(group):
    dump_o, dump_n, pairs_o, pairs_n = _dump_group(group)
    assert dump_o == dump_n
    assert pairs_o == pairs_n


@pytest.mark.parametrize("group", _EXPR_GROUPS)
def test_generalize_display_byte_identical(group):
    # Compare the rendered display string (unparse + $-spelling) end to end.
    sources = list(group)
    holes_o, holes_n = _Holes(), _Holes()
    to = _generalize_orig([ast.parse(s, mode="eval").body for s in group], sources, holes_o)
    tn = _generalize_new([ast.parse(s, mode="eval").body for s in group], sources, holes_n)
    disp_o = ast.unparse(to).replace(_MV_PREFIX, "$")
    disp_n = ast.unparse(tn).replace(_MV_PREFIX, "$")
    assert disp_o == disp_n


# --- End-to-end public entry: learn_rule must be unchanged. ------------------
_PAIR_BANK = [
    [("len(xs) == 0", "not xs"), ("len(a.b) == 0", "not a.b")],
    [("x + x", "2 * x"), ("y + y", "2 * y")],
    [("os.getcwd()", "Path.cwd()")],
    [("a + 1", "f(a)"), ("b - 2", "f(b)")],
    [("f(a)", "g(a, b)"), ("f(c)", "g(c, d)")],
    [("len(x ==", "not x")],
    [],
    [("a + b", "b + a"), ("c + d", "d + c")],
    [("f(a, b)", "f(b, a)"), ("f(c, d)", "f(d, c)")],
    [("x.y", "y.x"), ("p.q", "q.p")],
    [("a and a", "a"), ("b and b", "b")],
    [("[a, a]", "a"), ("[b, b]", "b")],
    [("f(a)", "f(a)"), ("g(b)", "g(b)")],   # same op, identical structure
]


def _load_original_module():
    """Exec the pre-refactor rule_learn.py (from git HEAD) as an isolated module."""
    import subprocess
    import sys
    import types

    src = subprocess.run(
        ["git", "show", "HEAD:app/execution/rule_learn.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    name = "_rule_learn_head"
    mod = types.ModuleType(name)
    sys.modules[name] = mod  # dataclass annotation resolution needs this
    exec(compile(src, "<HEAD:rule_learn.py>", "exec"), mod.__dict__)
    return mod


@pytest.mark.parametrize("examples", _PAIR_BANK)
def test_learn_rule_unchanged_endtoend(examples):
    # Full record comparison: refactored learn_rule vs the original at HEAD.
    orig = _load_original_module()
    r_new = learn_rule(examples)
    r_old = orig.learn_rule(examples)
    assert r_new.pattern == r_old.pattern
    assert r_new.replacement == r_old.replacement
    assert r_new.blockers == r_old.blockers
    assert r_new.notes == r_old.notes
    assert r_new.ok == r_old.ok
