# Contributing to Apex Orchestrator

Thank you for your interest in making Apex Orchestrator better! This document will help you get started.

## Development Setup

```bash
git clone https://github.com/your-org/apex-orchestrator.git
cd apex-orchestrator
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

## Running Tests

We maintain **100% test success** as a baseline. All PRs must pass the full suite.

```bash
# Full suite
pytest

# Specific module
pytest tests/test_semantic_patch_generator.py -v
pytest tests/test_mcp_server.py -v
```

## Project Conventions

- **Imports:** `from __future__ import annotations` at the top of every file.
- **Type hints:** Required for all public APIs.
- **Dataclasses:** Prefer over raw dicts for structured data.
- **Tests:** Use `tmp_path` fixture and self-contained demo projects.
- **Paths:** Use `Path.as_posix()` in assertions; never hardcode `/`.
- **Error handling:** Graceful degradation — the orchestrator must never crash.
- **No mandatory external deps:** If you add an LLM or cloud integration, make it optional with a `none` default.

## Adding a New Skill

1. **Implement** the skill function in `app/automation/skills.py`.
2. **Register** it in `build_default_registry()` inside the same file.
3. **Add a plan step** in `app/automation/plans.py` if it fits an automation plan.
4. **Write tests** in `tests/test_<feature>.py`. Aim for edge cases and failure modes.
5. **Update docs:** `AGENTS.md`, `README.md`, and this file if needed.

## Adding a New AST Transform

The `SemanticPatchGenerator` is the heart of safe autonomous editing.

1. Add your transform method (e.g., `_transform_add_docstring`).
2. Wire it in `generate()` and `_select_transform()`.
3. Always produce `expected_old_content` for safety.
4. Add a test in `tests/test_semantic_patch_generator.py`.
5. Document it in the README transform table.

## Code Review Process

1. Open a PR with a clear description of the problem and solution.
2. Ensure CI passes (pytest + lint).
3. Request review from a maintainer.
4. Address feedback and keep commits atomic.

## Questions?

- Read `AGENTS.md` for architecture decisions.
- Open a Discussion for design questions.
- Open an Issue for bugs or feature requests.

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 License.
