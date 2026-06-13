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


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract a line range into a named helper — the engine's own #1
    structural recommendation ("extract a shared helper") made executable.

    Data flow is computed automatically: names read from the surrounding scope
    become parameters, names defined and used afterward become return values.
    Test-verified with rollback, like every Apex change.
    """
    from app.execution.cross_file_rename import apply_rename
    from app.execution.extract_method import plan_extract

    target = Path(args.target).resolve() if args.target else _get_project_root()
    plan = plan_extract(str(target), args.file, args.start, args.end, args.name)
    label = f"extract {args.file}:{args.start}-{args.end} → `{args.name}()`"

    if plan.blockers:
        print(f"# Extract blocked: {label}\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if getattr(args, "dry_run", False):
        print(f"# Extract (dry run): {label}\n")
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
        print(f"✅ Extracted — {label} in {', '.join(res['changed_files'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'extract not applied')}")
    return 1


def cmd_inline(args: argparse.Namespace) -> int:
    """Inline a tiny single-use helper into its one call site — the inverse of
    `apex extract`.

    The helper's `return EXPR` is spliced over the single call (arguments
    substituted for parameters) and the now-dead definition is deleted. Every
    ambiguity is a blocker, never a guess. Test-verified with rollback, like
    every Apex change.
    """
    from app.execution.cross_file_rename import apply_rename
    from app.execution.inline_function import plan_inline

    target = Path(args.target).resolve() if args.target else _get_project_root()
    plan = plan_inline(str(target), args.function)
    label = f"inline `{args.function}()` into its call site"

    if plan.blockers:
        print(f"# Inline blocked: {label}\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if getattr(args, "dry_run", False):
        print(f"# Inline (dry run): {label} — "
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
        print(f"✅ Inlined — {label} in {', '.join(res['changed_files'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'inline not applied')}")
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




def cmd_rewrite(args: argparse.Namespace) -> int:
    """User-defined structural rewrite: `apex rewrite 'len($x) == 0' 'not $x'`.

    $name metavariables match any expression (the same name must capture the
    same text); applies project-wide, suite-verified with rollback.
    """
    from app.execution.cross_file_rename import apply_rename
    from app.execution.pattern_rewrite import plan_pattern_rewrite
    from app.execution.rewrite_rules import load_rules, save_rule

    target = Path(args.target).resolve() if args.target else _get_project_root()

    if getattr(args, "rules", False):
        rules = load_rules(str(target))
        print(f"# Rewrite rule book — {len(rules)} rule(s)")
        for r in rules:
            print(f"- **{r['name']}**: `{r['pattern']}` → `{r['replacement']}`")
        return 0

    if getattr(args, "all", False):
        rules = load_rules(str(target))
        if not rules:
            print("# Rewrite rule book is empty — save one with --save NAME")
            return 0
        failures = 0
        for r in rules:
            plan = plan_pattern_rewrite(str(target), r["pattern"], r["replacement"])
            if plan.blockers:
                failures += 1
                print(f"⛔ {r['name']}: {plan.blockers[0]}")
                continue
            if not plan.new_contents:
                print(f"✓ {r['name']}: holds (no drift)")
                continue
            res = apply_rename(str(target), plan,
                               verify=not getattr(args, "no_verify", False))
            if res.get("applied"):
                print(f"✅ {r['name']}: re-applied — {res['edits']} match(es) in "
                      f"{len(res['changed_files'])} file(s)"
                      + (" (tests pass)" if res.get("verified") else ""))
            else:
                failures += 1
                print(f"↩️ {r['name']}: {res.get('reason', 'not applied')}")
        return 1 if failures else 0

    pattern, replacement = args.pattern, args.replacement
    if getattr(args, "rule", ""):
        match = next((r for r in load_rules(str(target)) if r["name"] == args.rule), None)
        if match is None:
            print(f"⛔ no saved rule named '{args.rule}' — see `apex rewrite --rules`")
            return 1
        pattern, replacement = match["pattern"], match["replacement"]
    if not pattern or replacement is None:
        print("⛔ rewrite needs PATTERN and REPLACEMENT (or --rule NAME / --rules / --all)")
        return 1

    plan = plan_pattern_rewrite(str(target), pattern, replacement)
    label = f"`{pattern}` → `{replacement}`"

    if getattr(args, "save", "") and not plan.blockers:
        err = save_rule(str(target), args.save, pattern, replacement)
        print(f"⛔ {err}" if err else f"💾 rule '{args.save}' saved to the book")
        if err:
            return 1

    if plan.blockers:
        print(f"# Rewrite blocked: {label}\n")
        for b in plan.blockers:
            print(f"- ⛔ {b}")
        return 1
    if not plan.new_contents:
        print(f"# Rewrite: {label} — no match in the project")
        for w in plan.warnings:
            print(f"- ⚠️ {w}")
        return 0
    if getattr(args, "dry_run", False):
        print(f"# Rewrite (dry run): {label} — "
              f"{sum(plan.edits_by_file.values())} match(es) across {len(plan.new_contents)} file(s)\n")
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
        print(f"✅ Rewrote {label}: {res['edits']} match(es) in "
              f"{len(res['changed_files'])} file(s): {', '.join(res['changed_files'])}")
        if res.get("verified") is True:
            print("   tests pass — change is verified")
        for w in res.get("warnings", []):
            print(f"- ⚠️ {w}")
        return 0
    print(f"↩️ {res.get('reason', 'rewrite not applied')}")
    return 1


def cmd_teach(args: argparse.Namespace) -> int:
    """Learn a rewrite rule FROM EXAMPLES (deterministic anti-unification).

    `apex teach 'len(xs) == 0' 'not xs' 'len(a.b) == 0' 'not a.b'` — the
    differing subtrees become $metavariables; the rule self-checks against
    every example before it is shown. Never applies; preview + optional save.

    ``--from-git`` mines the last N single-line Python commits instead of
    requiring explicit examples — pairs where both sides parse as expressions
    are fed through the same anti-unification engine.
    """
    from app.execution.pattern_rewrite import plan_pattern_rewrite
    from app.execution.rewrite_rules import save_rule
    from app.execution.rule_learn import learn_rule

    target = Path(args.target).resolve() if args.target else _get_project_root()

    if getattr(args, "from_git", False):
        from app.engine.git_rule_miner import mine_git_pairs
        n = int(getattr(args, "commits", 50) or 50)
        pairs = mine_git_pairs(str(target), n)
        if not pairs:
            print(f"No single-line expression changes found in the last {n} commit(s).")
            return 0
        print(f"Mined {len(pairs)} single-line change(s) from the last {n} commit(s).")
        for b, a in pairs[:5]:
            suffix = " …" if len(pairs) > 5 and (b, a) == pairs[4] else ""
            print(f"  `{b}` → `{a}`{suffix}")
    else:
        examples = list(args.examples or [])
        if len(examples) % 2 != 0:
            print("⛔ teach takes BEFORE/AFTER pairs (an even number of expressions)")
            return 1
        pairs = list(zip(examples[::2], examples[1::2]))

    if not pairs:
        print("⛔ no example pairs to learn from")
        return 1

    rule = learn_rule(pairs)
    if not rule.ok:
        print("# Teach blocked\n")
        for b in rule.blockers:
            print(f"- ⛔ {b}")
        return 1

    print(f"# Learned rule: `{rule.pattern}` → `{rule.replacement}`")
    for n in rule.notes:
        print(f"- {n}")

    plan = plan_pattern_rewrite(str(target), rule.pattern, rule.replacement)
    if plan.new_contents:
        print(f"\nWould rewrite {sum(plan.edits_by_file.values())} match(es) "
              f"across {len(plan.new_contents)} file(s) — preview:\n")
        print("```diff")
        print(plan.render_diff().rstrip()[:4000])
        print("```")
    else:
        print("\nNo match in the project right now (the rule still guards the future).")

    if getattr(args, "save", ""):
        err = save_rule(str(target), args.save, rule.pattern, rule.replacement)
        print(f"⛔ {err}" if err else f"💾 rule '{args.save}' saved — apply with: "
              f"apex rewrite --rule {args.save}")
        if err:
            return 1
    return 0


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

    # extract — lift a line range into a helper (data flow auto-computed), verified
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract a line range from a function into a named helper "
             "(parameters/returns auto-computed from data flow, test-verified)",
    )
    extract_parser.add_argument("file", help="File containing the range (e.g. app/x.py)")
    extract_parser.add_argument("start", type=int, help="First line of the range (1-based)")
    extract_parser.add_argument("end", type=int, help="Last line of the range (inclusive)")
    extract_parser.add_argument("name", help="Name for the extracted helper function")
    extract_parser.add_argument("--target", default="", help="Target project root")
    extract_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                                help="Preview the unified diff without changing files")
    extract_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                                help="Skip the test verification run")
    extract_parser.add_argument("--json", action="store_true", help="Emit JSON")
    extract_parser.set_defaults(func=cmd_extract)

    # inline — fold a tiny helper into every call site project-wide, verified
    inline_parser = subparsers.add_parser(
        "inline",
        help="Inline a tiny helper (a single `return EXPR`) into every call site "
             "project-wide and delete the definition — the inverse of extract "
             "(test-verified)",
    )
    inline_parser.add_argument("function", help="Helper function to inline")
    inline_parser.add_argument("--target", default="", help="Target project root")
    inline_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                               help="Preview the unified diff without changing files")
    inline_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                               help="Skip the test verification run")
    inline_parser.add_argument("--json", action="store_true", help="Emit JSON")
    inline_parser.set_defaults(func=cmd_inline)

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

    # rewrite — user-defined structural rewrite with $metavariables, verified
    rw_parser = subparsers.add_parser(
        "rewrite",
        help="Structural rewrite with $x metavariables, project-wide (test-verified): "
             "apex rewrite 'len($x) == 0' 'not $x'",
    )
    rw_parser.add_argument("pattern", nargs="?", default="",
                           help="Expression pattern; $name matches any expression")
    rw_parser.add_argument("replacement", nargs="?", default=None,
                           help="Replacement template reusing the $name captures")
    rw_parser.add_argument("--save", default="", metavar="NAME",
                           help="Also save this rule to the project rule book")
    rw_parser.add_argument("--rule", default="", metavar="NAME",
                           help="Run a saved rule from the book instead")
    rw_parser.add_argument("--rules", action="store_true",
                           help="List the rule book and exit")
    rw_parser.add_argument("--all", action="store_true",
                           help="Run EVERY saved rule (each apply verified) — drift enforcement")
    rw_parser.add_argument("--target", default="", help="Target project root")
    rw_parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                           help="Preview the unified diff without changing files")
    rw_parser.add_argument("--no-verify", action="store_true", dest="no_verify",
                           help="Skip the test verification run")
    rw_parser.add_argument("--json", action="store_true", help="Emit JSON")
    rw_parser.set_defaults(func=cmd_rewrite)

    # teach — learn a rewrite rule from BEFORE/AFTER examples (never applies)
    teach_parser = subparsers.add_parser(
        "teach",
        help="Learn a $-pattern rule from BEFORE/AFTER example pairs (anti-unification, self-checked)",
    )
    teach_parser.add_argument("examples", nargs="*",
                              help="BEFORE AFTER [BEFORE2 AFTER2 ...] expression pairs "
                                   "(omit when using --from-git)")
    teach_parser.add_argument("--save", default="", metavar="NAME",
                              help="Save the learned rule to the project rule book")
    teach_parser.add_argument("--from-git", action="store_true", dest="from_git",
                              help="Mine single-line Python expression changes from git "
                                   "history instead of requiring explicit examples")
    teach_parser.add_argument("--commits", type=int, default=50, metavar="N",
                              help="How many recent commits to mine (default: 50, "
                                   "with --from-git)")
    teach_parser.add_argument("--target", default="", help="Target project root")
    teach_parser.set_defaults(func=cmd_teach)
