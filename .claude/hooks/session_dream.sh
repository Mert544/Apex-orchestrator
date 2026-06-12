#!/usr/bin/env bash
# SessionStart hook — the chief engineer's ritual: when a session begins, read
# what the organism discovered while we were away and surface it. Deterministic,
# zero tokens, never fails the session. Default `apex dream` only REPORTS
# (inputs untouched); the nightly CI is the one that curates/promotes.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
command -v python >/dev/null 2>&1 || exit 0
python -m app.cli dream 2>/dev/null | sed -n '1,40p' || true
exit 0
