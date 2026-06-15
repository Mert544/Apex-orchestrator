# Migrating to Apex

Practical, copy-pasteable playbooks for adopting Apex **alongside or in place of**
the quality tools you already run. Apex is a **deterministic, zero-token engineering
assistant** for Python: it runs fully offline (stdlib-only core, no API keys, no
network, no per-token billing) and returns the **same verdict for the same diff
every time**. That property is what makes the migrations below safe — you can stand
Apex up next to your current tool, compare results on real PRs, and only then
decide what to retire.

> **Install once (every playbook assumes this).** Apex ships a console script and a
> module entry point; both come from a plain `pip install`:
>
> ```bash
> pip install .            # or: pip install -e .   (editable, for a checkout)
> apex --help              # the `apex` console script
> python -m app.cli --help # identical surface, no console script needed
> ```
>
> Every command below works either way: `apex gate` ≡ `python -m app.cli gate`.

**A note on output formats (read before you wire anything).** Today Apex's
machine-readable review exports are **SARIF 2.1.0** (`apex review --sarif`) and
**JSON** (`apex review --json`). Native **CodeClimate**, **JUnit**, **GitHub
annotations**, and **SonarQube** exporters are **being added this wave** — where a
playbook needs one of those formats *right now*, it shows a small, deterministic
shim over `--json` and flags clearly that the native exporter is **coming**. No
invented flags: every flag in this document exists in the CLI today.

---

## Table of contents

1. [Add Apex to an existing CI as a quality gate](#1-add-apex-to-an-existing-ci-as-a-quality-gate)
2. [Replace CodeClimate / GitLab Code Quality](#2-replace-codeclimate--gitlab-code-quality)
3. [Replace or augment Sourcery](#3-replace-or-augment-sourcery)
4. [Air-gapped / regulated environments](#4-air-gapped--regulated-environments)
5. [What still needs a human](#what-still-needs-a-human)

---

## 1. Add Apex to an existing CI as a quality gate

**Goal:** keep your current linter/scanner exactly as-is, and add Apex *next to it*
as a second, deterministic gate. Nothing is removed; you get a side-by-side read on
every PR. This is the recommended first step for any migration — adopt before you
replace.

The two commands that do the work:

- **`apex gate`** — zero-config PASS/FAIL. It scores the repo on Apex's own
  deterministic metrics (health grade + project profile: security-finding modules,
  correctness-bug modules, out-of-scope ratio) and **exits non-zero** when the bar
  isn't met. A clean repo passes; the moment a detector flags a real security or
  correctness issue, the build goes red. Exit `0` = pass, `1` = fail — the CI
  contract.
- **`apex review --base <ref>`** — reviews **only the lines changed** since a base
  ref and can emit SARIF for your code-scanning dashboard.

### 1a. GitHub Actions

Add this as a **new** workflow file (it does not touch your existing one). Your
current tool keeps running in its own job; Apex runs in this one.

```yaml
# .github/workflows/apex.yml
name: Apex
on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read           # checkout
  security-events: write   # upload SARIF to the Security tab
  pull-requests: write      # post Apex's verdict as a sticky PR comment

jobs:
  apex:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0           # full history so --baseline / --base can diff

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Apex
        run: pip install .

      # Deterministic PASS/FAIL gate. Fails the job on a finding/regression.
      - name: Apex quality gate
        run: apex gate

      # Export the diff review as SARIF — runs even if the gate failed, so the
      # Security tab is populated on exactly the PRs that need attention.
      - name: Export findings as SARIF
        if: ${{ always() }}
        run: apex review --base "origin/${{ github.base_ref || 'main' }}" --sarif apex.sarif

      - name: Upload SARIF to the Security tab
        if: ${{ always() }}
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: apex.sarif
          category: apex          # keeps Apex alerts distinct from your other tool's

      # One-glance verdict for the PR itself: 🟢 clean or 🔴 N high-severity issues.
      - name: Render Apex verdict
        if: ${{ always() && github.event_name == 'pull_request' }}
        run: apex review --base "origin/${{ github.base_ref || 'main' }}" --summary > apex-review.md

      - name: Post verdict as a sticky PR comment
        if: ${{ always() && github.event_name == 'pull_request' }}
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          header: apex-review     # one comment, updated in place (never a stale thread)
          path: apex-review.md
```

Because Apex runs under its own SARIF `category: apex`, its findings appear in the
Security tab **alongside** your existing scanner's, not mixed into them — so you can
compare the two directly before deciding which to keep.

### 1b. Gate on regressions instead of an absolute bar

`apex gate` answers *"is this repo good enough?"*. On an existing codebase with
pre-existing debt that absolute bar may be too strict on day one. Use a **baseline**
to gate on the sharper question — *"did **this** change make it worse?"* — which is
exactly what you want when adopting onto a mature repo:

```bash
# Once, on a known-good commit:
apex gate --save-baseline      # writes .apex/gate-baseline.json
git add .apex/gate-baseline.json && git commit -m "chore: apex gate baseline"
```

Then in CI swap the gate step to:

```yaml
      - name: Apex regression gate
        run: apex gate --baseline           # fails only on a regression vs. the baseline
        # add --tolerance N to absorb a health-score drop of up to N points
```

`--baseline` fails on a lower score (beyond `--tolerance`), more security/bug
modules, or a higher out-of-scope ratio. A **missing** baseline exits `2` (a
misconfigured gate, never a silent pass). A bare `apex gate` stays byte-identical —
baseline mode is fully opt-in.

You can also tune the absolute gate per check without a baseline:

```bash
apex gate --max-security 0 --max-bugs 0          # the conservative defaults
apex gate --min-score 80                          # also require health score ≥ 80
apex gate --max-out-of-scope 40                   # fail if >40% of the repo is non-Python
```

### 1c. GitLab CI

The commands are plain CLI — `apex gate` exits `0`/`1`, `apex review --sarif` writes
a file. That wires into GitLab unchanged. Run Apex as its own job next to your
current `code_quality` job:

```yaml
# .gitlab-ci.yml  (excerpt — add as a new job, change nothing else)
apex:
  stage: test
  image: python:3.11
  variables:
    GIT_DEPTH: 0                       # full history so --base can diff
  script:
    - pip install .
    - apex gate                        # deterministic PASS/FAIL — fails the pipeline on a finding
    - apex review --base "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}" --sarif apex.sarif
  artifacts:
    when: always
    paths:
      - apex.sarif                     # keep the SARIF as a build artifact
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

(To surface findings in GitLab's MR widget specifically, see playbook 2 — that's the
`codequality` report format, and there's a shim for it today.)

### 1d. Any other CI (Jenkins, CircleCI, pre-merge hook)

There is nothing GitHub- or GitLab-specific about the mechanism: install, then run
two commands that an exit code and an artifact store can consume.

```bash
pip install .
apex gate                                  # exit 0 = pass, 1 = fail
apex review --base origin/main --sarif apex.sarif   # write the artifact
```

Any CI that reads an exit code and can store a file works.

---

## 2. Replace CodeClimate / GitLab Code Quality

**Goal:** retire a hosted Code Quality service (CodeClimate, or GitLab's built-in
Code Quality, which itself consumes a **CodeClimate-format JSON** report) and let
Apex produce the report instead — keeping the same MR/PR widget you already read.

### Why teams make this move

| You had | What changes with Apex |
|---|---|
| A SaaS that ingests your code, or a vendored engine image | Stdlib-only CLI, runs in your own runner; **no code egress** |
| Per-seat / per-LOC billing | Zero marginal cost — it's `pip install` + runner minutes |
| A model/engine version you can't pin, results that drift | Deterministic: same diff → same findings, replayable |

### The format you need

GitLab Code Quality reads a **CodeClimate-format** JSON array uploaded as a
`codequality` report artifact. Each element looks like:

```json
{
  "description": "human-readable message",
  "check_name": "rule id",
  "fingerprint": "stable-hash",
  "severity": "minor",
  "location": { "path": "app/foo.py", "lines": { "begin": 12 } }
}
```

A **native `--codeclimate` exporter is coming this wave.** Until it lands, Apex
already emits everything that report needs via `apex review --json`, so you can
produce a valid `codequality` artifact today with a tiny deterministic shim. The
JSON Apex emits per finding carries `file`, `line`, `category`, `severity`
(`high`/`medium`/`low`), `message`, and `auto_fixable`.

### GitLab — wire the `codequality` artifact today

```yaml
# .gitlab-ci.yml
apex_code_quality:
  stage: test
  image: python:3.11
  variables:
    GIT_DEPTH: 0
  before_script:
    - pip install .
    - apt-get update && apt-get install -y jq    # or use python -c, see below
  script:
    # 1. Emit Apex's deterministic diff review as JSON.
    - apex review --base "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}" --json > apex.json
    # 2. Map it to the CodeClimate shape GitLab's widget reads.
    #    (Replaced by a native `apex review --codeclimate` exporter, coming this wave.)
    - |
      jq '[.findings[] | {
        description: .message,
        check_name: .category,
        fingerprint: (.file + ":" + (.line|tostring) + ":" + .category),
        severity: (if .severity=="high" then "major"
                   elif .severity=="medium" then "minor"
                   else "info" end),
        location: { path: .file, lines: { begin: .line } }
      }]' apex.json > gl-code-quality-report.json
  artifacts:
    reports:
      codequality: gl-code-quality-report.json   # GitLab renders this in the MR widget
    paths:
      - gl-code-quality-report.json
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

No `jq` in the image? The same map in pure stdlib Python (no extra install):

```bash
apex review --base "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}" --json > apex.json
python - <<'PY'
import json
sev = {"high": "major", "medium": "minor", "low": "info"}
data = json.load(open("apex.json"))
out = [{
    "description": f["message"],
    "check_name": f["category"],
    "fingerprint": f'{f["file"]}:{f["line"]}:{f["category"]}',
    "severity": sev.get(f["severity"], "info"),
    "location": {"path": f["file"], "lines": {"begin": f["line"]}},
} for f in data["findings"]]
json.dump(out, open("gl-code-quality-report.json", "w"), indent=2)
PY
```

That report drops into the exact `artifacts.reports.codequality` slot CodeClimate /
GitLab Code Quality used — your MR widget is unchanged, the engine behind it is now
deterministic and offline.

### GitHub — the same findings, the Security tab instead

If you were on CodeClimate's GitHub integration, the closest native home for
findings on GitHub is the **Security tab via SARIF** — which Apex emits directly,
no shim:

```bash
apex review --base origin/main --sarif apex.sarif
# then: github/codeql-action/upload-sarif@v3  (see playbook 1a)
```

### Migration checklist

1. Add the Apex job **next to** your existing CodeClimate job. Compare the two
   widgets on real MRs for a sprint.
2. Once you trust Apex's findings, delete the CodeClimate job/integration and the
   vendored engine config (`.codeclimate.yml`).
3. Optionally add `apex gate` (playbook 1) so the pipeline also **fails** on
   regressions, not just reports them — something the report-only CodeClimate
   artifact never did on its own.

---

## 3. Replace or augment Sourcery

**Goal:** move from Sourcery's LLM/heuristic refactoring suggestions to Apex's
**deterministic, test-verified auto-fix** — and understand exactly how they differ,
so you keep Sourcery for the parts Apex deliberately does *not* do.

### The core difference: proof, not optimism

Sourcery proposes refactors; Apex **applies fixes only when it can prove them safe**
and **never fakes a green**:

| | Sourcery-style suggestion | `apex maintain` |
|---|---|---|
| How a fix lands | You accept a suggested diff | Apex applies, **runs your test suite**, and **auto-rolls-back** on any failure |
| Determinism | Heuristic/model-driven; can vary | Same repo state → same fixes, replayable |
| Evidence | A diff to eyeball | A **proof-of-fix** artifact: finding cited, diff, tests run + durations, rollback events |
| Coverage honesty | Applies regardless of test coverage | A behaviour-adjacent (Tier-1) fix on a file your tests don't exercise is **shielded** with a generated characterization test first, or **blocked** — never gambled |
| Network / keys | Cloud service | Offline, stdlib-only, zero tokens |

The point of Apex's auto-fix is not "more fixes" — it's that **every fix it does
land is one your suite proved didn't break anything**, with an auditable record.

### Daily use

```bash
# Preview every fix as a unified diff — change nothing (the safe first run):
apex maintain --dry-run

# Apply the safe, test-verified fixes (supervised: applies, does not commit):
apex maintain

# Full autonomous pass: apply AND commit each verified step:
apex maintain --mode autonomous --commit

# Cap the blast radius of a single run:
apex maintain --max-apply 5

# Scope the pass to one named recipe/intent (see `apex recipes` for the catalog):
apex maintain --recipe modernize
```

After a real run, Apex writes the evidence file (default `.apex/proof-of-fix.json`,
or `--proof <path>`): the finding each fix addressed, the diff, the tests it ran
with before/after status and durations, and any rollbacks. That file *is* the
review artifact — a compliance officer or a skeptical reviewer can open it.

### On a PR (replace Sourcery's bot comment)

Apex reviews the **changed lines** and can apply its auto-fixable findings through
the same guarded pass — test-verified, with rollback:

```bash
# Comment-style review of the diff (no changes):
apex review --base origin/main

# Review AND apply the auto-fixable findings on the changed files (test-verified):
apex review --base origin/main --fix
```

In CI this is the analogue of Sourcery's auto-fix PR — except a fix only survives if
your suite stays green. Wire it like playbook 1a, adding `--fix` to the review step
if you want Apex to push the verified fixes back.

### What to keep Sourcery (or an LLM assistant) for

Apex is deterministic **by design**, which caps it on creative work. Be honest about
the boundary and keep your other tool for the other side of it:

- **Naming, docstring prose, API design, genuinely novel refactors** — these need
  judgement Apex doesn't have. Apex's autonomous changes are a catalog of safe,
  AST-based transforms; higher-risk or design-level issues are **flagged with a
  proposed direction, not rewritten**.
- Large, ambiguous, multi-file redesigns. Apex has cross-file `rename`/`move` with
  import rewriting, but a *redesign* is human/LLM work, human-reviewed.

The clean split: **let Sourcery/an LLM propose the creative change; let Apex be the
deterministic verifier and the zero-cost upkeep that proves what's safe.** They are
complementary, and you can run both during the transition with no conflict.

---

## 4. Air-gapped / regulated environments

**Goal:** run a real quality gate where SaaS tools structurally **cannot** operate —
finance, defense, healthcare, classified, or any IP-sensitive shop where source code
may not leave the building and outbound network is blocked.

### Why Apex works where cloud tools don't

This is not a price advantage; it is an **access** advantage. Apex's core runs on
the **Python standard library only**:

- **No network calls.** Nothing phones home, no model endpoint, no telemetry
  upload. It runs unchanged inside a runner with **zero egress**.
- **No API key.** There is no account to provision, no secret to inject, no vendor
  to onboard through procurement.
- **No code egress.** Your source never leaves the machine. The analysis happens
  locally; the only outputs are the files Apex writes into your repo (SARIF,
  proof-of-fix, reports).
- **Deterministic and replayable.** An auditor can re-run last quarter's commit and
  get last quarter's verdict — the gate is a function of the code, not of a model
  snapshot you can't pin. LLM-based reviewers cannot offer this.

If a cloud assistant is **banned** in your environment, that's not a gap Apex has to
work around — it's the exact niche Apex was built for.

### Install behind the firewall

The only step that touches a network is fetching the package once. Do it on a
connected machine, then carry it in:

```bash
# On a machine WITH network access:
pip download . -d apex-wheels/            # vendor Apex + its (minimal) deps as wheels
#   ... transfer apex-wheels/ across the air gap (the approved way for your site) ...

# On the air-gapped runner, no network needed:
pip install --no-index --find-links apex-wheels/ apex-orchestrator
apex --help
```

After that, **every** command runs offline. There is no second network step at
runtime — `apex gate`, `apex review`, `apex maintain`, `apex grade` all work with
the network cable unplugged.

### A self-hosted runner gate (network fully disabled)

```yaml
# Self-hosted GitLab/GitHub runner inside the enclave. No registry, no SaaS.
apex_offline_gate:
  stage: test
  tags: [airgapped]                 # pin to your in-enclave runner
  variables:
    GIT_DEPTH: 0
    PIP_NO_INDEX: "1"               # belt-and-suspenders: forbid any index fetch
    PIP_FIND_LINKS: "/opt/apex-wheels"
  script:
    - pip install --no-index --find-links /opt/apex-wheels apex-orchestrator
    - apex gate                                     # deterministic PASS/FAIL, offline
    - apex review --base origin/main --sarif apex.sarif
    - apex grade --json > apex-grade.json           # health grade as a build record
  artifacts:
    when: always
    paths:
      - apex.sarif
      - apex-grade.json
```

### The audit story (for the compliance reviewer)

Regulated environments need *evidence*, and Apex's outputs are built for exactly
that:

- **`apex maintain`** writes a **proof-of-fix** JSON (`.apex/proof-of-fix.json`):
  every applied fix with its cited finding, diff, the tests it ran, and any
  rollback. That is a signed-off-able change record.
- **`apex gate --save-baseline`** + **`apex gate --baseline`** give a reproducible,
  versioned quality bar checked into the repo — the gate's behaviour is auditable
  from git history, not from a vendor dashboard.
- **`apex grade`** / **`apex scope`** report a deterministic health grade and an
  **honest analysis-coverage figure** (what fraction of the repo Apex actually
  analyses, since the deep analysis is Python-only). It never claims to have
  covered code it didn't.
- **`apex review --sarif`** produces a standard SARIF 2.1.0 document — an
  open-format finding record any compliance tooling can ingest, with no proprietary
  lock-in.

Everything an auditor opens is a plain file in your repo, produced by a process they
can replay byte-for-byte.

---

## What still needs a human

Honesty is the product, so the limits are stated plainly. Apex is a **deterministic
complement** to human/LLM engineering, not a replacement for either:

- **Apex does not generate features.** It will not write new functionality from a
  prompt. Its autonomous changes are a catalog of safe, AST-based transforms.
- **Creative/ambiguous work is out of scope by design** — naming, docstring prose,
  API design, genuinely novel refactors. Apex flags these with a direction; a human
  or LLM does the writing.
- **`apex deps`** (dependency audit: possibly-unused / undeclared / unpinned
  packages) is an honest **heuristic** — optional/extra imports can false-positive.
  It returns `0` by default and only fails a build when you opt in with `--strict`.
  **Review its output before gating on it.**
- **Higher-risk fixes are flagged, not applied.** Logic bugs and design issues are
  surfaced with a proposed direction; only safe transforms are auto-applied, and
  even those roll back if your suite goes red.
- **Verification is only as strong as your tests.** "Test-verified" on a repo with
  four smoke tests means less than on a well-covered one — and Apex says so
  (verification strength per fix; a Tier-1 fix on an uncovered file is shielded or
  blocked). Strengthen your suite to strengthen the guarantee.

The migration that works: **adopt Apex alongside your current tools first**, compare
on real PRs, retire what Apex provably replaces (deterministic gating, code-quality
reporting, safe auto-fix), and **keep your LLM assistant for the creative half**
Apex deliberately leaves to humans.
