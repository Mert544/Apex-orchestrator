# Developing Apex — the current model (source of truth)

> This is the **authoritative** guide to how Apex is built *today*. The older
> `AGENTS.md` documents earlier directions (security scanner, semantic-patch
> pipeline, swarms) that still exist but are **not** where new work goes. When
> the two disagree, **this file wins.**

## What Apex is (the one invariant)

Apex is a **deterministic, stdlib-only, LLM-free-by-default project-DEVELOPMENT
assistant**. Positioning:

> *LLMs write code fast. Apex proves which is solid — and tells what to do next.*

It does not just **detect** problems — it **develops** the codebase toward goals
with verified, reversible moves, and it can improve **itself**. Security is one
grounding signal, never the headline. The brand signature is **barzeuss**.

Three rules that are never broken:

1. **Deterministic & stdlib-only.** Same input → same output. No LLM in the core,
   no network, no third-party runtime deps. Every transform is AST-based.
2. **Suite-gated & reversible.** A change "lands" only if the project's tests
   stay green; otherwise it is rolled back automatically. We never ship red.
3. **`examples/` is sacred.** The projects under `examples/` are *intentionally*
   vulnerable/messy fixtures. **Never "fix" them** — they are test inputs.

## The develop core

### Objective-Compiler — `app/engine/objective_compiler.py`
Goal-directed greedy composition: toward an **objective** (a measurable fitness =
count of fixable items remaining), it repeatedly applies the best **move** (an
AST transform), each one suite-verified with auto-rollback, until fitness hits a
fixpoint. Scanning is **per-pass** (scan once, apply all landing moves, re-scan)
so it stays fast on large repos.

- A move is a `Move(operator, target, description, build_plan)` whose
  `build_plan()` returns a `RenamePlan` (see below).
- `compile_objective(root, objective=..., max_steps=25, verify=True, apply=True,
  scope_module=None)` runs one campaign. `scope_module` confines it to one file.
- `available_objectives()` lists every objective (built-in **and** discovered).

### RenamePlan + apply — `app/execution/cross_file_rename.py`
A `RenamePlan` carries `old`, `new`, `blockers`, `originals`, `new_contents`,
`edits_by_file`. An **empty** plan (no `new_contents`, no `blockers`) is a clean
**no-op**, not a failure. `apply_rename` writes `new_contents`, runs the suite,
and on failure restores `originals` **and deletes any file the plan created**
(so generative moves like writing a test are first-class and leave no orphan).

### The fractal goal tree — `app/engine/fractal_develop.py`
A high-level **goal** decomposes, self-similarly, into sub-goals and leaf
objectives. `resolve_goal(goal)` flattens it deterministically. Current tree:

```
reduce-debt ─ tidy ─ modernize · simplify-bool-return · remove-dead-code · dead-params
            │      └ polish ─ remove-unused-imports · sort-imports · simplify-comprehension
            │      └ simplify-conditions ─ merge-isinstance · collapse-startswith
            └ simplify-structure ─ dedup · shrink-functions · inline-helpers
harden ─ cover-gaps         (standalone TEST dimension; not under reduce-debt)
```

### The commands
| Command | What it does |
|---|---|
| `apex develop --objective X [--apply]` | run one objective's campaign (dry run by default) |
| `apex develop --goal G [--apply]` | run a fractal goal (all its leaf objectives) |
| `apex develop --all` | sweep every objective |
| `apex plan` | the priority board — what to improve next, worst fixable debt first (changes nothing) |
| `apex ascend [--apply] [--goal G] [--until 90\|A-]` | **autonomous self-improvement**: each round develop the worst fixable debt, suite-gated and grade-proven, to a fixpoint |
| `apex brief --develop [--apply]` | turn a work brief's evidenced concerns into verified campaigns, then re-measure the burndown |

`ascend` **learns**: it weights each objective's pending debt by the health-gain
it produced per move in past runs (`.apex/dev-history.json`), so the organism
climbs toward the debt that has paid off best. No history → pure pending order
(a fresh project is unchanged).

## Adding a new develop objective (the 3-file recipe)

Thanks to the **auto-registry** (`app/engine/develop_registry.py`), a new
objective registers **itself** — no hub edit, so any number can be added in
parallel without colliding. Scaffold it:

```bash
python scripts/new_objective.py collapse-foo --summary "collapse foo into bar"
```

This writes three files (a registered no-op until you implement the rewrite),
where `<snake>` is the objective name with hyphens turned to underscores (so
`collapse-foo` → `collapse_foo`):

1. **`app/execution/<snake>.py`** — `plan_<snake>(project_root,
   module_rel) -> RenamePlan`. The transform. Follow the canonical pattern in
   **`app/execution/bool_return.py`**: read → `ast.parse` → collect line/column-
   span rewrites → apply bottom-up → re-parse-or-block. Conservative by design:
   any ambiguity is a blocker (or a skipped occurrence), never a guess.
2. **`app/execution/objectives/<snake>.py`** — the `_modules` / `fitness` /
   `moves` trio (now one `register_module_objective(...)` call). Modules under
   `app/execution/objectives/` are discovered automatically.
3. **`tests/test_<snake>.py`** — skeleton tests incl. a self-registration
   assertion. Add a real before/after test once the transform is implemented.

Then implement the TODO, and verify (below). The objective is immediately live
across `develop`, `plan`, and `ascend`.

## Verify discipline — the green gate

The full suite **OOMs** when run as a single pytest process in the container
(one process accumulates every module until the kernel kills it). **Always**
verify with the chunked runner, which runs each chunk in its own process:

```bash
python scripts/verify.py            # all chunks + ruff  (the gate before every commit)
python scripts/verify.py --chunk 1  # just one chunk (fast iteration)
python scripts/verify.py --lint-only
```

- A global **`--timeout=120`** (in `pyproject.toml`) catches hangs. A genuinely
  slow test overrides it per-test with `@pytest.mark.timeout(N)` (see
  `tests/test_security_audit.py`) — don't remove the global to fix one slow test.
- `ruff check app/` must be clean.
- Tests use `tmp_path` and self-contained demo projects; `from __future__ import
  annotations` at the top; type hints on public APIs; dataclasses over dicts.

## Memory / learning stores (`.apex/`)
| File | Purpose |
|---|---|
| `dev-history.json` | every graded campaign (the fitness trajectory `ascend` learns from) |
| `composition-archive.json` | MAP-Elites: best verified composition per objective × operator-mix |
| `dream-journal.json` / `dream-promotions.json` | the nocturnal discovery loop |

## Conventions
- **Branch / commit**: develop on the assigned feature branch; commit messages
  end with the session footer line. Don't open PRs unless asked.
- **Parallel agents**: each agent works in its own git worktree on **disjoint
  new files** and self-registers — integration is a clean cherry-pick with zero
  hub wiring.
- **Never** put model/assistant identity in committed artifacts.
