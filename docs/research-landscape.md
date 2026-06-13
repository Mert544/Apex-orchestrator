# Landscape research — who else delivers pieces of the fractal promise? (2026-06)

> **Why this document:** the tree is the icon; the *promise* is fractal
> reasoning that develops projects — grounded ideas, sequenced plans, verified
> execution, cross-run narrative. This maps who delivers fractions of that
> promise, what we can legally and architecturally use, and where our original
> moves live. Decisions feed `ROADMAP.md`.

## 1. The map — neighbors and what they own

| Tool | Their fraction of the promise | License / usability | Verdict |
|---|---|---|---|
| **CodeScene** | Behavioral code analysis: hotspots = churn × complexity, *temporal coupling*, knowledge maps, deterministic CodeHealth metric, debt prioritization by how the team works | Proprietary SaaS — concepts published (Tornhill's books/papers), tool unusable | **BUILD the concepts** (clean-room, stdlib): co-change coupling ✅ shipped, knowledge factor next |
| **OpenRewrite / Moderne** | Deterministic execution at scale: human-authored recipes over lossless semantic trees, composable into migrations; "correctness over completeness" | Apache-2.0 (core) | **STUDY the recipe model**: declarative metadata + composition is the growth path for our transform catalog (`apex upgrade`-style composite plans) |
| **OpenSSF Scorecard** | Repo *process* health 0–10 (CI, review policy, branch protection), badge + public API distribution | Apache-2.0 | **PARTIAL ADOPT**: a few cheap process checks (license file, CI — ours exists) into the grade; copy the badge/API *distribution* idea for `apex bench` |
| **SonarQube** | Metric vocabulary: **cognitive complexity** (published spec, 77% dev acceptance) vs raw cyclomatic | Spec published; formula = method, not copyrightable | **BUILD**: stdlib cognitive complexity to upgrade hotspot-function, effort estimation and facet evidence |
| **GitHub Spec-Kit** | Promise→code direction: spec → plan → tasks artifacts as the source of truth (LLM-centric) | MIT | **MIRROR**: we are its deterministic complement (ideas → roadmap → briefs, evidence-grounded). Possible interop: emit `apex brief` in a tasks-file format |
| **tree-sitter** | Multi-language parsing (incremental, queries), powers GitHub code nav | MIT | **DEFER, keep warm**: the BS-1 (beyond-Python) path when we open it — optional dependency, core stays stdlib |
| **Truck-factor research (Avelino/DOA)** | Knowledge concentration from git authorship — who solely owns which file | Published algorithm (papers) | ✅ **BUILT**: knowledge-risk signal (≥85% single-author, two genuinely active authors required) |
| **Anthropic Dreams** (Managed Agents, research preview) | Scheduled memory curation: an LLM reads a memory store + up to 100 session transcripts, outputs a NEW reorganized store (input untouched); merges duplicates, drops stale entries, surfaces cross-session patterns; billed per token, minutes per run | Separate product/API (beta headers, access form) | ✅ **REBUILT deterministically** (`apex dream`): artifact stores instead of transcripts, rules instead of an LLM, seconds instead of minutes, zero tokens. Adopted their two superior design calls: inputs never modified by default (curation is a reviewed proposal until `--curate`) and cross-run consolidation (the dream journal annotates patterns "seen in N consecutive dreams"). Then went past parity into their one true advantage — open-ended discovery: `dream_discovery.py` mines the full signal-COMBINATION space (no combination coded in advance) for associations and confluences, deterministic, so adding a signal widens discovery with zero code change. Open-ended over known signals' combinations — honestly short of an LLM's concept invention, a real step past enumerated pattern classes. THEN closed the loop they don't: discoveries that persist across PROMOTE_STREAK dreams at high confidence GRADUATE into waking development ideas (dream→confirm→promote→seed), persistence-gated so noise never oscillates into the tree — a deterministic self-improving organism, surfaced at session start via a SessionStart hook |

**Conclusion the map supports:** nobody combines *reasoning about what to build*
(idea tree) + *verified execution* (tiered, shielded, proof-of-fix) +
*cross-run narrative* (signal-attributed diffs). The fractal thesis stands.
Every neighbor owns one organ; none has the organism. What they do own, we
adopt as **food for the tree** — new signals and better measurements, never a
new headline.

## 2. Adoption queue (decided)

1. ✅ **Co-change coupling** (CodeScene concept, clean-room) — *shipped with
   this document*: modules that repeatedly change in the same commits are
   factually coupled, whether or not an import connects them. Feeds pair
   ideas with measured evidence.
2. **Cognitive complexity** (Sonar spec, clean-room stdlib) — replaces raw
   branch counts where "hard to understand" is the real question: hotspot
   functions, effort estimation, `complexity N` magnitudes.
3. **Knowledge factor / DOA** (Avelino) — per-module authorship concentration
   from git; a single-author dependency hub seeds a knowledge-risk idea;
   pairs with churn and convergence.
4. **Recipe metadata + composition** (OpenRewrite model) — declare transforms
   with tags/preconditions; compose into named upgrade plans.
5. **Process checks + badge distribution** (Scorecard model) — small grade
   additions; publish bench/grade as a fetchable badge.

## 3. Original moves (no neighbor does these)

- **Temporal convergence** — convergence today is *spatial* (independent
  signals agree on one module). Add the time axis: a module whose churn is
  *rising* while its debt *ages* is an accelerating hotspot — a different
  urgency than a stable one. Cross-run snapshots already hold the data.
- **Evidence-burndown briefs** — `apex brief` checklists where items bind to
  facet evidence, so progress is *measured* by the next scan (evidence gone =
  item done), not self-reported. The work order audits itself.
- **Promise ledger** — generalize doc-drift: every promise surface (README
  claims, CHANGELOG, "supports X" docstrings) tracked across runs like the
  roadmap diff — a kept/broken-promises narrative per release.
- **Co-change pair ideas** — adoption×original hybrid: CodeScene *shows*
  temporal coupling; nobody *generates development ideas* from it. We do, with
  the measured count as the idea's magnitude.

## 4. Licensing notes

Concepts, metrics and published algorithms (cognitive complexity spec, DOA,
hotspot = churn×complexity) are methods — implementable clean-room; we cite
sources and never copy code or trademarks (e.g. "CodeHealth" is theirs; our
grade keeps its own name). Apache-2.0/MIT tools (OpenRewrite, Scorecard,
tree-sitter, Spec-Kit) are study- and integration-safe. The core stays
stdlib-only; anything external enters as an *optional* integration.

## Sources

- CodeScene behavioral analysis: <https://codescene.com/product/behavioral-code-analysis>, <https://codescene.com/>
- OpenRewrite recipes: <https://docs.openrewrite.org/concepts-and-explanations/recipes>, <https://github.com/openrewrite/rewrite>
- OpenSSF Scorecard: <https://github.com/ossf/scorecard>, <https://scorecard.dev/>
- Cognitive complexity: <https://www.sonarsource.com/resources/cognitive-complexity/>, <https://arxiv.org/pdf/2007.12520>
- Truck factor / DOA: <https://homepages.dcc.ufmg.br/~mtov/pub/2019-sqj.pdf>, <https://github.com/aserg-ufmg/Truck-Factor>
- Spec-Kit: <https://github.com/github/spec-kit>
- tree-sitter: <https://github.com/tree-sitter/tree-sitter>, <https://tree-sitter.github.io/>
- Anthropic Dreams: <https://platform.claude.com/docs/en/managed-agents/dreams>, <https://claude.com/blog/new-in-claude-managed-agents>

## 2026-06-13 — The codemod neighbors, and the move they validated

Fresh scan of the structural-rewrite and behavioral-analysis space:

| Neighbor | What it does | What Apex takes from the comparison |
|---|---|---|
| [ast-grep](https://github.com/ast-grep/ast-grep) | tree-sitter structural search/rewrite, polyglot, `$X` metavariables | The pattern language UX (metavariables) — but it rewrites **without running your tests** |
| [Comby](https://github.com/untitaker/spacemod/blob/main/docs/alternatives.md) | parser-free structural match across any text | Robust but not AST-aware; spans can cross node boundaries |
| [GritQL / Biome plugins](https://dev.to/herrington_darkholme/biomes-gritql-plugin-vs-ast-grep-your-guide-to-ast-based-code-transformation-for-jsts-devs-29j2) | a full query language over code | Powerful, but a language to learn; Apex keeps one expression + `$x` |
| [OpenRewrite / Moderne](https://docs.openrewrite.org/) | deterministic recipe catalog over lossless semantic trees (JVM-first) | Direct validation of `apex recipes`' model: deterministic, composable, catalog-driven |
| [CodeScene / code-maat](https://github.com/adamtornhill/code-maat) | behavioral analysis: hotspots = churn × complexity, knowledge maps | Apex grew the same signal family independently (churn, knowledge-risk, co-change, convergence) — and adds the apply+verify loop they stop short of |
| [Rope](https://github.com/python-rope/rope) | the classic Python refactoring library | The bar for rename/extract correctness; Apex's surface is CLI-first + test-verified |
| Sourcery | "not wrong but could be better" suggestions | Apex's idea tree plays this role with full provenance per idea |

**The gap none of them fill** — and the move shipped today: a user-defined
structural rewrite that is *verified*. `apex rewrite 'len($x) == 0' 'not $x'`
matches structurally (AST, not text), keeps each capture's own spelling,
skips multi-line matches honestly, refuses unbound metavariables — and then
runs the project's suite, rolling back on red. ast-grep finds and rewrites;
Apex finds, rewrites, **proves, or undoes**.

Sources: [ast-grep comparison](https://ast-grep.github.io/advanced/tool-comparison.html) ·
[CodeScene hotspots](https://docs.enterprise.codescene.io/versions/3.3.6/guides/technical/hotspots.html) ·
[OpenRewrite docs](https://docs.openrewrite.org/) ·
[Moderne on determinism](https://www.moderne.ai/blog/understanding-openrewrite-beyond-the-myths) ·
[rope](https://github.com/python-rope/rope) ·
[Sourcery alternatives 2026](https://dev.to/rahulxsingh/sourcery-ai-alternatives-10-best-code-quality-tools-in-2026-98n)

### How Apex leapfrogs (shipped 2026-06-13)

Two competitor weaknesses, two counters — both live:

1. **OpenRewrite's catalog is right; its contribution cost is wrong** (a
   recipe = a compiler-grade visitor). Apex's rule book makes a recipe ONE
   LINE: `apex rewrite 'len($x) == 0' 'not $x' --save no-len-eq-zero`. The
   book is committed config; `apex rewrite --all` re-applies every rule,
   each suite-verified — and the nightly run executes it, so saved rules
   become **fitness functions that fix themselves**.

2. **ast-grep's rules are hand-written; Sourcery's suggestions are ML.**
   `apex teach` learns the rule from examples by deterministic
   anti-unification: show two BEFORE/AFTER pairs, the differing subtrees
   become metavariables, identical capture-pairs collapse to one variable,
   and the learned rule must reproduce every example (self-check) before it
   is ever displayed. First live run: taught from two examples, learned
   `len($v1) == 0 → not $v1`, applied 19 matches across 16 of Apex's own
   files, suite green. *Fix it once — Apex writes the law.*
