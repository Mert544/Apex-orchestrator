"""Characterization proof that the refactored ``find_near_duplicates`` is
byte-identical to the pre-refactor original.

The original module body is loaded from ``git show HEAD:app/engine/near_dup.py``
into a throwaway module and exercised side-by-side with the current implementation
over a battery of representative project trees, comparing the FULL output (group
order, occurrences, line counts, diff counts, and per-position difference columns)
plus the rendered markdown. Any mismatch fails the proof.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import app.engine.near_dup as refactored

_REPO = Path(__file__).resolve().parents[1]


def _load_original() -> types.ModuleType:
    """Compile the HEAD (pre-refactor) version of near_dup.py as ``_orig_near_dup``.

    It reuses the live ``app.engine`` package dependencies (``source_index`` is
    unchanged by this refactor), so only the near_dup body differs."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/engine/near_dup.py"], cwd=str(_REPO)
    ).decode()
    if "_window_template" in src and "_index_body" in src:
        pytest.skip("HEAD already contains the refactor; characterization is N/A")
    mod = types.ModuleType("_orig_near_dup")
    mod.__file__ = str(_REPO / "app" / "engine" / "near_dup.py")
    spec = importlib.util.spec_from_loader("_orig_near_dup", loader=None)
    mod.__spec__ = spec
    sys.modules["_orig_near_dup"] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _tree_simple(root: Path) -> None:
    _write(
        root,
        "a.py",
        "def f():\n"
        "    a = 1\n    b = 2\n    c = a + b\n    d = c * 3\n    e = d - 1\n"
        "    g = 1\n    h = 2\n    i = g + h\n    j = i * 4\n    k = j - 9\n"
        "    return e + k\n",
    )


def _tree_multibyte_and_names(root: Path) -> None:
    _write(
        root,
        "pkg/mod.py",
        "def alpha(x):\n"
        "    s = 'héllo'\n    t = x + 1\n    u = t * 2\n    v = u - 3\n    w = v\n"
        "    s2 = 'wörld'\n    t2 = x + 1\n    u2 = t2 * 2\n    v2 = u2 - 3\n    w2 = v2\n"
        "    return w + w2\n",
    )
    _write(
        root,
        "pkg/__init__.py",
        "",
    )


def _tree_async_and_nested(root: Path) -> None:
    _write(
        root,
        "b.py",
        "async def outer():\n"
        "    p = 10\n    q = p + 1\n    r = q + 2\n    s = r + 3\n    t = s + 4\n"
        "    def inner():\n"
        "        p = 20\n        q = p + 1\n        r = q + 2\n        s = r + 3\n        t = s + 4\n"
        "        return t\n"
        "    return inner() + t\n",
    )


def _tree_empty(root: Path) -> None:
    _write(root, "c.py", "x = 1\n")


def _tree_exact_dups(root: Path) -> None:
    # Identical blocks (no value diffs) — must be EXCLUDED, exercises diff_count==0 path.
    _write(
        root,
        "d.py",
        "def f():\n"
        "    a = 1\n    b = 1\n    c = 1\n    d = 1\n    e = 1\n"
        "    a = 1\n    b = 1\n    c = 1\n    d = 1\n    e = 1\n",
    )


_TREES = [
    _tree_simple,
    _tree_multibyte_and_names,
    _tree_async_and_nested,
    _tree_empty,
    _tree_exact_dups,
]

_PARAMS = [
    {"min_statements": 5, "min_occurrences": 2, "max_diffs": 3},
    {"min_statements": 3, "min_occurrences": 2, "max_diffs": 1},
    {"min_statements": 1, "min_occurrences": 2, "max_diffs": 5},
    {"min_statements": 2, "min_occurrences": 3, "max_diffs": 10},
    # degenerate / clamped inputs
    {"min_statements": 0, "min_occurrences": 0, "max_diffs": 0},
    {"min_statements": -4, "min_occurrences": -1, "max_diffs": -2},
]


@pytest.mark.parametrize("builder", _TREES, ids=[b.__name__ for b in _TREES])
@pytest.mark.parametrize("params", _PARAMS, ids=[str(p) for p in _PARAMS])
def test_byte_identical(builder, params, tmp_path):
    orig = _load_original()
    builder(tmp_path)

    g_old = orig.find_near_duplicates(str(tmp_path), **params)
    g_new = refactored.find_near_duplicates(str(tmp_path), **params)

    old_dicts = [g.to_dict() for g in g_old]
    new_dicts = [g.to_dict() for g in g_new]
    assert old_dicts == new_dicts

    # Full rendered markdown must also be byte-for-byte identical.
    assert orig.render_near_duplicates_markdown(
        g_old
    ) == refactored.render_near_duplicates_markdown(g_new)
