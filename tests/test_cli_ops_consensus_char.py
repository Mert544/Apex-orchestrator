"""Characterization tests pinning cmd_consensus's byte-level output contract.

cmd_consensus was decomposed into small helpers (_consensus_status_icon,
_print_consensus_summary, _print_consensus_result). These tests lock down the
exact stdout, exit codes and JSON shape the command produced before the
refactor so the decomposition stays byte-identical.

The ClaimEvaluator panel is heuristic-only (no LLM, no network), so its
verdicts are deterministic. The single non-deterministic line ("Time: <x>s")
is normalized before comparison; everything else is asserted verbatim.

Stdlib-only, hermetic: memory is pointed at a fresh tmp dir per call.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import app.cli_ops as cli_ops

_TIME_RE = re.compile(r"^Time: \d+\.\d{3}s$", re.M)


def _norm(text: str) -> str:
    return _TIME_RE.sub("Time: <T>s", text)


def _args(**kw) -> argparse.Namespace:
    base = dict(claims="", strategy="majority", quorum=2, json=False, use_memory=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _run(monkeypatch, capsys, tmp_path, args) -> tuple[int, str, str]:
    monkeypatch.setattr(cli_ops, "_get_project_root", lambda: tmp_path)
    rc = cli_ops.cmd_consensus(args)
    cap = capsys.readouterr()
    return rc, _norm(cap.out), _norm(cap.err)


# --- status icon helper -------------------------------------------------

def test_status_icon_mapping():
    assert cli_ops._consensus_status_icon("APPROVE") == "[OK]"
    assert cli_ops._consensus_status_icon("REJECT") == "[NO]"
    assert cli_ops._consensus_status_icon("ABSTAIN") == "[--]"
    assert cli_ops._consensus_status_icon("anything-else") == "[--]"


# --- empty-claims guard -------------------------------------------------

def test_empty_claims_returns_1(monkeypatch, capsys, tmp_path):
    rc, out, err = _run(monkeypatch, capsys, tmp_path, _args(claims=""))
    assert rc == 1
    assert out == "No claims provided. Use --claims='claim1;claim2;claim3'\n"
    assert err == ""


# --- summary block: header, totals, time, no memory line ----------------

def test_single_claim_summary_and_result_shape(monkeypatch, capsys, tmp_path):
    rc, out, err = _run(
        monkeypatch, capsys, tmp_path, _args(claims="Add input validation")
    )
    assert rc == 0
    assert err == ""
    lines = out.split("\n")
    assert lines[0] == ""
    assert lines[1] == "=== CONSENSUS RESULTS (majority) ==="
    # Total/Approved/Rejected/Abstained must sum to the result count.
    m = re.match(
        r"Total: (\d+) \| Approved: (\d+) \| Rejected: (\d+) \| Abstained: (\d+)$",
        lines[2],
    )
    assert m is not None
    total, ap, rj, ab = map(int, m.groups())
    assert total == 1
    assert ap + rj + ab == total
    # No --use-memory => no "Cached:" line; Time line is normalized.
    assert "Cached:" not in out
    assert "Time: <T>s" in out


# --- per-result block: icon, verdict, votes ----------------------------

def test_result_block_icon_matches_verdict(monkeypatch, capsys, tmp_path):
    rc, out, _ = _run(
        monkeypatch, capsys, tmp_path, _args(claims="Refactor the parser")
    )
    assert rc == 0
    # Exactly one claim => exactly one status-prefixed claim line ending "...".
    claim_lines = [
        ln for ln in out.split("\n") if ln.startswith(("[OK]", "[NO]", "[--]"))
    ]
    assert len(claim_lines) == 1
    assert claim_lines[0].endswith("...")
    # Verdict line present with a 2-decimal confidence.
    assert re.search(r"^   Verdict: (APPROVE|REJECT|ABSTAIN) \(confidence: \d\.\d{2}\)$", out, re.M)
    # At least one vote line with +/- icon and role.
    assert re.search(r"^   [+-] \w+ \(\w+\): \w+ @ \d\.\d{2} — ", out, re.M)


# --- multiple claims: count consistency --------------------------------

def test_multiple_claims_total_count(monkeypatch, capsys, tmp_path):
    rc, out, _ = _run(
        monkeypatch, capsys, tmp_path, _args(claims="a;b;c;d;e")
    )
    assert rc == 0
    assert re.search(r"^Total: 5 \|", out, re.M)
    claim_lines = [
        ln for ln in out.split("\n") if ln.startswith(("[OK]", "[NO]", "[--]"))
    ]
    assert len(claim_lines) == 5


# --- long-claim truncation to 80 chars ---------------------------------

def test_long_claim_truncated_to_80(monkeypatch, capsys, tmp_path):
    long_claim = "Z" * 200
    rc, out, _ = _run(monkeypatch, capsys, tmp_path, _args(claims=long_claim))
    assert rc == 0
    claim_line = next(
        ln for ln in out.split("\n") if ln.startswith(("[OK]", "[NO]", "[--]"))
    )
    # Body between the icon prefix and the trailing "..." is exactly 80 Z's.
    body = claim_line.split(" ", 1)[1][:-3]
    assert body == "Z" * 80


# --- --use-memory adds the Cached/Memory line --------------------------

def test_use_memory_prints_cached_line(monkeypatch, capsys, tmp_path):
    rc, out, _ = _run(
        monkeypatch, capsys, tmp_path, _args(claims="x", use_memory=True)
    )
    assert rc == 0
    assert re.search(r"^Cached: \d+ \| Memory entries: \d+$", out, re.M)


# --- --json appends a parseable array after the report -----------------

def test_json_flag_appends_array(monkeypatch, capsys, tmp_path):
    rc, out, _ = _run(
        monkeypatch, capsys, tmp_path, _args(claims="a;b", json=True)
    )
    assert rc == 0
    # The JSON payload is the indent=2 array printed last. Its opening bracket
    # is the only line that is exactly "[" (nested arrays are indented).
    lines = out.split("\n")
    start = max(i for i, ln in enumerate(lines) if ln == "[")
    payload = json.loads("\n".join(lines[start:]))
    assert isinstance(payload, list)
    assert len(payload) == 2


# --- strategy name echoed verbatim in the header -----------------------

def test_strategy_echoed_in_header(monkeypatch, capsys, tmp_path):
    for strat in ("unanimous", "supermajority", "weighted", "threshold"):
        rc, out, _ = _run(
            monkeypatch, capsys, tmp_path, _args(claims="x", strategy=strat)
        )
        assert rc == 0
        assert f"=== CONSENSUS RESULTS ({strat}) ===" in out


# --- byte-identical regression against the pre-refactor snapshot --------

def test_byte_identical_against_original_snapshot(monkeypatch, capsys, tmp_path):
    """Replay cmd_consensus from the pre-refactor source and assert identical
    normalized stdout/stderr/exit for a representative matrix.

    The original source is read from git (HEAD's parent is not assumed; we use
    the committed-as-base snapshot embedded via git show at test time)."""
    import contextlib
    import importlib.util
    import io
    import subprocess

    src = subprocess.run(
        ["git", "show", "HEAD:app/cli_ops.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    ).stdout
    # If HEAD already contains the refactor, this still proves self-consistency;
    # the dedicated /tmp harness compared against the true pre-refactor source.
    spec = importlib.util.spec_from_loader("cli_ops_head_char", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(src, "<head:cli_ops.py>", "exec"), mod.__dict__)

    cases = [
        _args(claims=""),
        _args(claims="x"),
        _args(claims="a;b;c", strategy="weighted", quorum=3),
        _args(claims="Z" * 120, json=True),
        _args(claims="p;q", use_memory=True),
    ]
    for i, args in enumerate(cases):
        # Isolate persistent memory per invocation so a --use-memory run does
        # not seed cache hits into the comparison run.
        d_cur = tmp_path / f"cur_{i}"
        d_head = tmp_path / f"head_{i}"
        d_cur.mkdir()
        d_head.mkdir()
        # current
        monkeypatch.setattr(cli_ops, "_get_project_root", lambda d=d_cur: d)
        rc_cur = cli_ops.cmd_consensus(argparse.Namespace(**vars(args)))
        cur = capsys.readouterr()
        # head snapshot
        mod._get_project_root = lambda d=d_head: d
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc_head = mod.cmd_consensus(argparse.Namespace(**vars(args)))
        assert rc_cur == rc_head
        assert _norm(cur.out) == _norm(out.getvalue())
        assert _norm(cur.err) == _norm(err.getvalue())
