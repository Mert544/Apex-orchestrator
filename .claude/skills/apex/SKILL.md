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

- `apex auto [GOAL] [--target=.] [--apply]` — **the recommended entry point**. Assesses the
  project, prioritizes via the roadmap, and recommends the best next moves (default: no
  changes); `--apply` runs the safe, test-verified fixes in roadmap order (capped, verified,
  auto-rollback). Bare `apex` (no subcommand) runs this in recommend-only mode. Use it when
  you don't want to memorize the specialized commands below.
- `python -m app.cli ideate --target=. --depth=2 --breadth=4 --actions` — idea
  permutation tree + supervised action plan (`--kind synthesis|pair|permutation` to filter,
  `--draft` to preview real patches, `--mermaid`, `--out FILE`).
  - `--facets [--facet-depth N]` — **fractal zoom**: expand the strongest leaves into
    self-similar sub-ideas (L1 = operator aspects, L2+ = common/boundary/failure cases).
  - `--roadmap` — sequence the tree into **Stabilize→Secure→Evolve→Refine** phases with
    impact/effort/ROI (grounded in measured fan-in + LOC/complexity) and quick wins.
    `--roadmap --save` snapshots to `.apex/roadmap-snapshot.json`; `--roadmap --diff`
    reports what changed since (new / no-longer-surfaced / phase-moved / ROI shift).
    `--roadmap --actions [--phase Secure]` orders the apply plan by phase.
  - `--shape` — tree-shape telemetry (branching factor, depth dist, subject spread, facet
    penetration) + the engine's own observations on how to steer the next run.
  - `--pareto` — the efficient frontier: non-dominated ideas across impact/effort/value
    (everything else is strictly dominated and safely ignorable).
  - `--sequence` — dependency-ordered execution plan (test a module before changing it,
    document after building, break a cycle before its interface) + the critical path.
  - `--budget N` — the impact-maximizing *portfolio* of ideas whose total effort fits N
    (a precedence-constrained knapsack; prerequisites are pulled in automatically).
  - `--adaptive` — value-guided fractal: high-value branches grow deeper than `--depth`
    (pairs well with a larger `--max-ideas`). Learning + adaptive depth compose: as the
    engine learns which lenses are reliable, those branches deepen.

Learning: `auto`/`maintain`/`evolve` record apply outcomes to `.apex/idea-memory.json`;
later runs nudge feasibility toward lenses with a good track record (bounded ±10%, no-op
without the file). `apex auto` prints what it has learned.
- `apex evolve --target=. [--max-cycles N] [--dry-run] [--commit]` — self-improvement
  loop: apply guarded fixes cycle by cycle to a fixpoint, then prove the gain (before/after
  security findings + open fixes + mean ROI, plus a roadmap diff of resolved ideas).
- `apex explain [BRANCH] --target=.` — show *why* an idea scored what it did: provenance
  (the code fact), the value formula with the weights used, roadmap impact/effort/ROI
  grounded in fan-in + LOC, the action it maps to, and its caveats. Defaults to the top idea.
- `apex brief [BRANCH] --target=.` — turn a design-level idea (hub evolution, integration,
  generalization — the non-executable steps) into an actionable work order: grounding facts,
  measured context (fan-in/LOC/complexity), the fractal facet vocabulary as a checklist, and
  a definition-of-done the engine itself verifies on the next run (`--roadmap --diff`).
- `apex dream [--target=.]` — the nightly curator: reviews the organism's memory stores
  (outcome memory, saved briefs, proof-of-fix, signal trends), extracts patterns, archives
  fully-resolved briefs, trims memory to high-signal keys, writes `.apex/dream-digest.md`.
  Open-ended DISCOVERY: mines the full signal-combination space (no rule named in advance)
  for associations ("80% of single-author modules are also high-churn") and confluences
  (a module whose signal fingerprint is unusually broad). Default reports; `--curate` applies — and a confluence confirmed across enough dreams MATERIALIZES its own saved work order (`apex brief x.y --check`), so a standing discovery becomes a measurable brief without a human in the loop.
- `apex changelog [--target=.] [--out FILE]` — release notes from ARTIFACTS, not memory:
  commits since the last tag, verified fixes (proof-of-fix, with shields/strength), roadmap
  ideas that landed (signal-narrated), the current grade. Sections render only when their
  artifact exists.
- `apex grade [--min-score N]` — single project health grade (A–F) from all signals, with
  a breakdown + cheapest fixes; `--min-score` gates CI.
- `apex bench [--manifest docs/bench/manifest.json] [--out FILE]` — grade pinned external
  codebases with the same rubric (calibration context for the grade; exact SHAs, fully
  reproducible; local `path` entries keep tests offline). Results: `docs/bench/results.md`.
- `apex simulate [--max-cycles N]` — preview what `apex evolve` would do, run on a disposable
  copy so the real tree is never touched.
- `apex impact <function> [--target=.]` — function-level blast radius: who transitively
  calls a function (direct callers are precise; transitive is name-based + hub-stopped).
- `apex review [--base REF] [--fail-on-high]` — diff-scoped code review (Apex as a PR
  reviewer): flags security/bug/style/docs issues on the *changed* lines only, noting which
  Apex can auto-fix. Also flags violations of your saved REWRITE RULES on the changed lines (category `convention`, fixable by `apex rewrite --rule NAME`). `--fail-on-high` exits non-zero for CI gating — fixture/test code is excluded (its flaws are intentional); `--max-findings N` caps the comment so a wide diff stays under the PR comment size limit.
- `apex rename OLD NEW [--target=.] [--dry-run] [--no-verify]` — cross-file rename of a
  top-level function/class: definition + imports + call sites, comment-preserving span
  edits, conservative blockers (ambiguity/shadow/collision), test-verified with rollback.
  With `--param FUNC`: renames a *parameter* of FUNC instead — def site, body uses, and
  every keyword call site project-wide (positional calls untouched; `**kwargs` sites warn).
- `apex signature drop FUNC PARAM [--target=.] [--dry-run] [--no-verify]` — remove a
  parameter the function body never reads: the `def` is rebuilt without it and every
  keyword call site loses the argument, project-wide. Positional callers block ("convert
  to keywords first" — no silent repositioning), `**kwargs` sites warn, a comment inside
  the signature blocks (comment-preservation promise). Test-verified with rollback.
- `apex signature add FUNC PARAM --default EXPR [--dry-run] [--no-verify]` — introduce a
  parameter with a safe default (no call site can break by construction). Placement is
  safety-chosen: appended positionally, or keyword-only after `*args`/existing kwonly
  params (a trailing default before `*args` would absorb positionals). A caller already
  passing that keyword blocks; `f(**…)` sites warn. Test-verified with rollback.
- `apex signature keywordify FUNC [--dry-run] [--no-verify]` — rewrite every positional
  call site of FUNC as keywords (`f(v, 4)` → `f(value=v, factor=4)`), project-wide.
  The drop-enabler: a `signature drop` blocked on positional callers chains through
  this. Positional-only params stay positional; calls feeding `*args` are left alone
  (warned); `f(*xs)` and paren-wrapped arguments block. Test-verified with rollback.
- `apex signature reorder FUNC a,b,c [--dry-run] [--no-verify]` — change the REGULAR
  parameters' order. Callers need no edit by construction: any caller passing them
  positionally blocks with the chain hint (`keywordify` first). Positional-only,
  `*args`, keyword-only and `**kwargs` sections stay put; an order that puts a
  required param after a defaulted one blocks (it wouldn't compile).
- `apex rewrite 'PATTERN' 'REPLACEMENT' [--dry-run] [--no-verify]` — user-defined
  STRUCTURAL rewrite, project-wide: `$name` matches any expression (AST, not text;
  the same `$name` must capture the same source), the replacement reuses captures
  verbatim. Multi-line matches are skipped with a warning; unbound replacement
  metavariables and bare-`$x` patterns block. Suite-verified with rollback —
  the ast-grep shape, plus the proof the neighbors don't run.
- `apex rewrite --save NAME | --rule NAME | --rules | --all` — the project RULE BOOK
  (`.apex/rewrite-rules.json`, committed): save a pattern as a named rule, run one, list
  them, or `--all` to re-apply every rule (each verified) — drift that re-enters the
  codebase gets rewritten back out; the nightly dogfood runs this as an enforcement step.
- `apex teach BEFORE AFTER [BEFORE2 AFTER2 ...] [--save NAME]` — learn a rule FROM
  EXAMPLES via deterministic anti-unification: differing subtrees become $metavariables,
  the same capture-pair reuses one variable, and the rule SELF-CHECKS by reproducing every
  example before it is shown. One pair = exact-match rule (honest note). Never applies —
  preview + optional save; apply via `apex rewrite --rule NAME`.
- `apex extract FILE START END NAME [--target=.] [--dry-run] [--no-verify]` — lift a
  line range out of a function into a module-level helper NAME. Data flow is computed
  automatically: names read from the surrounding scope become PARAMETERS, names defined
  in the range and used afterward become RETURN VALUES (the call rebinds them). The
  engine's own #1 structural recommendation ("extract a shared helper" for long
  functions) made executable. Conservative blockers: the range must be a contiguous run
  of complete statements in ONE closure-free function (top-level fn or a method of a
  top-level class); `return`/`yield`/`await`/`global`/`nonlocal` or a nested `def`/
  `lambda` in the range block; a `break`/`continue` whose loop is outside the selection
  blocks; the helper name must be free at module level. Suite-verified with rollback.
- `apex inline FUNC [--target=.] [--dry-run] [--no-verify] [--json]` — the inverse of
  `extract`: fold a tiny single-use helper (a body of exactly one `return EXPR`, optional
  leading docstring) into its ONE call site and delete the definition. Arguments are
  substituted for parameters by source-span splicing (formatting preserved), each spliced
  in parenthesized. Conservative blockers: FUNC must be defined exactly once, never
  recursive, decorator-free, with only regular params (no `*args`/`**kwargs`/posonly/
  kwonly); never referenced as a bare object (only called); exactly one call site using
  plain positional/keyword args (no `*`/`**` unpacking); a param used more than once whose
  argument isn't a pure-simple expression blocks (no duplicated side effect). Suite-verified
  with rollback.
- `apex move SRC.py DST.py [--target=.] [--dry-run] [--no-verify]` — move/rename a module;
  every import form (`import x.y`, `from x.y import f`, `from x import y`, aliases) is
  rewritten project-wide, missing `__init__.py` created, relative-import cases block.
- `python -m app.cli maintain --target=. --dry-run` — preview every fix as a unified diff.
  Modes: `--mode report|supervised|autonomous` (+ `--commit`, `--verify` on by default,
  `--no-verify`, `--max-apply N`, `--out MAINT.md`).
- `python -m app.cli dashboard --target=. --out=.apex/dashboard.html` — self-contained HTML
  (overview, findings, architecture, idea tree, **shape**, **roadmap**, actions, reasoning).
- `python -m app.cli debug trace|analyze` — debug subsystem.

Safety model: `report` can't patch; `supervised` patches (test-verified, auto-rollback on
failure) but never commits; `autonomous` also commits each fix individually. SafetyGates
block sensitive paths / secrets / over-scope. Risk tiers (`app/execution/risk_tiers.py`):
Tier 0 (semantics-preserving) auto-applies; Tier 1 (behavior-adjacent) requires the suite
to cover the target — the test-first shield generates a characterization test when nothing
references the module, and with no coverage and no shield the fix is BLOCKED; Tier 2
(design-level) is proposal-only. Verification strength (function/module/none) is graded
per fix and recorded in `.apex/proof-of-fix.json`. New transforms default to Tier 1 —
they must earn Tier 0 by being classified in TIER_BY_ACTION.

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

### Add a fractal facet vocabulary (deepen the zoom)
`_FACETS` in `app/engine/idea_permutation.py` maps an operator → its level-1 aspects;
`_FACET_CASES` is the recursive common/boundary/failure decomposition for deeper levels.
Facets are parented under their leaf (`kind="facet"`), so they render nested and never
break the permutation invariant. `_expand_facets` is gated by `fractal_facets`/`facet_depth`
config and a per-level source cap so depth stays reachable within the budget.

### Add a roadmap dimension (impact / effort / phase)
`app/engine/idea_roadmap.py`: `estimate_impact` (value + structural-risk boosts + measured
fan-in) and `estimate_effort` (1−feasibility + depth + measured LOC/complexity) feed
`ROI = impact/effort`. `classify_phase` routes ideas to Stabilize/Secure/Evolve/Refine by
lens + fact label. Real metrics come from `report.stats["fan_in"]` and `["metrics"]`, which
the engine attaches in `run()` (fan-in from `dependency_edges`, size via
`app/tools/code_metrics.py`). Cross-run comparison lives in
`app/engine/roadmap_history.py` (snapshot + diff by idea title).

### Add a tree-shape observation
`analyze_tree_shape` in `app/engine/idea_tree_shape.py` computes shape metrics; `_observe`
turns thresholds into plain steering advice. Add a metric to `TreeShape` and a matching
threshold reading in `_observe`, then surface it in `render_tree_shape_markdown`.

## Invariants to preserve
- Determinism: same input → same output (no time/random in scoring).
- `node.value` stays in [0,1]; roots keep `novelty == 1.0`.
- Synthesis/pair ideas use `kind != "permutation"` and an `x.s*`/`x.p*` branch path;
  facets use `kind == "facet"`, are parented under their leaf, and reuse the leaf's
  `operator_chain` (they refine the subject, they don't add an operator).
- New engine features that share the idea budget should be **opt-in** (default off) so
  existing callers' idea sets don't shift — see `fractal_facets`.
- Everything stays offline by default; LLM is opt-in.
