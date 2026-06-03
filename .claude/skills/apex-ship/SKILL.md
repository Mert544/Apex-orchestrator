---
name: apex-ship
description: The Apex change-shipping discipline — how to verify, lint, commit, and push a change in this repo correctly and cheaply. Trigger before committing or pushing Apex work, or when unsure about the test/lint/branch/commit conventions here.
allowed-tools: Bash, Read
---

# Shipping a change in Apex (the house rules)

Follow this for every change so velocity stays high and the branch stays green.

## Verify ladder (cheap → thorough)

1. **While iterating:** only the directly relevant test files
   (`python -m pytest tests/test_x.py tests/test_y.py -q`). The full suite every turn is
   the biggest budget sink — don't.
2. **Lint:** `ruff check app/` (and any test files you added). Config: `select E,F,W`;
   `ignore E402,E501,E741`. Must be clean — CI runs lint as a gate.
3. **Before any commit that spans modules or touches a core/shared module:** run the full
   suite once — `python -m pytest -q`. State the real pass count.

If a test fails, report it honestly with the output; never paper over it. If a change
surfaced a real bug, fix the bug and add a regression test rather than loosening the test.

## Commit

- GPG signing is disabled for machine commits — **always** use:
  `git -c commit.gpgsign=false commit -m "<message>"`.
- Message style: imperative summary with the concrete delta
  (`Cover cli.py main() dispatch (40% -> 72%)`, `Fix ActionExecutor crash on None old_code`).
  Lead with a real bug fix when there is one. No model identifiers anywhere in the message.
- Group related edits into one logical commit; keep unrelated changes separate.

## Branch & push

- Develop on the designated feature branch (here: `claude/apex-orchestrator-eZbJO`).
  Create it locally if missing; never push to a different branch without explicit OK.
- Push with retries on network errors only (exponential backoff 2/4/8/16s):
  `git push -u origin <branch>`.
- Do **not** open a PR unless explicitly asked. Once a PR exists and you're subscribed to
  its activity, drive CI to green and address review comments per the harness rules.

## Parallelism (when speed matters)

For independent work, spawn agents (see the `apex-test-writer` / `apex-engineer` subagents)
on **disjoint file sets** so they never conflict — or give a coding agent
`isolation: worktree` and integrate its branch afterward (`git worktree list`,
then merge/cherry-pick onto the feature branch, then run the full suite).
