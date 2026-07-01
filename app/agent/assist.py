"""``apex assist`` — the conversational UNDERSTAND→PLAN→ACT→EXPLAIN loop.

The capstone of Apex's LLM-LIKE surface, and still zero-token / offline /
deterministic / LLM-FREE: ONE command that reads a natural request, names the
plan, runs the right SHIPPED organ (safely, gated), and explains the result in a
grounded narrative that echoes what it understood. It is pure WIRING — it adds no
engine, registers no objective, and writes nothing of its own; every byte it
lands flows through the existing ``compile_objective`` (covered-only, suite-gated,
auto-rollback).

The flow:

1. **UNDERSTAND** — :func:`~app.intent.comprehension.comprehend` maps the request
   to a :class:`Comprehension` (action / objectives / mode / scope / confidence).
2. **BRANCH**
   - the *next-work* question ("what should I build next?") → **the DREAM ROUTE**:
     :func:`~app.engine.dream_develop.dream_develop` (dry-run) surfaces the ranked,
     value-led concrete directions (each carrying objective + target + buyer-value
     + verification tier) and OFFERS the one-command follow-ups. Read-only.
   - a *coupling/cycle/dependency* question ("why is this module so coupled?") →
     **the DEPS ROUTE**: the project's real import cycles + top fan-in hubs, read
     straight off the same dependency graph ``apex grade`` reads. Read-only.
   - any other question → :func:`~app.engine.health_score.grade` (the project's
     real health numbers). Read-only.
   - a develop request WITH objectives → value-led order, scope-restricted when a
     scope was named, each objective driven through ``compile_objective`` (preview
     unless the mode + ``--apply`` resolve to a write).
   - an unmappable / low-confidence request → an HONEST "no capability" answer plus
     a grounded recommend (the roadmap's best next moves).
3. **EXPLAIN** — :func:`render_assist_markdown` echoes the understanding, states the
   plan, narrates the GROUNDED result, and suggests the next concrete step.

The next-work intent is self-classified HERE from a small EN+TR phrase set (so this
loop stays independent of any new comprehend field). Determinism: the narrative is
a pure function of ``(request, target)`` — no clock, no randomness — modulo the
unified diff an applied develop run carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.intent.comprehension import Comprehension, comprehend

__all__ = [
    "AssistResult", "assist", "render_assist_markdown",
    "is_next_work_question", "NEXT_WORK_PHRASES",
    "is_coupling_question", "COUPLING_PHRASES",
]

# The "what should I build next?" intent — a small, deterministic EN+TR phrase
# table (a literal substring of the normalized request resolves it). Kept HERE so
# the loop never depends on a new ``comprehend`` field (Wave-2b independence): the
# proactive DREAM ROUTE is owned by this module's own self-classification.
NEXT_WORK_PHRASES: tuple[str, ...] = (
    # English
    "what should i build next", "what should i develop next",
    "what should i do next", "what should i build", "what should i develop",
    "what should i work on", "what to build next", "what to develop next",
    "what to work on", "what next", "what's next", "whats next",
    "highest value", "highest-value", "most valuable", "best next",
    "where should i start", "what would you build",
    # Turkish
    "ne geliştirmeli", "ne gelistirmeli", "sırada ne var", "sirada ne var",
    "ne yapmalı", "ne yapmaliyim", "ne üzerinde çalışmalı",
)

# How many ranked dream directions / develop objectives the narrative shows before
# it discloses the rest as a "+N more" tail — a stable cap, so a huge board never
# floods the answer and the count is deterministic.
_MAX_SHOWN = 5


def _norm(text: str) -> str:
    """Lowercased, apostrophe-stripped, single-spaced — the surface the phrase
    table matches against (so "What's next?" and "whats next" both resolve)."""
    low = " ".join(text.lower().replace("'", "").replace("’", "").split())
    return low


def is_next_work_question(request: str) -> bool:
    """True when ``request`` asks the proactive "what should I build next?" — a
    literal-substring match against :data:`NEXT_WORK_PHRASES`. Deterministic,
    table-driven, no fuzzy/LLM matching."""
    text = _norm(request)
    return any(phrase in text for phrase in NEXT_WORK_PHRASES)


# The "is this coupled / are there cycles?" intent — a second small, deterministic
# EN+TR phrase table (a literal substring of the normalized request resolves it).
# Kept HERE alongside :data:`NEXT_WORK_PHRASES` so the loop owns its own dependency-
# question self-classification and never edits a shared vocabulary file: a plain
# question about COUPLING / CYCLES / DEPENDENCIES routes to the DEPS ROUTE (the real
# import graph), not the generic health grade.
COUPLING_PHRASES: tuple[str, ...] = (
    # English
    "coupled", "coupling", "tightly coupled", "loosely coupled",
    "cycle", "cycles", "circular", "circular import", "circular dependency",
    "circular dependencies", "import cycle", "depends on", "depend on",
    "dependency", "dependencies", "fan-in", "fan in", "fanin",
    "fan-out", "fan out", "fanout", "interdependent", "entangled", "spaghetti",
    # Turkish
    "bağımlılık", "bagimlilik", "döngü", "dongu", "döngüsel", "dongusel",
    "bağ", "bagimli", "bağımlı", "sıkı bağ", "siki bag",
)


def is_coupling_question(request: str) -> bool:
    """True when ``request`` asks about COUPLING / CYCLES / DEPENDENCIES — a literal-
    substring match against :data:`COUPLING_PHRASES`. Deterministic, table-driven,
    no fuzzy/LLM matching (mirrors :func:`is_next_work_question`)."""
    text = _norm(request)
    return any(phrase in text for phrase in COUPLING_PHRASES)


@dataclass
class AssistResult:
    """The deterministic outcome of one :func:`assist` run — the buyer-facing unit.

    ``route`` names which organ answered (``"dream"`` / ``"grade"`` / ``"deps"`` /
    ``"develop"`` / ``"recommend"``), ``comprehension`` is the echoed understanding,
    ``applied``
    records whether any write landed, ``payload`` carries the route's structured
    result (for ``--json``), and ``narrative`` is the rendered, grounded answer."""

    request: str
    route: str
    comprehension: Comprehension
    applied: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "route": self.route,
            "applied": self.applied,
            "comprehension": self.comprehension.to_dict(),
            "payload": self.payload,
        }


# --- The resolved write gate -------------------------------------------------

def _resolve_apply(comprehension: Comprehension, apply: bool) -> bool:
    """Whether a develop run should WRITE: only when the caller passed ``--apply``
    AND comprehend's safety mode is patch-capable (``report`` always previews, so
    an explicit "just show me" pins a dry run even with ``--apply``). SAFE by
    default — a bare ``assist`` never writes."""
    if not apply:
        return False
    return comprehension.mode != "report"


def _resolve_commit(comprehension: Comprehension, apply: bool, commit: bool) -> bool:
    """Whether a landed develop run should be AUTO-COMMITTED — LEVEL 3.

    True only when the caller passed ``--commit`` AND ``--apply`` resolved to a
    write AND comprehend read the request as ``autonomous`` (an explicit
    "automatically…"/"otomatik…" phrasing — see ``_AUTONOMOUS_TRIGGERS``). NEVER
    on ``supervised`` (the safe default — a bare "add type hints" stays applied-
    but-uncommitted even with ``--commit``) or ``report`` (always a preview). This
    mirrors ``_resolve_apply``'s shape one gate further: apply is "may I write?",
    commit is "may I land it on the user's history without a human looking?" —
    only an explicitly autonomous request earns that."""
    return commit and apply and comprehension.mode == "autonomous"


# --- The DREAM ROUTE: "what should I build next?" ---------------------------

# The INTERACTIVITY BOUND the assist preview passes to ``dream_develop`` (it is
# the one caller that opts in; ``apex dream --land`` never does, so its exhaustive
# path stays byte-identical). ``apex assist`` has a HUMAN waiting, so the proactive
# "what should I build next?" preview must answer in seconds, not the ~7 min the
# unbounded chain takes on a multi-module project. The bound is the CHEAPEST one
# that keeps the leading value-led directions (see ``dream_develop`` for the
# profile): cap the per-confluence module fan-out to the top ``_DREAM_MAX_MODULES``
# by centrality, and skip the un-previewable mutation-testing objective (its
# generation runs the suite per mutant per module — irreducibly minutes — and is
# disclosed by the narrative, never silently dropped). Both are deterministic, so
# the same request renders byte-identical run to run.
_DREAM_MAX_MODULES = 12


def _dream_route(request: str, comprehension: Comprehension,
                 target: str) -> AssistResult:
    """Route the next-work question into the DREAM core — read-only.

    Runs :func:`dream_develop` as a DRY RUN (writes nothing) and surfaces its
    ranked, value-led concrete directions, each already carrying objective +
    target + buyer-value + verification tier. The proactive-agent surface: a
    vague "what should I build?" becomes an executable, value-ordered plan.

    BOUNDED for interactivity: the preview passes ``max_modules`` /
    ``preview_skip_mutation`` so a multi-module project answers in seconds while
    the leading value-led directions are preserved (see :data:`_DREAM_MAX_MODULES`
    and ``dream_develop``). The exhaustive ``apex dream --land`` path is unbounded
    and unchanged; only this read-only preview opts in. ``skipped`` records the
    directions the bound traded for latency, so the narrative stays HONEST."""
    from app.engine.dream_develop import (
        _PREVIEW_SKIP_OBJECTIVES,
        dream_develop,
    )

    report = dream_develop(target, apply=False, max_modules=_DREAM_MAX_MODULES,
                           preview_skip_mutation=True)
    contributions = report.contributions
    payload = {
        "goal": report.goal,
        "whole_tree": report.whole_tree,
        "modules": list(report.modules),
        "directions": [c.to_dict() for c in contributions],
        "total": len(contributions),
        # The directions the interactivity bound skipped (un-previewable mutation
        # objectives) — disclosed so the preview never hides what a full run lands.
        "skipped": sorted(_PREVIEW_SKIP_OBJECTIVES),
    }
    result = AssistResult(request=request, route="dream",
                          comprehension=comprehension, applied=False,
                          payload=payload)
    result.narrative = render_assist_markdown(result)
    return result


# --- The QUESTION route: grade the project ----------------------------------

def _grade_route(request: str, comprehension: Comprehension,
                 target: str) -> AssistResult:
    """Route a plain question to the project's real health grade — read-only.

    Narrates the grounded grade numbers (score / letter / per-area points lost /
    cheapest fixes) the :func:`~app.engine.health_score.grade` organ computes, so
    "is this well tested?" gets a real answer, not advice. Writes nothing."""
    from app.engine.health_score import grade

    health = grade(target)
    payload = {
        "score": health.score, "letter": health.letter,
        "components": [c.to_dict() for c in health.components],
        "fixes": list(health.fixes),
    }
    result = AssistResult(request=request, route="grade",
                          comprehension=comprehension, applied=False,
                          payload=payload)
    result.narrative = render_assist_markdown(result)
    return result


# --- The DEPS route: narrate the project's real cycles + fan-in hubs ----------

# How many top fan-in HUBS the deps narrative lists — the same display cap the
# DREAM/grade surfaces use (a stable head, never a flood, deterministic count).
_MAX_HUBS = 5


def _deps_route(request: str, comprehension: Comprehension,
                target: str) -> AssistResult:
    """Route a coupling/cycle/dependency question to the import graph — read-only.

    Runs the EXISTING dependency organ (:class:`DependencyGraphBuilder`, the same
    one ``apex grade``'s Architecture area reads) and narrates the GROUNDED numbers:
    the import CYCLES (``find_cycles`` — incl. indirect A->B->C->A) and the top
    fan-in HUBS (modules many others import, ranked by ``in_degree``). So "why is
    this module so coupled?" gets the project's real dependency shape, not a grade
    breakdown. Writes NOTHING.

    Both organ outputs are already deterministic (the graph is iterated in sorted
    order, cycles are de-duplicated by rotation, hubs are sorted by ``-in_degree``
    then path) — so the same ``(request, target)`` renders byte-identical. The build
    is best-effort (an unparseable tree yields an honest empty read, never a crash),
    mirroring the other read-only routes."""
    cycles, hubs, total_modules = _dependency_shape(target)
    payload = {
        "cycles": cycles,
        "hubs": hubs,
        "cycle_count": len(cycles),
        "modules": total_modules,
    }
    result = AssistResult(request=request, route="deps",
                          comprehension=comprehension, applied=False,
                          payload=payload)
    result.narrative = render_assist_markdown(result)
    return result


def _dependency_shape(target: str) -> tuple[list[list[str]], list[dict[str, Any]],
                                            int]:
    """``(cycles, hubs, module_count)`` off the project's import graph — read-only.

    ``cycles`` are :meth:`DependencyGraphBuilder.find_cycles` (each a module-path
    list ending back at its start); ``hubs`` are the top :data:`_MAX_HUBS` modules
    by fan-in (``in_degree`` > 0), each ``{"module", "fan_in"}``, ranked by
    ``-fan_in`` then path (the SAME order the profile's ``module_fanin`` uses).
    Best-effort: any build failure yields ``([], [], 0)`` so the narrative stays
    honest rather than raising."""
    try:
        from app.tools.dependency_graph import DependencyGraphBuilder

        builder = DependencyGraphBuilder(target)
        graph = builder.build()
        cycles = builder.find_cycles(limit=_MAX_HUBS)
    except Exception:
        return [], [], 0
    ranked = sorted(
        (n for n in graph.values() if n.in_degree > 0),
        key=lambda n: (-n.in_degree, n.path),
    )
    hubs = [{"module": n.path, "fan_in": n.in_degree} for n in ranked[:_MAX_HUBS]]
    return cycles, hubs, len(graph)


# --- The DEVELOP route: land (or preview) the named objectives ---------------

def _scoped_objectives(comprehension: Comprehension) -> list[str]:
    """The develop objectives in value-led order, capped at :data:`_MAX_SHOWN`.

    The comprehension already ranks objectives (exact name > specific phrase >
    family). We re-order by buyer value descending — the move a buyer values most
    is attempted first — with the comprehension rank as a stable tiebreak, then
    cap. Deterministic: a pure sort, no clock/random."""
    from app.engine.move_value import objective_value

    ranked = list(comprehension.objectives)
    order = {obj: i for i, obj in enumerate(ranked)}
    value_led = sorted(ranked, key=lambda o: (-objective_value(o), order[o]))
    return value_led[:_MAX_SHOWN]


def _resolve_scope_module(target: str, scope: str | None) -> str | None:
    """Map comprehend's bare scope HINT to a real module path the compiler accepts.

    Comprehend yields a bare name ("alpha" from "the alpha module") or a path
    ("app/x.py"); ``compile_objective(scope_module=...)`` matches the move's
    full relative target ("alpha.py:modernize" → module "alpha.py"). So a bare
    hint is resolved to the project's own module whose path/stem matches it (exact
    relative path first, then unique basename, then unique stem). Returns ``None``
    when the hint resolves to nothing OR is ambiguous — a safe whole-project run,
    never a wrong-module scope. Best-effort and read-only (no writes, no suite)."""
    if not scope:
        return None
    try:
        from app.engine.source_index import indexed_project

        rels = [rel for rel, _src in indexed_project(target).own_sources()]
    except Exception:
        return None
    norm = scope.replace("\\", "/").strip()
    if norm in rels:                                    # exact relative path
        return norm
    base = [r for r in rels if Path(r).name == (norm if norm.endswith(".py")
                                                else norm + ".py")]
    if len(base) == 1:                                  # unique basename
        return base[0]
    stem = [r for r in rels if Path(r).stem == Path(norm).stem]
    return stem[0] if len(stem) == 1 else None          # unique stem, else None


def _run_one_objective(target: str, objective: str, scope_module: str | None,
                       apply: bool) -> Any:
    """Drive ONE objective through the existing verified-with-rollback compiler.

    Pure reuse of :func:`compile_objective` (covered-only safe-apply, suite-gated,
    auto-rollback) — never a bypass. ``scope_module`` (already resolved to a real
    module path) confines the campaign to one module when the request named one;
    ``apply`` is the already-resolved write gate."""
    from app.engine.objective_compiler import compile_objective

    return compile_objective(target, objective=objective, apply=apply,
                             verify=True, scope_module=scope_module,
                             covered_only=apply)


# --- LEVEL 3: autonomous APPLY + AUTO-COMMIT (covered-verified-only) ---------

def _working_tree_clean(target: str) -> bool:
    """True iff ``target`` is a git repo with an empty ``git status --porcelain``.

    The AUTO-COMMIT precondition: a dirty tree may carry the user's own
    unrelated, unstaged/uncommitted work, and ``GitAutoCommit`` stages by
    EXPLICIT pathspec (never ``git add -A``) — but only committing when the tree
    started clean guarantees nothing pre-existing rides along, and gives an
    honest "nothing to commit but this run" history. A non-repo, or any git
    failure, counts as "not clean" (refuse to commit rather than guess)."""
    import subprocess

    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=target, capture_output=True, text=True, timeout=10)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=target, capture_output=True, text=True, timeout=10)
        return status.returncode == 0 and not status.stdout.strip()
    except Exception:
        return False


def _commit_result(target: str, result: Any) -> None:
    """Auto-commit ONE objective's landed steps, in place on ``result``.

    STRICT gate — stricter than ``covered_only`` alone: a step lands in
    ``result.steps`` once its green suite passed the covered-only withhold gate,
    but ``covered_only`` and ``coverage_verified`` are not the same predicate for
    every future caller, so this re-checks EVERY step's own
    :attr:`CompileStep.coverage_verified` (the tier-aware verdict: a Tier-1 move
    proven only at ``module`` coverage is NOT verified) before committing anything
    — one weak step withholds the WHOLE objective's commit (never a partial,
    file-by-file trust call). Leaves the change applied-on-disk either way; only
    the commit is withheld. No-op when ``result.steps`` is empty (nothing landed)."""
    from app.engine.git_auto_commit import GitAutoCommit

    steps = list(getattr(result, "steps", []))
    if not steps or not all(s.coverage_verified for s in steps):
        return
    changed_files = sorted({str(s.target).split(":", 1)[0] for s in steps})
    if not changed_files:
        return
    committer = GitAutoCommit(target)
    outcome = committer.commit(changed_files=changed_files,
                               finding=result.objective, action="develop")
    if outcome.success:
        result.committed = True
        result.commit_hash = outcome.commit_hash


def _develop_route(request: str, comprehension: Comprehension, target: str,
                   apply: bool, commit: bool = False) -> AssistResult:
    """Plan + act on a develop request: value-led objectives, each gated.

    PLAN: value-led objective order (scope-restricted when a scope was named).
    ACT: each objective through :func:`_run_one_objective` (preview unless the
    write gate resolved on). LEVEL 3: when the commit gate resolves on (an
    explicitly autonomous request, ``--apply --commit``, a clean tree) each
    landed objective is auto-committed via :func:`_commit_result` — but ONLY the
    steps a green suite genuinely vouches for at their risk tier; anything else
    stays applied-but-uncommitted for a human to review. EXPLAIN is deferred to
    :func:`render_assist_markdown`, which counts the landed / weak / blocked /
    committed moves from the real results."""
    write = _resolve_apply(comprehension, apply)
    should_commit = _resolve_commit(comprehension, write, commit)
    if should_commit and not _working_tree_clean(target):
        # Refuse to commit into a dirty tree — never sweep pre-existing
        # uncommitted work into Apex's auto-commit. The run still applies (write
        # already resolved), it just stays uncommitted, same as a bare --apply.
        should_commit = False
    scope_hint = comprehension.scope
    scope_module = _resolve_scope_module(target, scope_hint)
    objectives = _scoped_objectives(comprehension)
    results = [_run_one_objective(target, obj, scope_module, write)
               for obj in objectives]
    if should_commit:
        for r in results:
            _commit_result(target, r)
    payload = {
        "objectives": objectives,
        "capped": len(comprehension.objectives) > len(objectives),
        "scope": scope_hint,
        "scope_module": scope_module,
        "write": write,
        "commit": should_commit,
        "results": [r.to_dict() for r in results],
    }
    landed = any(getattr(r, "steps", None) for r in results)
    result = AssistResult(request=request, route="develop",
                          comprehension=comprehension, applied=write and landed,
                          payload=payload)
    result._results = results  # type: ignore[attr-defined]  # for the renderer
    result.narrative = render_assist_markdown(result)
    return result


# --- The HONEST fallback: no matching capability -----------------------------

def _quick_wins(target: str) -> list[dict[str, Any]]:
    """The roadmap's best next moves (high impact, low effort) — read-only.

    The same grounded recommend ``apex auto`` leads with: scan → ideate → roadmap,
    then surface the quick wins. Best-effort (a scan failure yields an empty list,
    so the honest no-capability answer still renders); writes nothing."""
    try:
        from app.engine.idea_permutation import IdeaPermutationEngine
        from app.engine.idea_roadmap import RoadmapSynthesizer

        engine = IdeaPermutationEngine(
            config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
            project_root=target)
        report = engine.run()
        roadmap = RoadmapSynthesizer().build(report)
    except Exception:
        return []
    return [{"title": i.title, "roi": i.roi} for i in roadmap.quick_wins]


def _recommend_route(request: str, comprehension: Comprehension,
                     target: str) -> AssistResult:
    """The honest fallback for an unmappable / low-confidence request — read-only.

    Says plainly that Apex has no capability matching the request (never fabricates
    an action), then routes to a grounded recommend (the roadmap's best next moves,
    the same surface ``apex auto`` reports). Writes nothing."""
    payload = {"quick_wins": _quick_wins(target)}
    result = AssistResult(request=request, route="recommend",
                          comprehension=comprehension, applied=False,
                          payload=payload)
    result.narrative = render_assist_markdown(result)
    return result


# --- The entry point ---------------------------------------------------------

def assist(request: str, target: str | Path = ".",
           apply: bool = False, commit: bool = False) -> AssistResult:
    """Run the conversational loop on ``request`` against ``target``.

    UNDERSTAND (:func:`comprehend`) → BRANCH → ACT → EXPLAIN. Deterministic,
    zero-token, offline. SAFE by default: nothing is written unless ``apply`` is
    set AND comprehend's mode is patch-capable, and every develop write flows
    through the existing covered-only / suite-gated / auto-rollback compiler.
    ``commit`` is LEVEL 3, one gate further: nothing is auto-committed unless
    ``apply`` resolved to a write AND comprehend read the request as explicitly
    ``autonomous`` AND every landed step is genuinely coverage-verified at its
    risk tier AND the working tree started clean (see :func:`_resolve_commit`)
    — a supervised-phrased request stays applied-but-uncommitted even with
    ``commit=True``.

    The branch order is load-bearing: the proactive next-work question (the DREAM
    ROUTE) is detected first (it is a question that names develop work), then a
    coupling/cycle/dependency question routes to the DEPS analysis (the real import
    graph) while every other plain question routes to the grade, then a develop
    request with objectives runs them value-led, and anything unmapped gets the
    honest no-capability recommend."""
    target = str(target)
    comprehension = comprehend(request)

    # The proactive surface FIRST: a "what should I build next?" reads as a
    # question to comprehend, but it is the one question that names concrete
    # develop work — so it routes to the DREAM core, not the grade.
    if is_next_work_question(request):
        return _dream_route(request, comprehension, target)

    if comprehension.action == "question":
        # A coupling/cycle/dependency question wants the real import graph (cycles
        # + fan-in hubs), not the generic health grade — every other question still
        # routes to the grade, byte-identically.
        if is_coupling_question(request):
            return _deps_route(request, comprehension, target)
        return _grade_route(request, comprehension, target)

    # A develop request that matched real objectives → plan + act (gated).
    if comprehension.action == "develop" and comprehension.objectives:
        return _develop_route(request, comprehension, target, apply, commit)

    # Unmappable / low-confidence / removal-of-additive → honest no-capability.
    return _recommend_route(request, comprehension, target)


# --- EXPLAIN: the grounded narrative -----------------------------------------

_TIER_TAG = {
    "verified": "✅ verified",
    "weak": "⚠️ weak (suite green but uncovered)",
    "no-suite": "⚠️ no-suite",
}


def _understood_line(c: Comprehension, route: str, scope: str) -> str:
    """The grounded one-line "I understood …" reading for the echo, per route.

    A question route (dream / grade) names the topic; a develop route lists the
    objectives; the recommend route is HONEST that the request mapped to no
    capability (it does NOT claim a develop or question reading it didn't earn)."""
    if route == "recommend":
        return (f"I **couldn't map this to a capability** (no matching develop "
                f"objective) — so I won't fabricate one ({c.mode} mode, "
                f"scope: {scope}).")
    if route in ("dream", "grade", "deps"):
        topic = {"dream": "what to build next",
                 "grade": "the project's health",
                 "deps": "the project's coupling / dependencies"}[route]
        return (f"I understood a **question** → {topic} "
                f"({c.mode} mode, scope: {scope}).")
    shown = ", ".join(c.objectives[:3]) or "(none)"
    more = f" (+{len(c.objectives) - 3} more)" if len(c.objectives) > 3 else ""
    return (f"I understood a **develop** request → {shown}{more} "
            f"({c.mode} mode, scope: {scope}).")


def _echo_lines(c: Comprehension, route: str) -> list[str]:
    """The ECHO header: the request, then the one-line "I understood …" reading.

    Quotes the request verbatim and states the understood action, the topic
    (objectives for a develop run, else the route), the safety mode, the scope,
    and the confidence — the transparency surface a buyer reads first."""
    scope = c.scope if c.scope else "whole project"
    return [
        "# Apex assist", "",
        f"**You asked:** «{c.request}»", "",
        _understood_line(c, route, scope),
        f"_Confidence: {c.confidence}._", "",
    ]


def _skipped_note(skipped: list[str]) -> list[str]:
    """The HONEST one-line disclosure of what the interactivity bound skipped.

    The proactive preview drops the un-previewable mutation-testing objective(s)
    so it answers in seconds; this names them and points to the exhaustive
    ``apex dream --land`` so the bound is transparent, never a silent omission.
    Empty when the bound skipped nothing (e.g. an unbounded caller)."""
    if not skipped:
        return []
    names = ", ".join(f"`{s}`" for s in skipped)
    return [f"_Bounded for an interactive answer: skipped {names} (mutation-"
            "testing, too slow to preview). `apex dream --land` runs the full "
            "chain._", ""]


def _render_dream(result: AssistResult) -> list[str]:
    """The DREAM ROUTE body: the ranked value-led directions + the offer to act."""
    p = result.payload
    directions = p.get("directions", [])
    skipped = p.get("skipped", [])
    scope = ("whole-tree (the dream graduated no confluence)" if p.get("whole_tree")
             else "dream confluences: " + ", ".join(p.get("modules", [])))
    lines = ["## Plan — the DREAM core (what to build next)",
             f"_Ranked, value-led concrete directions · scope: {scope}._", ""]
    if not directions:
        lines += ["_Nothing landable yet — the chain refused honestly rather than "
                  "faking a move. Run `apex dream` to accrue confluences, or add "
                  "fillable stubs / untested code for it to land on._", ""]
        lines += _skipped_note(skipped)
        return lines
    total = p.get("total", len(directions))
    lines.append(f"**{total} concrete direction(s)**, highest buyer-value first:")
    lines.append("")
    for i, c in enumerate(directions[:_MAX_SHOWN], 1):
        tag = _TIER_TAG.get(c.get("tier", ""), c.get("tier", ""))
        lines.append(f"{i}. `{c['objective']}` → {c['description']} "
                     f"— buyer-value {c.get('value', 0):.2f} · {tag}")
    if total > _MAX_SHOWN:
        lines.append(f"   …and {total - _MAX_SHOWN} more.")
    lines.append("")
    lines += _skipped_note(skipped)
    lines += [
        "## Next — one command to act on this",
        "- Land the whole value-led chain:  `apex dream --land --apply`",
        f"- Land just the top move:  "
        f"`apex develop {directions[0]['objective']} "
        f"--target {directions[0]['target'].split(':', 1)[0]}`",
        "",
    ]
    return lines


def _render_grade(result: AssistResult) -> list[str]:
    """The QUESTION-route body: the grounded grade breakdown + cheapest fixes."""
    p = result.payload
    lines = ["## Answer — the project's real health",
             f"**{p.get('letter', '?')}** ({p.get('score', 0)}/100), "
             "graded from the project's own structure.", "",
             "| Area | Points lost | Detail |", "|---|---:|---|"]
    for c in p.get("components", []):
        lines.append(f"| {c['name']} | −{c['points_lost']} | {c['detail']} |")
    lines.append("")
    fixes = p.get("fixes", [])
    if fixes:
        lines.append("## Next — cheapest ways to climb")
        lines += [f"- {f}" for f in fixes]
    else:
        lines.append("_Clean bill of health — nothing is costing points._")
    lines.append("")
    return lines


def _render_deps(result: AssistResult) -> list[str]:
    """The DEPS-route body: the real import cycles + top fan-in hubs, grounded.

    Lists the project's import CYCLES (or states "0 cycles — clean"), then the top
    fan-in HUBS with their dependent counts, then a NEXT suggestion — mirrors
    :func:`_render_grade`'s grounded, numbers-first style. Every figure is read
    straight off the dependency graph (no claimed numbers); empty/clean reads are
    stated plainly, never papered over."""
    p = result.payload
    cycles = p.get("cycles", [])
    hubs = p.get("hubs", [])
    modules = p.get("modules", 0)
    lines = ["## Answer — the project's real dependency shape",
             f"Read off the import graph across **{modules} module(s)** — the same "
             "graph the grade's Architecture area reads.", ""]
    lines += _render_deps_cycles(cycles)
    lines += _render_deps_hubs(hubs)
    lines += _render_deps_next(cycles, hubs)
    return lines


def _render_deps_cycles(cycles: list[list[str]]) -> list[str]:
    """The import-cycle section: each cycle as a path chain, or an honest clean read."""
    if not cycles:
        return ["**Import cycles:** 0 — clean (no circular imports detected).", ""]
    lines = [f"**Import cycles: {len(cycles)}** "
             "(circular imports — a change in one can ripple back through itself):",
             ""]
    for cyc in cycles:
        lines.append(f"- {' → '.join(f'`{m}`' for m in cyc)}")
    lines.append("")
    return lines


def _render_deps_hubs(hubs: list[dict[str, Any]]) -> list[str]:
    """The fan-in-hub section: the most depended-on modules + their dependent counts."""
    if not hubs:
        return ["**Top fan-in hubs:** none — no module is imported by another "
                "(a flat, uncoupled tree).", ""]
    lines = ["**Top fan-in hubs** (modules the most others depend on — coupling "
             "concentrates here):", ""]
    for i, h in enumerate(hubs, 1):
        dependents = h.get("fan_in", 0)
        lines.append(f"{i}. `{h['module']}` — {dependents} dependent module(s)")
    lines.append("")
    return lines


def _render_deps_next(cycles: list[list[str]],
                      hubs: list[dict[str, Any]]) -> list[str]:
    """The NEXT step for a deps read: break a cycle, else guard the biggest hub."""
    lines = ["## Next"]
    if cycles:
        lines.append("- Break a cycle by extracting the shared names into a new "
                     "leaf module both sides import (one-way edges, no loop).")
    if hubs:
        lines.append(f"- Add a regression test to the highest-fan-in hub "
                     f"(`{hubs[0]['module']}`) before changing it — many modules "
                     "ride on it.")
    if not cycles and not hubs:
        lines.append("- Nothing to untangle — the dependency tree is clean.")
    lines.append("")
    return lines


def _develop_counts(results: list[Any]) -> tuple[int, int, int, int]:
    """``(landed_verified, weak, blocked, files)`` summed across the campaigns —
    the honest never-fake-green split (only a test-COVERED move is "verified")."""
    verified = weak = blocked = 0
    files: set[str] = set()
    for r in results:
        for s in getattr(r, "steps", []):
            files.add(str(s.target).split(":", 1)[0])
            if getattr(s, "coverage_verified", False):
                verified += 1
            else:
                weak += 1
        blocked += len(getattr(r, "blocked", []))
    return verified, weak, blocked, len(files)


def _render_develop(result: AssistResult) -> list[str]:
    """The DEVELOP-route body: the planned objectives + the grounded result.

    Counts the landed / weak / blocked moves from the REAL compiler results
    (never a claimed number), lists each objective's per-move breakdown, and
    suggests the next concrete step (apply, or add tests to lift weak moves)."""
    p = result.payload
    results = getattr(result, "_results", [])
    write = p.get("write", False)
    objectives = p.get("objectives", [])
    plan = ", ".join(f"`{o}`" for o in objectives) or "(none)"
    capped = " (capped to the top moves)" if p.get("capped") else ""
    scope = p.get("scope")
    where = f" on `{scope}`" if scope else ""
    lines = [f"## Plan — {len(objectives)} objective(s){capped}, value-led{where}",
             plan, ""]
    verified, weak, blocked, files = _develop_counts(results)
    committed = sum(1 for r in results if getattr(r, "committed", False))
    heading = ("Result — landed the verified moves" if write
               else "Result — preview (nothing written)")
    lines.append(f"## {heading}")
    if write:
        lines.append(f"**{verified} verified move(s)** on {files} file(s)"
                     + (f"; {weak} weak (uncovered)" if weak else "")
                     + (f"; {blocked} blocked." if blocked else "."))
        # NEVER claim a commit that didn't happen: only disclosed when at least
        # one objective's steps were actually auto-committed (LEVEL 3).
        if committed:
            lines.append(f"**{committed} objective(s) auto-committed** — see the "
                         "per-move breakdown below for each commit hash.")
    else:
        previewed = verified + weak
        lines.append(f"Preview: **{previewed} move(s)** would land across "
                     f"{files} file(s)"
                     + (f"; {blocked} blocked." if blocked else "."))
    lines.append("")
    lines += _render_develop_steps(results, write)
    lines += _render_develop_next(write, weak, objectives, scope, committed)
    return lines


def _render_develop_steps(results: list[Any], write: bool) -> list[str]:
    """The per-objective move breakdown — each landed/previewed move, grounded.

    On an applied run each move carries its honest coverage tier (a test-COVERED
    move is "verified", else "uncovered"); on a PREVIEW nothing ran the suite, so
    each move is shown as "(preview)" rather than claiming a coverage verdict it
    did not measure (never-fake-green: a dry run proves nothing about coverage).
    A committed objective's header names its commit hash — "applied, not
    committed" is stated just as plainly when a landed objective did NOT commit,
    so the two outcomes are never conflated."""
    lines: list[str] = []
    for r in results:
        steps = getattr(r, "steps", [])
        if not steps:
            continue
        header = f"**`{r.objective}`** — {len(steps)} move(s)"
        if write:
            if getattr(r, "committed", False):
                header += f", committed `{r.commit_hash}`"
            else:
                header += ", applied — not committed"
        lines.append(header + ":")
        for s in steps:
            if not write:
                tag = "(preview)"
            else:
                tag = ("✅ verified" if getattr(s, "coverage_verified", False)
                       else "⚠️ uncovered")
            lines.append(f"- {s.description} · {tag}")
        lines.append("")
    return lines


def _render_develop_next(write: bool, weak: int, objectives: list[str],
                         scope: str | None, committed: int = 0) -> list[str]:
    """The NEXT step for a develop run: how to apply, or how to lift weak moves."""
    lines = ["## Next"]
    if not write:
        cmd = f"apex assist \"{objectives[0] if objectives else 'develop'}\""
        lines.append(f"- Re-run with `--apply` to land these: "
                     f"`{cmd} --apply --target <path>`")
    # The "uncovered" advice is meaningful ONLY on an applied run — a dry run never
    # ran the suite, so its moves aren't a coverage GAP, just unmeasured.
    if write and weak:
        lines.append("- Add tests that exercise the uncovered moves, then re-run — "
                     "a covered move lands as verified.")
    if write and not weak and not committed:
        lines.append("- Review with `git diff`; undo with `git checkout -- .`")
    if write and committed:
        lines.append("- Committed automatically — review with `git show`; "
                     "undo with `git revert`.")
    lines.append("")
    return lines


def _render_recommend(result: AssistResult) -> list[str]:
    """The honest no-capability body: say so plainly, then the grounded recommend."""
    p = result.payload
    lines = ["## Answer — no matching capability",
             f"I don't have a capability that matches «{result.request}», so I "
             "won't fabricate one. Here's a grounded read of the project instead.",
             ""]
    quick = p.get("quick_wins", [])
    if quick:
        lines.append("**Best next moves (high impact, low effort):**")
        lines += [f"- {q['title']}  (ROI {q['roi']})" for q in quick[:_MAX_SHOWN]]
    else:
        lines.append("_No quick wins surfaced right now — run `apex auto` for a "
                     "full assessment._")
    lines += ["", "## Next",
              "- `apex auto` — the full autonomous review + best next moves.",
              "- Rephrase naming a concrete change (e.g. \"add type hints\", "
              "\"sort imports\", \"remove dead code\").", ""]
    return lines


_ROUTE_BODY = {
    "dream": _render_dream,
    "grade": _render_grade,
    "deps": _render_deps,
    "develop": _render_develop,
    "recommend": _render_recommend,
}


def render_assist_markdown(result: AssistResult) -> str:
    """Render an :class:`AssistResult` as the grounded EXPLAIN narrative.

    ECHOES the understanding ("You asked: «…». I understood a <action> → …"),
    states the PLAN, narrates the GROUNDED result (real engine numbers — the
    ranked dream directions, the grade breakdown, or the landed/weak/blocked move
    counts), and suggests the NEXT concrete step. Deterministic: a pure function
    of the result (no clock/random), so two runs on the same fixture render
    byte-identical modulo an applied develop run's unified diff."""
    lines = _echo_lines(result.comprehension, result.route)
    body = _ROUTE_BODY.get(result.route)
    if body is not None:
        lines += body(result)
    return "\n".join(lines)
