"""Edge-path coverage for the near-duplicate detector's helpers.

Targets the position-less ``_segment`` fallbacks, the primitive-list-element
template branch, the overlapping-self de-dup (two windows that map to the same
``module:lineno``), and the memoized ``near_duplicates`` wrapper (cache hit,
cache miss, and ``fresh=True``). Inputs are built explicitly for determinism.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine import near_dup as nd
from app.engine.near_dup import (
    _segment,
    _split_source_lines,
    _walk_template,
    find_near_duplicates,
    near_duplicates,
)


def _write(root: Path, rel: str, body_lines: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")


# --- _segment: the position-less fallback branches -------------------------

def test_segment_fallback_for_positionless_constant():
    # A synthesized Constant with no position info -> repr(value) fallback.
    node = ast.Constant(value=42)
    assert _segment([], node) == "42"


def test_segment_fallback_for_positionless_name():
    node = ast.Name(id="foo", ctx=ast.Load())
    assert _segment([], node) == "foo"


def test_segment_fallback_for_positionless_other_node():
    # Any other position-less node falls back to its type name.
    node = ast.Pass()
    assert _segment([], node) == "Pass"


# --- _walk_template: a primitive (non-AST) list element --------------------

def test_walk_template_encodes_primitive_list_element():
    # ``ast.Global`` carries ``names: list[str]`` — primitive list elements that
    # must be encoded by repr rather than recursed into.
    src = "global a, b\n"
    stmt = ast.parse(src).body[0]
    lines = _split_source_lines(src)
    out: list[str] = []
    wildcards: dict[str, str] = {}
    _walk_template(stmt, lines, "", out, wildcards)
    template = "".join(out)
    assert "'a'" in template and "'b'" in template
    assert wildcards == {}


# --- overlapping-self de-dup: same module:lineno reached twice --------------

def test_overlapping_windows_same_lineno_counted_once(tmp_path: Path) -> None:
    # Six structurally identical statements packed onto ONE physical line via
    # ``;`` — so adjacent windows (start=0 and start=1) share an identical
    # template AND the same anchor lineno (``:2``). The second window therefore
    # hits the ``location in occ`` guard and is counted once, not twice.
    _write(tmp_path, "app/a.py", [
        "def alpha():",
        "    a = k; a = k; a = k; a = k; a = k; a = k",
    ])
    _write(tmp_path, "app/b.py", [
        "def beta():",
        "    a = k; a = k; a = k; a = k; a = k; a = m",
    ])
    # The scan runs the overlapping same-line windows through the de-dup guard.
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    # Every reported occurrence is unique despite the overlapping windows.
    for g in groups:
        assert len(g.occurrences) == len(set(g.occurrences))


# --- near_duplicates: memoized wrapper (miss, hit, fresh) ------------------

def _two_near_dup_modules(root: Path) -> None:
    body1 = ["    x = 1", "    y = x + 1", "    z = y + 2",
             "    w = z + 3", "    return w"]
    body2 = ["    x = 2", "    y = x + 1", "    z = y + 2",
             "    w = z + 3", "    return w"]
    _write(root, "app/a.py", ["def alpha():"] + body1)
    _write(root, "app/b.py", ["def beta():"] + body2)


def test_near_duplicates_caches_and_returns_same_object(tmp_path: Path) -> None:
    nd._NEAR_DUP_CACHE.clear()
    _two_near_dup_modules(tmp_path)
    first = near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    second = near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    # Cache hit returns the identical cached list object.
    assert first is second
    assert len(first) == 1


def test_near_duplicates_fresh_recomputes(tmp_path: Path) -> None:
    nd._NEAR_DUP_CACHE.clear()
    _two_near_dup_modules(tmp_path)
    cached = near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    fresh = near_duplicates(tmp_path, min_statements=5, min_occurrences=2,
                            fresh=True)
    # fresh=True bypasses the cache -> a freshly computed (distinct) list object
    # carrying equivalent data.
    assert fresh is not cached
    assert [g.to_dict() for g in fresh] == [g.to_dict() for g in cached]
