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
import os
from pathlib import Path
from typing import Any

from app.engine.objective_compiler import (
    SESSION_OBJECTIVES,
    CompileResult,
    compile_objective,
)

__all__ = [
    "SessionMove", "SessionObjective", "SessionReport",
    "run_develop_session", "render_session_markdown",
]

# Verification tiers a landed move can carry. A move only reaches the report if
# it LANDED (the engine kept it); a move that failed its gate was rolled back and
# is surfaced as a refusal, not a tier.
TIER_VERIFIED = "verified"   # suite ran green AND a test exercises the change
TIER_WEAK = "weak"           # suite ran green but NO test references the change
TIER_NO_SUITE = "no-suite"   # the move landed but NO suite could verify it

# Directories never worth snapshotting for the diff (caches, vcs, venvs, the
# .apex memory store). Skipping them keeps the snapshot — and so the report — a
# stable function of the project's own source, not its incidental tooling state.
_SKIP_DIRS = {".git", ".hg", ".svn", ".apex", ".venv", "venv", "__pycache__",
              ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules",
              ".tox", "build", "dist", ".eggs"}


@dataclass
class SessionMove:
    """One landed move, with the verification tier it earned."""
    objective: str
    operator: str
    target: str
    description: str
    tier: str

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
    def objectives_with_work(self) -> list[SessionObjective]:
        return [o for o in self.objectives if o.moves]

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "objectives": [o.to_dict() for o in self.objectives],
            "diff": self.diff,
        }


def _snapshot(root: Path) -> dict[str, str]:
    """Map of ``rel_posix_path -> source`` for every ``.py`` file under ``root``.

    Skips caches/vcs/venv dirs (``_SKIP_DIRS``) so the snapshot is a stable
    function of the project's own source. Walked in sorted order for a
    deterministic file set; an unreadable file is simply omitted."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            try:
                out[path.relative_to(root).as_posix()] = path.read_text(
                    encoding="utf-8")
            except OSError:
                continue
    return out


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

    A move that FAILED its gate never reaches the steps list (it was rolled back),
    so these are the only tiers a reported move can hold."""
    if not getattr(step, "verified", False):
        return TIER_NO_SUITE
    return TIER_VERIFIED if getattr(step, "coverage_verified", False) else TIER_WEAK


def _collect_objective(result: CompileResult) -> SessionObjective:
    """Fold one objective's CompileResult into the session's per-objective view."""
    obj = SessionObjective(objective=result.objective)
    for step in result.steps:
        obj.moves.append(SessionMove(
            objective=result.objective, operator=step.operator,
            target=step.target, description=step.description,
            tier=_tier_for(step)))
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


def run_develop_session(
    project_root: str | Path, *, max_steps: int = 25, verify: bool = True,
    apply: bool = False, scope_verify: bool = False,
    objectives: tuple[str, ...] = SESSION_OBJECTIVES,
) -> SessionReport:
    """Run the fixed concrete-value-first objective sequence in one motion.

    Each objective runs its EXISTING deterministic ``compile_objective`` loop
    (suite/oracle-gated, auto-rollback), landed steps are accumulated, and ONE
    combined report is built as a pure function of the captured before/after
    sources. ``apply=False`` is a report-only dry run (no writes); ``apply=True``
    lands the moves. After an apply, the FULL suite is run once as the backstop
    and the report states whether the repo is green after.

    Deterministic: fixed order, deterministic sub-loops, clock/random-free report.
    """
    root = Path(project_root)
    before = _snapshot(root) if apply else {}

    report = SessionReport(applied=apply)
    for objective in objectives:
        result = compile_objective(
            str(root), objective=objective, max_steps=max_steps,
            verify=verify, apply=apply, scope_verify=scope_verify)
        report.objectives.append(_collect_objective(result))

    if apply:
        after = _snapshot(root)
        files, added, removed, diff = _diff_snapshots(before, after)
        report.files_changed = files
        report.lines_added = added
        report.lines_removed = removed
        report.diff = diff
        # Full-suite backstop: even though every move was gated, run the whole
        # suite once after the combined session and disclose the verdict. Under
        # ``--no-verify`` (verify=False) NOTHING was gated and the backstop is
        # NOT run, so ``backstop_ran`` stays False and the renderer must NOT claim
        # the suite is green (never-fake-green — the moves are UNVERIFIED).
        if verify:
            report.suite_available, report.suite_green_after = _full_suite_green(root)
            report.backstop_ran = True

    # Baseline-red guard. When NOTHING landed, the renderer would otherwise say
    # "every objective is already satisfied" — which is a LIE if the real reason is
    # a RED baseline (unsynthesizable stubs / pre-existing failures), not a clean
    # project. Probe the baseline ONCE, and ONLY in this no-contribution case (so a
    # session that LANDS work never pays the extra full-suite run), to let the
    # wording key off the honest reason. Deterministic: same project -> same bool.
    if not report.objectives_with_work:
        report.baseline_suite_green = _baseline_suite_green(root)
    return report


def _headline_lines(report: SessionReport) -> list[str]:
    """The title + one-line headline. Pure function of ``report``.

    Applied mode reports the real landed counts (files/lines from the diff).
    Report-only mode has NO dry-run diff, so files/lines are structurally 0 and
    rendering them reads as broken — point at ``--apply`` instead; the
    per-objective breakdown already lists each candidate move."""
    head = ["# Develop session — concrete objectives, one motion", ""]
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


def _render_summary(report: SessionReport) -> list[str]:
    """The headline + per-objective breakdown lines (no diff)."""
    lines = _headline_lines(report)
    if report.applied:
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
        lines.append("Verification: " + ", ".join(parts) + ".")
        if not report.backstop_ran:
            # --no-verify: nothing was gated and the backstop did NOT run, so we
            # cannot claim the suite is green. Disclose the moves are UNVERIFIED.
            backstop = ("backstop not run (--no-verify) — moves UNVERIFIED, "
                        "the full suite was not run to back-stop them")
        elif not report.suite_available:
            backstop = "no test suite detected — nothing to back-stop"
        elif report.suite_green_after:
            backstop = "✅ full suite GREEN after the session"
        else:
            backstop = "⚠️ full suite RED after the session"
        lines.append(f"Full-suite backstop: {backstop}.")
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
            }.get(mv.tier, "⚠️ no-suite")
            lines.append(f"{i}. {mv.description} — {tag}")
    lines += _tier_footnote(report)
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
    if not (report.weak_moves or report.no_suite_moves):
        return []
    note = ["", "Tiers:"]
    if report.weak_moves:
        note.append("- `weak` = applied and the suite is green, but NO test exercises this code, so Apex won't claim it's test-verified; add a test (or `apex shield`) to upgrade it.")
    if report.no_suite_moves:
        note.append("- `no-suite` = applied but no test suite exists to verify this code, so Apex won't claim it's test-verified; add a test (or `apex shield`) to upgrade it.")
    return note


def render_session_markdown(report: SessionReport) -> str:
    """Render the combined session report — the buyer artifact.

    Pure function of the report: a stable headline, the per-objective breakdown,
    and the unified diff (the tangible code Apex landed). No clock/random, so the
    same report renders byte-identically every time."""
    lines = _render_summary(report)
    if report.applied and report.diff:
        lines.append("")
        lines.append("## The verified diff (the tangible artifact)")
        lines.append("")
        lines.append("```diff")
        lines.append(report.diff.rstrip("\n"))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)
