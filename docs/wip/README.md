# docs/wip — parked work-in-progress (preserved, NOT applied)

These are **git stashes that lived only in a cloud container's working copy**
(never on `origin`), exported to patch files so they are not lost when the repo
is cloned/pulled elsewhere (e.g. moving to a local machine). They are **parked
reference material**, deliberately NOT applied to the tree.

| Patch | What it is | Status |
|---|---|---|
| `scope-honesty-WIP-stash0.patch` | "scope-honesty" reporting WIP from a dead agent ("recover later") — touches `project_profile.py`, the dashboard/reporting + readiness-report surfaces (~344 lines). | **Stale** (no longer applies cleanly) and **likely superseded**: the branch already ships analysis-scope honesty (see the `Scope: analysing N% of the repo …` line emitted by `app/engine/health_score.py`). |
| `scope-honesty-WIP-stash1.patch` | An earlier snapshot of the same scope-honesty work (~318 lines, same 7 files). | Same — stale / superseded. |

## How to inspect / recover (if ever wanted)
```bash
git apply --check docs/wip/scope-honesty-WIP-stash0.patch   # will report conflicts (stale)
git apply --3way  docs/wip/scope-honesty-WIP-stash0.patch   # attempt a 3-way merge
# or just read the patch for the ideas; re-implement cleanly on top of current HEAD
```

## North-Star note
This is **reporting / scope-honesty** machinery — the *safety/honesty* surface the
mission says NOT to lead with (`CLAUDE.md`). Parking it as a patch (rather than
activating stale code) preserves it without letting it drift into the active
develop core. Resurrect only if a concrete, buyer-visible need appears — and
re-implement against current HEAD, since these no longer apply.
