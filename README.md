# Epistemic Orchestrator

A constitutional **fractal project intelligence engine** for codebases.

Instead of stopping at a flat answer, Epistemic Orchestrator scans a project, derives structural claims, classifies and prioritizes them, generates recursive follow-up questions, searches for supporting and opposing evidence, and expands only the highest-value branches.

## Why this project exists

Most project analyzers stop at one of these layers:

- static file listing
- symbol extraction
- lint-style findings
- one-shot LLM summaries

Epistemic Orchestrator is designed to go further:

- **structure-first**: understand the repository as a graph, not a folder dump
- **constitution-driven**: every expansion is constrained by explicit rules
- **fractal**: every meaningful claim can generate deeper sub-questions
- **risk-aware**: contradictory evidence, security, quality, novelty, and budget gates matter
- **action-oriented**: the end state is not just insight, but useful engineering direction

## What “fractal” means here

Fractal does **not** just mean recursively scanning files.
It means the engine follows a mathematical and constitutional pattern:

1. derive a claim
2. classify and prioritize it
3. generate four mandatory question classes
4. search for supporting and opposing evidence
5. evaluate risk, quality, novelty, and security
6. expand only if the branch is worth expanding
7. surface not just conclusions, but the confidence structure behind them

## Core constitution

1. Do not stop at a single answer; decompose into claims.
2. For every claim, generate four mandatory question classes.
3. Search for counter-evidence against current conclusions.
4. Mark under-supported claims as low confidence.
5. Do not deepen a branch without security, quality, and verifiability checks.
6. Cut repetitive or low-value branches.
7. Tie expansion to budget and novelty thresholds.
8. Show the confidence structure, not only the final conclusion.

## Architecture overview

```mermaid
flowchart TD
    A[Target Project] --> B[Perception Layer]
    B --> B1[Repo Scanner]
    B --> B2[Project Profiler]
    B --> B3[Python Structure Analyzer]
    B --> B4[Dependency Signals]

    B1 --> C[Epistemic Layer]
    B2 --> C
    B3 --> C
    B4 --> C

    C --> C1[Claim Seeding]
    C --> C2[Claim Typing]
    C --> C3[Claim Priority]
    C --> C4[Evidence Mapping]

    C1 --> D[Fractal Reasoning Layer]
    C2 --> D
    C3 --> D
    C4 --> D

    D --> D1[Missing Info Questions]
    D --> D2[Contradiction Questions]
    D --> D3[Risk Questions]
    D --> D4[Deepening Questions]
    D --> D5[Security Gate]
    D --> D6[Quality Gate]
    D --> D7[Novelty/Budget Gate]

    D --> E[Output Layer]
    E --> E1[Main Findings]
    E --> E2[Confidence Map]
    E --> E3[Risks]
    E --> E4[Open Questions]
    E --> E5[Stopped Branches]
```

## Current capabilities

- project-aware claim seeding from repository structure
- heuristic claim typing and priority scoring
- local project evidence scanning
- lightweight Python import and symbol extraction
- dependency hub and symbol density signals
- untested module heuristics
- graph memory with simple deduplication
- recursive question generation with constitutional gates
- final synthesis with confidence map and prioritized findings
- test suite + GitHub Actions CI

## Repository layout

```text
app/
├── engine/          # budget, novelty, termination, execution loop
├── memory/          # graph store and dedup helpers
├── models/          # nodes, questions, reports, enums
├── policies/        # constitution and scoring
├── skills/          # decomposer, validator, claim analyzer, synthesizer
├── tools/           # repo scanner, project profiler, dependency signals
└── utils/           # support utilities

config/
└── *.yaml           # engine, routing, and policy config

tests/
└── test_*.py        # core verification suite

examples/
└── synthetic_shop/  # intentionally imperfect demo project
```

## How it works

### 1. Perception
The engine scans the target repository and extracts structural signals:

- file types
- top directories
- entrypoints
- tests
- CI/workflows
- config surfaces
- sensitive paths
- Python imports and symbols

### 2. Claim seeding
Those signals are transformed into initial claims such as:

- dependency hub claim
- symbol density claim
- testing gap claim
- automation claim
- sensitive surface claim
- configuration claim

### 3. Claim analysis
Each claim is enriched with:

- claim type
- claim priority
- claim signals
- evidence for / against
- assumptions
- risk score

### 4. Fractal expansion
For every viable claim, the engine generates four mandatory question classes:

- missing-information questions
- contradiction questions
- risk questions
- deepening questions

Then it decides whether to expand or stop the branch.

### 5. Synthesis
The final report contains:

- main findings
- claim types
- claim priorities
- confidence map
- strongest supporting evidence
- strongest opposing evidence
- assumptions
- unresolved questions
- stopped branches

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m app.main
pytest
```

To run against another project:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
python -m app.main
```

## Try the demo project

A synthetic project is included under `examples/synthetic_shop`.
It is intentionally small, centralized, partially tested, and contains sensitive/auth/payment surfaces so the orchestrator has something meaningful to find.

Run the engine against it like this:

```bash
export EPISTEMIC_TARGET_ROOT=$(pwd)/examples/synthetic_shop
python -m app.main
```

What you should expect to see in the report:

- dependency hub claims around `order_service.py`
- sensitive surface claims around auth/payment files
- validation gap or untested module claims
- configuration and automation-related signals

## Recommended usage modes

### Scan mode
Fast structural overview of a project.

Use it for:
- onboarding a new repo
- high-level architectural review
- quick technical risk discovery

### Audit mode
Deeper analysis of validation, security, configuration, and dependency pressure.

Use it for:
- release readiness checks
- technical debt review
- engineering health scans

### Expansion mode
Focused recursive analysis of one branch.

Use it for:
- auth module inspection
- payment flow review
- CI gap analysis
- entrypoint risk analysis

## Example analysis themes

- Which dependency hubs are central and under-tested?
- Which sensitive modules appear early in the expansion tree?
- Which entrypoints create architectural coupling risk?
- Which config surfaces likely hide environment assumptions?
- Which subsystems deserve the next engineering investment?

## Roadmap

### Near term
- real dependency graph edges
- stronger test linking
- evidence anchors with precise traceability
- richer contradiction generation

### Mid term
- action generator
- refactor/test suggestion engine
- patch candidate generation
- host adapters for Claude Code / opencode

### Later
- persistent memory
- branch audit history
- semantic retrieval
- graph-aware expansion strategies

## License

Licensed under **Apache-2.0**.

A detectable license file is included so GitHub can display the license clearly for the repository.
