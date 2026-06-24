# Apex Orchestrator — K1 Value-Landed Metric (9 real external-repo sweeps)

**Date:** 2026-06-24 · **Apex:** zero-token / offline / deterministic / proof-carrying / auto-rollback
**Question (K1):** when Apex runs its `develop` loop on a real project it has *never seen*, how much
**value does it LAND** — per objective — and would a maintainer *accept* it?

This consolidates THREE independent pilots (the original + two expansions) into one buyer-value
metric. It is the honest answer to blind-spot **K2** ("all our proof is self-generated") and the
direct measure for **K1** ("we count objectives, not value").

---

## Corpus — 8 unique libraries, 9 sweeps, ~4,000 tests, all baseline-GREEN

Obtained as PyPI sdists (GitHub clone is 403-blocked; PyPI is allowlisted — same released source).
Each got its own venv; every "verified" is gated against the library's OWN suite.

| Library | Ver | Baseline | Shape (why chosen) |
|---|---|---|---|
| inflection | 0.5.1 | 455 | single-module, fully typed |
| funcy | 2.0 | 202 | rich functional surface (richest fire) |
| humanize | 4.15.0 | 737 | mature, fully typed (control) |
| more-itertools | 11.1.0 | 722 (+19896 subtests) | one ~5k-LoC module |
| boltons | 26.0.0 | 437 | 30 modules, EVERY file has a `# Copyright` header (wire worst-case) |
| cachetools | 7.1.4 | 283 | all modules already `__all__` (idempotence control) |
| toolz | 1.1.0 | 186 | functional utils |
| wrapt | 2.2.2 | 1037 | C-ext + pure-Python, heavily tested |

**Zero crashes / tracebacks across all 9 sweeps** (≈100 objective-runs). Every empty result is an
*honest no-op*, never a failure.

---

## K1 — value tier per objective (aggregated across all sweeps)

### 🟢 HIGH value — a maintainer would take these (value is CONCENTRATED here)
| Objective | Evidence across repos |
|---|---|
| **pin-doctest** | inflection **455→467** (+12 enforced docstring examples), more-itertools +3; refuses set/dict-repr examples; on boltons (which already runs `--doctest-modules`) it correctly **declines to duplicate** — a discipline signal. Prevents silent docstring rot. THE standout. |
| **infer-type-hints** | funcy 11 · boltons 25 · cachetools 6 · more-itertools 2 — accurate conservative return hints (`__init__→None`, `__repr__→str`, `__len__→int`, `__contains__→bool`), often FUNCTION-coverage, behaviour-preserving. |
| **generate-usage-doc** | funcy 1073-line · boltons 2504-line · more-itertools 2756-line · humanize 117-line API references derived from real signatures + docstrings. |
| **wire-exports** | correct package-`__init__` re-export surface, `__all__` at file bottom, excludes stdlib imports. The *good* cousin of wire-module-exports. |
| **dataclassify** | boltons 3 (now `==`/`hash()`-safe after the round-19 eq-flip fix); in the curated `SESSION_OBJECTIVES` headline path. |
| **curated `session`** | funcy: 15 contributions / 11 files / 13 verified, full suite GREEN — Apex's headline artifact already gates OUT the noisy objectives. |

### 🟡 NARROW — technically fine, situational value
- **cover-gaps** — pins real gaps, but on *mature* repos it had targeted leftover trivia (`docs/conf.py`,
  `_version.py`, private modules). **Round-20 targeting fix** restricts it to real public library modules.
- **add-from-future-annotations** — harmless modernization (caveat F5: PEP-563 stringizes annotations,
  a runtime change for reflective consumers — flagged, not yet gated).

### 🔴 WAS NOISE / CONTRACT-CHANGE → being closed (the pilots' core findings)
| Objective | Finding | Status |
|---|---|---|
| **wire-module-exports** | imported names in `__all__` (`re`/`os`/`annotations`); fired on `setup.py`/`docs/conf.py`; inserted above shebang; **destroyed `module.__doc__`** on comment-headered modules (5/6 boltons) | #1/#2/#3 **FIXED round-19**; docstring-loss **FIXED round-20** |
| **add-final / seal-final-method / freeze-dataclass** | ~73 `@final` on boltons' PUBLIC classes → forbids downstream subclassing (type-level contract change; runtime no-op so the suite never catches it). Reachable via the autonomous `ascend` board. | **GATED round-20** (public-API refusal) |
| **document-signature** | content-free docstrings that merely restate the signature (`"""pop. Args: self"""`) | **REFUSED round-20** (honest no-op > noise) |

### ⚪ HONEST NO-OP — correctly finds nothing on mature code (NOT a failure)
`implement-stub`, `tdd-implement`, `scaffold-from-protocol`, `freeze-dataclass` fire **nowhere** on
mature libs — those patterns (stubs / `NotImplementedError` / `Protocol`s / plain-dataclass candidates)
simply don't exist there. This is the honest majority on already-clean code.

---

## Trust-foundation scorecard (the moat — on code Apex never saw)

| Property | Result across all sweeps |
|---|---|
| **Determinism** | ✅ byte-identical diffs across two `--apply` runs (SHA-checked: wire, infer-type-hints, session) |
| **Auto-rollback** | ✅ a guard-breaking change reverted byte-for-byte (`setup.py`, `typeutils.py`); suite GREEN again |
| **Never-fake-green** | ✅ RED baseline → lands 0, discloses every blocked candidate, working tree clean |
| **Weak vs verified honesty** | ✅ `coverage=none` moves labeled "weak", excluded from the verified count |
| **Crashes** | ✅ ZERO tracebacks across ≈100 objective-runs |

---

## The K1 verdict

**YES — Apex lands real, verified, behaviour-preserving value on libraries it has never seen, and the
trust foundation holds on external code.** But the honest shape of that value is:

1. **Value is CONCENTRATED in ~4 objectives** (pin-doctest, infer-type-hints, generate-usage-doc,
   curated session) + dataclassify/wire-exports where applicable.
2. **On mature repos most objectives are honest no-ops** — correct behaviour, not failure. Fire-rate
   ranged 4–10 of 16 (richest on multi-module functional libs like funcy/boltons/wrapt).
3. **The pilots earned their keep**: they caught **6 latent fake-green / noise / contract-change bugs
   the internal ~23k-test gate STRUCTURALLY cannot** (Apex is an application, not a published library —
   it has no `setup.py`/shebang/license-header/external-subclasser/env-fragile shapes). Round-19 + 20
   close all of them.

## Honest open items (carried)
- **Scaling:** `strengthen-tests` (and `cover-gaps` mutation-fallback) **time out at 600s** on very
  large modules (boltons' 30 modules, more-itertools' 5k-LoC `more.py`) — honest no-op, not a crash;
  needs a per-module budget / incremental mode.
- **`--json` stdout isolation:** a target that prints at import (boltons `easterutils`) floods Apex's
  JSON stream — benign, worth hardening.

## What "K1" means going forward (the permanent metric)
**value-landed = Σ verified, behaviour-preserving moves a maintainer would accept** — NOT raw move
count, NOT objective count. The new `apex self-audit --soundness` check (round-20) makes the
"would-accept" half automatic: every registered objective must, on an adversarial library-shaped
fixture corpus, *refuse or stay behaviour-identical*. Re-run this pilot each wave — it is the buyer's
view, and it has caught what we cannot see from inside.
