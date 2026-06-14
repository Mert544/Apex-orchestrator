# Apex Autonomous Engineering Organism - Checkpoint

**Date**: 2026-06-14
**Commit**: branch `claude/apex-orchestrator-eZbJO`
**Tests**: 3900+ passing ✅
**Status**: Team-org tooling + capability efficiency + idea/fractal-engine depth — see "Latest milestone" below

> Previous milestones: self-measurement truth + capability growth (2026-06-14, 3400 tests);
> trust layer + multi-file refactoring (2026-06-12, 1921 tests);
> idea-engine+action-bridge (2026-05-30, 786 tests);
> autonomy-safety-core (2026-04-25, 633 tests).

---

## Latest milestone: team-org tooling + capability efficiency + engine depth (2026-06-14)

A sustained multi-agent campaign (orchestrator + parallel specialist agents in
isolated worktrees, each gated and integrated under the green gate).

**Development team as tooling.** The process is codified
(`docs/development-team.md` + `docs/ordu-duzeni.{html,png}`): worktrees from
current HEAD, an auditor every wave, isolated writers, value-sized headcount.
Two tools back it: `apex partition` (`app/engine/work_partition.py` — computes
provably-disjoint parallel work groups via the dependency graph + blast-radius)
and `scripts/merge_train.py` (safe-order cherry-pick + gate integration). Plus
`apex changed` (`app/engine/blast_radius.py` — a change's dependents, covering
tests, and scope cohesion).

**Capability efficiency.** 37 develop objectives. New transforms:
`remove-unreachable-after-terminator`, `remove-pointless-pass`,
`fold-literal-string-concat`, `simplify-negated-comparison`, `format-to-fstring`,
`dedup-total-return`. The whole splice-precedence class (an auditor finding,
H1-H7) is closed across every transform via the shared
`_transform_base.splice_operand`; the dedup helper-insertion bug (H4) and a
fractal-analyzer method double-count are fixed. The idea engine now routes **18**
develop objectives (was 6) from discovered facets (`FACET_OBJECTIVE_MAP` +
enriched `idea_facets.py` vocabulary).

**Idea/fractal-engine depth.** Two new development lenses (`decouple`, `verify`)
→ 10 operators. A `purity`/`side-effects` dimension in the function fractal
analyzer, and a compounding `impure-untested` seeding signal that uses it to
ground "isolate the side effect, then cover the core" ideas (→ `create_test_stub`).

**Visualization.** `apex canvas --kind deps|idea` (JSONCanvas) and `apex
idea-html` (self-contained HTML idea tree).

---

## Milestone: self-measurement truth + capability growth (2026-06-14)

**Blind-spot class eliminated (and proven).** Apex was scanning its own
`.claude/` agent worktrees — full repo COPIES — so tree-walks double-counted
modules, collided test basenames, and (worst) the **health grade itself** was
computed from worktree copies instead of real code (`.claude` sorts first, so a
capped walk filled with copies). One canonical exclusion now governs every
walk (`app/engine/skip_dirs.py`: `SKIPPED_DIRS` / `is_skipped` /
`iter_source_files`); ~17 walkers route through it. Locked by regression tests:
the grade is **byte-identical with 1145 worktree copies present and with zero** —
worktree-immune. This is core differentiation: Apex measures correctly inside
its own parallel-agent development environment, where naive tools silently skew.

**Capability growth.** 32 develop objectives. New `dedup-total-return`
(control-flow dedup: an exact-duplicate block whose every exit returns lifts into
a shared helper). `dedup-parameterized` moved onto the fast board (near-dup scan
~100s → ~1.8s). Dedup helpers and parameters now get **human-readable
deterministic names** (`_generate_patch_skill`, not `_shared_1`).
`extract-constant` skips idioms (`utf-8`, small ints) and names constants
`CONTENT_TYPE`, not `CONST_X`. `extract-guard-clause` inverts membership/identity
tests in place (no `not (a in b)`).

**New capability — `apex canvas`.** Exports the dependency graph as a
**JSONCanvas** (`.canvas`) for Obsidian / any canvas tool — Apex's deterministic
structure as a navigable knowledge map.

**Determinism + coverage.** Plugin discovery sorted; `python_structure` parse
`except` narrowed (no silent module drops). `detectors.py` 91→100%,
`idea_permutation.py` 94→99% coverage (+41 tests).

**Development department.** The proven multi-agent process is a written module
(`docs/development-team.md`): orchestrator + specialist agents (engineer /
auditor / test-writer) in isolated worktrees, disjoint-file partitioning, the
green gate (`scripts/verify.py`), agents-don't-push integration by cherry-pick,
and the phantom-worktree rule.

---

## Latest milestone: trust layer + refactoring (2026-06)

**Identity (binding, see `AGENTS.md`):** single focus = Idea Permutation
Engine, fractal facets, roadmap reasoning. Apex is a project-development
assistant; security stays integrated as a supporting signal, never the
headline. Strategy + blind-spot plans: `docs/market-positioning.md`.

**Trust layer**
- Proof-of-Fix artifact: every apply run writes `.apex/proof-of-fix.json`
  (finding cited, exact diff, test run evidence, rollbacks, commits)
  — `app/engine/proof_of_fix.py`.
- Coverage-aware verification strength (`app/engine/verification_strength.py`):
  each verified fix graded function / module / none / test-change; weakest
  link across changed files; reported in proof + maintenance markdown.
- Test-first shield: a fix targeting a module NO test references first gets a
  generated characterization test (verified), then applies under its
  protection (`apply_plan(test_first=True)`).
- SARIF 2.1.0 export: `apex review --sarif` (`app/engine/sarif_export.py`).

**Multi-file refactoring (span-edit machinery)**
- `apex rename OLD NEW` — definition + imports + call sites, comment-preserving,
  blockers on ambiguity/shadow/collision (`app/execution/cross_file_rename.py`).
- `apex move SRC DST` — module move; every import form rewritten project-wide,
  `__init__.py` created, relative-import cases block (`app/execution/move_module.py`).
- Both: `--dry-run` diffs, test-verified apply, full rollback.

**Richer fact base for the idea engine**
- Git-churn hotspots (`ProjectProfiler._scan_churn`) → "churn-hotspot" seeds
  (Evolve phase) + "high-churn" convergence dimension (change×complexity).
- Debt-marker age via git blame (`_scan_debt_age`) → stale debt narrated
  ("oldest has waited N months").
- Level-3 content-aware facet vocabulary; facet budget stretches with
  requested zoom depth (12% at depth<=2, +6%/level, cap 30%).

**Cross-run narrative**
- Roadmap snapshots carry per-item provenance (`grounded_in`); `--roadmap
  --diff` narrates which signal produced each new idea / stopped firing
  (`app/engine/roadmap_history.py`).
- Dashboard: proof-of-fix section, roadmap-changes section, churn + stale-debt
  in the profile (`app/reporting/dashboard.py`).

---

## Implemented Features

### Phase 1: Safety & Mode Foundation ✅
- **ModePolicy** (`app/policies/mode_policy.py`)
  - `ApexMode` enum: `report`, `supervised`, `autonomous`
  - `ModePermissions` per mode with granular permissions
  - `can_write()`, `can_commit()`, `enforce_clean_working_tree()`
- **Safety Gates** (`app/policies/safety_gates.py`)
  - `SafetyGates` class with 5 checks:
    - `patch_scope`: Max changed files
    - `sensitive_paths`: Block .env, secrets, .ssh
    - `secret_detection`: Regex for passwords, API keys, tokens
    - `test_verification`: Run tests after patch
    - `rollback_ready`: Ensure files exist
- **CLI Flags** (`app/cli.py`)
  - `--auto-patch`, `--auto-commit`, `--max-fractal-budget`, `--safety-policy`

### Phase 2: Semantic Patch Infrastructure ✅
- **Wired fractal patches to semantic patch generator** (`app/engine/fractal_cortex.py`)
  - `SemanticPatchGenerator` integration
  - Falls back to deterministic patches if semantic fails
- **Patch Metadata** (`app/engine/fractal_patch_generator.py`)
  - Added `reversible` and `patch_source` fields

### Phase 3: Real Fallback Execution ✅
- **Fallback strategies** (`app/agents/fractal_agents.py`)
  - `add_input_validation` for eval issues
  - `add_command_whitelist` for os.system issues
  - Executes when primary patch fails

### Phase 4: Reflection Feeds Behavior ✅
- **Adaptive Planner** (`app/engine/planner.py`)
  - `_extract_issue_type()`: Pattern extraction
  - `_is_known_false_positive_pattern()`: Skip bad patterns
  - `_get_confidence_boost()`: Adjust confidence
  - `record_action_result()`: Store results for learning
- **Feedback Integration** (`app/engine/feedback_loop.py`)
  - Per-node and per-type learning
  - EMA-based confidence updates

### Phase 5: Reports ✅
- **Enhanced FinalReport** (`app/models/report.py`)
  - `autonomy_mode`: Current mode
  - `safety_gates_passed`: Gate status
  - `patches_applied/blocked`: Patch stats
  - `feedback_learned_patterns`: Recent learning
- **ReportComposer Updates** (`app/orchestrator/report_composer.py`)
  - Autonomy context in reports

### Phase 6: Multi-Limb Agent System ✅
- **Limbs** (`app/agents/limbs/__init__.py`)
  - `DebugLimb`: Runtime error diagnosis
  - `CoverageLimb`: Test coverage analysis
  - `RefactorLimb`: Code quality improvements
  - `DependencyLimb`: Package management
  - `DocLimb`: Documentation generation
  - `CILimb`: CI/CD pipeline execution

---

## Test Coverage

**87+ tests passing:**
- Mode policy: 16 tests
- Safety gates: 14 tests
- Automation plans: 7 tests
- Fractal cortex/agents: 9 tests
- Planner reflection: 4 tests
- Limbs: 19 tests
- Swarm stability: 11 tests
- Pre-existing: 4 tests (flaky)

---

## Architecture

```
Apex Architecture (Brain-Hands-Limbs)

┌─────────────────────────────────────────────────────────┐
│                    APEX ORCHESTRATOR                     │
├─────────────────────────────────────────────────────────┤
│  Brain (Cortex)     │  Hands (Executor) │  Limbs      │
│  ───────────────    │  ───────────────  │  ─────      │
│  Fractal5Whys       │  ActionExecutor   │  Debug      │
│  MetaAnalysis       │  SemanticPatch    │  Coverage    │
│  Decision           │  SafetyGates      │  Refactor   │
│                     │  Fallback        │  CI         │
│                     │                  │  Dependency  │
│                     │                  │  Doc        │
├─────────────────────────────────────────────────────────┤
│  Memory/Feedback    │  Policy          │  Reports    │
│  ─────────────      │  ──────          │  ───────    │
│  FeedbackLoop       │  ModePolicy      │  FinalReport│
│  Reflector          │  SafetyGates     │  Composer   │
│  Planner            │  (gates before   │             │
│                     │   autonomous)    │             │
├─────────────────────────────────────────────────────────┤
│  Swarm Stability    │                  │              │
│  ──────────────     │                  │              │
│  SwarmTimeout       │                  │              │
│  GracefulShutdown   │                  │              │
│  SwarmStability    │                  │              │
└─────────────────────────────────────────────────────────┘
```

---

## Pending: Phase 7 - Swarm Stabilization

- Distributed swarm/socket tests can stall ~185 tests
- Needs explicit timeouts/shutdown
- Multi-agent coordination improvements

---

## COMPLETED: Phase 7 - Swarm Stabilization ✅

- **SwarmTimeout** (`app/agents/swarm_stability.py`)
  - Per-operation timeout management
  - Thread-based timer support
  - Cancel/cleanup capabilities

- **GracefulShutdown** (`app/agents/swarm_stability.py`)
  - Shutdown request handling
  - Agent finish waiting
  - Thread-safe state management

- **SwarmStability** (`app/agents/swarm_stability.py`)
  - `run_with_timeout()`: Execute with timeout
  - `wait_with_shutdown_check()`: Wait with shutdown support
  - Decorators: `@with_timeout`, `@with_graceful_shutdown`

- **Tests** (`tests/test_swarm_stability.py`)
  - 11 tests covering timeout, shutdown, stability

---

## COMPLETED: Memory and Execution Hardening ✅

### 1. Feedback Deduplication & Confidence Decay
- **FeedbackLoop** (`app/engine/feedback_loop.py`)
  - Duplicate detection within time window (300s default)
  - Confidence decay over time (30-day halflife)
  - Memory cleanup (max 50 entries per node)
  - Source tracking ("auto" or "human")
  - Statistics and hygiene methods

### 2. Patch Rollback Journal
- **RollbackJournal** (`app/engine/rollback_journal.py`)
  - Record patches with old content
  - Rollback individual or all patches
  - Track promoted vs reverted status
  - Statistics and cleanup

### 3. Swarm Timeout Coordinator Integration
- **SwarmCoordinator** (`app/agents/swarm_coordinator.py`)
  - Integrated SwarmStability
  - GracefulShutdown handling
  - Per-operation timeouts (scan: 30s, analyze: 45s, patch: 60s, test: 120s, total: 180s)
  - Timeout detection and logging
  - Stability status tracking

### 4. Targeted Test Selection
- **TargetedTestSelector** (`app/execution/targeted_test_selector.py`)
  - Find tests for changed files
  - Prioritize by uncovered functions
  - Support pytest markers
  - TestRunner with timeout

### 5. Run Comparison Report
- **RunComparison** (`app/engine/run_comparison.py`)
  - Record run snapshots
  - Compare recent runs
  - Calculate trends
  - Statistics and analysis

### 6. Checkpoint Automation
- **CheckpointManager** (`app/engine/checkpoint_manager.py`)
  - Auto-save after milestones
  - Git integration
  - Run metadata tracking
  - Recovery support

---

## Key Files Added

- `app/engine/rollback_journal.py` (NEW)
- `app/engine/run_comparison.py` (NEW)
- `app/engine/checkpoint_manager.py` (NEW)
- `app/execution/targeted_test_selector.py` (NEW)
- `app/policy/mode.py` (NEW — autonomy-safety-core)

## New Test Files

- `tests/test_mode_policy.py`
- `tests/test_safety_gates.py`
- `tests/test_planner_reflection.py`
- `tests/test_limbs.py`
- `tests/test_swarm_stability.py`

---

## autonomy-safety-core Milestone — COMPLETE

### New Files
- `app/policy/mode.py` — `ApexMode`, `ModePermissions`, `SafetyPolicy`, `ModePolicy`, `_build_mode_table`
- `app/policy/__init__.py` — policy module exports
- `tests/test_mode_policy.py` — 23 tests
- `.apex/safety.yml` — safety policy template

### Mode Policy System (`app/policy/mode.py`)
- Modes: `report` | `supervised` | `autonomous`
- Permission matrix per mode (can_write, can_stage, can_commit, can_force, can_auto_patch, can_auto_commit, requires_safety_gates, requires_clean_tree)
- `SafetyPolicy`: check_scope, check_secrets, check_tests, check_sensitive_files, allow_rollback, max_patch_files, blocked_paths, blocked_patterns, required_test_files
- `ModePolicy.from_env()` — reads all APEX_* environment variables
- `can_apply_patch()` — enforces scope limits, blocked paths/patterns, clean working tree
- `SafetyPolicy.from_yaml()` — loads from YAML file (missing file returns defaults)

### CLI Flags Updated
- `--mode {report,supervised,autonomous}` on `scan` and `run`
- `--dry-run` on `run` — validates patch without writing
- `--safety-policy` on `scan`, `run`, fractal `analyze`
- `--max-fractal-budget` on fractal `analyze`
- `APEX_MODE`, `APEX_AUTO_PATCH`, `APEX_AUTO_COMMIT`, `APEX_MAX_FRACTAL_BUDGET`, `APEX_SAFETY_POLICY`, `APEX_DRY_RUN` all wired

### ActionExecutor Enhancements
- `dry_run` parameter on `execute_patch()` — validates without writing
- `rollback_all()` — rollback all non-reverted patches
- `rollback_file(path)` — rollback specific file by path

### Planner Integration
- `AutonomousPlanner.build_plan(intent, project_profile, policy)` accepts optional `ModePolicy`
- `can_patch = intent.mode != "report"` (supervised/autonomous retain patching steps)

### `.apex/safety.yml` Template
- Comprehensive blocked paths: .env, secrets/**, *.key, *.pem, .ssh, .aws, credentials
- Blocked regex patterns for secrets
- max_patch_files: 20

### Test Updates (633 passing)
- `tests/test_cli_run.py` — args namespace extended with fractal, auto_patch, auto_commit, max_fractal_budget, safety_policy, dry_run
- `tests/test_fractal_cli.py` — DummyNamespace extended with max_fractal_budget
- `tests/test_supervised_patch_loop.py` — step indices shifted (+1 safety_gate_check); apply_patch output checked flexibly
- `tests/test_git_pr_loop.py` — step indices shifted (+1 safety_gate_check)
- `tests/test_main_fractal.py` — `APEX_MODE=report` set to bypass clean-tree blocks
- `tests/test_cognitive_loop.py` — `EPISTEMIC_TARGET_ROOT` monkeypatched; graceful error accepted

### Next Phase Suggestion
1. Replace fractal string patching with semantic AST patch requests (Phase 2)
2. Implement real fallback execution in `BaseFractalAgent` (Phase 3)
3. Feed reflection into future strategy selection (Phase 4)
4. Stabilize distributed swarm (Phase 7)
5. Add improved memory/report UI (Phase 5)

---

## COMPLETED: Phase 6 — Cross-Run Findings Persistence (JSON/Shelve)

- **FindingsPersistence** (`app/memory/findings_persistence.py`)
  - Pluggable backends: `json` and `shelve`
  - `record_findings(run_id, findings, run_meta)` — dedupe, status tracking, eviction
  - `get_persistent_findings(min_runs=2)` — claims seen across multiple runs
  - `get_resolved_findings()` — claims marked resolved or potentially resolved
  - `update_claim_status()`, `get_open_claims()`, `build_recall_prompt()`
  - `export_state()` / `import_state()` for backup and migration
  - Context-manager support (`with FindingsPersistence(...) as store:`)
  - Configurable limits: `max_claims`, `max_runs`

- **Tests** (`tests/test_findings_persistence.py`)
  - 12 tests covering JSON and Shelve backends
  - Round-trip export/import, eviction, context manager, invalid backend

---

## COMPLETED: Phase 7 — Reasoning Graph Visibility

- **ReasoningGraphExporter** (`app/reporting/reasoning_graph_exporter.py`)
  - Data model: `ReasoningNode`, `ReasoningEdge`, `ReasoningGraph`
  - Mermaid export with shapes/colors per node type and confidence
  - Markdown export grouped by node type
  - HTML export with colored cards
  - Dict round-trip serialization

- **ReportComposer Integration** (`app/reporting/composer.py`)
  - `to_markdown()` auto-renders `reasoning_graph` in results
  - `to_html()` auto-renders `reasoning_graph` in results

- **Tests** (`tests/test_reasoning_graph_exporter.py`)
  - 9 tests covering Mermaid, Markdown, HTML, round-trip dict, line styles, shapes/colors, ReportComposer integration

---

## COMPLETED: Distributed Swarm End-to-End Tests

- **Enhanced Test Coverage** (`tests/test_distributed_swarm.py`)
  - `test_distributed_run_e2e` — round-robin dispatch across online nodes
  - `test_distributed_run_with_aggregator` — custom aggregation function
  - `TestCircuitBreaker` — 4 tests: success, open after failures, half-open recovery, failure reset
  - `TestSwarmNodeServerLifecycle` — start/stop health verification
  - Robust fixture with `_wait_for_server` retry helper

---

## New Files
- `app/memory/findings_persistence.py` (NEW)
- `app/reporting/reasoning_graph_exporter.py` (NEW)
- `app/reporting/__init__.py` (NEW)
- `tests/test_findings_persistence.py` (NEW)
- `tests/test_reasoning_graph_exporter.py` (NEW)

## Updated Files
- `app/memory/__init__.py` — exports `FindingsPersistence`
- `app/reporting/composer.py` — reasoning graph rendering in Markdown and HTML
- `tests/test_distributed_swarm.py` — expanded coverage, circuit breaker, lifecycle tests
- `CHECKPOINT.md` — this update

---

## COMPLETED: Self-Audit & Meta-Scan Capability

- **SelfAuditAgent** (`app/agents/skills/self_audit_agent.py`)
  - AST-based risk detection (eval, exec, os.system, pickle.loads, bare except)
  - Missing docstring analysis
  - Long function detection (>50 lines)
  - TODO/FIXME/HACK comment scanning
  - Coverage gap analysis (tested vs untested modules)
  - Registered in `app/agents/skills/__init__.py`

- **Self-Audit Script** (`scripts/self_audit.py`)
  - Standalone script that runs the same analysis on any project
  - Produces `.apex/self-audit-report.md` with recommendations
  - Detected **962 missing docstrings**, **55 long functions**, **6 TODOs** in Apex itself

- **Tests** (`tests/test_self_audit_agent.py`)
  - 6 tests covering clean code, eval detection, docstrings, long functions, todos, coverage gap

---

## COMPLETED: LLM Multi-Model Integration Tests

- **CostAwareRouter Tests** (`tests/test_llm_multi_model.py`)
  - `test_estimate_cost` — cost calculation verification
  - `test_select_model_for_budget` — affordable model selection
  - `test_cost_aware_router_no_op` — none provider fallback
  - `test_cost_aware_router_snapshot` — session cost tracking
  - `test_cost_aware_router_multi_model_config` — multi-model parsing
  - `test_cost_aware_router_fallback_chain` — fallback execution
  - 6 tests, all passing

---

## COMPLETED: Central Memory Bridge

- **CentralMemoryBridge** (`app/memory/bridge.py`)
  - Unifies `CrossRunTracker`, `FindingsPersistence`, and `AgentLearning`
  - `record_run(run_id, claims, findings)` — writes to all stores
  - `get_open_claims()` — deduplicated aggregation from cross-run + findings
  - `get_persistent_claims(min_runs)` — claims seen across multiple runs
  - `get_learning_tips(agent)` — behavioral learning tips
  - `build_recall_prompt()` — cross-run recall prompt
  - Context-manager support
  - Exported from `app/memory/__init__.py`

- **Tests** (`tests/test_memory_bridge.py`)
  - 6 tests covering record/retrieve, dedupe, learning, persistent claims, recall prompt, context manager

---

## COMPLETED: VS Code Extension

- **Extension Code** (`vscode-extension/`)
  - `package.json` — manifest with 4 commands: Project Scan, Semantic Patch, Run Tests, Open Presence Log
  - `tsconfig.json` — TypeScript configuration
  - `src/extension.ts` — command handlers with progress notifications and webview output
  - Supports configurable `apex.pythonPath` and `apex.projectRoot`

---

## COMPLETED: Git Integration End-to-End

- **GitAdapter Enhancements** (`app/runtime/git_adapter.py`)
  - `push(repo_dir, remote, branch)` — push to remote
  - `tag(repo_dir, tag_name, message)` — create tags
  - `remote_add(repo_dir, name, url)` — add remotes
  - `remote_list(repo_dir)` — list remotes
  - `stash(repo_dir, message)` — stash changes

- **Tests** (`tests/test_git_e2e.py`)
  - 10 tests with real temp git repos: create_branch, add/commit, diff, status, log, tag, stash, remote_add, restore
  - All tests use actual `git` binary via `CommandRunner`

---

## COMPLETED: Deployment & Operations

- **Dockerfile** — multi-stage Python 3.11 slim image with git, `pip install -e .[dev]`, exposed port 8767
- **Helm Chart** (`helm/apex-orchestrator/`)
  - `Chart.yaml`, `values.yaml`, `templates/deployment.yaml`, `templates/pvc.yaml`, `templates/service.yaml`, `templates/_helpers.tpl`
  - Configurable replica count, resources, persistence, environment variables
- **Prometheus Metrics Exporter** (`app/metrics/exporter.py`)
  - `PrometheusExporter` — counter, gauge, histogram with label support
  - `MetricsMiddleware` — `record_run()` and `record_test()` helpers
  - `render()` produces Prometheus-compatible text format
  - `snapshot()` for debugging

- **Tests** (`tests/test_metrics_exporter.py`)
  - 6 tests covering counter, gauge, snapshot, clear, middleware run recording, test recording

---

## New Files (This Session)
- `scripts/self_audit.py` (NEW)
- `app/agents/skills/self_audit_agent.py` (NEW)
- `app/memory/bridge.py` (NEW)
- `app/metrics/exporter.py` (NEW)
- `Dockerfile` (NEW)
- `helm/apex-orchestrator/Chart.yaml` (NEW)
- `helm/apex-orchestrator/values.yaml` (NEW)
- `helm/apex-orchestrator/templates/deployment.yaml` (NEW)
- `helm/apex-orchestrator/templates/pvc.yaml` (NEW)
- `helm/apex-orchestrator/templates/service.yaml` (NEW)
- `helm/apex-orchestrator/templates/_helpers.tpl` (NEW)
- `vscode-extension/package.json` (NEW)
- `vscode-extension/tsconfig.json` (NEW)
- `vscode-extension/src/extension.ts` (NEW)
- `tests/test_self_audit_agent.py` (NEW)
- `tests/test_memory_bridge.py` (NEW)
- `tests/test_llm_multi_model.py` (NEW)
- `tests/test_git_e2e.py` (NEW)
- `tests/test_metrics_exporter.py` (NEW)

## Updated Files (This Session)
- `app/agents/skills/__init__.py` — exports `SelfAuditAgent`
- `app/memory/__init__.py` — exports `CentralMemoryBridge`
- `app/runtime/git_adapter.py` — push, tag, remote_add, remote_list, stash
- `CHECKPOINT.md` — this update

## COMPLETED: LLM Fallback in Semantic Patch Generator

- **LLM Fallback Generator** (`app/execution/semantic/generators/llm_fallback.py`)
  - Called when AST transforms don't apply to a target file
  - Builds prompt from file context + strategy + task title
  - Returns `SemanticPatchResult` with `expected_old_content` set for safety
  - Strips markdown fences from LLM output
  - Graceful degradation on LLM errors (returns None → draft fallback)

- **SemanticPatchGenerator Integration**
  - Accepts optional `llm_router` in `__init__`
  - After AST transform failure, tries LLM fallback per file before draft mode
  - Transform type prefixed: `llm_{strategy}` (e.g., `llm_add_docstring`)

- **Mock LLM Server** (`scripts/mock_llm_server.py`)
  - Local OpenAI-compatible HTTP server for testing without API keys
  - Context-manager friendly for test fixtures
  - Returns heuristic responses based on prompt keywords

- **DeepSeek Provider Tests** (`tests/test_deepseek_provider.py`)
  - 7 tests: defaults, custom model/base_url, complete response, message passing, router registration

- **LLM Fallback Tests** (`tests/test_semantic_llm_fallback.py`)
  - 6 tests: generates patch, skips when no LLM, SKIP response, exception handling, fence stripping, AST priority

- **Demo Script** (`scripts/demo_llm_difference.py`)
  - Side-by-side comparison: NoOp vs LLM-assisted
  - Shows concrete difference in output quality

---

## COMPLETED: Distributed Swarm Stability Fix

- **Dynamic Port Allocation** (`app/engine/distributed_swarm.py`)
  - `SwarmNodeServer` supports `port=0` for OS-assigned free ports
  - `actual_port` property exposes bound port
  - Added `SO_LINGER`, `shutdown(SHUT_RDWR)` for clean socket close
  - `OSError` break in accept loop prevents hang on stop

- **Test Fixes** (`tests/test_distributed_swarm.py`)
  - All hardcoded ports replaced with `port=0` + `actual_port`
  - Race condition fixed: retry loop waits for socket bind before health check
  - 13/13 tests passing, suite no longer hangs

## COMPLETED: LLM-Enhanced Agents

---

## REMOVED: External LLM Integration

- **Reason**: External API dependencies (OpenAI, DeepSeek, OpenRouter) proved unreliable for consistent operation
- **Result**: Zero mandatory external dependencies restored — all core features work with stdlib only

### Files Removed
- `app/execution/semantic/generators/llm_fallback.py`
- `tests/test_deepseek_provider.py`
- `tests/test_openrouter_provider.py`
- `tests/test_semantic_llm_fallback.py`
- `tests/test_llm_enhanced_agents.py`
- `scripts/test_deepseek_real.py`
- `scripts/test_openrouter_live.py`
- `scripts/mock_llm_server.py`
- `scripts/demo_llm_difference.py`

### Files Reverted
- `app/llm/router.py` — Only `NoOpProvider` remains (returns empty response)
- `app/llm/cost_registry.py` — External provider imports removed, falls back to `NoOpProvider`
- `app/execution/semantic_patch_generator.py` — LLM fallback logic removed
- `app/agents/skills/docstring_agent.py` — Placeholder docstrings only
- `app/agents/skills/security_agent.py` — AST-based detection only, no LLM enrichment

---

## Test Summary
- **89 core tests passing** (semantic patch, LLM router noop, cost registry, distributed swarm, mode policy, safety gates, agents)
- **Zero external API dependencies** ✅
- **Total collected**: 756 tests in suite ✅

---

## Phase 8: Integration Hardening & Evaluation ✅ (2026-05-30)

A holistic audit (3 parallel reviews + manual verification) found the verdict:
**components are real, but the integration/wiring layer was the weak point.**
This phase wires the real components into a working end-to-end pipeline and
closes the highest-leverage gaps. All changes are deterministic; LLM remains
strictly optional and off by default.

### 8.1 Bug fixes & stability
- `app/llm/agent_adapter.py` — `json`/`re` moved to module scope (fixed latent
  `NameError` in `analyze_claim`).
- `app/engine/fractal_patch_generator.py` — `os.system→subprocess` patch now
  uses `shlex.split`; placeholder docstring/test templates made usable.
- `app/engine/self_improvement.py` — real `missing_docstrings` AST count
  (was hardcoded `0`).

### 8.2 Quality cleanup
- `app/execution/semantic/generators/stub.py` — misleading `assert True` stub
  replaced with a skipped `NotImplementedError` placeholder (no false coverage).
- `app/agents/fractal_agents.py` — fragile `split("# TODO")` replaced with
  `_minimal_code()`.
- Removed dead `app/engine/router.py` (`ModelRouter`).

### 8.3 Optional free LLM providers (off by default)
- `app/llm/router.py` — `OpenAICompatibleProvider` (stdlib `urllib`, zero deps)
  + presets: **github**, groq, gemini, openrouter, ollama. Keys via env
  (`api_key_env`); missing key / network error degrades to deterministic logic.
- Wired into the orchestrator as an *optional* report summary
  (`FinalReport.llm_summary`); `provider: none` keeps runs fully offline.
- Docs: `docs/free-llm-setup.md`. Endpoint reachability verified (HTTP 401).

### 8.4 Focus on the main idea (deterministic)
- `app/skills/relevance_scorer.py` — `RelevanceScorer` scores each claim/branch
  against the objective. Used three ways: prioritise (always on), prune
  off-topic drift (`focus.min_relevance` opt-in), observe
  (`debug_stats.mean_relevance`, `focus_drift_pruned`).

### 8.5 Swarm wiring fix (P0 — biggest functional gap)
- `app/agents/swarm_coordinator.py` — every scanner role now runs on
  `scan.complete` (was security-only). `app/main.py` `_build_swarm_for_plan`:
  `project_scan` registers all four read-only scanners.
- **Result:** `project_scan` on `examples/flask_mini` went from **0 → 4**
  scanner results. Locked by `tests/test_swarm_scan_wiring.py`.

### 8.6 Orphaned reasoning engines wired in
- `CounterfactualGenerator` + `ConfidenceCalibrator` (`app/engine/*`) were
  implemented + unit-tested but never called (`used_in_app=0`). The
  orchestrator now stress-tests each claim with counterfactual scenarios
  (`node.counterfactuals`) and calibrates confidence from evidence quality
  (`node.confidence_reliability`). Config: `reasoning.deep` (default true).

### 8.7 Deeper, claim-specific questions
- `app/skills/question_generator.py` — replaced the four identical generic
  stems with domain-tailored phrasing (security / tests / architecture /
  config / CI / feature-gap / operations), reusing `ClaimAnalyzer` and
  anchoring on the detected signal. Deterministic, no LLM.

### 8.8 Packaging & tooling
- `pyproject.toml` — `[project.scripts]` exposes **`apex`** and **`apex-mcp`**;
  added `pytest-cov` + `[tool.coverage]`.
- Fixed pytest collection warning (`TestStubAgent.__test__ = False`).
- `.gitignore` — ignore `.coverage`/`htmlcov`.

### Notes / honest caveats
- The "5 missing reasoning engines" claim from one audit pass was **wrong** —
  the files exist; they were merely unwired (now fixed in 8.6).
- The bare `except:` flagged in `app/validation/django_mini_factory.py` is
  **intentional fixture code** (deliberately-flawed Django for the scanner to
  find) and was left as-is.
- Still open for a future phase: plugin hooks in the main swarm path (P0.3),
  CI quality gates (ruff/mypy/coverage), and broader `engine/`+`memory/`+
  `tools/` test coverage.

---

## Phase 9: Idea Permutation Engine ✅ (2026-05-30)

The project's core vision, now a working feature: a **generative** fractal that
splits a project into autonomous development branches and permutes each into
operator-sequence sub-branches — the "abc" of every "a". Derived from the real
codebase, fully deterministic (no LLM). Design: `docs/idea-permutation-engine.md`.

- **Models** (`app/models/idea.py`): `IdeaNode` (traceable to `source_facts` +
  `operator_chain`), `IdeaTreeReport`.
- **Seeder** (`app/engine/idea_permutation.py` `IdeaSeeder`): root development
  branches from `ProjectProfiler` facts (dependency hubs, untested/sensitive/
  entrypoint modules, symbol hubs, missing CI).
- **Engine** (`IdeaPermutationEngine`): best-first expansion applying the
  `DEVELOPMENT_OPERATORS` alphabet (extend/harden/test/simplify/document/
  integrate/generalize/observe) each idea hasn't used yet, so every branch path
  is a unique permutation of lenses over a code subject. Reuses RelevanceScorer,
  CounterfactualGenerator (per-idea caveats), GraphStore dedup, BudgetController.
  `value = 0.4*relevance + 0.3*novelty + 0.3*feasibility`.
- **CLI**: `apex ideate --target=. --depth --breadth --max-ideas --min-relevance
  --objective --mermaid --json --out` → hierarchical markdown + Mermaid tree.
- **Tests**: 21 new (seeder rules/limits/dedup, permutation uniqueness & chain
  integrity, budget, relevance pruning, determinism, rendering, CLI smoke).
- **Future (P-D)**: MCP `apex_ideate` tool, optional LLM polish of titles, and
  plugin-contributed operators.

---

## Phase 10: Idea→Action, CI gate, docs (2026-05-30)

Four-theme follow-up to Phase 9.

- **A — Idea→Action bridge** (`app/engine/idea_action_bridge.py`): maps each
  idea's terminal operator (or a root's fact) to a known action type, marking
  executable ones (create_test_stub/add_docstring/harden_security/
  organize_imports) vs design tasks. `apex ideate --actions --top N` prints a
  value-ordered, supervised plan that is **never applied**.
- **A2 — Idea engine P-D**: operator/fact-aware counterfactual caveats (relevant,
  not generic); new MCP tool `apex_ideate` (tree + optional action plan).
- **B — CI gates**: `[tool.ruff]` config (select E/F/W, ignore E402 intentional
  `__future__`-first pattern); fixed remaining pyflakes (TYPE_CHECKING forward
  refs, dead imports, ambiguous name) so `ruff check app/` is green; `ci.yml`
  gains a ruff lint job + coverage (term + xml).
- **C — Docs & honesty**: README Idea Permutation Engine section + refreshed
  roadmap; new `ROADMAP.md`; explicit "Experimental (not production-ready)"
  labels for the K8s operator, Helm chart, and VS Code extension.

Remaining (ROADMAP): plugin-contributed operators, optional LLM polish of idea
titles, idea→real-patch drafting, and raising `engine/`/`memory/`/`tools/`
coverage.
