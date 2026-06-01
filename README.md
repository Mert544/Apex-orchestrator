<div align="center">

# 🧠 Apex Orchestrator

### **Your codebase doesn't just need scanning — it needs reasoning.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-715%2B%20passing-brightgreen)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-black)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)
[![Helm](https://img.shields.io/badge/helm-chart-green)](helm/apex-orchestrator)
[![MCP](https://img.shields.io/badge/MCP-stdio%20%26%20HTTP-blueviolet)]()

**Apex Orchestrator** is a branch-aware, memory-aware, supervised engineering agent that evolves toward guarded autonomous coding. It doesn't just read your codebase — it *reasons* about it, remembers what it found, and helps you act on it.

[🚀 Quick Start](#quick-start) · [🎯 Why Apex](#why-apex) · [🔧 Features](#core-capabilities) · [🛡️ Safety](#safety-first) · [📊 Architecture](#architecture) · [🗺️ Roadmap](#roadmap)

</div>

---

## 🎯 Why Apex?

Most code intelligence tools stop at the surface. They give you:
- 📁 A file tree
- ⚠️ A lint-style issue list
- 📝 A one-shot summary
- 🤷 A vague “looks fine” answer

**Apex Orchestrator goes deeper.**

It treats your codebase as a living reasoning surface:
- **Extracts** structural claims about your architecture
- **Challenges** those claims with counter-evidence
- **Branches** recursively into the most valuable paths
- **Remembers** findings across multiple runs
- **Cuts** low-value noise automatically
- **Focuses** only where the next insight is worth the cost

This is not just repo analysis. This is **fractal project reasoning**.

---

## 🧩 What Makes It Different?

### 1. 🔀 It Thinks in Branches, Not Blobs
Instead of one flat summary, Apex builds a **branch map** of your project's risk and opportunity landscape:

```text
x.a     dependency hub risk
x.a.a   why this hub matters
x.a.b   what evidence could contradict it
x.b     sensitive surface claim
x.b.a   auth/payment expansion
```

You can focus any branch for deeper exploration.

### 2. 🧠 It Remembers Without Going Blind
Apex uses **degrade-not-block memory**:
- Same-run duplicates are stopped
- Prior-run repeats are degraded, not killed
- Important branches can reappear with adjusted novelty

### 3. ✂️ It Cuts Recursive Noise
Built-in spam guard filters repetitive meta-claims, generic questions, and low-value echoes.

### 4. 🎛️ You Steer the Depth
After a full scan, focus any branch (`x.a`, `x.a.b`, `x.k.b`) and deepen only that subtree.

---

## 🔧 Core Capabilities

| Capability | What It Does |
|---|---|
| 🏗️ **Fractal Analysis** | Recursive claim extraction with 5-Whys depth, counter-evidence, and meta-analysis |
| 🩹 **Semantic Patches** | AST-based deterministic transforms: docstrings, type annotations, guard clauses, rename, extract method, test stubs |
| 🔁 **Retry & Repair Loop** | Failed patches are diagnosed, repaired, and retried within budget |
| 🌿 **Git Integration** | Diff, branch, commit, tag, stash, push — full closing loop |
| 🧠 **Cross-Run Memory** | Persistent claim tracking: `open` → `still_open` → `resolved` |
| 🤖 **Multi-Agent Swarm** | Parallel agent execution with timeout, circuit breaker, and graceful shutdown |
| 🛡️ **Safety Gates** | Scope limits, secret detection, sensitive path blocking, test verification |
| 📡 **MCP Server** | Stdio + HTTP/SSE transport for IDE integration (VS Code, Cursor, Claude Desktop) |
| 📊 **Prometheus Metrics** | Counter, gauge, histogram export for observability |
| 🐳 **Docker + Helm** | Production-ready container and Kubernetes deployment |

---

## 🚀 Quick Start

```bash
# 1. Install
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]

# 2. Verify
pytest

# 3. Scan your project
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=project_scan
python -m app.main
```

**Or run with CLI:**
```bash
apex scan --target=/path/to/project --plan=project_scan --mode=report
```

**Or run as MCP server:**
```bash
python -m app.mcp.server
```

---

## 💡 Idea Permutation Engine

Apex doesn't only *analyse* code — it can **propose how to develop it**. The Idea
Permutation Engine splits a project into autonomous development branches derived
from its real structure, then permutes each branch into operator-sequence
sub-ideas — the "abc" of every "a". Fully deterministic (no LLM required).

```bash
# Generate a tree of development directions, grounded in the codebase
apex ideate --target=. --depth=2 --breadth=4

# Turn the highest-value ideas into a supervised action plan (never applied)
apex ideate --target=. --actions --top=10
```

```
## x.a — Evolve the central module app/routes/api.py   (value 0.82)
   - x.a.a [extend]  Extend: app/routes/api.py
   - x.a.b [harden]  Harden: app/routes/api.py        ⚠ caveat: ...
   - x.a.c [test]    Test: app/routes/api.py
       - x.a.c.b  Test → Harden: app/routes/api.py
```

Each idea is traceable to a concrete project fact, scored by relevance/novelty/
feasibility, and stress-tested with counterfactual caveats. The action bridge
maps executable ideas (tests, docstrings, hardening) to known transforms while
surfacing higher-level directions as design tasks — and it **proposes, it never
applies**. See `docs/idea-permutation-engine.md`.

---

## 🤖 Autonomous Maintenance (`apex maintain`)

One command runs the whole guarded loop: **scan → generate fixes → apply →
verify with tests → roll back failures → commit → report.** Every change is
gated by `ModePolicy` + `SafetyGates`, individually verified against your test
suite, and automatically rolled back if it breaks anything.

```bash
# Plan only — never touches the tree (default of report mode)
apex maintain --target=. --mode=report

# Apply verified fixes, but don't commit (supervised)
apex maintain --target=. --mode=supervised

# Full autonomy: apply, verify, and commit each fix individually
apex maintain --target=. --mode=autonomous --commit --out=MAINT.md
```

Real deterministic fixes it can apply: `eval()` → `ast.literal_eval()`,
`os.system()` → `subprocess.run()`, bare `except:` → `except Exception:`,
missing docstrings, import organization, and test stubs. A fix that fails the
test suite is reverted automatically, so a maintenance run can never leave the
project broken. The run ends with a Markdown report of what was applied, rolled
back, or blocked — with per-step commit hashes in autonomous mode.

---

## 🛡️ Safety First

Apex operates in three modes:

| Mode | What It Does | Best For |
|---|---|---|
| 📋 **Report** | Scans and reports only. Zero file changes. | Audits, CI pipelines |
| 👁️ **Supervised** | Proposes patches. Asks before applying. | Daily development |
| 🤖 **Autonomous** | Applies and commits patches automatically. | Trusted environments |

**Safety Gates** enforce:
- Max changed files limit
- Blocked paths (`.env`, `secrets/**`, `*.pem`)
- Secret detection (API keys, tokens, passwords)
- Mandatory test verification after patches
- Rollback-ready journal for every change

---

## 📊 Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    APEX ORCHESTRATOR                         │
├─────────────────────────────────────────────────────────────┤
│  Brain (Cortex)     │  Hands (Executor)   │  Limbs          │
│  ───────────────    │  ───────────────    │  ─────          │
│  Fractal 5-Whys     │  Action Executor    │  Debug Agent    │
│  Meta Analysis      │  Semantic Patch     │  Coverage Agent │
│  Decision Engine    │  Safety Gates       │  Refactor Agent │
│                     │  Fallback Handler   │  CI Agent       │
│                     │                     │  Doc Agent      │
├─────────────────────────────────────────────────────────────┤
│  Memory & Feedback  │  Policy             │  Reports        │
│  ─────────────      │  ──────             │  ───────        │
│  Cross-Run Tracker  │  Mode Policy        │  Markdown/HTML  │
│  Findings Store     │  Safety Gates       │  SARIF          │
│  Agent Learning     │  Learning Policy    │  Mermaid        │
├─────────────────────────────────────────────────────────────┤
│  Swarm & Scale      │  Deployment         │  Integrations   │
│  ─────────────      │  ─────────          │  ───────────    │
│  Distributed Swarm  │  Docker             │  MCP Server     │
│  Circuit Breaker    │  Helm Chart         │  VS Code Ext    │
│  Graceful Shutdown  │  Prometheus Metrics │  GitHub Actions │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎬 Use Cases

### 🔒 Security Audit
Detect `eval()`, `os.system()`, `pickle.loads()`, bare except blocks, and missing input validation. Get a fractal root-cause analysis for every finding.

```bash
apex scan --target=. --goal="security audit" --mode=report
```

### 🩹 Autonomous Refactoring
Add missing docstrings, type annotations, and guard clauses. Apex generates AST-based patches, verifies them with tests, and commits.

```bash
apex run --goal="fix docstrings" --mode=supervised
```

### 🧪 Test Coverage Gap Analysis
Identify untested modules, generate test stubs, and run targeted tests only for changed files.

```bash
apex run --goal="improve test coverage" --mode=autonomous
```

### 🌿 Git Workflow Automation
Diff → patch → verify → commit → PR summary — all in one command.

```bash
apex run --plan=full_autonomous_loop --target=.
```

---

## 🗺️ Roadmap

### ✅ Completed
- **Autonomous maintenance** (`apex maintain`) — scan → fix → verify → auto-rollback → commit → report
- **Idea Permutation Engine** (`apex ideate`) — generative development-branch tree + supervised action bridge, with synthesis (security-test-suite) and module-pair / import-cycle ideas
- **Verified apply** — real security fixes (eval/os.system/bare-except), test-gated with automatic rollback
- **`apex debug`** (trace + traceback analysis) and **`apex dashboard`** (self-contained HTML)
- Objective-relevance focus + deterministic deep reasoning (counterfactual stress-test + confidence calibration)
- Fractal reasoning engine (5-Whys + counter-evidence + meta-analysis)
- AST-based semantic patch generation (11 transforms)
- Retry repair loop with controlled budget
- Git diff / commit / PR summary closing loop
- Token telemetry with budget enforcement
- Optional free LLM providers (GitHub Models, Groq, Gemini, Ollama; off by default)
- MCP server (stdio + HTTP/SSE)
- Multi-agent swarm — every scanner runs on a scan; plugin hooks fire in the main path
- Cross-run persistent memory (JSON + Shelve backends)
- Central Memory Bridge (unified CrossRun + Findings + Learning)
- Self-audit agent (AST risk, docstring, complexity analysis)
- Prometheus metrics exporter
- Plugin ecosystem with hook points
- CI: tests + coverage + ruff lint gate
- **780+ tests** passing

### 🚧 Next
- Idea engine P-D: MCP `apex_ideate` tool, optional LLM polish, plugin-contributed operators
- Raise unit-test coverage of `engine/`, `memory/`, `tools/`
- Plugin marketplace / registry server
- IDE Language Server Protocol (LSP) integration

### 🧪 Experimental (not production-ready)
- Kubernetes operator (`app/k8s/operator.py`) — in-memory reconciliation; does not yet use the K8s client
- Helm chart — skeletal (no RBAC/ingress)
- VS Code extension — a CLI wrapper (spawns `app.main`), not a full LSP/diagnostics integration

---

## 📈 Project Status

**Current state:** Production-ready beta

Apex is strongest as:
- 🧠 **Repo intelligence engine** with fractal reasoning
- 🗂️ **Memory-aware planning** and branch-focused research agent
- 🩹 **Supervised autonomous coding agent** (semantic patch + retry + git/PR)
- 💰 **Token-budget-aware** execution system
- 🔌 **Zero-mandatory-dependencies** core (LLM is opt-in)

It can now run end-to-end: **Research → Plan → Patch → Verify → Retry → Commit → PR Summary → Telemetry**

---

## 🤝 Contributing

We love contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions, and review process.

```bash
pip install -e .[dev]
pytest
```

---

## 📄 License

Licensed under **Apache-2.0**.

---

<div align="center">

**Built with 💜 by engineers who believe codebases deserve deep thought.**

[⭐ Star us on GitHub](https://github.com/your-org/apex-orchestrator) · [🐛 Report an issue](https://github.com/your-org/apex-orchestrator/issues) · [💬 Discussions](https://github.com/your-org/apex-orchestrator/discussions)

</div>
