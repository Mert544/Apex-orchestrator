---
name: apex
description: Use and extend the Apex Orchestrator in this repo — run ideate/maintain/dashboard/debug, and add new deterministic transforms, idea operators, or seeding signals following the project's established patterns. Trigger when working on app/engine/idea_permutation.py, app/engine/idea_action_bridge.py, app/execution/semantic/transforms/, or when the user asks to run Apex on a project or add a new fix/idea capability.
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Apex Orchestrator — usage & extension guide

Apex is a deterministic (no-LLM-by-default) engineering agent: it **scans** a codebase,
**generates** grounded development ideas, and **applies** real, test-verified fixes under
mode/safety gating. Think of it as brain (reasoning), eyes (scanners), hands (executor).

## Running Apex (CLI)

- `python -m app.cli ideate --target=. --depth=2 --breadth=4 --actions` — idea
  permutation tree + supervised action plan (`--kind synthesis|pair|permutation` to filter,
  `--draft` to preview real patches, `--mermaid`, `--out FILE`).
- `python -m app.cli maintain --target=. --dry-run` — preview every fix as a unified diff.
  Modes: `--mode report|supervised|autonomous` (+ `--commit`, `--verify` on by default,
  `--no-verify`, `--max-apply N`, `--out MAINT.md`).
- `python -m app.cli dashboard --target=. --out=.apex/dashboard.html` — self-contained HTML.
- `python -m app.cli debug trace|analyze` — debug subsystem.

Safety model: `report` can't patch; `supervised` patches (test-verified, auto-rollback on
failure) but never commits; `autonomous` also commits each fix individually. SafetyGates
block sensitive paths / secrets / over-scope.

## Testing discipline (keep cost low)

Run only the relevant tests while iterating, then ruff:
`python -m pytest tests/test_idea_action_bridge.py tests/test_idea_permutation_engine.py -q && ruff check app/`
Run the full suite (`python -m pytest -q`) only before a commit that spans modules.

## Extending Apex — established patterns

### Add a deterministic security/quality fix
1. Add a transform fn in `app/execution/semantic/transforms/security.py` (or a new module
   under `transforms/`) returning a `SemanticPatchResult`. For risks with no safe
   auto-rewrite (pickle, SQL), **flag with a comment** instead of rewriting; for safe ones
   (eval→literal_eval, bare-except) rewrite via AST + line replace.
2. Route it: add a keyword branch in `app/execution/edit_strategy.py` (return a
   `fix_<x>` strategy) and add `"fix_<x>"` to the security tuple in
   `app/execution/semantic_patch_generator.py`.
3. Detection: extend `IdeaActionBridge._detect_security_issue` in
   `app/engine/idea_action_bridge.py` so `harden_security` picks it.
4. Test in `tests/test_idea_action_bridge.py` (apply path) + a transform unit test.

### Add an idea operator (widen the permutation alphabet)
Append an `Operator(name, "...{x}...", feasibility)` to `DEVELOPMENT_OPERATORS` in
`app/engine/idea_permutation.py`, or contribute one at runtime via a plugin's
`proxy.add_operator(...)`. Add a `_OPERATOR_HINTS` entry so caveats stay on-topic.

### Add a seeding signal (new root-idea source)
Compute a field on `ProjectProfile` (`app/tools/project_profile.py`), then emit it in
`IdeaSeeder.seed` via `self._append_root(...)` with a traceable `fact_label`. Add the
label to `_FACT_HINTS` (and `_SECURITY_LABELS` if reliability-relevant).

## Invariants to preserve
- Determinism: same input → same output (no time/random in scoring).
- `node.value` stays in [0,1]; roots keep `novelty == 1.0`.
- Synthesis/pair ideas use `kind != "permutation"` and an `x.s*`/`x.p*` branch path.
- Everything stays offline by default; LLM is opt-in.
