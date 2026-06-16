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


def _modules(subject: str) -> set[str]:
    """Tokenize a pair subject (``a.py↔b.py``) into its module names."""
    return set(subject.replace("↔", " ").split())


def _group_by_base(ideas: list[IdeaNode]) -> dict[str, list[IdeaNode]]:
    """Group ideas by their base subject (facets fold into their leaf)."""
    by_subject: dict[str, list[IdeaNode]] = defaultdict(list)
    for i in ideas:
        by_subject[_base(i.subject)].append(i)
    return by_subject


def _peers(idea: IdeaNode, group: list[IdeaNode], operators: set[str]) -> set[str]:
    """Ids of other ideas in ``group`` whose operator is in ``operators``."""
    return {i.id for i in group if i.operator in operators and i.id != idea.id}


def _prereqs_for(idea: IdeaNode, group: list[IdeaNode]) -> set[str]:
    """Within one base-subject group, the prerequisite ids for ``idea``.

    A mutating lens waits on the group's tests; a document/observe lens waits
    on the group's builds. ``idea`` never depends on itself.
    """
    out: set[str] = set()
    if idea.operator in _MUTATING:
        out.update(_peers(idea, group, {"test"}))
    if idea.operator in _AFTER_BUILD:
        out.update(_peers(idea, group, _BUILD))
    return out


def _cycle_prereqs(idea: IdeaNode, cycles: list[IdeaNode]) -> set[str]:
    """Interface pairs wait on cycle-break pairs over overlapping modules."""
    if not (idea.kind == "pair" and "interface" in idea.title.lower()):
        return set()
    members = _modules(_base(idea.subject))
    return {c.id for c in cycles if members & _modules(c.subject)}


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

    for group in _group_by_base(ideas).values():
        for i in group:
            deps[i.id].update(_prereqs_for(i, group))

    # Cycle-before-interface: a coupling/interface pair waits on a cycle break
    # that covers overlapping modules.
    cycles = [i for i in ideas if i.kind == "pair" and "cycle" in i.title.lower()]
    for i in ideas:
        deps[i.id].update(_cycle_prereqs(i, cycles))
    return deps


def _known_prereqs(iid: str, deps: dict[str, set[str]], by_id: dict[str, IdeaNode]) -> list[str]:
    """Prerequisite ids of ``iid`` that are present in this idea set."""
    return [d for d in deps.get(iid, set()) if d in by_id]


def _compute_levels(
    ideas: list[IdeaNode], deps: dict[str, set[str]], by_id: dict[str, IdeaNode]
) -> dict[str, int]:
    """Longest-path layering: a node's layer = 1 + max layer of its prerequisites.

    Cycle-guarded — a node re-entered while still resolving is treated as a root.
    """
    level: dict[str, int] = {}

    def _level(iid: str, visiting: set[str]) -> int:
        if iid in level:
            return level[iid]
        if iid in visiting:  # defensive cycle guard — treat as a root
            return 0
        visiting.add(iid)
        prereqs = _known_prereqs(iid, deps, by_id)
        lv = 0 if not prereqs else 1 + max(_level(d, visiting) for d in prereqs)
        visiting.discard(iid)
        level[iid] = lv
        return lv

    for i in ideas:
        _level(i.id, set())
    return level


def _critical_path(
    ideas: list[IdeaNode],
    deps: dict[str, set[str]],
    by_id: dict[str, IdeaNode],
    level: dict[str, int],
) -> set[str]:
    """Walk back from a deepest node, always to a deepest prereq.

    ``crit`` doubles as the visited set: on a mutual dependency cycle the walk
    would otherwise oscillate between two nodes forever (``_compute_levels`` is
    cycle-guarded, but this walk was not). Re-reaching a visited node ends it.
    """
    crit: set[str] = set()
    if not level:
        return crit
    cur = max(ideas, key=lambda i: (level[i.id], i.value)).id
    while cur not in crit:
        crit.add(cur)
        prereqs = _known_prereqs(cur, deps, by_id)
        if not prereqs:
            break
        cur = max(prereqs, key=lambda d: (level[d], by_id[d].value))
    return crit


def _build_step(
    idea: IdeaNode,
    deps: dict[str, set[str]],
    by_id: dict[str, IdeaNode],
    level: dict[str, int],
    crit: set[str],
) -> ExecStep:
    """Materialize one ordered step (prerequisite branch paths sorted)."""
    return ExecStep(
        branch_path=idea.branch_path, title=idea.title, subject=idea.subject,
        operator=idea.operator, value=idea.value, order=level[idea.id],
        depends_on=sorted(by_id[d].branch_path for d in _known_prereqs(idea.id, deps, by_id)),
        on_critical_path=idea.id in crit,
    )


def execution_order(ideas: list[IdeaNode]) -> list[ExecStep]:
    """Topologically order ideas so every prerequisite precedes its dependent."""
    if not ideas:
        return []
    deps = infer_dependencies(ideas)
    by_id = {i.id: i for i in ideas}
    level = _compute_levels(ideas, deps, by_id)
    crit = _critical_path(ideas, deps, by_id, level)
    steps = [_build_step(i, deps, by_id, level, crit) for i in ideas]
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
