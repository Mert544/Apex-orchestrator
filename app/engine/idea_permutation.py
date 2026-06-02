from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engine.budget import BudgetController
from app.engine.counterfactual_generator import CounterfactualGenerator
from app.engine.novelty import NoveltyScorer
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


# Fractal facets: the self-similar "zoom" of each lens. Applying a lens to a
# subject ("Harden auth.py") is itself decomposable into finer sub-directions
# ("what to harden: input validation, error handling, ..."). These let a leaf
# idea open into its own miniature idea-tree — the same subject→lens structure
# recurring at a finer grain. Fixed and deterministic.
_FACETS: dict[str, list[str]] = {
    "harden": ["input validation", "error handling", "resource limits", "secret handling"],
    "extend": ["new inputs", "new outputs", "configuration surface"],
    "test": ["edge cases", "failure modes", "property invariants"],
    "simplify": ["dead code", "duplicated logic", "deep nesting"],
    "document": ["public API", "usage examples", "failure semantics"],
    "integrate": ["data contract", "error propagation", "version skew"],
    "generalize": ["parameters", "extension points", "sensible defaults"],
    "observe": ["key metrics", "structured logs", "trace spans"],
}


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

    def _append_root(
        self,
        roots: list[IdeaNode],
        seen_subjects: set,
        *,
        title: str,
        subject: str,
        fact_label: str,
        fact_value: str,
        rationale: str | None = None,
    ) -> None:
        """Append a traceable root idea unless its subject was already seeded."""
        if subject in seen_subjects:
            return
        seen_subjects.add(subject)
        idx = len(roots)
        roots.append(
            IdeaNode(
                id=f"idea-{idx}",
                title=title,
                subject=subject,
                rationale=rationale or f"Seeded from {fact_label}: {fact_value}",
                branch_path=make_branch_path("x", idx),
                depth=0,
                operator="root",
                source_facts=[f"{fact_label}: {fact_value}"],
            )
        )

    def seed(self, profile: ProjectProfile, objective: str | None = None) -> list[IdeaNode]:
        roots: list[IdeaNode] = []
        seen_subjects: set[str] = set()

        # Fragility first (highest priority): heavily-depended-on but thinly
        # tested modules — the biggest blast-radius risk.
        for module in (getattr(profile, "fragile_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"Reduce fragility of the heavily-depended-on module {module}",
                subject=module,
                fact_label="fragile",
                fact_value=f"{module} (high in-degree, thin tests)",
            )

        for attr, limit, title_tmpl, fact_label in self._RULES:
            values = getattr(profile, attr, []) or []
            for subject in values[:limit]:
                self._append_root(
                    roots, seen_subjects,
                    title=title_tmpl.format(s=subject),
                    subject=subject,
                    fact_label=fact_label,
                    fact_value=subject,
                )

        # Coverage DEPTH: modules with exactly one linked test are shallowly
        # covered — they need "deepen", not "first test layer".
        untested = set(getattr(profile, "untested_modules", []) or [])
        partial = sorted(
            m for m, tests in (getattr(profile, "module_to_tests", {}) or {}).items()
            if 0 < len(tests) <= 1 and m not in untested
        )
        for module in partial[:2]:
            self._append_root(
                roots, seen_subjects,
                title=f"Deepen the thin test coverage of {module}",
                subject=module,
                fact_label="partial-coverage",
                fact_value=f"{module} (1 test)",
            )

        # Dominant language → tooling idea (type hints / lint config).
        exts = getattr(profile, "extension_counts", {}) or {}
        if exts.get(".py", 0) >= 1:
            self._append_root(
                roots, seen_subjects,
                title="Add type hints and a lint/type-check config",
                subject="Python type coverage",
                fact_label="extension-py",
                fact_value=f".py x{exts['.py']}",
            )

        # Dominant top-level directory → structure/boundaries idea.
        for directory in (getattr(profile, "top_directories", []) or [])[:1]:
            self._append_root(
                roots, seen_subjects,
                title=f"Clarify the structure and boundaries of `{directory}/`",
                subject=f"{directory}/ package",
                fact_label="top-directory",
                fact_value=directory,
            )

        # If the project has no CI, that itself is a development direction.
        if not getattr(profile, "ci_files", None):
            self._append_root(
                roots, seen_subjects,
                title="Add continuous-integration automation",
                subject="CI pipeline",
                fact_label="missing-ci",
                fact_value="no CI workflow files detected",
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

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        project_root: str | Path = ".",
        extra_operators: list[Operator | dict[str, Any]] | None = None,
    ) -> None:
        cfg = config or {}
        self.project_root = str(project_root)
        self.profiler = ProjectProfiler(self.project_root)
        self.seeder = IdeaSeeder()
        # Plugins (or callers) can contribute operators to widen the alphabet.
        extra = [
            op if isinstance(op, Operator) else Operator(**op)
            for op in (extra_operators or [])
            if isinstance(op, Operator) or "{x}" in op.get("template", "")
        ]
        self.operators = DEVELOPMENT_OPERATORS + extra
        self.counterfactual = CounterfactualGenerator()
        self.max_depth = int(cfg.get("max_idea_depth", 2))
        self.breadth = int(cfg.get("breadth", 4))
        self.min_relevance = float(cfg.get("min_relevance", 0.0))
        # Fractal facets: zoom the strongest permutation leaves into self-similar
        # sub-ideas. Opt-in (off by default) because facets share the idea budget
        # with permutation and synthesis; enabling them is most useful with a
        # larger budget. When on, a dedicated slice is carved for them.
        self.fractal_facets = bool(cfg.get("fractal_facets", False))
        self.facets_per_idea = int(cfg.get("facets_per_idea", 2))
        self.budget = BudgetController(max_total_nodes=int(cfg.get("max_total_ideas", 40)))
        # When False, skip the security scan (e.g. tests/perf); weighting stays static.
        self.security_aware = bool(cfg.get("security_aware", True))
        self._security_pressure = 1.0
        self._has_objective = False

    def _scan_security_pressure(self) -> float:
        """Map real security findings to a harden/test weighting multiplier.

        0 findings → 1.0 (no bias); grows ~0.06 per finding, capped at 1.3.
        Best-effort and deterministic; any failure leaves weighting static.
        """
        if not self.security_aware:
            return 1.0
        try:
            from app.agents.skills import SecurityAgent

            result = SecurityAgent().run(project_root=self.project_root)
            n = int(result.get("findings_count", 0) or 0)
        except Exception:
            return 1.0
        return round(min(1.3, 1.0 + 0.06 * n), 4)
    def run(self, objective: str | None = None) -> IdeaTreeReport:
        profile = self.profiler.profile()
        relevance = RelevanceScorer(objective or "")
        self._has_objective = bool(objective and objective.strip())
        graph = GraphStore()  # reused purely for near-duplicate idea detection
        self.novelty = NoveltyScorer(graph)  # reuse the dedup-backed scorer
        self._chain_counts: dict[str, int] = {}  # per-run, for deterministic novelty
        self._subject_counts: dict[str, int] = {}  # subject-diversity novelty signal
        # Security pressure: how strongly real findings should bias harden/test
        # weighting. Scales 1.0 (none) → up to 1.3 (many findings). Best-effort.
        self._security_pressure = self._scan_security_pressure()
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

        # Reserve budget slices so mechanical permutation can't crowd out the
        # genuinely-new ideas. Synthesis and (optionally) fractal facets each get
        # their own slice carved off the top.
        self._synth_reserve = max(4, int(self.budget.max_total_nodes * 0.15))
        facet_reserve = (
            max(2, int(self.budget.max_total_nodes * 0.12)) if self.fractal_facets else 0
        )
        perm_cap = max(
            len(emitted),
            self.budget.max_total_nodes - self._synth_reserve - facet_reserve,
        )

        # Best-first expansion, but diversity-aware: a subject that has already
        # produced many ideas is temporarily down-ranked so the tree spreads
        # across modules instead of over-mining one hub. This shapes *selection
        # order* only — node.value (the score) is untouched.
        emitted_by_subject: dict[str, int] = {}
        for n in emitted:
            emitted_by_subject[n.subject] = emitted_by_subject.get(n.subject, 0) + 1

        def _priority(n: IdeaNode) -> float:
            return n.value - 0.05 * emitted_by_subject.get(n.subject, 0)

        while frontier and not self.budget.exhausted and len(emitted) < perm_cap:
            frontier.sort(key=_priority, reverse=True)
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
                emitted_by_subject[child.subject] = emitted_by_subject.get(child.subject, 0) + 1
                frontier.append(child)

        # Fractal facets: zoom the strongest leaves into self-similar sub-ideas
        # before synthesis claims the remaining budget.
        if self.fractal_facets:
            self._expand_facets(emitted, relevance, graph, stats)

        # Synthesis: genuinely new ideas beyond mechanical permutation, drawn
        # from the budget slice reserved above.
        synth = self._synthesize(emitted, profile, relevance, graph)
        added = 0
        for node in synth:
            if self.budget.exhausted:
                break
            graph.register_claim(node.title)
            self.budget.consume_node()
            emitted.append(node)
            added += 1
        stats["synthesized"] = added

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

    def _synthesize(
        self,
        emitted: list[IdeaNode],
        profile: ProjectProfile,
        relevance: RelevanceScorer,
        graph: GraphStore,
    ) -> list[IdeaNode]:
        """Produce genuinely new ideas that no single operator permutation yields.

        Two sources:
          1. Cross-lens synthesis — if a subject got BOTH 'test' and 'harden'
             lenses, propose a dedicated security-focused test suite.
          2. Module-pair ideas — from dependency-graph edges, propose
             standardizing the interface between coupled modules (and breaking
             import cycles when a mutual edge exists).
        These are not permutations, so they carry kind != "permutation" and a
        non-conflicting branch path (`x.s*` / `x.p*`).
        """
        out: list[IdeaNode] = []

        # 1. Cross-lens synthesis per subject.
        lenses_by_subject: dict[str, set[str]] = {}
        for idea in emitted:
            if idea.subject:
                lenses_by_subject.setdefault(idea.subject, set()).update(idea.operator_chain)
        sidx = 0
        for subject, lenses in lenses_by_subject.items():
            if {"test", "harden"} <= lenses:
                node = IdeaNode(
                    id=f"synth-{sidx}",
                    title=f"Build a security-focused test suite for {subject}",
                    subject=subject,
                    rationale=(
                        "Synthesized: both hardening and testing apply to this "
                        "subject, so target the hardening with dedicated tests."
                    ),
                    branch_path=f"x.s{sidx}",
                    depth=1,
                    operator="synthesis",
                    operator_chain=["harden", "test"],
                    source_facts=["synthesis: test+harden"],
                    kind="synthesis",
                )
                self._score(node, relevance)
                if not graph.has_similar_claim(node.title):
                    out.append(node)
                    sidx += 1

        # 2. Import-cycle ideas — real cycles incl. indirect A->B->C->A, from
        # the dependency graph's cycle detector. Modules already covered by a
        # cycle idea are not re-proposed as plain interface pairs.
        pidx = 0
        in_cycle: set[str] = set()
        for cycle in (getattr(profile, "import_cycles", []) or [])[:3]:
            if pidx >= 4:
                break
            ring = " → ".join(cycle)
            members = [m for m in cycle if m]
            in_cycle.update(members)
            node = IdeaNode(
                id=f"pair-{pidx}",
                title=f"Break the import cycle {ring}",
                subject="↔".join(dict.fromkeys(members)),
                rationale=f"Synthesized: {len(set(members))} modules form an import cycle.",
                branch_path=f"x.p{pidx}",
                depth=1,
                operator="synthesis",
                operator_chain=["integrate"],
                source_facts=["dependency-cycle"],
                kind="pair",
            )
            self._score(node, relevance)
            if not graph.has_similar_claim(node.title):
                out.append(node)
                pidx += 1

        # Plain coupling ideas for edges not already inside a reported cycle.
        edges = getattr(profile, "dependency_edges", []) or []
        seen_pairs: set[tuple[str, str]] = set()
        for source, target in edges:
            if pidx >= 5:  # keep total pair ideas bounded
                break
            if source in in_cycle and target in in_cycle:
                continue
            key = tuple(sorted((source, target)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            node = IdeaNode(
                id=f"pair-{pidx}",
                title=f"Standardize the interface between {source} and {target}",
                subject=f"{source}↔{target}",
                rationale="Synthesized: a dependency edge couples these modules.",
                branch_path=f"x.p{pidx}",
                depth=1,
                operator="synthesis",
                operator_chain=["integrate"],
                source_facts=["dependency-edge"],
                kind="pair",
            )
            self._score(node, relevance)
            if not graph.has_similar_claim(node.title):
                out.append(node)
                pidx += 1

        return out

    def _expand(self, node: IdeaNode) -> list[IdeaNode]:
        """Apply each unused operator to produce permutation children."""
        children: list[IdeaNode] = []
        available = [op for op in self.operators if op.name not in node.operator_chain]
        for i, op in enumerate(available[: self.breadth]):
            chain = node.operator_chain + [op.name]
            base = op.template.format(x=node.subject)
            # Depth-aware rationale: reference the accumulated lens path.
            rationale = (
                base
                if node.depth == 0
                else f"{base} — building on: {' then '.join(node.operator_chain)}."
            )
            # Context reweighting: security-relevant subjects favor harden/test,
            # scaled by how many real security findings the project has.
            ctx = _context_weight(node, op.name, self._security_pressure)
            feasibility = min(1.0, round(op.feasibility * (0.9 ** node.depth) * ctx, 4))
            children.append(
                IdeaNode(
                    id=f"{node.id}-{i}",
                    title=_compose_title(node.subject, chain),
                    subject=node.subject,
                    rationale=rationale,
                    branch_path=make_branch_path(node.branch_path, i),
                    depth=node.depth + 1,
                    parent_id=node.id,
                    operator=op.name,
                    operator_chain=chain,
                    source_facts=node.source_facts,
                    feasibility=feasibility,
                )
            )
        return children

    def _expand_facets(
        self,
        emitted: list[IdeaNode],
        relevance: RelevanceScorer,
        graph: GraphStore,
        stats: dict[str, Any],
    ) -> None:
        """Zoom the strongest permutation leaves into self-similar facet ideas.

        A leaf (a fully-expanded permutation idea with no permutation children)
        whose lens has a known facet vocabulary opens into finer sub-directions
        — e.g. "Harden auth.py" → "...input validation", "...error handling".
        Facets are parented under their leaf (``kind="facet"``), so they render
        nested in the tree and never violate the operator-permutation invariant
        (which applies only to ``kind="permutation"`` ideas).
        """
        # A leaf is a permutation idea that produced no permutation children.
        perm_parents = {
            n.parent_id for n in emitted if n.kind == "permutation" and n.parent_id
        }
        leaves = [
            n for n in emitted
            if n.kind == "permutation"
            and n.operator != "root"
            and n.operator in _FACETS
            and n.id not in perm_parents
        ]
        # Best leaves first; deterministic tie-break on branch path.
        leaves.sort(key=lambda n: (n.value, n.branch_path), reverse=True)

        facet_cap = max(2, int(self.budget.max_total_nodes * 0.12))
        # Never spend the slice reserved for synthesis.
        synth_floor = self.budget.max_total_nodes - getattr(self, "_synth_reserve", 0)
        added = 0
        for leaf in leaves:
            if self.budget.exhausted or added >= facet_cap or len(emitted) >= synth_floor:
                break
            for j, facet in enumerate(_FACETS[leaf.operator][: self.facets_per_idea]):
                if self.budget.exhausted or added >= facet_cap or len(emitted) >= synth_floor:
                    break
                child = IdeaNode(
                    id=f"{leaf.id}-f{j}",
                    title=f"{leaf.operator.capitalize()} {leaf.subject} — {facet}",
                    subject=f"{leaf.subject} :: {facet}",
                    rationale=(
                        f"Fractal zoom of `{leaf.branch_path}`: refine the "
                        f"{leaf.operator} of {leaf.subject} down to {facet}."
                    ),
                    branch_path=f"{leaf.branch_path}.f{j}",
                    depth=leaf.depth + 1,
                    parent_id=leaf.id,
                    operator=leaf.operator,
                    operator_chain=list(leaf.operator_chain),
                    source_facts=list(leaf.source_facts) + [f"facet: {facet}"],
                    feasibility=leaf.feasibility,
                    kind="facet",
                )
                if graph.has_similar_claim(child.title):
                    continue
                self._score(child, relevance)
                # _score recomputes feasibility only for roots, so the inherited
                # leaf feasibility above is preserved for facets.
                graph.register_claim(child.title)
                self.budget.consume_node()
                emitted.append(child)
                added += 1
        stats["faceted"] = added

    def _novelty(self, node: IdeaNode) -> float:
        """Deterministic novelty: deeper / more-repeated lens chains are less novel.

        Uses the dedup GraphStore-backed NoveltyScorer's philosophy at the
        operator-chain granularity (raw titles are already unique by construction,
        so a per-chain repetition signal is what actually differentiates ideas).
        """
        if node.operator == "root":
            return 1.0
        sig = ">".join(node.operator_chain)
        seen = self._chain_counts.get(sig, 0)
        self._chain_counts[sig] = seen + 1
        # Subject-diversity: penalize piling many ideas onto the same subject so
        # the tree spreads across modules instead of over-mining one hub.
        subj_seen = self._subject_counts.get(node.subject, 0)
        self._subject_counts[node.subject] = subj_seen + 1
        nov = 1.0 - 0.15 * node.depth - 0.10 * seen - 0.04 * subj_seen
        return max(0.2, round(nov, 4))

    def _score(self, node: IdeaNode, relevance: RelevanceScorer) -> None:
        node.relevance = relevance.score(f"{node.title} {node.subject}")
        if node.operator == "root":
            node.feasibility = node.feasibility or 0.7
        node.novelty = self._novelty(node)
        # Weight calibration: relevance only discriminates when an objective is
        # set (otherwise it is constant 1.0 and the 0.4 term is dead, flattening
        # scores). With no objective, redistribute that weight to the signals
        # that actually vary — novelty and feasibility.
        if self._has_objective:
            node.value = round(
                0.4 * node.relevance + 0.3 * node.novelty + 0.3 * node.feasibility, 4
            )
        else:
            node.value = round(
                0.2 * node.relevance + 0.4 * node.novelty + 0.4 * node.feasibility, 4
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
    "partial-coverage": "check validation edge cases",
    "entrypoint": "request call network",
    "dependency-hub": "complex",
    "symbol-hub": "complex",
    "config": "hardcoded secret",
    "fragile": "check validation edge cases complex",
    "extension-py": "type hints lint",
    "top-directory": "structure boundaries",
}

# Root fact labels where reliability/security lenses matter most.
_SECURITY_LABELS = {"sensitive-path", "critical-untested", "untested", "partial-coverage", "fragile"}


def _context_weight(node: IdeaNode, op_name: str, security_pressure: float = 1.0) -> float:
    """Upweight harden/test for security-relevant subjects, downweight the rest.

    ``security_pressure`` (>= 1.0) scales the harden/test boost up when the
    project has real security findings, so reliability lenses rise to the top
    exactly when they matter most.
    """
    label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
    if label in _SECURITY_LABELS:
        if op_name in ("harden", "test"):
            # base 1.1 boost, amplified by security pressure (capped to keep
            # feasibility <= 1.0 after the min() at the call site).
            return min(1.3, 1.1 * security_pressure)
        if op_name in ("integrate", "generalize"):
            return 0.9
    return 1.0


# Caveat hints for synthesized ideas, keyed by kind, so counterfactuals stay
# on-topic instead of misfiring on incidental words in the title.
_KIND_HINTS: dict[str, str] = {
    "synthesis": "check validation edge cases security",
    "pair": "interface boundary coupling refactor",
}


def _caveat_hint(node: IdeaNode) -> str:
    if node.kind != "permutation":
        return _KIND_HINTS.get(node.kind, "interface boundary")
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

    # Synthesis/pair ideas are parentless-but-not-roots; render them separately.
    # Facet ideas are parented under a permutation leaf, so they render nested
    # via walk() (the fractal zoom) and are excluded from this flat section.
    synth = [i for i in report.ideas if i.kind != "permutation" and i.parent_id is None]
    synth_ids = {i.id for i in synth}
    perm_roots = [
        i for i in by_parent.get(None, []) if i.kind == "permutation" and i.id not in synth_ids
    ]

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

    for root in perm_roots:
        walk(root, 0)
        lines.append("")

    if synth:
        lines.append("## 🔗 Synthesized ideas (beyond single-lens permutation)")
        for idea in sorted(synth, key=lambda n: n.value, reverse=True):
            tag = "synthesis" if idea.kind == "synthesis" else "module-pair"
            lines.append(f"- [{tag}] {idea.title}  (v {idea.value})")
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
