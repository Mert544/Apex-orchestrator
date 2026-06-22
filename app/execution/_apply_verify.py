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
    "VERIFICATION_UNAVAILABLE",
    "function_of",
    "mark_no_suite",
    "mark_verification_unavailable",
    "regressed_functions",
    "run_full_suite_verification",
    "stamp_coverage_strength",
    "suite_baseline_green",
    "suite_failing_nodes",
    "verification_unavailable_interpreter",
]

# pytest's short-summary failure lines name every failing node id, e.g.
# ``FAILED tests/test_x.py::test_y - AssertionError``. We want the WHOLE set (the
# proof summariser caps its copy at 5 for human display; the rollback backstop
# needs every one to diff baseline-green vs. after), so this parses them directly.
# Matches both ``FAILED <node>`` and ``ERROR <node>``; the trailing ``- reason``
# (if any) is stripped so the node id is the bare ``path::name`` token.
_NODE_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def _pytest_failing_cmd(root: Path) -> list[list[str]]:
    """The runner's own pytest command(s), with collection errors made NON-FATAL.

    A single test/conftest with an import or syntax error makes pytest print
    ``Interrupted: N error(s) during collection`` and run NOTHING — the whole
    suite is masked behind one ``ERROR <file>`` line, so a regression to a REAL
    test never appears in the failing-node set and is silently kept (the
    collection-interrupt BYPASS). Threading pytest's ``--continue-on-collection-errors``
    makes the un-collectable file report as an ERROR node (same in both runs) while
    the REST of the suite actually runs, so the failing-node set is COMPLETE and
    comparable and a real regression becomes visible.

    Built from the runner's OWN detected command (so the target's interpreter /
    venv is preserved). The flag is appended ONLY to pytest invocations and ONLY
    once; a non-pytest command (``npm test``) is returned unchanged. When there is
    NO collection error the flag is a no-op, so a clean suite's run is
    behaviourally identical. Returns an empty list when no suite is detectable."""
    from app.skills.execution.run_tests import RunTestsSkill

    detected = RunTestsSkill()._detect_commands(root)
    out: list[list[str]] = []
    for cmd in detected:
        if "pytest" in cmd and "--continue-on-collection-errors" not in cmd:
            cmd = [*cmd, "--continue-on-collection-errors"]
        out.append(cmd)
    return out


def function_of(node_id: str) -> str:
    """The TEST-FUNCTION identity of a pytest node id — its ``[...]`` suffix stripped.

    ``tests/t.py::test_lookup[a-1]`` and ``tests/t.py::test_lookup[x-1]`` are the
    SAME function ``tests/t.py::test_lookup`` parametrized over different data. The
    rollback backstop diffs at THIS granularity so a transform that legitimately
    changes the literal data feeding a ``@parametrize`` (shifting the case ids of a
    still-RED function) is not mistaken for a brand-new failure. A node with no
    ``[`` (the common case) returns unchanged. Pure/deterministic — no clock."""
    head = node_id.split("[", 1)[0]
    return head


def _file_of(node_id: str) -> str:
    """The test FILE a node id belongs to — everything before the first ``::``.

    A collection-error node is bare (``tests/t.py``, no ``::``) and returns itself;
    a per-test node (``tests/t.py::test_x``) returns ``tests/t.py``. Lets the
    regression diff recognise that a function newly failing AFTER lives in a file
    that had a COLLECTION ERROR at baseline (so it was masked, never proven green)."""
    return node_id.split("::", 1)[0]


def _collection_error_files(failing: frozenset[str]) -> frozenset[str]:
    """The FILE-level collection-error nodes in a failing set (bare paths, no ``::``).

    With ``--continue-on-collection-errors`` an un-collectable module reports as a
    bare ``ERROR <file>`` node while its per-test functions never run. Knowing those
    files lets the diff treat a function newly failing AFTER (because the session
    CLEARED the collection error and unmasked pre-existing failures) as NOT a
    regression — it was masked, not green, at baseline."""
    return frozenset(n for n in failing if "::" not in n)


def suite_failing_nodes(
    root: Path,
) -> tuple[bool, frozenset[str]]:
    """One full-suite run, reduced to ``(suite_available, failing_node_ids)``.

    Runs the project's full test suite ONCE (the same runner the baseline
    pre-flight and the per-move gate use) and returns the DETERMINISTIC set of
    every failing/erroring pytest node id parsed from the short-summary lines
    (``FAILED <node>`` / ``ERROR <node>``). ``suite_available`` is False when no
    test command is detectable.

    Collection errors are made NON-FATAL (pytest ``--continue-on-collection-errors``)
    so a single un-collectable module cannot mask the whole suite: it reports as an
    ERROR node in BOTH baseline and after (unchanged, so never a false regression)
    while every other test actually runs, making a real regression visible. When
    there is NO collection error the flag is a no-op and the run is identical.

    This is the granularity the session's end-of-session rollback backstop diffs:
    a node that FAILED at baseline but is absent here recovered; a node ABSENT at
    baseline that FAILS here is a REGRESSION the session introduced. Parsed from
    the captured output, sorted into a ``frozenset`` — no clock, no randomness, so
    the same suite output always yields the same set. Stdlib-only; the runner is
    imported lazily exactly as the rest of this tail does."""
    from app.skills.execution.run_tests import RunTestsSkill

    commands = _pytest_failing_cmd(root)
    if not commands:
        return False, frozenset()
    summary = RunTestsSkill().run(str(root), commands=commands)
    nodes: set[str] = set()
    for res in summary.results or []:
        text = (res.get("stdout") or "") + (res.get("stderr") or "")
        nodes.update(_NODE_LINE.findall(text))
    return bool(summary.commands), frozenset(nodes)


def regressed_functions(
    baseline_failing: frozenset[str], after_failing: frozenset[str]
) -> frozenset[str]:
    """The node ids that are a TRUE regression: a baseline-GREEN test function now RED.

    Diffs at TEST-FUNCTION granularity (``function_of``), not raw node id, so two
    failure modes that look like regressions but are NOT get filtered out:

      * **parametrize id-shift** — a still-RED ``@parametrize`` function whose case
        ids shifted (``test_lookup[a-1]`` -> ``test_lookup[x-1]``) because a
        transform legitimately changed the data feeding it. The FUNCTION was red at
        baseline, so a shifted/added case under it is NOT a new regression.
      * **unmask** — a function that was MASKED at baseline (uncollected behind a
        collection error the session legitimately cleared) cannot be charged: it was
        never proven GREEN at baseline. ``--continue-on-collection-errors`` already
        keeps such functions collected in both runs, but this guard is kept for
        safety — a function is only charged if NO node of it failed at baseline.

    So an after-node is a regression ONLY when its function had NO failing node at
    baseline AND its file did not have a COLLECTION ERROR at baseline (a masked file
    was never proven green). Returns the offending AFTER node ids, sorted-stable via
    ``frozenset`` — deterministic, no clock/random."""
    baseline_funcs = {function_of(n) for n in baseline_failing}
    baseline_collerr = _collection_error_files(baseline_failing)
    return frozenset(
        n for n in after_failing
        if function_of(n) not in baseline_funcs
        and _file_of(n) not in baseline_collerr
    )

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


# HONEST verification-UNAVAILABLE tier — a SIBLING of ``NO_SUITE``, never folded
# into it. ``NO_SUITE`` means "this project has no tests"; this means "this
# project HAS tests, but the interpreter Apex invoked cannot import pytest, so
# NOTHING could be run". Conflating the two would itself be dishonest: a
# pytest-missing run is not a suite-less project, and (the original bug) it is not
# a RED suite either. The tier is emitted purely from ``summary.pytest_missing``
# — a deterministic fact about the interpreter on disk, no clock/random.
VERIFICATION_UNAVAILABLE = "verification-unavailable"


def mark_verification_unavailable(out: dict, interpreter: str) -> None:
    """Stamp the explicit "pytest is not importable, so nothing could run"
    disclosure onto ``out`` (additive — touched ONLY on the pytest-missing path,
    so a project WITH pytest produces a byte-identical result).

    Mirrors :func:`mark_no_suite` but with a DISTINCT level so the report and proof
    artifact can tell "no tests exist" from "tests exist but pytest is missing"
    from "tests failed". Records:

      * ``suite_available`` -> ``False`` (nothing could run);
      * ``verification_unavailable`` -> ``True`` and ``pytest_interpreter`` -> the
        offending interpreter path, so the loud message can name it;
      * ``verification_strength.level`` -> ``"verification-unavailable"``.
    """
    out["suite_available"] = False
    out["verification_unavailable"] = True
    out["pytest_interpreter"] = interpreter
    strength = dict(out.get("verification_strength") or {})
    strength["level"] = VERIFICATION_UNAVAILABLE
    strength["suite_available"] = False
    out["verification_strength"] = strength


def verification_unavailable_interpreter(root: Path) -> str | None:
    """The interpreter path under which verification is UNAVAILABLE, or ``None``.

    The shared entry-guard the orchestration layers (the develop session, the
    maintenance/ideate bridge) consult BEFORE doing any move work: if the
    interpreter the runner would invoke for ``root`` cannot import pytest, they
    must decline up front — never read the baseline as RED, never roll a move
    back as "failed", never claim "verified" (proof-carrying: can't verify => don't
    touch). Returns that interpreter path so the decline message can name it.

    Returns ``None`` (the common, byte-identical path) when there is no detectable
    pytest suite (a non-pytest / suite-less project is NOT a verification-
    unavailable one — it has the honest ``NO_SUITE`` story) or when pytest IS
    importable. Deterministic and offline — reuses ``RunTestsSkill`` exactly as the
    rest of this tail imports it lazily, so it never forms an import cycle."""
    from app.skills.execution.run_tests import (
        RunTestsSkill,
        pytest_importable,
    )

    skill = RunTestsSkill()
    for cmd in skill._detect_commands(root):
        if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "pytest":
            interp = cmd[0]
            if not pytest_importable(interp):
                return interp
            return None
    return None


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
    if getattr(summary, "pytest_missing", False):
        # VERIFICATION UNAVAILABLE — pytest is not importable under the interpreter
        # Apex invoked, so the run proved NOTHING. This is NOT a RED suite (the
        # original bug returned False here and the caller rolled the change back as
        # "failed") and NOT a no-suite project. Stamp the DISTINCT tier, leave the
        # change applied WITHOUT a rollback, and return True so the caller keeps it
        # un-touched — proof-carrying: we never claim "verified", and we never roll
        # back a move we simply could not verify.
        out["verified"] = False
        out["test_evidence"] = summarize_test_run(summary)
        mark_verification_unavailable(
            out, getattr(summary, "pytest_interpreter", ""))
        out["rolled_back"] = False
        return True
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
