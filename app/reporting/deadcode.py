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

from app.engine.runtime_trace import (
    RuntimeEvidence,
    StaticFinding,
    confirm_findings,
)
from app.engine.skip_dirs import SKIPPED_DIRS

# Canonical exclusions (incl. `.claude` agent worktrees) plus this report's own
# extras — a dead-code scan that descended into worktree copies would see a
# symbol "used" in a stale copy and wrongly call it live.
_SKIP_DIRS = SKIPPED_DIRS | {".tox", ".mypy_cache"}


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


def find_dead_code(
    project_root: str,
    limit: int = 40,
    evidence: RuntimeEvidence | None = None,
) -> list[dict[str, Any]]:
    """Module-level symbols defined in non-test code but referenced nowhere.

    When ``evidence`` (a :class:`RuntimeEvidence` from running the project's own
    tests under :mod:`app.engine.runtime_trace`) is supplied, each finding gains
    an additive ``runtime`` key — ``"runtime-confirmed"`` (the def line never
    ran), ``"refuted"`` (it did run, so the static guess is a false positive) or
    ``"static-only"`` (the file was never loaded). With ``evidence=None`` the
    output is byte-identical to before: no ``runtime`` key is added.
    """
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
            # A private (underscore-prefixed) symbol that nothing references is
            # internal-by-convention dead code — high confidence to remove. A
            # public one might still be intended API (imported by a downstream
            # consumer this scan can't see), so flag it for review instead.
            confidence = "high" if name.startswith("_") else "review"
            dead.append({"module": rel, "symbol": name, "kind": kind,
                         "line": lineno, "confidence": confidence})
    # High-confidence (private) findings first — they're the safe, actionable ones.
    dead.sort(key=lambda d: (0 if d["confidence"] == "high" else 1, d["module"], d["line"]))
    dead = dead[:limit]
    if evidence is not None:
        # Confirm/refute each finding against what the tests actually executed.
        # Findings carry a project-relative ``module``; resolve to an absolute
        # path so it lines up with the traced (absolute) filenames.
        findings = [
            StaticFinding(path=str(root / d["module"]),
                          lineno=d["line"], symbol=d["symbol"])
            for d in dead
        ]
        by_key = {
            (c.path, c.lineno, c.symbol): c.confidence
            for c in confirm_findings(findings, evidence)
        }
        for d in dead:
            d["runtime"] = by_key[(str(root / d["module"]), d["line"], d["symbol"])]
    return dead


def render_dead_code_markdown(rows: list[dict[str, Any]]) -> str:
    """Render the dead-code report as markdown."""
    if not rows:
        return "# Dead code\n\n_No unreferenced module-level symbols found._\n"
    high = sum(1 for r in rows if r.get("confidence") == "high")
    summary = (
        f"{len(rows)} module-level symbol(s) defined but referenced nowhere in the project "
        "(tests included). Dynamic use can't be seen statically — verify before removing."
    )
    if high:
        summary += (
            f" {high} are private (underscore-prefixed) and high-confidence to remove; "
            "the rest are public and may be intended API."
        )
    lines = [
        "# Dead code (possibly unused)",
        "",
        summary,
        "",
        "| Module | Symbol | Kind | Line | Confidence |",
        "|---|---|---|---:|---|",
    ]
    for r in rows:
        conf = r.get("confidence", "review")
        lines.append(f"| {r['module']} | `{r['symbol']}` | {r['kind']} | {r['line']} | {conf} |")
    lines.append("")
    return "\n".join(lines)
