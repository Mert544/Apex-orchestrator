# Token Economics Architecture Branch

## Why this branch exists

Apex Orchestrator will be used through external agent environments and model stacks.
That means token cost is not a side issue — it is part of the system architecture.

When the agent is used with models such as Claude, Codex, Gemini, Qwen, DeepSeek, Minimax, or others, three different token surfaces matter:

1. **analysis tokens** — used while the model reasons over repo state
2. **response tokens** — used when the model explains findings, plans, and patches
3. **memory/context tokens** — used when prior runs, docs, and working context are loaded

This branch defines how Apex Orchestrator should treat token usage as a first-class engineering concern.

---

## Goal

Make the agent more useful **per token spent**.

Not just:
- more intelligence
- more automation
- more branches

Also:
- less waste
- better compression
- selective depth
- cheaper repeat runs
- predictable budget usage across model providers

---

## Main design principle

**Spend tokens only where epistemic value is high.**

This means:
- scan broadly first
- deepen only valuable branches
- degrade repeated questions instead of restating them
- compress reports and memory where safe
- separate “thinking detail” from “user-visible verbosity”

---

## Architecture layers

### 1. Branch budget layer

Each branch should compete for token budget.

Questions to ask:
- Is this branch novel?
- Is it risky?
- Is it actionable?
- Is it likely to change engineering decisions?

Low-value branches should be cut early.

### 2. Memory compression layer

Persistent memory should not grow forever in raw form.

Needed strategies:
- keep structured memory summaries
- preserve branch maps and critical evidence
- compress repeated natural-language explanations
- store task outcomes in short canonical form

### 3. Output compression layer

Different users and models need different output styles.

Modes should exist for:
- **full reasoning summary**
- **engineering brief**
- **compressed operator mode**
- **machine-friendly patch summary**

This is where external repos like `caveman` become relevant.
A repo such as `JuliusBrussee/caveman` can be evaluated as an optional output-compression layer for agent responses, especially in multi-model or high-volume usage.

### 4. Model routing layer

Different models can serve different roles:
- cheap model for broad scan
- stronger model for patch planning
- precise model for verification or security review

Apex Orchestrator should evolve toward model-role separation instead of assuming one model does everything.

---

## Candidate token metrics

Track at least:
- cost per full scan
- cost per focused branch run
- cost per successful supervised patch loop
- memory growth per run
- average branch count per useful outcome
- compression ratio for reports and memory summaries

---

## Proposed implementation path

### Phase A
- add token accounting fields to reports
- record approximate prompt/output sizes per run
- separate scan budget from patch-loop budget

### Phase B
- add compressed report modes
- add compressed memory snapshots
- add summary-only replay for old runs

### Phase C
- integrate optional external compression layers
- benchmark compressed vs uncompressed operator outputs
- compare readability, accuracy, and cost

---

## `caveman` as an evaluation repo

`JuliusBrussee/caveman` is useful here for two reasons:

1. it is itself a compression-oriented agent repo
2. it gives us a concrete benchmark target for output-compression architecture

Apex Orchestrator should be able to:
- clone and scan the repo
- extract real compression claims
- test whether its own reports can be emitted in shorter operator formats
- compare normal vs compressed reporting without losing engineering value

---

## Strategic conclusion

Apex Orchestrator should not treat token reduction as a cosmetic feature.
It should become a dedicated architecture branch:

**reason deeply, branch selectively, remember compactly, speak efficiently.**
