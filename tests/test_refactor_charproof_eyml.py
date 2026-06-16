"""Characterization tests for the decomposed helpers in return_consistency and
dead_code_scan (refactor proof, session eyml). These pin the externally-visible
behavior of the small pure helpers extracted from ``_block_always_exits`` and
``analyze_dead_code`` so the decomposition stays byte-faithful."""
from __future__ import annotations

import ast

from app.tools.dead_code_scan import analyze_dead_code
from app.tools.return_consistency import _block_always_exits

# (source, expected) — one case per structural branch of _block_always_exits.
_BLOCK_CASES = [
    ("def f(): pass", False),                                  # plain stmt
    ("def f(): return 1", True),                               # return value
    ("def f(): return", True),                                 # bare return
    ("def f():\n raise X", True),                              # raise
    ("def f():\n if c: return 1", False),                      # if, no else
    ("def f():\n if c: return 1\n else: return 2", True),      # if/else both exit
    ("def f():\n if c: return 1\n else: pass", False),         # else falls through
    ("def f():\n with a: return 1", True),                     # with exits
    ("def f():\n with a: pass", False),                        # with falls through
    ("async def f():\n async with a: return 1", True),         # async with exits
    ("def f():\n try: return 1\n except: return 2", True),     # try+except exit
    ("def f():\n try: return 1\n except: pass", False),        # handler falls through
    ("def f():\n try: pass\n except: return 2", False),        # body falls through
    ("def f():\n try: return 1\n finally: return 9", True),    # finally exits
    ("def f():\n try: return 1\n finally: pass", True),        # body exits, finally pass
    ("def f():\n try: pass\n except A: return 2\n else: return 4", True),  # else+handler exit
    ("def f():\n try: pass\n except A: return 2\n else: pass", False),  # else falls through
    ("def f():\n for x in y: return 1", False),                # loop never proven
    ("def f():\n while c: return 1", False),                   # loop never proven
    ("def f():\n match x:\n  case 1: return 1", False),        # match not proven
]


def test_block_always_exits_all_branches():
    for source, expected in _BLOCK_CASES:
        fn = ast.parse(source).body[0]
        assert _block_always_exits(fn.body) is expected, source


def test_block_always_exits_empty_body():
    assert _block_always_exits([]) is False


def test_block_always_exits_try_else_and_handlers_exit():
    fn = ast.parse(
        "def f():\n try: pass\n except A: return 2\n except B: return 3\n else: return 4"
    ).body[0]
    assert _block_always_exits(fn.body) is True


def test_dead_code_full_rules(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .mod import *\n")
    (pkg / "mod.py").write_text(
        "__all__ = ['Exported']\n"
        "def used(): pass\n"
        "def Exported(): pass\n"
        "def dead_one(): pass\n"
        "class DeadClass: pass\n"
        "@deco\ndef decorated(): pass\n"
        "def main(): pass\n"
        "def cmd_x(): pass\n"
        "def __weird__(): pass\n"
        "x = used()\n"
        "ref = 'dead_one'\n"
    )
    (pkg / "dyn.py").write_text("def maybe(): pass\ngetattr(o, 'maybe')\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_a(): pass\ndef helper(): pass\n")

    report = analyze_dead_code(tmp_path)
    symbols = {c["symbol"] for c in report.candidates}
    # Only DeadClass survives: dead_one is string-referenced (rule 6), decorated
    # is decorated (rule 8), Exported is in __all__ (rule 3), main/cmd_x/__weird__
    # excluded (rules 4/2), maybe is in a dynamic-access module (rule 7), and the
    # tests/ defs are excluded definition sites (rule 10).
    assert symbols == {"DeadClass"}
    assert report.files_scanned == 4
    assert report.candidate_count == 1


def test_dead_code_reports_unreferenced(tmp_path):
    (tmp_path / "a.py").write_text("def live(): pass\nx = live()\ndef gone(): pass\n")
    report = analyze_dead_code(tmp_path)
    assert [c["symbol"] for c in report.candidates] == ["gone"]
    assert report.candidate_count == 1
    assert report.reported_count == 1
    assert report.truncated is False


def test_dead_code_missing_root():
    report = analyze_dead_code("/nonexistent_eyml_xyz")
    assert report.candidates == []
    assert report.files_scanned == 0
