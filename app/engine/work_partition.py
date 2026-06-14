"""Provably-disjoint work assignments for a multi-agent army.

Apex can run many agents in parallel — but only safely if no two agents touch
overlapping work. Two tasks overlap not just when they edit the SAME file, but
also when one task's change would ripple (via the import graph) into a file the
other task is editing: a silent merge hazard. This module computes, from a list
of declared tasks, a set of *partitions* such that:

  * tasks WITHIN a partition conflict (share a file or have overlapping change
    blast-radii) and so must run SERIALLY, and
  * tasks in DIFFERENT partitions are provably disjoint and so may run in
    PARALLEL — one agent per partition.

The conflict relation is computed by reusing the existing change blast-radius
(:func:`app.engine.blast_radius.blast_radius`): for each task we take the union
of its edited files and their full transitive-dependent set (the "footprint").
Two tasks conflict iff one task's edited files intersect the other task's
footprint. Conflicts are transitive for grouping purposes (A~B and B~C put A, B,
C in one partition), so partitions are the connected components of the conflict
graph, found with union-find.

Conservative by construction: if a task declares NO resolvable files, its
footprint can't be trusted to be disjoint from anything, so it is treated as
conflicting with every other task (folded into one serial partition) rather than
risk a false "safe to parallelise" verdict.

Deterministic (tasks sorted by name, partitions ordered by their first task
name, every file list sorted; no time/random), stdlib-only, offline, and
read-only — it creates no project files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.engine.blast_radius import blast_radius, is_skipped

__all__ = [
    "Task",
    "Partition",
    "partition_work",
    "render_partition_markdown",
    "max_parallelism",
]


@dataclass
class Task:
    """A unit of work an agent will perform.

    ``name`` identifies the task (used for deterministic ordering). ``files`` are
    the project-relative paths the task will create or modify.
    """

    name: str
    files: list[str] = field(default_factory=list)


@dataclass
class Partition:
    """A group of tasks that must run serially because they conflict.

    ``tasks`` are the conflicting task names (sorted); ``files`` is the sorted
    union of every file those tasks edit. A lone task in its own partition is the
    common, happy case — it may run fully in parallel with the other partitions.
    """

    tasks: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"tasks": self.tasks, "files": self.files}


def _norm(rel: str) -> str:
    """A path string in the blast-radius graph's key format (posix, no ./)."""
    return Path(rel).as_posix()


def _task_files(task: Task) -> list[str]:
    """The task's edited files, normalised, de-skipped, sorted, de-duplicated."""
    return sorted({_norm(f) for f in task.files if f and not is_skipped(f)})


def _footprint(project_root: str | Path, files: list[str]) -> set[str]:
    """A task's full reach: its edited files PLUS their transitive dependents.

    Touching ``files`` can break anything that imports them (directly or
    transitively), so the footprint is the set of files a parallel agent must
    stay clear of. Unresolvable paths simply contribute no dependents (the
    blast-radius skips them); the edited files themselves are always included.
    """
    br = blast_radius(project_root, files)
    return set(files) | set(br.transitive_dependents)


class _UnionFind:
    """Minimal deterministic union-find over integer indices."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression keeps it near-flat without affecting determinism.
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Always attach the larger index under the smaller so the canonical root
        # of a component is its lowest member — fully deterministic.
        lo, hi = (ra, rb) if ra < rb else (rb, ra)
        self._parent[hi] = lo


def partition_work(project_root: str | Path, tasks: list[Task]) -> list[Partition]:
    """Group ``tasks`` into provably-disjoint parallel partitions.

    Two tasks conflict — and so land in the SAME partition (serial) — iff either
    edits a file the other also edits, OR one task's edited files intersect the
    other task's transitive-dependent set (their change blast-radii overlap).
    Conflict is treated as transitive for grouping (connected components via
    union-find), so a chain of overlapping tasks collapses into one partition.

    Tasks in different partitions are safe to run in parallel. The result is
    deterministic: tasks are processed in name order, each partition's tasks and
    files are sorted, and partitions are ordered by their first task name.

    Conservative: a task whose files all fail to resolve (none survive
    :func:`is_skipped` / it declares none) has an untrustworthy footprint, so it
    is unioned with every other task rather than risk a false "disjoint".
    """
    # Sort by name first so all downstream ordering is stable and index-based
    # union-find tie-breaks land on the lowest task name.
    ordered = sorted(tasks, key=lambda t: t.name)
    n = len(ordered)
    if n == 0:
        return []

    edited = [_task_files(t) for t in ordered]
    edited_sets = [set(e) for e in edited]
    footprints = [_footprint(project_root, e) for e in edited]
    # A task is "unresolved" when it names no usable files: we cannot prove it is
    # disjoint from anything, so it must serialise with everyone.
    unresolved = [i for i in range(n) if not edited[i]]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            # Conflict iff either task's edited files touch the other's footprint
            # (a footprint already includes that task's own edited files, so a
            # plain shared file is naturally covered by this single check).
            if edited_sets[i] & footprints[j] or edited_sets[j] & footprints[i]:
                uf.union(i, j)
    # An unresolved task could touch anything, so nothing is provably
    # parallel-safe alongside it: union every task into one shared serial group.
    if unresolved:
        anchor = unresolved[0]
        for i in range(n):
            uf.union(anchor, i)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    partitions: list[Partition] = []
    for members in groups.values():
        names = sorted(ordered[i].name for i in members)
        files: set[str] = set()
        for i in members:
            files |= edited_sets[i]
        partitions.append(Partition(tasks=names, files=sorted(files)))

    # Order partitions by their first (lowest) task name for a stable plan.
    partitions.sort(key=lambda p: p.tasks[0])
    return partitions


def max_parallelism(parts: list[Partition]) -> int:
    """How many agents can run at once safely — the number of partitions.

    Each partition is independent of the others, so one agent per partition can
    run concurrently with zero file-overlap risk.
    """
    return len(parts)


def render_partition_markdown(parts: list[Partition]) -> str:
    """A human-readable parallel plan.

    Lists each partition as a "Parallel group N" with the tasks that share it
    (run serially) and the union of files they touch, and reports the safe
    parallelism (group count).
    """
    lines: list[str] = ["# Parallel Work Plan", ""]

    if not parts:
        lines.append("_No tasks to partition._")
        return "\n".join(lines) + "\n"

    lines.append(f"Max parallelism: {max_parallelism(parts)} agent(s).")
    lines.append("")
    for idx, part in enumerate(parts, start=1):
        tasks_str = ", ".join(part.tasks)
        files_str = ", ".join(part.files) if part.files else "(no resolved files)"
        serial = " (run serially — they overlap)" if len(part.tasks) > 1 else ""
        lines.append(f"## Parallel group {idx}{serial}")
        lines.append(f"- tasks: [{tasks_str}]")
        lines.append(f"- touching files: [{files_str}]")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
