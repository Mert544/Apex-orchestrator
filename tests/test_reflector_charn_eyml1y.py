"""Characterization test: byte-identical refactor of Reflector.reflect.

Compares the refactored Reflector against the original HEAD snapshot across
many synthetic feedback histories that exercise every branch.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.engine.reflector import Reflector as RefactoredReflector

REPO = Path(__file__).resolve().parents[1]


def _load_original():
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/reflector.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    path = REPO / "tests" / "_reflector_orig_eyml1y_mod.py"
    path.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location("_reflector_orig_eyml1y", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_reflector_orig_eyml1y"] = mod
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.modules.pop("_reflector_orig_eyml1y", None)
        return mod.Reflector
    finally:
        path.unlink(missing_ok=True)


@dataclass
class FakeEntry:
    node_key: str
    feedback_score: float
    timestamp: str


class FakeFeedback:
    def __init__(self, entries):
        self.entries = entries


def _entry(k, s, ts):
    return FakeEntry(node_key=k, feedback_score=s, timestamp=ts)


def _scenarios():
    cases = []
    # empty
    cases.append([])
    # single success
    cases.append([_entry("a:1:1", 1.0, "2026-01-01 10:00:00")])
    # single failure
    cases.append([_entry("a:1:1", -0.5, "2026-01-01 10:00:00")])
    # single zero (neither success nor failure)
    cases.append([_entry("a:1:1", 0.0, "2026-01-01 10:00:00")])
    # high fp rate + low success (>0.3 fp, <0.5 success)
    cases.append([
        _entry("a:1:1", -1.0, "2026-01-01 10:00:00"),
        _entry("b:2:2", -1.0, "2026-01-01 11:00:00"),
        _entry("c:3:3", 1.0, "2026-01-02 11:00:00"),
    ])
    # all good -> "All patterns performing well"
    cases.append([
        _entry("a:1:1", 1.0, "2026-01-01 10:00:00"),
        _entry("a:1:1", 1.0, "2026-01-01 11:00:00"),
        _entry("b:2:2", 0.5, "2026-01-01 12:00:00"),
    ])
    # many nodes to test top-5 truncation and sorting
    big = []
    for i in range(12):
        score = -1.0 + (i * 0.1)
        big.append(_entry(f"n{i}:0:0", score, f"2026-02-{(i % 28) + 1:02d} 09:00:00"))
    cases.append(big)
    # mixed with multiple entries per node (averaging)
    cases.append([
        _entry("x:1:1", -1.0, "2026-03-01 10:00:00"),
        _entry("x:1:1", 1.0, "2026-03-01 11:00:00"),  # avg 0 -> not fp
        _entry("y:2:2", -0.5, "2026-03-01 12:00:00"),
        _entry("y:2:2", -0.5, "2026-03-02 12:00:00"),  # avg -0.5 -> fp
    ])
    # rounding edge: -0.005 average
    cases.append([
        _entry("z:1:1", -0.01, "2026-04-01 10:00:00"),
        _entry("z:1:1", 0.0, "2026-04-01 11:00:00"),
    ])
    # low success but fp not high (success<0.5, fp<=0.3)
    cases.append([
        _entry("a:1:1", 0.0, "2026-05-01 10:00:00"),
        _entry("b:2:2", 0.0, "2026-05-01 11:00:00"),
        _entry("c:3:3", 1.0, "2026-05-02 11:00:00"),
    ])
    # same day duplicates -> unique_days collapses
    cases.append([
        _entry("a:1:1", 1.0, "2026-06-01 10:00:00"),
        _entry("a:1:1", 1.0, "2026-06-01 23:59:00"),
    ])
    return cases


def test_byte_identical_against_original_snapshot():
    Original = _load_original()
    mismatches = 0
    for entries in _scenarios():
        orig = Original(FakeFeedback(list(entries))).reflect().to_dict()
        new = RefactoredReflector(FakeFeedback(list(entries))).reflect().to_dict()
        if orig != new:
            mismatches += 1
            print("MISMATCH", entries, orig, new)
    assert mismatches == 0
