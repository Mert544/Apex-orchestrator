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

## Scaling up: the workflow organism (two teams)

When the backlog holds enough genuinely disjoint work, the department scales to a
two-level organism: **chief engineer → two team leads → three specialists each**
(eight agents). The two standing teams map to the two halves of Apex's work:

- **Team A — Correctness & Hardening.** Blind spots, determinism, measurement
  truth (e.g. the grade chain), safety of transforms. Lead synthesizes findings
  into one coherent, gated change set.
- **Team B — Capabilities & Self-improvement.** New transforms/objectives,
  capability quality (readable output), and dogfooding them on Apex's own body.

**Tooling reality — read this before drawing an org chart.** Only the
orchestrator can spawn agents; a specialist cannot spawn sub-agents. So a "team
lead" is not a sub-commander — it is a **domain-synthesis role**: either the
orchestrator wearing that hat, or a lead agent that prepares and reviews its
team's disjoint outputs for integration. The spawn fan-out stays flat; the
hierarchy is organizational, not literal.

### The phantom-worktree rule (first-class safety)

Every active worktree is a full repo COPY living under `.claude/`. To the
analysis layer it is a phantom — a second (third, eighth) copy of every module
that, unguarded, gets counted, graded, and searched as if it were real code.
This is not a tidiness issue, it is a correctness one: with eight worktrees the
copies outnumber the real tree, and because `.claude` sorts first, a capped
walker fills entirely with phantoms before reaching one real file.

Three rules keep the organism honest as it scales:

1. **The measurement layer must exclude every phantom** — all tree-walks route
   through `app/engine/skip_dirs.py`; a capped walk applies its cap AFTER the
   skip, never before.
2. **Headcount never outruns the gate.** Spawn only as many worktrees as there
   is disjoint work; each extra seat is another phantom to exclude and more CPU
   contending with the green gate. Seats are filled by value, never by quota.
3. **Prune after every wave.** Integrate, then `git worktree remove` the stale
   copies so the next measurement is clean. Branches survive; no commit is lost.

## Standard for every long run (learned from the 8-agent run)

These four refinements turn "many agents" into actual throughput. They are the
default, not the exception:

1. **Every worktree starts at current HEAD.** The single biggest source of
   integration friction was agents spawned on a stale base — they re-implemented
   modules that already exist and collided on shared files. Each agent's FIRST
   step is `git merge --ff-only origin/<branch>` so it builds against the live
   tree. This alone made the later waves integrate cleanly.
2. **Always run an auditor.** The read-only `apex-auditor` was the single
   highest-value seat in every wave — it found real, executable-repro bugs the
   feature agents couldn't see (a whole precedence-splice class, a helper
   mis-insertion). A wave without an adversarial verifier is half-blind.
3. **Every writing agent isolates.** Test-writers must use a worktree too —
   writing straight to the main checkout races the orchestrator and pollutes the
   tree with half-finished files.
4. **Let Apex compute the partition.** `app/engine/work_partition.py` turns a set
   of planned tasks into provably-disjoint parallel groups (via the dependency
   graph + blast-radius), so "these N tasks don't touch each other" is a computed
   fact, not a manual guess — the seed of the army planning its own parallelism.

The remaining bottleneck is the orchestrator's serial integration. The relief is
the same partition data: cherry-pick disjoint groups, gate once per merged batch,
and keep the active headcount matched to what one integrator can gate cleanly.

## Why this beats a single agent

A lone agent serializes everything and has no second pair of eyes. The team
runs independent, verifiable work in parallel and crosses it: an **auditor**
finds the blind spot, an **engineer** fixes it, a **test writer** locks it in —
each in isolation, each gated, integrated deterministically. The orchestrator
keeps the whole thing honest by never integrating anything that isn't green.
