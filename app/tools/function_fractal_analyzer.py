from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


class FunctionFractalAnalyzer:
    """Analyze functions/classes within a file to produce mini-fractal claims.

    This complements file-level analysis by zooming into each function
    and detecting risks, missing docs, complexity, and cross-file impact.
    """

    RISK_PATTERNS = {
        "eval": "Uses eval() — arbitrary code execution risk",
        "exec": "Uses exec() — arbitrary code execution risk",
        "os.system": "Uses os.system() — shell injection risk",
        "subprocess.call": "Uses subprocess without shell=False — injection risk",
        "pickle.loads": "Uses pickle.loads() — deserialization risk",
        "yaml.load": "Uses yaml.load() without Loader — arbitrary object risk",
        "input": "Uses input() in Python 2 style — security concern",
        "__import__": "Dynamic import — potential code injection",
    }

    def analyze_file(self, file_path: str | Path) -> list[dict[str, Any]]:
        path = Path(file_path)
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        results = []
        module_name = self._module_name_from_path(path)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_info = self._analyze_function(node, module_name, source)
                results.append(fn_info)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn_info = self._analyze_function(item, module_name, source, class_name=node.name)
                        results.append(fn_info)

        return results

    def _analyze_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, module_name: str, source: str, class_name: str | None = None
    ) -> dict[str, Any]:
        name = f"{class_name}.{node.name}" if class_name else node.name
        full_name = f"{module_name}::{name}"

        has_docstring = ast.get_docstring(node) is not None
        risks = []
        risk_score = 0.0

        # Check for risk patterns
        fn_source = ast.unparse(node) if hasattr(ast, "unparse") else ""
        for pattern, description in self.RISK_PATTERNS.items():
            if pattern in fn_source:
                risks.append(description)
                risk_score += 0.3

        # Missing docstring
        if not has_docstring:
            risks.append("missing_docstring")
            risk_score += 0.1

        # Long function heuristic
        lines = fn_source.count("\n")
        if lines > 30:
            risks.append(f"long_function ({lines} lines)")
            risk_score += 0.1

        # Too many arguments
        arg_count = len(node.args.args) + len(node.args.kwonlyargs)
        if arg_count > 5:
            risks.append(f"too_many_arguments ({arg_count})")
            risk_score += 0.1

        # Bare except
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.ExceptHandler) and subnode.type is None:
                risks.append("bare_except")
                risk_score += 0.2

        return {
            "name": name,
            "full_name": full_name,
            "module": module_name,
            "has_docstring": has_docstring,
            "risks": risks,
            "risk_score": round(min(risk_score, 1.0), 2),
            "line_count": lines,
            "arg_count": arg_count,
        }

    def build_call_graph(self, project_root: str | Path) -> dict[str, dict[str, Any]]:
        """Build a cross-file call graph: who calls whom."""
        root = Path(project_root)
        graph: dict[str, dict[str, Any]] = {}
        all_functions: dict[str, str] = {}  # full_name -> file_path

        # First pass: collect all functions
        for py_file in root.rglob("*.py"):
            if "test_" in py_file.name or py_file.name.startswith("test"):
                continue
            module = self._module_name_from_path(py_file)
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    # Try to find parent class
                    for parent in ast.walk(tree):
                        if isinstance(parent, ast.ClassDef) and node in parent.body:
                            fn_name = f"{parent.name}.{node.name}"
                            break
                    full = f"{module}::{fn_name}"
                    all_functions[full] = str(py_file)
                    graph[full] = {"callees": set(), "callers": set(), "file": str(py_file)}

        # Second pass: find calls
        for py_file in root.rglob("*.py"):
            if "test_" in py_file.name or py_file.name.startswith("test"):
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except SyntaxError:
                continue

            # Determine current module and imported names
            current_module = self._module_name_from_path(py_file)
            imports: dict[str, str] = {}  # alias -> full_module
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[alias.asname or alias.name] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imports[name] = mod

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    for parent in ast.walk(tree):
                        if isinstance(parent, ast.ClassDef) and node in parent.body:
                            fn_name = f"{parent.name}.{node.name}"
                            break
                    caller = f"{current_module}::{fn_name}"
                    if caller not in graph:
                        continue

                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Call):
                            callee = self._resolve_call(sub, imports, current_module, all_functions)
                            if callee and callee in graph:
                                graph[caller]["callees"].add(callee)
                                graph[callee]["callers"].add(caller)

        # Convert sets to lists for JSON serialization
        for key in graph:
            graph[key]["callees"] = sorted(graph[key]["callees"])
            graph[key]["callers"] = sorted(graph[key]["callers"])

        return graph

    def compute_cross_file_impact(self, project_root: str | Path) -> dict[str, dict[str, Any]]:
        """For each risky function, find all downstream callers across files."""
        graph = self.build_call_graph(project_root)
        impact: dict[str, dict[str, Any]] = {}

        for full_name, info in graph.items():
            # Heuristic: if function has 'risky' patterns or high risk score
            file_path = info["file"]
            try:
                file_results = self.analyze_file(file_path)
            except Exception:
                continue
            fn_result = next((r for r in file_results if r["full_name"] == full_name), None)
            if fn_result and (fn_result["risk_score"] >= 0.3 or any("risk" in r.lower() for r in fn_result["risks"])):
                downstream = set()
                visited = set()
                queue = list(info["callers"])
                while queue:
                    caller = queue.pop(0)
                    if caller in visited:
                        continue
                    visited.add(caller)
                    downstream.add(caller)
                    queue.extend(graph.get(caller, {}).get("callers", []))
                impact[full_name] = {
                    "risks": fn_result["risks"],
                    "risk_score": fn_result["risk_score"],
                    "downstream": sorted(downstream),
                    "downstream_count": len(downstream),
                }

        return impact

    def _module_name_from_path(self, path: Path) -> str:
        # Simple heuristic: relative path without .py, / -> .
        parts = path.parts
        # Find 'app' or project root
        try:
            idx = parts.index("app")
            rel = parts[idx:]
        except ValueError:
            rel = parts[-2:] if len(parts) >= 2 else parts
        name = ".".join(rel)[:-3] if str(rel[-1]).endswith(".py") else ".".join(rel)
        return name

    def _resolve_call(
        self, node: ast.Call, imports: dict[str, str], current_module: str, all_functions: dict[str, str]
    ) -> str | None:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in imports:
                imported = imports[name]
                candidate = f"{imported}::{name}"
                if candidate in all_functions:
                    return candidate
                # Maybe imported is module, function name is same
                candidate2 = f"{imported}::{name}"
                if candidate2 in all_functions:
                    return candidate2
            # Local function
            local = f"{current_module}::{name}"
            if local in all_functions:
                return local
        elif isinstance(node.func, ast.Attribute):
            # obj.method() — hard to resolve without type inference
            pass
        return None
