# Drop Apex into your CI

Apex is a **deterministic, zero-token quality gate** for Python. It runs fully
offline — no API keys, no network, no per-token billing — and produces the
**same verdict for the same diff every time**. An LLM reviewer can't gate a
build reproducibly; Apex can.

This page is the one-page on-ramp: copy a workflow, get a pass/fail gate plus
findings in your GitHub Security tab.

## The minimal snippet

Copy [`.github/workflows/apex-ci.yml`](../.github/workflows/apex-ci.yml) into
your repo. The essential parts:

```yaml
name: Apex CI
on:
  pull_request:
permissions:
  contents: read
  security-events: write          # required to upload SARIF
jobs:
  apex-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0           # so --baseline can diff the change
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install "git+https://github.com/Mert544/Apex-orchestrator@main"  # ADOPTER line: installs APEX, not your project (pin a release tag when one exists). The real apex-ci.yml auto-detects and dogfoods the local source only inside Apex's own SELF-REPO.
      - run: apex gate             # fail the build on a finding / regression
      - if: ${{ always() }}
        run: apex review --base "origin/${{ github.base_ref || 'main' }}" --sarif apex.sarif
      - if: ${{ always() }}
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: apex.sarif
```

That is the whole integration. No secrets, no service to provision.

## What each step does

### `apex gate` — the build gate

Zero-config pass/fail. It scores the repo on Apex's own deterministic metrics
(health grade + project profile: security-finding modules, correctness-bug
modules, out-of-scope ratio) and **exits non-zero when the bar is not met**, so
the CI job fails. A clean repo passes; the moment a detector flags a real
security or correctness issue, the build goes red. No configuration required.

### `apex gate --baseline` — regression detection

Absolute thresholds answer "is this repo good enough?". A baseline answers the
sharper CI question: **"did THIS change make the project worse?"**

1. Once, on a known-good commit, snapshot the metrics:
   ```bash
   apex gate --save-baseline      # writes .apex/gate-baseline.json
   ```
   Commit that file.
2. In CI, gate on regressions:
   ```bash
   apex gate --baseline           # fails on a lower score, more security/bug
                                  # modules, or a higher out-of-scope ratio
   ```
   Use `--tolerance N` to absorb a health-score drop of up to N points. A
   missing baseline exits `2` (a misconfigured gate, never a silent pass).

Baseline mode is opt-in — a bare `apex gate` stays byte-identical.

### The SARIF step — findings in the Security tab

`apex review --base <ref> --sarif apex.sarif` writes the deterministic diff
review as a **SARIF 2.1.0** document. `github/codeql-action/upload-sarif` then
publishes it as code-scanning alerts, so each finding appears **inline on the
PR's Security tab** — where reviewers already look — instead of buried in a
build log. The findings carry severity, a stable rule id, and the suggested
fix. Both steps run under `if: ${{ always() }}` so the Security tab is
populated even when the gate has already failed the job.

## Why Apex in CI (the commercial case)

- **Deterministic.** Same input, same output. The gate is reproducible and
  auditable; you can re-run last week's PR and get last week's verdict. An LLM
  can't gate a build reproducibly — Apex can.
- **Zero-token.** No API keys, no per-token cost, no rate limits. CI cost is
  just the runner minutes.
- **Air-gappable.** Pure stdlib, no network calls. Runs unchanged inside a
  locked-down or on-prem runner with no egress.
- **Auditable.** Findings export as standard SARIF; fixes carry a
  proof-of-fix trail. The gate's verdict is a function of the code, not a model
  snapshot you can't pin.

## Beyond GitHub Actions

The commands are plain CLI — `apex gate` exits `0`/`1`, `apex review --sarif`
writes a file. Wire them into GitLab CI, Jenkins, CircleCI, or a pre-merge hook
the same way — install *Apex*
(`pip install git+https://github.com/Mert544/Apex-orchestrator@<ref>`), not
your own project (a bare `pip install .` outside Apex's own repo installs
whatever project lives at *your* root, not Apex), then run the two commands.
Any CI that reads an exit code and can store an artifact works.
