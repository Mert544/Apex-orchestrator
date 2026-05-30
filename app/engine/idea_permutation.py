from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engine.budget import BudgetController
from app.engine.counterfactual_generator import CounterfactualGenerator
from app.memory.graph_store import GraphStore
from app.models.idea import IdeaNode, IdeaTreeReport
from app.skills.relevance_scorer import RelevanceScorer
from app.tools.project_profile import ProjectProfile, ProjectProfiler
from app.utils.branching import make_branch_path


@dataclass(frozen=True)
class Operator:
    """A development lens that turns an idea about ``{x}`` into a child idea.

    ``template`` is phrased so it reads naturally when appended to a parent
    direction; ``feasibility`` is a cheap 0..1 weight (cheaper lenses score
    higher) used by the engine's value function.
    """

    name: str
    template: str
    feasibility: float


# The fixed permutation alphabet — the "abc" applied to every branch "a".
# Data-driven so breadth is tunable and plugins can extend it later.
DEVELOPMENT_OPERATORS: list[Operator] = [
    Operator("extend", "Extend {x} with a new capability", 0.6),
    Operator("harden", "Harden {x} against failure and abuse", 0.6),
    Operator("test", "Raise test coverage and add property tests for {x}", 0.85),
    Operator("simplify", "Refactor {x} to reduce complexity", 0.5),
    Operator("document", "Document the contract and usage of {x}", 0.85),
    Operator("integrate", "Integrate {x} with another subsystem", 0.4),
    Operator("generalize", "Make {x} reusable and configurable", 0.45),
    Operator("observe", "Add metrics and logging around {x}", 0.7),
]


class IdeaSeeder:
    """Derive root development branches from a project's real structure.

    Each root is grounded in concrete profile facts (``source_facts``) so every
    downstream idea is traceable to actual code.
    """

    # (profile attribute, max seeds, subject label, title template, fact label)
    _RULES = [
        ("dependency_hubs", 3, "Evolve the central module {s}", "dependency-hub"),
        ("critical_untested_modules", 3, "Establish a safety net around {s}", "critical-untested"),
        ("untested_modules", 2, "Add a first test layer for {s}", "untested"),
        ("sensitive_paths", 3, "Harden the sensitive path {s}", "sensitive-path"),
        ("entrypoints", 2, "Grow capability behind the entrypoint {s}", "entrypoint"),
        ("symbol_hubs", 2, "Generalize the symbol-rich module {s}", "symbol-hub"),
        ("config_files", 1, "Make configuration {s} environment-aware", "config"),
    ]

    def seed(self, profile: ProjectProfile, objective: str | None = None) -> list[IdeaNode]:
        roots: list[IdeaNode] = []
        seen_subjects: set[str] = set()

        for attr, limit, title_tmpl, fact_label in self._RULES:
            values = getattr(profile, attr, []) or []
            for subject in values[:limit]:
                if subject in seen_subjects:
                    continue
                seen_subjects.add(subject)
                idx = len(roots)
                roots.append(
                    IdeaNode(
                        id=f"idea-{idx}",
                        title=title_tmpl.format(s=subject),
                        subject=subject,
                        rationale=f"Seeded from {fact_label}: {subject}",
                        branch_path=make_branch_path("x", idx),
                        depth=0,
                        operator="root",
                        source_facts=[f"{fact_label}: {subject}"],
                    )
                )

        # If the project has no CI, that itself is a development direction.
        if not getattr(profile, "ci_files", None):
            idx = len(roots)
            roots.append(
                IdeaNode(
                    id=f"idea-{idx}",
                    title="Add continuous-integration automation",
                    subject="CI pipeline",
                    rationale="Seeded from missing-ci: no CI workflow files detected",
                    branch_path=make_branch_path("x", idx),
                    depth=0,
                    operator="root",
                    source_facts=["missing-ci: no CI workflow files detected"],
                )
            )

        return roots


class IdeaPermutationEngine:
    """Generative fractal: split a project into autonomous development branches
    and permute each into operator-sequence sub-branches.

    Roots are derived from the real codebase (IdeaSeeder). Each idea is then
    expanded by applying development operators it has not used yet, so every
    branch path is a unique *permutation* of lenses over a code subject
    (the "abc" of each "a"). Deterministic — no LLM.

    Config keys (all optional):
        max_total_ideas: budget on emitted ideas (default 40)
        max_idea_depth:  how deep the permutation goes (default 2)
        breadth:         operators applied per node (default 4)
        min_relevance:   drop ideas below this relevance to the objective (0=off)
    """

    def __init__(self, config: dict[str, Any] | None = None, project_root: str | Path = ".") -> None:
        cfg = config or {}
        self.project_root = str(project_root)
        self.profiler = ProjectProfiler(self.project_root)
        self.seeder = IdeaSeeder()
        self.operators = DEVELOPMENT_OPERATORS
        self.counterfactual = CounterfactualGenerator()
        self.max_depth = int(cfg.get("max_idea_depth", 2))
        self.breadth = int(cfg.get("breadth", 4))
        self.min_relevance = float(cfg.get("min_relevance", 0.0))
        self.budget = BudgetController(max_total_nodes=int(cfg.get("max_total_ideas", 40)))

    def run(self, objective: str | None = None) -> IdeaTreeReport:
        profile = self.profiler.profile()
        relevance = RelevanceScorer(objective or "")
        graph = GraphStore()  # reused purely for near-duplicate idea detection
        stats = {"considered": 0, "pruned_relevance": 0, "pruned_duplicate": 0}

        emitted: list[IdeaNode] = []
        frontier: list[IdeaNode] = []

        for root in self.seeder.seed(profile, objective):
            if self.budget.exhausted:
                break
            self._score(root, relevance)
            graph.register_claim(root.title)
            self.budget.consume_node()
            emitted.append(root)
            frontier.append(root)

        # Best-first expansion by value.
        while frontier and not self.budget.exhausted:
            frontier.sort(key=lambda n: n.value, reverse=True)
            node = frontier.pop(0)
            if node.depth >= self.max_depth:
                continue
            for child in self._expand(node):
                if self.budget.exhausted:
                    break
                stats["considered"] += 1
                if graph.has_similar_claim(child.title):
                    stats["pruned_duplicate"] += 1
                    continue
                self._score(child, relevance)
                if self.min_relevance > 0.0 and child.relevance < self.min_relevance:
                    stats["pruned_relevance"] += 1
                    continue
                graph.register_claim(child.title)
                self.budget.consume_node()
                emitted.append(child)
                frontier.append(child)

        stats["total_ideas"] = len(emitted)
        stats["mean_value"] = (
            round(sum(i.value for i in emitted) / len(emitted), 4) if emitted else 0.0
        )
        return IdeaTreeReport(
            objective=objective or "",
            project_root=self.project_root,
            ideas=emitted,
            branch_map={i.branch_path: i.title for i in emitted},
            stats=stats,
        )

    def _expand(self, node: IdeaNode) -> list[IdeaNode]:
        """Apply each unused operator to produce permutation children."""
        children: list[IdeaNode] = []
        available = [op for op in self.operators if op.name not in node.operator_chain]
        for i, op in enumerate(available[: self.breadth]):
            chain = node.operator_chain + [op.name]
            children.append(
                IdeaNode(
                    id=f"{node.id}-{i}",
                    title=_compose_title(node.subject, chain),
                    subject=node.subject,
                    rationale=op.template.format(x=node.subject),
                    branch_path=make_branch_path(node.branch_path, i),
                    depth=node.depth + 1,
                    parent_id=node.id,
                    operator=op.name,
                    operator_chain=chain,
                    source_facts=node.source_facts,
                    feasibility=round(op.feasibility * (0.9 ** node.depth), 4),
                )
            )
        return children

    def _score(self, node: IdeaNode, relevance: RelevanceScorer) -> None:
        node.relevance = relevance.score(f"{node.title} {node.subject}")
        if node.operator == "root":
            node.feasibility = node.feasibility or 0.7
        node.value = round(
            0.4 * node.relevance + 0.3 * node.novelty + 0.3 * node.feasibility, 4
        )
        # Feed operator/fact context so counterfactual caveats are relevant to
        # the development direction, not generic.
        cf_text = f"{node.title} {_caveat_hint(node)}".strip()
        node.caveats = self.counterfactual.generate({"text": cf_text}).scenarios[:2]


# Keyword-rich context per development lens so the CounterfactualGenerator
# surfaces scenarios relevant to that direction (it pattern-matches on text).
_OPERATOR_HINTS: dict[str, str] = {
    "harden": "guard validation check sanitize secret",
    "document": "docstring documented contract",
    "simplify": "long complex refactor",
    "integrate": "network request call subsystem",
    "observe": "network call logging monitoring",
    "test": "check validation edge cases",
    "extend": "validation guard new input",
    "generalize": "configurable check reusable",
}
_FACT_HINTS: dict[str, str] = {
    "sensitive-path": "guard validation secret check",
    "untested": "check validation edge cases",
    "critical-untested": "check validation edge cases",
    "entrypoint": "request call network",
    "dependency-hub": "complex",
    "symbol-hub": "complex",
    "config": "hardcoded secret",
}


def _caveat_hint(node: IdeaNode) -> str:
    if node.operator != "root":
        return _OPERATOR_HINTS.get(node.operator, "")
    label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
    return _FACT_HINTS.get(label, "")


def _compose_title(subject: str, chain: list[str]) -> str:
    """Readable, distinct title from the operator chain over a subject."""
    lenses = " → ".join(name.capitalize() for name in chain)
    return f"{lenses}: {subject}"


def render_markdown(report: IdeaTreeReport) -> str:
    """Render an idea tree as a readable, hierarchical markdown document."""
    lines = [f"# Development Ideas for `{report.project_root}`", ""]
    meta = f"{report.stats.get('total_ideas', 0)} ideas · mean value {report.stats.get('mean_value', 0)}"
    if report.objective:
        meta = f"objective: _{report.objective}_ · " + meta
    lines += [meta, ""]

    by_parent: dict[str | None, list[IdeaNode]] = {}
    for idea in report.ideas:
        by_parent.setdefault(idea.parent_id, []).append(idea)

    def walk(idea: IdeaNode, depth: int) -> None:
        indent = "  " * depth
        if depth == 0:
            lines.append(f"## {idea.branch_path} — {idea.title}  (value {idea.value})")
            if idea.source_facts:
                lines.append(f"{indent}- _facts: {', '.join(idea.source_facts)}_")
        else:
            caveat = f"  ⚠ {idea.caveats[0]}" if idea.caveats else ""
            lines.append(
                f"{indent}- `{idea.branch_path}` [{idea.operator}] {idea.title}  (v {idea.value}){caveat}"
            )
        for child in by_parent.get(idea.id, []):
            walk(child, depth + 1)

    for root in by_parent.get(None, []):
        walk(root, 0)
        lines.append("")
    return "\n".join(lines)


def render_mermaid(report: IdeaTreeReport) -> str:
    """Render the idea tree as a Mermaid flowchart."""
    lines = ["```mermaid", "flowchart TD"]
    for idea in report.ideas:
        label = idea.title.replace('"', "'")
        lines.append(f'    {idea.branch_path.replace(".", "_")}["{label}"]')
    for idea in report.ideas:
        if idea.parent_id:
            parent = next((p for p in report.ideas if p.id == idea.parent_id), None)
            if parent:
                a = parent.branch_path.replace(".", "_")
                b = idea.branch_path.replace(".", "_")
                lines.append(f"    {a} --> {b}")
    lines.append("```")
    return "\n".join(lines)
