"""Objective Compiler — goal-directed composition of verified transforms.

The deterministic search controller the research (GenProg, search-based
refactoring, AutoCodeRover, MAP-Elites) identifies as Apex's next leap. Where
``apex maintain`` applies whatever single smell-fix it finds, the compiler is
*goal-directed*: given an OBJECTIVE — a measurable fitness over the project —
and a pool of safe moves, it greedily applies the move that reduces the
objective metric, **each apply gated by the test suite with automatic
rollback**, until the objective is met or no improving move remains.

This is the classic propose→apply→measure→select loop with two parts Apex
already owns and the LLM-agent crowd bolts on: the *operators* are real,
test-verified transforms (not generated text), and the *oracle* is the project's
own suite (not a model's opinion). The loop itself is stdlib + the existing
``RenamePlan`` / ``apply_rename`` engine — no model, fully deterministic.

The first wired objective is **dead-parameter elimination**: every move is an
``apex signature drop`` of a never-read parameter — semantics-preserving, so the
fitness (the count of dead parameters) strictly decreases with each landed move.
The architecture is operator-agnostic: adding inline / extract / modernize move
generators is a single function each. The applied ordering is recorded to the
composition memory, so the organism learns which move *sequences* land.

Deterministic, stdlib-only; reuses the verified-with-rollback transform engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.cross_file_rename import RenamePlan

__all__ = [
    "Move", "CompileStep", "CompileResult",
    "dead_parameter_fitness", "inlinable_helper_fitness", "compile_objective",
    "dream_confluence_modules", "compile_from_dream",
    "render_compile_markdown", "render_from_dream_markdown",
]


@dataclass
class Move:
    """One candidate transform the compiler may apply to the current tree.

    ``build_plan`` is a thunk that re-derives the plan against the project's
    CURRENT state (line numbers shift as earlier moves land), so a move stays
    valid only as long as its precondition holds."""
    operator: str
    target: str
    description: str
    build_plan: Callable[[], RenamePlan]


@dataclass
class CompileStep:
    operator: str
    target: str
    description: str
    fitness_before: float
    fitness_after: float
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator, "target": self.target,
            "description": self.description,
            "fitness_before": self.fitness_before,
            "fitness_after": self.fitness_after, "verified": self.verified,
        }


@dataclass
class CompileResult:
    objective: str
    fitness_start: float
    fitness_end: float
    steps: list[CompileStep] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    applied: bool = False  # were any moves actually written (vs. dry run)?

    @property
    def improved(self) -> bool:
        return self.fitness_end < self.fitness_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "fitness_start": self.fitness_start,
            "fitness_end": self.fitness_end,
            "improved": self.improved,
            "moves_applied": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "blocked": self.blocked,
            "applied": self.applied,
        }


# --- Objective: dead-parameter elimination -----------------------------------

def _dead_params(project_root: str | Path) -> list[dict]:
    """The project's never-read parameters (the profiler's own scan)."""
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(str(project_root)).profile()
    return list(getattr(profile, "dead_params", []) or [])


def dead_parameter_fitness(project_root: str | Path) -> float:
    """Fitness = how many never-read parameters remain. Lower is better; the
    objective is reached at 0."""
    return float(len(_dead_params(project_root)))


def _dead_param_moves(project_root: str | Path) -> list[Move]:
    """One drop move per never-read parameter found in the current tree."""
    from app.execution.param_drop import plan_param_drop

    moves: list[Move] = []
    for dp in _dead_params(project_root):
        fn, param, mod = dp["function"], dp["param"], dp["module"]
        moves.append(Move(
            operator="drop_param",
            target=f"{mod}:{fn}({param})",
            description=f"drop never-read parameter `{param}` from {fn}() in {mod}",
            build_plan=lambda f=fn, p=param: plan_param_drop(str(project_root), f, p),
        ))
    return moves


# --- Objective: inline single-use helpers (reduce indirection) ---------------

def _inlinable_helpers(project_root: str | Path) -> list[dict]:
    """Tiny single-use helpers `apex inline` would cleanly fold away."""
    from app.execution.inline_function import suggest_inlines

    return list(suggest_inlines(str(project_root)))


def inlinable_helper_fitness(project_root: str | Path) -> float:
    """Fitness = how many single-use helpers remain to fold in. Lower is less
    indirection; the objective is reached at 0."""
    return float(len(_inlinable_helpers(project_root)))


def _guarded_inline_plan(project_root: str | Path, function: str) -> RenamePlan:
    """The inline plan for ``function``, but BLOCKED when it would fold the
    helper into a test/fixture file. A function whose only caller is a test is a
    public surface, not internal indirection — inlining it would dissolve real
    code into a test assertion (and empty its module). Safety over activity."""
    from app.engine.health_score import _is_fixture_path
    from app.execution.inline_function import plan_inline

    plan = plan_inline(str(project_root), function)
    if plan.new_contents and any(_is_fixture_path(rel) for rel in plan.new_contents):
        plan.blockers.append(
            "inlining would edit a test/fixture file — the helper is a public "
            "surface, not internal indirection; skipped")
        plan.new_contents.clear()
    return plan


def _inline_moves(project_root: str | Path) -> list[Move]:
    """One inline move per single-use helper found in the current tree."""
    moves: list[Move] = []
    for h in _inlinable_helpers(project_root):
        fn, mod = h["function"], h["module"]
        moves.append(Move(
            operator="inline",
            target=f"{mod}:{fn}()",
            description=f"inline the single-use helper `{fn}()` in {mod}",
            build_plan=lambda f=fn: _guarded_inline_plan(project_root, f),
        ))
    return moves


_OBJECTIVES: dict[str, tuple[Callable[[str | Path], float],
                             Callable[[str | Path], list[Move]]]] = {
    "dead-params": (dead_parameter_fitness, _dead_param_moves),
    "inline-helpers": (inlinable_helper_fitness, _inline_moves),
}


def _move_module(move: "Move") -> str:
    """The module a move targets (the part before ':' in its target)."""
    return move.target.split(":", 1)[0]


def compile_objective(project_root: str | Path, objective: str = "dead-params",
                      max_steps: int = 25, verify: bool = True,
                      apply: bool = True, scope_module: str | None = None) -> CompileResult:
    """Greedily compose verified moves toward ``objective``.

    Each iteration: regenerate candidate moves against the current tree, apply
    the first one that lands (suite-verified, auto-rolled-back on failure), and
    re-measure fitness. Stops at fixpoint (no candidate or none improving) or
    ``max_steps``. With ``apply=False`` it only reports the moves it WOULD make
    (no writes), measuring the projected fitness from the candidate count.

    ``scope_module`` confines the campaign to one module (a dream confluence,
    say): only moves targeting that module are composed, and fitness becomes the
    count of those scoped moves remaining — so the organism can clean up the one
    risky file its nightly dream flagged, not the whole project at once."""
    from app.execution.cross_file_rename import apply_rename

    if objective not in _OBJECTIVES:
        known = ", ".join(sorted(_OBJECTIVES))
        return CompileResult(objective=objective, fitness_start=0.0, fitness_end=0.0,
                             blocked=[f"unknown objective '{objective}' (known: {known})"])

    fitness, generate = _OBJECTIVES[objective]
    root = str(project_root)

    def candidates() -> list[Move]:
        moves = generate(root)
        if scope_module is not None:
            moves = [m for m in moves if _move_module(m) == scope_module]
        return moves

    def measure() -> float:
        # Scoped runs measure the local debt (remaining scoped moves); a global
        # run trusts the objective's own project-wide fitness function.
        return float(len(candidates())) if scope_module is not None else fitness(root)

    start = measure()
    result = CompileResult(objective=objective, fitness_start=start, fitness_end=start,
                           applied=apply)

    if not apply:
        # Dry run: list the moves available now (no writes, no suite runs).
        for mv in candidates()[:max_steps]:
            plan = mv.build_plan()
            if plan.blockers:
                result.blocked.append(f"{mv.target}: {plan.blockers[0]}")
            elif plan.new_contents:
                result.steps.append(CompileStep(
                    operator=mv.operator, target=mv.target, description=mv.description,
                    fitness_before=start, fitness_after=max(0.0, start - 1), verified=False))
        return result

    current = start
    for _ in range(max_steps):
        moves = candidates()
        if not moves:
            break
        advanced = False
        for mv in moves:
            plan = mv.build_plan()
            if plan.blockers or not plan.new_contents:
                if plan.blockers:
                    result.blocked.append(f"{mv.target}: {plan.blockers[0]}")
                continue
            res = apply_rename(root, plan, verify=verify)
            if not res.get("applied"):
                # Suite failed (rolled back) or nothing applied — not a valid move.
                if res.get("reason"):
                    result.blocked.append(f"{mv.target}: {res['reason']}")
                continue
            after = measure()
            result.steps.append(CompileStep(
                operator=mv.operator, target=mv.target, description=mv.description,
                fitness_before=current, fitness_after=after,
                verified=res.get("verified") is True))
            current = after
            advanced = True
            break  # re-generate against the new tree (line numbers shifted)
        if not advanced:
            break

    result.fitness_end = current
    _record_composition(result, root)
    return result


def _record_composition(result: CompileResult, project_root: str) -> None:
    """Credit the applied move ordering to the composition memory, so the engine
    learns which operator sequences land (here: drop_param>drop_param chains)."""
    if not result.steps:
        return
    from app.engine.idea_memory import IdeaMemory

    summary = {"results": [{"operator": s.operator, "applied": True} for s in result.steps]}
    try:
        IdeaMemory.learn_from(summary, project_root)
    except OSError:
        pass  # learning is best-effort; never fail a successful compile on it


def render_compile_markdown(result: CompileResult) -> str:
    """Render a compile campaign as a readable report."""
    verb = "Applied" if result.applied else "Would apply"
    lines = [f"# Objective compile — `{result.objective}`", ""]
    if result.blocked and not result.steps:
        lines.append(f"_No improving move available. Fitness: {result.fitness_start:g}._")
    lines.append(
        f"Fitness {result.fitness_start:g} → **{result.fitness_end:g}** "
        f"({verb.lower()} {len(result.steps)} verified move(s))."
    )
    lines.append("")
    for i, s in enumerate(result.steps, 1):
        tick = " ✅ tests pass" if s.verified else ""
        lines.append(f"{i}. {s.description} — {s.fitness_before:g}→{s.fitness_after:g}{tick}")
    if result.blocked:
        lines.append("")
        lines.append("## Blocked")
        for b in result.blocked[:10]:
            lines.append(f"- ⛔ {b}")
    lines.append("")
    return "\n".join(lines)


# --- Dream → action: act on the nightly structural discoveries ---------------

def dream_confluence_modules(project_root: str | Path) -> list[str]:
    """Modules the dream graduated as CONFLUENCES — files that carry many
    structural signals at once (high churn × hub × co-change). Read from the
    promotion store the dream writes (`.apex/dream-promotions.json`); these are
    the organism's hardest-won, multi-night discoveries about where the risk
    concentrates. Returns existing module paths only, sorted, deduplicated."""
    import json

    path = Path(project_root) / ".apex" / "dream-promotions.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        key = it.get("key", "") if isinstance(it, dict) else ""
        if key.startswith("confluence:"):
            module = key.split(":", 1)[1].strip()
            if module and (Path(project_root) / module).exists():
                out.append(module)
    return sorted(set(out))


def compile_from_dream(project_root: str | Path, objective: str = "dead-params",
                       max_steps: int = 25, verify: bool = True,
                       apply: bool = True) -> list[CompileResult]:
    """Run a scoped develop campaign on each module the dream flagged as a
    confluence — the closed loop: a 20-night structural discovery becomes a
    morning's verified cleanup, no human choosing the next move. One
    CompileResult per confluence module (empty list when the dream named none)."""
    results: list[CompileResult] = []
    for module in dream_confluence_modules(project_root):
        results.append(compile_objective(
            project_root, objective=objective, max_steps=max_steps,
            verify=verify, apply=apply, scope_module=module))
    return results


def render_from_dream_markdown(results: list[CompileResult],
                               modules: list[str]) -> str:
    """Render the dream-driven multi-module campaign."""
    if not modules:
        return ("# Develop from dream\n\n_The dream has graduated no confluence "
                "yet — run `apex dream --curate` over more nights first._\n")
    lines = [f"# Develop from dream — {len(modules)} confluence module(s)", "",
             "_The nightly dream flagged these files as risk confluences; "
             "here is the verified cleanup it composed for each._", ""]
    for module, result in zip(modules, results):
        lines.append(f"## `{module}`")
        lines.append(render_compile_markdown(result))
    return "\n".join(lines)
