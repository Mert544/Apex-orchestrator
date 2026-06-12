"""Ideate-family command: the Idea Permutation Engine's CLI surface.

Extracted from the `app/cli.py` monolith — the engine's own #1 convergence
target (central dependency hub × high churn). Pure mechanical move:
`app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_ideate(args: argparse.Namespace) -> int:
    """Generate a permutation tree of development ideas from the codebase."""
    from app.engine.idea_permutation import (
        IdeaPermutationEngine,
        render_markdown,
        render_mermaid,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()

    # Plugins may contribute extra development operators to the alphabet.
    from app.plugins.registry import PluginRegistry

    plugins = PluginRegistry()
    plugins.load_all()
    extra_operators = plugins.idea_operators()

    engine = IdeaPermutationEngine(
        config={
            "max_total_ideas": args.max_ideas,
            "max_idea_depth": args.depth,
            "breadth": args.breadth,
            "min_relevance": args.min_relevance,
            "fractal_facets": getattr(args, "facets", False),
            "facet_depth": getattr(args, "facet_depth", 1),
            "adaptive_depth": getattr(args, "adaptive", False),
        },
        project_root=str(target),
        extra_operators=extra_operators,
    )
    report = engine.run(objective=args.objective or None)

    # --roadmap (without --actions): view the prioritized, phase-ordered plan.
    # With --actions, the roadmap instead drives the *order* of the action plan
    # below (Stabilize first), so this view-only branch is skipped.
    if getattr(args, "roadmap", False) and not getattr(args, "actions", False):
        from app.engine.idea_roadmap import (
            RoadmapSynthesizer,
            render_roadmap_markdown,
        )

        roadmap = RoadmapSynthesizer().build(report)
        snapshot_path = target / ".apex" / "roadmap-snapshot.json"

        # --diff: compare this roadmap against the last saved snapshot.
        if getattr(args, "diff", False):
            from app.engine.roadmap_history import (
                diff_roadmaps,
                load_snapshot,
                render_diff_markdown,
            )

            previous = load_snapshot(snapshot_path)
            if previous is None:
                print(
                    "[ideate] No saved roadmap snapshot to diff against. "
                    "Run with --save first."
                )
                return 1
            diff = diff_roadmaps(previous, roadmap)
            if args.json:
                print(json.dumps(diff.to_dict(), indent=2))
            else:
                print(render_diff_markdown(diff))
            return 0

        body = render_roadmap_markdown(roadmap)
        if args.json:
            print(json.dumps(roadmap.to_dict(), indent=2))
        else:
            print(body)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(body, encoding="utf-8")
            print(f"\n[ideate] Roadmap written to {out_path}")
        # --save: snapshot for future --diff comparisons.
        if getattr(args, "save", False):
            from app.engine.roadmap_history import snapshot_roadmap

            saved = snapshot_roadmap(roadmap, snapshot_path)
            print(f"\n[ideate] Roadmap snapshot saved to {saved}")
        return 0

    # --invest: the impact-vs-effort investment curve + diminishing-returns knee.
    if getattr(args, "invest", False):
        from app.engine.idea_investment import (
            investment_curve,
            render_investment_markdown,
        )

        points = investment_curve(report)
        if args.json:
            print(json.dumps([p.to_dict() for p in points], indent=2))
        else:
            print(render_investment_markdown(points))
        return 0

    # --budget: optimal portfolio of ideas for an effort budget (knapsack).
    if getattr(args, "budget", 0.0):
        from app.engine.idea_portfolio import (
            optimize_portfolio,
            render_portfolio_markdown,
        )

        portfolio = optimize_portfolio(report, float(args.budget))
        if args.json:
            print(json.dumps(portfolio.to_dict(), indent=2))
        else:
            print(render_portfolio_markdown(portfolio))
        return 0

    # --sequence: dependency-ordered execution plan (prerequisites first).
    if getattr(args, "sequence", False):
        from app.engine.idea_dependencies import (
            execution_order,
            render_execution_markdown,
        )

        steps = execution_order(report.ideas)
        if args.json:
            print(json.dumps([s.to_dict() for s in steps], indent=2))
        else:
            print(render_execution_markdown(steps))
        return 0

    # --pareto: the efficient frontier of ideas across impact/effort/value.
    if getattr(args, "pareto", False):
        from app.engine.idea_pareto import frontier_from_roadmap, render_pareto_markdown
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = RoadmapSynthesizer().build(report)
        points = frontier_from_roadmap(roadmap)
        if args.json:
            print(json.dumps([p.to_dict() for p in points], indent=2))
        else:
            print(render_pareto_markdown(points, total_ideas=len(report.ideas)))
        return 0

    # --shape: report on the shape/health of the tree the engine just produced.
    if getattr(args, "shape", False):
        from app.engine.idea_tree_shape import (
            analyze_tree_shape,
            render_tree_shape_markdown,
        )

        shape = analyze_tree_shape(report)
        if args.json:
            print(json.dumps(shape.to_dict(), indent=2))
        else:
            print(render_tree_shape_markdown(shape))
        return 0

    # --kind: list only ideas of a given kind (permutation/synthesis/pair),
    # value-sorted. A focused view onto what the engine surfaced.
    kind = getattr(args, "kind", "") or ""
    if kind and kind != "all":
        selected = sorted(
            (i for i in report.ideas if i.kind == kind),
            key=lambda n: n.value,
            reverse=True,
        )
        if args.json:
            print(json.dumps([i.to_dict() for i in selected], indent=2))
        else:
            print(f"# {kind} ideas for `{target}`  ({len(selected)} found)")
            for i in selected:
                caveat = f"  ⚠ {i.caveats[0]}" if i.caveats else ""
                print(f"- `{i.branch_path}` [{i.operator}] {i.title}  (v {i.value}){caveat}")
        return 0

    # Optionally bridge ideas into a supervised, never-applied action plan.
    action_plan = None
    apply_results = None
    if getattr(args, "actions", False):
        from app.engine.idea_action_bridge import (
            IdeaActionBridge,
            render_action_markdown,
        )

        bridge = IdeaActionBridge()
        _plan_mode = getattr(args, "mode", None) or "supervised"
        _draft = getattr(args, "draft", False) or getattr(args, "apply", False)
        if getattr(args, "roadmap", False):
            # Roadmap-ordered plan: apply Stabilize→Secure→Evolve→Refine, with an
            # optional --phase filter to act on a single phase.
            action_plan = bridge.plan_roadmap(
                report,
                phase=getattr(args, "phase", None) or None,
                mode=_plan_mode,
                top=args.top or None,
                draft=_draft,
                project_root=str(target),
            )
        else:
            action_plan = bridge.plan_tree(
                report,
                mode=_plan_mode,
                top=args.top or None,
                draft=_draft,
                project_root=str(target),
            )
        # Strictly opt-in apply: only when --apply is passed; gated by mode + safety.
        if getattr(args, "apply", False):
            apply_results = bridge.apply_plan(
                action_plan,
                str(target),
                mode=getattr(args, "mode", None) or "supervised",
                verify=getattr(args, "verify", False),
                max_apply=(args.max_apply or None) if getattr(args, "max_apply", 0) else None,
                commit=getattr(args, "commit", False),
            )

    if args.json:
        payload = report.model_dump()
        if action_plan is not None:
            payload["action_plan"] = action_plan.model_dump()
        if apply_results is not None:
            payload["apply_results"] = apply_results
        print(json.dumps(payload, indent=2))
    elif action_plan is not None:
        print(render_action_markdown(action_plan))
        if apply_results is not None:
            verify_note = " · verified" if apply_results.get("verify") else ""
            commit_note = (
                f" · committed {apply_results.get('committed', 0)}"
                if apply_results.get("commit") else ""
            )
            print(
                f"\n## Maintenance run (mode: {apply_results.get('mode')}{verify_note}{commit_note})\n"
                f"applied {apply_results['applied']} · rolled back "
                f"{apply_results['rolled_back']} · blocked {apply_results['blocked']} "
                f"of {apply_results['total_executable']} executable steps"
            )
            for r in apply_results["results"]:
                if r.get("rolled_back"):
                    status = "↩️"
                elif r.get("applied"):
                    status = "✅"
                else:
                    status = "⛔"
                detail = r.get("reason") or ", ".join(r.get("changed_files", []))
                if r.get("verified") is True:
                    detail += "  (tests pass)"
                if r.get("committed"):
                    detail += f"  [committed {r.get('commit_hash', '')}]"
                print(f"- {status} `{r['branch']}` {r['action']} — {detail}")
    else:
        print(render_markdown(report))
        if args.mermaid:
            print()
            print(render_mermaid(report))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if action_plan is not None:
            body = render_action_markdown(action_plan)
        else:
            body = render_markdown(report)
            if args.mermaid:
                body += "\n\n" + render_mermaid(report)
        out_path.write_text(body, encoding="utf-8")
        print(f"\n[ideate] Written to {out_path}")
    return 0


