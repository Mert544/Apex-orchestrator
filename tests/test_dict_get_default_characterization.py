"""Characterization harness: refactored ``dict_get_default`` is byte-identical
to the pre-refactor original across matching and non-matching snippets.

The original module source is loaded verbatim from git ``HEAD`` and executed in
an isolated module; both implementations are run through their full ``apply``
path and the produced ``new_content`` (or ``None``) is compared byte-for-byte.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types

import pytest

from app.execution.semantic.transforms import dict_get_default as refactored

ORIGINAL_REF = "HEAD"
ORIGINAL_PATH = "app/execution/semantic/transforms/dict_get_default.py"


def _load_original() -> types.ModuleType:
    src = subprocess.check_output(
        ["git", "show", f"{ORIGINAL_REF}:{ORIGINAL_PATH}"],
        text=True,
    )
    # Reuse the already-imported package so relative imports resolve.
    spec = importlib.util.spec_from_loader(
        "app.execution.semantic.transforms._dgd_original", loader=None
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.execution.semantic.transforms"
    sys.modules[mod.__name__] = mod
    exec(compile(src, "<dgd_original>", "exec"), mod.__dict__)
    return mod


original = _load_original()


# Snippets that SHOULD match (canonical shape) plus many that should NOT, to
# exercise every skip condition in the matcher.
SNIPPETS = [
    # --- matching ---
    "if k in d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if 'a' in d:\n    x = d['a']\nelse:\n    x = None\n",
    "if 1 in cfg:\n    v = cfg[1]\nelse:\n    v = -1\n",
    "if key in mapping:\n    out = mapping[key]\nelse:\n    out = fallback\n",
    "if k in d:\r\n    x = d[k]\r\nelse:\r\n    x = 0\r\n",
    "def f():\n    if k in d:\n        x = d[k]\n        return x\n",  # nested-but-not
    "    if k in d:\n        x = d[k]\n    else:\n        x = 0\n",  # indented EOF-ish
    "if k in d:\n    x = d[k]\nelse:\n    x = 0",  # no trailing newline
    "if True:\n    pass\nif k in d:\n    x = d[k]\nelse:\n    x = 0\n",
    # --- non-matching: wrong operator / shape ---
    "if k not in d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k in d and True:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k < d:\n    x = d[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\n",  # no else
    "if k in d:\n    x = d[k]\nelif j in d:\n    x = d[j]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k]\n    y = 1\nelse:\n    x = 0\n",  # extra stmt
    "if k in d:\n    x = d[k]\nelse:\n    x = 0\n    y = 1\n",  # extra else stmt
    # --- non-matching: target mismatch ---
    "if k in d:\n    x = d[k]\nelse:\n    y = 0\n",
    "if k in d:\n    x, y = d[k], 1\nelse:\n    x = 0\n",
    "if k in d:\n    a.b = d[k]\nelse:\n    a.b = 0\n",
    "if k in d:\n    x = x = d[k]\nelse:\n    x = 0\n",
    # --- non-matching: container/key mismatch ---
    "if k in d:\n    x = e[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[j]\nelse:\n    x = 0\n",
    "if 'a' in d:\n    x = d['b']\nelse:\n    x = 0\n",
    "if 1 in d:\n    x = d[1.0]\nelse:\n    x = 0\n",  # int vs float key
    # --- non-matching: complex container/key ---
    "if k in d.sub:\n    x = d.sub[k]\nelse:\n    x = 0\n",
    "if f() in d:\n    x = d[f()]\nelse:\n    x = 0\n",
    "if k in get():\n    x = get()[k]\nelse:\n    x = 0\n",
    "if k in d:\n    x = d[k:1]\nelse:\n    x = 0\n",  # slice
    # --- non-matching: subscript not a Load / not subscript ---
    "if k in d:\n    x = k\nelse:\n    x = 0\n",
    "if k in d:\n    x = d.get(k)\nelse:\n    x = 0\n",
    # --- non-matching: side-effectful default ---
    "if k in d:\n    x = d[k]\nelse:\n    x = compute()\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = a.b\n",
    "if k in d:\n    x = d[k]\nelse:\n    x = e[0]\n",
    # --- defaults that ARE simple (match) ---
    "if k in d:\n    x = d[k]\nelse:\n    x = other\n",
    # --- syntax error ---
    "if k in d\n    x = d[k]\n",
    "def (:\n",
    # --- empty / trivial ---
    "",
    "x = 1\n",
    "pass\n",
    # --- multiple ifs, only second matches ---
    "if a > b:\n    x = 1\nelse:\n    x = 2\nif k in d:\n    y = d[k]\nelse:\n    y = 0\n",
]


@pytest.mark.parametrize("source", SNIPPETS, ids=range(len(SNIPPETS)))
def test_apply_byte_identical(source: str) -> None:
    orig = original.apply("pkg/mod.py", source, "title")
    new = refactored.apply("pkg/mod.py", source, "title")

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


def test_matches_helper_byte_identical() -> None:
    """``_matches`` output (the replacement RHS) matches the original exactly."""
    import ast

    checked = 0
    for source in SNIPPETS:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                assert refactored._matches(node) == original._matches(node)
                checked += 1
    assert checked > 0
