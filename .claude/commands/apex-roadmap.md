---
description: Sequence the codebase's development ideas into a prioritized engineering roadmap (Stabilize→Secure→Evolve→Refine) with impact/effort/ROI grounded in real structure, and optionally track progress across runs. Use when asked "what should we do first / in what order" or "did our work move the needle?".
argument-hint: "[target path] (default: repo root)"
allowed-tools: Bash
---

Build and summarize Apex's engineering roadmap for the target (deterministic, offline).

Target: `$ARGUMENTS` (if empty, use the repository root `.`).

Generate it:

```!
python -m app.cli ideate --target="${ARGUMENTS:-.}" --depth=2 --breadth=4 --max-ideas=40 --roadmap
```

Then:
1. Summarize the **quick wins** (high impact, low effort) first — these are the best ROI.
2. Walk the phases in order — **Stabilize → Secure → Evolve → Refine** — calling out the top
   1–3 items per phase with their ROI and the measured signals (`imported by N`, `M LOC`).
3. Explain the sequencing rationale: safety net before risky change, secure the exposed
   surface, then evolve, then polish.
4. Mention the follow-ups available, without running them unless asked:
   - `--roadmap --save` to snapshot, then `--roadmap --diff` later to see what changed.
   - `--roadmap --actions [--phase Secure]` to turn a phase into a guarded apply plan
     (that one applies fixes — only with the user's go-ahead).

This is a planning command — do not apply anything here.
