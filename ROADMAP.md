# Roadmap

Living document. For shipped detail see `CHECKPOINT.md`.
Strategic positioning + blind-spot closure plans: `docs/market-positioning.md`.
**Single focus** (see `AGENTS.md`): the Idea Permutation Engine, fractal facets
and roadmap reasoning — Apex is a project-development assistant; security stays
an integrated supporting signal.

## Now (shipped)
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
1. **Refactor family growth** on the span-edit machinery: signature change
   with call-site update; `apex rename --from-idea` (the engine proposes the
   rename it already suggests in ideas).
2. Optional **verifier-gated local-LLM** adapter (Ollama; off by default):
   LLM proposes, the deterministic pipeline validates/tests/rolls back.
3. **Coverage** — keep raising unit-test coverage of thin areas.

   (Shipped meanwhile: `apex bench` external calibration on pinned OSS repos;
   risk-tiered transform catalog; `apex rename --param`; nightly dogfood CI.)

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
