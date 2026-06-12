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
| **Anthropic Dreams** (Managed Agents, research preview) | Scheduled memory curation: an LLM reads a memory store + up to 100 session transcripts, outputs a NEW reorganized store (input untouched); merges duplicates, drops stale entries, surfaces cross-session patterns; billed per token, minutes per run | Separate product/API (beta headers, access form) | ✅ **REBUILT deterministically** (`apex dream`): artifact stores instead of transcripts, rules instead of an LLM, seconds instead of minutes, zero tokens. Adopted their two superior design calls: inputs never modified by default (curation is a reviewed proposal until `--curate`) and cross-run consolidation (the dream journal annotates patterns "seen in N consecutive dreams") |

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
