# Roadmap

Living document. For shipped detail see `CHECKPOINT.md`.
Strategic positioning + blind-spot closure plans: `docs/market-positioning.md`.
**Single focus** (see `AGENTS.md`): the Idea Permutation Engine, fractal facets
and roadmap reasoning — Apex is a project-development assistant; security stays
an integrated supporting signal.

## Now (shipped)
- **The cell — proof-carrying, multi-language-aware, self-knowing.** A runnable
  recommendation shows its proof: the exact draft diff, a re-parse verdict, the
  before→after metric delta (`transform_impact`), and whether the tests exercise
  the change (verification strength) — `apex ideate --actions --prove`. BS-1
  (Python-only) is broken open: `polyglot_facts` names the biggest / most-churned
  non-Python files with a test-presence flag and a debt-marker count, surfaced as
  honest recommend-only ideas, in `apex scope`, and a dashboard panel. Apex knows
  itself: `apex trackrecord` shows its proven fix history; `apex pulse` is the
  one-screen vital-signs snapshot (grade + scope + next-moves + track record);
  **`apex proof`** makes the proof-of-fix evidence visible — a read-only view of
  each applied/rolled-back/blocked/withheld move with its reason and coverage, a
  tamper-evident sha256, and the aggregate track record (renders
  `.apex/proof-of-fix.json` + the proof history; invents no analysis).
- **A learning, concrete idea engine** — roadmap ranking now learns from the
  repo's own `IdeaMemory` outcome ledger (historically-landing fixes rank up;
  no-op on a fresh repo), activated on `apex ideate`. Two new grounded signals:
  *confluence* (3+ pressures converge on one module) and *co-change test-gap*
  (modules that change together but share no test — naming the actual linking
  symbol). Recommendations are now **concrete**: `IdeaNode.anchors`
  (`symbol·line·metric`) pinpoint the riskiest function in a flagged module and
  flow through `ideate`/`explain`/brief/dashboard and the `create_test_stub`
  action (a real pytest skeleton naming the symbol). **BS-7 visible**:
  `apex deadcode --confirm` confirms/refutes dead-code via the project's own
  tests under stdlib `trace` (keyed on use-only body lines); `apex objectives`
  reports catalog reachability (facet routing now reaches 40/40). Dogfood
  bug-fixes the agents proved: a dependency-planner infinite-hang (cycle guard),
  an unreachable `candidate2` in the fractal analyzer, a dead `_block_template`.
- **Development-team tooling** — `apex partition` (provably-disjoint parallel work
  groups), `scripts/merge_train.py` (safe-order integration), `apex changed`
  (change blast-radius), and the codified team process (`docs/development-team.md`).
- **Capability efficiency** — 37 develop objectives (6 new transforms); the
  splice-precedence bug class closed across all transforms; the idea engine now
  routes **18** objectives (was 6) from discovered facets.
- **Idea/fractal-engine depth** — two new lenses (`decouple`, `verify`), a
  `purity`/`side-effects` fractal dimension, and the compounding `impure-untested`
  seeding signal. `apex canvas` / `apex idea-html` visual exports.
- **Self-measurement truth** — one canonical tree-walk exclusion
  (`app/engine/skip_dirs.py`) governs ~17 walkers; the health grade is now
  **worktree-immune** (proven byte-identical with 1145 worktree copies present
  vs zero), so Apex measures correctly inside its own parallel-agent dev
  environment. Regression-tested.
- **Capability growth** — 32 develop objectives; new `dedup-total-return`
  (control-flow dedup), `dedup-parameterized` on the fast board, **human-readable
  deterministic helper/constant names**, idiom-aware `extract-constant`.
- **`apex canvas`** — exports the dependency graph as a **JSONCanvas** (`.canvas`)
  for Obsidian / any canvas tool.
- **Development department** — the multi-agent build process as a written module
  (`docs/development-team.md`).
- **Trust layer** — `proof-of-fix.json` evidence artifact (finding, diff, test
  run, rollback per fix), **coverage-aware verification strength** (does the
  green suite *name the changed function*, reference the module, or never look
  at it?), **test-first shield** (uncovered modules get a generated
  characterization test BEFORE the fix), SARIF export for `apex review`.
- **Multi-file refactoring** — `apex rename` (cross-file rename: definition +
  imports + call sites) and `apex move` (module move with project-wide import
  rewriting). Span-edit machinery: comment-preserving, conservative blockers,
  test-verified with rollback.
- **Richer fact base** — git-churn hotspots, change×complexity convergence
  dimension, debt-marker age via git blame, level-3 content-aware fractal facet
  vocabulary, depth-stretched facet budget.
- **Cross-run narrative** — roadmap snapshots carry provenance; `--roadmap
  --diff` narrates which signal produced each new idea and which stopped
  firing. Dashboard sections for proof-of-fix and roadmap changes.
- **Autonomous maintenance** — `apex maintain` runs the full guarded loop
  (scan → ideate → apply → verify with tests → auto-rollback → commit →
  Markdown report). Modes: report / supervised / autonomous.
- **Idea Permutation Engine** — `apex ideate` generates a tree of development
  branches from the real codebase and permutes each into operator-sequence
  sub-ideas, plus synthesis (security-test-suite) and module-pair / import-cycle
  ideas. `--actions` bridges them into a supervised plan; `--apply --verify
  [--commit]` applies real fixes test-gated with rollback.
  Design: `docs/idea-permutation-engine.md`.
- Integration hardening — swarm runs every scanner, orphaned reasoning engines
  wired in, plugin hooks fire in the main path.
- Quality — `ruff` lint gate + coverage in CI; deterministic-by-default core.
- **Idea → Action bridge** (`apex ideate --actions`) + real patch *drafting*
  (`--draft`, preview only, never applied) via `SemanticPatchGenerator`.
- **MCP `apex_ideate` tool**; operator/fact-aware counterfactual caveats.
- **Plugin-contributed operators** (`proxy.add_operator`) widen the alphabet.

## Next (near-term)

> **Campaign — grow Apex AS Apex (never into an LLM).** Identity (binding):
> Apex's purpose is to *develop the project it sits in* — it proves,
> concretizes, and **produces grounded ideas** (the fractal/idea engine, develop
> objectives). Security is a grounding signal, **never** the headline. The wedge
> against "why Apex when I have a local LLM?" is NOT to add an LLM (that dilutes
> the whole identity) — it is to **deepen the deterministic-development advantage
> an LLM structurally cannot match**: zero-token, zero-cost, reproducible,
> CI-droppable, *test-verified-with-rollback*, and grounded in concrete code
> facts. An LLM cannot run your suite, prove a change is safe, or grade
> deterministically — Apex can. Make that self-evident through the product.
>
> Focus — close the open, NON-LLM blind spots (§4b of
> `docs/market-positioning.md`) and deepen the core:
> **BS-7** (runtime understanding: harvest executed-line data when the host
> suite runs, via stdlib `trace`, to confirm/refute static findings and label
> their confidence — *Apex verifies with YOUR actual tests, which an LLM never
> does*); **BS-1** (Python-only → first an honest "X% of this repo is outside
> analysis scope" instead of silently grading the Python subset, then a
> language-plugin seam); deepen the **idea/fractal engine** (richer grounded
> signals, sharper "what to do next" prioritization); ~~make the **proof
> visible** (proof-of-fix / verification-strength surfaced)~~ — **✅ shipped as
> `apex proof`**. Explicitly **NO local-LLM
> layer** (BS-2 is deferred — it works against the positioning).
> Run it as a team (army): `apex partition` to plan disjoint work, worktree
> agents + a standing auditor per wave, `scripts/merge_train.py` to integrate,
> one green gate. Dogfood hygiene runs alongside each wave (e.g. the dead
> `_block_template` symbol removed and the one broad-silent `except` in
> `cli_autonomy` justified — most silent passes are legitimate best-effort).

1. **Refactor family growth** on the span-edit machinery: signature change
   with call-site update; `apex rename --from-idea` (the engine proposes the
   rename it already suggests in ideas).
2. **Runtime understanding (BS-7)** — harvest executed-line data when the host
   suite runs (stdlib `trace`) to confirm/refute static findings and label
   their confidence. *Apex develops a project like an LLM would, but verifies
   with YOUR actual tests — which an LLM cannot do.* (No LLM involved.)
3. **Honest scope (BS-1)** — report "X% of this repo is outside Python analysis
   scope" instead of silently grading the Python subset; then a language-plugin
   seam. Builds trust an LLM's confident guess never earns.
4. **Coverage** — keep raising unit-test coverage of thin areas.

   (Shipped meanwhile: `apex bench` external calibration on pinned OSS repos;
   risk-tiered transform catalog; `apex rename --param`; nightly dogfood CI;
   `apex proof` — the proof-of-fix evidence made visible.)

## Later
- Plugin marketplace / registry server.
- IDE Language Server Protocol (LSP) integration.
- Make the experimental infra real (see below) or keep it clearly labelled.

## Experimental (not production-ready)
- **Kubernetes operator** (`app/k8s/operator.py`) — in-memory reconciliation;
  does not yet use `kubernetes-client/python` to watch CRDs.
- **Helm chart** — skeletal (no RBAC, ingress, or storage class).
- **VS Code extension** — a thin CLI wrapper around `python -m app.main`, not a
  full LSP/diagnostics integration.

## Principles
- The core stays **deterministic and offline by default**; any LLM is opt-in.
- Generative/autonomous features **propose**; applying changes stays **gated**
  by `ModePolicy` (report / supervised / autonomous) and `SafetyGates`.
