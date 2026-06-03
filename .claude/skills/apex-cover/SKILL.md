---
name: apex-cover
description: Raise test coverage of a specific Apex module the established, cost-aware way — measure missing lines, write tests that match the repo's patterns, verify with targeted runs, then full suite before commit. Trigger when asked to "cover", "add tests for", or "raise coverage of" a module, or to harden a weak/low-coverage area.
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Apex coverage workflow (fast, cost-aware)

A repeatable recipe for raising a module's test coverage without burning the Claude
budget. The discipline: **targeted measurement → pattern-matched tests → targeted verify →
full suite only before commit.**

## 1. Measure the gap (targeted, cheap)

```bash
python -m pytest <relevant test files> --cov=app.the.module --cov-report=term-missing -q
```

Use the dotted module path (`app.engine.idea_roadmap`), never a file path, or coverage
reports "module never imported". Read the `Missing` line ranges — those are your targets.
Open the module and map each missing range to a behavior (a branch, an error path, a
boundary, an early return).

## 2. Write tests that look like the neighbors

- Read 1–2 existing tests for the module (or a sibling) and **match their style**: fixture
  names (`tmp_path`, `capsys`, `monkeypatch`), import placement, naming, assertion density.
- Prefer real behavior over mocks; mock only true externals (network, servers,
  `subprocess.run`, server `serve_forever` → raise `KeyboardInterrupt`).
- One behavior per test; name it after the behavior. Cover the **edge/error** paths the
  Missing ranges point to — that's where the coverage (and real bugs) hide.
- Tests frequently surface real bugs. If a test exposes one, **fix the bug** (don't weaken
  the test); add a regression test and note it in the commit.

## 3. Verify targeted, then full

```bash
python -m pytest tests/test_<module>.py -q            # iterate here
ruff check app/ tests/test_<module>.py                # E/F/W; ignores E402/E501/E741
python -m pytest tests/test_<module>.py --cov=app.the.module --cov-report=term-missing -q
```

Only run the **full** suite (`python -m pytest -q`) once, right before committing —
especially if you touched a shared/core module. Iterating with the full suite is the main
budget sink; avoid it.

## 4. Commit (see the apex-ship skill for the exact discipline)

Commit message states the coverage delta, e.g.
`Cover idea_roadmap edge paths (62% -> 91%)`. If a real bug was fixed, lead with that.

## Notes specific to this repo
- ruff config: `select E,F,W`; `ignore E402,E501,E741`. CI lints `app/` only, but keep new
  test files clean too (no unused imports / f-strings-without-placeholders).
- Test isolation for target-project runs: `RunTestsSkill` sets PYTHONPATH to the target root.
- Determinism: never assert on timestamps or unordered set ordering.
