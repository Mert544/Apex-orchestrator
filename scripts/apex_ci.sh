#!/usr/bin/env sh
# Apex Orchestrator — Generic CI/CD integration script
# Supports: GitHub Actions, GitLab CI, Jenkins, Azure DevOps, Bitbucket Pipelines
#
# Usage:
#   chmod +x scripts/apex_ci.sh
#   ./scripts/apex_ci.sh --goal="security audit" --mode=report
#
# Environment variables:
#   APEX_GOAL       — Natural-language goal (default: "scan project")
#   APEX_MODE       — report | supervised | autonomous (default: report)
#   APEX_TARGET     — Project root (default: ".")
#   APEX_FORMAT     — Output format: markdown | html | sarif (default: markdown)
#   APEX_FAIL_ON    — Fail CI on: critical | high | none (default: critical)
#   APEX_OUTPUT     — Report output path (default: apex-report.md)

set -e

GOAL="${APEX_GOAL:-scan project}"
MODE="${APEX_MODE:-report}"
TARGET="${APEX_TARGET:-.}"
FORMAT="${APEX_FORMAT:-markdown}"
FAIL_ON="${APEX_FAIL_ON:-critical}"
OUTPUT="${APEX_OUTPUT:-apex-report.md}"

# Parse CLI flags (override env vars)
while [ $# -gt 0 ]; do
  case "$1" in
    --goal=*)
      GOAL="${1#*=}"
      shift
      ;;
    --mode=*)
      MODE="${1#*=}"
      shift
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    --format=*)
      FORMAT="${1#*=}"
      shift
      ;;
    --fail-on=*)
      FAIL_ON="${1#*=}"
      shift
      ;;
    --output=*)
      OUTPUT="${1#*=}"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Detect CI environment and print context
CI_NAME="local"
if [ -n "$GITHUB_ACTIONS" ]; then
  CI_NAME="github-actions"
  echo "[apex-ci] Detected GitHub Actions"
  echo "[apex-ci] Repository: $GITHUB_REPOSITORY"
  echo "[apex-ci] Commit: $GITHUB_SHA"
elif [ -n "$GITLAB_CI" ]; then
  CI_NAME="gitlab-ci"
  echo "[apex-ci] Detected GitLab CI"
  echo "[apex-ci] Project: $CI_PROJECT_NAME"
  echo "[apex-ci] Commit: $CI_COMMIT_SHA"
elif [ -n "$JENKINS_URL" ]; then
  CI_NAME="jenkins"
  echo "[apex-ci] Detected Jenkins"
elif [ -n "$BUILD_BUILDID" ]; then
  CI_NAME="azure-devops"
  echo "[apex-ci] Detected Azure DevOps"
elif [ -n "$BITBUCKET_PIPELINE_UUID" ]; then
  CI_NAME="bitbucket"
  echo "[apex-ci] Detected Bitbucket Pipelines"
fi

# Install Apex if not already installed
if ! command -v apex >/dev/null 2>&1; then
  echo "[apex-ci] Installing Apex Orchestrator..."
  pip install -e . >/dev/null 2>&1 || pip install -e . 2>&1 | tail -n 5
fi

# Run Apex
RUN_JSON=".apex/last-run.json"
mkdir -p .apex

echo "[apex-ci] Goal: $GOAL"
echo "[apex-ci] Mode: $MODE"
echo "[apex-ci] Target: $TARGET"
echo "[apex-ci] Running..."

python -m app.cli run --goal="$GOAL" --target="$TARGET" --mode="$MODE" > "$RUN_JSON" 2>&1 || true

# Generate report
python -m app.cli report --input="$RUN_JSON" --format="$FORMAT" --output="$OUTPUT" >/dev/null 2>&1 || true

echo "[apex-ci] Report saved to $OUTPUT"

# Determine exit code based on findings
if [ "$FAIL_ON" != "none" ]; then
  # Parse JSON for critical/high risks
  if command -v python >/dev/null 2>&1; then
    CRITICAL=$(python -c "
import json, sys
try:
    data = json.load(open('$RUN_JSON'))
    results = data.get('swarm_results', data.get('results', []))
    count = sum(1 for r in results for f in r.get('findings', []) if f.get('severity') == '$FAIL_ON')
    print(count)
except:
    print(0)
" 2>/dev/null || echo 0)

    if [ "$CRITICAL" -gt 0 ]; then
      echo "[apex-ci] $CRITICAL $FAIL_ON risk(s) found — failing build."
      exit 1
    fi
  fi
fi

echo "[apex-ci] Passed."
exit 0
