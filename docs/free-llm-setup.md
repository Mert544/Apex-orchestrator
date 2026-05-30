# Free / Low-Cost LLM Setup

Apex Orchestrator works fully without any LLM (the default `provider: none`
makes zero external calls). When you *do* want an LLM, you don't need a paid
account — several providers offer free access, and Apex talks to all of them
through one OpenAI-compatible client built on the Python standard library (no
extra dependencies, no SDK to install).

Pick a provider, set one environment variable, and set `llm.provider` in
`config/default.yaml`.

| Provider     | `llm.provider` | Cost            | Env var              | Needs a key? |
| ------------ | -------------- | --------------- | -------------------- | ------------ |
| GitHub Models| `github`       | Free for devs   | `GITHUB_TOKEN`       | Yes          |
| Groq         | `groq`         | Free tier       | `GROQ_API_KEY`       | Yes          |
| Google Gemini| `gemini`       | Free tier       | `GEMINI_API_KEY`     | Yes          |
| OpenRouter   | `openrouter`   | Has free models | `OPENROUTER_API_KEY` | Yes          |
| Ollama (local)| `ollama`      | Free / offline  | —                    | No           |

## GitHub Models (recommended for students)

GitHub Models is free for developers and pairs well with the
[GitHub Student Developer Pack](https://education.github.com/pack).

1. **Create a token** at <https://github.com/settings/personal-access-tokens>.
   Use a fine-grained token and grant the **`Models` → read-only** permission
   (account permission `models:read`). No repository access is required.
2. **Export it:**
   ```bash
   export GITHUB_TOKEN=ghp_your_token_here
   ```
3. **Enable it** in `config/default.yaml`:
   ```yaml
   llm:
     provider: github          # uses model openai/gpt-4o-mini by default
     api_key_env: GITHUB_TOKEN
   ```
4. (Optional) Pick a different model:
   ```yaml
   llm:
     provider: github
     model: openai/gpt-4o       # or microsoft/Phi-3.5-mini-instruct, etc.
   ```

That's it — Apex will route reasoning calls to GitHub Models. If the token is
missing or a request fails, Apex degrades gracefully and falls back to its
deterministic logic, so a hiccup never blocks a run.

## Ollama (fully offline, no key)

If you'd rather run a model locally with no account at all:

```bash
# install from https://ollama.com, then:
ollama pull llama3.2
ollama serve            # serves an OpenAI-compatible API on :11434
```

```yaml
llm:
  provider: ollama
  model: llama3.2
```

## Keeping your key safe

- Prefer `api_key_env` (an env var name) over putting `api_key` directly in the
  YAML file, so secrets never get committed.
- `config/default.yaml` ships with `api_key: ""` on purpose — leave it empty.
