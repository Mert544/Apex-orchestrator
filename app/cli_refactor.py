"""Refactor-family commands: cross-file rename and module move.

Extracted from the 1900-line `app/cli.py` monolith — the engine's own #1
convergence target (central dependency hub × high churn). Pure mechanical
move: `app.cli` re-exports every symbol, so the import surface is unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_common import _get_project_root

def cmd_rename(args: argparse.Namespace) -> int:
    """Cross-file rename: definition + imports + call sites, test-verified.

    With ``--param FUNC``, renames a *parameter* of FUNC instead: the def
    site, the body uses, and every keyword call site project-wide.
    """
    from app.execution.cross_file_rename import apply_rename, plan_rename

    target = Path(args.target).resolve() if args.target else _get_project_root()
    param_of = getattr(args, "param", "") or ""
    if param_of:
        from app.execution.param_rename import plan_param_rename

        plan = plan_param_rename(str(target), param_of, args.old, args.new)
    else:
        plan = plan_rename(str(target), args.old, args.new)

    if plan.blockers:
        print(f"# Rename blocked: `{args.old}` → `{args.new}`\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if getattr(args, "dry_run", False):
        print(f"# Rename (dry run): `{args.old}` → `{args.new}` — "
              f"{sum(plan.edits_by_file.values())} edit(s) across {len(plan.new_contents)} file(s)\n")
        print("```diff")
        print(plan.render_diff().rstrip())
        print("```")
        for w in plan.warnings:
            print(f"- ⚠️ {w}")
        return 0

    res = apply_rename(str(target), plan, verify=not getattr(args, "no_verify", False))
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res.get("applied") else 1
    if res.get("applied"):
        print(f"✅ Renamed `{args.old}` → `{args.new}`: {res['edits']} edit(s) in "
              f"{len(res['changed_files'])} file(s): {', '.join(res['changed_files'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'rename not applied')}")
    return 1



def cmd_move(args: argparse.Namespace) -> int:
    """Move/rename a module across the project — imports rewritten, test-verified."""
    from app.execution.move_module import apply_move, plan_move

    target = Path(args.target).resolve() if args.target else _get_project_root()
    plan = plan_move(str(target), args.src, args.dst)

    if plan.blockers:
        print(f"# Move blocked: `{args.src}` → `{args.dst}`\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if getattr(args, "dry_run", False):
        print(f"# Move (dry run): `{args.src}` → `{args.dst}` — "
              f"{sum(plan.edits_by_file.values())} import edit(s) across "
              f"{len(plan.new_contents)} file(s)\n")
        print("```diff")
        print(plan.render_diff().rstrip())
        print("```")
        for w in plan.warnings:
            print(f"- ⚠️ {w}")
        return 0

    res = apply_move(str(target), plan, verify=not getattr(args, "no_verify", False))
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res.get("applied") else 1
    if res.get("applied"):
        print(f"✅ Moved `{args.src}` → `{args.dst}`: {res['edits']} import edit(s) in "
              f"{len(res['changed_files'])} file(s)")
        if res.get("created"):
            print(f"   created: {', '.join(res['created'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'move not applied')}")
    return 1


