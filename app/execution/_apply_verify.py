"""Shared test-verification tail for the multi-file apply operations.

:func:`app.execution.cross_file_rename.apply_rename` and
:func:`app.execution.move_module.apply_move` each, after writing their planned
files, run the project's full test suite and stamp the SAME outcome onto the
result dict. That nine-line tail — import the runner, run the suite, record
``verified`` / ``test_evidence``, and decide whether the change stands or must be
rolled back — was byte-identical across the two operations (the duplication
detector flagged it as a shared statement window), so it lives here once and both
operations call it.

This is a **library** (leading underscore in the filename) — it is never an
objective and exposes no ``plan_*`` entry point. It imports nothing from the
transforms (it pulls the test runner lazily, exactly as the inlined copies did),
so it can never form an import cycle with them. Deterministic and stdlib-only —
no time, no randomness.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["run_full_suite_verification", "suite_baseline_green"]


def suite_baseline_green(root: Path) -> bool:
    """One-time BASELINE pre-flight: was the suite ALREADY green before any fix?

    Run the project's full test suite ONCE — with no patch applied — and report
    whether it passes. A maintenance pass calls this exactly once, before its
    first apply, and caches the bool: a fix verified against an already-RED
    baseline cannot attribute a green-after to itself, so it must be recorded
    inconclusive rather than verified.

    "No test command to run" counts as a GREEN baseline (the same convention
    :func:`run_full_suite_verification` uses for an empty ``commands`` list — a
    project with no suite is not a *failing* suite). Deterministic and
    stdlib-only — the runner is imported lazily, exactly as the verification
    tail does, so this never forms an import cycle with the transforms."""
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    return bool(summary.ok) or not summary.commands


def run_full_suite_verification(root: Path, out: dict) -> bool:
    """Run the project's full test suite and stamp the verdict onto ``out``.

    Records ``out["verified"]`` (a bool) and ``out["test_evidence"]`` (the
    summarised run). Returns ``True`` when the change stands — either the tests
    passed or there were no test commands to run — having already set
    ``out["rolled_back"] = False``; the caller returns ``out`` unchanged. Returns
    ``False`` when the tests failed, leaving ``out`` for the caller to finish its
    own rollback. This is the byte-identical verification tail both
    :func:`~app.execution.cross_file_rename.apply_rename` and
    :func:`~app.execution.move_module.apply_move` carried verbatim, with the
    runner imported lazily exactly as the inlined copies did."""
    from app.engine.proof_of_fix import summarize_test_run
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    out["verified"] = bool(summary.ok)
    out["test_evidence"] = summarize_test_run(summary)
    if summary.ok or not summary.commands:
        out["rolled_back"] = False
        return True
    return False
