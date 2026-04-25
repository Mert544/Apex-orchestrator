from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any


class TargetedTestSelector:
    """Selects relevant tests based on changed files and coverage data.

    Features:
    - Find tests related to modified files
    - Prioritize tests by coverage data
    - Support pytest markers
    - Configurable test selection strategy

    Usage:
        selector = TargetedTestSelector(project_root=".")
        tests = selector.select_tests(changed_files=["app/main.py"])
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = Path(project_root)

    def select_tests(
        self,
        changed_files: list[str] | None = None,
        uncovered_functions: list[str] | None = None,
        markers: list[str] | None = None,
        max_tests: int = 20,
    ) -> list[str]:
        """Select relevant tests based on changed files and other criteria."""
        selected = []

        if changed_files:
            tests = self._find_tests_for_files(changed_files)
            selected.extend(tests)

        if uncovered_functions:
            tests = self._find_tests_for_functions(uncovered_functions)
            selected.extend(tests)

        selected = list(dict.fromkeys(selected))

        if markers:
            marked_tests = self._filter_by_markers(selected, markers)
            selected = marked_tests

        return selected[:max_tests]

    def _find_tests_for_files(self, files: list[str]) -> list[str]:
        """Find tests related to the given files."""
        tests = []
        tests_dir = self.project_root / "tests"

        if not tests_dir.exists():
            return tests

        for changed_file in files:
            changed_path = Path(changed_file)
            module_name = changed_path.stem

            possible_test_files = [
                tests_dir / f"test_{module_name}.py",
                tests_dir / f"{module_name}_test.py",
                tests_dir / f"test_{changed_path.parent.name}",
            ]

            for test_file in possible_test_files:
                if test_file.exists():
                    tests.append(str(test_file.relative_to(self.project_root)))

            tests.extend(self._find_test_names_in_dir(tests_dir, module_name))

        return tests

    def _find_test_names_in_dir(self, tests_dir: Path, module_name: str) -> list[str]:
        """Find test functions in test files."""
        test_names = []

        for test_file in tests_dir.glob("test_*.py"):
            try:
                content = test_file.read_text(encoding="utf-8")
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if node.name.startswith("test_"):
                            if (
                                module_name in test_file.name
                                or module_name in content[:500]
                            ):
                                test_names.append(f"{test_file.name}::{node.name}")

            except Exception:
                pass

        return test_names

    def _find_tests_for_functions(self, functions: list[str]) -> list[str]:
        """Find tests that cover specific functions."""
        tests = []
        tests_dir = self.project_root / "tests"

        if not tests_dir.exists():
            return tests

        for func in functions:
            func_name = func.split("::")[-1] if "::" in func else func

            for test_file in tests_dir.glob("test_*.py"):
                try:
                    content = test_file.read_text(encoding="utf-8")
                    if func_name in content:
                        tests.append(str(test_file.relative_to(self.project_root)))
                except Exception:
                    pass

        return tests

    def _filter_by_markers(self, tests: list[str], markers: list[str]) -> list[str]:
        """Filter tests by pytest markers."""
        filtered = []

        for test in tests:
            try:
                result = subprocess.run(
                    ["python", "-m", "pytest", test, "--markers", "-q"],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                for marker in markers:
                    if marker in result.stdout:
                        filtered.append(test)
                        break

            except Exception:
                filtered.append(test)

        return filtered if filtered else tests

    def get_test_command(
        self,
        changed_files: list[str] | None = None,
        uncovered_functions: list[str] | None = None,
        markers: list[str] | None = None,
        max_tests: int = 20,
    ) -> list[str]:
        """Get pytest command with selected tests."""
        selected = self.select_tests(
            changed_files=changed_files,
            uncovered_functions=uncovered_functions,
            markers=markers,
            max_tests=max_tests,
        )

        if not selected:
            return ["python", "-m", "pytest", "-q"]

        cmd = ["python", "-m", "pytest"]
        for test in selected:
            if "::" in test:
                parts = test.split("::")
                cmd.append(f"{parts[0]}::{parts[1]}")
            else:
                cmd.append(test)

        return cmd


class TestRunner:
    """Run tests with timeout and result tracking."""

    def __init__(self, project_root: str = ".", timeout: int = 120) -> None:
        self.project_root = Path(project_root)
        self.timeout = timeout

    def run_tests(self, test_args: list[str] | None = None) -> dict[str, Any]:
        """Run tests and return results."""
        cmd = test_args or ["python", "-m", "pytest", "-q", "--tb=short"]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            return {
                "passed": result.returncode in (0, 5),
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "return_code": -1,
                "stdout": "",
                "stderr": f"Tests timed out after {self.timeout}s",
                "success": False,
                "timeout": True,
            }
        except Exception as e:
            return {
                "passed": False,
                "return_code": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False,
                "error": True,
            }

    def run_targeted(
        self,
        changed_files: list[str] | None = None,
        uncovered_functions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run targeted tests based on changes."""
        selector = TargetedTestSelector(self.project_root)
        cmd = selector.get_test_command(
            changed_files=changed_files,
            uncovered_functions=uncovered_functions,
        )

        print(f"[test] Running: {' '.join(cmd)}")
        return self.run_tests(cmd)
