"""Characterization tests for the pure helpers extracted from mine_git_pairs.

mine_git_pairs was decomposed into three pure helpers over parsed git output:
_shas_from_log, _single_change, and _expr_pair.  These tests pin the exact
behavior each helper inherited from the original monolithic loop, and confirm
the full pipeline still yields deterministic, byte-identical pairs (order +
contents) over mocked git output.
"""

from __future__ import annotations

import types

from app.engine import git_rule_miner
from app.engine.git_rule_miner import (
    _expr_pair,
    _shas_from_log,
    _single_change,
    mine_git_pairs,
)


# --- _shas_from_log ----------------------------------------------------------

def test_shas_from_log_extracts_first_token_per_line():
    out = "abc123 fix one\ndef456 fix two\n"
    assert _shas_from_log(out) == ["abc123", "def456"]


def test_shas_from_log_skips_blank_and_whitespace_only_lines():
    # "   " splits to [] under split(None, 1) and is dropped.
    out = "\n   \nabc123 real commit\n"
    assert _shas_from_log(out) == ["abc123"]


def test_shas_from_log_empty_input():
    assert _shas_from_log("") == []


# --- _single_change ----------------------------------------------------------

def test_single_change_returns_pair_for_one_removed_one_added():
    diff = (
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "-    return len(xs) == 0\n"
        "+    return not xs\n"
    )
    assert _single_change(diff) == ("    return len(xs) == 0", "    return not xs")


def test_single_change_skips_file_headers():
    # The --- / +++ header lines must not be counted as removed/added content.
    diff = "--- a/m.py\n+++ b/m.py\n-old\n+new\n"
    assert _single_change(diff) == ("old", "new")


def test_single_change_rejects_multi_line_change():
    diff = "--- a/m.py\n+++ b/m.py\n-a\n-b\n+c\n"
    assert _single_change(diff) is None


def test_single_change_rejects_zero_lines():
    assert _single_change("--- a/m.py\n+++ b/m.py\n") is None


# --- _expr_pair --------------------------------------------------------------

def test_expr_pair_unwraps_return_statements():
    assert _expr_pair("    return len(xs) == 0", "    return not xs") == (
        "len(xs) == 0",
        "not xs",
    )


def test_expr_pair_rejected_when_either_side_not_expression():
    assert _expr_pair("yield x", "    return not xs") is None
    assert _expr_pair("    return not xs", "yield x") is None


def test_expr_pair_rejected_when_expressions_identical():
    assert _expr_pair("    return not xs", "return  not xs") is None


# --- full pipeline characterization over mocked git output -------------------

def _fake_git(log_stdout, diffs):
    """Build a subprocess.run stand-in mapping sha -> diff stdout."""

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "log"]:
            return types.SimpleNamespace(returncode=0, stdout=log_stdout, stderr="")
        # diff: cmd is ["git", "diff", "<sha>^..<sha>", ...]
        ref = cmd[2]
        sha = ref.split("^", 1)[0]
        rc, out = diffs.get(sha, (1, ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    return fake_run


def test_pipeline_collects_clean_single_expr_changes_in_order(monkeypatch):
    log = "s1 fix one\ns2 multi\ns3 fix two\n"
    diffs = {
        "s1": (0, "--- a/m.py\n+++ b/m.py\n-    return a == True\n+    return a is True\n"),
        "s2": (0, "--- a/m.py\n+++ b/m.py\n-x\n-y\n+z\n"),  # multi -> skipped
        "s3": (0, "--- a/m.py\n+++ b/m.py\n-    return len(xs) == 0\n+    return not xs\n"),
    }
    monkeypatch.setattr(git_rule_miner.subprocess, "run", _fake_git(log, diffs))
    assert mine_git_pairs("/repo", max_commits=50) == [
        ("a == True", "a is True"),
        ("len(xs) == 0", "not xs"),
    ]


def test_pipeline_skips_nonzero_diff_returncode(monkeypatch):
    log = "s1 initial-no-parent\n"
    diffs = {"s1": (128, "")}  # merge/initial commit
    monkeypatch.setattr(git_rule_miner.subprocess, "run", _fake_git(log, diffs))
    assert mine_git_pairs("/repo") == []


def test_pipeline_empty_when_log_fails(monkeypatch):
    def fake_run(cmd, *args, **kwargs):
        return types.SimpleNamespace(returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(git_rule_miner.subprocess, "run", fake_run)
    assert mine_git_pairs("/repo") == []
