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


def _confluence_entries(profile) -> list[dict]:
    """Normalize ``profile.confluence_modules`` into a stable, JSON-safe list.

    Each entry is ``{"module", "family_count", "families"}``; ``families`` is
    coerced to a sorted-as-stored list (the profiler already emits a sorted
    tuple). Returns ``[]`` for a missing/empty signal so callers can gate the
    whole section and keep no-confluence output byte-identical.
    """
    raw = getattr(profile, "confluence_modules", None) or []
    out: list[dict] = []
    for conv in raw:
        families = list(conv.get("families", ()) or ())
        out.append({
            "module": conv["module"],
            "family_count": int(conv.get("family_count", len(families))),
            "families": families,
        })
    return out


def _render_confluence_markdown(entries: list[dict]) -> str:
    """Render the convergence-hotspots development guidance section.

    Only called when ``entries`` is non-empty; the caller gates on that so the
    no-confluence path emits nothing additional.
    """
    lines = [
        "## Convergence hotspots",
        "",
        "These modules sit under the most independent pressures — they are the "
        "highest-leverage development targets. Stabilize and test them first.",
        "",
    ]
    for e in entries:
        fams = ", ".join(e["families"])
        lines.append(
            f"- `{e['module']}` — {e['family_count']} converging families: {fams}"
        )
    return "\n".join(lines)


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

    # Surface signal convergence (the seeder's #1 development target) prominently
    # in the default ideate view. ADDITIVE and gated: emitted only when the
    # profile names confluence modules, so the no-confluence path is unchanged.
    confluence = _confluence_entries(getattr(engine, "last_profile", None))

    if args.json:
        payload = report.model_dump()
        if action_plan is not None:
            payload["action_plan"] = action_plan.model_dump()
        if apply_results is not None:
            payload["apply_results"] = apply_results
        if confluence:
            payload["confluence"] = confluence
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
        if confluence:
            print()
            print(_render_confluence_markdown(confluence))

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




def register_parsers(subparsers) -> None:
    """Register the ideate family's subcommand: ideate."""
    ideate_parser = subparsers.add_parser(
        "ideate",
        help="Generate a permutation tree of development ideas from the codebase",
    )
    ideate_parser.add_argument("--target", default="", help="Target project root")
    ideate_parser.add_argument(
        "--objective", default="", help="Optional theme to focus ideas on"
    )
    ideate_parser.add_argument("--depth", type=int, default=2, help="Permutation depth")
    ideate_parser.add_argument(
        "--breadth", type=int, default=4, help="Operators applied per idea"
    )
    ideate_parser.add_argument(
        "--max-ideas", type=int, default=40, dest="max_ideas", help="Idea budget"
    )
    ideate_parser.add_argument(
        "--min-relevance",
        type=float,
        default=0.0,
        dest="min_relevance",
        help="Drop ideas below this relevance to the objective (0=off)",
    )
    ideate_parser.add_argument(
        "--actions",
        action="store_true",
        help="Bridge ideas into a supervised, never-applied action plan",
    )
    ideate_parser.add_argument(
        "--top", type=int, default=0, help="Limit action plan to top-N ideas by value"
    )
    ideate_parser.add_argument(
        "--draft",
        action="store_true",
        help="Draft real patch previews for executable steps (never applied)",
    )
    ideate_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply executable steps — gated by mode + safety gates (opt-in)",
    )
    ideate_parser.add_argument(
        "--verify",
        action="store_true",
        help="After applying, run tests and auto-rollback any step that breaks them",
    )
    ideate_parser.add_argument(
        "--commit",
        action="store_true",
        help="Auto-commit each applied step (autonomous mode only)",
    )
    ideate_parser.add_argument(
        "--max-apply",
        type=int,
        default=0,
        dest="max_apply",
        help="Cap how many steps a maintenance run applies (0 = no cap)",
    )
    ideate_parser.add_argument(
        "--mode",
        default="supervised",
        choices=["report", "supervised", "autonomous"],
        help="Execution mode for --apply (report cannot patch)",
    )
    ideate_parser.add_argument(
        "--mermaid", action="store_true", help="Also emit a Mermaid diagram"
    )
    ideate_parser.add_argument("--json", action="store_true", help="Emit JSON")
    ideate_parser.add_argument("--out", default="", help="Write markdown to this path")
    ideate_parser.add_argument(
        "--kind",
        default="",
        choices=["", "all", "permutation", "synthesis", "pair"],
        help="List only ideas of this kind (value-sorted)",
    )
    ideate_parser.add_argument(
        "--roadmap",
        action="store_true",
        help="Sequence ideas into a prioritized roadmap (Stabilize→Secure→Evolve→Refine)",
    )
    ideate_parser.add_argument(
        "--facets",
        action="store_true",
        help="Fractal zoom: expand the strongest leaves into self-similar sub-ideas",
    )
    ideate_parser.add_argument(
        "--facet-depth",
        type=int,
        default=1,
        dest="facet_depth",
        help="How many self-similar facet zoom levels to recurse (with --facets)",
    )
    ideate_parser.add_argument(
        "--shape",
        action="store_true",
        help="Analyze the shape/health of the generated idea tree",
    )
    ideate_parser.add_argument(
        "--pareto",
        action="store_true",
        help="Show the efficient frontier: non-dominated ideas across impact/effort/value",
    )
    ideate_parser.add_argument(
        "--adaptive",
        action="store_true",
        help="Adaptive depth: let high-value branches grow deeper (value-guided fractal)",
    )
    ideate_parser.add_argument(
        "--sequence",
        action="store_true",
        help="Dependency-ordered execution plan (prerequisites first) + critical path",
    )
    ideate_parser.add_argument(
        "--budget", type=float, default=0.0,
        help="Optimal idea portfolio for this effort budget (impact-maximizing knapsack)",
    )
    ideate_parser.add_argument(
        "--invest", action="store_true",
        help="Investment curve: impact achievable per effort budget + diminishing-returns knee",
    )
    ideate_parser.add_argument(
        "--phase",
        default="",
        choices=["", "Stabilize", "Secure", "Evolve", "Refine"],
        help="With --roadmap --actions: restrict the action plan to one phase",
    )
    ideate_parser.add_argument(
        "--save",
        action="store_true",
        help="With --roadmap: snapshot the roadmap to .apex/roadmap-snapshot.json",
    )
    ideate_parser.add_argument(
        "--diff",
        action="store_true",
        help="With --roadmap: show what changed since the last saved snapshot",
    )
    ideate_parser.set_defaults(func=cmd_ideate)
