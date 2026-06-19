"""Function-level call graph and blast-radius analysis.

Every other Apex analysis is within a file; this one is *across* them. It parses
the project into a name-based call graph (which functions call which), then for
any function answers the question a developer asks before touching it: **what
depends on this?** — the transitive set of callers whose behavior could change.

Call resolution is name-based and best-effort (Python is dynamic), which is the
standard, useful approximation: it can't see runtime dispatch, but it surfaces
the concrete call sites that reference a name. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FuncRef:
    module: str            # project-relative path, e.g. app/x.py
    name: str              # function/method simple name
    lineno: int

    @property
    def qualname(self) -> str:
        return f"{self.module}::{self.name}:{self.lineno}"

    def to_dict(self) -> dict:
        return {"module": self.module, "name": self.name, "lineno": self.lineno}


class CallGraph:
    """A name-based function call graph over a project."""

    def __init__(self) -> None:
        self.defs: dict[str, list[FuncRef]] = {}        # name -> definitions
        self.callers: dict[str, set[str]] = {}          # called name -> caller qualnames
        self._meta: dict[str, FuncRef] = {}             # qualname -> ref
        self._qual_name: dict[str, str] = {}            # qualname -> simple name

    @classmethod
    def build(cls, project_root: str | Path, max_files: int = 2000) -> CallGraph:
        g = cls()
        root = Path(project_root)
        scanned = 0
        for path in sorted(root.rglob("*.py")):
            if scanned >= max_files or not path.is_file():
                continue
            rel = str(path.relative_to(root))
            if rel.startswith((".", "build/")) or "/." in rel:
                continue
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (SyntaxError, RecursionError, MemoryError):
                continue
            g._index_module(rel, tree)
        return g

    def _index_module(self, rel: str, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            ref = FuncRef(module=rel, name=node.name, lineno=node.lineno)
            self.defs.setdefault(node.name, []).append(ref)
            self._meta[ref.qualname] = ref
            self._qual_name[ref.qualname] = node.name
            for called in _called_names(node):
                self.callers.setdefault(called, set()).add(ref.qualname)

    # --- queries -------------------------------------------------------------

    def definitions(self, name: str) -> list[FuncRef]:
        return sorted(self.defs.get(name, []), key=lambda r: (r.module, r.lineno))

    def direct_callers(self, name: str) -> list[FuncRef]:
        return sorted(
            (self._meta[q] for q in self.callers.get(name, set())),
            key=lambda r: (r.module, r.lineno),
        )

    def blast_radius(self, name: str, max_depth: int = 5) -> list[FuncRef]:
        """Functions that transitively call ``name`` (its change blast radius).

        Propagation stops at *hub* names (dunders and ubiquitous verbs like
        ``run``/``__init__``): a call to such a generic name can't be pinned to
        this specific function, so following its callers would over-connect the
        whole project. Hubs are still reported as affected, just not expanded.
        Bounded by ``max_depth`` for the same reason.
        """
        result: set[str] = set()
        seen_names: set[str] = set()
        frontier: list[tuple[str, int]] = [(name, 0)]
        while frontier:
            cur, depth = frontier.pop()
            if cur in seen_names or depth > max_depth:
                continue
            seen_names.add(cur)
            for caller_q in self.callers.get(cur, set()):
                if caller_q not in result:
                    result.add(caller_q)
                    caller_name = self._qual_name[caller_q]
                    if caller_name not in _HUB_NAMES and not caller_name.startswith("__"):
                        frontier.append((caller_name, depth + 1))
        return sorted((self._meta[q] for q in result), key=lambda r: (r.module, r.lineno))


# Ubiquitous names that act as dispatch hubs, not specific dependencies — used
# to stop transitive over-connection in the (name-based) blast-radius walk.
_HUB_NAMES = {
    "run", "start", "stop", "main", "execute", "setup", "teardown", "wrapper",
    "inner", "_run", "_execute", "process", "handle", "call", "apply",
}


def _called_names(func: ast.AST) -> set[str]:
    """Simple names called within a function body (Name calls and method calls)."""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def render_impact_markdown(name: str, graph: CallGraph) -> str:
    """Render the impact (definitions + blast radius) of changing ``name``."""
    defs = graph.definitions(name)
    direct = graph.direct_callers(name)
    radius = graph.blast_radius(name)
    lines = [f"# Impact of changing `{name}()`", ""]
    if not defs:
        lines += [f"_No function named `{name}` is defined in this project._", ""]
        return "\n".join(lines)

    lines.append(f"**Defined in {len(defs)} place(s):**")
    for d in defs:
        lines.append(f"- `{d.module}:{d.lineno}`")
    lines.append("")
    indirect = len(radius) - len(direct)
    lines.append(
        f"**Blast radius: {len(radius)} affected function(s)** "
        f"({len(direct)} direct caller(s)" + (f", {indirect} indirect" if indirect > 0 else "") + ")."
    )
    if not radius:
        lines += ["", "_Nothing calls it — safe to change in isolation._", ""]
        return "\n".join(lines)
    lines.append("")
    direct_set = {d.qualname for d in direct}
    for r in radius:
        tag = "direct" if r.qualname in direct_set else "indirect"
        lines.append(f"- `{r.module}:{r.lineno}` `{r.name}()`  _({tag})_")
    lines.append("")
    return "\n".join(lines)
