from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from app.agents.base import Agent


class SelfAuditAgent(Agent):
    """Agent that audits the Apex codebase itself.

    Usage:
        agent = SelfAuditAgent()
        result = agent.run(project_root=".")
        # result contains risks, missing docstrings, long functions, todos, coverage gaps
    """

    def __init__(self) -> None:
        super().__init__(name="self_audit", role="code_auditor")

    def _find_python_files(self, root: Path) -> list[Path]:
        return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]

    def _analyze_risks(self, files: list[Path]) -> list[dict[str, Any]]:
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

    def _analyze_docstrings(self, files: list[Path]) -> list[dict[str, Any]]:
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

    def _analyze_complexity(self, files: list[Path]) -> list[dict[str, Any]]:
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

    def _find_todos(self, files: list[Path]) -> list[dict[str, Any]]:
        todos = []
        for f in files:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip().lower()
                if "todo" in stripped or "fixme" in stripped or "hack" in stripped:
                    todos.append({"file": str(f), "line": i, "text": line.strip()})
        return todos

    def _coverage_gap(self, app_files: list[Path], test_files: list[Path]) -> dict[str, Any]:
        tested_modules: set[str] = set()
        for tf in test_files:
            text = tf.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("from app."):
                    # from app.module_a import a -> app.module_a
                    module_part = line.split(" import ")[0].replace("from ", "").strip()
                    parts = module_part.split(".")
                    if len(parts) > 1:
                        tested_modules.add(parts[1])
                elif line.startswith("import app."):
                    # import app.module_a -> app.module_a
                    module_part = line.replace("import ", "").strip()
                    parts = module_part.split(".")
                    if len(parts) > 1:
                        tested_modules.add(parts[1])
        app_modules = {f.parts[f.parts.index("app") + 1].replace(".py", "") for f in app_files if "app" in f.parts}
        return {
            "tested_modules": sorted(tested_modules - {""}),
            "untested_modules": sorted(app_modules - tested_modules),
            "total_app_modules": len(app_modules),
            "total_test_files": len(test_files),
        }

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        project_root = Path(kwargs.get("project_root", ".")).resolve()
        app_dir = project_root / "app"
        tests_dir = project_root / "tests"

        app_files = self._find_python_files(app_dir)
        test_files = self._find_python_files(tests_dir)

        risks = self._analyze_risks(app_files)
        missing_docs = self._analyze_docstrings(app_files)
        long_funcs = self._analyze_complexity(app_files)
        todos = self._find_todos(app_files + test_files)
        cov = self._coverage_gap(app_files, test_files)

        return {
            "agent": "self_audit",
            "findings": risks,
            "missing_docstrings_count": len(missing_docs),
            "missing_docstrings_sample": missing_docs[:20],
            "long_functions_count": len(long_funcs),
            "long_functions_sample": long_funcs[:20],
            "todos_count": len(todos),
            "todos_sample": todos[:20],
            "coverage_gap": cov,
        }
