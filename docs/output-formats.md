# Apex review output formats — CI-interop reference

`apex review` reviews only the lines changed since a base ref and can emit its
findings in the formats the common CI quality systems already ingest. This lets
Apex drop into an existing pipeline — next to, or in place of, SonarQube /
CodeClimate / GitLab Code Quality — rather than replacing the dashboard a team
already runs.

The relevant flags (defined in `app/cli_review.py`):

- `--format {sarif,codeclimate,junit,github,sonar,csv,html}` — pick the output
  format. When set, the formatted findings are the **sole** output of the command.
- `--format-out PATH` — write the formatted output to a file. If omitted, the
  output is printed to stdout.
- `--base REF` — the git ref to diff against (default `HEAD`).
- `--fail-on-high` — exit non-zero when a high-severity finding lands in the diff
  (works with `--format`, for CI gating).

All exporters are pure, deterministic, and make no network call: the same findings
in produce byte-identical output out (no clock, no timestamp, no randomness).

General form:

```
apex review --base <REF> --format <X> --format-out <PATH>
```

---

## sarif

- **Consumes:** GitHub code scanning (PR **Security** tab) and most CI security
  dashboards that ingest SARIF 2.1.0.
- **Exporter:** `app/engine/sarif_export.py`.
- **Command:**

  ```
  apex review --format sarif --format-out apex.sarif
  ```

  (The standalone `apex review --sarif apex.sarif` flag writes the same artifact;
  `.github/workflows/apex-ci.yml` uses it and uploads via
  `github/codeql-action/upload-sarif@v3`.)

## codeclimate

- **Consumes:** GitLab's **Code Quality** widget and the broader CodeClimate
  ecosystem — a JSON array of issue objects (description, check_name, fingerprint,
  severity, location).
- **Exporter:** `app/reporting/codeclimate_export.py`.
- **Command:**

  ```
  apex review --format codeclimate --format-out gl-code-quality-report.json
  ```

## sonar

- **Consumes:** SonarQube via its **Generic Issue Import** report
  (`sonar.externalIssuesReportPaths`) — a single JSON object `{"issues": [...]}`
  with `engineId: "apex"`. Feeds Apex findings straight into an existing SonarQube
  quality gate.
- **Exporter:** `app/reporting/sonar_generic_export.py`.
- **Command:**

  ```
  apex review --format sonar --format-out apex-sonar.json
  ```

## junit

- **Consumes:** any JUnit-XML-aware CI test-report UI (Jenkins, GitLab, GitHub
  Actions, CircleCI). Each finding becomes a failing `<testcase>`; a clean file
  becomes a passing suite.
- **Exporter:** `app/reporting/junit_export.py`.
- **Command:**

  ```
  apex review --format junit --format-out apex-junit.xml
  ```

## github

- **Consumes:** GitHub Actions — workflow-command annotations that render as
  inline red/yellow/blue gutter markers on the changed lines of the PR, with no
  extra configuration. Typically printed to stdout from a workflow step.
- **Exporter:** `app/reporting/gha_annotations.py`.
- **Command:**

  ```
  apex review --format github
  ```

## csv

- **Consumes:** spreadsheets (Excel / Sheets), BI tools, data warehouses, and
  audit logs. One row per finding, a stable header, RFC-4180 quoting so messages
  with commas/quotes/newlines survive a round-trip.
- **Exporter:** `app/reporting/csv_export.py`.
- **Command:**

  ```
  apex review --format csv --format-out findings.csv
  ```

## html

- **Consumes:** humans — a single, self-contained HTML report (inlined CSS, no
  remote script/font, no per-run timestamp) to share with a team or an auditor.
- **Exporter:** `app/reporting/findings_html.py`.
- **Command:**

  ```
  apex review --format html --format-out findings.html
  ```

---

## Related adoption on-ramps

- **`.pre-commit-hooks.yaml`** — exposes `apex-gate` (offline health gate) and
  `apex-review` (review staged changes vs `HEAD`, fail on high severity) as
  [pre-commit](https://pre-commit.com) hooks.
- **`.github/workflows/apex-ci.yml`** — runs the gate, exports SARIF, and uploads
  it to the Security tab.
- **`.github/workflows/apex-review.yml`** — runs the diff review and posts the
  verdict as a sticky PR comment.
