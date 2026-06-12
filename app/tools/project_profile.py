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
    # Modules where the *content* detector found real security issues (eval,
    # os.system, pickle, ...), independent of the filename heuristic above.
    security_finding_modules: list[str] = field(default_factory=list)
    # Modules with a high-severity logic bug (frozen-dataclass mutation, return
    # in finally, unreachable except, ...) — a likely/guaranteed crash.
    correctness_bug_modules: list[str] = field(default_factory=list)
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
    shallow_tested_modules: list[str] = field(default_factory=list)
    # Symbol granularity: complex functions no linked test ever names.
    # Each entry: {"module", "function", "line", "complexity"}.
    hotspot_functions: list[dict] = field(default_factory=list)
    # Change-frequency hotspots from git history: where development energy
    # concentrates. Each entry: {"module", "commits"}.
    churn_hotspots: list[dict] = field(default_factory=list)


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
    # Churn: how many recent commits to examine, and how many touches a module
    # needs inside that window to count as a hotspot. A fixed window keeps the
    # signal deterministic for a given repo state and bounds the git call.
    CHURN_COMMIT_WINDOW = 300
    CHURN_THRESHOLD = 3

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
        security_finding_modules: list[str] = []
        correctness_bug_modules: list[str] = []

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
            if ext == ".py" and not (
                name_lower.startswith("test_") or "/tests/" in f"/{rel_lower}/"
                or rel_lower.startswith("tests/")
            ):
                count = self._count_debt_markers(path)
                if count:
                    debt_counts[rel_str] = count
                # Content-based security findings (eval/os.system/pickle/...),
                # so the idea engine can point at the *actual* dangerous file —
                # not only files whose name matches a sensitive hint.
                if self._has_security_finding(path):
                    security_finding_modules.append(rel_str)
                # High-severity logic bugs (frozen-dataclass mutation, return in
                # finally, unreachable except, ...) — likely/guaranteed crashes
                # the idea engine should surface as a top fix, not just the grade.
                if self._has_correctness_bug(path):
                    correctness_bug_modules.append(rel_str)

        profile.extension_counts = dict(ext_counter.most_common())
        profile.top_directories = [name for name, _count in dir_counter.most_common(5)]
        profile.entrypoints = sorted(dict.fromkeys(profile.entrypoints))
        profile.test_files = sorted(dict.fromkeys(profile.test_files))
        profile.ci_files = sorted(dict.fromkeys(profile.ci_files))
        profile.config_files = sorted(dict.fromkeys(profile.config_files))
        profile.sensitive_paths = sorted(dict.fromkeys(profile.sensitive_paths))
        profile.security_finding_modules = sorted(dict.fromkeys(security_finding_modules))[:5]
        profile.correctness_bug_modules = sorted(dict.fromkeys(correctness_bug_modules))[:5]

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
        self._scan_churn(profile)
        self._drop_fixture_signals(profile)
        return profile

    def _scan_churn(self, profile: ProjectProfile) -> None:
        """Rank modules by how often recent commits touched them (git churn).

        Where change concentrates is where development energy goes — the idea
        engine should reason about the project's *living* modules, not only its
        statically risky ones. Non-git directories (or a missing git binary)
        simply yield no signal.
        """
        import subprocess

        try:
            out = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:",
                 "-n", str(self.CHURN_COMMIT_WINDOW)],
                cwd=self.root, capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return
        if out.returncode != 0:
            return
        counts: Counter[str] = Counter()
        for line in out.stdout.splitlines():
            rel = line.strip()
            if not rel.endswith(".py") or self._is_fixture_path(rel):
                continue
            if not (self.root / rel).exists():  # deleted files don't need ideas
                continue
            counts[rel] += 1
        profile.churn_hotspots = [
            {"module": module, "commits": commits}
            for module, commits in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            if commits >= self.CHURN_THRESHOLD
        ]

    # Mirrors app.engine.health_score._is_fixture_path (kept local to avoid a
    # project_profile <-> health_score import cycle). Example/fixture/test code
    # carries intentional flaws and is throwaway, so it must not seed development
    # ideas about the *real* project — exactly as the grade already excludes it.
    @staticmethod
    def _is_fixture_path(path: str) -> bool:
        p = path.replace("\\", "/").lower()
        return (
            p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
            or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
            or Path(p).name.startswith("test_")
        )

    # Seeding-signal fields the idea engine reads; filtered so fixtures never
    # become development ideas. (The grade applies the same predicate itself, so
    # pre-filtering here leaves grade results identical.)
    _SIGNAL_LIST_FIELDS = (
        "untested_modules", "critical_untested_modules", "sensitive_paths",
        "dependency_hubs", "symbol_hubs", "fragile_modules", "modernizable_modules",
        "mutable_default_modules", "debt_marker_modules", "hotspot_modules",
        "shallow_tested_modules", "security_finding_modules", "correctness_bug_modules",
        "entrypoints", "config_files",
    )

    def _drop_fixture_signals(self, profile: ProjectProfile) -> None:
        for field_name in self._SIGNAL_LIST_FIELDS:
            vals = getattr(profile, field_name, None)
            if vals:
                setattr(profile, field_name,
                        [m for m in vals if not self._is_fixture_path(str(m))])
        if profile.hotspot_functions:
            profile.hotspot_functions = [
                f for f in profile.hotspot_functions
                if not self._is_fixture_path(str(f.get("module", "")))
            ]
        if profile.churn_hotspots:
            profile.churn_hotspots = [
                c for c in profile.churn_hotspots
                if not self._is_fixture_path(str(c.get("module", "")))
            ]

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

    def _has_security_finding(self, path: Path) -> bool:
        """True if the content detector flags a real security issue in this file.

        Uses the same canonical detector as ``apex review`` and the grade, so the
        idea engine agrees with them on *where* the danger is — not just files
        whose name happens to match a sensitive hint.
        """
        from app.engine.detectors import security_labels
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return bool(security_labels(text))

    def _has_correctness_bug(self, path: Path) -> bool:
        """True if the detector finds a high-severity logic bug (likely crash)."""
        from app.engine.detectors import detect
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return any(
            i.category == "bug" and i.severity == "high"
            and not i.message.startswith("SyntaxError")
            for i in detect(text)
        )

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

        # Shallow coverage: a module whose only linked tests are characterization
        # stubs (import-smoke + isinstance contracts) — "covered" but not verified
        # correct. Surfaced so the grade/engine don't mistake linkage for depth.
        profile.shallow_tested_modules = self._scan_shallow_tests(profile.module_to_tests)

        # Fragility: many modules depend on it (high in-degree) but it has
        # weak coverage — a high-blast-radius risk worth surfacing. Coverage
        # weakness is measured by *depth* (untested, or linked tests that assert
        # nothing real), not by linked-test-file count: a single file with many
        # substantive tests fully covers a hub, so file-count is the wrong proxy.
        graph = graph_builder.build()
        thin = set(profile.untested_modules)
        thin |= set(self._scan_shallow_tests(profile.module_to_tests, limit=None))
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

        # Symbol granularity: descend into the riskiest modules and name the
        # *functions* that combine real branching with zero direct test mentions
        # — so ideas can target a symbol, not just a file. Bounded to modules
        # already surfaced as risky, so this stays cheap.
        candidates = list(dict.fromkeys(
            [*profile.hotspot_modules, *profile.fragile_modules, *profile.dependency_hubs[:5]]
        ))
        profile.hotspot_functions = self._scan_hotspot_functions(candidates, profile.module_to_tests)

    @staticmethod
    def _is_test_path(rel: str) -> bool:
        r = rel.replace("\\", "/").lower()
        return (r.startswith(("tests/", "test/")) or "/tests/" in f"/{r}"
                or Path(r).stem.startswith("test_"))

    def _scan_hotspot_functions(self, candidates: list[str], module_to_tests: dict) -> list[dict]:
        """Complex functions inside risky modules that no linked test exercises.

        "Exercises" is name-based but wrapper-aware: a function counts as
        covered when a linked test names it directly, names its enclosing
        class (tests driving ``Limb.run()`` exercise ``Limb._execute``), or
        names a sibling function that references it (a private helper tested
        through its public wrapper). Direct-name-only was too strict — it kept
        flagging code that real tests already drive.
        """
        import ast
        from app.tools.code_metrics import function_complexities

        all_tests_text: str | None = None  # lazy fallback corpus, read once

        def _whole_suite_text() -> str:
            nonlocal all_tests_text
            if all_tests_text is None:
                parts: list[str] = []
                for p in sorted(self.root.rglob("*.py")):
                    rel = str(p.relative_to(self.root))
                    if self._is_test_path(rel):
                        try:
                            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                        except OSError:
                            continue
                all_tests_text = "\n".join(parts)
            return all_tests_text

        out: list[dict] = []
        for module in candidates:
            if not module.endswith(".py") or self._is_test_path(module):
                continue
            try:
                source = (self.root / module).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if module in module_to_tests:
                test_text = ""
                for rel in module_to_tests.get(module, []) or []:
                    try:
                        test_text += (self.root / rel).read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
            else:
                # The linker doesn't track this module (e.g. code living in an
                # __init__.py) — check the whole suite before accusing it.
                test_text = _whole_suite_text()

            # Map each function in the module to the simple names it references,
            # so a private helper inherits coverage from a test-named wrapper.
            refs_by_func: dict[str, set[str]] = {}
            try:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                        names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                        refs_by_func[node.name] = names
            except SyntaxError:
                refs_by_func = {}

            def _named(token: str) -> bool:
                # Whole-word match, not substring: 'run' must not be "covered"
                # by 'rerun'/'prerun_hook', nor 'add' by 'self.address'.
                return re.search(rf"\b{re.escape(token)}\b", test_text) is not None

            def _exercised(qualified: str) -> bool:
                simple = qualified.rsplit(".", 1)[-1]
                if _named(simple):
                    return True  # named directly
                if any(          # a test-named sibling calls this helper
                    caller != simple and _named(caller) and simple in refs
                    for caller, refs in refs_by_func.items()
                ):
                    return True
                # Coverage flows down the nesting chain: a method is exercised
                # when its class is, a closure when its enclosing function is.
                if "." in qualified:
                    return _exercised(qualified.rsplit(".", 1)[0])
                return False

            for name, lineno, complexity in function_complexities(source):
                if complexity < 8:
                    continue  # a real branching function, not a trivial one
                simple = name.rsplit(".", 1)[-1]
                if simple.startswith("__") and simple.endswith("__"):
                    continue
                if _exercised(name):
                    continue
                out.append({"module": module, "function": name,
                            "line": lineno, "complexity": complexity})
        out.sort(key=lambda d: (-d["complexity"], d["module"], d["function"]))
        return out[:5]

    def _scan_shallow_tests(self, module_to_tests: dict, limit: int | None = 5) -> list[str]:
        """Modules whose linked tests exist but assert no real behaviour (shallow).

        ``limit=None`` returns the full set (used by the fragility scan, which
        needs every shallow hub, not just the top few surfaced in the profile).
        """
        from app.engine.detectors import test_has_substantive_assertions

        out: list[str] = []
        for module, tests in sorted(module_to_tests.items()):
            if not tests:
                continue  # genuinely untested — handled by untested_modules
            substantive = False
            for rel in tests:
                try:
                    text = (self.root / rel).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if test_has_substantive_assertions(text):
                    substantive = True
                    break
            if not substantive:
                out.append(module)
        return out if limit is None else out[:limit]

    def _scan_hotspots(self, modules: list, graph: dict, module_to_tests: dict) -> list[str]:
        """Top modules by complexity × (1 + fan-in) ÷ (1 + tests), bounded + filtered."""
        from app.tools.code_metrics import hotspot_risk
        from app.tools.code_metrics import CodeMetrics
        from app.tools.test_linker import count_test_functions

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
            if self._is_test_path(path):
                continue  # a branchy test file is not a de-risking target
            # depth-aware coverage: test functions, not linked files
            tests = count_test_functions(self.root, module_to_tests.get(path, []) or [])
            risk = hotspot_risk(mm.complexity, fan_in.get(path, 0), tests)
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
