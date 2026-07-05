# Test-surface audit — genuine value vs. inflation (2026-07)

> **Report-only.** This is an honest, evidence-based map of the machine-generated
> test surface. It recommends *no* bulk deletion — it separates the parts that
> carry real regression value (keep) from a bounded, verified inflation core, so
> the owner can decide what to consolidate. Method: two multi-agent workflows
> (10 high-effort reviewers), with the strongest claim confirmed by a **live
> experiment**, not just reasoning.

## Headline

The mutation-hardened **core is genuine**: deep-mutation pins that exercise real
branch/boundary logic, the boundary/off-by-one gate tests, the source-rewriting
landers, and the mutation harness itself all deliver **proportional regression
value**. Layered on top is a **bounded, identifiable inflation core** — ~10,100
LOC of permanently-unfalsifiable tests plus a few hundred LOC of copy-paste pins
— whose real cost is **maintenance-surface and reader trust, not CI time**.

A blanket "40% of the tests are inflation" was too harsh. The truth is narrower
and sharper: a *specific, provable* ~10.3k-LOC layer is ceremony; the rest of the
machine surface mostly earns its keep.

## What is genuine value — keep as-is

- **Deep-mutation pins that call real functions** (the majority of that tier,
  e.g. `test_bridge_seeder_deep_mutation_eyml.py` — zero mocks, asserts business
  rules against real objects). A refactor that broke a cap/sort/dedup constant
  *would* be caught.
- **Boundary / off-by-one / exact-value gates** (e.g. `_gate_eval_oos_boundary`
  pinning `<= 9.0%` vs `10.0%` and the exact detail string) — falsifiable,
  targeting operator-direction bugs the core's directional checks structurally
  miss.
- **Source-rewriting / `near_dup` lander tests** — they mutate real source and
  assert on the *transformation output*, with a track record of catching real
  regressions in a tool that rewrites production Python.
- **The mutation-testing harness/methodology** (`app/engine/mutation_tester.py`)
  — a real AST fault-injection engine with a baseline-green guard, deterministic
  budget, and explicit equivalent-mutant bookkeeping. Sound infrastructure; the
  inflation is in specific *artifacts built on top*, not the method.

## The inflation core — verified magnitudes

### 1. Unfalsifiable `git show HEAD:` characterization tests — 54 files, ~10,100 LOC
These load a module's source from **bare git HEAD**, `exec` it as a throwaway
"original", and assert current behavior matches it byte-for-byte. On a clean
checkout `HEAD == working tree`, so the two copies are **identical source** —
the assertion is a tautology. They can only fail in the brief pre-commit window
during the very refactor they were written to validate; **after merge they can
never fail again.**

**Proven by live experiment** (fully cleaned up afterward, repo untouched):
1. Injected a real behavior change in the working tree (uncommitted) →
   `2/18 tests FAILED` (the mechanism works pre-commit).
2. Made the *identical* change on a throwaway branch and **committed** it
   (HEAD == working tree, i.e. post-merge) → `18/18 PASSED`. The same bug became
   invisible the instant it was committed.

The fix pattern already exists in the repo: 2 files
(`test_param_add_byte_identical.py`, `test_dedup_finalize_helper_byte_identical_eyml1y.py`)
walk `git log` back to a genuine pre-refactor commit by content marker, so they
stay falsifiable no matter how many commits land on top. The other 54 don't.

### 2. Copy-paste routing-table pins — ~170 LOC
`test_bridge_seeder_deep_mutation_eyml.py:1069-1248` hand-transcribes
`_OPERATOR_ACTIONS` (8 rows) and `_FACT_ACTIONS` (74 rows) verbatim into
`_OP_EXPECTED`/`_FACT_EXPECTED`, then asserts equality. Its real job is "did you
edit both copies" — commit `22db31b` literally restored a row a cherry-pick had
dropped from this pin. The `config` row is duplicated 3×. Not independent
verification; a mirror.

### 3. Mechanical integer pin-sweep — 27 files
27 near-identical files each assert the single global fact
`available_objectives() == 98`, all bumped `97 → 98` in one commit alongside
unrelated changes. 27 assertions, one fact, ~zero distinguishing power.

**Shared defect shape:** each of the three re-encodes a *static fact from
production* (a snapshot, a table, a count) and compares it **to itself**, instead
of exercising behavior through inputs and observed outputs. That is the
signature of test-count inflation — impressive numbers, little independent
protection.

## Cost verdict

The cost is **maintenance-surface and clarity/trust, not CI time.** Collection is
cheap (27,015 tests / 5.6s) and most machine tests are fast (270-850 tests/sec
sampled). The real taxes:
- **Reader trust:** 10k LOC of tests that *cannot fail* dilute the meaning of a
  green suite and of the "17,500-test, mutation-tested" claim.
- **Maintenance drift:** 228 files use `monkeypatch.setattr` (1413 sites, 142
  distinct `app.*` targets); 54 define hand-rolled `_Fake*` classes. A single
  1-param addition to a widely-mocked function breaks ~dozens of mock signatures
  by hand — **this session hit exactly that** (the `apex pulse` fix broke a fake
  engine `__init__` and several `grade=` lambda mocks that the static consensus
  had judged safe; only the empirical run caught it).
- Not universally free at runtime: a few files are slow (one took 43.9s for 46
  tests); worth profiling separately.

## Recommendations (report-only, ranked)

1. **Highest value / cheapest:** convert the 54 bare-HEAD characterization files
   (10,100 LOC) to the git-log walk-back pattern the 2 correct files already use
   (pin to the genuine pre-refactor base commit), OR retire them if the refactor
   they proved is long merged. Either restores falsifiability or removes dead
   ceremony.
2. Collapse the 27-file `== 98` sweep into **one** canonical objective-count test.
3. Replace the `_FACT_EXPECTED`/`_OP_EXPECTED` dict-copy with a few behavioral
   spot-checks via `bridge.plan_idea(...)` (independent verification, not a
   mirror).
4. Treat the **mock-signature maintenance tax** as its own separate audit — it
   spans machine (89 files) *and* hand-written (139 files) tests roughly evenly,
   so it is not a "machine-test" problem to fold into this cleanup.
5. **Leave the genuine core untouched** — the deep-mutation pins, the `near_dup`
   lander, the boundary/exact-value gates. The live experiment (a committed
   regression that *only* the collapsed HEAD-diff tier missed) shows the honest
   core does its job.

## Honest caveats

- The "82% of characterization LOC" figure from the first pass **could not be
  independently reproduced** (the denominator's definition is ambiguous). The
  **absolute** magnitude — 54 files / ~10,100 LOC — is confirmed almost exactly.
- Surface facts (file/commit counts, shapes) were re-verified independently via
  `grep`/`git show`; a small (~5%) file-count discrepancy between passes is
  likely repo drift or differing globs.
- No files were modified during this audit; the working tree was clean before
  and after every experiment.

## Why this matters for the identity

Apex is a **project-development cell**, not a security tool — its test surface
should protect *real development behavior* (does an idea land the right fix? does
a transform preserve semantics?), which the genuine core does well. Ceremony that
re-asserts static facts against themselves inflates the count without protecting
behavior, and — worse — dilutes the trust foundation Apex sells. Consolidating
the inflation core makes the green suite *mean* more, not less.
