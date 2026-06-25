from __future__ import annotations

import re
from dataclasses import dataclass, field
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

from app.engine.idea_facets import (  # noqa: F401  (re-exports: surface unchanged)
    _FACET_CASES,
    _FACET_CAVEAT_RULES,
    _FACET_SUBASPECTS,
    _FACETS,
)
from app.engine.idea_seeder import IdeaSeeder  # noqa: F401  (re-export)


@dataclass
class _PairState:
    """Threaded state for the module-pair synthesis sections: one bounded
    ``pidx`` counter and the cross-section dedup set, so cycle/co-change/edge
    ideas share the same numbering and never re-propose the same pair."""

    pidx: int = 0
    seen_pairs: set[tuple[str, str]] = field(default_factory=set)


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
DEVELOPMENT_OPERATORS: list[Operator] = [
    Operator("extend", "Extend {x} with a new capability", 0.6),
    Operator("harden", "Harden {x} against failure and abuse", 0.6),
    Operator("test", "Raise test coverage and add property tests for {x}", 0.85),
    Operator("simplify", "Refactor {x} to reduce complexity", 0.5),
    Operator("document", "Document the contract and usage of {x}", 0.85),
    Operator("integrate", "Integrate {x} with another subsystem", 0.4),
    Operator("generalize", "Make {x} reusable and configurable", 0.45),
    Operator("observe", "Add metrics and logging around {x}", 0.7),
    Operator("decouple", "Decouple {x} from its direct dependencies", 0.45),
    Operator("verify", "Strengthen the proof that {x} is correct", 0.5),
    Operator("fortify", "Add the smallest guard that removes an edge-input failure mode in {x}", 0.5),
]


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
        learning:        consult .apex/idea-memory.json to nudge feasibility from
                         past apply outcomes (default True; no-op without the file)
        adaptive_depth:  let high-value branches grow past max_idea_depth
                         (default False); adaptive_depth_bonus (2) and
                         adaptive_depth_threshold (0.6) tune it
        fractal_facets:  zoom strong leaves into self-similar sub-ideas
                         (default False); facet_depth (1) sets the zoom levels
        security_aware:  scan real findings to bias harden/test (default True)
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
        self.seeder = IdeaSeeder(self.project_root)
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
        # Learning: consult past apply outcomes to nudge feasibility. No-op when
        # no memory file exists, so a fresh project scores exactly as before.
        self.learning = bool(cfg.get("learning", True))
        self._memory = None
        # Adaptive depth: let high-value branches grow deeper than max_depth,
        # concentrating the fractal where value (and learned reliability) lives.
        # Opt-in; off by default so existing trees are unchanged.
        self.adaptive_depth = bool(cfg.get("adaptive_depth", False))
        self.adaptive_depth_bonus = int(cfg.get("adaptive_depth_bonus", 2))
        # A branch keeps deepening past max_depth only while its value stays above
        # this bar; novelty decay pulls deep nodes under it, so depth self-limits.
        self.adaptive_depth_threshold = float(cfg.get("adaptive_depth_threshold", 0.6))
        # Fractal facets: zoom the strongest permutation leaves into self-similar
        # sub-ideas. Opt-in (off by default) because facets share the idea budget
        # with permutation and synthesis; enabling them is most useful with a
        # larger budget. When on, a dedicated slice is carved for them.
        self.fractal_facets = bool(cfg.get("fractal_facets", False))
        self.facets_per_idea = int(cfg.get("facets_per_idea", 2))
        # How many self-similar zoom levels facets recurse (1 = aspects only;
        # 2+ drills each aspect into common/boundary/failure cases, fractally).
        self.facet_depth = max(1, int(cfg.get("facet_depth", 1)))
        self.budget = BudgetController(max_total_nodes=int(cfg.get("max_total_ideas", 40)))
        # When False, skip the security scan (e.g. tests/perf); weighting stays static.
        self.security_aware = bool(cfg.get("security_aware", True))
        # Opt-in (DEFAULT FALSE = byte-identical scoring): when on, an idea whose
        # subject module the cheap/pure ``idea_synthesis_signals`` prove LANDABLE
        # (a real implement-stub / type-hint / dataclass / modernize / dedup diff
        # is producible) earns a bounded scoring bonus, so a verifiable concrete
        # contribution outranks a pure-analysis idea on the same budget. Off →
        # ``_landable_subjects`` stays empty → the bonus is 0.0 for every node, so
        # existing idea sets do not shift.
        self.landability_aware = bool(cfg.get("landability_aware", False))
        # Opt-in COST tier for the landability scan (DEFAULT FALSE): when on, the
        # scan ALSO probes the five high-value but suite-cost signals (cover-gaps,
        # tdd, strengthen, wire-exports, generate-usage-doc) — the work the North
        # Star cares about most — and the seeder's value-led ``::landable-*`` family
        # fires. Off ⇒ only the 6 cheap pure-read signals run (the historical fast
        # ranking contract), so the default ``plan``/``ascend`` board never runs a
        # suite while merely ranking. Requires ``landability_aware`` to take effect.
        self.landability_deep = bool(cfg.get("landability_deep", False))
        # Opt-in: append fused cross-engine discovery leads as recommend-only
        # roots (default off = byte-identical seeding). Forwarded to the seeder.
        self.seed_discoveries = bool(cfg.get("seed_discoveries", False))
        self._security_pressure = 1.0
        # The LANDABLE subject modules → the BEST (highest) buyer value of any
        # landable signal that matched them (computed ONCE per run in ``_begin_run``
        # when ``landability_aware`` is on). A mapping, not a set, so the bonus is
        # GRADED by the kind of move that lands: a stub-landable module (1.0) earns
        # the full cap, a sort-landable one (0.18) a fraction. Initialized empty so
        # a caller that drives ``_score`` directly without ``_begin_run`` (e.g. unit
        # tests) sees the off-by-default behavior — an empty mapping → no bonus.
        self._landable_subjects: dict[str, float] = {}
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

    def _facet_share(self) -> float:
        """The slice of the node budget the fractal zoom may claim.

        Identical to the historical 12% for zoom depth <= 2; stretches
        proportionally with the *requested* depth (incl. the adaptive bonus,
        capped at 30%) so asking for a deep zoom actually buys levels instead
        of exhausting the slice while the base levels are still being laid.
        """
        if not self.fractal_facets:
            return 0.0
        bonus = self.adaptive_depth_bonus if self.adaptive_depth else 0
        max_level = self.facet_depth + bonus
        return min(0.30, 0.12 * max(1.0, max_level / 2))

    def run(self, objective: str | None = None) -> IdeaTreeReport:
        # Orchestrator: seed → permute → facets → synthesize → measure. Each
        # phase is a cohesive helper below; the order and budget hand-off here
        # are the only behaviour this method itself owns.
        profile, relevance, graph, stats = self._begin_run(objective)

        emitted = self._seed_roots(profile, objective, relevance, graph)
        perm_cap = self._reserve_perm_cap(len(emitted))
        self._expand_permutations(emitted, relevance, graph, stats, perm_cap)

        # Fractal facets: zoom the strongest leaves into self-similar sub-ideas
        # before synthesis claims the remaining budget.
        if self.fractal_facets:
            self._expand_facets(emitted, relevance, graph, stats)

        self._emit_synthesis(emitted, profile, relevance, graph, stats)
        self._attach_stats(emitted, profile, stats)
        return IdeaTreeReport(
            objective=objective or "",
            project_root=self.project_root,
            ideas=emitted,
            branch_map={i.branch_path: i.title for i in emitted},
            stats=stats,
        )

    def _begin_run(
        self, objective: str | None
    ) -> tuple[ProjectProfile, RelevanceScorer, GraphStore, dict[str, Any]]:
        """Set up the per-run scoring context (profile, trends, relevance, dedup
        graph, novelty counters, security pressure, learning memory) and return
        the handles the later phases share. No ideas are produced here."""
        profile = self.profiler.profile()
        self.last_profile = profile  # recorders (signal trends) read this
        # Temporal convergence: which modules got WORSE since the last
        # recorded snapshot (rising churn while a risk on them ages)?
        # No history file -> empty -> identical to a fresh engine.
        try:
            from app.engine.signal_trends import SignalTrends

            self._accelerating = {
                d["module"]: d
                for d in SignalTrends(self.project_root).accelerating(profile)
            }
        except Exception:
            self._accelerating = {}
        relevance = RelevanceScorer(objective or "")
        self._has_objective = bool(objective and objective.strip())
        graph = GraphStore()  # reused purely for near-duplicate idea detection
        self.novelty = NoveltyScorer(graph)  # reuse the dedup-backed scorer
        self._chain_counts: dict[str, int] = {}  # per-run, for deterministic novelty
        self._subject_counts: dict[str, int] = {}  # subject-diversity novelty signal
        self._source_cache: dict[str, str | None] = {}  # subject-module sources (facet evidence)
        # Security pressure: how strongly real findings should bias harden/test
        # weighting. Scales 1.0 (none) → up to 1.3 (many findings). Best-effort.
        self._security_pressure = self._scan_security_pressure()
        # Landability set: which subject modules a verifiable concrete change can
        # land on (cheap/pure synthesis signals only). Computed ONCE here so the
        # per-node scoring stays a pure set membership; empty when the flag is off
        # (→ byte-identical scoring) or the scan finds/yields nothing.
        self._landable_subjects = (
            self._scan_landable_subjects(profile)
            if self.landability_aware else {}
        )
        # Learning memory: bounded feasibility nudges from past apply outcomes.
        if self.learning:
            from app.engine.idea_memory import IdeaMemory

            self._memory = IdeaMemory.load(self.project_root)
        stats = {"considered": 0, "pruned_relevance": 0, "pruned_duplicate": 0}
        return profile, relevance, graph, stats

    def _seed_roots(
        self,
        profile: ProjectProfile,
        objective: str | None,
        relevance: RelevanceScorer,
        graph: GraphStore,
    ) -> list[IdeaNode]:
        """Emit the seeder's root ideas (scored, deduped against the graph,
        budgeted) and return them as the initial ``emitted`` list."""
        emitted: list[IdeaNode] = []
        for root in self.seeder.seed(profile, objective, accelerating=self._accelerating,
                                     seed_discoveries=self.seed_discoveries,
                                     landability_deep=self.landability_deep):
            if self.budget.exhausted:
                break
            self._score(root, relevance)
            graph.register_claim(root.title)
            self.budget.consume_node()
            emitted.append(root)
        return emitted

    def _reserve_perm_cap(self, emitted_count: int) -> int:
        """Carve the synthesis (and optional facet) budget slices off the top so
        mechanical permutation can't crowd out the genuinely-new ideas, and
        return the cap on how many ideas permutation expansion may leave behind."""
        self._synth_reserve = max(4, int(self.budget.max_total_nodes * 0.15))
        facet_reserve = (
            max(2, int(self.budget.max_total_nodes * self._facet_share()))
            if self.fractal_facets else 0
        )
        return max(
            emitted_count,
            self.budget.max_total_nodes - self._synth_reserve - facet_reserve,
        )

    def _expand_permutations(
        self,
        emitted: list[IdeaNode],
        relevance: RelevanceScorer,
        graph: GraphStore,
        stats: dict[str, Any],
        perm_cap: int,
    ) -> None:
        """Best-first, diversity-aware permutation expansion. Appends children to
        ``emitted`` in place until the budget or ``perm_cap`` is hit.

        A subject that has already produced many ideas is temporarily
        down-ranked so the tree spreads across modules instead of over-mining
        one hub. This shapes *selection order* only — node.value is untouched.
        """
        frontier = list(emitted)
        emitted_by_subject: dict[str, int] = {}
        for n in emitted:
            emitted_by_subject[n.subject] = emitted_by_subject.get(n.subject, 0) + 1

        def _priority(n: IdeaNode) -> float:
            return n.value - 0.05 * emitted_by_subject.get(n.subject, 0)

        while frontier and not self.budget.exhausted and len(emitted) < perm_cap:
            frontier.sort(key=_priority, reverse=True)
            node = frontier.pop(0)
            if node.depth >= self._effective_max_depth(node):
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

    def _emit_synthesis(
        self,
        emitted: list[IdeaNode],
        profile: ProjectProfile,
        relevance: RelevanceScorer,
        graph: GraphStore,
        stats: dict[str, Any],
    ) -> None:
        """Append the synthesized ideas (genuinely new beyond mechanical
        permutation) from the reserved budget slice, recording the count."""
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

    def _attach_stats(
        self,
        emitted: list[IdeaNode],
        profile: ProjectProfile,
        stats: dict[str, Any],
    ) -> None:
        """Compute the measured grounding stats (totals, mean value, fan-in,
        per-module metrics) that downstream consumers like the roadmap read."""
        stats["total_ideas"] = len(emitted)
        stats["mean_value"] = (
            round(sum(i.value for i in emitted) / len(emitted), 4) if emitted else 0.0
        )
        # Measured fan-in (in-degree) per idea subject: how many modules import
        # it. A real blast-radius signal downstream consumers (the roadmap) use
        # to ground impact in structure rather than re-deriving it from value.
        fan_in_all: dict[str, int] = {}
        for _src, tgt in (getattr(profile, "dependency_edges", []) or []):
            fan_in_all[tgt] = fan_in_all.get(tgt, 0) + 1
        subjects = {i.subject.split(" :: ", 1)[0] for i in emitted}
        stats["fan_in"] = {m: fan_in_all[m] for m in subjects if m in fan_in_all}

        # Measured size/complexity per idea subject (cheap: only the modules the
        # tree references). Grounds the roadmap's effort estimate in real code.
        try:
            from app.tools.code_metrics import CodeMetrics

            file_subjects = [m for m in subjects if m.endswith(".py")]
            metrics = CodeMetrics(self.project_root).for_modules(file_subjects)
            stats["metrics"] = {m: mm.to_dict() for m, mm in metrics.items()}
        except (OSError, ImportError) as exc:
            # Metrics are optional grounding for effort; degrade gracefully but
            # narrowly (don't mask programming errors inside CodeMetrics).
            stats["metrics"] = {}
            stats["metrics_error"] = str(exc)

    # Risk dimensions a module can be flagged by. Each is an *independent*
    # concern, so a subject triggering two of them is genuinely higher-leverage
    # than one. Coverage is a single dimension (a module can't be both untested
    # and shallow), resolved to its most-severe present label below.
    _CONVERGENCE_DIMS = [
        ("sensitive_paths", "security-sensitive"),
        ("security_finding_modules", "security-sensitive"),
        ("correctness_bug_modules", "a likely crash bug"),
        ("hotspot_modules", "a complexity hotspot"),
        ("fragile_modules", "fragile"),
        ("dependency_hubs", "a central dependency hub"),
        ("debt_marker_modules", "debt-laden"),
    ]

    # Themes: one signal spread across many modules is a systemic initiative, not
    # N chores. (profile attribute, min modules, fact label, title verb, lens).
    _THEMES = [
        ("security_finding_modules", 3, "security-theme",
         "Run a security-hardening pass across", "harden"),
        ("modernizable_modules", 3, "modernize-theme",
         "Modernize the None comparisons across", "simplify"),
        ("mutable_default_modules", 3, "mutable-theme",
         "Fix mutable default arguments across", "harden"),
        ("untested_modules", 4, "coverage-theme",
         "Establish baseline test coverage across", "test"),
        ("shallow_tested_modules", 3, "depth-theme",
         "Deepen the shallow tests across", "test"),
        ("debt_marker_modules", 3, "debt-theme",
         "Clear the clustered TODO/FIXME debt across", "simplify"),
    ]

    # Landability scan (opt-in, see ``landability_aware``). Probe at most this many
    # candidate modules (bounds cost; matches the action bridge's own synthesis
    # candidate cap). Each signal name maps to the OPERATOR its lander would run, so
    # the bonus can be sized by that move's buyer value (``move_value``) — a stub
    # lander earns the full cap, a sort lander a fraction. Two cost tiers:
    #
    #   * the CHEAP/PURE tier (always, when the flag is on) — each is a pure-source
    #     read that mirrors the lander's own gate, no suite run while merely ranking
    #     (the historical fast-ranking contract);
    #   * the DEEP tier (only when ``landability_deep`` is also on) — the five
    #     high-value but suite-cost signals the North Star cares about most. They
    #     are STILL the lander's own diff-producing gate, so surfacing them never
    #     over-promises; they just cost a suite, so they stay behind the explicit
    #     deep flag and out of the fast plan/ascend board.
    _LANDABLE_CANDIDATE_LIMIT = 40
    _LANDABLE_SIGNAL_OPERATORS: dict[str, str] = {
        "fillable_stub_modules": "implement_stub",
        "inferable_return_modules": "infer_type_hints",
        "dataclassifiable_modules": "dataclassify",
        "modernizable_modules": "modernize",
        "dedup_total_return_modules": "dedup_total_return",
        "dedup_parameterizable_modules": "dedup_parameterized",
    }
    _LANDABLE_DEEP_SIGNAL_OPERATORS: dict[str, str] = {
        "cover_gaps_modules": "cover_gaps",
        "tdd_implementable_symbols": "tdd_implement",
        "strengthenable_modules": "strengthen_tests",
        "wire_export_packages": "wire_exports",
        "generate_usage_doc_packages": "generate_usage_doc",
    }

    def _scan_landable_subjects(self, profile: ProjectProfile) -> dict[str, float]:
        """The subject modules a verifiable concrete change can LAND on, each
        mapped to the BEST (highest) buyer value of any landable signal that
        matched it.

        Reuses the existing honest ``idea_synthesis_signals`` (each returns only
        modules whose REAL lander would produce a diff, so this never over-promises
        a landability) over a bounded, deterministic candidate set drawn from the
        profile. The per-subject reduction takes a ``max`` of ``move_value`` over a
        FIXED signal order, so the GRADED bonus ranks a high-value concrete
        contribution above a low-value one — using the SAME value model the move
        loop uses (Layers a and b can never disagree). Pure and best-effort: any
        failure yields the empty mapping rather than perturbing the run, and the
        inputs are sorted/capped so the result is deterministic for a given repo
        state — no clock, no randomness.

        The DEEP (suite-cost) signals run ONLY when ``landability_deep`` is on, so
        the default ranking path stays the 6 cheap pure-read signals.

        GOTCHA: ``ProjectProfile`` has no single attribute enumerating every ``.py``
        module, so the candidate set is the union of ``module_to_tests`` keys (the
        full set of analyzed production modules) with every module-valued profile
        list — a defensive superset that survives a profile variant leaving any one
        of them empty.
        """
        candidates = self._landable_candidates(profile)
        if not candidates:
            return {}
        signals = dict(self._LANDABLE_SIGNAL_OPERATORS)
        if self.landability_deep:
            signals.update(self._LANDABLE_DEEP_SIGNAL_OPERATORS)
        try:
            from app.engine import idea_synthesis_signals as sigs
            from app.engine.move_value import move_value

            landable: dict[str, float] = {}
            for signal_name, operator in signals.items():
                signal = getattr(sigs, signal_name)
                value = move_value(operator)
                for module in signal(self.project_root, candidates,
                                     limit=self._LANDABLE_CANDIDATE_LIMIT):
                    # Symbol signals return "<module>:<name>"; keep the module half
                    # so the subject membership test matches a path. Record the BEST
                    # value seen for the subject (a module landable by several moves
                    # is worth its most valuable one).
                    base = module.split(":", 1)[0]
                    if value > landable.get(base, 0.0):
                        landable[base] = value
            return landable
        except Exception:
            return {}

    @classmethod
    def _landable_candidates(cls, profile: ProjectProfile) -> list[str]:
        """The bounded, sorted ``.py`` candidate set the landability signals probe.

        Union of ``module_to_tests`` keys with every module-valued profile list, so
        a single empty attribute can't blind the scan; sorted + capped for
        determinism and cost."""
        mods: set[str] = set(getattr(profile, "module_to_tests", {}) or {})
        for attr in ("untested_modules", "critical_untested_modules",
                     "modernizable_modules", "mutable_default_modules",
                     "debt_marker_modules", "shallow_tested_modules",
                     "fragile_modules", "hotspot_modules",
                     "security_finding_modules", "correctness_bug_modules"):
            mods.update(getattr(profile, attr, None) or [])
        mods.update(getattr(profile, "module_fanin", {}) or {})
        return sorted(m for m in mods if m.endswith(".py"))[:cls._LANDABLE_CANDIDATE_LIMIT]

    def _thematic_ideas(
        self, profile: ProjectProfile, relevance: RelevanceScorer, graph: GraphStore
    ) -> list[IdeaNode]:
        """One signal affecting many modules -> a single systemic initiative.

        The horizontal complement to convergence: instead of N separate
        per-module chores, name the pattern once and list every module it
        touches, so a project-wide issue reads as a project-wide decision.
        """
        out: list[IdeaNode] = []
        for idx, (attr, threshold, label, verb, lens) in enumerate(self._THEMES):
            modules = list(dict.fromkeys(getattr(profile, attr, []) or []))
            if len(modules) < threshold:
                continue
            shown = ", ".join(modules[:4]) + (", ..." if len(modules) > 4 else "")
            node = IdeaNode(
                id=f"theme-{idx}",
                title=f"{verb} {len(modules)} modules ({shown})",
                subject=modules[0],          # a real target for the action bridge
                rationale=(
                    f"Synthesized theme: {len(modules)} modules share this signal "
                    f"({shown}) - treat it as one systemic pass, not scattered fixes."
                ),
                branch_path=f"x.t{idx}",
                depth=1,
                operator="synthesis",
                operator_chain=[lens],
                source_facts=[f"theme: {label} ({len(modules)} modules)"],
                kind="synthesis",
                feasibility=0.6,
            )
            self._score(node, relevance)
            if not graph.has_similar_claim(node.title):
                out.append(node)
        return out

    def _collect_convergence_dims(
        self, profile: ProjectProfile
    ) -> dict[str, list[str]]:
        """Map each subject to the distinct risk dimensions independently
        flagging it (the raw material convergence is read off)."""
        from collections import defaultdict

        dims_by_subject: dict[str, list[str]] = defaultdict(list)

        for subject, label in self._structural_dims(profile):
            # Distinct dimensions only: two signals that mean the same thing
            # (name-sensitive AND content-finding both → "security-sensitive")
            # count as one, so they can't fake a convergence by themselves.
            if label not in dims_by_subject[subject]:
                dims_by_subject[subject].append(label)

        for subject, label in self._coverage_dims(profile):
            dims_by_subject[subject].append(label)
        return dims_by_subject

    def _structural_dims(self, profile: ProjectProfile):
        """Yield the (subject, label) risk dimensions read off the profile's
        structure (the list-valued signals, churn, and acceleration), in the
        original order, before coverage labels are layered on."""
        for attr, label in self._CONVERGENCE_DIMS:
            for subject in (getattr(profile, attr, []) or []):
                yield subject, label
        yield from self._churn_dims(profile)
        # The time dimension: a subject getting WORSE since the last snapshot
        # converges with whatever else flags it — urgency from the slope.
        for subject in (getattr(self, "_accelerating", {}) or {}):
            yield subject, "accelerating"

    @staticmethod
    def _churn_dims(profile: ProjectProfile):
        """Churn carries its count, so it isn't a plain module list: a subject
        many recent commits touch adds the "high-churn" dimension — combined
        with a complexity hotspot this is the classic change×complexity hotspot,
        the strongest refactoring mandate structure analysis offers."""
        for spot in (getattr(profile, "churn_hotspots", []) or []):
            subject = spot.get("module", "")
            if subject:
                yield subject, "high-churn"

    @staticmethod
    def _coverage_dims(profile: ProjectProfile) -> list[tuple[str, str]]:
        """Coverage is one dimension; emit the most-severe label a subject
        carries, in the original deterministic (sorted-subject) order."""
        crit = set(getattr(profile, "critical_untested_modules", []) or [])
        untested = set(getattr(profile, "untested_modules", []) or [])
        shallow = set(getattr(profile, "shallow_tested_modules", []) or [])
        out: list[tuple[str, str]] = []
        for subject in sorted(crit | untested | shallow):
            if subject in crit:
                out.append((subject, "critically untested"))
            elif subject in untested:
                out.append((subject, "untested"))
            else:
                out.append((subject, "only shallowly tested"))
        return out

    @staticmethod
    def _make_convergence_node(idx: int, subject: str, labels: list[str]) -> IdeaNode:
        """Build the convergence idea for a subject and its agreeing labels."""
        n = len(labels)
        return IdeaNode(
            id=f"conv-{idx}",
            title=f"Prioritize {subject} — {n} independent analyses converge ({_join_phrase(labels)})",
            subject=subject,
            rationale=(
                f"Synthesized: {n} independent signals flag this same module, so "
                "convergence marks it the highest-leverage target — stabilize and "
                "secure it before lower-agreement work."
            ),
            branch_path=f"x.c{idx}",
            depth=1,
            operator="synthesis",
            operator_chain=["harden"],
            source_facts=[f"convergence: {'+'.join(labels)}"],
            kind="synthesis",
            # More converging signals = a clearer, higher-priority mandate.
            feasibility=min(0.95, 0.7 + 0.1 * n),
        )

    def _convergence_ideas(
        self, profile: ProjectProfile, relevance: RelevanceScorer, graph: GraphStore
    ) -> list[IdeaNode]:
        """Subjects independently flagged by >=2 risk dimensions — the engine's
        highest-leverage targets, where multiple analyses agree."""
        dims_by_subject = self._collect_convergence_dims(profile)
        converged = [
            (subject, labels) for subject, labels in dims_by_subject.items()
            if len(labels) >= 2
        ]
        # Strongest convergence first (more agreeing signals → higher priority).
        converged.sort(key=lambda t: (-len(t[1]), t[0]))

        out: list[IdeaNode] = []
        for idx, (subject, labels) in enumerate(converged[:3]):
            node = self._make_convergence_node(idx, subject, labels)
            self._score(node, relevance)
            if not graph.has_similar_claim(node.title):
                out.append(node)
        return out

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

        # 0. Convergence synthesis (highest priority) — the engine's own
        # "everything points here" insight: a single subject independently
        # flagged by two or more *different* risk dimensions is a higher-leverage
        # target than any one signal implies. This reasons across the profile's
        # signals instead of mining one fact at a time.
        out.extend(self._convergence_ideas(profile, relevance, graph))

        # 0b. Thematic synthesis — the horizontal complement to convergence: a
        # *single* signal affecting *many* modules is a systemic theme, not N
        # scattered chores. The engine surfaces it as one initiative naming the
        # whole affected set, so a project-wide pattern reads as a project-wide
        # decision.
        out.extend(self._thematic_ideas(profile, relevance, graph))

        # 1. Cross-lens synthesis per subject.
        out.extend(self._cross_lens_ideas(emitted, relevance, graph))

        # 2. Module-pair ideas (cycles, then co-change, then plain edges), all
        # sharing one bounded `pidx`/dedup state so the strongest coupling
        # evidence claims the low branch paths.
        state = _PairState()
        in_cycle = self._cycle_ideas(profile, relevance, graph, out, state)
        self._cochange_ideas(profile, relevance, graph, out, state)
        self._edge_ideas(profile, relevance, graph, out, state, in_cycle)
        return out

    def _emit_synth(
        self, node: IdeaNode, relevance: RelevanceScorer, graph: GraphStore,
        out: list[IdeaNode],
    ) -> bool:
        """Score a synthesized candidate and append it unless it duplicates an
        existing claim. Returns whether it was kept (so callers advance their
        index only on success, exactly as before)."""
        self._score(node, relevance)
        if graph.has_similar_claim(node.title):
            return False
        out.append(node)
        return True

    def _cross_lens_ideas(
        self, emitted: list[IdeaNode], relevance: RelevanceScorer, graph: GraphStore,
    ) -> list[IdeaNode]:
        """If a subject got BOTH 'test' and 'harden' lenses, propose a dedicated
        security-focused test suite for it."""
        lenses_by_subject: dict[str, set[str]] = {}
        for idea in emitted:
            if idea.subject:
                lenses_by_subject.setdefault(idea.subject, set()).update(idea.operator_chain)
        out: list[IdeaNode] = []
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
                if self._emit_synth(node, relevance, graph, out):
                    sidx += 1
        return out

    def _cycle_ideas(
        self, profile: ProjectProfile, relevance: RelevanceScorer, graph: GraphStore,
        out: list[IdeaNode], state: _PairState,
    ) -> set[str]:
        """Import-cycle ideas — real cycles incl. indirect A->B->C->A, from the
        dependency graph's cycle detector. Returns the set of modules covered so
        they aren't re-proposed as plain interface pairs."""
        in_cycle: set[str] = set()
        for cycle in (getattr(profile, "import_cycles", []) or [])[:3]:
            if state.pidx >= 4:
                break
            ring = " → ".join(cycle)
            members = [m for m in cycle if m]
            in_cycle.update(members)
            node = IdeaNode(
                id=f"pair-{state.pidx}",
                title=f"Break the import cycle {ring}",
                subject="↔".join(dict.fromkeys(members)),
                rationale=f"Synthesized: {len(set(members))} modules form an import cycle.",
                branch_path=f"x.p{state.pidx}",
                depth=1,
                operator="synthesis",
                operator_chain=["integrate"],
                source_facts=["dependency-cycle"],
                kind="pair",
            )
            if self._emit_synth(node, relevance, graph, out):
                state.pidx += 1
        return in_cycle

    def _cochange_ideas(
        self, profile: ProjectProfile, relevance: RelevanceScorer, graph: GraphStore,
        out: list[IdeaNode], state: _PairState,
    ) -> None:
        """Co-change pairs (temporal coupling): modules that repeatedly change
        in the SAME commits are factually coupled, whether or not an import
        connects them — the hidden seam static analysis can't see. Measured
        evidence, so these outrank plain dependency-edge pairs below."""
        for cc in (getattr(profile, "change_coupling", []) or []):
            if state.pidx >= 5:
                break
            a, b, n = cc.get("a", ""), cc.get("b", ""), cc.get("commits", 0)
            key = tuple(sorted((a, b)))
            if not a or not b or key in state.seen_pairs:
                continue
            state.seen_pairs.add(key)
            node = IdeaNode(
                id=f"pair-{state.pidx}",
                title=f"Decouple {a} and {b} — they changed together in {n} commits",
                subject=f"{a}\N{LEFT RIGHT ARROW}{b}",
                rationale=("Synthesized: temporal coupling measured from git history — "
                           "these modules co-change whether or not an import connects them."),
                branch_path=f"x.p{state.pidx}",
                depth=1,
                operator="synthesis",
                operator_chain=["integrate"],
                source_facts=[f"co-change: {a} + {b} ({n} commits together)"],
                kind="pair",
            )
            if self._emit_synth(node, relevance, graph, out):
                state.pidx += 1

    def _edge_ideas(
        self, profile: ProjectProfile, relevance: RelevanceScorer, graph: GraphStore,
        out: list[IdeaNode], state: _PairState, in_cycle: set[str],
    ) -> None:
        """Plain coupling ideas for dependency edges not already inside a
        reported cycle."""
        edges = getattr(profile, "dependency_edges", []) or []
        for source, target in edges:
            if state.pidx >= 5:  # keep total pair ideas bounded
                break
            if source in in_cycle and target in in_cycle:
                continue
            key = tuple(sorted((source, target)))
            if key in state.seen_pairs:
                continue
            state.seen_pairs.add(key)
            node = IdeaNode(
                id=f"pair-{state.pidx}",
                title=f"Standardize the interface between {source} and {target}",
                subject=f"{source}↔{target}",
                rationale="Synthesized: a dependency edge couples these modules.",
                branch_path=f"x.p{state.pidx}",
                depth=1,
                operator="synthesis",
                operator_chain=["integrate"],
                source_facts=["dependency-edge"],
                kind="pair",
            )
            if self._emit_synth(node, relevance, graph, out):
                state.pidx += 1

    def _effective_max_depth(self, node: IdeaNode) -> int:
        """How deep this branch may go. Adaptive mode lets high-value branches
        (where value, and learned reliability, concentrate) exceed the base depth
        by a bounded bonus, so the fractal deepens exactly where it pays off."""
        if self.adaptive_depth and node.value >= self.adaptive_depth_threshold:
            return self.max_depth + self.adaptive_depth_bonus
        return self.max_depth

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
        leaves = self._facet_leaves(emitted)

        # Adaptive zoom: high-value branches grow past the base facet_depth by a
        # bounded bonus, so the fractal *sharpens where it pays off* instead of
        # faceting every leaf uniformly. The base levels stay wide; each extra
        # adaptive level narrows to the single strongest branch — a deep spike on
        # the most valuable leaf rather than shallow breadth everywhere.
        bonus = self.adaptive_depth_bonus if self.adaptive_depth else 0
        max_level = self.facet_depth + bonus

        # Same stretched share that run() reserved out of the permutation cap,
        # so the room the permutation tree left is exactly the room we may use.
        facet_cap = max(2, int(self.budget.max_total_nodes * self._facet_share()))
        # Never spend the slice reserved for synthesis.
        synth_floor = self.budget.max_total_nodes - getattr(self, "_synth_reserve", 0)
        counter = {"added": 0}

        def _stop() -> bool:
            return (
                self.budget.exhausted
                or counter["added"] >= facet_cap
                or len(emitted) >= synth_floor
            )

        # Per-level source cap: split the facet budget across ALL the zoom levels
        # (including the adaptive bonus) so the wide base levels leave room for
        # the deep spike — otherwise level 1 alone would exhaust the cap.
        per_level = max(2, facet_cap // (self.facets_per_idea * max_level))

        # Level-by-level (BFS) fractal zoom: each level's facets become the next
        # level's sources, up to ``max_level``. Best-first within a level.
        sources = leaves
        for level in range(1, max_level + 1):
            if _stop():
                break
            sources = self._select_level_sources(sources, level, per_level)
            sources = self._emit_facet_level(
                sources, level, emitted, relevance, graph, counter, _stop
            )
        stats["faceted"] = counter["added"]

    @staticmethod
    def _facet_leaves(emitted: list[IdeaNode]) -> list[IdeaNode]:
        """The permutation leaves eligible to open into facets.

        A leaf is a non-root permutation idea with a known facet vocabulary that
        itself produced no permutation children.
        """
        perm_parents = {
            n.parent_id for n in emitted if n.kind == "permutation" and n.parent_id
        }
        return [
            n for n in emitted
            if n.kind == "permutation"
            and n.operator != "root"
            and n.operator in _FACETS
            and n.id not in perm_parents
            # Executable ``<module>::simplify-<transform>`` ideas are atomic, fully
            # specified fixes ("apply exactly this rewrite"), not decomposable
            # development directions — fractally zooming them ("...:: dead code")
            # is noise, and the extra leaves crowd the best-first facet selection
            # so the genuine ladder paths no longer reach their deep L3 phrases.
            and "::simplify-" not in n.subject
        ]

    def _select_level_sources(
        self, sources: list[IdeaNode], level: int, per_level: int
    ) -> list[IdeaNode]:
        """Best-first selection of the sources to facet at this zoom level.

        Base levels facet the top ``per_level``; adaptive extra levels keep only
        the single strongest branch (and only while it stays valuable).
        """
        sources = sorted(
            sources, key=lambda n: (n.value, n.branch_path), reverse=True
        )
        if level <= self.facet_depth:
            return sources[:per_level]
        return [s for s in sources[:1] if s.value >= self.adaptive_depth_threshold]

    def _emit_facet_level(
        self,
        sources: list[IdeaNode],
        level: int,
        emitted: list[IdeaNode],
        relevance: RelevanceScorer,
        graph: GraphStore,
        counter: dict[str, int],
        stop: Any,
    ) -> list[IdeaNode]:
        """Score and emit one BFS level of facets; return the next level's sources."""
        next_sources: list[IdeaNode] = []
        for src in sources:
            if stop():
                break
            for child in self._facet_children(src, level):
                if stop():
                    break
                if graph.has_similar_claim(child.title):
                    continue
                self._score(child, relevance)
                # _score recomputes feasibility only for roots, so the
                # inherited feasibility on the facet is preserved.
                graph.register_claim(child.title)
                self.budget.consume_node()
                emitted.append(child)
                counter["added"] += 1
                next_sources.append(child)
        return next_sources

    @staticmethod
    def _facet_caveat(phrase: str) -> str:
        """A stress-test specific to a facet sub-concern, so the fractal deepens
        its *reasoning*, not just its title — keyed by the theme of the phrase so
        all ~75 facet phrases are covered without per-phrase hand-writing."""
        p = phrase.lower()
        for keys, caveat in _FACET_CAVEAT_RULES:
            if any(k in p for k in keys):
                return caveat
        return ""

    def _facet_vocab(self, node: IdeaNode, level: int) -> list[str]:
        """Facet phrases available to refine ``node`` at the given zoom level.

        Level 1 uses the operator's aspect vocabulary; deeper levels use the
        common/boundary/failure case split, excluding any case already applied
        on this branch so a chain never repeats itself.
        """
        if level == 1:
            return _FACETS.get(node.operator, [])
        facet_labels = [
            f.split("facet:", 1)[1].strip()
            for f in node.source_facts
            if f.startswith("facet:")
        ]
        used = set(facet_labels)
        # Prefer the most-recent aspect's own sub-concerns, so the zoom keeps
        # descending into specifics; only fall to the universal case split once
        # an aspect has no finer vocabulary of its own.
        last = facet_labels[-1] if facet_labels else ""
        subs = [s for s in _FACET_SUBASPECTS.get(last, []) if s not in used]
        if subs:
            return subs
        return [c for c in _FACET_CASES if c not in used]

    def _subject_source(self, subject: str) -> str | None:
        """The subject module's source (cached per run) — or None for abstract
        subjects ("CI pipeline") that have no file to look at."""
        base = subject.split(" :: ", 1)[0].split("::", 1)[0]
        if not base.endswith(".py"):
            return None
        if base not in self._source_cache:
            try:
                self._source_cache[base] = (Path(self.project_root) / base).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                self._source_cache[base] = None
        return self._source_cache[base]

    def _facet_children(self, node: IdeaNode, level: int) -> list[IdeaNode]:
        """Build the facet sub-ideas that zoom into ``node`` at ``level``.

        Each facet is *grounded where possible*: the canonical detector checks
        the subject's actual code for the concern the phrase names, so a facet
        is either a verified observation (with file:line evidence) or an honest
        hypothesis — and the value-guided spike follows the evidence.
        """
        from app.engine.facet_evidence import evidence_for_facet

        children: list[IdeaNode] = []
        # The zoom path so far ("failure modes → partial or interrupted
        # operation") — the rationale should narrate the descent, not recite ids.
        zoom_path = [
            f.split("facet:", 1)[1].strip()
            for f in node.source_facts if f.startswith("facet:")
        ]
        base = node.subject.split(" :: ", 1)[0]
        source = self._subject_source(node.subject)
        for j, phrase in enumerate(self._facet_vocab(node, level)[: self.facets_per_idea]):
            trail = " → ".join([*zoom_path, phrase])
            evidence = evidence_for_facet(source, phrase) if source else []
            facts = list(node.source_facts) + [f"facet: {phrase}"]
            rationale = (
                f"Fractal zoom L{level} on {base}: {trail} — each level narrows "
                f"the work to one concern an engineer can act on."
            )
            if evidence:
                line, detail = evidence[0]
                facts += [f"evidence: {base}:{ln} — {d}" for ln, d in evidence]
                rationale = (
                    f"Fractal zoom L{level} on {base}: {trail} — verified in the "
                    f"code: line {line}, {detail}."
                )
            children.append(
                IdeaNode(
                    id=f"{node.id}-f{j}",
                    title=f"{node.title} — {phrase}",
                    subject=f"{node.subject} :: {phrase}",
                    rationale=rationale,
                    branch_path=f"{node.branch_path}.f{j}",
                    depth=node.depth + 1,
                    parent_id=node.id,
                    operator=node.operator,
                    operator_chain=list(node.operator_chain),
                    source_facts=facts,
                    feasibility=node.feasibility,
                    kind="facet",
                )
            )
        return children

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
        self._score_signals(node, relevance)
        node.value = self._score_value(node)
        self._attach_caveats(node)

    def _score_signals(self, node: IdeaNode, relevance: RelevanceScorer) -> None:
        """Set ``relevance``, ``feasibility`` (with the learning nudge) and
        ``novelty`` on the node — the per-signal inputs the value blend reads."""
        # Score relevance against the idea's *grounding* — its title, subject,
        # fact labels, and lens chain — not just the rendered title. A "security"
        # objective should match a harden/sensitive-path/security-finding idea
        # via concept expansion, even though those words never appear in the
        # generated title.
        grounding = " ".join(node.source_facts + node.operator_chain + [node.operator])
        node.relevance = relevance.score(f"{node.title} {node.subject} {grounding}")
        if node.operator == "root":
            node.feasibility = node.feasibility or 0.7
        # Learning nudge: tilt feasibility by this lens/label's past track record
        # on this project (bounded ±10%, clamped). No-op without a memory file.
        if self._memory is not None:
            label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
            factor = self._memory.feasibility_factor(node.operator, label)
            if factor != 1.0:
                node.feasibility = round(min(1.0, max(0.0, node.feasibility * factor)), 4)
        node.novelty = self._novelty(node)

    def _score_value(self, node: IdeaNode) -> float:
        """Blend relevance/novelty/feasibility into the node's value, then layer
        the bounded convergence/evidence/magnitude bonuses on top."""
        # Weight calibration: relevance only discriminates when an objective is
        # set (otherwise it is constant 1.0 and the 0.4 term is dead, flattening
        # scores). With no objective, redistribute that weight to the signals
        # that actually vary — novelty and feasibility.
        if self._has_objective:
            value = round(
                0.4 * node.relevance + 0.3 * node.novelty + 0.3 * node.feasibility, 4
            )
        else:
            value = round(
                0.2 * node.relevance + 0.4 * node.novelty + 0.4 * node.feasibility, 4
            )
        # Convergence bonus: a node where N independent analyses agree is, by its
        # own definition, the highest-leverage target — so make the *number*
        # agree with the prose. Each extra agreeing signal lifts value (clamped
        # to <= 1.0), so convergence sorts to the top of the value-ordered plan
        # instead of contradicting its "highest-leverage" rationale.
        conv = convergence_labels(node)
        if len(conv) >= 2:
            value = round(min(1.0, value + 0.08 * (len(conv) - 1)), 4)
        # Evidence bonus: a facet whose concern was verified in the actual code
        # (a real finding at a real line) outranks a sibling hypothesis, so the
        # value-guided zoom drills into what is *demonstrably* there.
        if node.kind == "facet" and any(f.startswith("evidence:") for f in node.source_facts):
            value = round(min(1.0, value + 0.08), 4)
        # Magnitude bonus: when the seeding fact carries a MEASURED quantity —
        # months a finding/debt has sat in the code, commits of churn, branch
        # complexity — the number itself moves the ranking (bounded like the
        # other bonuses). One mechanism for every measured signal: a 14-month
        # exposure outranks a fresh one, a 50-commit hotspot outranks a
        # 5-commit one, without any signal-specific special cases.
        if node.operator == "root":
            bonus = _magnitude_bonus(node)
            if bonus:
                value = round(min(1.0, value + bonus), 4)
        # Landability bonus (opt-in; ``_landable_subjects`` is empty when off, so
        # this is a no-op by default): an idea whose subject module a verifiable
        # concrete change can land on outranks a pure-analysis idea. Applies at
        # ALL depths — a permutation/facet child inherits its root's subject, so
        # the whole branch off a landable module is lifted. Pair / abstract
        # subjects (``A↔B``, "CI pipeline") don't name a ``.py`` module → no bonus.
        bonus = _landability_bonus(node, self._landable_subjects)
        if bonus:
            value = round(min(1.0, value + bonus), 4)
        # Facet landable lift (opt-in; gated on ``landability_aware`` so the engine
        # default is byte-identical): a facet phrase that NAMES a concrete Tier-1
        # contribution ("the function the red test calls", "the public re-export
        # surface to wire") routes via ``facet_to_objective`` to a develop objective;
        # give it the SAME graded landability lift (cap × the objective's buyer
        # value), so the value-guided spike drills toward the facet that names real,
        # high-value work rather than a generic case-split leaf. Reuses the shared
        # ``move_value`` model (via ``objective_value``) — no new vocabulary.
        if self.landability_aware and node.kind == "facet":
            bonus = _facet_landable_bonus(node)
            if bonus:
                value = round(min(1.0, value + bonus), 4)
        return value

    def _attach_caveats(self, node: IdeaNode) -> None:
        """Generate the node's counterfactual caveats from a claim grounded in
        its lens/fact/symbol context, leading a facet with its own sub-concern."""
        node.caveats = self.counterfactual.generate(self._caveat_claim(node)).scenarios[:2]
        # A facet refines into a specific sub-concern; lead its caveat with a
        # stress-test of *that* concern so the fractal deepens the reasoning, not
        # just the title. The lens caveat stays as the second scenario.
        if node.kind == "facet" and node.source_facts:
            self._lead_facet_caveat(node)

    def _lead_facet_caveat(self, node: IdeaNode) -> None:
        """Reorder a facet's caveats so its own sub-concern stress-test leads,
        keeping the lens caveat as the second scenario."""
        facet_facts = [f for f in node.source_facts if f.startswith("facet:")]
        if facet_facts:
            phrase = facet_facts[-1].split("facet:", 1)[-1].strip()
            specific = self._facet_caveat(phrase)
            if specific:
                node.caveats = [specific] + [c for c in node.caveats if c != specific][:1]

    @staticmethod
    def _caveat_claim(node: IdeaNode) -> dict:
        """Build the counterfactual claim dict — text plus the most-specific
        discriminator (terminal lens, else root fact label) and any symbol."""
        # Feed operator/fact context so counterfactual caveats are relevant to
        # the development direction, not generic. Symbol-granular subjects
        # (``mod.py::Class.func``) also pass the symbol so caveats can name the
        # actual function instead of reciting a template.
        cf_text = f"{node.title} {_caveat_hint(node)}".strip()
        claim: dict = {"text": cf_text}
        # The terminal lens drives a lens-specific caveat (a 'simplify' idea is
        # stress-tested for silent behavior change, not for malformed input).
        terminal_lens = node.operator_chain[-1] if node.operator_chain else node.operator
        if terminal_lens and terminal_lens != "root":
            claim["operator"] = terminal_lens
        elif node.source_facts:
            # A root idea: discriminate its caveat by the seeding fact label.
            claim["fact_label"] = node.source_facts[0].split(":", 1)[0].strip()
        # Symbol-granular subjects ("mod.py::func") get a function-named caveat —
        # but a facet's "subject :: phrase" also contains "::", so guard against
        # mistaking a facet phrase for a function name.
        if "::" in node.subject and node.kind != "facet":
            claim["symbol"] = node.subject.split("::", 1)[1].rsplit(".", 1)[-1]
        return claim


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
    "decouple": "coupling dependency import interface seam",
    "verify": "invariant assertion proof correctness contract precondition postcondition",
    "fortify": "edge case None empty boundary malformed guard validation failure mode defensive",
}
# Measured magnitudes a seeding fact can carry, each with the value at which
# the bonus saturates: ~16 months of exposure/debt, 50 commits of churn, or
# branch complexity 24 all earn the full bonus. Shared cap matches the other
# scoring bonuses (convergence/evidence) so no single mechanism dominates.
_MAGNITUDE_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"~(\d+) months"), 16.0),
    # Order matters: a knowledge-risk fact also mentions "across N commits",
    # so the share pattern must win before the generic commits pattern.
    (re.compile(r"(\d+)% single-author"), 100.0),
    (re.compile(r"(\d+)% confidence"), 100.0),
    (re.compile(r"(\d+) commits"), 50.0),
    (re.compile(r"complexity (\d+)"), 24.0),
]
_MAGNITUDE_CAP = 0.08


def _magnitude_bonus(node: IdeaNode) -> float:
    """Bounded value lift from the measured quantity in the seeding fact."""
    fact = node.source_facts[0] if node.source_facts else ""
    for pattern, saturation in _MAGNITUDE_PATTERNS:
        m = pattern.search(fact)
        if m:
            return round(_MAGNITUDE_CAP * min(1.0, int(m.group(1)) / saturation), 4)
    return 0.0


# Landability is GRADED by the BUYER VALUE of the move that would land (the shared
# ``move_value`` table): the cap is scaled by that value, so a stub-landable module
# (value 1.0) earns the full lift and a sort-landable one (0.18) a fraction. The
# ceiling stays the same shared ``0.08`` as the other scoring bonuses
# (convergence/evidence/magnitude) so no one mechanism dominates — but now a
# concrete HIGH-value contribution ranks strictly above a concrete LOW-value one,
# which the old flat bonus could never do.
_LANDABILITY_CAP = 0.08


def _landability_bonus(node: IdeaNode, landable_values: dict[str, float]) -> float:
    """``_LANDABILITY_CAP`` scaled by the node subject's best landable buyer value.

    Empty ``landable_values`` (the off-by-default case) short-circuits to 0.0, so
    scoring is byte-identical. The subject is reduced to its bare module path before
    the lookup: a facet's ``"mod.py :: phrase"`` and a symbol subject's
    ``"mod.py::Class.f"`` both reduce to ``mod.py`` (so a child inherits its root's
    landability), while a pair (``A↔B``) or abstract subject (``"CI pipeline"``)
    reduces to itself, names no ``.py`` module, and earns nothing. A subject present
    with value ``v`` earns ``round(_LANDABILITY_CAP * v, 4)`` — the graded lift."""
    if not landable_values:
        return 0.0
    base = node.subject.split(" :: ", 1)[0].split("::", 1)[0]
    return round(_LANDABILITY_CAP * landable_values.get(base, 0.0), 4)


def _facet_landable_bonus(node: IdeaNode) -> float:
    """The graded landability lift for a FACET whose phrase names a concrete
    develop objective, sized by that objective's buyer value (the shared
    ``move_value`` model via ``objective_value``), clamped to the shared
    ``_LANDABILITY_CAP``.

    A facet phrase (carried as a ``facet:<phrase>`` source fact) is routed through
    ``facet_develop.facet_to_objective``; a phrase that names a high-value
    contribution ("the function the red test calls" → tdd-implement, value 1.0)
    earns the full cap, a phrase that names a low-value tidy a fraction, and a
    case-split phrase that routes to NOTHING earns 0.0. Deterministic and pure:
    a fixed map lookup, no clock/randomness."""
    facet_facts = [f for f in node.source_facts if f.startswith("facet:")]
    if not facet_facts:
        return 0.0
    phrase = facet_facts[-1].split("facet:", 1)[-1].strip()
    if not phrase:
        return 0.0
    from app.engine.facet_develop import facet_objective_value

    return round(_LANDABILITY_CAP * facet_objective_value(phrase), 4)


_FACT_HINTS: dict[str, str] = {
    "sensitive-path": "guard validation secret check",
    "security-finding": "eval exec os.system pickle secret guard validation",
    "correctness-bug": "crash bug logic frozen dataclass finally exception edge cases",
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
    "modernization": "refactor cleanup",
    "mutable-default": "shared mutable state bug",
    "debt-markers": "refactor cleanup deferred work",
    "complexity-hotspot": "complex check validation edge cases simplify",
    "hotspot-function": "complex check validation edge cases",
    "churn-hotspot": "refactor interface boundary coupling simplify",
    "doc-drift": "documentation drift broken reference promise",
    "dead-parameter": "unused parameter signature api surface cleanup simplify",
    "extractable-block": "extract a shared helper smaller unit single source refactor",
    "inlinable-helper": "inline simplify single use helper fold call site smaller surface",
    "knowledge-risk": "bus factor onboarding documentation pairing review",
    "dream-insight": "structural pattern refactor architecture coupling confirmed",
    "convergence": "complex secret guard validation check edge cases",
    "shallow-coverage": "check validation edge cases assert behaviour",
    "impure-untested": "side effect isolate decouple pure testable check validation edge cases",
    "hub-untested": "regression net test blast radius dependents safety net cover edge cases",
    "confluence": "decouple test boundary coupling blast radius safety net simplify check validation edge cases",
    "cochange-testgap": "joint integration test co-change coupling safety net cover both modules together regression check validation edge cases",
    "missing-ci": "ci workflow run tests automation",
    "polyglot-hotspot": "review awareness out of scope non-python coverage attention largest active surface",
    "incomplete-protocol": "complete finish protocol contract pair half built equality hash context manager enter exit recommend design",
    "generalizable-duplication": "generalize extract shared helper reuse dry duplicated across modules common abstraction recommend design",
    "coordinator": "decouple split responsibilities god module high fan-out coordination chokepoint boundary seams recommend design",
    "deep-nesting": "flatten guard clause early return extract inner block nested control flow staircase readability maintainability recommend design",
    "god-class": "decompose split responsibilities single responsibility cohesive collaborators smaller classes too many methods extract class boundary seams recommend design",
}

# Root fact labels where reliability/security lenses matter most.
_SECURITY_LABELS = {"sensitive-path", "security-finding", "correctness-bug", "critical-untested", "untested", "partial-coverage", "fragile", "complexity-hotspot", "shallow-coverage", "hotspot-function", "impure-untested", "hub-untested", "convergence", "confluence"}


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


def _join_phrase(labels: list[str]) -> str:
    """Readable English join: ['a', 'b', 'c'] -> 'a, b and c'."""
    if len(labels) <= 1:
        return labels[0] if labels else ""
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


# Convergence remediation: each risk dimension maps to one concrete, phased step.
# (phase_rank, phase, step text, action_type, executable). The rank encodes the
# Stabilize -> Secure -> Evolve -> Refine thesis: a safety net (tests) ALWAYS
# precedes changing risky code (hardening) — you don't harden what you can't
# re-verify. Coverage labels share the create_test_stub action, so they collapse.
_CONVERGENCE_STEPS: dict[str, tuple[int, str, str, str, bool]] = {
    "critically untested":      (1, "Stabilize", "Add a safety-net test layer first", "create_test_stub", True),
    "untested":                 (1, "Stabilize", "Add a first test layer first", "create_test_stub", True),
    "only shallowly tested":    (1, "Stabilize", "Deepen the shallow tests to assert real behaviour", "create_test_stub", True),
    "fragile":                  (1, "Stabilize", "Cover this heavily-depended-on hub with tests", "create_test_stub", True),
    "a complexity hotspot":     (1, "Stabilize", "Cover the complex branches before changing them", "create_test_stub", True),
    "security-sensitive":       (2, "Secure", "Harden inputs and fix risky patterns", "harden_security", True),
    "a central dependency hub": (3, "Evolve", "Reduce coupling and clarify the interface", "design_task", False),
    "accelerating":             (3, "Evolve", "Intervene while the trend is young — smooth the change path now", "design_task", False),
    "high-churn":               (3, "Evolve", "Smooth the change path so frequent change stays cheap", "design_task", False),
    "debt-laden":               (4, "Refine", "Clear the clustered TODO/FIXME debt", "design_task", False),
}


def convergence_labels(node: IdeaNode) -> list[str]:
    """The risk-dimension labels a convergence idea was built from."""
    for fact in node.source_facts:
        if fact.startswith("convergence:"):
            return [p.strip() for p in fact.split(":", 1)[1].split("+") if p.strip()]
    return []


def convergence_plan(labels: list[str]) -> list[dict[str, Any]]:
    """An ordered, deduped mini-roadmap for a convergence idea.

    Turns the converging risk dimensions into phased steps (Stabilize before
    Secure before the rest), collapsing dimensions that share an action so a
    subject that is both untested and a hotspot gets one test step, not two.
    """
    chosen: dict[str, tuple[int, str, str, str, bool]] = {}
    for label in labels:
        spec = _CONVERGENCE_STEPS.get(label)
        if spec is None:
            continue
        action = spec[3]
        # First label wins per action; coverage labels are pre-ordered by
        # severity at construction, so the most-severe phrasing is kept.
        chosen.setdefault(action, spec)
    ordered = sorted(chosen.values(), key=lambda s: (s[0], s[1]))
    return [
        {"phase": phase, "step": text, "action_type": action, "executable": executable}
        for _rank, phase, text, action, executable in ordered
    ]


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


def _render_md_header(report: IdeaTreeReport) -> list[str]:
    """The title + one-line summary (objective, idea count, mean value)."""
    meta = f"{report.stats.get('total_ideas', 0)} ideas · mean value {report.stats.get('mean_value', 0)}"
    if report.objective:
        meta = f"objective: _{report.objective}_ · " + meta
    return [f"# Development Ideas for `{report.project_root}`", "", meta, ""]


def _partition_for_render(
    report: IdeaTreeReport,
) -> tuple[dict[str | None, list[IdeaNode]], list[IdeaNode], list[IdeaNode]]:
    """Group ideas by parent and split the two flat top-level sections.

    Synthesis/pair ideas are parentless-but-not-roots and render in their own
    section. Facet ideas are parented under a permutation leaf, so they render
    nested via the tree walk and are excluded from the flat synthesis section.
    Returns ``(by_parent, synth, perm_roots)``.
    """
    by_parent: dict[str | None, list[IdeaNode]] = {}
    for idea in report.ideas:
        by_parent.setdefault(idea.parent_id, []).append(idea)
    synth = [i for i in report.ideas if i.kind != "permutation" and i.parent_id is None]
    synth_ids = {i.id for i in synth}
    perm_roots = [
        i for i in by_parent.get(None, []) if i.kind == "permutation" and i.id not in synth_ids
    ]
    return by_parent, synth, perm_roots


def _render_idea_line(idea: IdeaNode, depth: int, lines: list[str]) -> None:
    """Append the markdown line(s) for a single idea at ``depth`` (the node body,
    not its children). Roots get a heading + facts/focus; facets show only their
    delta sub-concern + evidence; other nodes show the lens-tagged title."""
    indent = "  " * depth
    if depth == 0:
        lines.append(f"## {idea.branch_path} — {idea.title}  (value {idea.value})")
        if idea.source_facts:
            lines.append(f"{indent}- _facts: {', '.join(idea.source_facts)}_")
        # Concrete loci: when the module-level idea names the riskiest
        # function(s) within, render a focus line. Gated on non-empty so
        # ideas with no anchors render BYTE-IDENTICALLY to before.
        if idea.anchors:
            foci = ", ".join(
                f"`{a['symbol'].rsplit('.', 1)[-1]}` ({a['metric']}, line {a['line']})"
                for a in idea.anchors
            )
            lines.append(f"{indent}  → focus: {foci}")
    elif idea.kind == "facet":
        # A facet is nested under the idea it refines, so the parent already
        # gives the context — repeating the whole title at every zoom level
        # buries the signal. Show only the *delta* (this level's sub-concern),
        # marked as a zoom.
        facet_facts = [f for f in idea.source_facts if f.startswith("facet:")]
        phrase = (facet_facts[-1].split("facet:", 1)[-1].strip()
                  if facet_facts else idea.title)
        caveat = f"  ⚠ {idea.caveats[0]}" if idea.caveats else ""
        lines.append(f"{indent}- 🔍 `{idea.branch_path}` {phrase}  (v {idea.value}){caveat}")
        # Verified concerns show their proof; hypotheses don't pretend.
        for ev in (f for f in idea.source_facts if f.startswith("evidence:")):
            lines.append(f"{indent}  - 📌 {ev.split('evidence:', 1)[1].strip()}")
    else:
        caveat = f"  ⚠ {idea.caveats[0]}" if idea.caveats else ""
        lines.append(
            f"{indent}- `{idea.branch_path}` [{idea.operator}] {idea.title}  (v {idea.value}){caveat}"
        )


def _walk_idea_tree(
    idea: IdeaNode,
    depth: int,
    by_parent: dict[str | None, list[IdeaNode]],
    lines: list[str],
) -> None:
    """Render ``idea`` then recurse into its children (the fractal zoom)."""
    _render_idea_line(idea, depth, lines)
    for child in by_parent.get(idea.id, []):
        _walk_idea_tree(child, depth + 1, by_parent, lines)


def _render_synthesis_section(synth: list[IdeaNode], lines: list[str]) -> None:
    """The flat 'Synthesized ideas' section, value-ordered, with each
    convergence idea auto-expanded into its phased mini-roadmap."""
    lines.append("## 🔗 Synthesized ideas (beyond single-lens permutation)")
    for idea in sorted(synth, key=lambda n: n.value, reverse=True):
        tag = "synthesis" if idea.kind == "synthesis" else "module-pair"
        lines.append(f"- [{tag}] {idea.title}  (v {idea.value})")
        # Convergence ideas auto-expand into a phased mini-roadmap so the
        # "highest-leverage target" comes with an ordered plan, not just a label.
        plan = convergence_plan(convergence_labels(idea))
        for i, step in enumerate(plan, 1):
            mark = "⚙️" if step["executable"] else "✋"
            lines.append(f"    {i}. [{step['phase']}] {mark} {step['step']}")
    lines.append("")


def render_markdown(report: IdeaTreeReport) -> str:
    """Render an idea tree as a readable, hierarchical markdown document."""
    lines = _render_md_header(report)
    by_parent, synth, perm_roots = _partition_for_render(report)

    for root in perm_roots:
        _walk_idea_tree(root, 0, by_parent, lines)
        lines.append("")

    if synth:
        _render_synthesis_section(synth, lines)
    return "\n".join(lines)


def render_mermaid(report: IdeaTreeReport) -> str:
    """Render the idea tree as a Mermaid flowchart."""
    lines = ["```mermaid", "flowchart TD"]
    for idea in report.ideas:
        facet_facts = [f for f in idea.source_facts if f.startswith("facet:")]
        if idea.kind == "facet" and facet_facts:
            # The edge to the parent already carries the context; a facet node
            # shows just its sub-concern, marked as a zoom.
            phrase = facet_facts[-1].split("facet:", 1)[-1].strip()
            label = f"🔍 {phrase}".replace('"', "'")
        else:
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
