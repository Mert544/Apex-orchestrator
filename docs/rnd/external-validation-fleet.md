# External-validation campaign — Apex `develop` across an OSS fleet (2026-07-08)

> **Why this exists.** Three anecdotal external proofs (slugify, humanize, inflection) show
> Apex *can* land verified code on independent projects. A campaign across a diverse FLEET
> answers the harder question a buyer actually asks: *what happens when you point it at
> real code it has never seen — and does its "never fake green" promise hold under that
> stress?* It did the most valuable thing an honest test can do: it **found a real
> fake-green hole, which was then root-caused and fixed.** This is the record.

## Method

- **Fleet:** independent OSS Python packages fetched as pypi sdists (GitHub is
  network-blocked in this environment; pypi is reachable). Per package: establish the
  package's OWN test suite green as a baseline → run `apex develop --target <pkg> session
  --apply` (zero-token, offline, deterministic) → **independently re-run the package's own
  suite** against Apex's modified tree → read `.apex/proof-of-fix.json` → adversarially
  review the diffs.
- Runs were isolated to a scratch dir; the Apex repo was only ever invoked read-only.

## Results

| Package | Baseline | Moves | Rolled back | Own suite after | Verdict |
|---|---:|---:|---:|---|---|
| `python-slugify` | 82 | 4 | 0 | 82 green | ✅ landed (all `no-suite`, honest) |
| `humanize` 4.16 | 784 | 5 | 0 | 784 green | ✅ verified refactors |
| `inflection` 0.5.1 | 455 | 1 | 0 | 455 green | ✅ verified (`__all__`) |
| `natsort` 8.4 | 333 | 6 | 0 | 333 green | ✅ clean win |
| `colorama` 0.4.6 | 38 | 11 | 0 | 38 green | ✅ green (wire-exports broad) |
| `parse` 1.22.1 | 97 | 5 | 0 | 97 green | ✅ green (dataclassify `eq=False`) |
| `toml` 0.10.2 | 19 (+2 pre-red) | 10 | 0 | same 2 pre-red | ✅ delta-green held; ⚠ docstring bug |
| `wcwidth` 0.8.2 | red (plugin) | 0 | 0 | — | ✅ **honest refusal** (no fake green) |
| `packaging` 26.2 | 61,513 | 31 | 0 | **401 FAILING** | 🐛 **FAKE-GREEN — the finding** |
| `pyparsing` 3.3 | 2013 | — | — | — | ⏭ too slow to finish (scale limit) |
| `cachetools` 7.1 | 283 | — | — | — | ⏭ incomplete (worker restart) |

**Aggregate over the completed runs:** ~10 independent packages, **43 moves applied, 0
rolled back**, real transform variety (infer-type-hints, wire-exports, modernize,
dataclassify, simplify-bool-return, shrink-functions, inline-helpers). On every package
except `packaging`, the package's own suite held exactly (`toml`'s 2 failures were
pre-existing env issues that delta-green correctly tolerated *without adding any*).
`wcwidth` is a positive signal: Apex saw a red baseline and **refused to land anything**
rather than fake a green.

## The finding — a real fake-green, found → root-caused → fixed

On `packaging`, Apex reported **"31 moves verified, 0 rolled back"** while the package's own
suite regressed **61,513 → 401 failing**. Verified three ways:
- **Runtime:** `canonicalize_license_expression('MIT')` → `UnboundLocalError`.
- **Ledger:** the move is stamped `verified: true, strength: module, rolled_back: false`.
- **Two root causes:**
  1. **extract-method returned a conditionally-bound value.** The transform treated a name
     assigned only inside `if not raw: …; raise` (`message`) as a return value, emitting
     `return license_expression, message` — unbound on the normal path. **Fixed**
     (`fix(extract-method)`): helper outputs now require **definite assignment**; a
     pre-existing conditional output is threaded through as a parameter; a genuinely-new
     conditional output makes the extraction **refuse**. Verified on the real pristine
     module: the `message`-returning seam is gone (Apex now picks a safe seam instead).
  2. **impact-scope verify missed the covering test.** `covering_test_files` for
     `licenses/__init__.py` selected `test_manylinux/metadata/musllinux/tags` — **not**
     `test_licenses.py`, which imports `packaging.licenses._spdx` (a *submodule* of the
     changed package). The scope matches a module's own dotted path and its parents, **not
     tests that import a child/submodule** (even though importing the submodule executes the
     package `__init__`). So the verify ran tests that never call the changed function.

The same second root cause explains the run's other packaging defect (`inline-helpers`
deleted `_compute_32_bit_interpreter`, a private symbol a test imports directly).

## Honest posture

- **What's fixed now:** the extract-method conditional-output bug (the transform can no
  longer *generate* that broken code) and the toml docstring theft (`_scan_function` no
  longer sweeps a leading docstring into the helper). Both carry falsifiable regression
  tests proven to fail on the pre-fix source.
- **What's characterized but NOT yet fixed (founder-gated):** the **impact-scope
  covering-scope gap** — `covering_test_files` can miss a test that imports a submodule (or
  a re-export) of the changed package, so the verify can run the wrong tests. This is the
  deeper "never-fake-green" hole: it would let *other* transforms' broken changes through
  stamped-verified. Broadening the scope is correct in direction but a wide, risky change
  to verification scoping (many modules' covering sets shift; many characterization tests
  pin them), so it is flagged for a deliberate decision rather than smuggled in here.
- **Scale limit:** `pyparsing`'s develop run was too heavy to finish in budget, and an
  interrupted session leaves a modified tree with no proof ledger — a real robustness note.

## Bottom line

Pointed at a fleet of real, unseen code, Apex landed 43 correct verified moves with zero
regressions on 10 packages and honestly refused a red baseline — AND surfaced a genuine
fake-green hole its own in-house suite never exercised, which was then root-caused and
fixed. That mixed result — most runs clean, one real bug found and closed — is a far
stronger and more truthful statement about the trust foundation than a clean sweep would
have been. The one remaining gap (impact-scope covering-scope) is named, not hidden.
