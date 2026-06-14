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

    if getattr(args, "develop", False):
        from app.engine.brief_develop import (
            develop_brief,
            render_brief_develop_markdown,
        )

        result = develop_brief(
            str(target), branch_path=branch,
            subject=getattr(args, "subject", "") or "",
            max_steps=getattr(args, "max_steps", 25),
            verify=not getattr(args, "no_verify", False),
            apply=getattr(args, "apply", False),
            depth=args.depth, breadth=args.breadth, max_ideas=args.max_ideas,
            objective_focus=args.objective or "")
        if result is None:
            print("No design-level idea to develop (every idea is directly executable).")
            return 1
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(render_brief_develop_markdown(result))
            if not getattr(args, "apply", False):
                print("[brief] Dry run — re-run with --develop --apply to land the moves.")
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
    from app.engine.health_score import (
        grade, load_grade_snapshot, render_grade_diff_markdown,
        render_grade_markdown, save_grade_snapshot,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    h = grade(str(target))

    if getattr(args, "diff", False):
        old = load_grade_snapshot(str(target))
        if old:
            print(render_grade_diff_markdown(old, h))
        else:
            print("_No grade snapshot found — run `apex grade --save` first._\n")
            print(render_grade_markdown(h))
    elif args.json:
        print(json.dumps(h.to_dict(), indent=2))
    else:
        print(render_grade_markdown(h))

    if getattr(args, "save", False):
        save_grade_snapshot(str(target), h)
        print("[grade] Snapshot saved to .apex/grade-snapshot.json")

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




def cmd_duplication(args: argparse.Namespace) -> int:
    """Find copy-pasted code blocks across the project — fix the bug once, miss
    the other three copies. Reports each duplicated block and where it lives."""
    from app.engine.dedup import find_duplicates, render_duplicates_markdown

    target = Path(args.target).resolve() if args.target else _get_project_root()
    blocks = find_duplicates(str(target),
                             min_statements=getattr(args, "min_statements", 5),
                             min_occurrences=2)
    if args.json:
        print(json.dumps([b.to_dict() for b in blocks], indent=2))
    else:
        print(render_duplicates_markdown(blocks))
    return 0


def cmd_mutants(args: argparse.Namespace) -> int:
    """Measure test STRENGTH by mutation: seed faults into a module and see how
    many the suite kills vs. survives (survivors = where the tests are blind)."""
    from app.engine.mutation_tester import (
        mutation_score,
        render_mutation_markdown,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = mutation_score(
        str(target), args.module,
        max_mutants=args.max_mutants, verify_timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(render_mutation_markdown(result))
    return 0


def _objective_reachability() -> tuple[list[str], set[str]]:
    """Every registered develop objective, plus the subset the idea engine can
    actually PROPOSE (i.e. a value in ``FACET_OBJECTIVE_MAP``).

    Honest self-measurement: an objective the compiler knows how to pursue is
    still *unreachable* unless some facet phrase routes to it. Both sets are read
    live from the registries, so the answer tracks the code, never a snapshot.
    """
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    registered = sorted(set(available_objectives()))
    # Reachable == mapped AND actually registered (a map value naming a retired
    # objective is not a capability the compiler can deliver).
    reachable = set(FACET_OBJECTIVE_MAP.values()) & set(registered)
    return registered, reachable


def cmd_objectives(args: argparse.Namespace) -> int:
    """List every registered develop objective with whether the idea engine can
    reach it — surfacing objectives wired into the compiler but not yet routed
    from any facet phrase (``FACET_OBJECTIVE_MAP``)."""
    registered, reachable = _objective_reachability()

    if getattr(args, "json", False):
        print(json.dumps({
            "objectives": [
                {"name": name, "reachable": name in reachable}
                for name in registered
            ],
            "total": len(registered),
            "reachable": sorted(reachable),
            "unreachable": [n for n in registered if n not in reachable],
            "reachable_count": len(reachable),
            "unreachable_count": len(registered) - len(reachable),
        }, indent=2))
        return 0

    width = max((len(n) for n in registered), default=9)
    print(f"{'OBJECTIVE':<{width}}  REACH")
    print(f"{'-' * width}  -----")
    for name in registered:
        flag = "REACHABLE" if name in reachable else "unreachable"
        print(f"{name:<{width}}  {flag}")
    n, m = len(registered), len(reachable)
    print()
    print(f"{n} objectives, {m} reachable from the idea engine, "
          f"{n - m} not yet wired")
    return 0


def _read_proof_of_fix(root: Path) -> dict:
    """The proof-of-fix evidence trail, read defensively (missing/corrupt → {}).

    Mirrors the established readers in ``outcomes._last_proof`` /
    ``changelog._fixes_section``: ``.apex/proof-of-fix.json`` is the artifact a
    maintenance pass leaves behind, and a fresh repo simply has none.
    """
    path = root / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _trackrecord(root: Path) -> dict:
    """Assemble Apex's PROVEN track record on this repo from the two artifacts it
    already keeps: the proof-of-fix evidence trail (what landed, test-verified,
    with auto-rollback) and IdeaMemory's per-fix-type landing rates.

    Deterministic and defensive: both sources read from disk, missing files
    collapse to an empty record, and the per-type table is sorted by
    (success_rate desc, key asc) so the output is byte-stable across runs.
    """
    from app.engine.idea_memory import IdeaMemory

    proof = _read_proof_of_fix(root)
    totals = proof.get("totals") or {}
    fixes = proof.get("fixes") or []
    verified = sum(
        1 for f in fixes
        if isinstance(f, dict) and f.get("outcome") == "applied"
    )
    rolled_back = sum(
        1 for f in fixes
        if isinstance(f, dict) and f.get("outcome") == "rolled_back"
    )
    # Prefer the recorded totals when present; fall back to counting fixes.
    landed = int(totals.get("applied", verified) or 0) if totals else verified
    reverted = int(totals.get("rolled_back", rolled_back) or 0) if totals else rolled_back

    mem = IdeaMemory.load(root).summary()
    reliable = mem.get("most_reliable") or []
    risky = mem.get("least_reliable") or []

    # Merge the two reliability views into one deterministically ordered table:
    # every tracked fix-type once, best landing rate first, then key.
    by_key: dict[str, dict] = {}
    for row in [*reliable, *risky]:
        key = row.get("key", "")
        if key and key not in by_key:
            by_key[key] = {
                "key": key,
                "success_rate": float(row.get("success_rate", 0.0)),
                "samples": int(row.get("samples", 0)),
            }
    by_type = sorted(
        by_key.values(),
        key=lambda r: (-r["success_rate"], r["key"]),
    )

    has_record = landed > 0 or bool(by_type)
    return {
        "verified_fixes": landed,
        "rolled_back": reverted,
        "operators_tracked": int(mem.get("operators_tracked", 0) or 0),
        "by_type": by_type,
        "generated_at": proof.get("generated_at", ""),
        "has_record": has_record,
    }


_RELIABLE_FLOOR = 0.75   # ≥ this landing rate → lead with it
_RISKY_CEIL = 0.40       # ≤ this → expect blocks / rollbacks


def render_trackrecord_markdown(rec: dict) -> str:
    """The calm, factual, evidence-grounded track-record report."""
    if not rec["has_record"]:
        return ("# Apex track record\n\n"
                "no track record yet — run `apex maintain` to start building one.")

    landed = rec["verified_fixes"]
    reverted = rec["rolled_back"]
    lines = ["# Apex track record", ""]
    fix_word = "fix" if landed == 1 else "fixes"
    lines.append(
        f"Apex has landed **{landed} {fix_word}** on this repo — each one "
        "test-verified, with automatic rollback if the suite went red."
    )
    if reverted:
        rb_word = "attempt" if reverted == 1 else "attempts"
        lines.append(
            f"A further {reverted} {rb_word} were rolled back automatically "
            "rather than left broken — the safety net working as designed."
        )
    lines.append("")

    by_type = rec["by_type"]
    if by_type:
        lines += ["## By fix type", "",
                  "Landing rate per operator, measured on this codebase over "
                  "time (lead with the reliable; expect blocks on the risky):", ""]
        for row in by_type:
            pct = round(row["success_rate"] * 100)
            samples = row["samples"]
            s_word = "sample" if samples == 1 else "samples"
            if row["success_rate"] >= _RELIABLE_FLOOR:
                flag = "reliable — lead with this"
            elif row["success_rate"] <= _RISKY_CEIL:
                flag = "risky — expect blocks/rollbacks"
            else:
                flag = "mixed"
            lines.append(
                f"- `{row['key']}` — {pct}% landed over {samples} {s_word} "
                f"({flag})"
            )
        lines.append("")

    lines.append(
        "_Every number here is read from Apex's own evidence trail "
        "(`.apex/proof-of-fix.json`, `.apex/idea-memory.json`) — deterministic, "
        "zero-token, no model in the loop._"
    )
    return "\n".join(lines)


def cmd_trackrecord(args: argparse.Namespace) -> int:
    """Show Apex's PROVEN track record on this repo — how many fixes it has
    landed (test-verified, auto-rollback) and the per-fix-type landing rates it
    has measured over time. Reads only Apex's own artifacts; LLM-free."""
    target = Path(args.target).resolve() if args.target else _get_project_root()
    rec = _trackrecord(target)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(render_trackrecord_markdown(rec))
    return 0


def register_parsers(subparsers) -> None:
    """Register the insight family's subcommands: grade, impact, brief, dream,
    outcomes, recipes, changelog, explain, objectives."""
    # grade — single project health grade (A-F)
    grade_parser = subparsers.add_parser(
        "grade", help="Give the project a single health grade (A-F) with a breakdown",
    )
    grade_parser.add_argument("--target", default="", help="Target project root")
    grade_parser.add_argument("--min-score", type=int, default=0, dest="min_score",
                              help="Exit non-zero if the score is below this (CI gate)")
    grade_parser.add_argument("--save", action="store_true",
                              help="Snapshot the current grade to .apex/grade-snapshot.json")
    grade_parser.add_argument("--diff", action="store_true",
                              help="Compare to the saved snapshot and show what improved")
    grade_parser.add_argument("--json", action="store_true", help="Emit JSON")
    grade_parser.set_defaults(func=cmd_grade)

    # impact — function-level blast radius (who calls this, transitively)
    impact_parser = subparsers.add_parser(
        "impact",
        help="Show the blast radius of changing a function (its transitive callers)",
    )
    impact_parser.add_argument("function", help="Function/method name to analyze")
    impact_parser.add_argument("--target", default="", help="Target project root")
    impact_parser.add_argument("--json", action="store_true", help="Emit JSON")
    impact_parser.set_defaults(func=cmd_impact)

    # duplication — find copy-pasted code blocks across the project
    dup_parser = subparsers.add_parser(
        "duplication",
        help="Find copy-pasted code blocks across the project (extract shared helpers)",
    )
    dup_parser.add_argument("--target", default="", help="Target project root")
    dup_parser.add_argument("--min-statements", type=int, default=5, dest="min_statements",
                            help="Minimum block size (statements) to report (default 5)")
    dup_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dup_parser.set_defaults(func=cmd_duplication)

    # mutants — mutation testing: how strong is the suite for one module?
    mutants_parser = subparsers.add_parser(
        "mutants",
        help="Mutation testing: seed faults into a module and report how many the suite kills",
    )
    mutants_parser.add_argument("--module", required=True,
                                help="Module to mutate, relative to the project root (e.g. app/foo.py)")
    mutants_parser.add_argument("--target", default="", help="Target project root")
    mutants_parser.add_argument("--max-mutants", type=int, default=30, dest="max_mutants",
                                help="Cap the number of mutants verified (cost control)")
    mutants_parser.add_argument("--timeout", type=int, default=120,
                                help="Per-mutant pytest timeout in seconds")
    mutants_parser.add_argument("--json", action="store_true", help="Emit JSON")
    mutants_parser.set_defaults(func=cmd_mutants)

    # brief — a design-level idea as an actionable engineering brief
    brief_parser = subparsers.add_parser(
        "brief",
        help="Turn a design-level idea into an actionable work brief (facts, plan, done-when)",
    )
    brief_parser.add_argument("branch", nargs="?", default="",
                              help="Branch path (default: the top design-level idea)")
    brief_parser.add_argument("--target", default="", help="Target project root")
    brief_parser.add_argument("--subject", default="",
                              help="Target by MODULE PATH (stable across runs, "
                                   "unlike branch paths — prefer this with --save)")
    brief_parser.add_argument("--objective", default="", help="Optional focus")
    brief_parser.add_argument("--depth", type=int, default=2)
    brief_parser.add_argument("--breadth", type=int, default=4)
    brief_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas")
    brief_parser.add_argument("--save", action="store_true",
                              help="Snapshot the brief's evidence baseline for --check")
    brief_parser.add_argument("--check", action="store_true",
                              help="Re-measure a saved brief: evidence gone = item resolved")
    brief_parser.add_argument("--develop", action="store_true",
                              help="Run the brief's evidenced concerns as verified develop "
                                   "campaigns, then re-measure the burndown")
    brief_parser.add_argument("--apply", action="store_true",
                              help="With --develop: actually land the moves (default: dry run)")
    brief_parser.add_argument("--max-steps", type=int, default=25, dest="max_steps",
                              help="With --develop: cap moves per objective")
    brief_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                              help="With --develop: skip the per-move suite gate (faster, unsafe)")
    brief_parser.add_argument("--json", action="store_true", help="Emit JSON")
    brief_parser.set_defaults(func=cmd_brief)

    # dream — scheduled curation over Apex's own memory stores
    dream_parser = subparsers.add_parser(
        "dream",
        help="Review memory stores, extract patterns, curate, and write the dream digest",
    )
    dream_parser.add_argument("--target", default="", help="Target project root")
    dream_parser.add_argument("--curate", action="store_true",
                              help="Apply the curation (default only reports; inputs untouched)")
    dream_parser.add_argument("--json", action="store_true", help="Emit JSON")
    dream_parser.set_defaults(func=cmd_dream)

    # outcomes — grade the project against a user-written rubric (CI gate)
    outcomes_parser = subparsers.add_parser(
        "outcomes",
        help="Verify the project against YOUR rubric — per-criterion gaps, CI-ready exit code",
    )
    outcomes_parser.add_argument("--target", default="", help="Target project root")
    outcomes_parser.add_argument("--init", action="store_true",
                                 help="Write a starter rubric to .apex/outcomes.json")
    outcomes_parser.add_argument("--json", action="store_true", help="Emit JSON")
    outcomes_parser.set_defaults(func=cmd_outcomes)

    # recipes — the named, composable transform catalog
    recipes_parser = subparsers.add_parser(
        "recipes",
        help="List the transform catalog as named, composable recipes",
    )
    recipes_parser.add_argument("--json", action="store_true", help="Emit JSON")
    recipes_parser.set_defaults(func=cmd_recipes)

    # changelog — release notes from evidence
    changelog_parser = subparsers.add_parser(
        "changelog",
        help="Release notes from artifacts: commits, verified fixes, landed roadmap work, the grade",
    )
    changelog_parser.add_argument("--target", default="", help="Target project root")
    changelog_parser.add_argument("--out", default="", help="Write the Markdown to this path")
    changelog_parser.set_defaults(func=cmd_changelog)

    # objectives — the develop catalog and its idea-engine reachability
    objectives_parser = subparsers.add_parser(
        "objectives",
        help="List registered develop objectives and which the idea engine can reach",
    )
    objectives_parser.add_argument("--json", action="store_true", help="Emit JSON")
    objectives_parser.set_defaults(func=cmd_objectives)

    # trackrecord — Apex's proven, test-verified fix history on THIS repo
    trackrecord_parser = subparsers.add_parser(
        "trackrecord",
        help="Show Apex's proven track record on this repo: fixes landed (test-verified, "
             "auto-rollback) and per-fix-type landing rates over time",
    )
    trackrecord_parser.add_argument("--target", default="", help="Target project root")
    trackrecord_parser.add_argument("--json", action="store_true", help="Emit JSON")
    trackrecord_parser.set_defaults(func=cmd_trackrecord)

    # explain — show why an idea scored what it did
    explain_parser = subparsers.add_parser(
        "explain",
        help="Explain why an idea scored what it did (provenance, score, ROI, caveats)",
    )
    explain_parser.add_argument("branch", nargs="?", default="",
                                help="Branch path to explain (e.g. x.a.c); default: the top idea")
    explain_parser.add_argument("--target", default="", help="Target project root")
    explain_parser.add_argument("--objective", default="", help="Optional theme to focus on")
    explain_parser.add_argument("--depth", type=int, default=2, help="Permutation depth")
    explain_parser.add_argument("--breadth", type=int, default=4, help="Operators per idea")
    explain_parser.add_argument("--max-ideas", type=int, default=40, dest="max_ideas",
                                help="Idea budget")
    explain_parser.add_argument("--facets", action="store_true",
                                help="Include fractal facet ideas (for facet branch paths)")
    explain_parser.add_argument("--json", action="store_true", help="Emit JSON")
    explain_parser.set_defaults(func=cmd_explain)
