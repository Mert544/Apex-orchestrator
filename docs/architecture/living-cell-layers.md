# Apex — the living cell: 7-layer architecture (VERIFIED MAP)

> **Purpose.** This is the **durable, verified** answer to "what is Apex, in
> parts, and where does each part actually live in the code?" It exists so no
> future session has to re-derive the map from scratch. Every claim below was
> re-grounded against the real tree (module listings, CLI surface, live counts)
> on the date in the verification log. If you are a new session: **read this
> instead of re-investigating**; only re-verify a row if you are about to change
> it. To confirm any row cheaply, run its **`verify:`** one-liner.

## Identity (LOCKED — see `CLAUDE.md`)

Apex is **NOT a cybersecurity agent.** It is a **deterministic, zero-token,
offline, proof-carrying project-DEVELOPMENT agent** — a *living, multi-layered
cell*. Security is one integrated supporting **signal**, never the identity. The
cell has seven layers; each is real code, not metaphor.

```
        ┌─────────────────────────────────────────────────────────┐
        │  L7  Self-awareness / proof   (pulse · grade · proof)     │
        │   ┌───────────────────────────────────────────────────┐  │
        │   │ L6  Inner intelligence  (reasoning + optional LLM) │  │
        │   │   ┌─────────────────────────────────────────────┐ │  │
        │   │   │ L2 Brain (ideas/roadmap) → L3 Hands (land)  │ │  │
        │   │   └─────────────────────────────────────────────┘ │  │
        │   │      ▲ L1 Eyes (read)        ▼ L4 Dream (learn)    │  │
        │   └───────────────────────────────────────────────────┘  │
        │  L5  Memory / Obsidian vault  (what it remembers)         │
        └─────────────────────────────────────────────────────────┘
```

---

## L1 — Eyes (read the project)

**Plain words:** Apex looks at an existing project and builds a factual picture —
files, functions, complexity, dependencies, what has tests and what doesn't —
deterministically (same project → same picture). No LLM, no guessing.

- **Where:** `app/tools/` — `project_profile.py`, `python_structure.py`,
  `dependency_graph.py`, `code_metrics.py`, `complexity_profile.py`,
  `polyglot_facts.py`, `profile_scanners.py`, `js_project_profile.py`.
- **Product surface:** `apex scan`, `apex metrics`, `apex deps`, `apex polyglot`,
  `apex hotspots`.
- **verify:** `ls app/tools/ | grep -E 'project_profile|python_structure|dependency_graph'`

## L2 — Brain (turn facts into concrete development ideas)

**Plain words:** From the Eyes' facts, the Brain proposes *specific* development
moves — "this untested function needs a test", "this TODO can be implemented",
"this duplication can be deduped" — ranked, explained, and tied to real
artifacts. This is the idea/roadmap engine.

- **Where:** `app/engine/idea_*.py` (bridge, facets, memory, investment,
  composition, dependencies, explain, brief, permutation, roadmap, seeder,
  reasoning, pareto, portfolio, tree_shape, synthesis_signals) +
  `facet_develop.py`, `facet_evidence.py`, `objective_compiler.py`.
- **Live fact:** `available_objectives()` = **98** compilable objectives.
- **Product surface:** `apex ideate`, `apex plan`, `apex brief`, `apex explain`,
  `apex objectives`, `apex roadmap`.
- **verify:** `python -c "from app.engine.objective_compiler import available_objectives as a; print(len(a()))"` → `98`

## L3 — Hands (land working code, verified, auto-rolled-back)

**Plain words:** The Hands actually *edit the code* — apply a transform, run the
impact-scoped tests, keep the change only if it stays green, otherwise roll it
back automatically. This is where "concrete contribution" becomes a real diff.

- **Where:** `app/execution/semantic/transforms/` — **43** transform modules
  (e.g. `mutable_defaults.py`, `open_encoding.py`, `net_timeout.py`,
  `raise_from.py`, `sql_text_wrap.py`, `type_annotations.py`, `guard_clause.py`,
  `extract_method.py`, `docstring.py`, `organize_imports.py`, `modernize.py`,
  `security.py`, `repair_test.py`, …).
- **Guarantees:** impact-scope verify · delta-green · auto-rollback ·
  proof-of-fix (see L7).
- **Product surface:** `apex develop`, `apex fix-coverage`, `apex fix-docstrings`,
  `apex rewrite`, `apex extract`, `apex rename`, `apex move`.
- **verify:** `ls app/execution/semantic/transforms/*.py | grep -v __init__ | wc -l` → `43`

## L4 — Dream (self-improve while you are away)

**Plain words:** When idle, Apex "dreams" — it explores what it could learn or
improve, discovers landable work, learns from its own gate outcomes, and writes
a digest of "what the organism learned while you were away." Deterministic and
guarded (nothing lands unverified).

- **Where:** `app/engine/` — `dream.py`, `dream_develop.py`,
  `dream_discovery.py`, `dream_gate_learn.py`, `dream_landing.py`, `agenda.py`.
- **Artifact:** `.apex/vault/dream-digest.md` ("what the organism learned…").
- **Product surface:** `apex dream`, `apex dream --land`, `apex discoveries`,
  `apex agenda`.
- **verify:** `ls app/engine/ | grep -E '^dream|^agenda'`

## L5 — Memory / Obsidian (what it remembers, and the human bridge)

**Plain words:** Apex keeps a persistent, deterministic memory of everything it
has done — findings, run history, dream digests — rolled into ONE vault view.
It also bridges to **Obsidian**: your `#apex-hedef` notes become objectives, and
idea trees export as a navigable JSONCanvas map you open in Obsidian.

- **Where:** `app/memory/` — `vault.py`, `vault_history.py`, `persistent_memory.py`,
  `graph_store.py`, `vector_store.py`, `cross_run_tracker.py`,
  `findings_persistence.py`. Obsidian bridge: `app/reporting/canvas_export.py`,
  `idea_canvas.py`; `#apex-hedef` note ingest in `app/cli.py` (V5) +
  `app/engine/agenda.py` (V6 dream-weight bridge).
- **Contracts:** single-writer · lossless/additive · honest-empties · byte
  deterministic (same stores → byte-identical vault).
- **Product surface:** `apex vault --save/--diff`, `apex canvas`, `apex city`.
- **verify:** `sed -n '1,20p' app/memory/vault.py` (single-writer/deterministic contract)

## L6 — Inner intelligence (reasoning core + optional small LLM)

**Plain words:** The reasoning brainstem — abductive/effort/remediation reasoning
and the fractal "cortex" that plans across a goal tree. A **small LLM is
optional and OFF by default**; with it off, behavior is byte-identical to the
zero-token core. When enabled (opt-in proposal lane), the LLM may only *propose*
diffs that pass the **same** gates as deterministic moves.

- **Where:** `app/engine/` — `fractal_cortex.py`, `abductive_reasoning.py`,
  `idea_reasoning.py`, `effort_reasoning.py`, `remediation_reasoning.py`,
  `interaction_reasoning.py`, `intelligence_report.py`; LLM lane:
  `app/llm/` — `router.py`, `agent_adapter.py`, `cost_registry.py`.
- **Rule:** off → zero-token/deterministic; on → "LLM-proposed, Apex-verified",
  same gates, nothing lands unverified (`CLAUDE.md` guardrail #4).
- **Product surface:** `apex intelligence`, `apex fractal`, `apex consensus`.
- **verify:** `ls app/engine/ | grep -E 'cortex|reasoning|intelligence'; ls app/llm/`

## L7 — Self-awareness / proof (never fakes green)

**Plain words:** Apex knows its own health and can *prove* it. It grades itself,
takes a "pulse", and carries proof for every change — and it **never fakes
green**: a change that doesn't hold is rolled back, and the report says so
honestly (coverage-aware honesty). This is the trust foundation.

- **Where:** `app/cli_reporting.py` (pulse/grade/proof), the full-green gate
  `scripts/verify.py`, the North-Star self-audit `apex self-audit --north-star`.
- **Product surface:** `apex pulse`, `apex grade`, `apex proof`, `apex trackrecord`,
  `apex evolve`, `apex readiness`, `apex self-audit`.
- **verify:** `apex self-audit --north-star` → PASS (drift=False)

---

## Verification log (so the next session inherits, not re-derives)

| Date | What was verified / done | Evidence |
|------|--------------------------|----------|
| 2026-07-04 | **Trunk un-fragmented** — `main` fast-forwarded to the flagship living cell (was a 2026-06-02 fossil; 1454 unmerged commits behind). `main` == flagship on origin. | `git rev-parse origin/main origin/claude/blissful-mayer-aaqb3p` equal (`29dd832`) |
| 2026-07-04 | **`apex pulse` timeout fixed** — profiled the project **once** and shared it across grade/scope/moves (was 3× full scans). Byte-identical output; ~263s → ~168s, under the 240s guard. Designed by 5-agent consensus, **empirically** verified (the run caught a mock-signature break the static consensus missed). | commit `31bdc3f`; `app/cli_reporting.py` `_pulse_snapshot` threads one `profile` |
| 2026-07-04 | **Test-surface audit** (report-only, no deletions) — separated the genuine mutation-hardened core (keep) from a **verified** inflation layer (~10,100 LOC of unfalsifiable `git show HEAD:` characterization tests), proven by a live pre-/post-commit experiment. | `docs/test-inflation-audit.md`; commit `29dd832` |
| 2026-07-05 | **7-layer map re-grounded** — all 7 layers confirmed against the real tree: L1 8 Eyes tools, L2 98 objectives, L3 43 transforms, L4 dream/agenda, L5 vault+Obsidian bridge, L6 reasoning+LLM lane, L7 pulse/grade/proof + ~70 CLI verbs. | this document; commands in each `verify:` row |
| 2026-07-05 | **Wave 3 — L6 Inner intelligence developed (the 7th & last layer): `apex fractal analyze --apply`.** The fractal reasoning agent could not land a single file before this. 5 parts, solo/atomic: (1) CLI `--apply`/`--commit`/`--mode`/`--agent` (default security for analysis, docstring for `--apply`); (2) `project_root` threaded end-to-end (was dropped 3 layers before the cortex; `_generate_semantic_patch` hardcoded `"."`); (3) `git_commit` rebound to the target repo (was bound to `.` — a real misdirected-commit hazard); (4) the action gate lets `missing_docstring`/`missing_test` reach `patch` on their own terms without inflating severity (`bare_except` stays escalate-only); (5) `enforce_clean_working_tree` points at the target. Also fixed a cache-hit divergence (a cached tree fell back to a broken `def ():` template instead of the semantic patch). Proven by an **unmocked** integration test (real tmp git repo, `project_root != CWD`): docstrings land + commit in the target, CWD untouched, dirty target blocked. An adversarial **code review of the landed L6** then caught **7 more real bugs** (all fixed + regression-tested): the clean-tree gate keyed on `--commit` instead of the resolved mode (so `--mode autonomous --apply` skipped it); a non-git target printing a **false "committed 1"** (stdout-only check + counting commit *attempts* not successes — a "never fakes green" violation); the CWD-relative decision cache / cross-run memory not scoped to the target; and the `bare_except`/empty-file patch guards being incidental rather than structural. | `app/cli_reporting.py`, `app/agents/fractal_agents.py`, `app/engine/fractal_cortex.py`, `app/engine/fractal_5whys.py`, `app/policies/mode_policy.py`, `tests/test_fractal_apply_integration_eyml.py` |
| 2026-07-05 | **Wave 2 hardening — self-grade gate + adversarial code review caught 6 issues** (all fixed before push). Apex's own **A+ 100 self-grade** refused the Wave-2 code twice for pushing `cli_ideate.py` functions over the complexity-12 ceiling (fixed by extract-to-helpers, no behavior change). An independent 9-agent review of the *landed code* (not the specs) found 4 real bugs the tests missed: value-ranked+max-modules dropped the highest-*value* module (re-sorted by centrality); `apply()` over-refused a `-> None` through an idiomatic `from functools import lru_cache`; `--max-modules 0` claimed a false cap; `--max-rounds 0` coerced to 8. All fixed with regression tests. **Lesson for next session:** run an adversarial *code* review (not just spec review) before pushing new CLI/engine surface — the self-grade + review are the trust rails working. | `app/engine/dream_develop.py`, `app/cli_insight.py`, `app/cli_ideate.py`, `app/execution/semantic/transforms/type_annotations.py` |
| 2026-07-05 | **Wave 2 — 2 more layers developed** (from the same design pass, REVISE specs with their mandated fixes bundled): **L5 Memory** — `.epistemic/memory.json` joins the vault as a 7th section (`epistemic_memory`), summarised as counts only (never the raw report blobs), read as bytes (vault stays a leaf reader). `apex vault` now shows `N/7`; owner-report/`--diff` pick it up generically, no change. **L2 Brain** — `apex ideate --actions --apply --drain` reaches the bridge's tested cascade-drain (re-detect changed files → re-apply to a fixpoint), with a CLI-side replan closure that **preserves the user's `--phase`/`--auto`/synthesis choices** across rounds (the bridge default drops them — a real scope-escape) + `--max-rounds`/`--max-attempts`; no-flags path byte-identical. | `app/memory/vault.py`+`tests/test_vault_epistemic_section_eyml.py`, `app/cli_ideate.py`+`tests/test_cli_ideate_drain_eyml.py` |
| 2026-07-05 | **Wave 1 — 3 layers developed + made visible** (from a 7-team / 42-agent design pass, ranked, drift-audited): **L3 Hands** — the `add_type_annotations` title-transform now proves the return type via the sound `_infer_return_type` oracle instead of blindly stamping `-> None` (a shipping correctness bug: it used to land a provably-wrong annotation on any value-returning function, invisibly to the test gate). **L4 Dream** — `apex dream --land` gains `--preview`/`--max-modules`/`--value-ranked` (the tested `dream_develop` bounds, never CLI-exposed) with explicit-flag-wins precedence + an honest CLI-local disclosure line; base command byte-identical. **L1 Eyes** — new `apex js-scope` command surfaces the already-built, already-tested JS/TS profiler (module graph, dependency hubs, untested hubs) for the non-Python half of a stack. | `app/execution/semantic/transforms/type_annotations.py`, `app/engine/dream_develop.py`+`app/agent/assist.py`+`app/cli_insight.py`, `tests/test_cli_js_scope.py` |

**Proof posture:** full-green gate = `python scripts/verify.py` (≈20k tests +
ruff); fast local run = `--chunks 16 -j 8`; self-grade **A+ 100/100** with the
grader's complexity ceiling **12**; `apex self-audit --north-star` → PASS,
drift=False. Compute here: **4 cores / 15 GB** → keep **≤3 pytest-running agents**
concurrent (5 = OOM); the workflow concurrency cap resolves to ~2.

## How this map stays honest

Each layer's `verify:` line is a falsifiable check against the live tree, not a
claim to trust. If a `verify:` line stops matching, the map drifted — fix the
map (or the code) rather than trusting the prose. This is the same discipline
Apex applies to a project it develops: **evidence over assertion.**
