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



def cmd_signature(args: argparse.Namespace) -> int:
    """Signature family: ``drop`` removes an UNUSED parameter project-wide;
    ``add`` introduces one with a safe default (no call site can break).

    Positional callers of a dropped param block (no silent repositioning);
    a caller already passing an added param's keyword blocks. Apply is
    test-verified with rollback, like every Apex change.
    """
    from app.execution.cross_file_rename import apply_rename

    target = Path(args.target).resolve() if args.target else _get_project_root()
    if args.op == "keywordify":
        from app.execution.keywordify import plan_keywordify

        plan = plan_keywordify(str(target), args.function)
        label = f"convert positional calls of `{args.function}()` to keywords"
    elif args.op == "reorder":
        from app.execution.param_reorder import plan_param_reorder

        order = [s.strip() for s in (args.param or "").split(",") if s.strip()]
        plan = plan_param_reorder(str(target), args.function, order)
        label = f"reorder `{args.function}()` parameters to ({', '.join(order)})"
    elif args.op == "add":
        from app.execution.param_add import plan_param_add

        default = getattr(args, "default", "") or "None"
        plan = plan_param_add(str(target), args.function, args.param, default)
        label = f"add `{args.param}={default}` to `{args.function}()`"
    else:
        from app.execution.param_drop import plan_param_drop

        if not args.param:
            print(f"# Signature change blocked: `{args.op}` needs a PARAM argument")
            return 1
        plan = plan_param_drop(str(target), args.function, args.param)
        label = f"drop `{args.param}` from `{args.function}()`"

    if plan.blockers:
        print(f"# Signature change blocked: {label}\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if getattr(args, "dry_run", False):
        print(f"# Signature change (dry run): {label} — "
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
        print(f"✅ Signature changed — {label}: {res['edits']} edit(s) in "
              f"{len(res['changed_files'])} file(s): {', '.join(res['changed_files'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'signature change not applied')}")
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




def register_parsers(subparsers) -> None:
    """Register the refactor family's subcommands: rename, move, signature."""
    # rename — cross-file rename (definition + imports + call sites), verified
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a top-level function/class across the whole project (test-verified)",
    )
    rename_parser.add_argument("old", help="Current symbol name")
    rename_parser.add_argument("new", help="New symbol name")
    rename_parser.add_argument("--param", default="",
                               help="Rename a PARAMETER of this function instead "
                                    "(def site + body + keyword call sites)")
    rename_parser.add_argument("--target", default="", help="Target project root")
    rename_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                               help="Preview the unified diff without changing files")
    rename_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                               help="Skip the test verification run")
    rename_parser.add_argument("--json", action="store_true", help="Emit JSON")
    rename_parser.set_defaults(func=cmd_rename)

    # move — move/rename a module across the project (imports rewritten), verified
    move_parser = subparsers.add_parser(
        "move",
        help="Move/rename a module; every import in the project is rewritten (test-verified)",
    )
    move_parser.add_argument("src", help="Current module path (e.g. app/old.py)")
    move_parser.add_argument("dst", help="New module path (e.g. app/sub/new.py)")
    move_parser.add_argument("--target", default="", help="Target project root")
    move_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                             help="Preview the unified diff without changing files")
    move_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                             help="Skip the test verification run")
    move_parser.add_argument("--json", action="store_true", help="Emit JSON")
    move_parser.set_defaults(func=cmd_move)

    # signature — signature-family refactors (drop/add/keywordify), verified
    sig_parser = subparsers.add_parser(
        "signature",
        help="Change a function's signature project-wide: drop an unused parameter, "
             "add one with a safe default, or keywordify positional calls (test-verified)",
    )
    sig_parser.add_argument("op", choices=["drop", "add", "keywordify", "reorder"],
                            help="drop: remove a parameter the body never reads; "
                                 "add: introduce a parameter with a safe default; "
                                 "keywordify: rewrite positional call sites as keywords; "
                                 "reorder: change parameter order (callers must be keyword)")
    # NB: dest must not be "func" — that's the dispatch slot set_defaults uses.
    sig_parser.add_argument("function", help="Function whose signature changes")
    sig_parser.add_argument("param", nargs="?", default="",
                            help="Parameter to drop/add; for reorder, the full "
                                 "comma-separated new order (e.g. b,a,c)")
    sig_parser.add_argument("--default", default="None",
                            help="Default expression for `add` (e.g. 0, None, \"utf-8\")")
    sig_parser.add_argument("--target", default="", help="Target project root")
    sig_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                            help="Preview the unified diff without changing files")
    sig_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                            help="Skip the test verification run")
    sig_parser.add_argument("--json", action="store_true", help="Emit JSON")
    sig_parser.set_defaults(func=cmd_signature)
