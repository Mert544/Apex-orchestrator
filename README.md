# Epistemic Orchestrator

A minimal but working V1 starter codebase for a constitution-driven recursive research engine that:

- decomposes findings into claims
- generates four mandatory question classes for every claim
- searches for supporting and opposing evidence
- enforces a constitution in code, not only in prompts
- stops low-value, unsafe, or repetitive branches
- produces a final report with a confidence map

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m app.main
pytest
```

## What is included

- import-safe Python package structure
- configurable orchestrator loop
- rule-based V1 skills
- graph memory with simple deduplication
- stop reasons and branch controls
- tests for the core engine

## Suggested next steps

1. Replace the mock validator with real web / data retrieval.
2. Replace the mock decomposer with an LLM-backed decomposer.
3. Upgrade dedup from exact match to embedding similarity.
4. Add persistent state and audit logging.
