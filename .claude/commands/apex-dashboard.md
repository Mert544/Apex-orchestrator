---
description: Generate a self-contained HTML project dashboard (profile, scan findings, architecture health, idea tree, reasoning telemetry) with Apex. Use when asked for a visual project health overview or report.
argument-hint: "[target path] (default: repo root)"
allowed-tools: Bash
---

Generate Apex's self-contained HTML dashboard for the target project.

Target: `$ARGUMENTS` (default `.`).

```!
python -m app.cli dashboard --target="${ARGUMENTS:-.}" --out=.apex/dashboard.html && echo "Open .apex/dashboard.html in a browser"
```

Then tell the user the dashboard was written to `.apex/dashboard.html` and summarize the
headline numbers (files, security findings, coverage, import cycles, ideas). If running
in an environment where the user can't open a browser, offer to surface the key sections
as text.
