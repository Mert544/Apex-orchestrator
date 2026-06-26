"""The FORCED jest gate shared by Apex's two JS body-landing objectives.

Both ``js-tdd-implement`` (:mod:`app.execution.js.js_stub_synthesis`) and
``js-implement-from-jsdoc`` (:mod:`app.execution.js.js_jsdoc_synthesis`) accept a
synthesised body iff a THROWAWAY copy's jest suite goes green. The gate they use
MUST be jest — never whatever :meth:`RunTestsSkill._detect_commands` auto-selects.
That auto-detection is pytest-FIRST (a ``tests/`` dir / ``pyproject.toml`` / a flat
pytest suite wins), so on a "mixed" repo — a JS package inside a Python monorepo,
or a JS repo with one stray Python tool test reachable under ``tests/`` — the
"jest gate" would actually run PYTEST. Pytest passes on the unrelated GREEN Python
test (rc=0), the gate reads green, and the FIRST template body is accepted WITHOUT
jest ever pinning it: a provably-wrong body lands and is stamped verified — a
direct breach of the never-fake-green moat. Changing the global default ordering is
out of the question (the Python develop loop and ``_apply_verify`` depend on it), so
this module forces the jest command explicitly at the JS call sites instead.

Two soundness requirements, both enforced here:

1. **FORCE jest** — run the project's own ``npm test`` (the sanctioned jest
   invocation ``RunTestsSkill`` already uses for a JS project, and exactly what the
   synthesis docstrings name) via an explicit ``commands=`` so detection is bypassed
   and pytest can never substitute.
2. **POSITIVE-EXECUTION proof** — require evidence that jest actually RAN >=1 test.
   Jest prints a ``Tests:       N passed, M total`` summary line; a
   ``--passWithNoTests`` / "no tests found" run prints NO such line (just exits 0
   with "No tests found"). A green *exit code alone* is therefore not enough — an
   empty/vacuous run would fake-green just like the pytest substitution did. The gate
   reads green ONLY when the suite ran clean AND the summary reports a non-zero
   ``passed`` count, so a vacuous gate REFUSES.

Deterministic (fixed command, fixed regex — same project, same verdict), offline
(the project owns its ``node_modules``; Apex installs nothing), zero-token.
"""

from __future__ import annotations

import re

from app.skills.execution.run_tests import RunTestsSkill, TestRunSummary

__all__ = ["JEST_COMMAND", "jest_ran_and_passed", "run_jest_gate"]

# The forced jest invocation. ``npm test`` is the project's OWN sanctioned jest
# entry point (the demos define ``"scripts": {"test": "jest"}``) and is exactly the
# command ``RunTestsSkill._detect_commands`` already returns for a JS project — so
# this only PINS that choice rather than relying on pytest-first auto-detection to
# (mis)make it. ``--runInBand`` is forwarded past ``npm``'s ``--`` so jest runs
# serially (deterministic, no worker races). ``npm``/``node`` are already on the
# CommandRunner allow-list; ``npx`` is NOT, so ``npm test`` is also the policy-clean
# choice without widening the security allow-list.
JEST_COMMAND: list[str] = ["npm", "test", "--", "--runInBand"]

# Jest's end-of-run per-TEST summary line, e.g. ``Tests:  1 skipped, 2 passed, 3
# total``. The capture is the ``<n> passed`` count; the line is ABSENT on a
# "No tests found" / ``--passWithNoTests`` run, so requiring it (with a non-zero
# count) is what makes a vacuous run read as NOT green. Matched anywhere in the
# combined stdout+stderr (jest writes the summary to stderr) across npm wrapping.
_TESTS_PASSED_RE = re.compile(r"^Tests:.*?(\d+)\s+passed", re.MULTILINE)


def jest_ran_and_passed(summary: TestRunSummary) -> bool:
    """Whether the run is a jest suite that EXECUTED >=1 test and passed it.

    The positive-execution proof that closes both fake-green holes: it is ``True``
    ONLY when (a) a command actually ran, (b) the suite exited green
    (``summary.ok``), AND (c) jest's ``Tests:`` summary across the run output
    reports a non-zero ``passed`` count. A ``--passWithNoTests`` / "no tests found"
    run prints no such summary line, so it reads as NOT green and the gate refuses —
    an empty/vacuous gate can never fake green. Pure function of the captured run
    output; no clock/random."""
    if not summary.commands or not summary.ok:
        return False
    return _passed_count(summary) > 0


def _passed_count(summary: TestRunSummary) -> int:
    """The largest ``<n> passed`` jest reports across the run's captured output (0
    when no ``Tests:`` summary line is present — the vacuous-run signature).

    Scans both stdout and stderr of every command result (jest writes the summary
    to stderr; npm may echo either), taking the max so a multi-result run is read by
    its richest summary. Deterministic — a pure parse of the captured text."""
    best = 0
    for result in summary.results:
        blob = (result.get("stdout") or "") + "\n" + (result.get("stderr") or "")
        for match in _TESTS_PASSED_RE.finditer(blob):
            best = max(best, int(match.group(1)))
    return best


def run_jest_gate(copy_root, runner: RunTestsSkill) -> bool:
    """Run the FORCED jest suite on ``copy_root`` and return whether it ran clean.

    Bypasses :meth:`RunTestsSkill._detect_commands` by passing :data:`JEST_COMMAND`
    explicitly, so a pytest suite reachable in a mixed repo can never substitute for
    jest, then applies the :func:`jest_ran_and_passed` positive-execution proof.
    The single seam both JS ``_gate_green`` helpers funnel their suite run through."""
    summary = runner.run(str(copy_root), commands=[JEST_COMMAND])
    return jest_ran_and_passed(summary)
