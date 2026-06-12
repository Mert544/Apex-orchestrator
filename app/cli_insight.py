"""Insight-family commands: explain, brief, dream, outcomes, recipes,
changelog, grade, impact — the commands that READ the organism.

Final slice of the `app/cli.py` monolith (2290 lines at its peak). Pure
mechanical move: `app.cli` re-exports every symbol, identity-guarded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_explain(args: argparse.Namespace) -> int:
    """Explain why a specific idea scored what it did — the engine's reasoning."""
    from app.engine.idea_explain import explain_idea, render_explanation_markdown
    from app.engine.idea_permutation import IdeaPermutationEngine

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = IdeaPermutationEngine(
        config={"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
                "breadth": args.breadth, "fractal_facets": getattr(args, "facets", False)},
        project_root=str(target),
    ).run(objective=args.objective or None)

    branch = getattr(args, "branch", "") or ""
    if not branch:
        # --top (default): explain the highest-value idea in the tree.
        if not report.ideas:
            print("[explain] No ideas generated for this target.")
            return 1
        branch = max(report.ideas, key=lambda i: i.value).branch_path

    exp = explain_idea(report, branch)
    if exp is None:
        print(f"[explain] No idea found at branch `{branch}`. "
              "Run `apex ideate` to see available branch paths.")
        return 1

    if args.json:
        print(json.dumps(exp.to_dict(), indent=2))
    else:
        print(render_explanation_markdown(exp))
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """A design-level idea rendered as an actionable engineering brief.

    ``--save`` snapshots the brief's evidence baseline; ``--check`` re-measures
    a saved brief against the CURRENT code — evidenced items whose evidence
    vanished are resolved by the scan, not by a checkbox (the burndown).
    """
    from app.engine.idea_brief import (
        build_brief,
        check_brief,
        render_brief_markdown,
        render_check_markdown,
        save_brief,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    branch = getattr(args, "branch", "") or ""

    if getattr(args, "check", False):
        if not branch:
            print("⛔ --check needs the BRANCH of a previously saved brief "
                  "(apex brief x.o --save)")
            return 1
        result = check_brief(str(target), branch)
        if result is None:
            print(f"⛔ no saved brief for `{branch}` — save one first: "
                  f"apex brief {branch} --save")
            return 1
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(render_check_markdown(result))
        return 0

    from app.engine.idea_permutation import IdeaPermutationEngine

    report = IdeaPermutationEngine(
        {"max_total_ideas": args.max_ideas, "max_idea_depth": args.depth,
         "breadth": args.breadth},
        project_root=str(target),
    ).run(objective=args.objective or None)
    brief = build_brief(report, branch_path=branch,
                        subject=getattr(args, "subject", "") or "")
    if brief is None:
        print("No design-level idea to brief (every idea is directly executable).")
        return 1
    if args.json:
        print(json.dumps(brief.to_dict(), indent=2))
    else:
        print(render_brief_markdown(brief))
    if getattr(args, "save", False):
        path = save_brief(brief, str(target))
        print(f"\n[brief] Evidence baseline saved to {path} — "
              f"measure progress later with: apex brief {brief.branch_path} --check")
    return 0


def cmd_dream(args: argparse.Namespace) -> int:
    """Review the organism's memory stores, extract patterns, curate, digest."""
    from app.engine.dream import dream, render_dream_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    report = dream(str(target), curate=getattr(args, "curate", False))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_dream_markdown(report))
        if report.digest_path:
            print(f"[dream] Digest written to {report.digest_path}")
    return 0


def cmd_outcomes(args: argparse.Namespace) -> int:
    """Grade the project against YOUR written rubric (per-criterion gaps)."""
    from app.engine.outcomes import (
        RUBRIC_REL,
        evaluate,
        init_rubric,
        render_outcomes_markdown,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if getattr(args, "init", False):
        path = init_rubric(str(target))
        print(f"[outcomes] Starter rubric written to {path} — edit the bar, "
              "then run `apex outcomes` (exits non-zero on gaps; CI-ready).")
        return 0
    report = evaluate(str(target))
    if report is None:
        print(f"⛔ no rubric at {RUBRIC_REL} — create one: apex outcomes --init")
        return 1
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_outcomes_markdown(report))
    return 0 if report.passed else 1


def cmd_recipes(args: argparse.Namespace) -> int:
    """List the named, composable transform catalog."""
    from app.execution.recipes import COMPOSITES, RECIPES, render_recipes_markdown

    if args.json:
        print(json.dumps({"recipes": [r.to_dict() for r in RECIPES.values()],
                          "composites": {k: list(v) for k, v in COMPOSITES.items()}},
                         indent=2))
    else:
        print(render_recipes_markdown())
    return 0


def cmd_changelog(args: argparse.Namespace) -> int:
    """Release notes written from artifacts, not memory."""
    from app.reporting.changelog import build_changelog

    target = Path(args.target).resolve() if args.target else _get_project_root()
    md = build_changelog(str(target))
    print(md)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"[changelog] Written to {out_path}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    """Give the project a single health grade (A–F) with a breakdown."""
    from app.engine.health_score import grade, render_grade_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    h = grade(str(target))
    if args.json:
        print(json.dumps(h.to_dict(), indent=2))
    else:
        print(render_grade_markdown(h))
    if getattr(args, "min_score", 0) and h.score < args.min_score:
        return 1
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    """Show the blast radius of changing a function: who transitively calls it."""
    from app.engine.call_graph import CallGraph, render_impact_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    graph = CallGraph.build(str(target))
    if args.json:
        print(json.dumps({
            "function": args.function,
            "definitions": [d.to_dict() for d in graph.definitions(args.function)],
            "direct_callers": [d.to_dict() for d in graph.direct_callers(args.function)],
            "blast_radius": [d.to_dict() for d in graph.blast_radius(args.function)],
        }, indent=2))
    else:
        print(render_impact_markdown(args.function, graph))
    return 0


