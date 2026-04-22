<div align="center">

# 🧠 Apex Orchestrator

### Agents for fractal codebase intelligence

**Scan deeper. Ask better questions. Focus the right branch.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-204%2F204%20passing-brightgreen)]()
[![Architecture](https://img.shields.io/badge/architecture-fractal-purple)]()
[![Memory](https://img.shields.io/badge/memory-degrade--not--block-green)]()
[![Focus](https://img.shields.io/badge/focus-branch--aware-orange)]()
[![Autonomy](https://img.shields.io/badge/autonomy-supervised%20→%20guarded-yellow)]()
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-blueviolet)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-black)](LICENSE)

> **Apex Orchestrator** is a branch-aware, memory-aware, supervised engineering agent that evolves toward guarded autonomous coding. It doesn't just read your codebase — it *reasons* about it.

[Quick Start](#quick-start) · [Core Concepts](#what-makes-it-different) · [Automation Plans](#automation-plans) · [Safety](#safety-first) · [Roadmap](#roadmap)

</div>

---

## Why this repo matters

Most code intelligence tools stop too early.

They give you one of these:
- a file tree
- a lint-style issue list
- a one-shot summary
- a vague “looks fine” answer

**Apex Orchestrator goes further.**

It treats a codebase like a living reasoning surface:
- extract structural claims
- challenge those claims
- branch recursively
- preserve memory across runs
- cut low-value recursion
- focus only where the next insight is worth the cost

This is not just repo analysis.
This is **fractal project reasoning**.

---

## What makes it different

### 1. It thinks in branches, not blobs
Instead of one flat summary, the engine builds a branch map such as:

```text
x.a     dependency hub risk
x.a.a   why this hub matters
x.a.b   what evidence could contradict it
x.b     sensitive surface claim
x.b.a   auth/payment expansion
```

### 2. It remembers without going blind
Most systems either:
- forget everything, or
- over-deduplicate and stop exploring

This project uses **degrade-not-block memory**:
- same-run duplicates still stop
- prior-run repeats are degraded, not killed
- important branches can reappear with lower novelty instead of disappearing completely

### 3. It cuts recursive noise
The system includes a spam guard that filters:
- repetitive meta-claims
- generic shell questions
- low-value recursive echoes

### 4. It lets the user steer depth
After a full scan, you can focus a specific branch like:
- `x.a`
- `x.a.b`
- `x.k.b`

and deepen only that subtree.

---

## The pitch in one sentence

**Apex Orchestrator is an agent brain for codebases: it scans, questions, prioritizes, remembers, and deepens the most valuable path instead of stopping at a shallow answer.**

---

## Core capabilities

- project-aware structural scanning
- claim extraction from repository signals
- claim typing and priority scoring
- recursive question generation with constitutional rules
- supporting and opposing evidence mapping
- branch maps like `x.a`, `x.a.b`, `x.c.a`
- persistent agent memory in `.epistemic/memory.json`
- degrade-not-block novelty logic
- branch focus mode
- debug stats for duplicates, memory degradation, spam filtering, and focus hits/misses
- grounded recommended actions
- skill automation plans such as `project_scan`, `focused_branch`, and `verify_project`
- **AST-based semantic patch generation** (docstring, type annotations, guard clauses, rename variable, extract method, test stub, assertion repair)
- **retry repair loop** with controlled retry budget
- **git diff / commit / PR summary** closing loop
- **token telemetry** with budget enforcement
- **compressed mode** for token efficiency
- **modular LLM router** (default: none, optional: openai/local)
- **MCP server** for IDE/tool integration via stdio

---

## How it works

```mermaid
flowchart TD
    A[Target Project] --> B[Perception Layer]
    B --> B1[Repo Scanner]
    B --> B2[Project Profiler]
    B --> B3[Dependency Signals]
    B --> B4[Test Linking]

    B --> C[Claim Seeding]
    C --> D[Claim Analysis]
    D --> D1[Type]
    D --> D2[Priority]
    D --> D3[Evidence]
    D --> D4[Assumptions]

    D --> E[Fractal Expansion]
    E --> E1[Missing Info Questions]
    E --> E2[Contradiction Questions]
    E --> E3[Risk Questions]
    E --> E4[Deepening Questions]

    E --> F[Memory + Spam Guard]
    F --> G[Branch Map]
    G --> H[Focused Expansion]
    H --> I[Actions + Final Report]
```

---

## What “fractal” means here

Fractal does **not** mean “keep recursing forever.”

It means every meaningful claim follows a disciplined loop:

1. derive a claim
2. classify and prioritize it
3. generate four mandatory question classes
4. search for supporting and opposing evidence
5. evaluate risk, quality, novelty, and security
6. expand only if the branch deserves more budget
7. expose not just conclusions, but the confidence structure behind them

---

## Core constitution

1. Do not stop at a single answer; decompose into claims.
2. For every claim, generate four mandatory question classes.
3. Search for counter-evidence against current conclusions.
4. Mark under-supported claims as low confidence.
5. Do not deepen a branch without security, quality, and verifiability checks.
6. Cut repetitive or low-value branches.
7. Tie expansion to budget and novelty thresholds.
8. Show the confidence structure, not only the final conclusion.

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
python -m app.main
```

Run against another project:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
python -m app.main
```

Run with skill automation:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=project_scan
python -m app.main
```

Verify a project quickly:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=verify_project
python -m app.main
```

Focus a branch:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=focused_branch
export EPISTEMIC_FOCUS_BRANCH=x.a.b
python -m app.main
```

---

---

## 🏢 3D Smart Office Dashboard

*Your codebase isn't just files — it's a living company. Walk the floor.*

Apex Orchestrator ships with a **fully interactive 3D Isometric Office Dashboard** that transforms abstract code intelligence into a living, breathing office building. Every engine module is a room. Every skill is an employee. Every room has depth, walls, and a worker inside.

```
                    🏢 Apex Corp. HQ — 3D Isometric Office
                           |
                           |  perspective: 1400px
                           v
              ┌─────────────────────────────────────┐
             /│  Reception  │  Board    │  Dev      │\
            / │    👩‍💼      │   👨‍💼     │   👨‍💻      │ \
           /  │    Maria    │   Boss    │   Coder   │  \
          /   ├─────────────┼───────────┼───────────┤   \
         /    │  Security   │  R&D Lab  │   QA Lab  │    \
        /     │    👮       │   👩‍🔬      │   👩‍🔬      │     \
       /      │    Guard    │   Prof    │   Tester  │      \
      /       ├─────────────┴───────────┴───────────┤       \
     /        │    ☕ Break Room    🏋️ Gym           │        \
    /         │      👨‍🍳 Barista      🧘‍♂️ Coach      │         \
   /          └─────────────────────────────────────┘          \
  /                      isometric floor                        \
 /───────────────────────────────────────────────────────────────\
```

### Your Team (10 SVG Vector Employees in 3D)

Every employee is a **hand-crafted SVG vector character** with full body proportions, facial expressions, clothing, and accessories — all drawn with native SVG shapes (`<ellipse>`, `<rect>`, `<circle>`, `<path>`). Zero images. Zero CDN. Zero dependencies.

| Department | Employee | Engine Module | 3D Animation |
|---|---|---|---|
| **Reception** | 👩‍💼 Maria | `ProjectProfiler` | Welcomes visitors |
| **Board Room** | 👨‍💼 Boss | `SmartPlanner` | Strategizes at the top |
| **Dev Office** | 👨‍💻 Coder | `SemanticPatchGenerator` | ⌨️ **Typing** (keys moving) |
| **QA Lab** | 👩‍🔬 Tester | `AbductiveReasoner` | Inspects with precision |
| **Security Office** | 👮 Guard | `EnhancedSafetyGovernor` | 🔄 **Scanning** (rotates left-right) |
| **R&D Lab** | 👩‍🔬 Prof | `RecursiveReflectionEngine` | 💡 **Deep thought** |
| **Archive Room** | 📦 Archie | `CrossRunTracker` | Organizes history |
| **HR / Swarm** | 👥 Team | `SwarmCoordinator` | Manages parallel teams |
| **☕ Break Room** | 👨‍🍳 Barista | `TokenTelemetry` | ☕ **Sipping coffee** (bobs up-down) |
| **🏋️ Gym** | 🧘‍♂️ Coach | `SystemHealth` | 🏃 **Walking** (side-to-side) |

### What Makes It Special

- **🧊 True 3D Isometric View** — `rotateX(60deg) rotateZ(-35deg)` with `preserve-3d`. Every room has a roof, front wall, and side wall. You are looking *down* at the building.
- **🎨 10 SVG Vector Characters** — Each employee is a detailed vector illustration: head, eyes, mouth, hair, torso, arms, hands, legs, shoes, and job-specific accessories (glasses, headset, clipboard, coffee cup, flashlight, apron, etc.). No images. No CDN. Zero dependencies.
- **📊 Floating Live Metrics** — Hover any room and a holographic metric label appears above it.
- **🔴🟡🟢 Room Status LEDs** — Each room has a pulsing colored dot: Green = idle, Yellow = busy, Red = alert, Blue = thinking.
- **📰 Scrolling Ticker** — Live event feed from all departments at the bottom.
- **🖱️ Click Any Room** — Opens a centered glassmorphism detail panel with full metrics and actions.
- **🌑 Dark Theme** — Deep navy background with glass walls and subtle grid floor. Feels like a real NOC/SOC control room.
- **📱 Responsive Scaling** — Auto-scales on mobile and tablets.

### Launch the 3D Office

```bash
# Start the dashboard
python -m app.engine.dashboard --port 8080

# Open your browser
open http://127.0.0.1:8080
```

*No build step. No npm install. No Three.js. No WebGL. Just pure CSS 3D transforms.*

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | The full 3D Isometric Office HTML dashboard |
| `GET /api/status` | Project root, file count, last run |
| `GET /api/telemetry` | Session cost, token usage |
| `GET /api/departments` | All 10 departments with live status |
| `GET /api/ticker` | Recent events from all engines |

---

## Demo project

A synthetic project is included under `examples/synthetic_shop`.
It is intentionally small, centralized, partially tested, and includes auth/payment/config surfaces so the engine has something meaningful to find.

```bash
export EPISTEMIC_TARGET_ROOT=$(pwd)/examples/synthetic_shop
export EPISTEMIC_AUTOMATION_PLAN=project_scan
python -m app.main
```

Then deepen one branch:

```bash
export EPISTEMIC_TARGET_ROOT=$(pwd)/examples/synthetic_shop
export EPISTEMIC_AUTOMATION_PLAN=focused_branch
export EPISTEMIC_FOCUS_BRANCH=x.a
python -m app.main
```

---

## Output you should expect

A successful run should surface things like:
- dependency hub claims
- sensitive surface claims
- validation gaps and critical untested modules
- configuration and CI signals
- branch maps and branch questions
- recommended actions grounded in real files
- a persistent memory file at `.epistemic/memory.json`

---

## Skill automation

The repo now supports plan-based skill automation.

### `project_scan`
Runs a structured sequence:
1. profile project
2. decompose objective
3. run research orchestrator

### `focused_branch`
Runs focused research using the selected branch from memory.

### `verify_project`
Runs a quick verification loop:
1. profile project
2. execute detected test commands

This moves the system from “a collection of skills” toward “an automation backbone.”

---

## MCP Server Integration

Apex Orchestrator can run as an **MCP server** via stdio transport, exposing its tools to any MCP-compatible client (Claude Desktop, VS Code, Cursor, etc.).

### Available MCP Tools

| Tool | Purpose |
|---|---|
| `apex_project_profile` | Scan project and return structural profile |
| `apex_generate_patch` | Generate semantic patches (docstring, type, guard, rename, extract) |
| `apex_apply_patch` | Apply generated patches safely with `expected_old_content` checks |
| `apex_run_tests` | Run detected test commands and report results |

### Running the MCP server

```bash
python -m app.mcp.server
```

Or configure in your MCP client:

```json
{
  "mcpServers": {
    "apex": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/apex-orchestrator"
      }
    }
  }
}
```

**Zero external dependencies:** The MCP server uses stdlib only.

---

## Current architecture snapshot

```text
app/
├── automation/      # skill registry, plans, runner, adapters
├── engine/          # budget, novelty, termination, execution loop
├── execution/       # semantic patch generator, retry, telemetry, PR summaries
├── llm/             # modular LLM router (none / openai / local)
├── mcp/             # MCP server and tool adapters (stdio, JSON-RPC 2.0)
├── memory/          # graph store and persistent memory
├── models/          # nodes, questions, reports, enums
├── policies/        # constitution and scoring
├── runtime/         # workspace, git, command foundation
├── skills/          # reasoning, execution, safety
├── tools/           # repo scanner, project profiler, dependency signals
└── utils/           # support utilities

config/
└── *.yaml

tests/
└── test_*.py

examples/
└── synthetic_shop/

docs/
└── branding.md
```

---

## Roadmap

### Completed
- ✅ stabilize automation, memory, spam guard, and branch focus
- ✅ semantic patch generation (AST-based, 11 transforms, no LLM required)
- ✅ advanced AST transforms: rename variable, extract method, inline variable, organize imports, move class, extract class
- ✅ retry repair loop with controlled retry budget
- ✅ git diff / commit / PR summary closing loop
- ✅ token telemetry with budget enforcement
- ✅ compressed operator mode for token efficiency
- ✅ modular LLM router (default: none, optional: openai/local)
- ✅ **multi-model routing** with cost-aware provider selection and budget enforcement
- ✅ MCP server integration (stdio transport, stdlib only)
- ✅ **MCP HTTP/SSE transport** for remote server usage
- ✅ enhanced safety governor with config-driven policies
- ✅ **self-directed autonomous workflow** (`self_directed_loop` plan)
- ✅ **multi-agent swarm coordination** (parallel branch processing)
- ✅ **GUI dashboard** for real-time monitoring (http://localhost:8686)
- ✅ **VS Code extension skeleton**
- ✅ **community docs & usage examples**
- ✅ **cross-run persistent memory** (claim tracking: open → still_open → resolved)
- ✅ **function-level fractal analysis** (cross-file call graph + risk scoring)
- ✅ **self-correction loop** (agent kendi claim'ini sorgular, low confidence'da otomatik derinleşir)
- ✅ **smart plan selection** (tek komut `apex scan`, agent kendi karar verir)
- ✅ **real-world validation suite** (bilinen hataları otomatik tespit — eval, os.system, pickle, bare except)
- ✅ **recursive reflection engine** (4 katmanlı self-scrutiny: evidence, boundary, counter-example, meta)
- ✅ **hypothesis-to-test mapping** (claim'leri pytest assertion'larına dönüştürme)
- ✅ **abductive reasoning** (gözlemlenen pattern'lerden kök neden çıkarımı — SRP violation, god module, vb.)
- ✅ **confidence calibration** (istatistiksel evidence diversity + conflict penalty ile güvenilirlik ayarı)
- ✅ **counterfactual generator** ("Eğer... olmasaydı" senaryoları — what if invalid input, what if server down)

### Next
- distributed swarm across multiple machines
- advanced refactoring transforms (extract interface, introduce parameter object)
- plugin ecosystem for third-party tool integrations

---

## Project status

**Current state:** strong internal alpha → beta transition

Today it is strongest as:
- repo intelligence engine with fractal reasoning
- memory-aware planning and branch-focused research agent
- **supervised autonomous coding agent** (semantic patch + retry + git/PR)
- token-budget-aware execution system
- optional LLM integration without mandatory external dependencies

It can now run end-to-end: research → plan → patch → verify → retry → commit → PR summary.

---

## Why star or follow this repo

If you care about:
- agent engineering
- memory-aware repo intelligence
- recursive reasoning systems
- branch-directed project analysis
- building toward safe autonomous coding agents

this repo is building exactly in that direction.

---

## Example branch map output

When Apex Orchestrator scans a project, it builds a branch map that looks like this:

```text
Branch Map
----------
x.a     dependency hub risk → app/services/order_service.py
x.a.a   why this hub matters → 4 downstream consumers, no integration tests
x.a.b   what evidence could contradict it → all consumers mocked in unit tests
x.b     sensitive surface claim → app/auth/token_service.py
x.b.a   auth/payment expansion → JWT validation lacks expiry check
x.c     validation gap → app/payments/gateway.py untested
x.c.a   missing guard clause → no amount > 0 validation before charge
```

You can focus any branch for deeper exploration:

```bash
export EPISTEMIC_FOCUS_BRANCH=x.a.b
export EPISTEMIC_AUTOMATION_PLAN=focused_branch
python -m app.main
```

## Example autonomous patch flow

```bash
# 1. Research
export EPISTEMIC_AUTOMATION_PLAN=semantic_patch_loop
export EPISTEMIC_TARGET_ROOT=./examples/synthetic_shop
python -m app.main

# 2. Review generated patch in .apex/patch-drafts/
# 3. Apply, verify, commit, and open PR summary
export EPISTEMIC_AUTOMATION_PLAN=full_autonomous_loop
python -m app.main
```

Output includes:
- `changed_files`: which files were modified
- `git_diff`: diff stat
- `pr_summary`: Markdown PR body ready for GitHub
- `telemetry`: token cost report

---

## Contributing

We love contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions, and the review process.

Quick start for contributors:

```bash
pip install -e .[dev]
pytest
```

---

## License

Licensed under **Apache-2.0**.
