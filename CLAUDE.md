# CLAUDE.md — Apex Orchestrator (READ FIRST, EVERY SESSION)

> This file is the **LOCKED North Star**. Claude Code loads it at the start of
> every session so the mission never drifts again. It governs **what to build**.
> `AGENTS.md` and `docs/DEVELOPING.md` govern **how**. If a past session drifted,
> this file is the correction.

## 🎯 North Star (LOCKED — do not relitigate)

Apex is a **zero-token, offline, deterministic, proof-carrying project-DEVELOPMENT
agent**. It takes an **existing project** and makes **concrete, demonstrable
development contributions** to it — autonomously — so a person can offload
mechanical development work to Apex **for free** instead of spending paid-LLM
tokens per message.

**Audience: students AND companies/teams** — anyone with real projects and a
limited or expensive LLM budget. (Example: an architecture student whose paid-LLM
usage is capped and pays per message; equally a company team that wants
mechanical dev work done deterministically and for free. Apex replaces the
per-message token cost for that mechanical work.)

**"Concrete contribution" means Apex LANDS working code, not just advice:**
generate real tests for untested code; implement simple functions from their
signature/docstring/existing tests; scaffold modules/classes/CLIs from a spec;
complete clear `TODO`/`NotImplementedError`; add type hints & docstrings;
modernize idioms; wire boilerplate — each **deterministic, verified, and
auto-rolled-back if it doesn't hold**.

## 🛡️ The moat is the TRUST FOUNDATION, not the goal

Apex's differentiators — **never fakes green**, proof-carrying, coverage-aware
honesty, offline/deterministic/zero-token, plus the auditor & intelligence
layers — are what make it **safe to let a free agent touch your real project**.
They earn trust. **They are not the product.** Per the founder decision
(`AGENTS.md` → "Single focus, 2026-06"), new capability investment goes to
**concrete project-development** (the idea / roadmap / `develop` core), **not**
to more detectors or more safety machinery. The safety infrastructure already
built is excellent and stays — but it is *done enough*; lead with development.

## 🚧 Anti-drift guardrails (the exact failure mode to correct)

1. **Every wave must deliver concrete, demonstrable development value to a real
   project.** If a wave only polishes internal safety / honesty / detector
   machinery, it has **DRIFTED** — stop and redirect to a concrete contribution.
2. Safety/honesty work is allowed ONLY as much as is needed to make a
   concrete-development capability trustworthy. Never build safety for its own sake.
3. Prove value the way a buyer/user sees it: run Apex's `develop` loop on an
   **independent** project and show the **tangible artifacts** it produced
   (real diffs: code, tests, scaffolding) — not just analysis.
4. Apex itself stays **LLM-free / zero-token** — that IS the product. (Claude is
   only the orchestrator wiring; Apex's own output must never depend on an LLM.)

## 🔎 The Mission Auditor ("denetçi") — standing discipline

Every wave is audited against this North Star **before it counts as done**:

- Did it make a **concrete project-development contribution** — land working code
  on a real project, verified?
- Is it **zero-token / offline / deterministic / proof-carrying / auto-rollback**?
- Did it **drift** into pure safety/detector/honesty polishing? If yes → flag and
  redirect.

Run the auditor as a read-only pass each wave (an `apex-auditor` agent). The
durable form is a deterministic **`apex self-audit --north-star`** check in the
repo — **building that check is itself on-mission self-development** and is the
preferred way to make the denetçi permanent and automatic.

## ⚙️ Operating discipline (how — brief; full detail in `AGENTS.md`)

- **Full-green gate before every push:** `python scripts/verify.py` (≈20k tests +
  ruff). Push ONLY on all-green. **Never fake green; never weaken a test to pass.**
- Proof-carrying + **auto-rollback** on every applied change.
- Commit as `mertelgul@gmail.com`; **never rewrite git history**; commit with
  explicit pathspecs (one writer per shared file/registry per wave).
- Parallel agent army is fine, but **≤3 heavy (pytest-running) engineers at once**
  (OOM ceiling; 5 = OOM). Read-only auditors are light. Run the gate alone.
- Develop on the designated feature branch; don't push elsewhere without permission.
- Transient hazards to scrub before grade/gate: any `app/orchestrator/*_scratch.py`
  / `tests/_inline_orig_blob.py` (now fixed to write to tmp); keep `pydantic>=2`.

See `AGENTS.md` and `docs/DEVELOPING.md` for the full development model
(Objective-Compiler, fractal goal tree, `apex develop` / `plan` / `ascend`,
`scripts/new_objective.py`, `apex dream`).
