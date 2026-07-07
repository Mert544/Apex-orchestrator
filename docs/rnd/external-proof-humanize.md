# Second external-project proof — Apex `develop` on `humanize` (2026-07-07)

> **Why this file exists.** The prior external proof (`external-proof-python-slugify.md`)
> was a single independent project, and every move there landed `⚠ no-suite` (slugify
> keeps its tests in one flat `test.py`, so Apex's impact-scoped verifier could not tie a
> change to a test). A one-off with no test-verified move invites the fair skepticism
> "cherry-picked, and never actually verified on someone else's suite." This is a
> **second, independent** project with **module-linked tests**, so Apex produced
> genuinely **test-verified** moves — and, honestly, the run also surfaced a real bug in
> one of Apex's own transforms, which was then fixed. That mixed outcome is the record.

## Target

- **Project:** [`humanize`](https://pypi.org/project/humanize/) 4.16.0 — an independent,
  MIT/ISC-licensed OSS Python package (number/time/filesize/list humanization). **Not**
  Apex, not bundled.
- **How obtained:** `pip download --no-binary :all: humanize` (an sdist *with* its test
  suite). This environment's network policy blocks `github.com` (HTTP 403) but allows the
  package registries (`pypi.org`, `registry.npmjs.org`), so the sdist route is how an
  independent project is reachable here. *(This is also why the JS external showcase —
  which needs a GitHub jest project — is not achievable in this environment; a second
  Python proof is.)*
- **Baseline:** humanize's own suite, **784 tests**, green before the run (`freezegun` +
  `pytest-benchmark` installed; `PYTHONPATH=src`). An absolute-green baseline — so every
  kept move was verified against a fully-green suite, not delta-green.
- **Apex mode:** `apex develop --target <humanize> session --apply` — zero-token, offline,
  deterministic.

## What Apex LANDED — and it is test-VERIFIED this time (real diffs, not advice)

`.apex/proof-of-fix.json` (schema `apex-proof-of-fix`, tamper-evident): **5 moves applied,
0 rolled back, 0 blocked.** Unlike slugify, `verification.performed = true` on every move.

| Move | Target | Verified | Strength |
|---|---|---|---|
| `shrink-functions` | `filesize.py::naturalsize()` | ✅ | none¹ |
| `shrink-functions` | `number.py::metric()` | ✅ | module |
| `shrink-functions` | `number.py::fractional()` | ✅ | module |
| `shrink-functions` | `time.py::precisedelta()` | ✅ | module |
| `wire-exports` | `__init__.py` | ✅ | module | ⚠ **see "the bug" below** |

¹ `none` = the green suite ran but Apex could not tie a test to the *changed function*
specifically, so it honestly under-graded the strength rather than claim "function"-level
proof. `module` = a green suite that imports the changed module vouches for it.

Sample — a genuine, behavior-preserving extraction Apex performed on external code
(`humanize/filesize.py`), lifting the suffix/base computation out of `naturalsize()`:

```python
def extracted_naturalsize_part(binary, gnu, value):
    if gnu:
        suffix = suffixes["gnu"]
    elif binary:
        suffix = suffixes["binary"]
    else:
        suffix = suffixes["decimal"]
    base = 1024 if (gnu or binary) else 1000
    bytes_ = float(value)
    return base, bytes_, suffix
# ...and naturalsize() now calls it instead of inlining the block.
```

## Independent verification (the proof, not a footnote)

Running humanize's **own 784-test suite against Apex's modified tree**:

```
784 passed in 5.13s
```

So the diffs Apex landed are correct and behavior-preserving on an independent project —
and here, unlike slugify, they were **test-verified during the run** (the module-linked
suite gated each move), then **independently re-confirmed** by the full suite. This is the
stronger form of the buyer-visible artifact the North Star asks for.

## The bug this run found — and Apex fixed (the honest part, not buried)

The `wire-exports` move was `verified` (the 784 tests stayed green) but the diff was
**wrong**: humanize ships a hand-curated `__all__` that deliberately excludes internals,
and Apex **appended a second `__all__`** — leaving the first dead and leaking internals
(`TYPE_CHECKING = False`, `Unit`, `suffixes`, `powers`, …) into the public API. It passed
the gate only because humanize has no test that pins `__all__`.

This is exactly the value of running on independent code: it exposed a real defect the
in-house suite never would. Two parts, handled differently and honestly:

- **Fixed now — the duplicate `__all__`** (`fix(wire-exports)`): `render_init_source` built
  its header from the whole existing `__init__` (including the old `__all__`) and then
  appended a freshly-merged one → two top-level `__all__` bindings on *any* package that
  already had one plus a new export. Root-caused, fixed (`_strip_top_level_all` removes the
  old before emitting the merged superset — no names lost), and pinned with a falsifiable
  regression test proven to fail on the old code. Verified on humanize's real
  `__init__.py`: now exactly **one** `__all__`.
- **Flagged for a founder call — the over-export.** Even with a single `__all__`,
  wire-exports still *widens* a deliberately-narrow curated `__all__` with every public
  sibling symbol (incl. non-API idioms like `TYPE_CHECKING = False`). Whether the transform
  should defer to an explicit curated `__all__` (respect maintainer intent) or pin a
  complete one (its current design) is a philosophy decision, left deliberate rather than
  smuggled into a bugfix.

## Conclusion

On a **second** independent OSS project, with zero tokens, Apex: read the code, landed **4
correct, test-verified, behavior-preserving refactors** (784-test suite green), and — on
the 5th move — surfaced a **real bug in its own transform**, which was root-caused, fixed,
and regression-tested. Two independent external proofs now exist (slugify + humanize), and
this one is *test-verified*, not just conservatively under-claimed. The honest posture
holds in both directions: Apex under-claimed strength where it couldn't prove more, and the
one over-claim (a green-but-wrong `wire-exports`) became a fix rather than a hidden footnote.

**Reproduce:** `pip download --no-binary :all: humanize && tar xzf humanize-*.tar.gz`,
`pip install freezegun pytest-benchmark`, then from the Apex repo
`PYTHONPATH=<humanize>/src python -m app.cli develop --target <humanize> session --apply`;
inspect `<humanize>/.apex/proof-of-fix.json` and re-run
`PYTHONPATH=<humanize>/src python -m pytest <humanize>` (expect 784 passed).
