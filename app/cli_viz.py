"""CLI family: visual & planning exports.

The dependency/idea **canvas** (JSONCanvas), the idea-tree **HTML** report, the
change **blast-radius**, and the work **partition** planner — grouped into one
family so the top-level ``app.cli`` stays a thin composition root (these grew
out of it; the idea engine itself flagged the coupling). Each command resolves
its target the same way and registers through :func:`register_parsers`, matching
the other ``cli_*`` families.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.cli_common import _get_project_root


def cmd_canvas(args: argparse.Namespace) -> int:
    """Export a JSONCanvas (.canvas) file — the dependency graph or the idea tree."""
    from app.reporting.canvas_export import write_canvas

    target = Path(args.target).resolve() if args.target else _get_project_root()
    kind = getattr(args, "kind", "deps")
    if kind == "idea":
        from app.reporting.idea_canvas import idea_canvas
        canvas = idea_canvas(str(target))
        default_name = "apex-ideas.canvas"
    else:
        from app.reporting.canvas_export import dependency_canvas
        canvas = dependency_canvas(str(target))
        default_name = "apex.canvas"
    out_path = Path(args.out) if args.out else target / ".apex" / default_name
    write_canvas(canvas, out_path)
    print(
        f"[canvas] Written to {out_path} "
        f"({len(canvas['nodes'])} nodes, {len(canvas['edges'])} edges)"
    )
    return 0


def cmd_changed(args: argparse.Namespace) -> int:
    """Report the blast radius of a change — dependents, covering tests, scope cohesion."""
    import json as _json

    from app.engine.blast_radius import (
        blast_radius, changed_from_git, render_blast_radius_markdown,
    )
    target = Path(args.target).resolve() if args.target else _get_project_root()
    changed = changed_from_git(str(target), args.base)
    br = blast_radius(str(target), changed)
    if args.json:
        print(_json.dumps(br.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_blast_radius_markdown(br))
    return 0


def cmd_idea_html(args: argparse.Namespace) -> int:
    """Render the idea tree as a self-contained, shareable HTML report."""
    from app.reporting.idea_html import idea_tree_html
    target = Path(args.target).resolve() if args.target else _get_project_root()
    html = idea_tree_html(str(target))
    out_path = Path(args.out) if args.out else target / ".apex" / "apex-ideas.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[idea-html] Written to {out_path} ({len(html)} bytes)")
    return 0


def cmd_partition(args: argparse.Namespace) -> int:
    """Compute provably-disjoint parallel work groups for a set of planned tasks.

    Each ``--task name=fileA,fileB`` declares the files a task will touch; the
    output groups tasks that can run in parallel safely and flags those that must
    run serially (their files or blast-radii overlap)."""
    from app.engine.work_partition import (
        Task, partition_work, render_partition_markdown,
    )
    target = Path(args.target).resolve() if args.target else _get_project_root()
    tasks: list[Task] = []
    for spec in args.task or []:
        name, _, files = spec.partition("=")
        tasks.append(Task(name=name.strip(),
                          files=[f.strip() for f in files.split(",") if f.strip()]))
    print(render_partition_markdown(partition_work(str(target), tasks)))
    return 0


def register_parsers(subparsers) -> None:
    """Register the visual/planning family: canvas, changed, idea-html, partition."""
    # canvas — export the dependency graph or idea tree as a JSONCanvas (.canvas)
    canvas_parser = subparsers.add_parser(
        "canvas", help="Export the dependency graph as a JSONCanvas (.canvas) file"
    )
    canvas_parser.add_argument("--target", default="", help="Target project root")
    canvas_parser.add_argument(
        "--kind", choices=["deps", "idea"], default="deps",
        help="Which graph to export: 'deps' (dependency graph) or 'idea' (idea tree)"
    )
    canvas_parser.add_argument(
        "--out", default="", help="Output .canvas path (default <target>/.apex/apex[-ideas].canvas)"
    )
    canvas_parser.set_defaults(func=cmd_canvas)

    # changed — blast radius of a change (dependents, covering tests, cohesion)
    changed_parser = subparsers.add_parser(
        "changed", help="Report the blast radius of a change vs a git base"
    )
    changed_parser.add_argument("--target", default="", help="Target project root")
    changed_parser.add_argument(
        "--base", default="HEAD", help="Git base to diff against (default HEAD)"
    )
    changed_parser.add_argument("--json", action="store_true", help="Emit JSON")
    changed_parser.set_defaults(func=cmd_changed)

    # idea-html — render the idea tree as a self-contained HTML report
    idea_html_parser = subparsers.add_parser(
        "idea-html", help="Render the idea tree as a self-contained HTML report"
    )
    idea_html_parser.add_argument("--target", default="", help="Target project root")
    idea_html_parser.add_argument(
        "--out", default="", help="Output .html path (default <target>/.apex/apex-ideas.html)"
    )
    idea_html_parser.set_defaults(func=cmd_idea_html)

    # partition — compute disjoint parallel work groups for a planned wave
    partition_parser = subparsers.add_parser(
        "partition", help="Compute disjoint parallel work groups for planned tasks"
    )
    partition_parser.add_argument("--target", default="", help="Target project root")
    partition_parser.add_argument(
        "--task", action="append", metavar="NAME=FILES",
        help="A task as name=file1,file2 (repeatable)"
    )
    partition_parser.set_defaults(func=cmd_partition)
