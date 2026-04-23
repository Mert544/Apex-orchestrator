# Helper Agents Demo

Four focused helper agents that work standalone or as Apex plugins.

## Quick Start

```bash
# Security scan
python -m app.cli agents security --target=examples/microservices_shop

# Find missing docstrings
python -m app.cli agents docstring --target=examples/microservices_shop

# Auto-patch docstrings
python -m app.cli agents docstring --target=examples/microservices_shop --patch

# Find test coverage gaps
python -m app.cli agents test-stub --target=examples/microservices_shop

# Generate missing test stubs
python -m app.cli agents test-stub --target=examples/microservices_shop --generate

# Analyze dependencies
python -m app.cli agents dependency --target=examples/microservices_shop
```

## Agents

### SecurityAgent (`security_agent.py`)
AST-based security scanner detects:
- `eval()`, `exec()`, `compile()` — arbitrary code execution
- `os.system()`, `subprocess.call()` — shell injection
- `pickle.loads()`, `yaml.load()` — unsafe deserialization
- Hardcoded secrets (API keys, passwords, DB URLs)
- Bare `except:` clauses
- f-string SQL queries

Output: JSON report with severity, line numbers, and fix suggestions.

### DocstringAgent (`docstring_agent.py`)
Finds and fixes missing docstrings:
- Scans all functions and classes
- Reports gaps with file/line/name
- Optional `--patch` mode: auto-adds `"""name implementation."""` stubs
- Skips symbols that already have docstrings

### TestStubAgent (`test_stub_agent.py`)
Test coverage analyzer:
- Matches source functions to existing `test_` functions
- Calculates coverage ratio
- Generates `tests/test_<module>.py` stubs for missing tests
- Ignores private `_functions`
- Detects already-tested functions

### DependencyAgent (`dependency_agent.py`)
Import graph analyzer:
- Builds cross-file import graph
- Detects circular imports
- Finds orphaned modules (no imports, not imported)
- Ranks modules by centrality (connection count)

## Plugin Integration

Each agent exports a `register(proxy)` function for Apex plugin system:

```python
# In your plugin file
from examples.helper_agents.security_agent import SecurityAgent

__plugin_name__ = "my_security"

def register(proxy):
    agent = SecurityAgent(proxy.get("project_root", "."))
    proxy.add_hook("before_scan", lambda ctx: agent.scan())
```

## Tests

```bash
pytest tests/test_security_agent.py -v
pytest tests/test_docstring_agent.py -v
pytest tests/test_test_stub_agent.py -v
pytest tests/test_dependency_agent.py -v
```

All tests use `tmp_path` fixture with self-contained demo projects.
