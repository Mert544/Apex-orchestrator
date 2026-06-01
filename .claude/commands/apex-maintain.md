---
description: Run Apex's guarded autonomous maintenance — scan, generate fixes, apply (test-verified, auto-rollback on failure), and report. Use when asked to clean up / harden / auto-fix a project's code safely.
argument-hint: "[dry-run|supervised|autonomous] (default: dry-run)"
allowed-tools: Bash
---

Run Apex's maintenance pipeline on the repository. **Default to a dry run** so the user
sees the diffs before anything changes.

Mode requested: `$ARGUMENTS` (treat empty as `dry-run`).

Pick the matching invocation:

- **dry-run** (default, changes nothing — preview every fix as a diff):
  ```!
  python -m app.cli maintain --target=. --dry-run
  ```
- For **supervised** (apply test-verified fixes, no commits) run:
  `python -m app.cli maintain --target=. --mode=supervised`
- For **autonomous** (apply + verify + commit each fix) run:
  `python -m app.cli maintain --target=. --mode=autonomous --commit --out=MAINT.md`

Guidance:
1. Always start with the dry run above and show the user the proposed diffs.
2. Only run supervised/autonomous if the user explicitly asks to apply changes.
3. Every applied fix is verified against the test suite and **auto-rolled-back if tests fail**, so a run can't leave the project broken — but still summarize what was applied / rolled back / blocked.
4. In autonomous mode, report the per-step commit hashes from the Markdown report.
