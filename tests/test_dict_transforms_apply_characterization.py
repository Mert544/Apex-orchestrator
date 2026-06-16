"""Characterization harness: the refactored ``apply`` of ``dict_literal`` and
``dict_get_default`` is byte-identical to the pre-refactor original.

Both original module sources are loaded verbatim from git ``HEAD`` and executed
in isolated modules; the original and refactored ``apply`` are run over many
convertible and must-NOT-convert snippets, comparing the full produced result
(``new_content`` / ``expected_old_content`` / ``path`` / ``transform_type`` /
``rationale``) or ``None`` for byte equality. Zero mismatches are tolerated.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types

import pytest

from app.execution.semantic.transforms import dict_get_default as dgd_refactored
from app.execution.semantic.transforms import dict_literal as dl_refactored

ORIGINAL_REF = "HEAD"


def _load_original(rel_path: str, mod_name: str) -> types.ModuleType:
    src = subprocess.check_output(
        ["git", "show", f"{ORIGINAL_REF}:{rel_path}"],
        text=True,
    )
    # Reuse the already-imported package so relative imports resolve.
    full_name = f"app.execution.semantic.transforms.{mod_name}"
    spec = importlib.util.spec_from_loader(full_name, loader=None)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.execution.semantic.transforms"
    sys.modules[mod.__name__] = mod
    exec(compile(src, f"<{mod_name}>", "exec"), mod.__dict__)
    return mod


dl_original = _load_original(
    "app/execution/semantic/transforms/dict_literal.py", "_dl_original"
)
dgd_original = _load_original(
    "app/execution/semantic/transforms/dict_get_default.py", "_dgd_original2"
)


# ---------------------------------------------------------------------------
# dict_literal snippets: convertible ``dict(a=1, ...)`` and must-NOT-convert.
# ---------------------------------------------------------------------------
DL_SNIPPETS = [
    # --- convertible ---
    "x = dict(a=1)\n",
    "x = dict(a=1, b=2)\n",
    "x = dict(a=1, b=2, c=3)\n",
    "y = dict(name='n', value=2 + 3)\n",
    "z = dict(a=[1, 2], b={'k': 'v'})\n",
    "w = dict(a=f(1), b=g(x, y))\n",
    "cfg = dict(timeout=30, retries=5)\n",
    "x = dict(a=1)\r\n",  # CRLF
    "x = dict(a=1)",  # no trailing newline
    "x = dict(\n    a=1,\n    b=2,\n)\n",  # multiline
    "x = dict(a=dict(b=1))\n",  # nested -> both rewritten
    "vals = [dict(a=1), dict(b=2)]\n",  # two on one line
    "x = dict(a=1)\ny = dict(b=2)\n",  # two separate
    "x = dict(_a=1, b2=3)\n",  # identifier-ish kwargs
    # --- must NOT convert ---
    "x = dict()\n",  # empty
    "x = dict(other)\n",  # positional only
    "x = dict(other, a=1)\n",  # positional + kw
    "x = dict(**other)\n",  # ** unpacking
    "x = dict(a=1, **other)\n",  # kw + **
    "x = dict([('a', 1)])\n",  # iterable positional
    "x = Dict(a=1)\n",  # wrong name
    "x = obj.dict(a=1)\n",  # attribute, not Name
    "dict = 5\nx = dict\n",  # not a call
    "x = mydict(a=1)\n",  # different name
    # --- syntax error / trivial ---
    "x = dict(a=1\n",  # syntax error
    "",
    "pass\n",
    "x = 1\n",
    "d = {'a': 1}\n",  # already a literal
]


# ---------------------------------------------------------------------------
# dict_get_default snippets: canonical shape and every skip condition.
# ---------------------------------------------------------------------------
DGD_SNIPPETS = [
    # --- matching ---
    "if k in d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if 'a' in d:\n    x = d['a']\nelse:\n    x = None\n",
    "if 1 in cfg:\n    v = cfg[1]\nelse:\n    v = -1\n",
    "if key in mapping:\n    out = mapping[key]\nelse:\n    out = fallback\n",
    "if k in d:\r\n    x = d[k]\r\nelse:\r\n    x = 0\r\n",
    "    if k in d:\n        x = d[k]\n    else:\n        x = 0\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = 0",  # no trailing newline
    "if True:\n    pass\nif k in d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = other\n",
    # --- non-matching: wrong operator / shape ---
    "if k not in d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k in d and True:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k < d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\n",  # no else
    "if k in d:\n    x = d[k]\nelif j in d:\n    x = d[j]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\n    y = 1\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = 0\n    y = 1\n",
    # --- non-matching: target / container / key mismatch ---
    "if k in d:\n    x = d[k]\nelse:\n    y = 0\n",
    "if k in d:\n    a.b = d[k]\nelse:\n    a.b = 0\n",
    "if k in d:\n    x = e[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[j]\nelse:\n    x = 0\n",
    "if 1 in d:\n    x = d[1.0]\nelse:\n    x = 0\n",
    # --- non-matching: complex container/key ---
    "if k in d.sub:\n    x = d.sub[k]\nelse:\n    x = 0\n",
    "if f() in d:\n    x = d[f()]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k:1]\nelse:\n    x = 0\n",  # slice
    # --- non-matching: not subscript / side-effectful default ---
    "if k in d:\n    x = d.get(k)\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = compute()\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = a.b\n",
    # --- syntax error / trivial / multi ---
    "if k in d\n    x = d[k]\n",
    "",
    "x = 1\n",
    "if a > b:\n    x = 1\nelse:\n    x = 2\nif k in d:\n    y = d[k]\nelse:\n    y = 0\n",
]


def _assert_result_identical(orig, new) -> None:
    if orig is None:
        assert new is None
        return
    assert new is not None
    o = orig.patch_requests[0]
    n = new.patch_requests[0]
    assert o["new_content"] == n["new_content"]
    assert o["expected_old_content"] == n["expected_old_content"]
    assert o["path"] == n["path"]
    assert orig.transform_type == new.transform_type
    assert orig.rationale == new.rationale


@pytest.mark.parametrize("source", DL_SNIPPETS, ids=range(len(DL_SNIPPETS)))
def test_dict_literal_apply_byte_identical(source: str) -> None:
    orig = dl_original.apply("pkg/mod.py", source, "title")
    new = dl_refactored.apply("pkg/mod.py", source, "title")
    _assert_result_identical(orig, new)


@pytest.mark.parametrize("source", DGD_SNIPPETS, ids=range(len(DGD_SNIPPETS)))
def test_dict_get_default_apply_byte_identical(source: str) -> None:
    orig = dgd_original.apply("pkg/mod.py", source, "title")
    new = dgd_refactored.apply("pkg/mod.py", source, "title")
    _assert_result_identical(orig, new)


def test_at_least_one_match_each() -> None:
    """Sanity: both harnesses include snippets that actually convert."""
    dl_hits = sum(
        dl_refactored.apply("m.py", s, "t") is not None for s in DL_SNIPPETS
    )
    dgd_hits = sum(
        dgd_refactored.apply("m.py", s, "t") is not None for s in DGD_SNIPPETS
    )
    assert dl_hits > 0
    assert dgd_hits > 0
