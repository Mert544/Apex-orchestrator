# Roadmap

Living document. For shipped detail see `CHECKPOINT.md`.

## Now (shipped)
- **Idea Permutation Engine** — `apex ideate` generates a tree of development
  branches from the real codebase and permutes each into operator-sequence
  sub-ideas. `--actions` bridges them into a supervised, never-applied plan.
  Design: `docs/idea-permutation-engine.md`.
- Integration hardening — swarm runs every scanner, orphaned reasoning engines
  wired in, plugin hooks fire in the main path.
- Quality — `ruff` lint gate + coverage in CI; deterministic-by-default core.

## Next (near-term)
1. **Idea engine P-D**
   - MCP `apex_ideate` tool so IDEs/agents can request idea trees.
   - Optional LLM *polish* of idea titles/rationale (additive, off by default —
     same pattern as `report.llm_summary`).
   - Plugin-contributed operators (extend the permutation alphabet).
   - Idea-specific counterfactual caveats (feed subject/operator context).
2. **Idea → real drafts** — let an executable action step draft an actual patch
   via `SemanticPatchGenerator` (report-only preview, then supervised apply).
3. **Coverage** — raise unit-test coverage of the thin areas: `app/engine/`,
   `app/memory/`, `app/tools/`, `app/policies/`.

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
