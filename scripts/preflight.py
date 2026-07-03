#!/usr/bin/env python3
"""Pre-commit smoke gate — run ONLY the tests a change can actually reach.

The full gate costs ~40 minutes; most waves touch a handful of modules whose
impact is a few dozen test files. This computes the changed set (committed
delta vs origin plus the working tree, or explicit file arguments), maps it to
impacted test files via ``app.engine.test_impact.impacted_test_files``, and
runs ONE pytest over them with ``--timeout=300``. It is a smoke check, not the
gate: the full content-keyed gate (``scripts/gate_runner.py``) still runs
before every push.

Short-circuits (exit 0 with an explicit skip notice — go straight to the full
gate, running a partial smoke would be false confidence):

* a HUB file changed — a module whose import fan-in spans essentially the
  whole suite, so "impacted" would be everything anyway;
* more than ``IMPACT_LIMIT`` (120) test files are impacted — at that width the
  smoke run approaches full-gate cost without full-gate meaning;
* an app/ source changed but NO test imports reach it — the impact map has no
  opinion, so only the full gate can vouch for it.

Exit codes: 0 = proceed (green smoke, honest skip, or nothing to test);
1 = impacted tests RED (failures shown by pytest itself, uncaptured).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify
import wave_common as wc

ROOT = wc.ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.test_impact import impacted_test_files

# Hub modules whose import fan-in spans essentially the whole suite, so
# impact-scoping them is pointless — every CLI test imports app/cli*.py, and
# objective_compiler / idea_action_bridge sit at the develop core's center;
# tests/conftest.py reconfigures every test by definition. Hardcoded (with this
# comment as the drift-guard) because computing import fan-in at preflight time
# costs more than the decision saves; revisit if a new hub emerges.
HUB_FILES = frozenset({
    "app/engine/objective_compiler.py",
    "app/engine/idea_action_bridge.py",
    "tests/conftest.py",
})
IMPACT_LIMIT = 120


def is_hub(rel: str) -> bool:
    """Whether ``rel`` is a suite-wide hub (see HUB_FILES). ``app/cli.py`` and
    every ``app/cli_*.py`` sibling count; ``app/client.py`` would not."""
    if rel in HUB_FILES:
        return True
    p = Path(rel)
    return (p.parent.as_posix() == "app" and p.suffix == ".py"
            and (p.name == "cli.py" or p.name.startswith("cli_")))


def default_base() -> str:
    """The diff base: ``origin/<current branch>`` when origin has it, else
    ``origin/HEAD``, else '' (no base — working tree only)."""
    branch = wc.current_branch()
    for candidate in (f"origin/{branch}" if branch and branch != "HEAD" else "",
                      "origin/HEAD"):
        if candidate and wc.git_out("rev-parse", "--verify", candidate, check=False):
            return candidate
    return ""


def resolve_changed(base: str | None, files: list[str]) -> tuple[list[str], str]:
    """The changed set: explicit ``files`` if given, else the committed delta
    against the base plus every working-tree change. Returns (changed, base)."""
    if files:
        return sorted({Path(f).as_posix() for f in files}), "(explicit)"
    base = base or default_base()
    committed = (wc.git_out("diff", "--name-only", f"{base}...HEAD",
                            check=False).splitlines() if base else [])
    return sorted({p for p in committed if p} | wc.dirty_paths()), base or "(none)"


def decide(changed: list[str], impacted: list[str]) -> tuple[str, str]:
    """The preflight decision — pure, so the short-circuit table is directly
    unit-testable. Returns (decision, reason) with decision one of:
    ``empty`` (nothing to run, proceed), ``hub`` / ``wide`` / ``uncovered``
    (skip straight to the full gate), ``run`` (smoke the impacted files)."""
    if not changed:
        return "empty", "no changed files — nothing to smoke-test"
    hubs = sorted(r for r in changed if is_hub(r))
    if hubs:
        return "hub", f"hub file(s) changed ({', '.join(hubs)}) — impact spans the suite"
    if len(impacted) > IMPACT_LIMIT:
        return "wide", f"{len(impacted)} impacted test files > {IMPACT_LIMIT}"
    if not impacted:
        uncovered = sorted(r for r in changed
                           if r.startswith("app/") and r.endswith(".py"))
        if uncovered:
            return "uncovered", ("no test imports reach "
                                 f"{', '.join(uncovered[:5])} — impact unknown")
        return "empty", "changed files have no test impact (docs/tooling only)"
    return "run", f"{len(impacted)} impacted test file(s)"


def run_pytest(impacted: list[str]) -> int:
    """ONE pytest over the impacted files, uncaptured so failures are visible.
    ``--timeout=300`` outranks the pyproject default (CLI args follow addopts)
    because an impact-scoped run may cold-start heavier fixtures."""
    cmd = [sys.executable, "-m", "pytest", *impacted,
           "-q", "-p", "no:cacheprovider", "--timeout=300"]
    return subprocess.run(cmd, cwd=str(ROOT), env=verify._pytest_env()).returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Impact-scoped pre-commit smoke (the full gate still runs "
                    "before every push)")
    parser.add_argument("--base", default=None,
                        help="diff base (default: origin/<branch>, then origin/HEAD)")
    parser.add_argument("files", nargs="*",
                        help="explicit changed files (default: git diff + working tree)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    changed, base = resolve_changed(args.base, args.files)
    impacted: list[str] = []
    if changed and not any(is_hub(r) for r in changed):
        impacted = impacted_test_files(ROOT, [r for r in changed if r.endswith(".py")])
    decision, reason = decide(changed, impacted)
    print(f"preflight: base={base}, {len(changed)} changed file(s)", flush=True)
    if decision in ("hub", "wide", "uncovered"):
        print(f"preflight: SKIP smoke — {reason}; go straight to the full gate "
              "(python scripts/gate_runner.py)", flush=True)
        return 0
    if decision == "empty":
        print(f"preflight: {reason}", flush=True)
        return 0
    print(f"preflight: running {reason} (one pytest, --timeout=300)", flush=True)
    rc = run_pytest(impacted)
    print("preflight: GREEN — proceed to commit + gate" if rc == 0
          else "preflight: RED — fix before gating (failures above)", flush=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
