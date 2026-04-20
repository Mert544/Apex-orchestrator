# Epistemic Orchestrator

A minimal but working V1 starter codebase for a **constitution-driven fractal research engine** that operates primarily on a **local project repository**.

This system is designed to:

- scan project files and derive implementation claims
- seed initial structural claims from a project profile
- generate four mandatory question classes for every claim
- search for supporting and opposing evidence inside the project itself
- enforce a constitution in code, not only in prompts
- stop low-value, unsafe, or repetitive branches
- produce a final report with a confidence map

## What “fractal” means here

Fractal does **not** just mean recursively scanning files.
It means the engine follows the mathematical and constitutional structure defined earlier:

- claim -> subclaim decomposition
- mandatory question generation across four classes
- counter-evidence search
- risk-aware expansion
- novelty/budget-gated branching
- final output that shows confidence structure, not only conclusions

So the repo scanner is only an **evidence source**.
The real system is the orchestrator that keeps applying the constitution while expanding or stopping branches.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m app.main
pytest
```

To point the engine at another project:

```bash
export EPISTEMIC_TARGET_ROOT=/absolute/path/to/your/project
python -m app.main
```

## What is included

- import-safe Python package structure
- configurable orchestrator loop
- project-aware claim seeding from repository structure
- local project evidence scanning
- graph memory with simple deduplication
- stop reasons and branch controls
- tests for the core engine
- GitHub Actions CI workflow

## Suggested next steps

1. Replace heuristic claim seeding with host-model-assisted decomposition.
2. Upgrade repo search from keyword matching to semantic retrieval.
3. Add claim typing, dependency tracing, and branch audit logs.
4. Add host-environment adapters for Claude Code / opencode.
