"""Deep-mutation hardening for ``SwarmCoordinator._emit_status`` stream routing.

The Batch-B determinism fix routes every ``[swarm] ...`` progress/status line to
STDERR, so ``apex scan``'s STDOUT stays byte-identical across runs for a fixed
repo state — only the deterministic findings/result land on STDOUT. The status
lines carry wall-clock timing (``Completed in {elapsed:.1f}s``) and are therefore
non-deterministic, so they MUST NOT pollute STDOUT.

These tests pin, capturing BOTH streams:

  * ``_emit_status`` writes ONLY to ``sys.stderr`` (nothing on stdout), with the
    exact ``[swarm] <message>\\n`` shape;
  * it honours the CURRENT ``sys.stderr`` binding (so a redirect/capture sees the
    line — a ``file=sys.stderr`` bound-at-import mutant would surface here);
  * an end-to-end ``run_autonomous`` emits its ``Goal:`` / ``Plan:`` / wall-clock
    ``Completed in Xs`` lines to STDERR and leaves STDOUT empty — in particular
    the non-deterministic ``Completed in Xs`` line is ABSENT from stdout;
  * the deterministic result (the returned list) is unaffected.
"""

from __future__ import annotations

import sys

from app.agents.swarm_coordinator import SwarmCoordinator


# --------------------------------------------------------------------------- #
# _emit_status in isolation: stderr only, exact shape.                         #
# --------------------------------------------------------------------------- #


def test_emit_status_writes_only_to_stderr(capsys):
    """A single status line lands on STDERR and STDOUT stays empty."""
    SwarmCoordinator()._emit_status("scanning repo")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[swarm] scanning repo\n"


def test_emit_status_exact_prefix_and_newline(capsys):
    """The line is exactly ``[swarm] <message>\\n`` — pins the prefix literal and
    the trailing newline (print's default end) against a dropped-prefix mutant."""
    SwarmCoordinator()._emit_status("Completed in 1.0s with 0 result(s)")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[swarm] Completed in 1.0s with 0 result(s)\n"


def test_emit_status_multiple_lines_all_on_stderr(capsys):
    """Several status lines accumulate on STDERR in order; STDOUT stays empty."""
    c = SwarmCoordinator()
    c._emit_status("first")
    c._emit_status("second")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[swarm] first\n[swarm] second\n"


def test_emit_status_honours_current_stderr_binding(monkeypatch):
    """``_emit_status`` resolves ``sys.stderr`` at call time, so a redirected
    stderr captures the line and stdout is untouched. Kills a mutant that bound
    the stream at import or wrote to stdout."""
    import io

    out_buf, err_buf = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out_buf)
    monkeypatch.setattr(sys, "stderr", err_buf)
    SwarmCoordinator()._emit_status("routed")
    assert out_buf.getvalue() == ""
    assert err_buf.getvalue() == "[swarm] routed\n"


# --------------------------------------------------------------------------- #
# End-to-end run_autonomous: status on stderr, deterministic result/stdout.    #
# --------------------------------------------------------------------------- #


def test_run_autonomous_keeps_stdout_clean_of_swarm_lines(capsys):
    """A full (fast) autonomous run routes ALL ``[swarm]`` lines to STDERR and
    leaves STDOUT free of them — the byte-identical-stdout guarantee."""
    result = SwarmCoordinator().run_autonomous(
        goal="security audit", target=".", mode="supervised", timeout=0.0)
    captured = capsys.readouterr()
    assert isinstance(result, list)
    assert "[swarm]" not in captured.out
    # The status lines went to stderr instead.
    assert "[swarm]" in captured.err


def test_completed_wallclock_line_absent_from_stdout(capsys):
    """The non-deterministic ``Completed in Xs`` wall-clock line must NOT appear
    on STDOUT (it is the exact line the fix moved off stdout); it appears on
    STDERR instead."""
    SwarmCoordinator().run_autonomous(
        goal="security audit", target=".", mode="supervised", timeout=0.0)
    captured = capsys.readouterr()
    assert "Completed in" not in captured.out
    assert "Completed in" in captured.err


def test_run_autonomous_goal_and_plan_lines_on_stderr(capsys):
    """The ``Goal:`` and ``Plan:`` status lines are emitted to STDERR (not
    stdout) — they are ``[swarm]``-prefixed progress, never result output."""
    SwarmCoordinator().run_autonomous(
        goal="security audit", target=".", mode="supervised", timeout=0.0)
    captured = capsys.readouterr()
    assert "[swarm] Goal:" in captured.err
    assert "[swarm] Plan:" in captured.err
    assert "Goal:" not in captured.out
    assert "Plan:" not in captured.out


def test_shutdown_previously_requested_line_on_stderr(capsys):
    """The early ``Shutdown previously requested`` status line is also routed to
    STDERR, and the run returns the empty deterministic result on the call site,
    not via stdout."""
    c = SwarmCoordinator()
    c._shutdown()  # request shutdown so run_autonomous takes the early-return path
    result = c.run_autonomous(goal="security audit", target=".")
    captured = capsys.readouterr()
    assert result == []
    assert captured.out == ""
    assert "[swarm] Shutdown previously requested" in captured.err
