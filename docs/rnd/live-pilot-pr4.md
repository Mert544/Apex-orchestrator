# Live pilot: PR #4 — first real-PR run of all three GitHub surfaces

**Date:** 2026-07-08 → 2026-07-09 · **PR:** Mert544/Apex-orchestrator#4
(branch `claude/apex-development-cdhj5c` → `main`, 67 commits) ·
**Outcome: MERGED** (merge commit `56a5477`), all 8 checks green on head
`f12fa80` — including the first-ever green `security-audit` job.

## What was piloted

The three live distribution surfaces, on a real PR against this repo:

1. **apex-review** — sticky PR review comment (deterministic diff review).
2. **apex-autofix** — `apex review --fix` on the PR branch; commits only
   test-verified fixes back.
3. **security-audit** — SARIF/code-scanning + `scripts/security_audit.py`
   gate behind the chunked ~20k-test job.

## The pilot's yield: four real environment bugs, found and fixed live

Every one was invisible to the in-house suite and only surfaced by running
the surfaces on a real PR — exactly the pilot's purpose.

| # | Bug (live symptom) | Root cause | Fix |
|---|---|---|---|
| 1 | Both chunked `test` jobs died at collection | shallow clone broke 11 `git show <sha>:` characterization tests; single-process pytest OOM-prone | `fetch-depth: 0` + chunked gate (`bcbce52`) |
| 2 | Bot pushed a phantom "autofix" commit (894-line REPORT committed as fixes) | report written into the working tree; commit step treated any dirty tree as fixes | report → `$RUNNER_TEMP`; commit gated on `grep -q "🔧 Applied"` AND dirty tree |
| 3 | Sticky-comment action error after fix 2 | my own incomplete fix left the sticky `path:` at the old location | `path: ${{ runner.temp }}/apex-autofix.md` (`34192a8`) |
| 4 | `security-audit` failed the pipeline on 6 eval/exec CRITICALs | the audit script had **never been green on Apex's own tree** — fix 1 let it run past `test` for the first time; the synthesis engine's deliberate fixed-template eval/exec sites carry reviewed `# nosec` annotations the auditor ignored | audit honors `# nosec` fail-closed: annotated criticals move to a visible `acknowledged` bucket; unannotated/mixed/unresolvable stay CRITICAL and fail (`f12fa80`, 7 stash-verified red-first pins + repo-level live pin `critical == 0`) |

## Secondary findings

- **Model economy validated live:** a Sonnet worker produced the quickstart
  alignment in 14 min; orchestrator adversarial review caught (by
  measurement) that its engine unification cost 120 s even at
  `max_steps=1` on this 630-module repo — rejected, replaced with honest
  labeling (`6313f74`). The pattern (worker executes, orchestrator
  measures/reviews/gates) worked as designed.
- **Flake protocol exercised:** `tests/test_stub_count_eyml.py` recorded
  its 1st -j4 contention flake (nested-pytest 120 s timeout; isolated rerun
  13/13 green). Quarantine bar remains 2 independent flakes.
- **CI cost profile (2-core hosted runner):** each chunked ~20k gate ≈ 82
  min; full check round ≈ 85 min. Pushing to a green PR resets everything —
  hold doc-only commits until after the merge decision.

## Lesson

A gate that has never run is indistinguishable from a gate that passes.
The audit job was red-on-arrival the moment its prerequisite stopped
masking it — surface prerequisites (here: a green `test` stage) can hide a
never-green check indefinitely. Live pilots exist to flush exactly this.
