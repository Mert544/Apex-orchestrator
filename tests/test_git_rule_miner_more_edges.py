"""Additional edge-path tests for git_rule_miner.

Complements test_git_rule_miner_edges.py by reaching the remaining uncovered
branches: the bare expression-statement segment that is *not* itself a valid
eval expression (yield / starred), and the blank git-log-line guard.
"""

from __future__ import annotations

import subprocess
import types

from app.engine import git_rule_miner
from app.engine.git_rule_miner import _extract_expr, mine_git_pairs


# --- _extract_expr: Expr-statement whose segment is not eval-parseable --------

def test_yield_expression_statement_segment_rejected():
    """`yield x` parses as an Expr statement (line 46) but its extracted
    segment 'yield x' is not a valid eval expression (lines 54-55) -> None."""
    assert _extract_expr("yield x") is None


def test_starred_expression_statement_segment_rejected():
    """A bare starred expression is an Expr statement whose segment fails the
    eval re-parse and is rejected."""
    assert _extract_expr("*a,") is None


# --- mine_git_pairs: blank log line guard (line 81) --------------------------

def test_blank_log_line_split_is_skipped(monkeypatch):
    """A blank line in `git log` output splits to [] and is skipped without
    attempting any diff."""
    calls = {"diff": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "log"]:
            # Emit a blank line plus a real-looking sha line.
            return types.SimpleNamespace(returncode=0, stdout="\n   \n", stderr="")
        # Any diff call would mean the blank line wasn't skipped.
        calls["diff"] += 1
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(git_rule_miner.subprocess, "run", fake_run)
    assert mine_git_pairs("/whatever", max_commits=5) == []
    # The whitespace-only line yields no sha, so no diff is run for it.
    # (A non-empty "   " line splits to [] under split(None, 1).)
    assert calls["diff"] == 0


def test_log_nonzero_returncode_returns_empty(monkeypatch):
    """A failing `git log` (not a repo) short-circuits to []."""

    def fake_run(cmd, *args, **kwargs):
        return types.SimpleNamespace(returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(git_rule_miner.subprocess, "run", fake_run)
    assert mine_git_pairs("/not-a-repo") == []


def test_diff_nonzero_returncode_skips_commit(monkeypatch):
    """A commit whose diff fails (initial/merge commit) is skipped, not fatal."""

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "log"]:
            return types.SimpleNamespace(returncode=0, stdout="abc123 init\n", stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="bad rev")

    monkeypatch.setattr(git_rule_miner.subprocess, "run", fake_run)
    assert mine_git_pairs("/repo") == []


def test_real_subprocess_module_used():
    """Sanity: the module imports the stdlib subprocess (no shadowing)."""
    assert git_rule_miner.subprocess is subprocess
