"""Characterization harness: refactored transforms must be byte-identical to HEAD.

The pre-refactor sources of ``redundant_lambda`` and ``mutable_defaults`` are
loaded from disk snapshots and run side-by-side with the current (refactored)
modules over a large grab-bag of source snippets — convertible AND must-NOT-
convert. The full ``apply`` output (or ``None``) must match exactly for every
snippet, proving the decomposition changed no observable behaviour.
"""

from __future__ import annotations

import importlib.util

from app.execution.semantic.transforms import mutable_defaults as md_new
from app.execution.semantic.transforms import redundant_lambda as rl_new

_ORIG_DIR = "/tmp/charorig"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


rl_old = _load("redundant_lambda_orig", f"{_ORIG_DIR}/redundant_lambda_orig.py")
md_old = _load("mutable_defaults_orig", f"{_ORIG_DIR}/mutable_defaults_orig.py")


def _outcome(mod, src: str):
    r = mod.apply("m.py", src, "t")
    if r is None:
        return None
    return (
        r.transform_type,
        tuple(tuple(sorted(pr.items())) for pr in r.patch_requests),
        tuple(r.rationale),
    )


# --- redundant_lambda snippets -------------------------------------------------

_RL_SNIPPETS = [
    # fire
    "xs = sorted(ys, key=lambda x: f(x))\n",
    "r = reduce(lambda a, b: g(a, b), xs)\n",
    "h = lambda x: mod.sub.fn(x)\n",
    "z = lambda x: f(x)\n",
    "a = lambda x: f(x)\nb = lambda p, q: h(p, q)\n",
    "n = mapper(lambda p: ns.fn(p))\n",
    "a = lambda x: f(x)\nb = lambda u, v: g(u, v)\n",
    # refuse
    "z = lambda a, b: g(b, a)\n",
    "z = lambda a, b: g(a, b, c)\n",
    "z = lambda x: g(x, 1)\n",
    "z = lambda a, b: g(a)\n",
    "z = lambda x: g(x, k=1)\n",
    "z = lambda x: g(*x)\n",
    "z = lambda x: x.lower\n",
    "z = lambda x: x\n",
    "z = lambda x: x + 1\n",
    "z = lambda x: factory()(x)\n",
    "z = lambda x: tbl[0](x)\n",
    "z = lambda a, b=1: g(a, b)\n",
    "z = lambda *a: g(a)\n",
    "z = lambda **k: g(k)\n",
    "z = lambda x, *, y: g(x, y)\n",
    "z = lambda: f()\n",
    "z = lambda a: g(1)\n",
    # robustness
    "def f(:\n",
    "def f(x):\n    return x\n",
    "z = lambda x: f(\n    x)\n",
    # mixed grab bag
    (
        "w = sorted(xs, key=lambda x: f(x))\n"
        "k = lambda x: x.lower\n"
        "m = lambda a, b: g(b, a)\n"
        "n = mapper(lambda p: ns.fn(p))\n"
    ),
    # positional-only / kwonly variants
    "z = lambda a, /: g(a)\n",
    "z = lambda x, **k: g(x)\n",
    "z = lambda x: g(x, **k)\n",
    "z = lambda a, b, c: deep.chain.callable(a, b, c)\n",
    "",
    "y = lambda x: x()\n",
]


def test_redundant_lambda_byte_identical():
    mismatches = []
    for src in _RL_SNIPPETS:
        if _outcome(rl_old, src) != _outcome(rl_new, src):
            mismatches.append(src)
    assert mismatches == []


# --- mutable_defaults snippets -------------------------------------------------

_MD_SNIPPETS = [
    # fire (no future import)
    "def f(x=[]):\n    return x\n",
    "def f(x={}):\n    return x\n",
    "def f(x=set()):\n    return x\n",
    "def f(x=list()):\n    return x\n",
    "def f(x=dict()):\n    return x\n",
    "def f(x=[1, 2]):\n    return x\n",
    "def f(a, x=[], y={}):\n    return x\n",
    "def f(*, x=[]):\n    return x\n",
    "async def f(x=[]):\n    return x\n",
    "def outer():\n    def inner(x=[]):\n        return x\n    return inner\n",
    # refuse / no-op
    "def f(x=None):\n    return x\n",
    "def f(x=()):\n    return x\n",
    "def f(x=5):\n    return x\n",
    "def f(x=list(1)):\n    return x\n",
    "def f(x=set(a=1)):\n    return x\n",
    "def f():\n    return 1\n",
    "x = 5\n",
    "def f(:\n",
    "",
    # multiline default — skipped
    "def f(x=[\n    1,\n    2,\n]):\n    return x\n",
    # annotation widening WITH future import
    "from __future__ import annotations\n\ndef f(x: list = []):\n    return x\n",
    "from __future__ import annotations\n\ndef f(x: list[str] = []):\n    return x\n",
    "from __future__ import annotations\n\ndef f(x: list | None = []):\n    return x\n",
    "from __future__ import annotations\n\ndef f(x: 'Optional[list]' = []):\n    return x\n",
    "from __future__ import annotations\n\ndef f(x=[], y: dict = {}):\n    return x\n",
    # future import but no annotation
    "from __future__ import annotations\n\ndef f(x=[]):\n    return x\n",
    # multiple functions, deepest-first ordering
    "def a(x=[]):\n    return x\n\ndef b(y={}):\n    return y\n",
    # nested deep
    "def a(x=[]):\n    def b(y={}):\n        return y\n    return b\n",
    # kwonly with None mixed
    "def f(*, x=[], y=None):\n    return x\n",
    # indented (method)
    "class C:\n    def m(self, x=[]):\n        return x\n",
]


def test_mutable_defaults_byte_identical():
    mismatches = []
    for src in _MD_SNIPPETS:
        if _outcome(md_old, src) != _outcome(md_new, src):
            mismatches.append(src)
    assert mismatches == []
