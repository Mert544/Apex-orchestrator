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
        "eval(": "Uses eval() — arbitrary code execution risk",
        "exec(": "Uses exec() — arbitrary code execution risk",
        "os.system(": "Uses os.system() — shell injection risk",
        "subprocess.call(": "Uses subprocess without shell=False — injection risk",
        "pickle.loads(": "Uses pickle.loads() — deserialization risk",
        "yaml.load(": "Uses yaml.load() without Loader — arbitrary object risk",
        "input(": "Uses input() in Python 2 style — security concern",
        "__import__(": "Dynamic import — potential code injection",
    }

    def __init__(self, max_files: int = 0) -> None:
        self.max_files = max_files
        self._file_cache: dict[str, tuple[float, ast.AST, str]] = {}
        self._call_graph_cache: dict[str, Any] | None = None

    def _get_cached_ast(self, path: Path) -> tuple[ast.AST, str] | None:
        """Return (tree, source) from cache or parse and cache by (path, mtime)."""
        path_str = str(path.resolve())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        cached = self._file_cache.get(path_str)
        if cached is not None:
            cached_mtime, tree, source = cached
            if cached_mtime == mtime:
                return tree, source

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            return None

        self._file_cache[path_str] = (mtime, tree, source)
        return tree, source

    @staticmethod
    def _is_test_file(path: Path) -> bool:
        name = path.name
        return name.startswith("test") or "test_" in name

    def analyze_file(self, file_path: str | Path) -> list[dict[str, Any]]:
        path = Path(file_path)
        parsed = self._get_cached_ast(path)
        if parsed is None:
            return []
        tree, source = parsed

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

        # Check for risk patterns via AST Call nodes (avoids false positives in strings)
        fn_source = ast.unparse(node) if hasattr(ast, "unparse") else ""
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                if isinstance(subnode.func, ast.Name):
                    if subnode.func.id == "eval":
                        risks.append("Uses eval() — arbitrary code execution risk")
                        risk_score += 0.3
                    elif subnode.func.id == "exec":
                        risks.append("Uses exec() — arbitrary code execution risk")
                        risk_score += 0.3
                    elif subnode.func.id == "input":
                        risks.append("Uses input() in Python 2 style — security concern")
                        risk_score += 0.3
                    elif subnode.func.id == "__import__":
                        risks.append("Dynamic import — potential code injection")
                        risk_score += 0.3
                elif isinstance(subnode.func, ast.Attribute):
                    chain = []
                    current = subnode.func
                    while isinstance(current, ast.Attribute):
                        chain.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        chain.append(current.id)
                    chain_str = ".".join(reversed(chain))
                    if chain_str == "os.system":
                        risks.append("Uses os.system() — shell injection risk")
                        risk_score += 0.3
                    elif chain_str == "subprocess.call":
                        risks.append("Uses subprocess without shell=False — injection risk")
                        risk_score += 0.3
                    elif chain_str == "pickle.loads":
                        risks.append("Uses pickle.loads() — deserialization risk")
                        risk_score += 0.3
                    elif chain_str == "yaml.load":
                        risks.append("Uses yaml.load() without Loader — arbitrary object risk")
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
        cache_key = str(root.resolve())
        if self._call_graph_cache is not None and self._call_graph_cache.get("key") == cache_key:
            return self._call_graph_cache["graph"]

        graph: dict[str, dict[str, Any]] = {}
        all_functions: dict[str, str] = {}  # full_name -> file_path

        # Collect Python files once, skipping tests efficiently
        py_files = [f for f in root.rglob("*.py") if not self._is_test_file(f)]
        if self.max_files > 0:
            py_files = py_files[:self.max_files]

        file_infos: list[tuple[str, dict[str, str], list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]]] = []

        # First pass: collect all functions and imports with a single parent map per file
        for py_file in py_files:
            parsed = self._get_cached_ast(py_file)
            if parsed is None:
                continue
            tree, _ = parsed
            module = self._module_name_from_path(py_file)

            # Build parent-pointer map in one traversal
            parent_map: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parent_map[child] = parent

            imports: dict[str, str] = {}
            functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[alias.asname or alias.name] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imports[name] = mod
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    current = node
                    while current in parent_map:
                        current = parent_map[current]
                        if isinstance(current, ast.ClassDef):
                            fn_name = f"{current.name}.{node.name}"
                            break
                    full = f"{module}::{fn_name}"
                    all_functions[full] = str(py_file)
                    graph[full] = {"callees": set(), "callers": set(), "file": str(py_file)}
                    functions.append((full, node))

            file_infos.append((module, imports, functions))

        # Second pass: find calls
        for module, imports, functions in file_infos:
            for caller, node in functions:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        callee = self._resolve_call(sub, imports, module, all_functions)
                        if callee and callee in graph:
                            graph[caller]["callees"].add(callee)
                            graph[callee]["callers"].add(caller)

        # Convert sets to lists for JSON serialization
        for key in graph:
            graph[key]["callees"] = sorted(graph[key]["callees"])
            graph[key]["callers"] = sorted(graph[key]["callers"])

        self._call_graph_cache = {"key": cache_key, "graph": graph}
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
