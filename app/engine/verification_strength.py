"""What did "tests passed" actually prove? — coverage-aware verification.

Full-suite verification is only as strong as the suite's interest in what
changed: on a module no test ever references, a green run proves nothing
about the change. This module statically grades that strength, so apply
results and proof-of-fix records can distinguish "verified by tests that
NAME the changed function" from "applied blind — the suite never looks at
this module".

Levels (weakest link across the changed files):
  - ``function``   — a referencing test names a changed function
  - ``module``     — tests import/reference the module, none name the change
  - ``none``       — no test references the module at all (applied blind)
  - ``test-change``— only test files changed (they ARE the suite)

Deterministic, stdlib-only, no execution — it inspects the test files' text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS as _SKIPPED_DIRS
_RANK = {"none": 0, "module": 1, "function": 2}
_MAX_TEST_FILE_BYTES = 400_000  # don't slurp generated monsters


def _is_test_path(rel: str) -> bool:
    p = rel.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or p.startswith(("tests/", "test/")) or "/tests/" in p or "/test/" in p)


def changed_functions(old: str, new: str) -> list[str]:
    """Names of functions whose source differs between ``old`` and ``new``
    (including functions present on only one side). Unparsable sides yield []
    rather than guessing."""
    def _functions(src: str) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return out
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    out[node.name] = ast.get_source_segment(src, node) or node.name
                except Exception:
                    out[node.name] = node.name
        return out

    a, b = _functions(old), _functions(new)
    return sorted(name for name in {*a, *b} if a.get(name) != b.get(name))


def _test_files(root: Path) -> list[tuple[str, str]]:
    """All (relative_path, text) test files under ``root``, deterministic order."""
    out: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in _SKIPPED_DIRS for part in Path(rel).parts):
            continue
        if not _is_test_path(rel):
            continue
        try:
            if path.stat().st_size > _MAX_TEST_FILE_BYTES:
                continue
            out.append((rel, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return out


def _references_module(text: str, rel_path: str) -> bool:
    """Does this test text import/reference the module at ``rel_path``?"""
    dotted = rel_path[:-3].replace("\\", "/").replace("/", ".") if rel_path.endswith(".py") else ""
    if dotted and dotted in text:
        return True
    stem = Path(rel_path).stem
    # `import x` / `from pkg.x import` — the stem as a module token, not a
    # bare word match (function names like `run` would flood otherwise).
    return bool(re.search(rf"(?:^|\n)\s*(?:from|import)\s+[\w.]*\b{re.escape(stem)}\b", text))


def module_referenced_by_suite(project_root: str | Path, rel_path: str) -> bool:
    """Does ANY test file reference this module? (The cheap pre-check the
    test-first shield uses before touching an uncovered module.)"""
    if not rel_path.endswith(".py") or _is_test_path(rel_path):
        return True  # test files and non-Python targets never need a shield
    return any(_references_module(text, rel_path)
               for _rel, text in _test_files(Path(project_root)))


def assess_strength(
    project_root: str | Path,
    changed_files: list[str],
    old_by_path: dict[str, str | None],
    new_by_path: dict[str, str],
) -> dict:
    """Grade how strongly a passing suite vouches for these changes."""
    root = Path(project_root)
    code_files = [f for f in changed_files if f.endswith(".py") and not _is_test_path(f)]
    if not code_files:
        return {"level": "test-change", "changed_functions": [],
                "module_tests": [], "function_tests": []}

    tests = _test_files(root)
    worst = "function"
    all_changed: list[str] = []
    module_tests: list[str] = []
    function_tests: list[str] = []
    for rel in code_files:
        funcs = changed_functions(old_by_path.get(rel) or "", new_by_path.get(rel, ""))
        all_changed += [f"{rel}::{name}" for name in funcs]
        referencing = [(t_rel, text) for t_rel, text in tests
                       if _references_module(text, rel)]
        module_tests += [t_rel for t_rel, _ in referencing]
        naming = [
            t_rel for t_rel, text in referencing
            if any(re.search(rf"\b{re.escape(name)}\b", text) for name in funcs)
        ]
        function_tests += naming
        level = "function" if naming else ("module" if referencing else "none")
        if _RANK[level] < _RANK[worst]:
            worst = level
    return {
        "level": worst,
        "changed_functions": all_changed[:5],
        "module_tests": sorted(dict.fromkeys(module_tests))[:5],
        "function_tests": sorted(dict.fromkeys(function_tests))[:5],
    }
