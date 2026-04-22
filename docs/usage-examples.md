# Usage Examples

This page shows common ways to use Apex Orchestrator in real workflows.

## 1. Quick Project Health Check

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=verify_project
python -m app.main
```

**What happens:**
- Profiles the project structure
- Runs detected test commands
- Reports coverage gaps and untested modules

## 2. Full Repository Scan

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=project_scan
python -m app.main
```

**What happens:**
- Builds a branch map like `x.a`, `x.a.b`
- Identifies dependency hubs, sensitive surfaces, untested modules
- Generates recommended actions grounded in real files
- Persists memory to `.epistemic/memory.json`

## 3. Focused Branch Deepening

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=focused_branch
export EPISTEMIC_FOCUS_BRANCH=x.a.b
python -m app.main
```

**What happens:**
- Loads prior memory
- Deepens only the `x.a.b` subtree
- Produces focused claims and questions

## 4. Semantic Patch Loop

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=semantic_patch_loop
python -m app.main
```

**What happens:**
- Researches the codebase
- Generates an AST-based semantic patch (docstring, type, guard, rename, extract, inline, import cleanup)
- Applies the patch with `expected_old_content` safety
- Runs verification (tests + patch scope + sensitive edit checks)
- Retries if needed (up to configured max)

## 5. Git Commit + PR Summary

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=git_pr_loop
python -m app.main
```

**What happens:**
- Stages changed files
- Commits with descriptive message
- Generates a Markdown PR body including diff stat and verification status

## 6. Full Autonomous Loop

```bash
export EPISTEMIC_TARGET_ROOT=/path/to/your/project
export EPISTEMIC_AUTOMATION_PLAN=full_autonomous_loop
python -m app.main
```

**What happens:**
- End-to-end: research → plan → patch → verify → retry → commit → PR summary → telemetry
- Produces `.apex/telemetry/run-*.json` with token costs

## 7. MCP Server (stdio)

```bash
python -m app.mcp.server
```

Use with Claude Desktop, VS Code, Cursor, or any MCP client:

```json
{
  "mcpServers": {
    "apex": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "env": { "PYTHONPATH": "/path/to/apex-orchestrator" }
    }
  }
}
```

## 8. MCP Server (HTTP + SSE)

```bash
python -c "from app.mcp.tools import build_apex_tools; from app.mcp.http_server import MCPHTTPServer; MCPHTTPServer(build_apex_tools(), port=8787).run()"
```

Then POST JSON-RPC to `http://127.0.0.1:8787` or subscribe to SSE at `http://127.0.0.1:8787/sse`.

## 9. Multi-Model Cost-Aware Routing

Configure `config/default.yaml`:

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

Apex will:
- Try the cheapest model first
- Fallback to next if one fails
- Track session cost and enforce budget

## 10. Token Budget Enforcement

```yaml
token_budget_limit: 50000  # 0 = unlimited
```

When exceeded, Apex stops expansion gracefully and reports usage in telemetry.

## 11. Safety Governor

Sensitive edits are automatically blocked from auto-retry:
- More than 5 files changed (configurable)
- Restricted paths touched (`.github/workflows`, `config/`, `auth/`)
- More than 100 lines changed per file

Require human review before merge.

## 12. VS Code Extension

1. Install the `.vsix` from `vscode-extension/`
2. Open Command Palette → `Apex: Project Scan`
3. View results in Output → Apex Orchestrator

## Output Files

| File | Purpose |
|---|---|
| `.epistemic/memory.json` | Persistent agent memory across runs |
| `.apex/patch-drafts/*.md` | Draft patches when no safe semantic transform applies |
| `.apex/telemetry/run-*.json` | Token usage and cost reports |
| `.apex/presence.md` | Agent presence log (thoughts, actions, stats) |

## Need Help?

- See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup
- See [AGENTS.md](../AGENTS.md) for architecture decisions and conventions
- Open an issue for bugs or feature requests
