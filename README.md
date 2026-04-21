<div align="center">

# Epistemic Orchestrator

### Constitutional fractal intelligence for codebases

**Scan deeper. Ask better questions. Focus the right branch.**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Architecture](https://img.shields.io/badge/architecture-fractal-purple)
![Memory](https://img.shields.io/badge/memory-degrade--not--block-green)
![Focus](https://img.shields.io/badge/focus-branch--aware-orange)
![License](https://img.shields.io/badge/license-Apache%202.0-black)

</div>

---

## Why this repo matters

Most code intelligence tools stop too early.

They give you one of these:
- a file tree
- a lint-style issue list
- a one-shot summary
- a vague “looks fine” answer

**Epistemic Orchestrator goes further.**

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

**Epistemic Orchestrator is an agent brain for codebases: it scans, questions, prioritizes, remembers, and deepens the most valuable path instead of stopping at a shallow answer.**

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
- skill automation plans such as `project_scan` and `focused_branch`

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

Focus a branch:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=focused_branch
export EPISTEMIC_FOCUS_BRANCH=x.a.b
python -m app.main
```

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

This moves the system from “a collection of skills” toward “an automation backbone.”

---

## Current architecture snapshot

```text
app/
├── automation/      # skill registry, plans, runner, adapters
├── engine/          # budget, novelty, termination, execution loop
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
```

---

## Roadmap

### Now
- stabilize automation, memory, spam guard, and branch focus
- strengthen e2e validation
- expand runtime foundation

### Next
- supervised patch loop
- test execution skills
- patch application and verification
- safety guardrails for controlled code changes

### Later
- repair loop
- draft PR automation
- richer execution skills
- full guarded autonomous coding workflows

---

## Project status

**Current state:** strong internal alpha / working core

Today it is strongest as:
- repo intelligence engine
- fractal analysis system
- branch-focused research agent
- memory-aware planning brain

It is **not yet** a full end-to-end autonomous coding agent.
That is the next stage of the roadmap.

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

## License

Licensed under **Apache-2.0**.
