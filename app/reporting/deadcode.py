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


def _node_refs(node: ast.AST) -> set[str]:
    """Names a single AST node references (empty for nodes that reference none)."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.ImportFrom):
        return {a.asname or a.name for a in node.names}
    if isinstance(node, ast.Import):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    return set()


def _is_all_assign(node: ast.AST) -> bool:
    """True for an ``__all__ = [...]``/``(...)`` assignment (a literal seq)."""
    return (isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.List, ast.Tuple))
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets))


def _all_exports(node: ast.Assign) -> set[str]:
    """The string constants listed in an ``__all__`` literal sequence."""
    return {
        e.value for e in node.value.elts
        if isinstance(e, ast.Constant) and isinstance(e.value, str)
    }


def _collect_references(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(names referenced anywhere, names listed in __all__) for one module."""
    refs: set[str] = set()
    exports: set[str] = set()
    for node in ast.walk(tree):
        refs |= _node_refs(node)
        if _is_all_assign(node):
            exports |= _all_exports(node)
    return refs, exports


def _use_only_lines(node: ast.AST) -> frozenset[int]:
    """Line numbers that run only when the symbol is *exercised* — the honest
    runtime signal of deadness (see :func:`app.engine.runtime_trace.confirm_findings`).

    For a function: every line inside its body (those run only on call). For a
    class: the lines inside its *method bodies* only — a class's def header and
    its class-level statements (method ``def`` lines, class vars) run at import
    even if the class is never used, so they are excluded.
    """
    lines: set[int] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if hasattr(sub, "lineno"):
                    lines.add(sub.lineno)
    elif isinstance(node, ast.ClassDef):
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in item.body:
                    for sub in ast.walk(stmt):
                        if hasattr(sub, "lineno"):
                            lines.add(sub.lineno)
    return frozenset(lines)


def _candidates(tree: ast.Module) -> list[tuple[str, str, int, frozenset[int]]]:
    """Module-level (name, kind, lineno, use-only body lines) defs that could be
    dead, conservatively."""
    out: list[tuple[str, str, int, frozenset[int]]] = []
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
        out.append((name, kind, node.lineno, _use_only_lines(node)))
    return out


def _parse_project(root: Path) -> tuple[dict[str, ast.Module], set[str], set[str]]:
    """Parse every project ``.py`` file once: returns (rel-path → tree, all
    referenced names, all ``__all__`` exports) gathered across ALL files
    (tests included, since a test-only reference still keeps a symbol live)."""
    parsed: dict[str, ast.Module] = {}
    referenced: set[str] = set()
    exported: set[str] = set()
    for f in _iter_py(root):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        parsed[f.relative_to(root).as_posix()] = tree
        refs, exports = _collect_references(tree)
        referenced |= refs
        exported |= exports
    return parsed, referenced, exported


def _confidence(name: str) -> str:
    """A private (underscore-prefixed) symbol nothing references is internal-by-
    convention dead code — high confidence to remove. A public one might still be
    intended API (imported by a downstream consumer this scan can't see), so flag
    it for review instead."""
    return "high" if name.startswith("_") else "review"


def _gather_dead(
    parsed: dict[str, ast.Module], referenced: set[str], exported: set[str],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], frozenset[int]]]:
    """Walk candidate (non-test) modules, collecting unreferenced symbols as
    findings plus a (module, symbol, line) → use-only-body-lines side map."""
    dead: list[dict[str, Any]] = []
    body_by_key: dict[tuple[str, str, int], frozenset[int]] = {}
    for rel, tree in parsed.items():
        if _is_excluded_candidate(rel):
            continue
        for name, kind, lineno, body_lines in _candidates(tree):
            if name in referenced or name in exported:
                continue
            dead.append({"module": rel, "symbol": name, "kind": kind,
                         "line": lineno, "confidence": _confidence(name)})
            body_by_key[(rel, name, lineno)] = body_lines
    return dead, body_by_key


def _annotate_runtime(
    dead: list[dict[str, Any]],
    body_by_key: dict[tuple[str, str, int], frozenset[int]],
    root: Path,
    evidence: RuntimeEvidence,
) -> None:
    """Confirm/refute each finding against what the tests actually executed,
    adding a ``runtime`` key in place. Findings carry a project-relative
    ``module``; resolve to an absolute path so it lines up with the traced
    (absolute) filenames."""
    findings = [
        StaticFinding(path=str(root / d["module"]),
                      lineno=d["line"], symbol=d["symbol"],
                      body_lines=body_by_key[(d["module"], d["symbol"], d["line"])])
        for d in dead
    ]
    by_key = {
        (c.path, c.lineno, c.symbol): c.confidence
        for c in confirm_findings(findings, evidence)
    }
    for d in dead:
        d["runtime"] = by_key[(str(root / d["module"]), d["line"], d["symbol"])]


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
    parsed, referenced, exported = _parse_project(root)
    dead, body_by_key = _gather_dead(parsed, referenced, exported)
    # High-confidence (private) findings first — they're the safe, actionable ones.
    dead.sort(key=lambda d: (0 if d["confidence"] == "high" else 1, d["module"], d["line"]))
    dead = dead[:limit]
    if evidence is not None:
        _annotate_runtime(dead, body_by_key, root, evidence)
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
    # Additive runtime column: only when findings carry a ``runtime`` label
    # (i.e. evidence was supplied to find_dead_code). Without it, the output is
    # byte-identical to the static-only report.
    has_runtime = any("runtime" in r for r in rows)
    if has_runtime:
        summary += (
            "\n\nRuntime legend: **runtime-confirmed** = the symbol never ran "
            "while the tests executed (static finding strengthened); "
            "**refuted** = it did run, so the static guess is a false positive; "
            "**static-only** = the file never loaded, so runtime can't say."
        )
        header = "| Module | Symbol | Kind | Line | Confidence | Runtime |"
        divider = "|---|---|---|---:|---|---|"
    else:
        header = "| Module | Symbol | Kind | Line | Confidence |"
        divider = "|---|---|---|---:|---|"
    lines = [
        "# Dead code (possibly unused)",
        "",
        summary,
        "",
        header,
        divider,
    ]
    for r in rows:
        conf = r.get("confidence", "review")
        if has_runtime:
            rt = r.get("runtime", "static-only")
            lines.append(f"| {r['module']} | `{r['symbol']}` | {r['kind']} | {r['line']} | {conf} | {rt} |")
        else:
            lines.append(f"| {r['module']} | `{r['symbol']}` | {r['kind']} | {r['line']} | {conf} |")
    lines.append("")
    return "\n".join(lines)
