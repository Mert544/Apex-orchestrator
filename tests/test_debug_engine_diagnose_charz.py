"""Characterization harness for DebugEngine.diagnose refactor.

Proves the refactored diagnose is byte-identical to the original
(snapshot from HEAD) across many inputs covering every branch.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

from app.engine.debug_engine import DebugEngine

_ORIG_PATH = Path("/tmp/debug_engine_original.py")
_ORIG_MODNAME = "_debug_engine_original_snapshot"


def _load_original():
    spec = importlib.util.spec_from_file_location(_ORIG_MODNAME, _ORIG_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass annotation resolution can find the module.
    sys.modules[_ORIG_MODNAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_traces(engine, kind: str) -> None:
    if kind == "none":
        return
    engine.trace("setup", "ok detail")
    if kind == "error_phase":
        engine._traces[-1].phase = "error"
    elif kind == "exception_detail":
        engine._traces[-1].detail = "Something Exception happened"
    elif kind == "clean":
        engine._traces[-1].phase = "info"
        engine._traces[-1].detail = "all good"


def _seed_performance(EngineCls, perf_record_cls, engine, kind: str) -> None:
    if kind == "none":
        return
    rec = perf_record_cls("mod.fn", "mod")
    if kind == "fast":
        rec.call_count = 1
        rec.total_time_ms = 10.0
    elif kind == "slow":
        rec.call_count = 1
        rec.total_time_ms = 5000.0
    engine._performance["mod.fn"] = rec


_MEMORIES = [
    None,
    {},
    {f"k{i}": i for i in range(5)},
    {f"k{i}": i for i in range(1001)},
]

_CLAIM_SETS = [
    None,
    [],
    [{"status": "open", "text": "a", "evidence": ["e"], "depth": 1}],
    [{"status": "open"} for _ in range(60)],
    [{"status": "closed", "text": "x"} for _ in range(60)],
    [{"status": "open", "evidence": []} for _ in range(10)],
    [{"status": "open", "evidence": ["e"]} for _ in range(10)],
    [{"status": "open", "depth": 7, "evidence": ["e"]} for _ in range(3)],
    [{"status": "open", "depth": 3, "evidence": ["e"]} for _ in range(3)],
    # mixed: triggers open + no-evidence + stale simultaneously
    [{"status": "open", "depth": 9} for _ in range(55)],
    # half no-evidence boundary (exactly 0.5, should NOT trigger)
    [
        {"status": "closed", "evidence": ["e"]},
        {"status": "closed"},
    ],
]

_TRACE_KINDS = ["none", "error_phase", "exception_detail", "clean"]
_PERF_KINDS = ["none", "fast", "slow"]


def test_diagnose_byte_identical_against_original():
    orig_mod = _load_original()
    OrigEngine = orig_mod.DebugEngine
    OrigPerf = orig_mod.PerformanceRecord

    from app.engine.debug_engine import PerformanceRecord as NewPerf

    mismatches: list[str] = []
    combos = itertools.product(
        range(len(_MEMORIES)),
        range(len(_CLAIM_SETS)),
        _TRACE_KINDS,
        _PERF_KINDS,
    )
    count = 0
    for mi, ci, tk, pk in combos:
        count += 1
        memory = _MEMORIES[mi]
        claims = _CLAIM_SETS[ci]

        orig = OrigEngine(project_root=".", enabled=True)
        _seed_traces(orig, tk)
        _seed_performance(OrigEngine, OrigPerf, orig, pk)
        orig_out = orig.diagnose(
            memory=dict(memory) if memory is not None else None,
            claims=[dict(c) for c in claims] if claims is not None else None,
        )

        new = DebugEngine(project_root=".", enabled=True)
        _seed_traces(new, tk)
        _seed_performance(DebugEngine, NewPerf, new, pk)
        new_out = new.diagnose(
            memory=dict(memory) if memory is not None else None,
            claims=[dict(c) for c in claims] if claims is not None else None,
        )

        if orig_out != new_out:
            mismatches.append(
                f"mem={mi} claims={ci} trace={tk} perf={pk}: "
                f"orig={orig_out!r} new={new_out!r}"
            )

    assert not mismatches, "Byte-identical mismatches:\n" + "\n".join(mismatches)
    assert count == len(_MEMORIES) * len(_CLAIM_SETS) * len(_TRACE_KINDS) * len(_PERF_KINDS)


def test_diagnose_pure_helpers_are_static():
    # Helpers must be pure/static (no self dependence beyond passed args).
    for name in (
        "_diagnose_memory",
        "_diagnose_claims",
        "_diagnose_open_claims",
        "_diagnose_evidence",
        "_diagnose_stale_claims",
        "_diagnose_last_trace",
        "_diagnose_performance",
    ):
        assert isinstance(DebugEngine.__dict__[name], staticmethod), name


def test_diagnose_empty_returns_empty():
    d = DebugEngine(project_root=".")
    assert d.diagnose() == []
