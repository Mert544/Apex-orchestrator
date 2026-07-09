"""Develop session — run the concrete develop objectives on a repo in one motion.

The combined BUYER artifact the North Star names: *"run the develop loop on an
INDEPENDENT project and show the TANGIBLE artifacts it produced (real diffs:
code, tests, scaffolding)."* A student or team points this at their repo and, in
ONE command, Apex lands stub bodies + wires ``__init__`` exports + infers type
hints + dataclassifies boilerplate + modernizes idioms — each through its
EXISTING deterministic fitness→moves loop, suite-gated (or, for ``wire-exports``,
its import oracle) with byte-for-byte auto-rollback — and emits ONE combined,
deterministic report: per-objective move counts, total files / lines changed,
each move's verification tier, and the unified diff (the tangible artifact).

Why a separate command. Apex's two highest-value concrete objectives —
``implement-stub`` and ``wire-exports`` — are flagged ``expensive`` and are
excluded from ``apex develop --all`` / ``ascend`` so the fast autonomous board
stays fast. So there was no single motion that lands the WHOLE concrete-value
chain on a foreign repo and shows the combined verified diff. This session OPTS
THEM IN explicitly, in a fixed concrete-value-first order
(``SESSION_OBJECTIVES``).

Design.
  * REUSE, never reimplement: each objective runs through
    :func:`app.engine.objective_compiler.compile_objective` — the same greedy
    propose→apply→measure→select loop, the same ``apply_rename`` /
    ``param_drop`` / ``inline`` engines, the same per-move suite/oracle gate with
    rollback. The session only ORCHESTRATES that loop across a fixed objective
    list and ACCUMULATES the landed steps.
  * Honest labelling: a move that landed against a project with NO detectable
    test suite is recorded with tier ``no-suite`` (the ``mark_no_suite`` signal
    surfaced through ``CompileStep.verified``), never blended with a green one. A
    move that fails verification is rolled back by the underlying engine and
    surfaced as a refusal (``blocked``) — never counted as landed.
  * Determinism: the objective order is fixed; each objective's loop is itself
    deterministic; the report is a PURE function of the landed plans and the
    captured before/after sources (a stdlib ``unified_diff``). NO wall-clock or
    random in the artifact body — same repo state in → byte-identical report out.
  * Backstop: after the whole session, the FULL test suite is run once; the
    report states whether the repo is green after (never-fake-green — the session
    discloses if the combined result left the suite red, even though every
    individual move was gated).

Additive and opt-in: the normal ``apex develop`` / ``--all`` / ``ascend`` paths
are untouched and byte-identical; the session is a brand-new surface. Zero-token,
offline, stdlib-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import difflib
from pathlib import Path
from typing import Any

from app.engine.objective_compiler import (
    SESSION_OBJECTIVES,
    CompileResult,
    _record_backstop_ledger_correction,
    compile_objective,
)
from app.engine.tree_snapshot import (
    SKIP_DIRS as _SKIP_DIRS,  # noqa: F401  (re-export under the historical name)
    restore_py_tree,
    snapshot_py_tree,
)
from app.engine.value_landed import value_landed_from_session

__all__ = [
    "SessionMove", "SessionObjective", "SessionReport",
    "run_develop_session", "render_session_markdown",
    "build_session_proof",
]

# Verification tiers a landed move can carry. A move only reaches the report if
# it LANDED (the engine kept it); a move that failed its gate was rolled back and
# is surfaced as a refusal, not a tier.
TIER_VERIFIED = "verified"   # suite ran green AND a test exercises the change
TIER_WEAK = "weak"           # suite ran green but NO test references the change
TIER_NO_SUITE = "no-suite"   # the move landed but NO suite could verify it
# The DISTINCT report-only tier: a dry-run (``apply=False``) move was PROJECTED,
# not applied — no write happened and no suite ran, so neither "verified" nor
# "no-suite" ("applied but no suite could verify it") is an honest label. Keyed
# off the CompileResult's ``applied`` flag in ``_collect_objective``; an applied
# session never carries it, so applied-mode reports are byte-identical.
TIER_PREVIEW = "preview"     # dry run: not applied yet; test-verified on --apply
# The DISTINCT vacuous-delta tier: a move whose ENTIRE delta-green scope was
# already red/ERROR at baseline. The delta comparison could vouch for nothing —
# nothing passed at baseline, so nothing could regress, and no test actually
# exercised the changed code green — even though the move's raw ``verified``
# ("broke nothing new") reads True. Keyed off ``CompileStep.delta_vacuous`` in
# ``_tier_for``; a move whose scope had ANY baseline-green node never carries
# it (byte-identical for every partial-red/green-baseline campaign).
TIER_BASELINE_RED = "baseline-red"


def _verification_unavailable_message(interpreter: str) -> str:
    """The LOUD, actionable decline message — names the offending interpreter.

    Backward-compatible re-export: the canonical wording now lives in the leaf
    ``app.execution._apply_verify`` (:func:`~app.execution._apply_verify.
    verification_unavailable_message`) so the objective compiler can import it
    WITHOUT forming an import cycle through this module. This thin delegator keeps
    the public name every existing caller (the ideate/maintain bridge, this session's
    renderers, the tests) already imports — the text is byte-identical."""
    from app.execution._apply_verify import verification_unavailable_message

    return verification_unavailable_message(interpreter)

# The directories never worth snapshotting (caches, vcs, venvs, the .apex
# memory store) now live in :data:`app.engine.tree_snapshot.SKIP_DIRS` — the
# snapshot/restore pair moved to that LEAF so the objective compiler's
# end-of-campaign backstop reuses the identical semantics without an import
# cycle through this module. Re-exported above as ``_SKIP_DIRS``.


@dataclass
class SessionMove:
    """One landed move, with the verification tier it earned."""
    objective: str
    operator: str
    target: str
    description: str
    tier: str
    # Native-only idiom shapes THIS move's landing recorded into the
    # native-experience memory — the session-level mirror of ``CompileStep.
    # native_shapes`` (see that field's docstring), threaded through by
    # :func:`_collect_objective`. Purely INTERNAL bookkeeping — a session
    # backstop rollback reads it to name exactly which native experience it
    # could NOT un-record (``native_proof_memory`` is append-only; see
    # ``_restore_and_zero``) — so it is deliberately kept OUT of ``to_dict()``:
    # no external consumer needs it, and every existing JSON artifact stays
    # byte-identical. Default empty tuple keeps every existing
    # ``SessionMove(...)`` construction valid.
    native_shapes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"objective": self.objective, "operator": self.operator,
                "target": self.target, "description": self.description,
                "tier": self.tier}


@dataclass
class SessionObjective:
    """One objective's contribution to the session: its landed moves + refusals."""
    objective: str
    moves: list[SessionMove] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def landed(self) -> int:
        return len(self.moves)

    def to_dict(self) -> dict[str, Any]:
        return {"objective": self.objective, "landed": self.landed,
                "moves": [m.to_dict() for m in self.moves],
                "blocked": self.blocked}


@dataclass
class SessionReport:
    """The combined, deterministic session artifact.

    A pure function of the landed plans and the captured before/after sources —
    no clock or random anywhere in the body, so the same repo state yields a
    byte-identical report."""
    applied: bool
    objectives: list[SessionObjective] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    diff: str = ""
    suite_available: bool = True
    suite_green_after: bool = True
    # Did the full-suite BACKSTOP actually run? Under ``--no-verify`` the
    # per-move gate is skipped AND the backstop is not run, so the default
    # ``suite_green_after=True`` must NOT be read as "the suite is green" — nothing
    # ran. This flag gates that verdict: a "full suite GREEN" claim is only made
    # when the backstop genuinely ran (never-fake-green).
    backstop_ran: bool = False
    # Was the project's suite ALREADY green BEFORE any change? ``None`` means the
    # baseline was never probed (the session landed work, so the cause of an empty
    # contribution list is moot — we only probe when we'd otherwise have to explain
    # WHY nothing landed). ``False`` = the baseline suite is RED, so an empty
    # contribution list does NOT mean the project is clean: the renderer must say
    # the suite is RED, never "already satisfied" (never-fake-green). ``True`` = the
    # baseline genuinely passed, so "already satisfied" is honest.
    baseline_suite_green: bool | None = None
    # Did the END-OF-SESSION baseline-diff backstop detect a regression and ROLL
    # the whole session BACK? On a RED baseline the per-move gate is impact-scoped
    # (for speed), so a behaviour-CHANGING transform can break a previously-GREEN
    # test reachable only TRANSITIVELY — outside the impacted scope. The session
    # captures the baseline's failing-node set, reruns the suite once after applying,
    # and if ANY baseline-green node regressed, restores every modified file (and
    # deletes created ones) to its pre-session bytes. ``True`` here means that
    # happened: the contributions were UN-landed and the tree is back at baseline.
    # ``False`` (the default) means no baseline-green node regressed — the changes
    # stand. Only ever ``True`` on a RED baseline that actually applied changes; the
    # GREEN-baseline path gates full-suite per move and never reaches this.
    regression_rolled_back: bool = False
    # Did the end-of-session backstop's suite RE-RUN itself collapse (usage
    # error, nothing collected, timeout — pytest never reached its per-test
    # summary)? Such a run's empty node set is NOT "no regressions"; it measured
    # nothing. The session is rolled back (fail closed) and this flag discloses
    # WHY: the backstop could not vouch for the tree, so the tree was restored.
    # ``False`` (default) = the re-run was comparable and the verdict above is
    # the real diff.
    backstop_run_invalid: bool = False
    # The sorted node ids that were GREEN at baseline but RED after the session —
    # the evidence behind a ``regression_rolled_back``. Empty unless a regression
    # was detected (and rolled back), so a clean session's artifact is unchanged.
    regressed_nodes: list[str] = field(default_factory=list)
    # Did a GREEN baseline go RED *during* the session — self-inflicted by a late
    # objective — triggering the session-level restore? On a GREEN baseline every
    # per-move gate runs the FULL suite, so a single objective's own gate cannot
    # miss a break it caused; but in a MULTI-objective session a late objective can
    # break code an EARLIER objective already landed (an interaction the per-move
    # gate, run against the tree as it stood for that objective, never re-checks).
    # When the end-of-session full-suite backstop sees RED after a GREEN baseline,
    # that is by definition a self-inflicted regression: the whole session is
    # restored to its pre-session bytes (every objective's edits reverted) and
    # ``regression_rolled_back`` is set too. This flag is DISTINCT from
    # ``baseline_suite_green is False`` (a genuinely RED *baseline*): when ``True``
    # the renderer must say the RED was self-inflicted-then-reverted, NEVER "RED
    # before any change (pre-existing failures)". ``regressed_nodes`` stays empty
    # here — a green baseline diffs no failing-node set, the green→red transition
    # IS the proof. Defaults falsy, so a clean session's artifact is unchanged.
    self_inflicted_red: bool = False
    # VERIFICATION-UNAVAILABLE short-circuit. ``True`` when the interpreter Apex
    # would invoke for this project HAS a pytest suite to run but cannot import
    # pytest — so NOTHING could be verified. This is DISTINCT from a RED baseline
    # (the old, misleading reading) and from a suite-less project: the session
    # declines up front, lands nothing, and rolls nothing back as "failed". The
    # interpreter path names which Python needs ``pip install pytest`` (or to be
    # pointed at the project's ``.venv``). Both default falsy so a project WITH
    # pytest produces a byte-identical report.
    pytest_missing: bool = False
    pytest_interpreter: str = ""
    # MANIFESTO-ENFORCED (opt-in, ``manifesto_aware``): every law that fired
    # across this session's objectives, deduplicated in first-fired order
    # (mirrors ``CompileResult.manifesto_laws`` — see ``compile_objective``'s
    # docstring). Empty for every session that did not arm ``manifesto_aware``
    # (the default), so ``to_dict()``/render stay byte-identical.
    manifesto_laws: list[str] = field(default_factory=list)

    @property
    def total_moves(self) -> int:
        return sum(o.landed for o in self.objectives)

    @property
    def verified_moves(self) -> int:
        return sum(1 for o in self.objectives for m in o.moves
                   if m.tier == TIER_VERIFIED)

    @property
    def weak_moves(self) -> int:
        return sum(1 for o in self.objectives for m in o.moves
                   if m.tier == TIER_WEAK)

    @property
    def no_suite_moves(self) -> int:
        return sum(1 for o in self.objectives for m in o.moves
                   if m.tier == TIER_NO_SUITE)

    @property
    def preview_moves(self) -> int:
        """Dry-run (report-only) moves — projected, NOT applied, so they never
        count toward any applied tier (the ``no-suite`` mislabel this replaces)."""
        return sum(1 for o in self.objectives for m in o.moves
                   if m.tier == TIER_PREVIEW)

    @property
    def baseline_red_moves(self) -> int:
        """Landed moves whose ENTIRE delta-green scope was already red/ERROR at
        baseline — the delta comparison vouched for nothing (nothing passed, so
        nothing could regress). Distinct from ``no_suite_moves`` (no suite ran
        at all) and from ``weak_moves`` (a suite ran and covered SOMETHING, just
        not the changed function): here a suite ran but could see nothing green
        to compare against."""
        return sum(1 for o in self.objectives for m in o.moves
                   if m.tier == TIER_BASELINE_RED)

    @property
    def objectives_with_work(self) -> list[SessionObjective]:
        return [o for o in self.objectives if o.moves]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "applied": self.applied,
            "total_moves": self.total_moves,
            "verified_moves": self.verified_moves,
            "weak_moves": self.weak_moves,
            "no_suite_moves": self.no_suite_moves,
            "files_changed": self.files_changed,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "suite_available": self.suite_available,
            "suite_green_after": self.suite_green_after,
            "backstop_ran": self.backstop_ran,
            "baseline_suite_green": self.baseline_suite_green,
            "regression_rolled_back": self.regression_rolled_back,
            "regressed_nodes": self.regressed_nodes,
            "self_inflicted_red": self.self_inflicted_red,
            "pytest_missing": self.pytest_missing,
            "pytest_interpreter": self.pytest_interpreter,
            "objectives": [o.to_dict() for o in self.objectives],
            "diff": self.diff,
        }
        if self.preview_moves:
            # ADDITIVE: present only on a report-only run that projected moves
            # (an applied session never carries the preview tier), so every
            # applied report's dict is byte-identical to before.
            data["preview_moves"] = self.preview_moves
        if self.baseline_red_moves:
            # ADDITIVE, mirroring ``preview_moves``: present only when a move's
            # delta scope was entirely red at baseline, so every genuinely
            # test-vouched (or partial-red) session's dict is byte-identical.
            data["baseline_red_moves"] = self.baseline_red_moves
        if self.manifesto_laws:
            # ADDITIVE: appears only when the manifesto-aware gate actually
            # fired a law across this session's objectives (mirrors
            # ``CompileResult.to_dict()``'s ``manifesto_laws`` key), so a
            # session that never armed ``manifesto_aware`` is byte-identical.
            data["manifesto_laws"] = list(self.manifesto_laws)
        if self.pytest_missing:
            # Surface the LOUD message in --json too, so a machine consumer gets
            # the same actionable diagnostic the markdown shows (never a silent,
            # mislabelled "0 executable" — name the interpreter, say nothing was
            # rolled back). Additive: present ONLY in the pytest-missing case.
            data["verification_unavailable"] = _verification_unavailable_message(
                self.pytest_interpreter)
        return data


def _snapshot(root: Path) -> dict[str, str]:
    """Map of ``rel_posix_path -> source`` for every ``.py`` file under ``root``.

    Thin delegator over the shared LEAF :func:`app.engine.tree_snapshot.
    snapshot_py_tree` (extracted verbatim from here so the objective compiler's
    end-of-campaign backstop captures with IDENTICAL semantics). Kept as a
    module-level name so existing callers/tests keep their seam."""
    return snapshot_py_tree(root)


def _tier_for(step: Any) -> str:
    """The verification tier a landed CompileStep earned — COVERAGE-AWARE.

    A green suite proves nothing about a module no test references, so a bare
    ``verified=True`` (suite ran green) is NOT enough to earn ``verified``. The
    tier reads the step's coverage strength (the maintain-path ``assess_strength``
    levels the apply tail now stamps):

      * ``verified`` — suite ran green AND a test exercises the change
        (``coverage`` is ``function`` / ``module`` / ``test-change``);
      * ``weak`` — suite ran green but NO test references the change
        (``coverage == none``): honest, never blended with a genuine verified one;
      * ``no-suite`` — no detectable suite ran (``verified=False``; the
        ``mark_no_suite`` signal), applied with nothing to verify it.

      * ``baseline-red`` — the move's delta-green scope was ENTIRELY red/ERROR
        at baseline (``CompileStep.delta_vacuous``): the delta comparison could
        vouch for nothing, even though ``verified`` (broke nothing new) reads
        True — never blended with a genuine verified or weak tier.

    A move that FAILED its gate never reaches the steps list (it was rolled back),
    so these are the only tiers a reported move can hold."""
    if not getattr(step, "verified", False):
        return TIER_NO_SUITE
    if getattr(step, "delta_vacuous", False):
        return TIER_BASELINE_RED
    return TIER_VERIFIED if getattr(step, "coverage_verified", False) else TIER_WEAK


def _accumulate_manifesto_laws(report: SessionReport, result: CompileResult) -> None:
    """Fold one objective's fired laws onto the session's aggregate, deduplicated
    in first-fired order — the SAME dedup shape ``CompileResult.manifesto_laws``
    itself uses within a single campaign, now applied ACROSS objectives. A
    campaign that never armed ``manifesto_aware`` (or fired no law) hands an
    empty ``result.manifesto_laws``, so this is a no-op and the aggregate stays
    empty (byte-identical report). Extracted out of ``run_develop_session``'s
    loop body to keep that function's branching flat (a single delegated call,
    not an inline ``for``/``if``)."""
    for law in result.manifesto_laws:
        if law not in report.manifesto_laws:
            report.manifesto_laws.append(law)


def _collect_objective(result: CompileResult) -> SessionObjective:
    """Fold one objective's CompileResult into the session's per-objective view.

    The tier is keyed off the result's ``applied`` flag: an APPLIED step earns
    its coverage-aware tier (:func:`_tier_for`, byte-identical to before), but a
    DRY-RUN step was only PROJECTED — nothing was applied and no suite ran, so
    reading its raw ``verified=False`` as ``no-suite`` ("applied but no suite
    could verify it") would be doubly false. It carries the distinct
    :data:`TIER_PREVIEW` instead."""
    obj = SessionObjective(objective=result.objective)
    for step in result.steps:
        obj.moves.append(SessionMove(
            objective=result.objective, operator=step.operator,
            target=step.target, description=step.description,
            tier=_tier_for(step) if result.applied else TIER_PREVIEW,
            native_shapes=step.native_shapes))
    obj.blocked = list(result.blocked)
    return obj


def _diff_snapshots(before: dict[str, str],
                    after: dict[str, str]) -> tuple[list[str], int, int, str]:
    """The unified diff between two snapshots: ``(files, added, removed, text)``.

    Every changed/created/deleted ``.py`` file is diffed (sorted by path for
    determinism). ``added``/``removed`` count changed lines; the text is a single
    concatenated unified diff with NO timestamps in the headers (determinism)."""
    files: list[str] = []
    added = removed = 0
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel, "")
        new = after.get(rel, "")
        if old == new:
            continue
        files.append(rel)
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        # Empty fromfile/tofile dates => no clock in the header (determinism).
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="\n"))
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        chunk = "".join(diff)
        if chunk and not chunk.endswith("\n"):
            chunk += "\n"
        chunks.append(chunk)
    return files, added, removed, "".join(chunks)


def _verification_unavailable(root: Path) -> str | None:
    """The interpreter under which verification is unavailable, or ``None``.

    Thin wrapper over the shared entry-guard
    (:func:`app.execution._apply_verify.verification_unavailable_interpreter`) so
    the session declines BEFORE any move work when the project has a pytest suite
    Apex cannot run (pytest not importable under the interpreter it would invoke).
    Returns ``None`` (the common path) for a suite-less / non-pytest project or
    when pytest IS importable — both of which proceed exactly as before."""
    from app.execution._apply_verify import verification_unavailable_interpreter

    return verification_unavailable_interpreter(root)


def _baseline_suite_green(root: Path) -> bool:
    """Was the project's suite ALREADY green BEFORE the session touched it?

    Thin wrapper over the shared one-time baseline pre-flight
    (:func:`app.execution._apply_verify.suite_baseline_green`) so the session
    keys its "nothing landed" wording off the REAL reason: a clean project
    (genuinely satisfied) vs. a RED baseline (pre-existing failures Apex must not
    paper over). Runs the full suite ONCE — the session calls this at most once,
    and ONLY when it would otherwise have to explain why nothing landed, so the
    happy path that LANDS work pays no extra suite run. "No test command" counts
    as a GREEN baseline (the same convention the apply gate uses)."""
    from app.execution._apply_verify import suite_baseline_green

    return suite_baseline_green(root)


def _full_suite_green(root: Path) -> tuple[bool, bool]:
    """``(suite_available, green)`` from one full-suite run — the backstop.

    Reuses the same runner the per-move gate uses. ``suite_available`` is False
    when no test command is detectable (a suite-less repo is disclosed, never
    treated as a passing one); ``green`` is True when the suite passed OR there
    was nothing to run (a repo with no suite is not a *failing* suite, the same
    convention the apply gate uses)."""
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    suite_available = bool(summary.commands)
    green = bool(summary.ok) or not summary.commands
    return suite_available, green


def _failing_nodes(root: Path) -> frozenset[str]:
    """The DETERMINISTIC set of test node ids that FAIL on one full-suite run.

    Thin wrapper over :func:`app.execution._apply_verify.suite_failing_nodes`,
    used for BOTH the up-front baseline capture (on a red apply baseline) and the
    end-of-session re-run, so the backstop can diff "green at baseline" against
    "red after" and ROLL BACK a regression instead of merely disclosing it. Sorted
    node ids, no clock/random — same suite output in, same set out."""
    from app.execution._apply_verify import suite_failing_nodes

    _available, nodes = suite_failing_nodes(root)
    return nodes


def _failing_nodes_checked(root: Path) -> tuple[bool, frozenset[str]]:
    """``(run_valid, failing_node_ids)`` — the validity-aware re-run the
    END-OF-SESSION backstop must use.

    ``run_valid`` is False when the re-run COLLAPSED before its per-test summary
    (usage error, nothing collected, timeout, pytest never launched): its
    empty/truncated node set would diff against the red baseline as "no
    regressions" and the backstop would silently keep a possibly-broken tree —
    the exact hole the backstop exists to close. The caller fails CLOSED on
    ``False``. Delegates to the shared
    :func:`app.execution._apply_verify.suite_failing_nodes_checked` so the
    validity rule is written exactly once."""
    from app.execution._apply_verify import suite_failing_nodes_checked

    _available, valid, nodes = suite_failing_nodes_checked(root)
    return valid, nodes


def _restore_snapshot(root: Path, before: dict[str, str],
                      after: dict[str, str]) -> list[str]:
    """Roll the tree back to the pre-session ``before`` snapshot, byte-for-byte.

    Thin delegator over the shared LEAF :func:`app.engine.tree_snapshot.
    restore_py_tree` (extracted verbatim from here so the objective compiler's
    end-of-campaign backstop restores with IDENTICAL semantics): every file the
    session MODIFIED is rewritten to its exact pre-session bytes, and every file
    the session CREATED is deleted. Kept as a module-level name so existing
    callers/tests keep their seam. Returns the rels it FAILED to restore
    (additive — empty on a full success) so :func:`_restore_and_zero` can fail
    closed on the ledger correction instead of recording a false "rolled_back"
    proof for a tree that is not actually back at baseline."""
    return restore_py_tree(root, before, after)


def _regressed_nodes(baseline_failing: frozenset[str],
                     after_failing: frozenset[str]) -> frozenset[str]:
    """The node ids that were GREEN at baseline but are RED after the session.

    Delegates to the shared TEST-FUNCTION-granularity diff
    (:func:`app.execution._apply_verify.regressed_functions`): a node is charged as
    a regression ONLY when its test FUNCTION (``path::func``, the ``[...]``
    parametrize suffix stripped) had NO failing node at baseline. This is sound
    where a raw ``after - baseline`` set difference is NOT:

      * a node already failing at baseline (an unsynthesizable stub's pinned test)
        is NOT a regression — honest disclosure, never an over-rollback;
      * a ``@parametrize`` case whose id SHIFTED on a still-red function
        (``test_lookup[a-1]`` -> ``test_lookup[x-1]``, the literal data legitimately
        changed by a transform) is NOT a new failure — the function was red before;
      * a function MASKED at baseline (behind a collection error since cleared) is
        NOT charged — it was never proven green. ``--continue-on-collection-errors``
        keeps it collected in both runs, but the function-granularity guard makes
        the unmask case safe regardless. Deterministic — sorted sets, no clock."""
    from app.execution._apply_verify import regressed_functions

    return regressed_functions(baseline_failing, after_failing)


def _restore_and_zero(
    report: SessionReport, root: Path, before: dict[str, str],
    after: dict[str, str],
) -> None:
    """Roll the whole tree back to ``before`` and zero every landed move.

    The shared core of BOTH session-level rollbacks (the red-baseline failing-node
    backstop and the green-baseline self-inflicted-RED backstop): restore every
    modified file to its pre-session bytes (delete created ones) via
    ``_restore_snapshot``, mark ``regression_rolled_back``, and drop every landed
    move so the artifact reflects the rollback, not phantom contributions. The
    caller sets whichever EVIDENCE field is appropriate (``regressed_nodes`` on the
    red path; ``self_inflicted_red`` on the green path) — this only does the part
    that is identical for both.

    LEDGER CORRECTION: every objective's held moves are captured BEFORE they are
    dropped and handed ONCE, for the whole session, to the SHARED
    :func:`app.engine.objective_compiler._record_backstop_ledger_correction` — the
    same fail-closed writer the campaign-level backstop uses (``mode ==
    "develop-session-backstop"``), so a session rollback also feeds
    should_avoid/fragility with an honest ``rolled_back`` record instead of
    leaving the proof ledger silent about it (mirrors ``objective_compiler.
    _backstop_restore``). FAIL-CLOSED on an INCOMPLETE byte-restore: when
    ``_restore_snapshot`` reports it could not restore every path, the tree is
    not provably back at baseline, so the ledger correction is WITHHELD
    ENTIRELY rather than writing a "rolled_back" record that might itself be
    false. Any NATIVE-EXPERIENCE shapes the swept moves already recorded
    (``SessionMove.native_shapes``, threaded by ``_collect_objective``) are
    disclosed too — ``native_proof_memory`` is append-only, so that pollution
    can never be un-recorded. Every disclosure is via the EXISTING
    ``obj.blocked`` channel (prefix ``"backstop restore:"`` — the ONLY prefix
    :func:`render_session_markdown`'s dedicated section surfaces) — no new
    ``SessionReport``/``SessionObjective`` field, so a session that lands
    nothing (``swept`` empty) is unaffected."""
    swept = [(m.objective, m.operator, m.target,
             _SESSION_TIER_LEVEL.get(m.tier, "none"))
             for obj in report.objectives for m in obj.moves]
    swept_native = sorted(
        {shape for obj in report.objectives for m in obj.moves
         for shape in m.native_shapes})
    failed = _restore_snapshot(root, before, after)
    report.regression_rolled_back = True
    if failed:
        ok = False
    else:
        ok = _record_backstop_ledger_correction(
            root, swept, "session-backstop", "develop-session-backstop"
        ) if swept else True
    # The tree is back at baseline: drop every landed move so the artifact
    # reflects the rollback, not phantom contributions.
    for obj in report.objectives:
        _disclose_session_backstop(obj, failed, ok, swept_native)
        obj.moves = []


def _disclose_session_backstop(
    obj: SessionObjective, failed: list[str], ok: bool,
    swept_native: list[str],
) -> None:
    """Append :func:`_restore_and_zero`'s per-objective disclosures to
    ``obj.blocked`` — restore-incomplete/withheld-correction, failed
    correction write, and un-retractable native-experience pollution, each
    with the ``"backstop restore:"`` prefix ``render_session_markdown``'s
    dedicated section surfaces. Pure extraction from ``_restore_and_zero``
    (behavior byte-identical) to keep both under the complexity ceiling."""
    if not obj.moves:
        return
    if failed:
        obj.blocked.append(
            "backstop restore: restore incomplete "
            f"({len(failed)} file(s): {', '.join(failed)}) — ledger "
            "correction withheld — a false 'rolled_back' record would be "
            "worse than none")
    elif not ok:
        obj.blocked.append(
            "backstop restore: could not correct the proof ledger — "
            "should_avoid/fragility will NOT learn from this session "
            "rollback")
    if swept_native:
        obj.blocked.append(
            "backstop restore: native-experience memory for "
            f"{len(swept_native)} idiom shape(s) "
            f"({', '.join(swept_native)}) was already recorded before "
            "the rollback and could NOT be un-recorded")


def _maybe_rollback_regression(
    report: SessionReport, root: Path, before: dict[str, str],
    after: dict[str, str], baseline_failing: frozenset[str],
) -> dict[str, str]:
    """The END-OF-SESSION baseline-diff rollback backstop. Returns the effective
    ``after`` snapshot (``before`` when a regression was rolled back).

    The per-move gate already ran (impact-scoped on a red baseline), but a
    transitively-reachable GREEN test — outside every move's impacted scope — can
    be broken by a behaviour-changing transform and silently kept. So rerun the
    suite once, diff its failing-node set against the baseline's, and if ANY
    baseline-green node regressed, RESTORE every file to its pre-session bytes
    (delete created ones) — the sound, transform-agnostic guard. A node already
    failing at baseline is NOT a regression (honest disclosure, never
    over-rollback). Caller invokes this ONLY on a red baseline that changed files.

    FAIL-CLOSED on an invalid re-run: when the re-run collapses before its
    per-test summary (usage error, nothing collected, timeout), its node set is
    not comparable — diffing it would read "no regressions" off a run that
    never measured anything. The session is rolled back and the collapse is
    disclosed (``backstop_run_invalid``), never silently kept."""
    run_valid, after_failing = _failing_nodes_checked(root)
    if not run_valid:
        _restore_and_zero(report, root, before, after)
        report.backstop_run_invalid = True
        return before
    regressed = _regressed_nodes(baseline_failing, after_failing)
    if not regressed:
        return after
    _restore_and_zero(report, root, before, after)
    report.regressed_nodes = sorted(regressed)
    return before


def _finalize_apply(
    report: SessionReport, root: Path, before: dict[str, str], *, verify: bool,
    baseline_green: bool | None, baseline_failing: frozenset[str],
) -> None:
    """Build the apply-mode diff + run the full-suite backstop, after the session.

    The baseline-diff ROLLBACK backstop runs ONLY when the baseline was RED, the
    run gated (``verify``), and files actually changed — the precondition for the
    transitive-regression hole. Then the unified diff is computed against the
    EFFECTIVE after (which is ``before`` if a regression rolled the session back)
    and the disclosure full-suite backstop runs. On a GREEN baseline that backstop
    can ALSO observe RED — a late objective self-inflicting a regression a per-move
    gate missed (e.g. breaking an EARLIER objective's already-landed edits) — and
    THAT, too, restores the whole tree to its pre-session bytes (see below)."""
    after = _snapshot(root)
    if verify and baseline_green is False and after != before:
        after = _maybe_rollback_regression(
            report, root, before, after, baseline_failing)
    files, added, removed, diff = _diff_snapshots(before, after)
    report.files_changed = files
    report.lines_added = added
    report.lines_removed = removed
    report.diff = diff
    # Full-suite backstop: even though every move was gated, run the whole suite
    # once after the combined session and disclose the verdict. Under ``--no-verify``
    # (verify=False) NOTHING was gated and the backstop is NOT run, so
    # ``backstop_ran`` stays False and the renderer must NOT claim the suite is
    # green (never-fake-green — the moves are UNVERIFIED).
    if verify:
        report.suite_available, report.suite_green_after = _full_suite_green(root)
        report.backstop_ran = True
        # GREEN-baseline self-inflicted-RED backstop. The baseline was GREEN, so a
        # RED full suite AFTER the (gated) session is, by definition, a regression
        # the session caused — most plausibly a late objective breaking code an
        # EARLIER objective already landed (the per-move full-suite gate checks the
        # tree as it stood for THAT objective and never re-runs once a later one
        # edits over it). No failing-node diff is needed: green→red IS the proof.
        # Restore the WHOLE tree to its session-start bytes (the earlier objective's
        # edits reverted too) so the session never leaves the project worse than it
        # found it. Reuses ``before``/``_restore_snapshot`` — no new snapshot, no
        # extra suite run (the backstop result above is reused). Guards: ``after !=
        # before`` (a no-op session never restores) and ``suite_available`` (a
        # suite-less repo, whose ``suite_green_after`` defaults True, is untouched),
        # so a clean all-green session takes the exact same path as before — no
        # over-rollback. The red-baseline branch already handled its own RED, so this
        # only fires on a GREEN baseline.
        if (baseline_green is True and after != before
                and report.suite_available and not report.suite_green_after):
            _restore_and_zero(report, root, before, after)
            report.self_inflicted_red = True
            after = before
            files, added, removed, diff = _diff_snapshots(before, after)
            report.files_changed = files
            report.lines_added = added
            report.lines_removed = removed
            report.diff = diff


def run_develop_session(
    project_root: str | Path, *, max_steps: int = 25, verify: bool = True,
    apply: bool = False, scope_verify: bool = False,
    objectives: tuple[str, ...] = SESSION_OBJECTIVES,
    manifesto_aware: bool = False,
) -> SessionReport:
    """Run the fixed concrete-value-first objective sequence in one motion.

    Each objective runs its EXISTING deterministic ``compile_objective`` loop
    (suite/oracle-gated, auto-rollback), landed steps are accumulated, and ONE
    combined report is built as a pure function of the captured before/after
    sources. ``apply=False`` is a report-only dry run (no writes); ``apply=True``
    lands the moves. After an apply, the FULL suite is run once as the backstop
    and the report states whether the repo is green after.

    ``manifesto_aware`` (DEFAULT False = byte-identical to today) forwards to
    EVERY objective's ``compile_objective`` call unchanged; each objective's
    fired laws are aggregated onto ``report.manifesto_laws``, deduplicated in
    first-fired order across the whole session.

    Deterministic: fixed order, deterministic sub-loops, clock/random-free report.
    """
    root = Path(project_root)
    before = _snapshot(root) if apply else {}

    # VERIFICATION-UNAVAILABLE short-circuit. BEFORE any move work, check whether
    # the interpreter Apex would invoke can import pytest. If the project HAS a
    # pytest suite but pytest is missing, NOTHING can be verified: reading the
    # baseline as RED and rolling every landing back would be a silent, total
    # under-delivery. Decline up front instead — land nothing, roll nothing back,
    # set the loud flag the renderer surfaces. Gated on ``verify`` so an explicit
    # ``--no-verify`` run (which already declares its moves UNVERIFIED) is
    # byte-identical. Deterministic + memoized, so this costs at most one probe.
    if verify:
        interp = _verification_unavailable(root)
        if interp is not None:
            report = SessionReport(applied=apply)
            report.pytest_missing = True
            report.pytest_interpreter = interp
            return report

    # Probe the baseline suite ONCE, UP FRONT — before any objective runs — and
    # cache the bool. On a RED baseline (a "finish my project" repo whose suite
    # fails for an UNRELATED reason — an unfinished stub in some other module) the
    # cheap TIDY objectives would otherwise gate their CORRECT rename/hint/dataclass
    # change against the full red suite and get vetoed (every change rolled back).
    # When the baseline is RED we force impact-scoped gating for ALL objectives, so
    # a tidy change is gated only against the tests it actually impacts (which pass)
    # — never the unrelated pre-existing failures. The full-suite backstop below is
    # still the commit-time guard, so never-fake-green holds. A GREEN baseline keeps
    # full-suite gating exactly as before (happy path unchanged). The same cached
    # bool feeds the end-of-session honest "baseline RED" disclosure, so the suite
    # is probed AT MOST ONCE per session. ``scope_verify`` (the buyer's ``--fast``)
    # still forces scoping too; the two combine.
    # Only the apply path GATES (and so needs the baseline known BEFORE the loop to
    # pick the gate scope); a dry run gates nothing, so it probes lazily below only
    # if it must explain an empty outcome. ``None`` = not yet probed.
    baseline_green: bool | None = None
    # On a RED baseline the per-move gate is impact-SCOPED (above), which is fast
    # but blind to a previously-GREEN test reachable only TRANSITIVELY (outside the
    # impacted scope): a behaviour-CHANGING transform can break it and the move
    # lands un-noticed. So when (and only when) the baseline is RED we also capture
    # the EXACT set of failing node ids up front; after the session we rerun the
    # suite once and ROLL BACK if any baseline-green node regressed. The capture is
    # a single extra full-suite run, taken ONLY on a red apply baseline — correctness
    # over speed, and the green happy path pays nothing.
    baseline_failing: frozenset[str] = frozenset()
    if apply and verify:
        baseline_green = _baseline_suite_green(root)
        if baseline_green is False:
            baseline_failing = _failing_nodes(root)
    effective_scope = scope_verify or baseline_green is False

    # DELTA-GREEN baseline the per-move gate forgives. The session already probed
    # the suite ONCE up front, so it hands that SET to each ``compile_objective``
    # rather than letting every objective re-probe (one session-wide probe, not one
    # per objective). On a RED baseline this is the non-empty failing set (the gate
    # tolerates pre-existing reds, blocks a regression); on a GREEN baseline — and
    # on an un-gated run (dry / ``--no-verify``, where ``baseline_failing`` stayed
    # the default empty set) — it is the EMPTY set, which ``compile_objective`` reads
    # as absolute-green (no re-probe, per-move full-suite gating UNCHANGED), exactly
    # what the green-baseline self-inflicted-RED backstop relies on. Deterministic:
    # same set in, same set out.
    report = SessionReport(applied=apply)
    for objective in objectives:
        result = compile_objective(
            str(root), objective=objective, max_steps=max_steps,
            verify=verify, apply=apply, scope_verify=effective_scope,
            baseline_failing=baseline_failing, manifesto_aware=manifesto_aware)
        report.objectives.append(_collect_objective(result))
        _accumulate_manifesto_laws(report, result)

    if apply:
        _finalize_apply(report, root, before, verify=verify,
                        baseline_green=baseline_green,
                        baseline_failing=baseline_failing)

    # Baseline-red guard. When NOTHING landed, the renderer would otherwise say
    # "every objective is already satisfied" — which is a LIE if the real reason is
    # a RED baseline (unsynthesizable stubs / pre-existing failures), not a clean
    # project. REUSE the up-front cached probe (so the suite is run AT MOST ONCE per
    # session — no second full-suite run) to let the wording key off the honest
    # reason. Surfaced ONLY in this no-contribution case, so a session that LANDS
    # work keeps the field ``None`` (the cause of an empty list is moot when work
    # landed). Deterministic: same project -> same cached bool. When ``verify`` is
    # off the baseline was never probed (``baseline_green`` defaulted True) and the
    # field stays ``None`` — we never assert green we didn't run.
    if not report.objectives_with_work and verify:
        # Reuse the up-front probe if the apply path already ran it (AT MOST ONCE
        # per session); a dry run that landed nothing probes here, lazily.
        if baseline_green is None:
            baseline_green = _baseline_suite_green(root)
        report.baseline_suite_green = baseline_green
    return report


def _headline_lines(report: SessionReport) -> list[str]:
    """The title + one-line headline. Pure function of ``report``.

    Applied mode reports the real landed counts (files/lines from the diff).
    Report-only mode has NO dry-run diff, so files/lines are structurally 0 and
    rendering them reads as broken — point at ``--apply`` instead; the
    per-objective breakdown already lists each candidate move."""
    head = ["# Develop session — concrete objectives, one motion", ""]
    if report.pytest_missing:
        # Verification is unavailable: do NOT report a landed/ready count (there is
        # none, and a "0 contribution(s)" headline reads as a silent failure). Lead
        # with the honest decline; the body carries the actionable instructions.
        head += [
            "**Apex declined — verification is unavailable.** pytest is not "
            f"importable under the interpreter running Apex (`{report.pytest_interpreter}`), "
            "so no contribution could be verified, landed, or rolled back.", "",
        ]
        return head
    if report.applied:
        head += [
            f"**Apex landed {report.total_moves} contribution(s)** across "
            f"{len(report.files_changed)} file(s) "
            f"(+{report.lines_added} / -{report.lines_removed} lines).", "",
        ]
    else:
        head += [
            f"**Apex found {report.total_moves} contribution(s) ready to land.** "
            "Run again with `--apply` to write them to your tree.", "",
        ]
    return head


def _backstop_phrase(report: SessionReport) -> str:
    """The one-line full-suite backstop verdict — disclosure-only, as before."""
    if not report.backstop_ran:
        # --no-verify: nothing was gated and the backstop did NOT run, so we
        # cannot claim the suite is green. Disclose the moves are UNVERIFIED.
        return ("backstop not run (--no-verify) — moves UNVERIFIED, "
                "the full suite was not run to back-stop them")
    if not report.suite_available:
        return "no test suite detected — nothing to back-stop"
    if report.suite_green_after:
        return "✅ full suite GREEN after the session"
    return "⚠️ full suite RED after the session"


def _verification_lines(report: SessionReport) -> list[str]:
    """The applied-mode verification + backstop + auto-rollback disclosure lines."""
    parts = [f"**{report.verified_moves} verified** "
             f"(a test exercises the change)"]
    if report.weak_moves:
        parts.append(
            f"**{report.weak_moves} weak** (suite green but NO test references "
            f"the change — disclosed, not counted as verified)")
    if report.no_suite_moves:
        parts.append(
            f"**{report.no_suite_moves} no-suite** (landed but the repo has no "
            f"detectable test suite — disclosed, not counted as green)")
    if report.baseline_red_moves:
        parts.append(
            f"**{report.baseline_red_moves} baseline-red** (the whole scoped "
            f"suite was already red/ERROR before this move — nothing could "
            f"regress, but no test vouched for it either — disclosed, not "
            f"counted as verified)")
    lines = ["Verification: " + ", ".join(parts) + ".",
             f"Full-suite backstop: {_backstop_phrase(report)}."]
    if report.regression_rolled_back:
        # The end-of-session backstop caught a regression the per-move gate missed
        # and rolled the WHOLE session back to its pre-session bytes. Disclose it
        # loudly — never silently keep a regression. Two shapes, distinct wording:
        #   * self-inflicted (GREEN baseline went RED mid-session): no failing-node
        #     diff was computed, so ``regressed_nodes`` is empty — say a previously-
        #     GREEN baseline went RED, without implying named nodes there are none.
        #   * red-baseline transitive: name the specific previously-GREEN nodes the
        #     impact-scoped gate missed.
        if report.self_inflicted_red:
            lines.append(
                "⚠️ Auto-rollback: a GREEN baseline went RED mid-session "
                "(self-inflicted by a later objective) — the entire session was "
                "ROLLED BACK to its pre-session state; no contribution landed.")
        elif report.regressed_nodes:
            nodes = ", ".join(f"`{n}`" for n in report.regressed_nodes)
            lines.append(
                "⚠️ Auto-rollback: a previously-GREEN test regressed "
                f"({nodes}) — the entire session was ROLLED BACK to its "
                "pre-session state; no contribution landed.")
        else:
            lines.append(
                "⚠️ Auto-rollback: a previously-GREEN test regressed — the entire "
                "session was ROLLED BACK to its pre-session state; no contribution "
                "landed.")
    return lines


_BACKSTOP_DISCLOSURE_PREFIX = "backstop restore:"


def _backstop_disclosure_lines(report: SessionReport) -> list[str]:
    """The BACKSTOP-CORRECTION disclosures a session rollback left behind.

    :func:`_restore_and_zero` appends up to three distinct messages — a ledger
    correction failure, an incomplete-restore withhold, or unrecordable
    native-experience pollution — to EVERY objective's ``blocked`` list that
    lost moves, all prefix-matched ``"backstop restore:"``. This is the ONLY
    channel that landed those disclosures (no new ``SessionReport``/
    ``SessionObjective`` field — see that function's docstring), but
    ``render_session_markdown`` used to never read ``.blocked`` AT ALL, so a
    correction-failure or restore-incomplete verdict was silently invisible to
    the buyer artifact. Prefix-matched (never a bare substring) so an ORDINARY
    blocked reason (a declined move, an unserviceable target) never leaks into
    this section — those stay exactly where they always rendered: nowhere,
    same as before this fix (byte-identical for every session that never hit a
    backstop correction). Deduplicated (the same session-wide message is
    appended once per objective that lost moves) while preserving first-seen
    order, so the section reads as a short, non-repetitive list."""
    seen: set[str] = set()
    out: list[str] = []
    for obj in report.objectives:
        for b in obj.blocked:
            if b.startswith(_BACKSTOP_DISCLOSURE_PREFIX) and b not in seen:
                seen.add(b)
                out.append(b)
    return out


def _render_summary(report: SessionReport) -> list[str]:
    """The headline + per-objective breakdown lines (no diff)."""
    lines = _headline_lines(report)
    # The pytest-missing decline carries NO verification stats (nothing ran), so
    # skip the "N verified / backstop" block that would read as a hollow "0
    # verified" — the loud decline message in the breakdown below says it plainly.
    if report.applied and not report.pytest_missing:
        lines += _verification_lines(report)
    disclosures = _backstop_disclosure_lines(report)
    if disclosures:
        # ADDITIVE, present-only-when-present: a session that never hit a
        # backstop-correction disclosure renders byte-identically to before
        # this section existed.
        lines.append("")
        lines.append("## Backstop disclosures")
        for d in disclosures:
            lines.append(f"- ⚠️ {d}")
    lines.append("")
    lines.append("## Per-objective breakdown")
    work = report.objectives_with_work
    if not work:
        lines.append("")
        lines += _nothing_landed_lines(report)
    for obj in work:
        lines.append("")
        lines.append(f"### `{obj.objective}` — {obj.landed} move(s)")
        for i, mv in enumerate(obj.moves, 1):
            tag = {
                TIER_VERIFIED: "✅",
                TIER_WEAK: "⚠️ weak (suite green but uncovered)",
                TIER_NO_SUITE: "⚠️ no-suite",
                # A report-only projection: nothing was applied, so it must
                # never read as an applied tier (least of all "no-suite").
                TIER_PREVIEW: ("🔍 preview — not applied yet; "
                               "will be test-verified on --apply"),
                # The whole delta scope was already red/ERROR at baseline: never
                # a checkmark — no test exercised this change green.
                TIER_BASELINE_RED: ("🔶 baseline-red — unverifiable (scope "
                                    "already all-red at baseline)"),
            }.get(mv.tier, "⚠️ no-suite")
            lines.append(f"{i}. {mv.description} — {tag}")
    lines += _tier_footnote(report)
    lines += _manifesto_laws_lines(report)
    return lines


def _manifesto_laws_lines(report: SessionReport) -> list[str]:
    """Mirrors ``render_compile_markdown``'s 'Manifesto laws fired' block: which
    laws governed this session, so `apex manifesto`'s constitution is visibly
    governing here too. Present only when a law fired, so a session that never
    armed ``manifesto_aware`` (or hit no matured laws) renders byte-identically."""
    if not report.manifesto_laws:
        return []
    lines = ["", "## Manifesto laws fired"]
    lines += [f"- {law}" for law in report.manifesto_laws]
    return lines


def _nothing_landed_lines(report: SessionReport) -> list[str]:
    """The "no contribution landed" wording — HONEST about the reason.

    Two genuinely different causes hide behind an empty contribution list and the
    session must not conflate them (never-fake-green):

      * ``baseline_suite_green is False`` — the project's suite was RED *before*
        Apex touched anything (unsynthesizable stubs / pre-existing failures). An
        empty list does NOT mean the project is clean, so we say so explicitly and
        decline to claim a green Apex didn't earn.
      * otherwise (genuinely satisfied, or the baseline was never probed) — keep
        the positive "already satisfied" message byte-for-byte, so a clean GREEN
        project's report is unchanged from before."""
    if report.pytest_missing:
        # NOT "nothing to do" and NOT a RED suite: pytest is not importable under
        # the interpreter Apex would invoke, so NOTHING could be verified. The
        # session declined up front (proof-carrying: can't verify => don't touch);
        # nothing landed and nothing was rolled back as failed. Lead with the LOUD,
        # actionable message naming the interpreter so this is never a silent
        # mislabelled "0 executable".
        return [
            "_⚠️ "
            + _verification_unavailable_message(report.pytest_interpreter)
            + "_",
        ]
    if report.self_inflicted_red:
        # The baseline suite was GREEN, but a LATER objective regressed it
        # MID-SESSION (self-inflicted) — most plausibly by breaking code an earlier
        # objective already landed. The whole session was restored to its
        # pre-session bytes (the earlier objectives' edits reverted too). This is
        # NEITHER a pre-existing failure ("RED before any change") NOR an "already
        # satisfied" project; say so plainly so the wording is never misleading.
        return [
            "_No contribution stands: the baseline suite was GREEN, but a later "
            "objective REGRESSED it MID-SESSION (self-inflicted), so Apex rolled "
            "the ENTIRE session back to its pre-session bytes (auto-rollback). The "
            "earlier objectives' edits were reverted too — your tree is "
            "byte-identical to session start. This is NOT a pre-existing failure "
            "and NOT an 'already satisfied' project._",
        ]
    if report.regression_rolled_back:
        # The empty contribution list here is NOT "nothing to do" — work landed
        # then was UN-landed because it regressed a previously-green test. Say so
        # plainly; the backstop line above already named the regressed nodes.
        return [
            "_No contribution stands: the session landed work that REGRESSED a "
            "previously-green test, so Apex rolled the entire session back to its "
            "pre-session state (auto-rollback). This is NOT an 'already satisfied' "
            "project — nothing was kept because nothing held._",
        ]
    if report.baseline_suite_green is False:
        return [
            "_No concrete contribution available, but the project's test suite is "
            "RED before any change (pre-existing failures). Apex verifies each "
            "contribution against the tests it impacts and will not claim a green "
            "it didn't earn — this is NOT an 'already satisfied' project._",
        ]
    return [
        "_No concrete contribution available — every objective is "
        "already satisfied._",
    ]


def _tier_footnote(report: SessionReport) -> list[str]:
    """Explain the non-verified tiers — ONLY when a move carries one, so a
    fully-verified report stays byte-identical (honesty, not a defect)."""
    if not (report.weak_moves or report.no_suite_moves or report.preview_moves
            or report.baseline_red_moves):
        return []
    note = ["", "Tiers:"]
    if report.weak_moves:
        note.append("- `weak` = applied and the suite is green, but NO test exercises this code, so Apex won't claim it's test-verified; add a test (or `apex shield`) to upgrade it.")
    if report.no_suite_moves:
        note.append("- `no-suite` = applied but no test suite exists to verify this code, so Apex won't claim it's test-verified; add a test (or `apex shield`) to upgrade it.")
    if report.baseline_red_moves:
        note.append("- `baseline-red` = applied, but the WHOLE scoped suite was already red/ERROR before this move, so nothing could regress — but no test vouched for it either; Apex won't claim it's test-verified.")
    if report.preview_moves:
        # A dry run applied NOTHING — the footnote must never claim otherwise
        # (the old no-suite mislabel said "applied but no test suite exists").
        note.append("- `preview` = a report-only listing: nothing was applied or written; run with `--apply` to land it test-verified (suite-gated, auto-rollback).")
    return note


_TIER_LABEL = {
    "tier1": "Tier 1 (lands new code)",
    "tier2": "Tier 2 (structural)",
    "tier3": "Tier 3 (idiom)",
}


def _value_landed_lines(report: SessionReport) -> list[str]:
    """The buyer's value scorecard ON the landed diff — present ONLY when moves
    landed, so a no-op / nothing-landed report renders byte-identically.

    A pure render of :func:`value_landed_from_session(report)`: the verified
    total with the honest weak/unverified split, a per-tier table over the
    verified moves, and the top contributions (each a real landed diff below).
    No clock/random."""
    metric = value_landed_from_session(report)
    lines = [
        "",
        "## Value landed (what a buyer would pay for)",
        "",
        f"**{metric['value_landed_verified']:.2f} verified value** landed "
        f"({metric['moves_verified']} move(s)) — "
        f"{metric['value_landed_weak']:.2f} weak, "
        f"{metric['value_landed_unverified']:.2f} unverified (disclosed, not "
        "counted as verified).",
        "",
        "| Tier | Verified moves | Verified value |",
        "| --- | --- | --- |",
    ]
    for tier in ("tier1", "tier2", "tier3"):
        lines.append(
            f"| {_TIER_LABEL[tier]} | {metric['moves_by_tier'][tier]} | "
            f"{metric['by_tier'][tier]:.2f} |")
    top = [c for c in metric["top_contributions"] if c["bucket"] == "verified"]
    if top:
        lines.append("")
        lines.append("Top verified contributions:")
        for c in top:
            target = c["target"] or "(project)"
            lines.append(f"- `{c['operator']}` → {target} ({c['value']:.2f})")
    return lines


def render_session_markdown(report: SessionReport) -> str:
    """Render the combined session report — the buyer artifact.

    Pure function of the report: a stable headline, the per-objective breakdown,
    the value scorecard (only when moves landed), and the unified diff (the
    tangible code Apex landed). No clock/random, so the same report renders
    byte-identically every time."""
    lines = _render_summary(report)
    # Additive, present-only-when-present: the value scorecard appears ONLY for an
    # applied session that actually landed a move, so a report-only / no-op /
    # nothing-landed report is byte-identical to before.
    if report.applied and report.total_moves:
        lines += _value_landed_lines(report)
    if report.applied and report.diff:
        lines.append("")
        lines.append("## The verified diff (the tangible artifact)")
        lines.append("")
        lines.append("```diff")
        lines.append(report.diff.rstrip("\n"))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


# --- Proof trail: the session's landings as proof-of-fix evidence ------------
#
# A LANDED ``apex develop session --apply`` move IS a verified-with-rollback fix,
# so its realized buyer value belongs on the SAME ``.apex/proof-of-fix.json``
# trail that ``value_landed`` / the owner-report / the tamper-seal already
# consume — making the session's realized value legible cross-run. This is the
# develop-side analog of the dream chain's ``build_dream_proof`` wiring; the two
# stay attributable by their distinct ``mode`` (``develop-session`` vs
# ``dream-land``) on the shared, content-addressed trail.
#
# These two helpers are PURE and READ-ONLY over the report: each landed-and-held
# move (a ``SessionMove`` — a failed gate was rolled back by the engine and a
# regression empties ``obj.moves`` entirely, so only held moves are present)
# becomes one value-grade record matching ``proof_of_fix._fix_record``'s exact
# output contract, so ``value_landed`` / ``proof_hash`` / ``proof_manifest``
# score it UNCHANGED. We HONESTLY omit diff/changed_files (not threaded up
# through ``SessionMove``; faking them would betray the never-fake-green moat),
# and never fabricate a record for a move that did not hold.

# The session tier -> proof coverage-level map. ``SessionMove`` carries no
# ``coverage`` string (unlike the dream chain's ``CompileStep.coverage``), only
# the coverage-aware ``tier`` ``_tier_for`` stamped — so the proof builder maps
# the tier onto a ``value_landed``-recognized level. This table is the HONEST
# INVERSE of ``value_landed._SESSION_TIER_BUCKET``: feeding a record built from
# this level back through ``value_landed`` lands each move in the SAME honesty
# bucket ``value_landed_from_session`` assigns in-memory. ``"module"`` (not
# ``"function"``) is the conservative verified level — it never over-claims
# function-level coverage we cannot prove from a bare tier.
_SESSION_TIER_LEVEL = {
    TIER_VERIFIED: "module",    # genuinely verified -> a verified-bucket level
    TIER_WEAK: "none",          # green-but-uncovered -> the weak bucket
    TIER_NO_SUITE: "no-suite",  # nothing ran -> the unverified bucket
}


def _session_proof_records(report: SessionReport) -> list[dict]:
    """One value-grade proof record per LANDED-AND-HELD move, in session order.

    Each record matches ``proof_of_fix._fix_record``'s output contract exactly:
    ``finding`` (label/branch/action/operator/target), an empty
    ``transform_type`` and ``None`` ``risk_tier``, ``outcome == "applied"`` (only
    held moves reach ``report.objectives[*].moves`` — a failed gate was rolled
    back and a regression emptied the move list), empty ``changed_files``/``diff``
    (the session does not thread the per-move diff up — we omit it honestly rather
    than fake it), the ``verification.strength.level`` derived from the move's
    ``tier`` via :data:`_SESSION_TIER_LEVEL` (the SAME
    ``function``/``module``/``none``/``no-suite`` vocabulary value-landed reads),
    and a not-rolled-back ``rollback`` clause. Pure: no clock, no random, no I/O —
    a deterministic projection of the report."""
    records: list[dict] = []
    for obj in report.objectives:
        for mv in obj.moves:
            records.append({
                "finding": {
                    "label": obj.objective,
                    "branch": "",
                    "action": obj.objective,
                    "operator": mv.operator,
                    "target": mv.target,
                },
                "transform_type": "",
                "risk_tier": None,
                "outcome": "applied",
                "changed_files": [],
                "diff": "",
                "verification": {
                    "performed": mv.tier != TIER_NO_SUITE,
                    "strength": {"level": _SESSION_TIER_LEVEL.get(mv.tier, "none")},
                },
                "rollback": {"occurred": False, "reason": ""},
            })
    return records


def build_session_proof(report: SessionReport, project_root: str | Path) -> dict:
    """A proof-of-fix artifact for the develop session, in ``build_proof``'s schema.

    Reuses ``proof_of_fix``'s ``SCHEMA``/``SCHEMA_VERSION``/``tool_version`` and the
    same top-level shape ``build_proof`` emits, with ``mode == "develop-session"``,
    the ``fixes`` list from :func:`_session_proof_records`, and totals folded from
    the report (every landed-and-held move is an applied, never-rolled-back fix).
    So ``value_landed`` / ``proof_hash`` / ``proof_manifest`` / ``write_proof`` all
    consume it UNCHANGED, and the session's realized value joins the cross-run
    trail. ``totals.rolled_back == 0`` is honest BECAUSE a rolled-back move never
    appears in ``fixes`` (a per-move failure never reached the steps list; an
    end-of-session regression emptied ``obj.moves``).

    Pure apart from ``build_proof``'s lone clock convention: ``generated_at`` is
    the ONLY wall-clock, and it lives OUTSIDE the tamper seal — so the records,
    ``proof_hash`` and ``value_landed`` are byte-deterministic over the same
    landed moves. Read-only over the report; writes nothing (that is
    ``write_proof``'s job)."""
    from datetime import datetime, timezone

    from app.engine.proof_of_fix import (
        SCHEMA,
        SCHEMA_VERSION,
        tool_version,
    )

    fixes = _session_proof_records(report)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "Apex Orchestrator", "version": tool_version()},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "objective": "develop-session",
        "mode": "develop-session",
        "verify": True,
        "totals": {
            "executable": report.total_moves,
            "applied": len(fixes),
            "rolled_back": 0,
            "blocked": 0,
            "committed": 0,
        },
        "fixes": fixes,
    }
