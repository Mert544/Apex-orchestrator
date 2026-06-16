#!/usr/bin/env python3
"""Apex Self-Audit: Analyze the Apex codebase using its own tools.

Usage:
    python scripts/self_audit.py > .apex/self-audit-report.md
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


def find_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]


def _name_call_risk(func: ast.Name) -> tuple[str, str] | None:
    if func.id == "eval":
        return ("eval()", "critical")
    if func.id == "exec":
        return ("exec()", "critical")
    return None


def _attr_call_risk(func: ast.Attribute) -> tuple[str, str] | None:
    if not (isinstance(func.value, ast.Name)):
        return None
    if func.attr == "system" and func.value.id == "os":
        return ("os.system()", "high")
    if func.attr == "loads" and func.value.id == "pickle":
        return ("pickle.loads()", "high")
    return None


def _node_risk(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return _name_call_risk(node.func)
        if isinstance(node.func, ast.Attribute):
            return _attr_call_risk(node.func)
    if isinstance(node, ast.ExceptHandler) and node.type is None:
        return ("bare except", "medium")
    return None


def _risks_in_file(f: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        hit = _node_risk(node)
        if hit is not None:
            found.append({"file": str(f), "line": node.lineno, "risk": hit[0], "severity": hit[1]})
    return found


def analyze_risks(files: list[Path]) -> list[dict[str, Any]]:
    risks = []
    for f in files:
        risks.extend(_risks_in_file(f))
    return risks


def analyze_docstrings(files: list[Path]) -> list[dict[str, Any]]:
    missing = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))) and (not ast.get_docstring(node)):
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
            if (isinstance(node, ast.ImportFrom)) and (node.module and node.module.startswith("app.")):
                imports.append(node.module)
        if imports:
            graph[mod] = sorted(set(imports))
    return graph


def _render_risk_section(risks: list[dict[str, Any]]) -> list[str]:
    out = ["## Risk Analysis", ""]
    if risks:
        out.append("| File | Line | Risk | Severity |")
        out.append("|------|------|------|----------|")
        for r in risks:
            out.append(f"| {r['file']} | {r['line']} | {r['risk']} | {r['severity']} |")
    else:
        out.append("No critical risks detected. ✅")
    out.append("")
    return out


def _render_docstring_section(missing_docs: list[dict[str, Any]]) -> list[str]:
    out = ["## Missing Docstrings", f"**Total:** {len(missing_docs)}", ""]
    if missing_docs:
        out.append("| File | Line | Name | Type |")
        out.append("|------|------|------|------|")
        for m in missing_docs[:50]:
            out.append(f"| {m['file']} | {m['line']} | {m['name']} | {m['type']} |")
        if len(missing_docs) > 50:
            out.append("| ... | ... | ... | ... |")
            out.append(f"_Showing first 50 of {len(missing_docs)}_")
    out.append("")
    return out


def _render_long_funcs_section(long_funcs: list[dict[str, Any]]) -> list[str]:
    out = ["## Long Functions (>50 lines)", f"**Total:** {len(long_funcs)}", ""]
    if long_funcs:
        out.append("| File | Line | Name | Lines |")
        out.append("|------|------|------|-------|")
        for lf in long_funcs[:30]:
            out.append(f"| {lf['file']} | {lf['line']} | {lf['name']} | {lf['lines']} |")
        if len(long_funcs) > 30:
            out.append(f"_Showing first 30 of {len(long_funcs)}_")
    out.append("")
    return out


def _render_todos_section(todos: list[dict[str, Any]]) -> list[str]:
    out = ["## TODO / FIXME / HACK", f"**Total:** {len(todos)}", ""]
    if todos:
        out.append("| File | Line | Text |")
        out.append("|------|------|------|")
        for t in todos[:30]:
            out.append(f"| {t['file']} | {t['line']} | {t['text']} |")
        if len(todos) > 30:
            out.append(f"_Showing first 30 of {len(todos)}_")
    out.append("")
    return out


def _render_coverage_section(cov: dict[str, Any]) -> list[str]:
    return [
        "## Coverage Gap Analysis",
        "",
        f"- **Tested Modules:** {', '.join(cov['tested_modules']) or 'None'}",
        f"- **Untested Modules:** {', '.join(cov['untested_modules']) or 'None'}",
        f"- **Total App Modules:** {cov['total_app_modules']}",
        f"- **Total Test Files:** {cov['total_test_files']}",
        "",
    ]


def _render_graph_section(graph: dict[str, list[str]]) -> list[str]:
    return [
        "## Module Import Graph (Internal)",
        "",
        "```json",
        json.dumps(graph, indent=2, default=str),
        "```",
        "",
    ]


def build_report(
    app_files: list[Path],
    test_files: list[Path],
    risks: list[dict[str, Any]],
    missing_docs: list[dict[str, Any]],
    long_funcs: list[dict[str, Any]],
    todos: list[dict[str, Any]],
    cov: dict[str, Any],
    graph: dict[str, list[str]],
) -> list[str]:
    lines = [
        "# Apex Self-Audit Report",
        "",
        "**Date:** 2026-04-25",
        f"**App Files:** {len(app_files)}",
        f"**Test Files:** {len(test_files)}",
        "",
    ]
    lines.extend(_render_risk_section(risks))
    lines.extend(_render_docstring_section(missing_docs))
    lines.extend(_render_long_funcs_section(long_funcs))
    lines.extend(_render_todos_section(todos))
    lines.extend(_render_coverage_section(cov))
    lines.extend(_render_graph_section(graph))
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
    return lines


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

    lines = build_report(
        app_files, test_files, risks, missing_docs, long_funcs, todos, cov, graph
    )

    report_path = repo_root / ".apex" / "self-audit-report.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
