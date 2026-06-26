"""Characterization: refactored ``suggest_extractions`` is byte-identical to the
original (the base-commit version of ``app/execution/extract_method.py``), apart
from ONE intentional, audited change — the auto-suggested helper *name*.

The refactor decomposed ``suggest_extractions`` into pure helpers; this harness
loads the original module straight from the base commit's blob, then compares
full output — order AND contents of the suggestion dicts (including key order) —
across a battery of source inputs, original vs refactored. Zero mismatches is
the proof. Deterministic, stdlib-only, offline.

The base-commit original named the helper ``_<fn>_part``; that stacks
underscores for a ``_``-prefixed method (``_deserialize`` → ``__deserialize_part``)
whose unqualified call site inside a class body is then class-private
name-mangled to ``_ClassName__deserialize_part`` → ``NameError`` at runtime
(mangling is name-resolution, not syntax, so the plan parses and slips past the
plan-time guard). HEAD fixes this with :func:`_suggest_helper_name`
(``extracted_<stem>_part``). So this harness keeps the byte-identical proof for
every field EXCEPT ``name``, which it normalizes on the original via the very
helper under test — the only sanctioned drift from the snapshot.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

from app.execution.extract_method import _suggest_helper_name
from app.execution.extract_method import suggest_extractions as refactored


# The commit this refactor is based on; pinned so the proof stays honest even
# after the refactor itself lands on HEAD.
_BASE_SHA = "3616eb4a84bba14e81d385312d9ebcd20c07a453"


def _load_original_suggest():
    """``suggest_extractions`` as it stood at the base commit (pre-refactor)."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    blob = subprocess.check_output(
        ["git", "-C", str(repo), "show",
         f"{_BASE_SHA}:app/execution/extract_method.py"],
        text=True,
    )
    ns: dict = {}
    exec(compile(blob, f"<{_BASE_SHA}:extract_method.py>", "exec"), ns)
    return ns["suggest_extractions"]


original = _load_original_suggest()


def _renamed(suggestions: list[dict]) -> list[dict]:
    """The original's suggestions with only the ``name`` field migrated to HEAD's
    non-mangling scheme — the single audited change, applied via the helper under
    test so the rest of the dict stays the untouched base-commit snapshot."""
    out = []
    for d in suggestions:
        nd = dict(d)
        nd["name"] = _suggest_helper_name(d["function"])
        out.append(nd)
    return out


def _mk_long_fn(name: str, body: str) -> str:
    """A function tall enough (>= _SUGGEST_FN_FLOOR lines) to be mined."""
    pad = "\n".join(f"    pad{k} = {k}" for k in range(45))
    return f"def {name}(a, b, c):\n{body}\n{pad}\n"


# A spread of inputs exercising: data-flow seams, blockers (return/break/nested
# def/lambda/global), comprehension targets, aug-assign, methods, classes,
# multi-function modules, syntax errors, and the supplied-tree fast path.
_FN_BODIES = [
    # plain assignments forming a clean seam
    "    x = a + b\n    y = x * 2\n    z = y + c\n    w = z - a\n    v = w + b",
    # a return inside the run (blocks part of the windows)
    "    x = a + b\n    if x:\n        return x\n    y = a - b\n    z = y + c\n    w = z * 2",
    # a break whose loop is selected vs not
    "    total = 0\n    for i in range(a):\n        total += i\n        if total > b:\n            break\n    out = total + c",
    # nested def blocks
    "    x = a\n    def inner():\n        return x\n    y = x + b\n    z = y + c\n    w = z + a",
    # lambda blocks
    "    f = lambda t: t + a\n    x = f(b)\n    y = x + c\n    z = y + a\n    w = z + b",
    # comprehension targets must not count as locals/returns
    "    items = [k for k in range(a)]\n    pairs = {p: p for p in range(b)}\n    s = sum(items)\n    t = s + c\n    u = t + a",
    # aug-assign as both read and store
    "    acc = a\n    acc += b\n    acc += c\n    acc += a\n    out = acc + b",
    # global / yield / await blockers
    "    global G\n    G = a + b\n    x = G + c\n    y = x + a\n    z = y + b",
]


def _modules() -> list[str]:
    srcs: list[str] = []
    for idx, body in enumerate(_FN_BODIES):
        srcs.append(_mk_long_fn(f"fn{idx}", body))
    # a method on a top-level class (closure-free)
    pad = "\n".join(f"        m{k} = {k}" for k in range(45))
    srcs.append(
        "class C:\n"
        "    def method(self, a, b, c):\n"
        "        x = a + b\n        y = x + c\n        z = y + a\n        w = z + b\n"
        f"{pad}\n"
    )
    # two long functions in one module (exercises the final sort + tie-break)
    srcs.append(_mk_long_fn("alpha", _FN_BODIES[0]) + "\n\n" + _mk_long_fn("beta", _FN_BODIES[6]))
    # short functions / empty module / non-parsing source
    srcs.append("def tiny(a):\n    return a\n")
    srcs.append("")
    srcs.append("def broken(:\n    pass\n")
    srcs.append("x = 1\nclass D:\n    pass\n")
    return srcs


def test_byte_identical_across_inputs():
    mismatches = []
    for src in _modules():
        exp = _renamed(original(src))
        got = refactored(src)
        if got != exp:
            mismatches.append(src[:60])
        # full structural identity, including dict key order
        assert [list(d) for d in got] == [list(d) for d in exp], src[:60]
    assert mismatches == [], mismatches


def test_byte_identical_supplied_tree_fastpath():
    for src in _modules():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        assert refactored(src, tree=tree) == _renamed(original(src, tree=tree))
        # supplying the tree must equal the parse-here path
        assert refactored(src, tree=tree) == refactored(src)


def test_repr_identical():
    # repr captures order + contents + types in one string — the strongest
    # single-line byte-identical assertion (with only the audited name migrated).
    combined_exp = [_renamed(original(s)) for s in _modules()]
    combined_got = [refactored(s) for s in _modules()]
    assert repr(combined_got) == repr(combined_exp)
