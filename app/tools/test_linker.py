from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


def count_test_functions(root: str | Path, test_files: list[str]) -> int:
    """Total ``test*`` functions/methods across the given linked test files.

    A depth-aware coverage proxy: one file with many real tests covers a module
    far better than a single thin one, so risk/fragility signals should weigh
    this, not the linked-*file* count (which a single stub would inflate).
    """
    root = Path(root)
    total = 0
    for rel in test_files:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                total += 1
    return total


@dataclass
class TestCoverageResult:
    module_to_tests: dict[str, list[str]] = field(default_factory=dict)
    untested_modules: list[str] = field(default_factory=list)
    critical_untested_modules: list[str] = field(default_factory=list)


class TestLinker:
    __test__ = False

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def analyze(self, critical_modules: list[str] | None = None) -> TestCoverageResult:
        critical_modules = critical_modules or []
        tests = self._discover_test_files()
        modules = self._discover_module_files()

        module_to_tests: dict[str, list[str]] = {}
        untested_modules: list[str] = []

        for module in modules:
            linked_tests = self._find_linked_tests(module, tests)
            module_to_tests[module] = linked_tests
            if not linked_tests:
                untested_modules.append(module)

        critical_untested_modules = [m for m in critical_modules if m in set(untested_modules)]

        return TestCoverageResult(
            module_to_tests=module_to_tests,
            untested_modules=untested_modules,
            critical_untested_modules=critical_untested_modules,
        )

    def _discover_test_files(self) -> list[Path]:
        tests: list[Path] = []
        for path in self.root.rglob("*.py"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root)).lower()
            if rel.startswith("tests/") or "/tests/" in f"/{rel}/" or path.stem.startswith("test_"):
                tests.append(path)
        return tests

    def _discover_module_files(self) -> list[str]:
        modules: list[str] = []
        for path in self.root.rglob("*.py"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root))
            rel_lower = rel.lower()
            if rel_lower.startswith("tests/") or "/tests/" in f"/{rel_lower}/" or path.stem.startswith("test_"):
                continue
            if path.stem == "__init__":
                continue
            modules.append(rel)
        return sorted(modules)

    def _find_linked_tests(self, module: str, tests: list[Path]) -> list[str]:
        module_path = Path(module)
        module_stem = module_path.stem.lower()
        module_dotted = ".".join(module_path.with_suffix("").parts).lower()
        expected_test_name = f"test_{module_stem}"

        linked: list[str] = []
        for test_path in tests:
            rel = str(test_path.relative_to(self.root))
            test_stem = test_path.stem.lower()
            test_text = self._safe_read(test_path).lower()

            if test_stem == expected_test_name or module_stem in test_stem:
                linked.append(rel)
                continue
            if module_dotted in test_text:
                linked.append(rel)
                continue
            if f"import {module_stem}" in test_text or f"from {module_stem} import" in test_text:
                linked.append(rel)
                continue
            parent_name = module_path.parent.name.lower()
            if parent_name and parent_name in test_text and module_stem in test_text:
                linked.append(rel)
                continue

        return sorted(dict.fromkeys(linked))

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
