# Apex Orchestrator — Where It Fits

> **Honesty note:** this page describes what Apex *is* and *is not*, and when to
> reach for it versus an LLM coding assistant. We don't publish ✅/❌ feature
> grids about other tools — those age badly and we can't verify competitors'
> internals. We describe our own properties; every one of them is checkable in
> this repository.

## What Apex is

A **deterministic project-development assistant**. Its core loop — profile the
codebase, generate a fractal tree of grounded development ideas, sequence them
into a roadmap, apply test-verified fixes with automatic rollback — runs with
the Python standard library only. No LLM, no API key, no network.

Three properties follow from that design, and they are the entire pitch:

1. **Reproducible.** Same repository state → same ideas, same roadmap, same
   fixes. You can replay any run; CI gates stay stable.
2. **Private and free per run.** Code never leaves the machine; there is no
   per-token cost, so running it on every commit costs nothing.
3. **Evidence-bound.** Every idea cites the concrete code fact that produced it;
   every applied fix is verified against your test suite and recorded in a
   proof-of-fix artifact (diff, tests run, durations, rollbacks).

## What Apex is not

- **Not a code generator.** It will not write a new feature from a prompt. Its
  autonomous changes are limited to a catalog of safe, AST-based transforms;
  higher-risk issues are flagged with a proposed direction, not rewritten.
- **Not a conversation.** It has no natural-language understanding beyond a
  small goal parser. Ambiguous, creative, or genuinely novel design work is out
  of scope by construction.
- **Not multi-language (yet).** Analysis and transforms are Python/AST-based.
- **Not a replacement for LLM assistants.** It is the layer that *complements*
  them: deterministic review and grounded prioritization around code that
  humans or LLMs wrote.

## When to use what

| You want… | Reach for |
|---|---|
| Inline completions, conversational coding, new feature drafts | An LLM assistant (Copilot, Cursor, Claude Code, …) |
| "What should this project build/improve next, in what order?" | **Apex** (`apex ideate --roadmap`) |
| A deterministic, zero-cost PR gate that never answers differently twice | **Apex** (`apex grade`, `apex review --sarif`) |
| Autonomous cleanup whose every change is test-verified and auditable | **Apex** (`apex maintain`, proof-of-fix artifact) |
| Air-gapped / no-API-key / compliance-restricted environments | **Apex** |
| Security basics covered *inside* the same roadmap (detectors + Secure phase + SARIF), no separate scanner | **Apex** |
| Cross-run memory: "did last month's hotspots actually get resolved?" | **Apex** (`--roadmap --diff`, signal-narrated) |
| Large multi-file refactors, ambiguous requirements, creative work | An LLM assistant, human-reviewed |

## How we measure ourselves

- **Self-application:** Apex runs on its own codebase in CI; the published
  grade and dashboard are regenerated from the latest commit. The repository's
  1880+ tests are the verification layer every autonomous fix must pass.
- **Fixture detection suite:** the repository ships intentionally-flawed
  example projects (`examples/`) used as regression tests for the detectors.
  These are *fixtures we planted ourselves* — they prove the detectors work as
  specified, **not** field accuracy. Treat them as unit tests, not benchmarks.
- **What we don't yet have:** independent, third-party accuracy benchmarks on
  real-world repositories. Until a reproducible public benchmark exists
  (planned: pinned OSS-repo snapshots with published precision/recall), we
  make no comparative accuracy claims.

## The design bet

LLM assistants made code generation cheap; the scarce resources now are
**trust, prioritization, and verification**. Apex bets that a deterministic
engine which *reasons about what to build next* and *proves what it changed*
is worth more to a team than one more generator — and that it can earn that
trust precisely because every claim it makes is reproducible and inspectable.
