# The living cell's JS/TS hands are real — verified (2026-07-07)

> **Correcting a misconception.** A big-picture pass framed "polyglot" as a from-scratch
> build ("give the cell JS hands — it only profiles JS today"). That was **wrong**.
> Apex already **lands verified JavaScript/TypeScript code**, through the same
> never-fake-green discipline as its Python hands. This file records the evidence so no
> future session re-derives it.

## What exists (not vaporware)

- **A real TS driver.** `app/execution/js/ts_driver.js` (84 KB) is a Node program that
  `require("typescript")` and speaks canonical JSON to the Python side
  (`app/execution/js/js_tool.py`). Verified live this session: `apex js-scope --target
  <a TS project>` parsed a real `.ts` module via the driver (Node 22 + typescript on
  `NODE_PATH`), zero tokens.
- **Seven registered JS objectives**, all in the north-star CONCRETE bucket:
  `js-tdd-implement`, `js-cover-gaps`, `js-wire-exports`, `js-strengthen-tests`,
  `js-implement-from-jsdoc`, `js-document-param-types`, `js-document-returns-inferred`.
  Live this session: `apex develop --objective js-document-param-types` found a real
  JSDoc move on a TS module.
- **Never-fake-green extends to JS — with extra rigor.** `app/execution/js/js_gate.py`
  is a **FORCED jest gate**: the two body-landing objectives accept a synthesized body
  *only if a throwaway copy's jest suite goes green* AND there is **positive-execution
  proof** jest actually ran ≥1 test (a bare exit-0 / "no tests found" is rejected). It
  explicitly forces `npm test`=jest so that on a mixed Python+JS repo pytest can never
  substitute and fake-green a wrong JS body. This is *more* defensive than the Python
  path, for a real cross-language failure mode.
- **Coverage-aware honesty on JS.** Live this session, a JS JSDoc move on a module with
  no linked JS test was flagged `⚠ no-suite` and the apply path **refused to land it**
  unverified — the same honest under-claim the Python path makes.

## Internal proof (green in every gate this session)

`app/execution/js/` is covered by **12 JS test files** — one per objective plus the
gate and driver:

```
python -m pytest tests/test_js_tdd_implement_objective_eyml.py \
  tests/test_js_gate_forced_eyml.py tests/test_js_cover_gaps_objective_eyml.py -q
→ 86 passed
```

`test_js_gate_forced_eyml.py` is the load-bearing one: it pins that the jest gate
refuses a vacuous/pytest-substituted run — i.e. that a wrong JS body **cannot** land
stamped-verified. `test_js_tdd_implement_objective_eyml.py` proves a JS stub is filled
and jest-verified end to end. These are part of the ~20k-test full-green gate, so the
verified-JS-landing capability is not merely wired — it is **continuously proven**.

## What's genuinely left (scoped, not a capability gap)

The one thing NOT yet shown is the **external showcase** — the JS analog of
`docs/rnd/external-proof-python-slugify.md`: clone a real OSS JS/TS package with a jest
suite, run `apex develop --objective js-tdd-implement` (or `js-cover-gaps`), and show
the verified diff + proof ledger on someone else's code. That needs a jest project set
up (npm install), which is a focused run — **a demonstration, not a build.** The hands
work; they just haven't been filmed lifting a stranger's box yet.

## Bottom line

Apex is **not** a Python-only engine that merely reads JS. It has working, wired,
honestly-gated, internally-verified JS/TS hands. The "polyglot" frontier is therefore
about *demonstration and reach*, not construction.
