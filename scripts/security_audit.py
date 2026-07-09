#!/usr/bin/env python3
"""Apex Orchestrator — CI/CD Security Audit Script.

Runs deterministic security analysis on the codebase using stdlib-only
tools. Fails the pipeline if critical risks are detected.
"""
from __future__ import annotations

import ast
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


# ------------------------------------------------------------------------- #
# Acknowledged suppressions — bandit's `# nosec` convention, honored here.
#
# A critical call site annotated `# nosec <rule> - <rationale>` (the form
# app/execution/stub_synthesis.py already carries on its deliberate,
# fixed-template eval/exec sites) is reported as ACKNOWLEDGED instead of
# failing the pipeline. Strictly fail-closed: an unreadable file, an
# unresolvable function, a call we cannot locate, or ANY matching call in the
# function without its own annotation keeps the risk CRITICAL. Acknowledged
# risks stay fully visible in the report and the console output — this is an
# audit trail, never a mute button.
# ------------------------------------------------------------------------- #

def _parsed_with_nosec(path: Path, cache: dict):
    """``(ast.Module, {line numbers carrying '# nosec'})`` for ``path``,
    cached; ``None`` (→ fail closed) when unreadable or unparseable."""
    if path not in cache:
        try:
            source = path.read_text(encoding="utf-8")
            nosec = {n for n, line in enumerate(source.splitlines(), 1)
                     if "# nosec" in line}
            cache[path] = (ast.parse(source), nosec)
        except (OSError, SyntaxError, ValueError):
            cache[path] = None
    return cache[path]


def _named_function(tree: ast.Module, dotted: str):
    """Resolve the analyzer's function name (``fn`` or ``Class.method``) back
    to its AST node — the same top-level/method shape ``analyze_file`` walks."""
    cls_name, _, method = dotted.rpartition(".")
    for node in tree.body:
        if (not cls_name
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == dotted):
            return node
        if cls_name and isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method):
                    return item
    return None


def _matching_call_spans(fn_node, message: str) -> list[tuple[int, int]]:
    """Line spans of every call in ``fn_node`` whose analyzer risk message is
    ``message`` — reuses the analyzer's own ``_call_risk`` so the audit and
    the detector can never disagree about what was flagged."""
    spans: list[tuple[int, int]] = []
    for sub in ast.walk(fn_node):
        if isinstance(sub, ast.Call):
            hit = FunctionFractalAnalyzer._call_risk(sub)
            if hit is not None and hit[0] == message:
                spans.append((sub.lineno, sub.end_lineno or sub.lineno))
    return spans


def _is_acknowledged(risk: dict, project_root: Path, cache: dict) -> bool:
    """True ONLY when every call this critical risk points at carries an
    explicit ``# nosec`` annotation within its own line span."""
    parsed = _parsed_with_nosec(project_root / risk["file"], cache)
    if parsed is None:
        return False
    tree, nosec_lines = parsed
    fn_node = _named_function(tree, risk["function"])
    if fn_node is None:
        return False
    spans = _matching_call_spans(fn_node, risk["risk"])
    if not spans:
        return False
    return all(any(line in nosec_lines for line in range(start, end + 1))
               for start, end in spans)


def _split_acknowledged(buckets: dict[str, list[dict]],
                        project_root: Path) -> dict[str, list[dict]]:
    """Move `# nosec`-annotated criticals into their own ``acknowledged``
    bucket; unannotated criticals stay critical (and still fail the run)."""
    cache: dict = {}
    still_critical: list[dict] = []
    acknowledged: list[dict] = []
    for risk in buckets["critical"]:
        if _is_acknowledged(risk, project_root, cache):
            acknowledged.append(risk)
        else:
            still_critical.append(risk)
    buckets["critical"] = still_critical
    buckets["acknowledged"] = acknowledged
    return buckets


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
            "acknowledged": len(buckets["acknowledged"]),
            "high": len(buckets["high"]),
            "medium": len(buckets["medium"]),
            "low": len(buckets["low"]),
        },
        "risks": {
            "critical": buckets["critical"],
            "acknowledged": buckets["acknowledged"],
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
    buckets = _split_acknowledged(_categorize(all_risks), project_root)
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
    print(f"Acknowledged: {summary['acknowledged']}")
    print(f"High:         {summary['high']}")
    print(f"Medium:       {summary['medium']}")
    print(f"Low:          {summary['low']}")
    print("=" * 60)

    if summary["acknowledged"] > 0:
        print("\nACKNOWLEDGED RISKS (explicit `# nosec` at every call site — "
              "reviewed, visible, not pipeline-failing):")
        for r in report["risks"]["acknowledged"]:
            print(f"  [{r['file']}::{r['function']}] {r['risk']}")

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
