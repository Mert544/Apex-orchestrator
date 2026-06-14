"""Idea dependencies — turn a set of ideas into an ordered execution plan.

The roadmap orders ideas by *phase* (Stabilize → Secure → Evolve → Refine). But
real work has finer, idea-level prerequisites: you add a safety net to a module
*before* you change that same module; you break an import cycle *before* you
formalize the interface across it; you document a thing *after* you build it.

This module infers those prerequisites deterministically from (subject, lens),
builds a dependency DAG, topologically layers it into an execution order (ties
broken by value), and finds the **critical path** — the longest prerequisite
chain, i.e. the minimum number of sequential steps the plan can't avoid.

Pure and deterministic. No LLM.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.idea import IdeaNode

# Lenses that *change* a module — they should come after a test safety net.
_MUTATING = {"harden", "simplify", "extend", "generalize", "integrate"}
# Lenses that describe/observe — best done after the thing is built.
_AFTER_BUILD = {"document", "observe"}
_BUILD = {"extend", "generalize"}


def _base(subject: str) -> str:
    return subject.split(" :: ", 1)[0]


@dataclass
class ExecStep:
    branch_path: str
    title: str
    subject: str
    operator: str
    value: float
    order: int                      # topological layer (0 = no prerequisites)
    depends_on: list[str] = field(default_factory=list)  # prerequisite branch paths
    on_critical_path: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_dependencies(ideas: list[IdeaNode]) -> dict[str, set[str]]:
    """Map each idea id → the set of idea ids that should precede it.

    Rules (deterministic, per shared base subject):
      • a *mutating* lens depends on the *test* idea(s) for the same subject;
      • a *document/observe* lens depends on the *build* (extend/generalize) ideas;
      • a "standardize interface" pair depends on a "break import cycle" idea that
        covers the same modules.
    """
    deps: dict[str, set[str]] = {i.id: set() for i in ideas}

    by_subject: dict[str, list[IdeaNode]] = defaultdict(list)
    for i in ideas:
        by_subject[_base(i.subject)].append(i)

    for group in by_subject.values():
        tests = [i for i in group if i.operator == "test"]
        builds = [i for i in group if i.operator in _BUILD]
        for i in group:
            if i.operator in _MUTATING and tests:
                deps[i.id].update(t.id for t in tests if t.id != i.id)
            if i.operator in _AFTER_BUILD and builds:
                deps[i.id].update(b.id for b in builds if b.id != i.id)

    # Cycle-before-interface: a coupling/interface pair waits on a cycle break
    # that covers overlapping modules.
    cycles = [i for i in ideas if i.kind == "pair" and "cycle" in i.title.lower()]
    for i in ideas:
        if i.kind == "pair" and "interface" in i.title.lower():
            members = set(_base(i.subject).replace("↔", " ").split())
            for c in cycles:
                if members & set(c.subject.replace("↔", " ").split()):
                    deps[i.id].add(c.id)
    return deps


def execution_order(ideas: list[IdeaNode]) -> list[ExecStep]:
    """Topologically order ideas so every prerequisite precedes its dependent."""
    if not ideas:
        return []
    deps = infer_dependencies(ideas)
    by_id = {i.id: i for i in ideas}

    # Longest-path layering (a node's layer = 1 + max layer of its prerequisites).
    level: dict[str, int] = {}

    def _level(iid: str, visiting: set[str]) -> int:
        if iid in level:
            return level[iid]
        if iid in visiting:  # defensive cycle guard — treat as a root
            return 0
        visiting.add(iid)
        prereqs = [d for d in deps.get(iid, set()) if d in by_id]
        lv = 0 if not prereqs else 1 + max(_level(d, visiting) for d in prereqs)
        visiting.discard(iid)
        level[iid] = lv
        return lv

    for i in ideas:
        _level(i.id, set())

    # Critical path: walk back from a deepest node, always to a deepest prereq.
    # ``crit`` doubles as the visited set: on a mutual dependency cycle the walk
    # would otherwise oscillate between two nodes forever (``_level`` above is
    # cycle-guarded, but this walk was not). Re-reaching a visited node ends it.
    crit: set[str] = set()
    if level:
        cur = max(ideas, key=lambda i: (level[i.id], i.value)).id
        while cur not in crit:
            crit.add(cur)
            prereqs = [d for d in deps.get(cur, set()) if d in by_id]
            if not prereqs:
                break
            cur = max(prereqs, key=lambda d: (level[d], by_id[d].value))

    steps = [
        ExecStep(
            branch_path=i.branch_path, title=i.title, subject=i.subject,
            operator=i.operator, value=i.value, order=level[i.id],
            depends_on=sorted(by_id[d].branch_path for d in deps.get(i.id, set()) if d in by_id),
            on_critical_path=i.id in crit,
        )
        for i in ideas
    ]
    # Execute lower layers first; within a layer, highest value first.
    steps.sort(key=lambda s: (s.order, -s.value, s.branch_path))
    return steps


def critical_path_length(steps: list[ExecStep]) -> int:
    """Number of ideas on the critical path (min sequential depth of the plan)."""
    return sum(1 for s in steps if s.on_critical_path)


def render_execution_markdown(steps: list[ExecStep]) -> str:
    """Render the dependency-ordered execution plan, grouped by layer."""
    lines = ["# Execution plan (dependency-ordered)", ""]
    if not steps:
        lines += ["_No ideas to sequence._", ""]
        return "\n".join(lines)

    max_order = max(s.order for s in steps)
    crit = critical_path_length(steps)
    lines.append(
        f"{len(steps)} ideas across {max_order + 1} dependency layer(s) · "
        f"critical path {crit} step(s) deep."
    )
    lines.append("")
    by_order: dict[int, list[ExecStep]] = defaultdict(list)
    for s in steps:
        by_order[s.order].append(s)
    for order in sorted(by_order):
        label = "no prerequisites" if order == 0 else f"after layer {order - 1}"
        lines.append(f"## Layer {order} — {label}")
        for s in by_order[order]:
            star = " ⭐" if s.on_critical_path else ""
            dep = f"  ⟵ needs {', '.join(f'`{d}`' for d in s.depends_on)}" if s.depends_on else ""
            lines.append(f"- `{s.branch_path}` [{s.operator}] {s.title}{star}{dep}")
        lines.append("")
    lines.append("_⭐ = on the critical path (the chain that sets the minimum number "
                 "of sequential steps)._")
    lines.append("")
    return "\n".join(lines)
