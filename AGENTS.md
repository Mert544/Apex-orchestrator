# Apex Orchestrator — Agent Development Guide

## Product Identity

- **Name:** Apex Orchestrator
- **Tagline:** Agents for fractal codebase intelligence
- **Vision:** Branch-aware, memory-aware, supervised engineering agent evolving toward guarded autonomous coding

## Build & Test

```bash
# Setup
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]

# Run all tests
pytest

# Run security audit
python scripts/security_audit.py

# Run specific test groups
pytest tests/test_semantic_patch_generator.py
pytest tests/test_retry_engine.py
pytest tests/test_git_pr_loop.py
pytest tests/test_token_telemetry.py
pytest tests/test_compressed_mode.py
pytest tests/test_llm_router.py
pytest tests/test_mcp_server.py

# Run the main orchestrator
python -m app.main

# Run with automation plans
export EPISTEMIC_TARGET_ROOT=/path/to/project
export EPISTEMIC_AUTOMATION_PLAN=project_scan
python -m app.main

# Run MCP server (stdio transport)
python -m app.mcp.server
```

## Architecture Decisions

### 1. No Mandatory External Dependencies
- LLM integration is **optional** via `llm.provider: none` (default)
- `openai` package is **not** in default dependencies
- All core features work with stdlib only

### 2. AST Before LLM
- Semantic patch generator tries AST transforms first
- Only falls back to draft/LLM if no safe transform applies
- This keeps the system deterministic and auditable
- Supported transforms: `add_docstring`, `add_type_annotations`, `add_guard_clause`, `repair_test_assertion`, `create_test_stub`, `rename_variable`, `extract_method`, `inline_variable`, `organize_imports`, `move_class`, `extract_class`

### 3. Token Budget Awareness
- Every run tracks token consumption
- Budget limit can be set in config (`token_budget_limit`)
- Exceeded budget stops expansion gracefully

### 4. Cross-Platform Path Handling
- Always use `Path.as_posix()` when asserting paths in tests
- Never assume `/` separator in assertions

## Coding Conventions

- **Imports:** `from __future__ import annotations` at top
- **Type hints:** Required for public APIs
- **Dataclasses:** Prefer over raw dicts for structured data
- **Tests:** Use `tmp_path` fixture, self-contained demo projects
- **Error handling:** Graceful degradation, never crash the orchestrator

## Configuration

Key config values in `config/default.yaml`:

```yaml
mode: balanced              # balanced | compressed
max_depth: 3
max_total_nodes: 20
top_k_questions: 2
token_budget_limit: 0       # 0 = unlimited

llm:
  provider: none            # none | openai | local
  api_key: ""
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  max_tokens: 2048
  temperature: 0.2
```

## Safety Rules

1. Never make external API calls unless user explicitly configures `llm.provider`
2. Always use `expected_old_content` in patches
3. Never modify files outside project root
4. Sensitive edits require human review (blocked from auto-retry)
5. Max changed files default: 5 (configurable)

## Automation Plans

| Plan | Purpose |
|---|---|
| `project_scan` | Full repo analysis |
| `focused_branch` | Deepen one branch |
| `verify_project` | Profile + test run |
| `semantic_patch_loop` | Research → semantic patch → verify → retry |
| `semantic_apply_loop` | Clone → semantic patch → verify → retry |
| `git_pr_loop` | Diff → commit → PR summary |
| `full_autonomous_loop` | End-to-end: research → patch → verify → retry → commit → PR → telemetry |
| `self_directed_loop` | Self-directed: profile → research → auto-plan → patch → verify → commit → PR → telemetry |
| `telemetry_only` | Research + token report |

## Swarm Coordination

Run multiple Apex agents on different branches in parallel:

```python
from app.engine.swarm import SwarmCoordinator

coordinator = SwarmCoordinator(max_workers=4)
result = coordinator.run(
    branches=["x.a", "x.b", "x.c"],
    objective="Deepen all risk branches",
    runner_factory=lambda branch: run_focused_branch(branch),
)
print(result.aggregated_output["branch_map"])
```

- ThreadPoolExecutor ile paralel çalışma
- Hata durumunda graceful degradation
- Sonuçları otomatik birleştirir ve duplicate'leri temizler

## MCP Server Integration

Apex Orchestrator exposes its capabilities as an MCP server.

### Stdio Transport
- **No external dependencies:** Implemented with stdlib only (JSON-RPC 2.0 + Content-Length framing).
- **Tools exposed:** `apex_project_profile`, `apex_generate_patch`, `apex_apply_patch`, `apex_run_tests`.
- **Usage:** `python -m app.mcp.server`
- **Tests:** `tests/test_mcp_server.py`

### HTTP + SSE Transport
- **Remote usage:** Run `MCPHTTPServer` on any host/port.
- **Endpoints:** `POST /` for JSON-RPC, `GET /sse` for Server-Sent Events.
- **CORS enabled** for browser clients.
- **Tests:** `tests/test_mcp_http_server.py`

## Multi-Model Routing

Configure multiple models with cost-aware selection in `config/default.yaml`:

```yaml
llm:
  multi_model:
    enabled: true
    budget_usd: 0.05
    models:
      - model: gpt-4o-mini
        provider: openai
        api_key: ${OPENAI_API_KEY}
      - model: local
        provider: local
        base_url: http://localhost:11434/v1
```

- `CostAwareRouter` tries cheapest first, falls back on failure
- Session cost tracked in real time
- Budget enforcement stops calls when exceeded

## Cross-Run Memory

Track claims across runs to answer "is this still true?"

```python
from app.memory.cross_run_tracker import CrossRunTracker

tracker = CrossRunTracker(project_root)
tracker.record_run_claims(run_id="run-1", claims=[...])
open_claims = tracker.get_open_claims()
prompt = tracker.build_recall_prompt()
```

- Status lifecycle: `open` → `still_open` → `potentially_resolved` → `resolved`
- Auto-detects when a claim disappears from subsequent runs
- Produces recall prompts for the next run

## Function-Level Fractal Analysis

Zoom into individual functions and classes:

```python
from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer

analyzer = FunctionFractalAnalyzer()
results = analyzer.analyze_file("app/auth.py")
graph = analyzer.build_call_graph("app/")
impact = analyzer.compute_cross_file_impact("app/")
```

- Detects `eval()`, `os.system()`, `pickle.loads()`, bare except, missing docstrings via AST `Call` node inspection (no false positives from docstrings)
- Builds cross-file call graph
- Computes downstream impact for risky functions

## Self-Correction Loop

Agent evaluates its own claims before accepting them:

```python
from app.engine.self_correction import SelfCorrectionEngine

engine = SelfCorrectionEngine(min_confidence=0.6)
result = engine.evaluate(claim={"confidence": 0.3, ...}, budget_remaining=5)
# result.action: EXPAND_DEEPER, SEEK_COUNTER_EVIDENCE, BUDGET_HALT, FLAG_META
```

## Smart Plan Selection

```python
from app.automation.smart_planner import SmartPlanner

planner = SmartPlanner()
plan = planner.select_plan(project_profile, has_uncommitted_changes=False)
# Returns: project_scan, semantic_patch_loop, verify_project, git_pr_loop, full_autonomous_loop
```

## Real-World Validation

```bash
pytest tests/test_real_world_validation.py -v
```

Validates that Apex detects known issues in `examples/flask_mini/`:
- `eval()`, `os.system()`, `pickle.loads()`, bare except, missing docstrings

## Recursive Reflection Engine

Multi-layer self-scrutiny on every claim:

```python
from app.engine.recursive_reflection import RecursiveReflectionEngine

engine = RecursiveReflectionEngine(max_depth=4)
result = engine.reflect(claim={"text": "...", "evidence": [...], "confidence": 0.7})
# result.reflections: [Layer 1 — Evidence, Layer 2 — Boundary, Layer 3 — Counter-examples, Layer 4 — Meta]
# result.is_valid: True/False
```

## Hypothesis-to-Test Mapping

Convert claims into concrete pytest assertions:

```python
from app.engine.hypothesis_mapper import HypothesisMapper

mapper = HypothesisMapper()
result = mapper.map_to_test(claim={"text": "lacks input validation", "target_function": "process"})
# result.test_snippets: ["def test_process_rejects_invalid_input():..."]
```

## Abductive Reasoning

Infer root causes from observed patterns:

```python
from app.engine.abductive_reasoning import AbductiveReasoner

reasoner = AbductiveReasoner()
result = reasoner.infer([{"type": "long_function", "line_count": 55}])
# result.root_causes: ["Function has multiple responsibilities (SRP violation)", ...]
```

## Confidence Calibration

Statistical calibration with evidence diversity and conflict detection:

```python
from app.engine.confidence_calibration import ConfidenceCalibrator

calibrator = ConfidenceCalibrator()
result = calibrator.calibrate({"confidence": 0.8, "evidence": [{"source": "test", "weight": 1.0}]})
# result.adjusted_confidence, result.reliability, result.diversity_score
```

## Counterfactual Generator

Generate "what if" scenarios to stress-test claims:

```python
from app.engine.counterfactual_generator import CounterfactualGenerator

gen = CounterfactualGenerator()
result = gen.generate({"text": "lacks input validation", "context": "def process(data): return eval(data)"})
# result.scenarios: ["What if an attacker provides None?", "What if..."]
```

## Distributed Swarm

Run Apex agents across multiple machines:

```python
from app.engine.distributed_swarm import DistributedSwarmCoordinator, SwarmNode, SwarmNodeServer

# On remote machine
server = SwarmNodeServer("worker-1", host="0.0.0.0", port=18765)
server.register_task("scan", lambda payload: {"files": 42})
server.start()

# On coordinator
coord = DistributedSwarmCoordinator([
    SwarmNode("worker-1", "192.168.1.10", 18765),
    SwarmNode("worker-2", "192.168.1.11", 18765),
])
result = coord.run("scan", [{"branch": "x.a"}, {"branch": "x.b"}])
print(result.nodes_completed, result.aggregated_output)
```

## Advanced Refactoring

Extract interface or introduce parameter object:

```python
from app.execution.advanced_refactoring import AdvancedRefactoringEngine

# Create ABC from concrete class
result = AdvancedRefactoringEngine.extract_interface(source_code, "UserService")
print(result.new_content)  # class IUserService(ABC): ...

# Bundle parameters into dataclass
result = AdvancedRefactoringEngine.introduce_parameter_object(
    source_code, "create_order", param_indices=[0, 1, 2]
)
print(result.new_content)  # @dataclass class CreateOrderParams: ...
```

## Plugin Ecosystem

Register third-party hooks:

```python
from app.plugins.registry import PluginRegistry

registry = PluginRegistry(plugin_dirs=["./plugins"])
registry.load_all()

# Plugins run automatically at hook points
registry.run_hook("before_scan", {"target_root": "/path/to/project"})
registry.run_hook("after_patch", {"changed_files": [...]})
```

Hook points: `before_scan`, `after_scan`, `before_patch`, `after_patch`, `before_test`, `after_test`, `on_claim`, `on_report`

### Plugin Integration in `app.main`

When running automation plans, `app.main` automatically:
1. Loads plugins from `plugin_dirs` in config or `APEX_PLUGIN_PATH` env var
2. Passes the `PluginRegistry` to `SkillAutomationRunner`
3. Fires hooks at plan boundaries (`before_scan`, `after_patch`, `on_report`, etc.)

```python
# Example plugin: plugins/audit_plugin.py
__plugin_name__ = "audit"

def register(proxy):
    proxy.add_hook("before_scan", lambda ctx: print("Scan starting..."))
    proxy.add_hook("on_report", lambda ctx: print("Report generated."))
```

## Simulation Projects

Three synthetic validation targets with deliberately planted issues:

| Project | Issues |
|---|---|
| `examples/microservices_shop` | eval(), os.system(), pickle.loads, bare except, too_many_arguments, missing_docstring |
| `examples/legacy_bank` | eval(), exec(), os.system(), pickle.loads, too_many_arguments, missing_docstring |
| `examples/ml_pipeline` | eval(), exec(), os.system(), yaml.load, bare except, too_many_arguments, missing_docstring |

Run validation:
```bash
pytest tests/test_real_world_validation.py -v
```

## CI/CD Security Audit Pipeline

A GitHub Actions workflow (`.github/workflows/security-audit.yml`) runs:
1. Full test suite
2. `scripts/security_audit.py` — deterministic AST-based risk analysis
3. Uploads `.apex/security-report.json` as artifact
4. Fails pipeline if critical risks detected

The audit script uses AST `Call` node inspection (not naive string matching) to eliminate false positives from docstrings and string literals.

## Competitor Comparison

See `docs/comparison.md` for detailed positioning against GitHub Copilot, Cursor, Claude (Sonnet), and OpenAI Codex.

Key differentiators:
- **Fractal reasoning** vs linear completion
- **Cross-run memory** vs session-only
- **Deterministic self-correction** vs prompt-dependent
- **AST-first refactoring** vs LLM generation
- **Zero mandatory dependencies** vs cloud API required

## CLI Usage

```bash
# Scan a project
python -m app.cli scan --plan=project_scan --target=/path/to/project

# Install a plugin
python -m app.cli plugin install my-plugin
python -m app.cli plugin install https://example.com/plugin.py

# List installed plugins
python -m app.cli plugin list

# Uninstall a plugin
python -m app.cli plugin uninstall my-plugin

# Run registry server
python -m app.registry_server --port 8765
```

## Adding a New Skill

1. Implement skill function in the appropriate `app/automation/skills/*.py` file
2. Register in `build_default_registry()` in `app/automation/skills/registry_builder.py`
3. Add plan step in `app/automation/plans.py` if needed
4. Write test in `tests/test_<feature>.py`
5. Update this guide
