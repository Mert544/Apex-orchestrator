# Third external-project proof — Apex `develop` on `inflection` (2026-07-07)

> **Why a third.** Two independent proofs already exist (`python-slugify`, `humanize`).
> This one is short and deliberate: it lands on a THIRD independent package **and** it
> exercises the OTHER branch of the wire-exports fix — the complement to humanize. humanize
> has a hand-curated `__all__`, so the corrected transform must NOT widen it (it no-ops).
> `inflection` has NO `__all__`, so the transform must PIN a complete one. Both behaviours,
> on someone else's code, verified.

## Target

- **Project:** [`inflection`](https://pypi.org/project/inflection/) 0.5.1 — an independent,
  MIT-licensed, zero-dependency OSS Python package (string singularize/pluralize/camelize).
  Fetched via `pip download --no-binary :all: inflection` (GitHub is network-blocked in this
  environment; pypi is reachable).
- **Baseline:** its own `test_inflection.py`, **455 tests**, green before the run.
- **Apex mode:** `apex develop --target <inflection> session --apply` — zero-token, offline,
  deterministic.

## What Apex LANDED

`.apex/proof-of-fix.json`: **1 move applied, 0 rolled back, verified** (`strength=module`).

| Move | Target | Verified | Strength |
|---|---|---|---|
| `wire-exports` | `inflection/__init__.py` | ✅ | module |

`inflection/__init__.py` declared **no** `__all__`, so wire-exports pinned a complete,
sorted one from the package's genuine public surface:

```python
__all__ = [
    "PLURALS", "SINGULARS", "UNCOUNTABLES",
    "camelize", "dasherize", "humanize", "ordinal", "ordinalize",
    "parameterize", "pluralize", "singularize", "tableize",
    "titleize", "transliterate", "underscore",
]
```

Every name is a real public export (the 12 documented functions plus the three public
rule-table constants). No leading-underscore internals, no `TYPE_CHECKING` sentinel — the
corrected collector's exclusions hold on external code.

## Independent verification

Running `inflection`'s **own 455-test suite against Apex's modified tree**:

```
455 passed in 0.32s
```

Correct and behaviour-preserving on a third independent project.

## The point — both wire-exports branches proven on external code

- **`humanize`** (curated `__all__`): the corrected transform **respects** it — a clean
  no-op, no internals leaked. (`external-proof-humanize.md`)
- **`inflection`** (no `__all__`): the transform **pins a complete** one — the primary use
  case, unchanged and correct here.

Three independent external proofs now exist (slugify, humanize, inflection); the last two
are test-verified, and together they demonstrate the wire-exports capability doing the right
thing whether or not the maintainer curated their exports.

**Reproduce:** `pip download --no-binary :all: inflection && tar xzf inflection-*.tar.gz`,
then from the Apex repo `PYTHONPATH=<inflection> python -m app.cli develop --target
<inflection> session --apply`; inspect the diff and re-run
`PYTHONPATH=<inflection> python -m pytest <inflection>/test_inflection.py` (expect 455 passed).
