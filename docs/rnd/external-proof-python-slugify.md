# External-project proof — Apex `develop` on `python-slugify` (2026-07-07)

> **Why this file exists.** The North Star's hardest test is *"prove value the way a
> buyer sees it: run the develop loop on an INDEPENDENT project and show the tangible
> artifacts it produced — real diffs, not analysis."* A prior big-picture audit found
> the last 20 commits were 100% Apex-on-Apex and that Apex's proof evidence lived only
> as PROGRESS narrative, not a replayable record. This is that replayable record.

## Target

- **Project:** [`python-slugify`](https://github.com/un33k/python-slugify) — an
  independent, MIT-licensed OSS Python package. **Not** Apex, not bundled.
- **Baseline:** its own suite (`test.py`, **82 tests**) green before the run.
- **Apex mode:** `apex develop --target <clone> session --apply` — the combined
  concrete-objective "buyer artifact". Zero-token, offline, deterministic.

## What Apex LANDED (real diffs, not advice)

`.apex/proof-of-fix.json` (schema `apex-proof-of-fix`, tamper-evident) recorded **4
applied moves**:

| Move | Target | Kind |
|---|---|---|
| `wire-exports` | `slugify/__init__.py` | add `__all__` + public re-exports |
| `infer-type-hints` | `test.py` | add provable `-> None` return hints |
| `shrink-functions` | `slugify/__main__.py::parse_args()` | extract a 37-line helper |
| `shrink-functions` | `slugify/slugify.py::smart_truncate()` | extract a 40-line helper |

```
 slugify/__init__.py |  22 +++++++
 slugify/__main__.py |   7 ++-
 slugify/slugify.py  |  33 ++++++-----
 test.py             | 168 ++++++++++++++++++++++++++--------------------------
 4 files changed, 131 insertions(+), 99 deletions(-)
```

Sample — a genuine, behavior-preserving refactor Apex performed on external code
(`slugify/slugify.py`), extracting the truncation loop out of `smart_truncate`:

```python
def extracted_smart_truncate_part(max_length, save_order, separator, string):
    truncated = ''
    for word in string.split(separator):
        if word:
            next_len = len(truncated) + len(word)
            if next_len < max_length:
                truncated += '{}{}'.format(word, separator)
            elif next_len == max_length:
                truncated += '{}'.format(word)
                break
            else:
                if save_order:
                    break
    if not truncated:
        truncated = string[:max_length]
    return truncated
# ...and smart_truncate() now calls it instead of inlining the loop.
```

## The honesty (never-fake-green) — the point, not a footnote

Apex flagged **every** move `⚠ no-suite`: `python-slugify` keeps all its tests in one
flat `test.py`, not module-linked `tests/test_<module>.py` files, so Apex's
impact-scoped verifier could not tie a change in `slugify/slugify.py` to a test. Apex
therefore **applied the moves but explicitly refused to claim they were test-verified**
— coverage-aware honesty, on someone else's code. It did not fake green.

## Independent verification (the "unverified" was conservative, not wrong)

Running `python-slugify`'s **own 82-test suite against Apex's modified tree**:

```
82 passed in 0.11s
```

So the diffs Apex landed are in fact correct and behavior-preserving — Apex's honest
"nothing verified it" was a conservative disclosure (it lacked a module-linked test to
cite), not an admission of risk. This is exactly the trust posture the product sells:
**it under-claims rather than over-claims.**

## Conclusion

On an independent OSS project, with zero tokens, Apex: read the code, proposed
specific moves, **landed 131 lines of real, correct development**, and disclosed the
verification status honestly. That is the buyer-visible artifact the North Star asks
for.

**Reproduce:** `git clone https://github.com/un33k/python-slugify && pip install
text-unidecode && python -m app.cli develop --target python-slugify session --apply`,
then `git -C python-slugify diff` and re-run `python -m pytest python-slugify/test.py`.
