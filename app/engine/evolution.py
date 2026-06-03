"""Apex's self-improvement loop — apply, re-measure, prove progress.

Everything else in the engine *proposes*; this *converges*. `EvolutionLoop`
runs guarded maintenance in roadmap order, cycle after cycle, until it reaches a
**fixpoint** — the point where no further fix can be safely applied and verified.
Then it proves the needle moved: a before/after snapshot of the project's health
(security findings, mean ROI, executable work remaining) plus a roadmap **diff**
showing exactly which ideas were resolved.

It reuses the existing guarded executor (test-verified, auto-rollback, safety
gates), so a self-improvement run can never leave the project broken. The loop
itself is deterministic given a fixed project state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvolutionResult:
    cycles_run: int
    reached_fixpoint: bool
    applied: int
    rolled_back: int
    before: dict[str, Any]
    after: dict[str, Any]
    roadmap_diff: dict[str, Any]
    per_cycle: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "supervised"
    committed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvolutionLoop:
    """Iteratively improve a project toward a fixpoint, then prove the gain."""

    def __init__(
        self,
        project_root: str | Path,
        mode: str = "supervised",
        max_cycles: int = 3,
        max_apply_per_cycle: int = 5,
        verify: bool = True,
        commit: bool = False,
        objective: str | None = None,
    ) -> None:
        self.project_root = str(project_root)
        self.mode = mode
        self.max_cycles = max(1, max_cycles)
        self.max_apply_per_cycle = max(1, max_apply_per_cycle)
        self.verify = verify
        self.commit = commit
        self.objective = objective

    # --- measurement ---------------------------------------------------------

    def _build_report(self):
        from app.engine.idea_permutation import IdeaPermutationEngine

        return IdeaPermutationEngine(
            config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
            project_root=self.project_root,
        ).run(objective=self.objective or None)

    def _measure(self, report) -> dict[str, Any]:
        """A compact health snapshot of the current project state."""
        from app.engine.idea_action_bridge import IdeaActionBridge
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(report)
        plan = IdeaActionBridge().plan_roadmap(report, mode="report", project_root=self.project_root)
        try:
            from app.agents.skills import SecurityAgent

            findings = int(SecurityAgent().run(project_root=self.project_root).get("findings_count", 0) or 0)
        except Exception:
            findings = 0
        return {
            "security_findings": findings,
            "mean_roi": roadmap.stats.get("mean_roi", 0.0),
            "executable_fixes": plan.stats.get("executable_steps", 0),
            "total_ideas": report.stats.get("total_ideas", 0),
            "_roadmap": roadmap,  # internal; stripped from public dicts
        }

    @staticmethod
    def _public(measure: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in measure.items() if not k.startswith("_")}

    # --- the loop ------------------------------------------------------------

    def run(self) -> EvolutionResult:
        from app.engine.idea_action_bridge import IdeaActionBridge
        from app.engine.roadmap_history import diff_roadmaps, roadmap_to_snapshot

        bridge = IdeaActionBridge()
        first = self._measure(self._build_report())
        before_snapshot = roadmap_to_snapshot(first["_roadmap"])
        before = self._public(first)

        total_applied = 0
        total_rolled = 0
        total_committed = 0
        per_cycle: list[dict[str, Any]] = []
        reached_fixpoint = False
        cycles_run = 0

        for cycle in range(1, self.max_cycles + 1):
            cycles_run = cycle
            report = self._build_report()
            plan = bridge.plan_roadmap(
                report, mode=self.mode, project_root=self.project_root, draft=True
            )
            summary = bridge.apply_plan(
                plan, self.project_root, mode=self.mode,
                verify=self.verify, max_apply=self.max_apply_per_cycle, commit=self.commit,
            )
            applied = int(summary.get("applied", 0))
            rolled = int(summary.get("rolled_back", 0))
            committed = int(summary.get("committed", 0))
            total_applied += applied
            total_rolled += rolled
            total_committed += committed
            per_cycle.append({
                "cycle": cycle, "applied": applied, "rolled_back": rolled,
                "blocked": int(summary.get("blocked", 0)), "committed": committed,
            })
            # Fixpoint: a cycle that changed nothing means there's no further
            # safe, verifiable improvement to make.
            if applied == 0:
                reached_fixpoint = True
                break

        after_measure = self._measure(self._build_report())
        after = self._public(after_measure)
        diff = diff_roadmaps(before_snapshot, after_measure["_roadmap"])

        return EvolutionResult(
            cycles_run=cycles_run,
            reached_fixpoint=reached_fixpoint,
            applied=total_applied,
            rolled_back=total_rolled,
            before=before,
            after=after,
            roadmap_diff=diff.to_dict(),
            per_cycle=per_cycle,
            mode=self.mode,
            committed=total_committed,
        )


def render_evolution_markdown(result: EvolutionResult, project_root: str) -> str:
    """Render a self-improvement run as a before/after progress report."""
    b, a = result.before, result.after
    lines = [f"# Apex — self-improvement run on `{project_root}`", ""]
    fix = "reached a fixpoint" if result.reached_fixpoint else "hit the cycle cap"
    lines.append(
        f"Ran **{result.cycles_run}** cycle(s) ({fix}) · applied **{result.applied}** "
        f"fix(es) · rolled back {result.rolled_back}"
        + (f" · committed {result.committed}" if result.committed else "")
        + f" · mode {result.mode}"
    )
    lines.append("")

    def _delta(key: str, label: str, lower_is_better: bool = True) -> str:
        bv, av = b.get(key, 0), a.get(key, 0)
        arrow = "→"
        better = (av < bv) if lower_is_better else (av > bv)
        mark = "  ✅" if (av != bv and better) else ("  ⚠️" if av != bv else "")
        return f"- **{label}:** {bv} {arrow} {av}{mark}"

    lines.append("## Before → After")
    lines.append(_delta("security_findings", "Security findings", lower_is_better=True))
    lines.append(_delta("executable_fixes", "Open safe fixes", lower_is_better=True))
    # Mean ROI is shown neutrally: it often *falls* as the cheap high-ROI wins
    # get resolved first, which is a healthy sign rather than a regression.
    lines.append(f"- **Mean ROI:** {b.get('mean_roi', 0)} → {a.get('mean_roi', 0)}")
    lines.append("")

    rd = result.roadmap_diff
    resolved = rd.get("dropped", [])
    if resolved:
        lines.append("## ✅ Ideas resolved (no longer surface)")
        for c in resolved[:12]:
            lines.append(f"- {c['title']}")
        lines.append("")
    if result.per_cycle:
        lines.append("## Per cycle")
        for c in result.per_cycle:
            lines.append(
                f"- cycle {c['cycle']}: applied {c['applied']}, "
                f"rolled back {c['rolled_back']}, blocked {c['blocked']}"
            )
        lines.append("")
    return "\n".join(lines)
