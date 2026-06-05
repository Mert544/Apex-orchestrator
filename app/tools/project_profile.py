from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.tools.dependency_graph import DependencyGraphBuilder
from app.tools.python_structure import PythonStructureAnalyzer
from app.tools.test_linker import TestLinker


@dataclass
class ProjectProfile:
    root: str
    total_files: int = 0
    extension_counts: dict[str, int] = field(default_factory=dict)
    top_directories: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    sensitive_paths: list[str] = field(default_factory=list)
    dependency_hubs: list[str] = field(default_factory=list)
    symbol_hubs: list[str] = field(default_factory=list)
    untested_modules: list[str] = field(default_factory=list)
    critical_untested_modules: list[str] = field(default_factory=list)
    module_to_tests: dict[str, list[str]] = field(default_factory=dict)
    dependency_edges: list[tuple[str, str]] = field(default_factory=list)
    fragile_modules: list[str] = field(default_factory=list)
    import_cycles: list[list[str]] = field(default_factory=list)
    modernizable_modules: list[str] = field(default_factory=list)
    mutable_default_modules: list[str] = field(default_factory=list)
    debt_marker_modules: list[str] = field(default_factory=list)
    hotspot_modules: list[str] = field(default_factory=list)


class ProjectProfiler:
    ENTRYPOINT_NAMES = {
        "main.py",
        "__main__.py",
        "server.py",
        "app.py",
        "cli.py",
        "index.ts",
        "index.js",
    }
    CONFIG_NAMES = {
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
    }
    SENSITIVE_HINTS = {
        "auth",
        "payment",
        "token",
        "secret",
        "billing",
        "api",
        "credential",
    }
    # Sensitive-path hints only mean something for actual source code. A docs
    # file like ``docs/api.md`` matches "api" by substring but hardening or
    # "testing" a markdown doc is meaningless — restrict to code extensions so
    # external projects (e.g. click) don't get docs flagged as sensitive.
    CODE_EXTENSIONS = {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx",
        ".go", ".rs", ".java", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp",
    }
    # Technical-debt markers, matched only inside comments: a ``#`` then optional
    # whitespace then one of the marker words as a whole word (case-insensitive).
    # Anchoring to ``#`` keeps the signal precise — it won't fire on the bare
    # string "TODO" inside a literal or an identifier, only on real comments.
    DEBT_MARKER_RE = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)
    # A module needs at least this many markers to be flagged. >= 3 keeps the
    # signal meaningful (modules with a single stray TODO are noise); a cluster
    # of three or more is a real, surface-worthy pocket of deferred work.
    DEBT_MARKER_THRESHOLD = 3

    def __init__(self, root: str | Path, max_files: int = 2000) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def profile(self) -> ProjectProfile:
        profile = ProjectProfile(root=str(self.root))
        if not self.root.exists():
            return profile

        ext_counter: Counter[str] = Counter()
        dir_counter: Counter[str] = Counter()
        debt_counts: Counter[str] = Counter()

        skipped_dirs = {".git", "__pycache__", ".apex", ".epistemic", "node_modules", ".venv", "venv", "dist", "build", ".turbo", ".next"}
        scanned = 0
        for path in self.root.rglob("*"):
            if scanned >= self.max_files:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            rel_str = str(rel)
            # Skip known non-source directories
            if any(part in skipped_dirs for part in rel.parts):
                continue
            scanned += 1
            profile.total_files += 1

            ext = path.suffix.lower() or ""
            if ext:
                ext_counter[ext] += 1

            if rel.parts:
                dir_counter[rel.parts[0]] += 1

            name_lower = path.name.lower()
            rel_lower = rel_str.lower()

            if name_lower in self.ENTRYPOINT_NAMES:
                profile.entrypoints.append(rel_str)
            if name_lower.startswith("test_") or "/tests/" in f"/{rel_lower}/" or rel_lower.startswith("tests/"):
                profile.test_files.append(rel_str)
            if ".github" in rel_lower and "workflows" in rel_lower:
                profile.ci_files.append(rel_str)
            if name_lower in self.CONFIG_NAMES:
                profile.config_files.append(rel_str)
            if ext in self.CODE_EXTENSIONS and any(hint in rel_lower for hint in self.SENSITIVE_HINTS):
                profile.sensitive_paths.append(rel_str)

            # Count technical-debt markers in Python comments, folded into the
            # existing walk so we don't add a second full-tree pass.
            if ext == ".py":
                count = self._count_debt_markers(path)
                if count:
                    debt_counts[rel_str] = count

        profile.extension_counts = dict(ext_counter.most_common())
        profile.top_directories = [name for name, _count in dir_counter.most_common(5)]
        profile.entrypoints = sorted(dict.fromkeys(profile.entrypoints))
        profile.test_files = sorted(dict.fromkeys(profile.test_files))
        profile.ci_files = sorted(dict.fromkeys(profile.ci_files))
        profile.config_files = sorted(dict.fromkeys(profile.config_files))
        profile.sensitive_paths = sorted(dict.fromkeys(profile.sensitive_paths))

        # Modules with a meaningful cluster of debt markers, ranked by count
        # then path (stable/deterministic), capped like the other profile lists.
        flagged = [
            module for module, count in debt_counts.items()
            if count >= self.DEBT_MARKER_THRESHOLD
        ]
        profile.debt_marker_modules = sorted(
            flagged, key=lambda m: (-debt_counts[m], m)
        )[:5]

        self._populate_python_structure(profile)
        return profile

    def _count_debt_markers(self, path: Path) -> int:
        """Count ``# TODO/FIXME/XXX/HACK`` comment markers in a Python file.

        Matches only the comment form (anchored to ``#``) so the bare word
        appearing in a string literal or identifier is never counted.
        """
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return 0
        return len(self.DEBT_MARKER_RE.findall(text))

    def _populate_python_structure(self, profile: ProjectProfile) -> None:
        analyzer = PythonStructureAnalyzer(self.root)
        modules = analyzer.analyze()
        if not modules:
            return

        graph_builder = DependencyGraphBuilder(self.root)
        profile.dependency_hubs = graph_builder.top_central_modules(limit=5)
        profile.dependency_edges = [
            (e.source, e.target) for e in graph_builder.edges()
        ]
        profile.import_cycles = graph_builder.find_cycles(limit=5)

        symbol_rank = sorted(modules, key=lambda m: len(m.symbols), reverse=True)
        profile.symbol_hubs = [m.path for m in symbol_rank if len(m.symbols) > 0][:5]

        linker = TestLinker(self.root)
        coverage = linker.analyze(critical_modules=profile.dependency_hubs)
        profile.module_to_tests = coverage.module_to_tests
        profile.untested_modules = coverage.untested_modules[:5]
        profile.critical_untested_modules = coverage.critical_untested_modules[:5]

        # Fragility: many modules depend on it (high in-degree) but it has
        # thin/no test coverage — a high-blast-radius risk worth surfacing.
        graph = graph_builder.build()
        thin = {m for m, t in profile.module_to_tests.items() if len(t) <= 1}
        thin |= set(profile.untested_modules)
        fragile = sorted(
            (n for n in graph.values() if n.in_degree >= 2 and n.path in thin),
            key=lambda n: (n.in_degree, n.path),
            reverse=True,
        )
        profile.fragile_modules = [n.path for n in fragile][:3]

        # Modernization debt: modules with behavior-preserving cleanups available
        # (currently `== None`/`!= None`), so the engine can propose safe fixes.
        profile.modernizable_modules = self._scan_modernizable(modules)[:5]
        profile.mutable_default_modules = self._scan_mutable_defaults(modules)[:5]

        # Complexity hotspots: modules combining real cyclomatic complexity with
        # blast radius and thin tests — the riskiest places to change. Scored
        # only over a bounded candidate set (high in-degree or symbol-heavy) so
        # this stays cheap. Shares the risk formula with the hotspots report.
        profile.hotspot_modules = self._scan_hotspots(modules, graph, profile.module_to_tests)

    def _scan_hotspots(self, modules: list, graph: dict, module_to_tests: dict) -> list[str]:
        """Top modules by complexity × (1 + fan-in) ÷ (1 + tests), bounded + filtered."""
        from app.reporting.hotspots import hotspot_risk
        from app.tools.code_metrics import CodeMetrics

        fan_in = {n.path: n.in_degree for n in graph.values()}
        symbol_rank = sorted(modules, key=lambda m: len(m.symbols), reverse=True)
        candidates = {p for p, fi in fan_in.items() if fi >= 2}
        candidates |= {m.path for m in symbol_rank[:15]}
        if not candidates:
            return []
        metrics = CodeMetrics(self.root).for_modules(sorted(candidates))
        scored: list[tuple[float, int, str]] = []
        for path, mm in metrics.items():
            if mm.complexity < 8:        # a real branching module, not a trivial one
                continue
            risk = hotspot_risk(mm.complexity, fan_in.get(path, 0), len(module_to_tests.get(path, [])))
            scored.append((risk, mm.complexity, path))
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        return [p for _risk, _cx, p in scored[:3]]

    def _scan_mutable_defaults(self, modules: list) -> list[str]:
        """Modules with a mutable default argument (list/dict/set literal)."""
        import ast

        out: list[str] = []
        for m in modules:
            try:
                tree = ast.parse((self.root / m.path).read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            found = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
                    for d in defaults:
                        if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                            found = True
                        elif (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                              and d.func.id in ("list", "dict", "set")
                              and not d.args and not d.keywords):
                            found = True
                    if found:
                        break
            if found:
                out.append(m.path)
        return sorted(out)

    def _scan_modernizable(self, modules: list) -> list[str]:
        """Modules that contain a real `== None` / `!= None` comparison (AST)."""
        import ast

        out: list[str] = []
        for m in modules:
            try:
                tree = ast.parse((self.root / m.path).read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare) and any(
                    isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops
                ) and any(
                    isinstance(x, ast.Constant) and x.value is None
                    for x in (node.left, *node.comparators)
                ):
                    out.append(m.path)
                    break
        return sorted(out)
