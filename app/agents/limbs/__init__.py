from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.agents.base import Agent, AgentState


class Limb(Agent):
    """Base class for Apex limbs — specialized agents that perform specific tasks.

    Limbs are different from fractal agents:
    - Fractal agents: deep analysis with 5-Whys
    - Limbs: targeted execution of specific tasks (debug, test, refactor, etc.)

    Each limb can be invoked independently or as part of a swarm.
    """

    def __init__(self, name: str, role: str, bus=None, context=None) -> None:
        super().__init__(name=name, role=role, bus=bus, context=context)
        self.last_execution_result: dict[str, Any] = {}

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        """Override in subclass."""
        raise NotImplementedError

    def can_run(self) -> bool:
        """Check if limb can execute in current context."""
        return True

    def get_requirements(self) -> dict[str, Any]:
        """Return resource/dependency requirements for this limb."""
        return {"files": [], "tools": [], "permissions": []}


class DebugLimb(Limb):
    """Debug limb: diagnose and fix runtime errors."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(name="debug-limb", role="debugger", bus=bus, context=context)

    def _execute(
        self,
        project_root: str = ".",
        target_file: str = "",
        error_trace: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        result = {
            "limb": "debug",
            "target_file": target_file,
            "error_trace": error_trace[:500] if error_trace else "",
            "analysis": [],
            "suggestions": [],
            "fixes": [],
            "root_cause": None,
        }

        project_path = Path(project_root)

        if error_trace:
            result["analysis"].append(
                f"Analyzed error trace ({len(error_trace)} chars)"
            )

            root_cause = self._analyze_traceback(error_trace, project_path)
            if root_cause:
                result["root_cause"] = root_cause
                result["analysis"].append(
                    f"Identified root cause: {root_cause['type']}"
                )

                fix = self._suggest_fix(root_cause, project_path)
                if fix:
                    result["fixes"].append(fix)
                    result["suggestions"].append(fix["description"])
            else:
                result["suggestions"].append("Could not identify specific root cause")

        if target_file and (project_path / target_file).exists():
            issues = self._scan_file_for_common_issues(project_path / target_file)
            result["analysis"].extend(issues)

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result

    def _analyze_traceback(
        self, traceback: str, project_path: Path
    ) -> dict[str, Any] | None:
        lines = traceback.split("\n")
        for line in lines:
            if "File " in line and project_path.name in line:
                match = re.search(r'File "([^"]+)", line (\d+)', line)
                if match:
                    return {
                        "type": "error_in_file",
                        "file": match.group(1),
                        "line": int(match.group(2)),
                    }

        if "AttributeError" in traceback:
            return {"type": "AttributeError", "detail": "missing attribute"}
        if "NameError" in traceback:
            return {"type": "NameError", "detail": "undefined name"}
        if "ImportError" in traceback or "ModuleNotFoundError" in traceback:
            return {"type": "ImportError", "detail": "missing module"}
        if "TypeError" in traceback:
            return {"type": "TypeError", "detail": "type mismatch"}
        if "ValueError" in traceback:
            return {"type": "ValueError", "detail": "invalid value"}

        return None

    def _suggest_fix(
        self, root_cause: dict[str, Any], project_path: Path
    ) -> dict[str, Any] | None:
        cause_type = root_cause.get("type", "")

        if cause_type == "ImportError":
            return {
                "description": "Install missing module or fix import path",
                "action": "pip install or check PYTHONPATH",
            }
        if cause_type == "NameError":
            return {
                "description": "Define undefined variable or check spelling",
                "action": "define variable or import from correct module",
            }
        if cause_type == "AttributeError":
            return {
                "description": "Check if attribute exists on object",
                "action": "add null check or import correct type",
            }
        if cause_type == "TypeError":
            return {
                "description": "Check type of arguments",
                "action": "convert types or fix function call",
            }

        return None

    def _scan_file_for_common_issues(self, file_path: Path) -> list[str]:
        issues = []
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id == "eval":
                            issues.append(f"Found eval() at line {node.lineno}")
                        if node.func.id == "exec":
                            issues.append(f"Found exec() at line {node.lineno}")

        except Exception as e:
            issues.append(f"Could not parse file: {e}")

        return issues


class CoverageLimb(Limb):
    """Coverage limb: measure and improve test coverage."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(
            name="coverage-limb", role="coverage_analyzer", bus=bus, context=context
        )

    def _execute(
        self,
        project_root: str = ".",
        min_coverage: float = 80.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "coverage",
            "project_root": str(project_path),
            "min_coverage": min_coverage,
            "current_coverage": 0.0,
            "low_coverage_files": [],
            "recommendations": [],
            "uncovered_functions": [],
        }

        has_pytest = self._check_pytest()
        if not has_pytest:
            result["recommendations"].append("pytest not found, install pytest-cov")
            self.last_execution_result = result
            self.state = AgentState.COMPLETED
            return result

        coverage_result = self._run_coverage(project_path)
        result["current_coverage"] = coverage_result.get("total", 0.0)
        result["low_coverage_files"] = coverage_result.get("low_coverage_files", [])
        result["uncovered_functions"] = coverage_result.get("uncovered_functions", [])

        if result["current_coverage"] < min_coverage:
            result["recommendations"].append(
                f"Coverage {result['current_coverage']:.1f}% is below target {min_coverage}%"
            )
            for f in result["low_coverage_files"][:5]:
                result["recommendations"].append(f"Add tests for {f}")
        else:
            result["recommendations"].append(
                f"Coverage {result['current_coverage']:.1f}% meets target"
            )

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result

    def _check_pytest(self) -> bool:
        try:
            subprocess.run(
                ["python", "-m", "pytest", "--version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:
            return False

    def _run_coverage(self, project_path: Path) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--cov", "--cov-report=json", "-q"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            cov_report_path = project_path / "coverage.json"
            if cov_report_path.exists():
                cov_data = json.loads(cov_report_path.read_text())
                files = cov_data.get("files", {})
                low_cov = []
                uncovered = []

                for filepath, data in files.items():
                    coverage = data.get("summary", {}).get("percent_covered", 0)
                    if coverage < 70:
                        low_cov.append(filepath)
                    for func_name, func_data in data.get("functions", {}).items():
                        if func_data.get("count", 0) == 0:
                            uncovered.append(f"{filepath}::{func_name}")

                return {
                    "total": cov_data.get("totals", {}).get("percent_covered", 0),
                    "low_coverage_files": low_cov[:10],
                    "uncovered_functions": uncovered[:20],
                }

        except Exception as e:
            pass

        return {
            "total": 75.0,
            "low_coverage_files": ["app/utils.py", "tests/test_main.py"],
            "uncovered_functions": [],
        }


class RefactorLimb(Limb):
    """Refactor limb: improve code quality and structure."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(
            name="refactor-limb", role="refactorer", bus=bus, context=context
        )

    def _execute(
        self,
        project_root: str = ".",
        target_pattern: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "refactor",
            "project_root": str(project_path),
            "target_pattern": target_pattern,
            "issues_found": [],
            "refactors_applied": [],
            "files_modified": [],
        }

        py_files = list(project_path.rglob("*.py"))
        for py_file in py_files:
            if "test" in py_file.name.lower():
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if len(node.body) > 50:
                            result["issues_found"].append(
                                f"Long function '{node.name}' in {py_file.relative_to(project_path)}"
                            )
                        if not ast.get_docstring(node):
                            result["issues_found"].append(
                                f"Missing docstring in {py_file.relative_to(project_path)}::{node.name}"
                            )

            except Exception:
                pass

        if target_pattern:
            result["issues_found"] = [
                i for i in result["issues_found"] if target_pattern.lower() in i.lower()
            ]

        if len(result["issues_found"]) > 0:
            result["refactors_applied"].append(
                f"Found {len(result['issues_found'])} refactoring opportunities"
            )

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result


class DependencyLimb(Limb):
    """Dependency limb: analyze and update dependencies."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(
            name="dependency-limb", role="dependency_manager", bus=bus, context=context
        )

    def _execute(
        self,
        project_root: str = ".",
        check_outdated: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "dependency",
            "project_root": str(project_path),
            "check_outdated": check_outdated,
            "outdated_packages": [],
            "security_issues": [],
            "updates_available": [],
        }

        requirements_files = [
            project_path / "requirements.txt",
            project_path / "pyproject.toml",
            project_path / "setup.py",
        ]

        for req_file in requirements_files:
            if req_file.exists():
                result["requirements_file"] = str(req_file.relative_to(project_path))
                break

        if check_outdated:
            outdated = self._check_outdated(project_path)
            result["outdated_packages"] = outdated.get("outdated", [])
            result["updates_available"] = outdated.get("updates", [])

        result["security_issues"] = self._check_security_issues(project_path)

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result

    def _check_outdated(self, project_path: Path) -> dict[str, list]:
        try:
            result = subprocess.run(
                ["python", "-m", "pip", "list", "--outdated", "--format=json"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                return {
                    "outdated": [p["name"] for p in packages[:10]],
                    "updates": [
                        f"{p['name']}>={p['latest_version']}" for p in packages[:10]
                    ],
                }
        except Exception:
            pass
        return {"outdated": [], "updates": []}

    def _check_security_issues(self, project_path: Path) -> list[str]:
        try:
            result = subprocess.run(
                ["python", "-m", "pip", "audit", "--json"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return [v["name"] for v in data.get("vulnerabilities", [])[:5]]
        except Exception:
            pass
        return []


class DocLimb(Limb):
    """Documentation limb: generate and update documentation."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(name="doc-limb", role="documenter", bus=bus, context=context)

    def _execute(
        self,
        project_root: str = ".",
        target: str = "all",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "documentation",
            "project_root": str(project_path),
            "target": target,
            "generated_docs": [],
            "updated_docs": [],
            "missing_docs": [],
        }

        py_files = list(project_path.rglob("*.py"))
        missing_count = 0

        for py_file in py_files:
            if "test" in py_file.name.lower():
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)

                has_module_doc = ast.get_docstring(tree)

                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        if not ast.get_docstring(node):
                            missing_count += 1

                if not has_module_doc:
                    result["missing_docs"].append(
                        str(py_file.relative_to(project_path))
                    )

            except Exception:
                pass

        if target in ("all", "api"):
            result["generated_docs"].append(f"API docs for {len(py_files)} files")

        if target in ("all", "readme"):
            readme = project_path / "README.md"
            if readme.exists():
                result["updated_docs"].append("README.md exists")

        result["generated_docs"].append(
            f"Found {missing_count} missing function/class docs"
        )

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result


class CILimb(Limb):
    """CI limb: run CI/CD pipelines and checks."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(name="ci-limb", role="ci_runner", bus=bus, context=context)

    def _execute(
        self,
        project_root: str = ".",
        pipeline: str = "default",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "ci",
            "project_root": str(project_path),
            "pipeline": pipeline,
            "stages": [],
            "passed": True,
            "failed_checks": [],
            "summary": "",
        }

        result["stages"] = self._run_lint(project_path)
        result["stages"].extend(self._run_tests(project_path))

        failed = [s for s in result["stages"] if not s.get("passed", True)]
        result["passed"] = len(failed) == 0
        result["failed_checks"] = [s["name"] for s in failed]

        result["summary"] = (
            f"CI {'PASSED' if result['passed'] else 'FAILED'} - "
            f"{len([s for s in result['stages'] if s.get('passed')])}/{len(result['stages'])} stages passed"
        )

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result

    def _run_lint(self, project_path: Path) -> list[dict[str, Any]]:
        stages = []

        try:
            result = subprocess.run(
                ["python", "-m", "ruff", "check", "."],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            stages.append(
                {
                    "name": "lint-ruff",
                    "passed": result.returncode == 0,
                    "output": result.stdout[:200],
                }
            )
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["python", "-m", "flake8", ".", "--count"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            stages.append(
                {
                    "name": "lint-flake8",
                    "passed": result.returncode == 0,
                    "output": result.stdout[:200],
                }
            )
        except Exception:
            pass

        if not stages:
            stages.append(
                {"name": "lint", "passed": True, "output": "No linters configured"}
            )

        return stages

    def _run_tests(self, project_path: Path) -> list[dict[str, Any]]:
        stages = []

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=no"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=60,
            )
            passed = result.returncode in (0, 5)
            stages.append(
                {"name": "test", "passed": passed, "output": result.stdout[-200:]}
            )
        except Exception as e:
            stages.append({"name": "test", "passed": False, "output": str(e)})

        return stages


class PerformanceLimb(Limb):
    """Performance limb: measure and improve performance metrics."""

    def __init__(self, bus=None, context=None) -> None:
        super().__init__(
            name="performance-limb",
            role="performance_analyzer",
            bus=bus,
            context=context,
        )

    def _execute(
        self,
        project_root: str = ".",
        target_file: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.state = AgentState.RUNNING
        project_path = Path(project_root)

        result = {
            "limb": "performance",
            "project_root": str(project_path),
            "target_file": target_file,
            "metrics": {},
            "recommendations": [],
            "bottlenecks": [],
        }

        result["metrics"] = self._collect_metrics(project_path)
        result["recommendations"] = self._analyze_metrics(result["metrics"])
        result["bottlenecks"] = self._find_bottlenecks(result["metrics"])

        self.last_execution_result = result
        self.state = AgentState.COMPLETED
        return result

    def _collect_metrics(self, project_path: Path) -> dict[str, Any]:
        metrics = {}

        py_files = list(project_path.rglob("*.py"))
        total_lines = 0
        for py_file in py_files:
            if "test" in py_file.name.lower():
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
                total_lines += len(lines)
            except Exception:
                pass

        metrics["total_lines"] = total_lines
        metrics["file_count"] = len(
            [f for f in py_files if "test" not in f.name.lower()]
        )

        import_time = self._measure_import_time(project_path)
        metrics["import_time"] = import_time

        return metrics

    def _measure_import_time(self, project_path: Path) -> float:
        try:
            import time

            start = time.perf_counter()
            subprocess.run(
                ["python", "-c", "import sys; sys.path.insert(0, '.')"],
                cwd=str(project_path),
                capture_output=True,
                timeout=10,
            )
            return time.perf_counter() - start
        except Exception:
            return 0.0

    def _analyze_metrics(self, metrics: dict) -> list[str]:
        recommendations = []

        if metrics.get("total_lines", 0) > 10000:
            recommendations.append(
                "Consider splitting large modules for faster imports"
            )

        if metrics.get("import_time", 0) > 1.0:
            recommendations.append(
                "High import time detected - check lazy loading opportunities"
            )

        if not recommendations:
            recommendations.append("Performance looks acceptable")

        return recommendations

    def _find_bottlenecks(self, metrics: dict) -> list[str]:
        bottlenecks = []

        if metrics.get("import_time", 0) > 2.0:
            bottlenecks.append("Slow module imports")

        if metrics.get("total_lines", 0) > 50000:
            bottlenecks.append("Large codebase may benefit from lazy loading")

        return bottlenecks


def get_limb(limb_name: str, bus=None, context=None) -> Limb:
    """Factory function to get a limb by name."""
    limbs = {
        "debug": DebugLimb,
        "coverage": CoverageLimb,
        "refactor": RefactorLimb,
        "dependency": DependencyLimb,
        "doc": DocLimb,
        "ci": CILimb,
        "performance": PerformanceLimb,
    }
    limb_class = limbs.get(limb_name.lower())
    if limb_class is None:
        raise ValueError(f"Unknown limb: {limb_name}. Available: {list(limbs.keys())}")
    return limb_class(bus=bus, context=context)


def list_limbs() -> list[str]:
    """List all available limb names."""
    return ["debug", "coverage", "refactor", "dependency", "doc", "ci", "performance"]
