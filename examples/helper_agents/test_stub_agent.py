from __future__ import annotations

"""
TestStubAgent — Finds test coverage gaps and generates test stubs.

Logic:
- Scans source files for functions/classes
- Checks if corresponding test files exist
- Generates pytest stub files for missing tests
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CoverageGap:
    source_file: str
    symbol_name: str
    symbol_type: str
    test_file: str


@dataclass
class TestStubReport:
    gaps: list[CoverageGap] = field(default_factory=list)
    stubs_generated: list[str] = field(default_factory=list)
    total_functions: int = 0
    tested_functions: int = 0

    @property
    def coverage_ratio(self) -> float:
        return round(self.tested_functions / max(self.total_functions, 1), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_functions": self.total_functions,
            "tested_functions": self.tested_functions,
            "coverage_ratio": self.coverage_ratio,
            "gaps_found": len(self.gaps),
            "stubs_generated": self.stubs_generated,
            "gaps": [
                {
                    "source_file": g.source_file,
                    "symbol_name": g.symbol_name,
                    "symbol_type": g.symbol_type,
                    "test_file": g.test_file,
                }
                for g in self.gaps
            ],
        }


class TestStubAgent:
    """Helper agent: finds missing tests and generates stubs."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.report = TestStubReport()
        self._existing_tests: set[str] = set()

    def scan(self, target_files: list[str] | None = None) -> TestStubReport:
        self._load_existing_tests()
        files = self._discover_source_files(target_files)

        for rel_path in files:
            full = self.root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            self._scan_file(rel_path, source)

        return self.report

    def generate_stubs(self) -> list[str]:
        """Generate test stub files for coverage gaps."""
        generated: list[str] = []
        test_dir = self.root / "tests"
        test_dir.mkdir(exist_ok=True)

        for gap in self.report.gaps:
            test_file = test_dir / gap.test_file
            if test_file.exists():
                continue

            test_file.parent.mkdir(parents=True, exist_ok=True)
            stub = self._create_stub(gap)
            test_file.write_text(stub, encoding="utf-8")
            generated.append(str(test_file.relative_to(self.root).as_posix()))

        self.report.stubs_generated = generated
        return generated

    def _load_existing_tests(self) -> None:
        tests_path = self.root / "tests"
        if tests_path.exists():
            for test_file in tests_path.rglob("*.py"):
                try:
                    source = test_file.read_text(encoding="utf-8")
                    tree = ast.parse(source)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                            self._existing_tests.add(node.name)
                except (SyntaxError, OSError):
                    continue

    def _discover_source_files(self, target_files: list[str] | None = None) -> list[str]:
        if target_files:
            return [f for f in target_files if "test_" not in f and "tests/" not in f]
        return [
            str(p.relative_to(self.root).as_posix())
            for p in self.root.rglob("*.py")
            if "test_" not in p.name and "tests" not in p.parts
            and ".apex" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_file(self, rel_path: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        module_name = Path(rel_path).stem
        test_file_name = f"test_{module_name}.py"

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                self.report.total_functions += 1
                test_name = f"test_{node.name}"
                if test_name not in self._existing_tests:
                    self.report.gaps.append(
                        CoverageGap(
                            source_file=rel_path,
                            symbol_name=node.name,
                            symbol_type="function",
                            test_file=test_file_name,
                        )
                    )
                else:
                    self.report.tested_functions += 1

    def _create_stub(self, gap: CoverageGap) -> str:
        return f'''from __future__ import annotations

import pytest


# TODO: Implement test for {gap.symbol_name}
def test_{gap.symbol_name}():
    """Test {gap.symbol_name} from {gap.source_file}."""
    assert True, "Stub test — implement real assertions"
'''


# Plugin registration
__plugin_name__ = "test_stub_agent"

def register(proxy):
    agent = TestStubAgent(proxy.get("project_root", "."))
    proxy.add_hook("before_scan", lambda ctx: agent.scan())
    proxy.add_hook("after_scan", lambda ctx: agent.generate_stubs())
