#!/usr/bin/env python3
"""Merge train — safe-order integration of many agent worktree branches.

Integrating the parallel agent army by hand is the throughput bottleneck: a human
serially ``git cherry-pick``-s each worktree branch and re-runs the full
``scripts/verify.py`` gate, resolving fallout as it appears. This script automates
the *safe order* of that integration so the easy, conflict-free branches land
first and the genuinely-overlapping ones are surfaced (never auto-resolved) for a
human.

The ordering is least-friction first:

  * Branches that ONLY add brand-new files — no overlap with HEAD's tracked files
    and no overlap with each other — cherry-pick cleanly, so they go FIRST (sorted
    by ref name for determinism).
  * Branches that touch shared/existing files go AFTER, grouped with
    :func:`app.engine.work_partition.partition_work` (one ``Task(name=ref,
    files=changed)`` per ref). Refs that land in their own singleton partition are
    flagged parallel-safe; refs sharing a partition are flagged "ordered/manual
    merge" because their change blast-radii overlap.

Integration walks the computed order and ``git cherry-pick``-s each ref. On a
conflict it ``git cherry-pick --abort``-s and RECORDS the ref as
"conflicted — needs manual merge" (it NEVER force-resolves), then carries on with
the remaining refs. After all picks, unless ``--no-gate``, it runs
``scripts/verify.py`` and captures the gate result. ``--dry-run`` prints only the
plan (order, parallel/serial grouping, per-ref files) and integrates nothing.

Exit code is non-zero if any ref conflicted OR the gate went red — drop it into a
human-supervised integration loop.

    python scripts/merge_train.py worktree-agent-aaa worktree-agent-bbb
    python scripts/merge_train.py --auto                 # discover ahead-of-HEAD branches
    python scripts/merge_train.py --auto --dry-run       # plan only, change nothing
    python scripts/merge_train.py --auto --no-gate       # skip the verify.py gate
    python scripts/merge_train.py --base origin/main bbb # diff/merge-base against a ref

Deterministic, stdlib-only (``subprocess`` + ``argparse``), offline, and safe to
run from the repo root.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify.py"

# Local branches named like this are the per-agent worktree branches that
# ``--auto`` integrates (matches the repo's ``worktree-agent-*`` convention).
_AUTO_PREFIX = "worktree-agent-"


@dataclass
class RefPlan:
    """The integration plan for one ref: its files and where it sits in the order.

    ``changed`` is the sorted set of files the ref touches relative to the merge
    base. ``adds_only`` is True when none of those files already exist in the base
    tree (a clean, additive branch). ``group`` is the parallel-grouping verdict:
    ``"add"`` (additive, goes first), ``"parallel"`` (touches shared files but is
    disjoint from every other ref), or ``"serial"`` (overlaps another ref and so
    needs an ordered/manual merge). ``peers`` are the other refs sharing its serial
    partition (empty unless ``group == "serial"``).
    """

    ref: str
    changed: list[str] = field(default_factory=list)
    adds_only: bool = False
    group: str = "add"
    peers: list[str] = field(default_factory=list)


@dataclass
class RefResult:
    """The outcome of attempting to integrate one ref."""

    ref: str
    status: str  # "merged" | "conflicted"
    overlaps: list[str] = field(default_factory=list)


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a git command in the repo root, capturing text output."""
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=check,
    )


def _git_ok(*args: str) -> tuple[bool, str]:
    """Run a git command; return (success, combined stdout+stderr trimmed)."""
    proc = _git(*args)
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def merge_base(base: str, ref: str) -> str:
    """The merge base SHA of ``base`` and ``ref``, or ``base`` itself as a fallback.

    A missing merge base (unrelated histories) falls back to diffing against
    ``base`` directly so the tool degrades gracefully rather than crashing.
    """
    proc = _git("merge-base", base, ref)
    mb = proc.stdout.strip()
    return mb or base


def changed_files(base: str, ref: str) -> list[str]:
    """Files ``ref`` changes relative to its merge base with ``base`` (sorted)."""
    mb = merge_base(base, ref)
    proc = _git("diff", "--name-only", f"{mb}..{ref}")
    files = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return sorted(set(files))


def tracked_files(base: str) -> set[str]:
    """The set of files tracked in the ``base`` tree (for add-only detection)."""
    proc = _git("ls-tree", "-r", "--name-only", base)
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def discover_auto_refs(base: str) -> list[str]:
    """Local ``worktree-agent-*`` branches that are ahead of ``base`` (sorted).

    A branch is "ahead" when it has at least one commit not in ``base`` — i.e. it
    actually carries work to integrate. The base ref itself is never returned.
    """
    proc = _git("for-each-ref", "--format=%(refname:short)", "refs/heads/")
    names = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    refs: list[str] = []
    for name in names:
        if not name.startswith(_AUTO_PREFIX):
            continue
        # `<base>..<name>` counts commits on name but not on base; >0 means ahead.
        count = _git("rev-list", "--count", f"{base}..{name}").stdout.strip()
        if count and count != "0":
            refs.append(name)
    return sorted(set(refs))


def _add_candidates(
    refs: list[str], files_by_ref: dict[str, list[str]], tracked: set[str]
) -> dict[str, set[str]]:
    """Refs whose every changed file is brand-new versus ``tracked`` (as file sets).

    A ref qualifies only if it changes at least one file and none of its changed
    files already exist in the base tree — the precondition for being add-only.
    """
    return {
        r: set(files_by_ref[r])
        for r in refs
        if files_by_ref[r] and all(f not in tracked for f in files_by_ref[r])
    }


def _add_only_refs(candidates: dict[str, set[str]]) -> set[str]:
    """Add-only candidates that introduce no path another candidate also creates.

    Two add-only branches creating the same new file would still collide, so a
    candidate sharing a new path with any other candidate is demoted (dropped here)
    into the partitioned set.
    """
    return {
        r
        for r, fs in candidates.items()
        if not any(o != r and fs & candidates[o] for o in candidates)
    }


def _serial_peers(
    rest: list[str], files_by_ref: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Map each overlapping ref to its sorted serial peers via :func:`partition_work`.

    Refs alone in their partition are omitted (they are parallel-safe); only refs
    sharing a partition appear, each mapped to the other refs in that partition.
    """
    from app.engine.work_partition import Task, partition_work

    peers: dict[str, list[str]] = {}
    if not rest:
        return peers
    tasks = [Task(name=r, files=files_by_ref[r]) for r in rest]
    for part in partition_work(ROOT, tasks):
        if len(part.tasks) > 1:
            for t in part.tasks:
                peers[t] = sorted(x for x in part.tasks if x != t)
    return peers


def _build_plans(
    add_only: set[str],
    rest: list[str],
    files_by_ref: dict[str, list[str]],
    serial_peers: dict[str, list[str]],
) -> list[RefPlan]:
    """Assemble the ordered plan list: add-only refs first, then the rest (by name)."""
    plans: list[RefPlan] = [
        RefPlan(ref=r, changed=files_by_ref[r], adds_only=True, group="add", peers=[])
        for r in sorted(add_only)
    ]
    for r in sorted(rest):
        peers = serial_peers.get(r, [])
        plans.append(
            RefPlan(
                ref=r,
                changed=files_by_ref[r],
                adds_only=False,
                group="serial" if peers else "parallel",
                peers=peers,
            )
        )
    return plans


def plan_refs(base: str, refs: list[str]) -> list[RefPlan]:
    """Compute the deterministic integration plan for ``refs`` against ``base``.

    Add-only refs (every changed file is brand-new versus the base tree AND no two
    add-only refs introduce the same new path) are ordered first. The remaining
    refs are partitioned with :func:`partition_work`: a ref alone in its partition
    is ``"parallel"`` (disjoint from all others), a ref sharing a partition is
    ``"serial"`` (overlapping — ordered/manual merge), and its ``peers`` are the
    other refs in that partition. The returned list is the final integration order:
    add-only refs (by name), then the rest (by name).
    """
    refs = sorted(set(refs))
    tracked = tracked_files(base)
    files_by_ref: dict[str, list[str]] = {r: changed_files(base, r) for r in refs}

    candidates = _add_candidates(refs, files_by_ref, tracked)
    add_only = _add_only_refs(candidates)
    rest = [r for r in refs if r not in add_only]
    serial_peers = _serial_peers(rest, files_by_ref)

    return _build_plans(add_only, rest, files_by_ref, serial_peers)


def _overlapping_files(plan: RefPlan, plans: list[RefPlan]) -> list[str]:
    """Files in ``plan`` that another ref also touches — the conflict surface."""
    others: set[str] = set()
    for p in plans:
        if p.ref != plan.ref:
            others |= set(p.changed)
    return sorted(set(plan.changed) & others)


def integrate(plans: list[RefPlan]) -> list[RefResult]:
    """Cherry-pick each ref in plan order; abort + record conflicts, never resolve.

    On a clean pick the ref is recorded ``"merged"``. On a conflict the cherry-pick
    is aborted (leaving the tree clean, NOT mid-cherry-pick) and the ref is recorded
    ``"conflicted"`` with the files it shares with other refs; integration then
    continues with the remaining refs.
    """
    results: list[RefResult] = []
    for plan in plans:
        # ``-c commit.gpgsign=false`` keeps the pick from failing on signing setups
        # (mirrors the repo's other git-writing helpers); a real merge conflict
        # still surfaces as a non-zero exit handled below.
        ok, _ = _git_ok("-c", "commit.gpgsign=false", "cherry-pick", plan.ref)
        if ok:
            results.append(RefResult(ref=plan.ref, status="merged"))
            continue
        # Conflict (or any failed pick): abort to restore a clean tree, then record
        # it for manual handling. We NEVER auto-resolve.
        _git_ok("cherry-pick", "--abort")
        results.append(
            RefResult(
                ref=plan.ref,
                status="conflicted",
                overlaps=_overlapping_files(plan, plans),
            )
        )
    return results


def run_gate() -> int:
    """Run ``scripts/verify.py`` and return its exit code (0 = green)."""
    return subprocess.run(
        [sys.executable, str(VERIFY)],
        cwd=str(ROOT),
    ).returncode


def render_plan(base: str, plans: list[RefPlan]) -> str:
    """Render the dry-run plan: order, grouping, and each ref's files."""
    lines: list[str] = ["# Merge Train Plan", "", f"base: {base}", ""]
    if not plans:
        lines.append("_No refs to integrate._")
        return "\n".join(lines) + "\n"

    order = ", ".join(p.ref for p in plans)
    lines.append(f"integration order: [{order}]")
    lines.append("")

    add = [p for p in plans if p.group == "add"]
    parallel = [p for p in plans if p.group == "parallel"]
    serial = [p for p in plans if p.group == "serial"]

    lines.append(f"## Add-only (clean, go first) — {len(add)}")
    for p in add:
        lines.append(f"- {p.ref}: {_files_str(p.changed)}")
    lines.append("")

    lines.append(f"## Parallel-safe (disjoint, no overlap) — {len(parallel)}")
    for p in parallel:
        lines.append(f"- {p.ref}: {_files_str(p.changed)}")
    lines.append("")

    lines.append(f"## Serial (overlapping — ordered/manual merge) — {len(serial)}")
    for p in serial:
        peers = ", ".join(p.peers) if p.peers else "(none)"
        lines.append(f"- {p.ref}: {_files_str(p.changed)} | overlaps with: {peers}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _files_str(files: list[str]) -> str:
    return "[" + ", ".join(files) + "]" if files else "[no changed files]"


def render_summary(results: list[RefResult], gate: int | None) -> str:
    """Render the post-integration summary: merged, conflicted, and gate result."""
    merged = [r for r in results if r.status == "merged"]
    conflicted = [r for r in results if r.status == "conflicted"]

    lines: list[str] = ["", "=" * 48, "MERGE TRAIN SUMMARY", "=" * 48]
    lines.append(f"merged ({len(merged)}):")
    for r in merged:
        lines.append(f"  + {r.ref}")
    if not merged:
        lines.append("  (none)")

    lines.append(f"conflicted — need manual merge ({len(conflicted)}):")
    for r in conflicted:
        ov = ", ".join(r.overlaps) if r.overlaps else "(no shared files detected)"
        lines.append(f"  ! {r.ref}  overlapping: {ov}")
    if not conflicted:
        lines.append("  (none)")

    if gate is None:
        lines.append("gate: SKIPPED (--no-gate)")
    elif gate == 0:
        lines.append("gate: GREEN")
    else:
        lines.append(f"gate: RED (verify.py exit {gate})")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safe-order integration of agent worktree branches (merge train)",
    )
    parser.add_argument(
        "refs",
        nargs="*",
        help="git refs (branch names / SHAs) to integrate",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help=f"auto-discover local {_AUTO_PREFIX}* branches ahead of the base",
    )
    parser.add_argument(
        "--base",
        default="HEAD",
        help="merge-base/diff base ref (default HEAD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan only; integrate nothing",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="skip the scripts/verify.py gate after integration",
    )
    args = parser.parse_args(argv)

    refs = list(args.refs)
    if args.auto:
        refs.extend(discover_auto_refs(args.base))
    refs = sorted(set(refs))

    if not refs:
        print("merge_train: no refs to integrate "
              "(pass refs positionally or use --auto).")
        return 0

    plans = plan_refs(args.base, refs)

    if args.dry_run:
        print(render_plan(args.base, plans), end="")
        return 0

    results = integrate(plans)

    gate: int | None = None
    if not args.no_gate:
        print("\n===== running gate: scripts/verify.py =====", flush=True)
        gate = run_gate()

    print(render_summary(results, gate))

    conflicted = any(r.status == "conflicted" for r in results)
    gate_red = gate is not None and gate != 0
    return 1 if (conflicted or gate_red) else 0


if __name__ == "__main__":
    raise SystemExit(main())
