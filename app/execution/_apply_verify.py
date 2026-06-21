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
import re

__all__ = [
    "NO_SUITE",
    "mark_no_suite",
    "run_full_suite_verification",
    "stamp_coverage_strength",
    "suite_baseline_green",
    "suite_failing_nodes",
]

# pytest's short-summary failure lines name every failing node id, e.g.
# ``FAILED tests/test_x.py::test_y - AssertionError``. We want the WHOLE set (the
# proof summariser caps its copy at 5 for human display; the rollback backstop
# needs every one to diff baseline-green vs. after), so this parses them directly.
# Matches both ``FAILED <node>`` and ``ERROR <node>``; the trailing ``- reason``
# (if any) is stripped so the node id is the bare ``path::name`` token.
_NODE_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def suite_failing_nodes(root: Path) -> tuple[bool, frozenset[str]]:
    """One full-suite run, reduced to ``(suite_available, failing_node_ids)``.

    Runs the project's full test suite ONCE (the same runner the baseline
    pre-flight and the per-move gate use) and returns the DETERMINISTIC set of
    every failing/erroring pytest node id parsed from the short-summary lines
    (``FAILED <node>`` / ``ERROR <node>``). ``suite_available`` is False when no
    test command is detectable.

    This is the granularity the session's end-of-session rollback backstop diffs:
    a node that FAILED at baseline but is absent here recovered; a node ABSENT at
    baseline that FAILS here is a REGRESSION the session introduced. Parsed from
    the captured output, sorted into a ``frozenset`` — no clock, no randomness, so
    the same suite output always yields the same set. Stdlib-only; the runner is
    imported lazily exactly as the rest of this tail does."""
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    nodes: set[str] = set()
    for res in summary.results or []:
        text = (res.get("stdout") or "") + (res.get("stderr") or "")
        nodes.update(_NODE_LINE.findall(text))
    return bool(summary.commands), frozenset(nodes)

# HONEST no-suite tier. When no test command can be detected, a change is applied
# WITHOUT running anything and WITHOUT any rollback safety net — the auto-rollback
# guarantee silently lapses. This sentinel makes that absence a distinct, loud,
# unmistakable state (mirroring how ``baseline-red`` was added as the weakest
# verification tier) so a suite-less apply can never be blended with one a green
# suite genuinely vouched for. A deterministic fact: it is emitted purely from
# ``summary.commands`` being empty — no clock, no randomness.
NO_SUITE = "no-suite"


def mark_no_suite(out: dict) -> None:
    """Stamp the explicit "no test suite was detected to run" disclosure onto
    ``out`` (additive — touched ONLY on the suite-less path, so a project WITH a
    detectable suite produces a byte-identical result).

    A change kept on a suite-less project was NOT verified and could NOT have been
    protected by auto-rollback. ``out["verified"]`` already reads False there, but
    a plain ``verified: False`` is ambiguous — it looks identical to a fix that
    ran against a green suite the tests just never referenced. These fields say,
    loudly and unmistakably, that no run happened at all:

      * ``suite_available`` -> ``False`` (a deterministic fact: no command found);
      * ``verification_strength.level`` -> ``"no-suite"`` (the proof artifact and
        report read this and label the change unverified-for-lack-of-suite).
    """
    out["suite_available"] = False
    strength = dict(out.get("verification_strength") or {})
    strength["level"] = NO_SUITE
    strength["suite_available"] = False
    out["verification_strength"] = strength


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


def stamp_coverage_strength(
    root: Path,
    out: dict,
    changed_files: list[str],
    old_by_path: dict[str, str | None],
    new_by_path: dict[str, str],
) -> str:
    """Grade how strongly the just-passed suite actually VOUCHES for these changes
    and stamp the verdict onto ``out`` — the SAME coverage machinery the hardened
    maintain path uses (``assess_strength``), brought to the develop apply tail.

    A green full suite proves nothing about a module no test references: this
    records ``out["coverage"]`` / ``out["verification_strength"].level`` as
    ``function`` (a test names the changed function), ``module`` (a test imports
    the module), ``none`` (no test looks at it — applied blind) or ``test-change``
    (only test files changed). Returns the level. Purely static — no execution,
    no clock, no randomness — so it stays deterministic. Additive: a caller that
    passes no changed-file inputs never reaches this and is byte-identical."""
    from app.engine.verification_strength import assess_strength

    strength = assess_strength(root, changed_files, old_by_path, new_by_path)
    level = strength.get("level", "none")
    existing = dict(out.get("verification_strength") or {})
    existing.update(strength)
    out["verification_strength"] = existing
    out["coverage"] = level
    return level


def run_full_suite_verification(
    root: Path,
    out: dict,
    *,
    strength_inputs: tuple[list[str], dict[str, str | None], dict[str, str]]
    | None = None,
) -> bool:
    """Run the project's full test suite and stamp the verdict onto ``out``.

    Records ``out["verified"]`` (a bool) and ``out["test_evidence"]`` (the
    summarised run). Returns ``True`` when the change stands — either the tests
    passed or there were no test commands to run — having already set
    ``out["rolled_back"] = False``; the caller returns ``out`` unchanged. Returns
    ``False`` when the tests failed, leaving ``out`` for the caller to finish its
    own rollback. This is the byte-identical verification tail both
    :func:`~app.execution.cross_file_rename.apply_rename` and
    :func:`~app.execution.move_module.apply_move` carried verbatim, with the
    runner imported lazily exactly as the inlined copies did.

    When ``strength_inputs`` is given (``(changed_files, old_by_path,
    new_by_path)``) and the suite ran green, the change's COVERAGE strength is
    graded with the maintain path's ``assess_strength`` and ``out["coverage"]`` is
    stamped, so a green-but-unreferencing suite is never blended with one the
    tests genuinely vouched for. ``strength_inputs=None`` (the default, and the
    move_module caller) skips this and is byte-identical to the prior tail."""
    from app.engine.proof_of_fix import summarize_test_run
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    out["verified"] = bool(summary.ok)
    out["test_evidence"] = summarize_test_run(summary)
    if summary.ok and summary.commands and strength_inputs is not None:
        stamp_coverage_strength(root, out, *strength_inputs)
    if not summary.commands:
        # No test command was detected, so NOTHING ran: the change is kept, but it
        # is NOT verified and auto-rollback could not have protected it. Make that
        # absence explicit and loud rather than an ambiguous ``verified: False``.
        mark_no_suite(out)
        out["rolled_back"] = False
        return True
    if summary.ok:
        out["rolled_back"] = False
        return True
    return False
