from __future__ import annotations

"""TestStubAgent — Finds test coverage gaps and generates stubs."""

import ast
from pathlib import Path
from typing import Any

from app.agents.base import Agent
from app.engine.skip_dirs import iter_source_files


class TestStubAgent(Agent):
    """Agent: finds missing tests and generates stubs."""

    # Not a pytest test class despite the "Test" prefix — stop collection.
    __test__ = False

    def __init__(self, name: str = "test_stub", **kwargs: Any) -> None:
        super().__init__(name=name, role="test_coverage_analyst", **kwargs)
        self.project_root: Path | None = None
        self._existing_tests: set[str] = set()

    def _execute(self, project_root: str | Path = ".", generate: bool = False, **kwargs: Any) -> dict[str, Any]:
        root = Path(project_root).resolve()
        self.project_root = root
        self._load_existing_tests(root)

        gaps: list[dict[str, Any]] = []
        generated: list[str] = []
        total_functions = 0
        tested_functions = 0

        files = self._discover_source_files(root)
        for rel_path in files:
            full = root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            file_gaps, file_total, file_tested = self._scan_file(rel_path, source)
            gaps.extend(file_gaps)
            total_functions += file_total
            tested_functions += file_tested

        if generate:
            generated = self._generate_stubs(root, gaps)

        if gaps:
            self.send(
                topic="test.coverage.gap",
                payload={"count": len(gaps), "coverage": round(tested_functions / max(total_functions, 1), 2)},
            )

        return {
            "agent": self.name,
            "role": self.role,
            "total_functions": total_functions,
            "tested_functions": tested_functions,
            "coverage_ratio": round(tested_functions / max(total_functions, 1), 2),
            "gaps_found": len(gaps),
            "stubs_generated": generated,
            "gaps": gaps,
        }

    def _load_existing_tests(self, root: Path) -> None:
        tests_path = root / "tests"
        if tests_path.exists():
            for test_file in tests_path.rglob("*.py"):
                try:
                    source = test_file.read_text(encoding="utf-8")
                    tree = ast.parse(source)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                            self._existing_tests.add(node.name)
                except (SyntaxError, OSError, RecursionError, MemoryError):
                    continue

    def _discover_source_files(self, root: Path) -> list[str]:
        return [
            str(p.relative_to(root).as_posix())
            for p in iter_source_files(root)
            if "test_" not in p.name and "tests" not in p.parts
        ]

    def _scan_file(self, rel_path: str, source: str) -> tuple[list[dict[str, Any]], int, int]:
        gaps: list[dict[str, Any]] = []
        total = 0
        tested = 0
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
            return gaps, total, tested

        module_name = Path(rel_path).stem
        test_file_name = f"test_{module_name}.py"

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                total += 1
                test_name = f"test_{node.name}"
                if test_name in self._existing_tests:
                    tested += 1
                else:
                    gaps.append(
                        {
                            "source_file": rel_path,
                            "symbol_name": node.name,
                            "symbol_type": "function",
                            "test_file": test_file_name,
                        }
                    )
        return gaps, total, tested

    def _generate_stubs(self, root: Path, gaps: list[dict[str, Any]]) -> list[str]:
        generated: list[str] = []
        test_dir = root / "tests"
        test_dir.mkdir(exist_ok=True)

        by_file: dict[str, list[dict[str, Any]]] = {}
        for gap in gaps:
            by_file.setdefault(gap["test_file"], []).append(gap)

        for test_file_name, file_gaps in by_file.items():
            test_file = test_dir / test_file_name
            if test_file.exists():
                continue
            test_file.parent.mkdir(parents=True, exist_ok=True)
            stubs = [self._create_stub(g) for g in file_gaps]
            content = "from __future__ import annotations\n\nimport pytest\n\n\n" + "\n\n".join(stubs)
            test_file.write_text(content, encoding="utf-8")
            generated.append(str(test_file.relative_to(root).as_posix()))

        return generated

    def _create_stub(self, gap: dict[str, Any]) -> str:
        return f'''def test_{gap["symbol_name"]}():
    """Test {gap["symbol_name"]} from {gap["source_file"]}."""
    assert True, "Stub test — implement real assertions"'''
