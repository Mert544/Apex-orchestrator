# Apex — 60-Second Quickstart

Apex is a **deterministic, zero-token engineering agent** for Python. It runs
fully offline — no API keys, no network, no per-token billing — and gives the
**same verdict for the same code every time**. The LLM layer is optional and
**off by default**.

This page is the copy-pasteable on-ramp: install from source, grade a project,
review a diff, gate a build, look at the deeper analyzers, and open an HTML
dashboard.

---

## 0. Install (from source)

Apex installs from source today — it is **not** on PyPI. The package is
`apex-orchestrator`; installing it puts the `apex` console script on your PATH.

```bash
git clone https://github.com/Mert544/Apex-orchestrator
cd Apex-orchestrator
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .                    # add [dev] for the test/lint extras: pip install .[dev]
apex --help
```

Every command below takes `--target <path>` (default: the current directory),
so you can point Apex at any Python project. Most also accept `--json`.

---

## 1. Grade the project

A single A–F health grade with a breakdown — the fastest read on a codebase.

```bash
apex grade --target .            # human-readable grade + breakdown
apex grade --min-score 80        # exit non-zero if the score is below 80 (CI-friendly)
apex grade --save                # snapshot to .apex/grade-snapshot.json
apex grade --diff                # compare to the saved snapshot — what improved
```

## 2. Review the changed lines

`apex review` analyses **only the lines changed since a base ref** (security,
correctness, style, docs) and prints suggested fixes.

```bash
apex review --base origin/main                 # review this branch vs origin/main
apex review --base origin/main --fail-on-high  # exit non-zero on a high-severity finding
apex review --base HEAD --fix                  # apply the auto-fixable findings (test-verified)
```

It also emits **CI-interop formats** so findings land where your tooling already
looks:

```bash
apex review --base origin/main --format sarif --format-out apex.sarif   # GitHub code scanning
apex review --base origin/main --format codeclimate                     # GitLab Code Quality
apex review --base origin/main --format junit --format-out review.xml   # JUnit
```

`--format` accepts: `sarif`, `codeclimate`, `junit`, `github` (Actions
annotations), `sonar`, `csv`, `html`. `--sarif <path>` is shorthand for the
SARIF file.

## 3. Gate a build

`apex gate` is a zero-config, deterministic PASS/FAIL gate (exit `0`/`1`) over
Apex's own metrics. A clean repo passes; a real security/correctness regression
turns the build red.

```bash
apex gate                        # zero-config absolute gate
apex gate --save-baseline        # once, on a good commit -> .apex/gate-baseline.json (commit it)
apex gate --baseline             # then: fail only if THIS change made the repo worse
apex gate --baseline --tolerance 2   # absorb a health-score drop of up to 2 points
```

A missing baseline exits `2` (a misconfigured gate, never a silent pass).

## 4. Look deeper — the analyzer suite

Beyond the grade, Apex ships a set of deterministic analyzers. They all run
offline and support `--json`:

```bash
apex hotspots --target .         # modules most worth attention (complexity x fan-in / tests)
apex deps --target .             # possibly-unused / undeclared / unpinned dependencies
apex scope --target .            # honest coverage: what fraction of the repo Apex analyses
apex deadcode --target .         # symbols defined but referenced nowhere
apex deadcode --confirm          # ...confirmed at runtime under the project's own tests
apex duplication --target .      # copy-pasted blocks to extract into shared helpers
apex impact <function>           # blast radius of changing a function (transitive callers)
```

## 5. Generate a dashboard

A self-contained HTML report (profile, findings, architecture health, idea tree)
you can open in a browser or attach to a PR.

```bash
apex dashboard --target .                       # writes <target>/.apex/dashboard.html
apex dashboard --target . --out apex-report.html
```

---

## Drop Apex into CI

### GitHub Actions — one step

This repo ships a composite action, so a full health-grade gate plus a
diff-scoped review (with SARIF upload to the Security tab) is a single step:

```yaml
# .github/workflows/apex.yml
name: Apex
on: [pull_request]
permissions:
  contents: read
  security-events: write          # so the review can upload SARIF
jobs:
  apex:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # full history so the diff review can find the base
      - uses: Mert544/Apex-orchestrator@v1
        with:
          base: origin/${{ github.base_ref }}   # diff-scoped review (omit to grade only)
          min-score: '0'                          # raise to fail the build below a grade
```

Prefer plain steps? `pip install .`, then run the CLI directly — see
[`docs/ci.md`](ci.md) and the ready-made
[`.github/workflows/apex-ci.yml`](../.github/workflows/apex-ci.yml).

### Pre-commit hook

Apex ships [`.pre-commit-hooks.yaml`](../.pre-commit-hooks.yaml), so consuming
repos can gate locally — also fully offline, no token cost:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Mert544/Apex-orchestrator
    rev: v1                # pin a tag
    hooks:
      - id: apex-gate      # deterministic, offline health gate
      - id: apex-review    # review staged changes vs HEAD; fail on high severity
```

---

## What makes the verdict trustworthy

- **Deterministic & zero-token** — same input, same output; no API keys, no
  per-token cost, nothing leaves the machine. CI can depend on it; an LLM can't
  gate a build reproducibly.
- **Air-gappable** — the core runs with no network calls, unchanged inside a
  locked-down or on-prem runner.
- **Proof-carrying** — recommendations and fixes show the exact diff, a re-parse
  safety verdict, the before→after metric delta, and whether your tests actually
  exercise the change.
- **It never fakes a green** — `apex scope` says exactly what fraction it
  analyses, and applied fixes are test-verified with automatic rollback, so a
  run can't leave the project broken.

The optional LLM layer (GitHub Models, Groq, Gemini, Ollama) is **off by
default**; everything above works without it. See
[`docs/free-llm-setup.md`](free-llm-setup.md) if you want to enable it.
