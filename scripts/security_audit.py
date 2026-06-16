#!/usr/bin/env python3
"""Apex Orchestrator — CI/CD Security Audit Script.

Runs deterministic security analysis on the codebase using stdlib-only
tools. Fails the pipeline if critical risks are detected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on path when running standalone
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer
from app.tools.project_profile import ProjectProfiler


# Skip tests, venvs, generated code, examples, and audit scripts.
# `.claude/` holds agent git worktrees — full repo copies. Without
# this the audit re-scans every worktree's tree (8x+ the files),
# turning a seconds-long walk into a multi-minute near-hang.
_SKIP_DIRS = (
    "tests/", "test_", ".venv", "venv", "__pycache__", ".apex",
    "examples/", "scripts/",
    ".claude/", ".epistemic/", "node_modules/", "dist/", "build/",
)

_CRITICAL_PATTERNS = ("eval()", "exec()", "os.system()", "pickle.loads", "yaml.load")


def _is_skipped(rel: str) -> bool:
    return any(skip in rel for skip in _SKIP_DIRS)


def _fn_risks(fn: dict, rel: str) -> list[dict]:
    return [
        {
            "file": rel,
            "function": fn["name"],
            "risk": risk,
            "risk_score": fn["risk_score"],
        }
        for risk in fn["risks"]
    ]


def _is_critical(risk: dict) -> bool:
    return any(p in risk["risk"] for p in _CRITICAL_PATTERNS)


def _severity(risk: dict) -> str:
    if _is_critical(risk):
        return "critical"
    score = risk["risk_score"]
    if score >= 0.3:
        return "high"
    if score >= 0.1:
        return "medium"
    return "low"


def _categorize(all_risks: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {"critical": [], "high": [], "medium": [], "low": []}
    for risk in all_risks:
        buckets[_severity(risk)].append(risk)
    return buckets


def _scan(project_root: Path) -> tuple[list[dict], int]:
    analyzer = FunctionFractalAnalyzer()
    all_risks: list[dict] = []
    functions_analyzed = 0
    for py_file in project_root.rglob("*.py"):
        rel = py_file.relative_to(project_root).as_posix()
        if _is_skipped(rel):
            continue
        try:
            results = analyzer.analyze_file(py_file)
        except Exception:
            continue
        functions_analyzed += len(results)
        for fn in results:
            all_risks.extend(_fn_risks(fn, rel))
    return all_risks, functions_analyzed


def _build_report(project_root: Path, profile, all_risks: list[dict],
                  functions_analyzed: int, buckets: dict[str, list[dict]]) -> dict:
    return {
        "project_root": str(project_root),
        "summary": {
            "total_files": profile.total_files,
            "functions_analyzed": functions_analyzed,
            "total_risks": len(all_risks),
            "critical": len(buckets["critical"]),
            "high": len(buckets["high"]),
            "medium": len(buckets["medium"]),
            "low": len(buckets["low"]),
        },
        "risks": {
            "critical": buckets["critical"],
            "high": buckets["high"],
            "medium": buckets["medium"],
            "low": buckets["low"],
        },
        "critical_untested_modules": profile.critical_untested_modules,
    }


def _persist_report(project_root: Path, report: dict) -> None:
    apex_dir = project_root / ".apex"
    apex_dir.mkdir(exist_ok=True)
    report_path = apex_dir / "security-report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def run_audit(project_root: Path) -> dict:
    profile = ProjectProfiler(project_root).profile()
    all_risks, functions_analyzed = _scan(project_root)
    buckets = _categorize(all_risks)
    report = _build_report(project_root, profile, all_risks, functions_analyzed, buckets)
    _persist_report(project_root, report)
    return report


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    report = run_audit(project_root)

    summary = report["summary"]
    print("=" * 60)
    print("Apex Orchestrator Security Audit Report")
    print("=" * 60)
    print(f"Project:      {report['project_root']}")
    print(f"Files:        {summary['total_files']}")
    print(f"Functions:    {summary['functions_analyzed']}")
    print(f"Critical:     {summary['critical']}")
    print(f"High:         {summary['high']}")
    print(f"Medium:       {summary['medium']}")
    print(f"Low:          {summary['low']}")
    print("=" * 60)

    if summary["critical"] > 0:
        print("\nCRITICAL RISKS DETECTED — failing pipeline.")
        for r in report["risks"]["critical"]:
            print(f"  [{r['file']}::{r['function']}] {r['risk']}")
        return 1

    if summary["high"] > 0:
        print("\nHIGH RISKS DETECTED — review recommended.")
        for r in report["risks"]["high"]:
            print(f"  [{r['file']}::{r['function']}] {r['risk']}")

    print("\nNo critical risks found. Audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
