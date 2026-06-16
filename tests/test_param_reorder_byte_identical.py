"""Characterization: the refactored ``param_reorder`` produces plan output
byte-identical to the pre-refactor HEAD snapshot across many signatures.

The original module is loaded from ``git show HEAD:...`` into an isolated
module object; both versions run through the full ``plan_*`` path and every
field of the resulting plan is compared character-for-character.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

import app.execution.param_reorder as refactored


def _load_head_snapshot() -> types.ModuleType:
    """Import the HEAD version of param_reorder.py as a standalone module."""
    repo = Path(__file__).resolve().parents[1]
    src = subprocess.run(
        ["git", "show", "HEAD:app/execution/param_reorder.py"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    name = "_param_reorder_head_snapshot"
    mod = types.ModuleType(name)
    mod.__file__ = str(repo / "app" / "execution" / "param_reorder.py")
    sys.modules[name] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


_HEAD = _load_head_snapshot()


# A spread of signatures exercising every branch of _rebuild_reordered:
# posonly prefix, /, regular params, defaults, *args, *, kwonly, **kwargs,
# annotations (spaced =) vs none (bare =), and required-after-default fails.
_SIGNATURES = [
    "def f(a, b, c): return a",
    "def f(a, b): return a",
    "def f(a: int, b: str): return a",
    "def f(a=1, b=2): return a",
    "def f(a: int = 1, b: str = '2'): return a",
    "def f(a, b=2, c=3): return a",
    "def f(a: int, b: str = 'x', c=3): return a",
    "def f(p, /, a, b): return a",
    "def f(p, q, /, a, b=2): return a",
    "def f(p: int, /, a: str, b=2): return a",
    "def f(a, b, *args): return a",
    "def f(a, b, *args, k=1): return a",
    "def f(a, b, *, k1, k2=2): return a",
    "def f(a, b, *, k1: int, k2: str = 'z'): return a",
    "def f(a, b, **kw): return a",
    "def f(a, b, *args, k=1, **kw): return a",
    "def f(p, /, a, b, *args, k1, k2=2, **kw): return a",
    "def f(p: int = 0, /, a: str = 'a', *, k=1): return a",
    "async def f(a, b, c): return a",
    "async def f(p, /, a, b=2, *, k): return a",
]

# (signature_index, order) — each order is a permutation of that signature's
# REGULAR (non-posonly, non-kwonly) params, matching the upstream
# _validate_permutation contract. Some move a required param after a
# defaulted one (should yield None / "wouldn't compile" blocker).
_ORDERS = [
    (0, ["c", "b", "a"]),
    (0, ["b", "a", "c"]),
    (1, ["b", "a"]),
    (2, ["b", "a"]),
    (3, ["b", "a"]),
    (4, ["b", "a"]),
    (5, ["b", "a", "c"]),       # b has default, a required -> None
    (5, ["a", "c", "b"]),
    (6, ["b", "a", "c"]),       # b has default, a required -> None
    (6, ["a", "c", "b"]),
    (7, ["b", "a"]),
    (8, ["b", "a"]),
    (9, ["b", "a"]),            # b has default, a required -> None
    (10, ["b", "a"]),
    (11, ["b", "a"]),
    (12, ["b", "a"]),
    (13, ["b", "a"]),
    (14, ["b", "a"]),
    (15, ["b", "a"]),
    (16, ["b", "a"]),
    (18, ["c", "b", "a"]),
    (19, ["b", "a"]),
]


def _direct_rebuild(mod: types.ModuleType, sig: str, order: list[str]):
    tree = ast.parse(sig)
    fn = tree.body[0]
    return mod._rebuild_reordered(sig, fn, order)


def test_rebuild_reordered_byte_identical():
    mismatches = []
    for idx, order in _ORDERS:
        sig = _SIGNATURES[idx]
        ours = _direct_rebuild(refactored, sig, order)
        head = _direct_rebuild(_HEAD, sig, order)
        if ours != head:
            mismatches.append((sig, order, head, ours))
    assert not mismatches, mismatches


def _project(tmp_path: Path, sig: str) -> Path:
    (tmp_path / "app").mkdir(parents=True)
    body = sig if "\n" in sig else sig
    (tmp_path / "app" / "core.py").write_text(body + "\n")
    return tmp_path


def _plan_repr(plan) -> tuple:
    """A fully comparable snapshot of every plan field."""
    return (
        plan.old, plan.new, getattr(plan, "defined_in", None),
        tuple(sorted(plan.blockers)),
        tuple(sorted(plan.originals.items())),
        tuple(sorted(plan.new_contents.items())),
        tuple(sorted(plan.edits_by_file.items())),
    )


def test_full_plan_byte_identical(tmp_path):
    mismatches = []
    for i, (idx, order) in enumerate(_ORDERS):
        sig = _SIGNATURES[idx]
        d_ref = _project(tmp_path / f"ref_{i}", sig)
        d_head = _project(tmp_path / f"head_{i}", sig)
        # rename the def to a stable name 'f' already used; both run identical.
        p_ref = refactored.plan_param_reorder(d_ref, "f", order)
        p_head = _HEAD.plan_param_reorder(d_head, "f", order)
        r_ref = _plan_repr(p_ref)
        r_head = _plan_repr(p_head)
        if r_ref != r_head:
            mismatches.append((sig, order, r_head, r_ref))
    assert not mismatches, mismatches
