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
- Fractal reasoning engine (5-Whys + counter-evidence + meta-analysis)
- AST-based semantic patch generation (11 transforms)
- Retry repair loop with controlled budget
- Git diff / commit / PR summary closing loop
- Token telemetry with budget enforcement
- Multi-model LLM routing with cost-aware selection
- MCP server (stdio + HTTP/SSE)
- Multi-agent swarm with circuit breaker & graceful shutdown
- Cross-run persistent memory (JSON + Shelve backends)
- Central Memory Bridge (unified CrossRun + Findings + Learning)
- Self-audit agent (AST risk, docstring, complexity analysis)
- VS Code extension (TypeScript)
- Docker + Helm deployment
- Prometheus metrics exporter
- Plugin ecosystem with hook points
- CI/CD security audit pipeline
- **715+ tests** with comprehensive coverage

### 🚧 Next
- Plugin marketplace / registry server
- IDE Language Server Protocol (LSP) integration
- Enhanced self-healing for patch failures
- Real-time collaboration protocol across multiple machines

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
