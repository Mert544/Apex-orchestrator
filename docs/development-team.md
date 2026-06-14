# Apex Development Department — the team playbook

_The repeatable process by which Apex is built by a coordinated team: one
orchestrator (chief engineer) plus a roster of specialist agents working in
parallel, isolated git worktrees. Deterministic where it can be, disciplined
everywhere. Signed by barzeuss._

This is not aspirational — it is the process that produced the blind-spot
hardening, the new capabilities, and the self-improvement waves. It is written
down so every future run follows the parts that worked and avoids the mistakes
that cost time.

## Roster

| Role | Agent type | Scope | Writes? |
|------|-----------|-------|---------|
| Orchestrator | (chief engineer) | Plans, partitions, integrates, gates, pushes | yes — owns `main` branch |
| Feature engineer | `apex-engineer` | ONE self-contained capability end-to-end, with tests | yes — own worktree only |
| Auditor | `apex-auditor` | Read-only findings: bugs, blind spots, non-determinism | no — reports only |
| Test writer | `apex-test-writer` | Raise coverage of disjoint module sets | yes — own worktree, tests only |

The orchestrator is the only one that pushes to the remote or opens PRs.

## The seven invariants

1. **Worktree isolation.** Every agent runs in its own git worktree (a full,
   separate checkout). No two writers ever touch the live main tree at once.
2. **Disjoint files.** Partition the work so no two agents edit the same file.
   Integration is then a conflict-free `git cherry-pick`; overlap is the only
   thing that makes a merge hard, so design it out up front.
3. **The green gate.** `python scripts/verify.py` (the chunked test suite + ruff)
   is the single definition of done. Nothing integrates red. The suite is
   chunked because it OOMs as one process in a constrained container; run it as
   `--chunk K` slices if you need to bound any single step's time.
4. **Agents don't push.** A specialist commits to its worktree branch and
   reports its SHA. The orchestrator cherry-picks that SHA onto main, runs the
   full gate, then commits and pushes. One integration at a time.
5. **Size to value, not to slots.** Many agents is not the same as much value.
   Spawn an agent only for work that is genuinely disjoint AND worth a parallel
   seat. An idle-but-spawned agent is pure cost (CPU contention, coordination).
6. **Sequence heavy CPU.** Do not run the full gate while CPU-heavy agents are
   benchmarking or running their own suites — contention can stretch a 230s gate
   past 1000s. Integrate and gate when the fleet is idle, or gate in bounded
   per-chunk slices.
7. **Prune worktrees when done.** Agent worktrees live under `.claude/` and are
   full repo copies. Left behind, they pollute every tree-walk (double-counted
   modules, colliding test basenames, analyzers grading the COPIES) — the exact
   blind spot `app/engine/skip_dirs.py` now guards against. `git worktree remove`
   the stale ones after integrating; their branches survive, so no commit is lost.

## The flow

```
scope ──► partition into disjoint streams ──► spawn specialists (worktrees)
                                                      │
                          each gates locally (targeted tests + ruff)
                                                      │
   orchestrator, one stream at a time:  cherry-pick ─► FULL gate ─► commit ─► push
                                                      │
                              prune stale worktrees ──► report
```

## Why this beats a single agent

A lone agent serializes everything and has no second pair of eyes. The team
runs independent, verifiable work in parallel and crosses it: an **auditor**
finds the blind spot, an **engineer** fixes it, a **test writer** locks it in —
each in isolation, each gated, integrated deterministically. The orchestrator
keeps the whole thing honest by never integrating anything that isn't green.
