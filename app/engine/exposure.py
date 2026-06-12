"""Exposure — a security finding placed in its *development* context.

"There is an `eval` in utils.py" is a fact. "That `eval` has sat in the code
for 14 months and an entrypoint can reach it in two calls" is a decision.
This module computes both halves for any (file, line) finding:

  - **age** — how long the flagged line has existed, via ``git blame``,
    anchored to the HEAD commit time (not the wall clock) so the result is
    deterministic for a given repo state;
  - **reach** — whether a project *entrypoint* (main/cli/server/app) can
    transitively execute the enclosing function, via the call graph
    (name-based and hub-stopped, same machinery as ``apex impact``).

This is the security-integrated-into-development thesis in one place: the
detectors say *what*, the project's own history and structure say *how much
it matters*. Deterministic, stdlib-only; non-git targets simply get no age.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Exposure:
    file: str
    line: int
    enclosing: str = ""                 # function name, or "" = module level
    age_days: int | None = None         # None: no git history available
    reachable_from: list[str] = field(default_factory=list)  # entrypoint modules

    @property
    def exposed(self) -> bool:
        return bool(self.reachable_from)

    def describe(self) -> str:
        """One compact human phrase — empty when nothing noteworthy."""
        parts: list[str] = []
        if self.age_days is not None and self.age_days >= 60:
            parts.append(f"in the code ~{self.age_days // 30} months")
        if self.reachable_from:
            parts.append(f"reachable from `{self.reachable_from[0]}`")
        elif not self.enclosing:
            parts.append("module level (runs on import)")
        return " · ".join(parts)

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "enclosing": self.enclosing,
                "age_days": self.age_days, "reachable_from": self.reachable_from}


def _enclosing_function(source: str, line: int) -> str:
    """The innermost function containing ``line`` ('' = module level)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    best = ""
    best_span = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end:
                span = end - node.lineno
                if best_span is None or span < best_span:
                    best, best_span = node.name, span
    return best


def blame_age_days(project_root: str | Path, rel: str, line: int) -> int | None:
    """Days since the flagged line's commit, anchored to HEAD's commit time."""
    def _git(*args: str):
        return subprocess.run(["git", *args], cwd=project_root,
                              capture_output=True, text=True, timeout=15)

    try:
        head = _git("log", "-1", "--format=%ct")
        if head.returncode != 0 or not head.stdout.strip():
            return None
        blame = _git("blame", "-L", f"{line},{line}", "--porcelain", "--", rel)
        if blame.returncode != 0:
            return None
        for text_line in blame.stdout.splitlines():
            if text_line.startswith("committer-time "):
                then = int(text_line.split()[1])
                return max(0, (int(head.stdout.strip()) - then) // 86400)
    except Exception:
        return None
    return None


def _reachable_entrypoints(graph, module: str, func_name: str,
                           entrypoints: set[str]) -> list[str]:
    """Entrypoint modules that can transitively call ``func_name``."""
    if module in entrypoints:
        return [module]
    if not func_name:
        return []
    hits = {
        ref.module for ref in graph.blast_radius(func_name)
        if ref.module in entrypoints
    }
    return sorted(hits)


def analyze_exposure(project_root: str | Path,
                     findings: list[tuple[str, int]],
                     entrypoints: list[str] | None = None,
                     graph=None) -> list[Exposure]:
    """Exposure for each ``(rel_path, line)`` finding (order preserved)."""
    root = Path(project_root)
    if entrypoints is None:
        from app.tools.project_profile import ProjectProfiler

        entrypoints = ProjectProfiler(str(root)).profile().entrypoints
    eps = {e.replace("\\", "/") for e in entrypoints}
    if graph is None and findings:
        from app.engine.call_graph import CallGraph

        graph = CallGraph.build(str(root))

    sources: dict[str, str] = {}
    out: list[Exposure] = []
    for rel, line in findings:
        rel = rel.replace("\\", "/")
        if rel not in sources:
            try:
                sources[rel] = (root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                sources[rel] = ""
        enclosing = _enclosing_function(sources[rel], line)
        out.append(Exposure(
            file=rel, line=line, enclosing=enclosing,
            age_days=blame_age_days(root, rel, line),
            reachable_from=_reachable_entrypoints(graph, rel, enclosing, eps),
        ))
    return out
