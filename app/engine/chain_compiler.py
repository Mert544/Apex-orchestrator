"""`chain_compiler` — run an EXPLICIT, ordered SEQUENCE of develop objectives as
one proof-carrying, precondition-gated campaign.

Where ``dream_develop`` (``apex dream --land``) sequences ONE hardcoded goal
(``resolve_goal("ship-value", value_led=True)`` — the North-Star concrete
flatten, whole-tree or dream-scoped), this generalizes that same motion to an
ARBITRARY caller-supplied ordered list of objectives — a "chain" like
``["implement-stub", "cover-gaps", "strengthen-tests"]``. The DELTA over
``dream_develop`` is exactly three things, and NOTHING else:

  1. **explicit sequence** — the caller names the objectives AND their order; the
     chain runs them in that source order (no value re-sort, no goal flatten), so
     a human/idea can compose a precise campaign the compiler runs verbatim;
  2. **per-step PRECONDITIONS** — a step whose success genuinely DEPENDS on an
     earlier step (``strengthen-tests`` refuses a module with no linked test, so
     ``cover-gaps`` is its precondition) is checked against the FROZEN,
     drift-tested ``idea_composition._COMPOSITION_EDGES`` grammar: if the step's
     declared producer appears earlier in THIS chain but LANDED NOTHING, its
     precondition is unmet and the step is SKIPPED honestly (or the chain HALTS,
     opt-in) — never faked;
  3. **chain-level archival + halt** — a step whose gate ROLLED BACK a move (the
     suite went red) HALTS the chain (verified-or-refused, never a partial fake
     green), and the LANDED chain is archived to ``composition_archive`` under its
     objective-sequence signature — one learned recipe for "this ordered chain
     did N verified moves for a fitness gain of D".

Every byte the chain writes goes through the EXISTING ``compile_objective``
propose→apply→measure→select loop — suite-gated with byte-for-byte
``apply_rename`` rollback. This module adds ZERO new verification logic: the
never-fake-green moat is inherited PER STEP (a step lands a move only if its own
suite is green; a regression is rolled back inside ``compile_objective``). It is
pure orchestration over shipped primitives and registers NO develop objective (it
COMPOSES existing ones), so there is no objective-count / Facet-parity obligation.

DETERMINISM: the report body carries no clock and no randomness — the chain order
is the caller's list verbatim, the precondition grammar is a frozen table, and the
per-step gate is the deterministic compiler. Two runs on the same tree and same
chain render byte-identical. Stdlib-only; offline by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.objective_compiler import CompileResult, compile_objective

__all__ = [
    "ChainStep", "ChainReport", "run_chain", "render_chain_markdown",
]


@dataclass
class ChainStep:
    """One objective in the explicit chain and how it resolved.

    ``status`` is the honest per-step verdict: ``landed`` (it composed at least one
    verified move), ``empty`` (attempted, nothing to do — an honest no-op),
    ``skipped-precondition`` (an earlier producer it depends on landed nothing, so
    its precondition is unmet — never faked), ``red`` (a move rolled back: the
    suite went red, so the chain halts here), or ``halted`` (a later step the chain
    never reached because an earlier step skipped/rolled back under a halt policy).
    ``result`` is the underlying ``compile_objective`` campaign (``None`` for a
    step that was skipped/halted before it ran)."""
    objective: str
    status: str
    reason: str = ""
    result: CompileResult | None = None

    @property
    def moves(self) -> int:
        return len(self.result.steps) if self.result else 0

    @property
    def landed(self) -> bool:
        return self.status == "landed"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "objective": self.objective, "status": self.status,
            "reason": self.reason, "moves": self.moves,
        }
        if self.result is not None:
            d["result"] = self.result.to_dict()
        return d


@dataclass
class ChainReport:
    """The explicit-sequence chain's deterministic result.

    ``objectives`` is the caller's ordered chain verbatim; ``steps`` is the
    per-objective outcome in that order; ``grade_before``/``grade_after`` is the
    single before→after health proof (``-1`` on a dry run, which writes nothing to
    measure); ``halted`` records whether the chain stopped early (a red step, or a
    skipped precondition under the halt policy)."""
    objectives: list[str]
    steps: list[ChainStep] = field(default_factory=list)
    grade_before: int = -1
    grade_after: int = -1
    applied: bool = False
    halted: bool = False
    halt_reason: str = ""

    @property
    def total_moves(self) -> int:
        return sum(s.moves for s in self.steps)

    @property
    def landed_objectives(self) -> list[str]:
        """The chain steps that composed at least one verified move, in order."""
        return [s.objective for s in self.steps if s.landed]

    @property
    def green(self) -> bool:
        """The chain is GREEN iff every LANDED step held its suite AND the chain
        did not halt on a red step — the never-fake-green chain verdict. A chain
        with nothing to land (all steps empty) is trivially green (it faked
        nothing); a chain halted by a rolled-back move is NOT green."""
        return not self.halted

    @property
    def verified_moves(self) -> int:
        """Moves a test GENUINELY exercised across the chain — the honest count
        (a green-but-unreferencing suite does NOT count as verified)."""
        return sum(1 for s in self.steps if s.result
                   for m in s.result.steps if m.coverage_verified)

    @property
    def grade_delta(self) -> int:
        if self.grade_before < 0 or self.grade_after < 0:
            return 0
        return self.grade_after - self.grade_before

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectives": self.objectives,
            "steps": [s.to_dict() for s in self.steps],
            "landed_objectives": self.landed_objectives,
            "grade_before": self.grade_before, "grade_after": self.grade_after,
            "grade_delta": self.grade_delta, "total_moves": self.total_moves,
            "verified_moves": self.verified_moves, "green": self.green,
            "applied": self.applied, "halted": self.halted,
            "halt_reason": self.halt_reason,
        }


def _grade(project_root: str | Path) -> int:
    """The project's health grade, or ``-1`` when it cannot be computed (the same
    best-effort pattern ``dream_develop._grade`` / ``fractal_develop._grade`` use)."""
    try:
        from app.engine.health_score import grade
        return grade(str(project_root)).score
    except Exception:
        return -1


def _precondition_producer(objective: str, earlier: list[str]) -> str | None:
    """The EARLIER chain objective whose success is a declared precondition for
    ``objective``, or ``None`` when the chain names no such producer.

    Grounded in the FROZEN, drift-tested ``idea_composition._COMPOSITION_EDGES``
    grammar (the SAME grammar ``compose_chains`` walks): ``objective`` depends on a
    producer ``p`` iff the grammar lists ``objective`` as a successor of ``p`` (e.g.
    ``strengthen-tests`` is a successor of ``cover-gaps``). We return the LAST such
    producer that appears earlier in this chain — the nearest satisfier — so a
    chain that never placed a producer before ``objective`` has no precondition
    here (returns ``None`` ⇒ the step runs unconditionally). Pure/deterministic:
    a frozen table lookup, no clock, no IO."""
    from app.engine.idea_composition import _COMPOSITION_EDGES
    producers = {p for p, edges in _COMPOSITION_EDGES.items()
                 if any(succ == objective for succ, _why in edges)}
    for prior in reversed(earlier):
        if prior in producers:
            return prior
    return None


def _precondition_unmet(objective: str, earlier: list[str],
                        landed: set[str]) -> str:
    """The honest reason ``objective``'s precondition is unmet, or ``""`` when met.

    A step's precondition is unmet when the grammar names an earlier producer for
    it (:func:`_precondition_producer`) AND that producer LANDED NOTHING in this
    chain (so the state the successor needs — a first test, a filled body, a fresh
    @dataclass — was never actually created). The returned reason quotes the
    grammar's own rationale, so the skip/halt is legible. When no producer is named
    earlier, or the named producer landed, the precondition is met (returns
    ``""``)."""
    producer = _precondition_producer(objective, earlier)
    if producer is None or producer in landed:
        return ""
    from app.engine.idea_composition import _COMPOSITION_EDGES
    why = next((w for succ, w in _COMPOSITION_EDGES.get(producer, ())
                if succ == objective), "")
    tail = f" ({why})" if why else ""
    return (f"precondition unmet — `{producer}` landed nothing, so "
            f"`{objective}` has nothing to build on{tail}")


def _step_is_red(result: CompileResult) -> bool:
    """Did ``result`` ROLL BACK a move (the suite went red), landing nothing?

    A red step is one the compiler ATTEMPTED (it had work) but every candidate move
    regressed and was auto-rolled-back — surfaced by ``compile_objective`` as a
    ``blocked`` reason mentioning the rollback ("tests failed ... restored"), with
    NO step appended. An honest EMPTY step (nothing to do) has no such reason, so it
    is NOT red. This reads the compiler's OWN rollback disclosure — the chain adds
    no gate logic; the never-fake-green verdict is inherited."""
    if result.steps:
        return False  # it landed something → not a red halt
    return any("tests failed" in b or "restored" in b for b in result.blocked)


def _run_step(project_root: str | Path, objective: str, earlier: list[str],
              landed: set[str], *, max_steps: int, verify: bool, apply: bool,
              fast: bool) -> ChainStep:
    """Resolve ONE chain step: check its precondition, then (if met) run it through
    the EXISTING ``compile_objective`` gate and classify the outcome.

    Returns a ``ChainStep`` with the honest status: ``skipped-precondition`` (an
    earlier producer it depends on landed nothing), ``red`` (a move rolled back —
    the suite went red), ``landed`` (at least one verified move), or ``empty`` (no
    work). ZERO new verification: the suite gate + rollback live inside
    ``compile_objective``."""
    unmet = _precondition_unmet(objective, earlier, landed)
    if unmet:
        return ChainStep(objective=objective, status="skipped-precondition",
                         reason=unmet)
    campaign = compile_objective(
        project_root, objective=objective, max_steps=max_steps, verify=verify,
        apply=apply, scope_verify=fast)
    if _step_is_red(campaign):
        return ChainStep(objective=objective, status="red", result=campaign,
                         reason="a move rolled back — the suite went red")
    status = "landed" if campaign.steps else "empty"
    return ChainStep(objective=objective, status=status, result=campaign)


def _archive_chain(report: ChainReport, project_root: str | Path) -> None:
    """Archive the LANDED chain to ``composition_archive`` as one recipe.

    Reuses ``composition_archive.record_campaign`` — the SAME MAP-Elites store the
    per-objective compiler writes — keyed by the chain's ordered objective
    SIGNATURE (``chain:a>b>c``) so a chain competes only with other runs of the
    SAME sequence, never with a single objective's cell. The recipe's operators are
    the landed objectives in chain order; its fitness gain is the chain's total
    landed moves (each move clears one unit of debt, like the compiler's monotone
    campaigns). Best-effort and a STRICT no-op unless the chain applied AND landed —
    a dry run, an empty chain, or an all-skipped chain writes NOTHING, so the
    off-by-default tree stays byte-identical. Honest: records only what LANDED."""
    if not report.applied:
        return  # a dry run measured nothing to learn from
    landed = report.landed_objectives
    if not landed:
        return  # nothing landed → nothing to archive (byte-identical)
    from app.engine.composition_archive import record_campaign
    signature = _chain_signature(report)
    total = float(report.total_moves)
    try:
        record_campaign(project_root, signature, landed,
                        total, 0.0, len(landed))
    except OSError:
        pass  # the playbook is best-effort; never fail a good chain on a write


def _chain_signature(report: ChainReport) -> str:
    """The chain's ordered objective SIGNATURE ``chain:a>b>c`` — the SAME key the
    composition archive and the idea-memory chain table share, so a chain's whole
    ordered recipe is learned under ONE stable identity (no clock, no IO)."""
    return "chain:" + ">".join(report.objectives)


def _chain_outcome(report: ChainReport) -> str:
    """The chain's realized outcome bucket for :meth:`IdeaMemory.record_chain_outcome`,
    or ``""`` when there is nothing honest to record.

    Never-fake-green mapping: a chain that did NOT halt and LANDED at least one
    verified move is ``"applied"`` — the whole ordered recipe HELD (every landed
    step's suite stayed green, nothing rolled back). A chain HALTED by a
    rolled-back (suite-red) step is ``"rolled_back"`` (a genuine regression); a
    chain halted for any other reason (an opted-in precondition halt) is
    ``"blocked"``. A non-halted chain that landed NOTHING (all steps empty/skipped)
    is an honest no-op — ``""`` records nothing, so an all-empty chain leaves
    ``by_chain`` untouched (opt-in / byte-identical). Only a genuinely-held chain
    is ever a success, so a halted chain can never inflate a recipe's land-rate."""
    if report.halted:
        return "rolled_back" if any(s.status == "red" for s in report.steps) else "blocked"
    return "applied" if report.landed_objectives else ""


def _record_chain_memory(report: ChainReport, project_root: str | Path) -> None:
    """Record the chain's realized outcome into ``idea_memory.by_chain`` — the
    LEARNING loop that lets ascend/goal-trees rank whole ordered chains by the SAME
    Wilson-CI lower bound they already use for operators and sequences.

    Reuses the EXACT ordered signature the archive is keyed by (:func:`_chain_signature`),
    so the chain memory and the playbook speak one identity. Best-effort and a STRICT
    no-op unless the chain APPLIED and produced an honest outcome (:func:`_chain_outcome`):
    a dry run (``applied`` False), an empty chain, or an all-empty chain records
    NOTHING — so ``by_chain`` stays empty until a chain genuinely lands or halts and
    the off-by-default tree/ranking stays byte-identical. Honest: only a held chain
    is an ``applied`` success; a rolled-back/blocked chain is recorded as a
    NON-success and never a faked win. A write failure is swallowed (learning never
    fails a good chain)."""
    if not report.applied:
        return  # a dry run measured nothing to learn from
    outcome = _chain_outcome(report)
    if not outcome:
        return  # an all-empty chain did nothing to learn from (byte-identical)
    from app.engine.idea_memory import IdeaMemory
    try:
        mem = IdeaMemory.load(project_root)
        mem.record_chain_outcome(_chain_signature(report), outcome)
        mem.save(project_root)
    except OSError:
        pass  # the learn store is best-effort; never fail a good chain on a write


def run_chain(project_root: str | Path, objectives: list[str], *,
              max_steps: int = 25, verify: bool = True, apply: bool = False,
              fast: bool = False,
              halt_on_unmet_precondition: bool = False) -> ChainReport:
    """Run an EXPLICIT, ordered chain of develop objectives — each suite-gated, its
    precondition checked — and emit one deterministic :class:`ChainReport`.

    The generalization of ``dream_develop``'s hardcoded ``ship-value`` sequence:
    the caller supplies ANY ordered ``objectives`` list, and the chain runs them in
    THAT source order. Each step is:

      * PRECONDITION-checked against the frozen ``idea_composition`` grammar — a
        step whose declared earlier producer landed nothing is SKIPPED honestly
        (status ``skipped-precondition``); with ``halt_on_unmet_precondition`` the
        chain HALTS at the first unmet precondition instead of skipping past it;
      * GATED through the EXISTING ``compile_objective`` verified-with-rollback loop
        — a move lands only if its suite is green; a regression is rolled back
        INSIDE the compiler (zero new gate logic here);
      * a RED step (a move rolled back — the suite went red) HALTS the chain: the
        chain is green IFF every landed step held AND no step went red, so a partial
        fake-green is impossible.

    ``apply`` defaults to ``False`` (DRY-RUN: reports the moves each step WOULD land,
    writing nothing); ``apply=True`` writes, every byte gated. ``fast`` scopes each
    step's gate to the changed module. On an apply that landed anything, the chain
    is archived to ``composition_archive`` under its objective-sequence signature.

    Baseline/fitness is carried across steps via the SHARED tree: each step's
    ``compile_objective`` re-measures fitness against the CURRENT tree (an earlier
    step's landed edits are visible), and a step's precondition reads whether its
    producer actually LANDED earlier in this same chain — so state genuinely flows
    step→step. Deterministic: the order is the caller's list, the precondition
    grammar is frozen, and the report body carries no clock/random."""
    before = _grade(project_root) if apply else -1
    report = ChainReport(objectives=list(objectives), applied=apply,
                         grade_before=before)
    landed: set[str] = set()
    seen: list[str] = []
    halted = False
    for i, objective in enumerate(objectives):
        if halted:
            # A prior step halted the chain: every remaining objective is recorded
            # as ``halted`` (never attempted, never faked) for an honest report.
            report.steps.append(ChainStep(objective=objective, status="halted",
                                          reason=report.halt_reason))
            continue
        step = _run_step(project_root, objective, seen, landed,
                         max_steps=max_steps, verify=verify, apply=apply, fast=fast)
        report.steps.append(step)
        seen.append(objective)
        if step.landed:
            landed.add(objective)
        elif step.status == "red":
            halted = True
            report.halted = True
            report.halt_reason = f"`{objective}`: {step.reason}"
        elif step.status == "skipped-precondition" and halt_on_unmet_precondition:
            halted = True
            report.halted = True
            report.halt_reason = f"`{objective}`: {step.reason}"
    report.grade_after = _grade(project_root) if (apply and before >= 0) else before
    _archive_chain(report, project_root)
    _record_chain_memory(report, project_root)
    return report


_STATUS_TAG = {
    "landed": "✅ landed",
    "empty": "· nothing to do",
    "skipped-precondition": "⏭️ skipped (precondition unmet)",
    "red": "🛑 rolled back (suite went red) — chain halted",
    "halted": "⏸️ not reached (chain halted earlier)",
}


def _grade_line(report: ChainReport) -> str:
    """The single before→after health-grade line, or ``""`` when there is no grade
    to show (a dry run / uncomputable grade). Split out to keep the renderer under
    the complexity ceiling — the arrow/sign branching lives here, not in the loop."""
    if not (report.applied and report.grade_before >= 0 and report.grade_after >= 0):
        return ""
    d = report.grade_delta
    arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
    return (f"\n**Health grade: {report.grade_before} → {report.grade_after} "
            f"({'+' if d > 0 else ''}{d} {arrow})** — the chain's measured effect.")


def render_chain_markdown(report: ChainReport) -> str:
    """Render the explicit chain as a deterministic, CLOCK-FREE report.

    Lists each objective in chain order with its honest status (landed / empty /
    skipped-precondition / rolled-back / not-reached) and move count, the chain's
    green verdict, and the single before→after health grade. An empty chain (no
    objectives) renders an honest refusal. NO timestamp anywhere, so two runs on the
    same tree and chain render byte-identical."""
    if not report.objectives:
        return ("# Develop chain\n\n_Empty chain — pass an ordered list of "
                "objectives (e.g. `implement-stub → cover-gaps → "
                "strengthen-tests`) for the chain to run._\n")
    verb = "Landed" if report.applied else "Would land"
    verdict = "GREEN" if report.green else "HALTED"
    lines = [f"# Develop chain — {verdict}", "",
             f"_Explicit sequence: {' → '.join(report.objectives)} · per-step "
             "gated · deterministic · zero tokens_", "",
             f"{verb} **{report.verified_moves} verified move(s)** "
             f"({report.total_moves} total) across "
             f"{len(report.landed_objectives)} landed step(s)."]
    grade_line = _grade_line(report)
    if grade_line:
        lines.append(grade_line)
    if report.halted:
        lines.append(f"\n**Chain HALTED honestly at {report.halt_reason}** — no "
                     "partial fake-green; the landed steps held, the rest did not run.")
    lines += ["", "## Steps (source order)"]
    for i, s in enumerate(report.steps, 1):
        tag = _STATUS_TAG.get(s.status, s.status)
        detail = f" — {s.reason}" if s.reason else ""
        lines.append(f"{i}. `{s.objective}` · {tag} ({s.moves} move(s)){detail}")
    lines.append("")
    return "\n".join(lines)
