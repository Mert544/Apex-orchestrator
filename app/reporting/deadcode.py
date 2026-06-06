"""Cross-file dead-code analysis — symbols defined but never referenced.

Unlike the per-file detectors, this reasons across the whole project: it collects
every referenced name (calls, attribute access, imports, ``__all__`` exports —
including from the test suite) and then reports module-level functions/classes
that nothing ever uses.

It is deliberately conservative (decorated symbols, dunders, ``__all__`` exports,
``__init__``/test files, and entry-point names are excluded) but dynamic use
(getattr, plugin registries, string dispatch) can't be seen statically — so this
is a *surfaced* signal ("verify before removing"), never an auto-removal and not
a grade input.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_SKIP_DIRS = {".git", "__pycache__", ".apex", ".epistemic", ".venv", "venv",
              "node_modules", "dist", "build", ".tox", ".mypy_cache"}


def _iter_py(root: Path) -> list[Path]:
    return [
        p for p in sorted(root.rglob("*.py"))
        if not any(part in _SKIP_DIRS for part in p.relative_to(root).parts)
    ]


def _is_test_path(rel: str) -> bool:
    r = rel.replace("\\", "/").lower()
    return (r.startswith(("tests/", "test/")) or "/tests/" in f"/{r}"
            or Path(r).name.startswith("test_") or Path(r).name == "conftest.py")


def _is_excluded_candidate(rel: str) -> bool:
    """Files we don't report dead symbols *in*: tests, __init__ re-exports, and
    example/fixture code (demos intentionally carry unused symbols)."""
    r = rel.replace("\\", "/").lower()
    if _is_test_path(r) or Path(r).name == "__init__.py":
        return True
    return (r.startswith(("examples/", "example/", "fixtures/"))
            or "/examples/" in f"/{r}" or "/fixtures/" in f"/{r}")


def _collect_references(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(names referenced anywhere, names listed in __all__) for one module."""
    refs: set[str] = set()
    exports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                refs.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                refs.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    exports.update(
                        e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )
    return refs, exports


def _candidates(tree: ast.Module) -> list[tuple[str, str, int]]:
    """Module-level (name, kind, lineno) defs that could be dead, conservatively."""
    out: list[tuple[str, str, int]] = []
    for node in tree.body:  # top-level only
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        name = node.name
        if node.decorator_list:          # decorators often register the symbol externally
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        if name in ("main",) or name.startswith("test_"):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        out.append((name, kind, node.lineno))
    return out


def find_dead_code(project_root: str, limit: int = 40) -> list[dict[str, Any]]:
    """Module-level symbols defined in non-test code but referenced nowhere."""
    root = Path(project_root)
    files = _iter_py(root)
    referenced: set[str] = set()
    exported: set[str] = set()
    parsed: dict[str, ast.Module] = {}
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        rel = f.relative_to(root).as_posix()
        parsed[rel] = tree
        refs, exports = _collect_references(tree)  # references from ALL files, incl. tests
        referenced |= refs
        exported |= exports

    dead: list[dict[str, Any]] = []
    for rel, tree in parsed.items():
        if _is_excluded_candidate(rel):
            continue
        for name, kind, lineno in _candidates(tree):
            if name in referenced or name in exported:
                continue
            dead.append({"module": rel, "symbol": name, "kind": kind, "line": lineno})
    dead.sort(key=lambda d: (d["module"], d["line"]))
    return dead[:limit]


def render_dead_code_markdown(rows: list[dict[str, Any]]) -> str:
    """Render the dead-code report as markdown."""
    if not rows:
        return "# Dead code\n\n_No unreferenced module-level symbols found._\n"
    lines = [
        "# Dead code (possibly unused)",
        "",
        f"{len(rows)} module-level symbol(s) defined but referenced nowhere in the project "
        "(tests included). Dynamic use can't be seen statically — verify before removing.",
        "",
        "| Module | Symbol | Kind | Line |",
        "|---|---|---|---:|",
    ]
    for r in rows:
        lines.append(f"| {r['module']} | `{r['symbol']}` | {r['kind']} | {r['line']} |")
    lines.append("")
    return "\n".join(lines)
