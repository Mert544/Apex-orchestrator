# Idea Permutation Engine — Design

> Status: **Design / awaiting approval to implement.**
> Source of ideas: **derived from the existing codebase** (per project owner).

## 1. Vision

Take a project and recursively split it into **autonomous development branches**,
proposing **new ideas** — where every branch spawns its own sub-branches, like
each `a` of `abcd` having its own `abc`. This is the *generative* counterpart of
Apex's existing analytical fractal tree: instead of "what is wrong with this
code?", it answers **"in how many ways can this project be developed, and what
sub-directions does each of those open up?"**

```
project
 ├── a  "Harden the auth module"
 │    ├── a.1  "...by adding input validation"
 │    ├── a.2  "...by sandboxing eval paths"
 │    └── a.3  "...by adding a permissions test suite"
 ├── b  "Extend the dependency hub api/routes"
 │    ├── b.1 ...
 │    └── b.2 ...
 └── c  ...
```

## 2. Mapping to what already exists (reuse first)

The fractal infrastructure hardened this session is ~70% of the engine. We
**reuse**, not rebuild:

| Need | Reused component | Path |
| --- | --- | --- |
| Structural facts about the project | `ProjectProfiler.profile()` → `ProjectProfile` (dependency_hubs, untested_modules, entrypoints, symbol_hubs, sensitive_paths, config_files) | `app/tools/project_profile.py` |
| Recursive branch addressing (a.b.c) | `make_branch_path` | `app/utils/branching.py` |
| Tree storage / dedup | `GraphStore` | `app/memory/graph_store.py` |
| Stay anchored to the project theme | `RelevanceScorer` | `app/skills/relevance_scorer.py` |
| Avoid duplicate ideas | `NoveltyScorer`, `SpamGuard` | `app/engine/novelty.py`, `app/skills/spam_guard.py` |
| Stress-test each idea ("what could go wrong") | `CounterfactualGenerator` | `app/engine/counterfactual_generator.py` |
| Depth/budget control | `BudgetController`, `TerminationEngine` | `app/engine/*` |
| Priority scoring | `score_claim_priority` pattern | `app/policies/scoring.py` |

**The only genuinely new piece is a *generative* expander** (the current
`Decomposer`/`QuestionGenerator` are analytical).

## 3. Core concepts

### 3.1 Idea node
A lightweight model (new: `app/models/idea.py`), parallel to `ResearchNode`:

```python
class IdeaNode(BaseModel):
    id: str
    title: str                 # "Harden the auth module"
    rationale: str             # why this is worth doing (grounded in profile)
    branch_path: str = ""      # x.a.b
    depth: int = 0
    source_facts: list[str]    # profile facts that seeded it (e.g. "sensitive: app/auth.py")
    operator: str = "root"     # the lens that produced it (see 3.2)
    relevance: float = 1.0     # to the project theme/objective
    novelty: float = 1.0
    value: float = 0.0         # composite score (3.4)
    feasibility: float = 0.5   # cheap heuristic (3.4)
    caveats: list[str] = []    # from CounterfactualGenerator
    parent_id: str | None = None
```

### 3.2 Development operators (the "abc" applied to each "a")
The permutation comes from applying a fixed set of **development lenses** to every
idea. Each lens transforms a parent idea into a concrete child direction:

| Operator | Turns "X" into… |
| --- | --- |
| `extend` | "Extend X with a new capability" |
| `harden` | "Make X more secure/robust" |
| `test` | "Raise X's test coverage / add property tests" |
| `simplify` | "Reduce X's complexity / refactor seam" |
| `document` | "Document X's contract and usage" |
| `integrate` | "Connect X to another subsystem" |
| `generalize` | "Make X reusable/configurable" |
| `observe` | "Add metrics/logging around X" |

Operators are data-driven (a list), so the permutation breadth is tunable and
extensible (plugins could add operators later). Child count per node =
`min(len(active_operators), breadth_budget)`.

### 3.3 Root idea generation (derived from code)
`IdeaSeeder.seed(profile) -> list[IdeaNode]` maps **profile facts → root branches**:

- each `dependency_hub` → "Evolve the central module {hub}"
- each `critical_untested_module` → "Establish a safety net around {module}"
- each `sensitive_path` → "Harden {path}"
- each `entrypoint` → "Grow capability behind {entrypoint}"
- `symbol_hubs`, `config_files`, missing `ci_files` → analogous seeds

Each root carries `source_facts` so every idea is **traceable to real code**.

### 3.4 Scoring
- `relevance` = `RelevanceScorer(objective_or_project_theme).score(title)`
- `novelty` = `NoveltyScorer` against already-emitted ideas (dedup near-duplicates)
- `feasibility` = cheap heuristic: shallower depth + operator weight (e.g. `document`/`test` high, `integrate`/`generalize` lower)
- `value = 0.4*relevance + 0.3*novelty + 0.3*feasibility` (tunable, mirrors `scoring.py` style)
- `caveats` = `CounterfactualGenerator.generate({"text": title})` → top scenarios

Expansion is **best-first by `value`**, bounded by `BudgetController`
(max_total_ideas) and depth (`max_idea_depth`), and pruned by relevance/novelty
floors — exactly the focus mechanism we already built.

## 4. Architecture

New module `app/engine/idea_permutation.py`:

```python
class IdeaPermutationEngine:
    def __init__(self, config, project_root):
        self.profiler = ProjectProfiler(project_root)
        self.relevance = RelevanceScorer("")     # set per run
        self.novelty = NoveltyScorer(graph)
        self.counterfactual = CounterfactualGenerator()
        self.budget = BudgetController(max_total_nodes=config["max_total_ideas"])
        self.operators = DEFAULT_OPERATORS
        self.graph = GraphStore()                # reused for storage/dedup

    def run(self, objective: str | None = None) -> IdeaTreeReport:
        profile = self.profiler.profile()
        roots = IdeaSeeder().seed(profile, objective)
        # best-first expansion applying operators (permutation), with
        # relevance/novelty/budget control + counterfactual caveats
        ...
        return IdeaTreeReport(ideas=..., branch_map=..., stats=...)
```

Recommended: a **standalone engine** (not folded into
`FractalResearchOrchestrator`) so the analytical flow stays intact and the
generative flow is clean. It deliberately reuses the same primitives, so the two
trees feel consistent.

## 5. Surfaces (how the user runs it)
- **CLI:** new `apex ideate --target=. --depth=2 --breadth=4 [--objective="..."]`
  (`app/cli.py` already has subcommands; add one).
- **Report:** reuse `ReportComposer`/markdown + a Mermaid tree of the idea
  branches (we already have `mermaid_exporter`).
- **MCP tool (optional, later):** expose `apex_ideate` via `app/mcp/tools.py`.

## 6. Output
A markdown + JSON idea tree:
```
# Development Ideas for <project>
## a — Evolve the central module app/routes/api.py   (value 0.82)
   facts: dependency_hub
   - a.1 [extend]  Add a versioned endpoint layer to api.py      (0.79)
   - a.2 [harden]  Add request validation + rate limiting        (0.74)  ⚠ caveat: ...
   - a.3 [test]    Add contract tests for api.py routes          (0.71)
## b — Establish a safety net around app/services/...
   ...
```
Plus `report.idea_tree` (JSON) for tooling, and `mean_relevance` / pruned-drift
stats for observability (same telemetry style as the analytical engine).

## 7. Testing strategy
- Unit: `IdeaSeeder` maps known profile fixtures → expected root titles/facts.
- Unit: operators produce distinct, well-formed child titles; permutation breadth
  respected.
- Property: no duplicate ideas (novelty dedup); every idea traceable to ≥1 fact;
  all relevance/value in [0,1].
- E2E: `IdeaPermutationEngine.run()` on `examples/flask_mini` yields a depth-2
  tree with ≥ N ideas, each with a branch_path and caveats. Deterministic (no
  LLM), so assertions are stable.
- Optional: when `llm.provider != none`, an idea's title/rationale can be
  *polished* by the LLM (additive, off by default — same pattern as
  `report.llm_summary`).

## 8. Phased implementation
1. **P-A** `app/models/idea.py` (IdeaNode, IdeaTreeReport) + `IdeaSeeder` from
   profile + unit tests.
2. **P-B** `IdeaPermutationEngine` expansion loop with operators + relevance/
   novelty/budget + counterfactual caveats + E2E test on flask_mini.
3. **P-C** `apex ideate` CLI + markdown/Mermaid report.
4. **P-D** (optional) MCP tool + LLM polish + plugin-contributed operators.

Each phase: green tests, separate commit on `claude/apex-orchestrator-eZbJO`.

## 9. Verification
- `python -m pytest tests/test_idea_*.py -q` green.
- `apex ideate --target=examples/flask_mini --depth=2 --breadth=4` prints a
  traceable a.b idea tree with >0 ideas and caveats; fully offline/deterministic.
- Full suite stays green (no regression to the analytical engine).
```
