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


@dataclass
class AssistResult:
    """The deterministic outcome of one :func:`assist` run — the buyer-facing unit.

    ``route`` names which organ answered (``"dream"`` / ``"grade"`` / ``"develop"``
    / ``"recommend"``), ``comprehension`` is the echoed understanding, ``applied``
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


# --- The DREAM ROUTE: "what should I build next?" ---------------------------

def _dream_route(request: str, comprehension: Comprehension,
                 target: str) -> AssistResult:
    """Route the next-work question into the DREAM core — read-only.

    Runs :func:`dream_develop` as a DRY RUN (writes nothing) and surfaces its
    ranked, value-led concrete directions, each already carrying objective +
    target + buyer-value + verification tier. The proactive-agent surface: a
    vague "what should I build?" becomes an executable, value-ordered plan."""
    from app.engine.dream_develop import dream_develop

    report = dream_develop(target, apply=False)
    contributions = report.contributions
    payload = {
        "goal": report.goal,
        "whole_tree": report.whole_tree,
        "modules": list(report.modules),
        "directions": [c.to_dict() for c in contributions],
        "total": len(contributions),
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


def _develop_route(request: str, comprehension: Comprehension, target: str,
                   apply: bool) -> AssistResult:
    """Plan + act on a develop request: value-led objectives, each gated.

    PLAN: value-led objective order (scope-restricted when a scope was named).
    ACT: each objective through :func:`_run_one_objective` (preview unless the
    write gate resolved on). EXPLAIN is deferred to :func:`render_assist_markdown`,
    which counts the landed / weak / blocked moves from the real results."""
    write = _resolve_apply(comprehension, apply)
    scope_hint = comprehension.scope
    scope_module = _resolve_scope_module(target, scope_hint)
    objectives = _scoped_objectives(comprehension)
    results = [_run_one_objective(target, obj, scope_module, write)
               for obj in objectives]
    payload = {
        "objectives": objectives,
        "capped": len(comprehension.objectives) > len(objectives),
        "scope": scope_hint,
        "scope_module": scope_module,
        "write": write,
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
           apply: bool = False) -> AssistResult:
    """Run the conversational loop on ``request`` against ``target``.

    UNDERSTAND (:func:`comprehend`) → BRANCH → ACT → EXPLAIN. Deterministic,
    zero-token, offline. SAFE by default: nothing is written unless ``apply`` is
    set AND comprehend's mode is patch-capable, and every develop write flows
    through the existing covered-only / suite-gated / auto-rollback compiler.

    The branch order is load-bearing: the proactive next-work question (the DREAM
    ROUTE) is detected first (it is a question that names develop work), then plain
    questions route to the grade, then a develop request with objectives runs them
    value-led, and anything unmapped gets the honest no-capability recommend."""
    target = str(target)
    comprehension = comprehend(request)

    # The proactive surface FIRST: a "what should I build next?" reads as a
    # question to comprehend, but it is the one question that names concrete
    # develop work — so it routes to the DREAM core, not the grade.
    if is_next_work_question(request):
        return _dream_route(request, comprehension, target)

    if comprehension.action == "question":
        return _grade_route(request, comprehension, target)

    # A develop request that matched real objectives → plan + act (gated).
    if comprehension.action == "develop" and comprehension.objectives:
        return _develop_route(request, comprehension, target, apply)

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
    if route in ("dream", "grade"):
        topic = {"dream": "what to build next",
                 "grade": "the project's health"}[route]
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


def _render_dream(result: AssistResult) -> list[str]:
    """The DREAM ROUTE body: the ranked value-led directions + the offer to act."""
    p = result.payload
    directions = p.get("directions", [])
    scope = ("whole-tree (the dream graduated no confluence)" if p.get("whole_tree")
             else "dream confluences: " + ", ".join(p.get("modules", [])))
    lines = ["## Plan — the DREAM core (what to build next)",
             f"_Ranked, value-led concrete directions · scope: {scope}._", ""]
    if not directions:
        lines += ["_Nothing landable yet — the chain refused honestly rather than "
                  "faking a move. Run `apex dream` to accrue confluences, or add "
                  "fillable stubs / untested code for it to land on._", ""]
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
    lines += [
        "", "## Next — one command to act on this",
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
    heading = ("Result — landed the verified moves" if write
               else "Result — preview (nothing written)")
    lines.append(f"## {heading}")
    if write:
        lines.append(f"**{verified} verified move(s)** on {files} file(s)"
                     + (f"; {weak} weak (uncovered)" if weak else "")
                     + (f"; {blocked} blocked." if blocked else "."))
    else:
        previewed = verified + weak
        lines.append(f"Preview: **{previewed} move(s)** would land across "
                     f"{files} file(s)"
                     + (f"; {blocked} blocked." if blocked else "."))
    lines.append("")
    lines += _render_develop_steps(results, write)
    lines += _render_develop_next(write, weak, objectives, scope)
    return lines


def _render_develop_steps(results: list[Any], write: bool) -> list[str]:
    """The per-objective move breakdown — each landed/previewed move, grounded.

    On an applied run each move carries its honest coverage tier (a test-COVERED
    move is "verified", else "uncovered"); on a PREVIEW nothing ran the suite, so
    each move is shown as "(preview)" rather than claiming a coverage verdict it
    did not measure (never-fake-green: a dry run proves nothing about coverage)."""
    lines: list[str] = []
    for r in results:
        steps = getattr(r, "steps", [])
        if not steps:
            continue
        lines.append(f"**`{r.objective}`** — {len(steps)} move(s):")
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
                         scope: str | None) -> list[str]:
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
    if write and not weak:
        lines.append("- Review with `git diff`; undo with `git checkout -- .`")
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
