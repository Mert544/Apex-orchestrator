#!/usr/bin/env python3
"""Apex Self-Audit: Analyze the Apex codebase using its own tools.

Usage:
    python scripts/self_audit.py > .apex/self-audit-report.md
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


def find_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]


def analyze_risks(files: list[Path]) -> list[dict[str, Any]]:
    risks = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id == "eval":
                        risks.append({"file": str(f), "line": node.lineno, "risk": "eval()", "severity": "critical"})
                    elif func.id == "exec":
                        risks.append({"file": str(f), "line": node.lineno, "risk": "exec()", "severity": "critical"})
                elif isinstance(func, ast.Attribute):
                    if func.attr == "system" and isinstance(func.value, ast.Name) and func.value.id == "os":
                        risks.append({"file": str(f), "line": node.lineno, "risk": "os.system()", "severity": "high"})
                    elif func.attr == "loads" and isinstance(func.value, ast.Name) and func.value.id == "pickle":
                        risks.append({"file": str(f), "line": node.lineno, "risk": "pickle.loads()", "severity": "high"})
            elif isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    risks.append({"file": str(f), "line": node.lineno, "risk": "bare except", "severity": "medium"})
    return risks


def analyze_docstrings(files: list[Path]) -> list[dict[str, Any]]:
    missing = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not ast.get_docstring(node):
                    missing.append({"file": str(f), "line": node.lineno, "name": node.name, "type": type(node).__name__})
    return missing


def analyze_complexity(files: list[Path]) -> list[dict[str, Any]]:
    long_funcs = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno if node.end_lineno else 0
                if length > 50:
                    long_funcs.append({"file": str(f), "line": node.lineno, "name": node.name, "lines": length})
    return long_funcs


def find_todos(files: list[Path]) -> list[dict[str, Any]]:
    todos = []
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip().lower()
            if "todo" in stripped or "fixme" in stripped or "hack" in stripped:
                todos.append({"file": str(f), "line": i, "text": line.strip()})
    return todos


def coverage_gap(app_files: list[Path], test_files: list[Path]) -> dict[str, Any]:
    tested_modules = set()
    for tf in test_files:
        text = tf.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "from app." in line or "import app." in line:
                # crude heuristic
                parts = line.replace("from ", "").replace("import ", "").split(".")
                if parts[0] == "app":
                    tested_modules.add(parts[1] if len(parts) > 1 else "")
    app_modules = {f.parts[f.parts.index("app") + 1] for f in app_files if "app" in f.parts}
    return {
        "tested_modules": sorted(tested_modules - {""}),
        "untested_modules": sorted(app_modules - tested_modules),
        "total_app_modules": len(app_modules),
        "total_test_files": len(test_files),
    }


def build_import_graph(files: list[Path]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for f in files:
        mod = f.as_posix().replace("/", ".").replace(".py", "").replace(".__init__", "")
        imports = []
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app."):
                        imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app."):
                    imports.append(node.module)
        if imports:
            graph[mod] = sorted(set(imports))
    return graph


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_dir = repo_root / "app"
    tests_dir = repo_root / "tests"

    app_files = find_python_files(app_dir)
    test_files = find_python_files(tests_dir)

    risks = analyze_risks(app_files)
    missing_docs = analyze_docstrings(app_files)
    long_funcs = analyze_complexity(app_files)
    todos = find_todos(app_files + test_files)
    cov = coverage_gap(app_files, test_files)
    graph = build_import_graph(app_files)

    # Markdown report
    lines = [
        "# Apex Self-Audit Report",
        "",
        f"**Date:** 2026-04-25",
        f"**App Files:** {len(app_files)}",
        f"**Test Files:** {len(test_files)}",
        "",
        "## Risk Analysis",
        "",
    ]
    if risks:
        lines.append(f"| File | Line | Risk | Severity |")
        lines.append(f"|------|------|------|----------|")
        for r in risks:
            lines.append(f"| {r['file']} | {r['line']} | {r['risk']} | {r['severity']} |")
    else:
        lines.append("No critical risks detected. ✅")
    lines.append("")

    lines.extend([
        "## Missing Docstrings",
        f"**Total:** {len(missing_docs)}",
        "",
    ])
    if missing_docs:
        lines.append("| File | Line | Name | Type |")
        lines.append("|------|------|------|------|")
        for m in missing_docs[:50]:
            lines.append(f"| {m['file']} | {m['line']} | {m['name']} | {m['type']} |")
        if len(missing_docs) > 50:
            lines.append(f"| ... | ... | ... | ... |")
            lines.append(f"_Showing first 50 of {len(missing_docs)}_")
    lines.append("")

    lines.extend([
        "## Long Functions (>50 lines)",
        f"**Total:** {len(long_funcs)}",
        "",
    ])
    if long_funcs:
        lines.append("| File | Line | Name | Lines |")
        lines.append("|------|------|------|-------|")
        for lf in long_funcs[:30]:
            lines.append(f"| {lf['file']} | {lf['line']} | {lf['name']} | {lf['lines']} |")
        if len(long_funcs) > 30:
            lines.append(f"_Showing first 30 of {len(long_funcs)}_")
    lines.append("")

    lines.extend([
        "## TODO / FIXME / HACK",
        f"**Total:** {len(todos)}",
        "",
    ])
    if todos:
        lines.append("| File | Line | Text |")
        lines.append("|------|------|------|")
        for t in todos[:30]:
            lines.append(f"| {t['file']} | {t['line']} | {t['text']} |")
        if len(todos) > 30:
            lines.append(f"_Showing first 30 of {len(todos)}_")
    lines.append("")

    lines.extend([
        "## Coverage Gap Analysis",
        "",
        f"- **Tested Modules:** {', '.join(cov['tested_modules']) or 'None'}",
        f"- **Untested Modules:** {', '.join(cov['untested_modules']) or 'None'}",
        f"- **Total App Modules:** {cov['total_app_modules']}",
        f"- **Total Test Files:** {cov['total_test_files']}",
        "",
    ])

    lines.extend([
        "## Module Import Graph (Internal)",
        "",
        "```json",
        json.dumps(graph, indent=2, default=str),
        "```",
        "",
    ])

    lines.extend([
        "## Recommendations",
        "",
        "1. **Docstring Coverage:** Add docstrings to public APIs.",
        "2. **Refactor Long Functions:** Consider extracting helper functions.",
        "3. **Untested Modules:** Add tests for uncovered internal modules.",
        "4. **Circular Dependencies:** Review import graph for tight coupling.",
        "5. **Risk Remediation:** Address any critical/high severity findings.",
        "",
    ])

    report_path = repo_root / ".apex" / "self-audit-report.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
