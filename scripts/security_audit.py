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


def run_audit(project_root: Path) -> dict:
    profiler = ProjectProfiler(project_root)
    profile = profiler.profile()

    analyzer = FunctionFractalAnalyzer()
    all_risks = []
    functions_analyzed = 0

    for py_file in project_root.rglob("*.py"):
        # Skip tests, venvs, generated code, examples, and audit scripts
        rel = py_file.relative_to(project_root).as_posix()
        skip_dirs = (
            "tests/", "test_", ".venv", "venv", "__pycache__", ".apex",
            "examples/", "scripts/",
        )
        if any(skip in rel for skip in skip_dirs):
            continue
        try:
            results = analyzer.analyze_file(py_file)
            functions_analyzed += len(results)
            for fn in results:
                all_risks.extend(
                    {
                        "file": rel,
                        "function": fn["name"],
                        "risk": risk,
                        "risk_score": fn["risk_score"],
                    }
                    for risk in fn["risks"]
                )
        except Exception:
            continue

    # Categorize risks
    critical_patterns = ("eval()", "exec()", "os.system()", "pickle.loads", "yaml.load")
    critical = [r for r in all_risks if any(p in r["risk"] for p in critical_patterns)]
    high = [r for r in all_risks if r["risk_score"] >= 0.3 and r not in critical]
    medium = [r for r in all_risks if 0.1 <= r["risk_score"] < 0.3 and r not in critical and r not in high]
    low = [r for r in all_risks if r["risk_score"] < 0.1 and r not in critical and r not in high and r not in medium]

    report = {
        "project_root": str(project_root),
        "summary": {
            "total_files": profile.total_files,
            "functions_analyzed": functions_analyzed,
            "total_risks": len(all_risks),
            "critical": len(critical),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
        },
        "risks": {
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
        },
        "critical_untested_modules": profile.critical_untested_modules,
    }

    # Persist report
    apex_dir = project_root / ".apex"
    apex_dir.mkdir(exist_ok=True)
    report_path = apex_dir / "security-report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

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
