"""Characterization proof that the merge_nested_if refactor is byte-identical.

The ``_try_if`` predicate in ``app/execution/merge_nested_if.py`` was decomposed
into small pure helpers. This harness loads the HEAD snapshot of the module
dynamically (straight from ``git show HEAD:<path>``, leaving nothing on disk) and
feeds many source snippets — including the ones that must NOT change — through
both the original and the refactored plan path, asserting the full plan output
matches character-for-character. It also compares ``_try_if`` directly on every
``ast.If`` node. Zero mismatches is the proof.

Deterministic, stdlib-only.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import types

import pytest

import app.execution.merge_nested_if as new_mod

_PATH = "app/execution/merge_nested_if.py"


def _load_head() -> types.ModuleType:
    """Import the HEAD snapshot of the module without leaving a file on disk."""
    src = subprocess.check_output(["git", "show", f"HEAD:{_PATH}"], text=True)
    name = "app.execution._head_merge_nested_if_charproof"
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app.execution"  # let relative imports resolve
    sys.modules[name] = module
    exec(compile(src, _PATH, "exec"), module.__dict__)
    return module


orig_mod = _load_head()


# A spread of shapes: canonical merges, every conservative-skip branch, deep
# nesting, blank lines, missing trailing newline, tabs, varied indent steps.
SNIPPETS = [
    "if a:\n    if b:\n        do()\n",
    "if a or c:\n    if b:\n        do()\n",
    "if a:\n    if b or d:\n        do()\n",
    "if a or c:\n    if b and e:\n        do()\n",
    "if a:\n    if b:\n        do()\n    other()\n",
    "if a:\n    if b:\n        do()\nelse:\n    nope()\n",
    "if a:\n    if b:\n        do()\n    else:\n        no()\n",
    "if a:\n    if b:\n        do()\n    elif c:\n        x()\n",
    "if a:\n    if b:\n        do()\nelif c:\n    x()\n",
    "if a:\n    # comment\n    if b:\n        do()\n",
    "if a:\n    do()\n",
    "if a:\n    if b:\n        x = 1\n        y = 2\n",
    "if a:\n    if b:\n        if c:\n            do()\n",
    "def f():\n    if a:\n        if b:\n            do()\n",
    "if a\n    if b:\n        do()\n",
    "if a:\n    if b:\n        x = 1\n\n        y = 2\n",
    "if (a or\n    c):\n    if b:\n        do()\n",
    "if a:\n    if (b or\n        d):\n        do()\n",
    "if a:  # note\n    if b:\n        do()\n",
    "if a:\n    if b: do()\n",
    "x = 1\ny = 2\n",
    "if a:\n    if b:\n        do()",
    "if a:\n        if b:\n                do()\n",
    "if z:\n    only()\nif a:\n    if b:\n        do()\n",
    "",
    "# only comment\n",
    "if a:\n    if b:\n        x = (1 +\n2)\n",
    "if a:\n    if b:\n        return 1\n    return 0\n",
    "class C:\n    def m(self):\n        if a:\n            if b:\n                run()\n",
    "if a:\n    if b:\n        if c:\n            if d:\n                go()\n",
    "if alpha and beta:\n    if gamma or delta:\n        compute()\n",
    "if a:\n    if b:\n        x=1\n    if c:\n        y=2\n",
    "if a:\n  if b:\n    do()\n",
    "if a:\n    if b:\n        do()\n        if c:\n            deep()\n",
    "if cond():\n    if other():\n        result = work()\n",
    "if a:\n\tif b:\n\t\tdo()\n",
]


def _snapshot(plan):
    return (
        dict(plan.new_contents),
        list(plan.blockers),
        dict(plan.edits_by_file),
        plan.ok,
    )


@pytest.mark.parametrize("src", SNIPPETS)
@pytest.mark.parametrize("rel", ["app/m.py", "app/pkg/sub.py"])
def test_plan_byte_identical(tmp_path, src, rel):
    """Full plan output matches original character-for-character."""
    def _plan(mod):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
        out = _snapshot(mod.plan_merge_nested_if(str(tmp_path), rel))
        path.unlink()
        return out

    assert _plan(orig_mod) == _plan(new_mod), f"mismatch rel={rel!r} src={src!r}"


@pytest.mark.parametrize("src", SNIPPETS)
def test_try_if_byte_identical(src):
    """``_try_if`` returns an identical rewrite (or None) on every ``ast.If``."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return  # unparseable source never reaches _try_if
    lines = src.splitlines(keepends=True)

    def _rw(mod, node):
        rw = mod._try_if(node, src, lines)
        if rw is None:
            return None
        return (rw.lo, rw.hi, rw.header, rw.body_lo, rw.body_hi, rw.unit)

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            assert _rw(orig_mod, node) == _rw(new_mod, node), repr(src)
