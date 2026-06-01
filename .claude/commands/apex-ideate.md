---
description: Generate a tree of development ideas for this codebase using Apex's Idea Permutation Engine (deterministic, no LLM). Use when asked "what should we build/improve next" or to brainstorm grounded, traceable development directions.
argument-hint: "[target path] (default: repo root)"
allowed-tools: Bash
---

Run Apex's Idea Permutation Engine on the target and summarize the result for the user.

Target: `$ARGUMENTS` (if empty, use the repository root `.`).

Run it (deterministic, offline — safe to run anytime):

```!
python -m app.cli ideate --target="${ARGUMENTS:-.}" --depth=2 --breadth=4 --max-ideas=30 --actions
```

Then:
1. Summarize the highest-value development ideas (group by kind: permutation, synthesis, module-pair).
2. Call out any 🔴 fragile modules or 🔄 import cycles surfaced.
3. List which action steps are **executable** (Apex can draft/apply them) vs **design tasks** (need a human).
4. Do NOT apply anything — this is a planning/brainstorming command. If the user wants to apply fixes, point them to `/apex-maintain`.
