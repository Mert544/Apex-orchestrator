"""Performance-hardening characterization for ``detect``'s AST walks.

A scale red-team found ``detect(source)`` re-walked each file's AST four times
(the unreachable-code pass, the per-node dispatch, the SQL assignment map, and
the SQL sink scan), and the grade/readiness/dashboard pipeline re-invoked
``detect`` per file — ~6.8 min on a 1200-module repo.

The fix materializes one ``ast.walk`` and shares it across every logical pass,
and memoizes ``detect`` on the exact source string. Both changes are required to
be OUTPUT-PRESERVING: identical findings, identical order. These tests pin that:

  * exactly ONE whole-tree ``ast.walk`` per uncached ``detect`` (was four);
  * the per-source memo returns identical, independent results;
  * findings are byte-for-byte identical over a battery of real sources.

This file does NOT pin the *content* of findings (the kitchen-sink suites in
``test_detectors.py`` own that contract); it pins that the optimization changed
nothing.
"""

from __future__ import annotations

import ast
import glob

import app.engine.detectors as det
from app.engine.detectors import Issue, detect
from tests.test_detectors import _KITCHEN_SINK_SRC


def _findings(src: str):
    return [(i.line, i.category, i.severity, i.message, i.fix_kind) for i in detect(src)]


def _battery() -> dict[str, str]:
    sources = {
        "__kitchen__": _KITCHEN_SINK_SRC,
        "__empty__": "",
        "__only_comment__": "# nothing here\n",
        "__syntax_error__": "def f(:\n    pass\n",
        "__no_findings__": "def documented():\n    \"\"\"Doc.\"\"\"\n    return 1\n",
        "__sql_assigned__": (
            "def q(conn, name):\n"
            "    s = f\"select {name}\"\n"
            "    conn.execute(s)\n"
        ),
        "__unreachable__": (
            "def f():\n"
            "    return 1\n"
            "    x = 2\n"
        ),
    }
    for path in sorted(glob.glob("app/**/*.py", recursive=True))[:60]:
        try:
            sources[path] = open(path, encoding="utf-8").read()
        except OSError:
            pass
    return sources


def _count_module_walks(src: str) -> int:
    """Whole-tree ``ast.walk`` calls (those handed a ``Module``) for one detect()."""
    real = ast.walk
    seen: list[str] = []

    def spy(tree):
        seen.append(type(tree).__name__)
        return real(tree)

    det.ast.walk = spy
    try:
        det._DETECT_CACHE.clear()
        det.detect(src)
    finally:
        det.ast.walk = real
    return seen.count("Module")


def test_single_whole_tree_walk_per_uncached_detect():
    # The shared-walk collapse: exactly one Module-level ast.walk, not four.
    src = open("app/engine/idea_action_bridge.py", encoding="utf-8").read()
    assert _count_module_walks(src) == 1


def test_single_walk_holds_for_sql_and_unreachable_shapes():
    # The SQL and unreachable passes are the ones that used to add extra walks;
    # confirm they no longer re-walk the tree from scratch.
    sql_src = "def q(conn, n):\n    s = f\"select {n}\"\n    conn.execute(s)\n"
    dead_src = "def f():\n    return 1\n    x = 2\n"
    assert _count_module_walks(sql_src) == 1
    assert _count_module_walks(dead_src) == 1


def test_findings_byte_identical_over_battery():
    # Run twice (cold then warm) — both must equal each other; the optimization
    # changed nothing about the emitted findings or their order.
    det._DETECT_CACHE.clear()
    cold = {k: _findings(v) for k, v in _battery().items()}
    warm = {k: _findings(v) for k, v in _battery().items()}
    assert cold == warm


def test_memo_returns_equal_but_independent_lists():
    det._DETECT_CACHE.clear()
    src = _KITCHEN_SINK_SRC
    first = detect(src)
    second = detect(src)
    assert first == second
    # A fresh list each call: mutating one must not poison the cache.
    assert first is not second
    first.append(Issue(1, "bug", "low", "poison", ""))
    third = detect(src)
    assert third == second
    assert all(i.message != "poison" for i in third)


def test_memo_keyed_on_exact_source():
    det._DETECT_CACHE.clear()
    a = "def f():\n    return 1\n    x = 2\n"
    b = "def f():\n    return 1\n    x = 3\n"  # one char different
    fa, fb = detect(a), detect(b)
    # Both are cached; a second call returns the same findings (not b's).
    assert detect(a) == fa
    assert detect(b) == fb


def test_cache_is_bounded():
    det._DETECT_CACHE.clear()
    for i in range(det._DETECT_CACHE_MAX + 50):
        detect(f"x{i} = 1\n")
    assert len(det._DETECT_CACHE) <= det._DETECT_CACHE_MAX


def test_empty_and_syntax_error_paths_unaffected():
    det._DETECT_CACHE.clear()
    assert detect("") == []
    assert detect("# just a comment\n") == []
    err = detect("def f(:\n    pass\n")
    assert len(err) == 1 and err[0].category == "bug" and err[0].severity == "high"
    # Cached repeat returns an equal, independent list.
    again = detect("def f(:\n    pass\n")
    assert again == err and again is not err
