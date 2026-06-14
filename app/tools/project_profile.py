from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import is_skipped
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
    # Quantified blast-radius / convergence data pulled from the SAME dependency
    # graph the profiler already builds (no second graph). Both additive and
    # default-empty, so existing profile/seeder tests are byte-identical:
    #   - module_fanin: module path -> in_degree (how many modules import it — the
    #     blast radius: a change here ripples to all of them);
    #   - module_fanout: module path -> its heaviest dependency targets (the
    #     modules IT imports), ranked by the target's own fan-in (the most-
    #     depended-on dependency first — shedding it cuts the most convergence),
    #     tie-broken by path, capped. Lets a hub/confluence root name the SPECIFIC
    #     decoupling targets, not just "decouple something".
    module_fanin: dict[str, int] = field(default_factory=dict)
    module_fanout: dict[str, list[str]] = field(default_factory=dict)
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
    # Purity-violation: functions that mix observable side effects (I/O, global
    # state, effect-module calls) with logic AND that no linked test exercises —
    # impure-and-untested, the high-leverage "isolate the effect, then test it"
    # target. Each entry: {"module", "function", "line", "side_effects"}.
    impure_untested_functions: list[dict] = field(default_factory=list)
    # Dependency HUBS (high fan-in: many modules import it) that are ALSO
    # untested or only shallow-tested. A regression in a hub breaks every
    # dependent, so an untested hub is the highest-leverage place to add tests.
    # Uses a strictly higher fan-in bar than fragile_modules (a true hub, not
    # merely "depended on by >=2"); reuses the already-built dependency graph
    # and thin-coverage set, so it adds no new scan. Each entry:
    # {"module", "fan_in"}.
    hub_untested_modules: list[dict] = field(default_factory=list)
    # Confluences (signal convergence): modules named by >= 3 DISTINCT signal
    # families at once (e.g. complex-function + high-churn + hub + symbol-hub).
    # No single lens names them, yet a module under several independent pressures
    # is the highest-leverage development target — "decouple/test before you
    # change". Reuses only fields already on the profile (no new scan); each
    # family is counted at most once. Each entry: {"module", "family_count",
    # "families" (sorted tuple of family names)}.
    confluence_modules: list[dict] = field(default_factory=list)
    # Change-frequency hotspots from git history: where development energy
    # concentrates. Each entry: {"module", "commits"}.
    churn_hotspots: list[dict] = field(default_factory=list)
    # Temporal coupling: module pairs that repeatedly change in the SAME
    # commits — factually coupled whether or not an import connects them.
    # Each entry: {"a", "b", "commits"}.
    change_coupling: list[dict] = field(default_factory=list)
    # Co-change test-gap: module PAIRS that frequently change together (from
    # ``change_coupling``) yet NO single test file exercises BOTH — a change to
    # one can silently break the other with no test to catch it. A grounded,
    # high-value test gap no single-module signal sees. Reuses ``change_coupling``
    # (git-only, EMPTY in light mode) and ``module_to_tests`` (no new scan). Each
    # entry: {"a", "b", "cochanges" (int), "links"}. ``links`` (additive) names
    # the ACTUAL symbol(s) that connect the two modules — a sorted, capped list of
    # {"from", "to", "symbol"} (one module ``import``-s ``symbol`` from the other),
    # empty when they co-change without directly importing each other.
    cochange_test_gaps: list[dict] = field(default_factory=list)
    # Knowledge concentration (DOA-inspired): modules whose recent changes
    # come overwhelmingly from ONE author — a bus-factor risk. Author names
    # are never stored. Each entry: {"module", "share" (percent), "commits"}.
    knowledge_risks: list[dict] = field(default_factory=list)
    # Age (days) of the OLDEST debt marker per flagged module, from git blame —
    # a 3-year-old FIXME is a different fact than one written yesterday.
    debt_marker_ages: dict[str, int] = field(default_factory=dict)
    # Age (days) of the OLDEST security finding per flagged module — how long
    # the risk has been sitting in the code (its exposure window).
    security_finding_ages: dict[str, int] = field(default_factory=dict)
    # Documentation drift: backticked file references in README/docs that don't
    # exist on disk. Each entry: {"doc", "reference", "line"}.
    doc_drift: list[dict] = field(default_factory=list)
    # Parameters no statement in the function body ever reads — dead weight on
    # the API surface, droppable via `apex signature drop`. Conservative by
    # construction (see _scan_dead_params). Each entry:
    # {"module", "function", "param", "line"}.
    dead_params: list[dict] = field(default_factory=list)
    # Long functions with a clean extractable seam — the engine's "extract a
    # shared helper" recommendation made into a concrete `apex extract` command.
    # Each entry: {"module", "function", "line", "start", "end", "name",
    # "params", "returns", "lines_saved"}.
    extractable_blocks: list[dict] = field(default_factory=list)
    # Tiny single-use helpers `apex inline` would cleanly accept — the engine's
    # "fold a thin helper back into its call site" recommendation made into a
    # concrete `apex inline FUNC` command. Conservative by construction (see
    # _scan_inlinable_helpers). Each entry: {"module", "function", "line",
    # "call_sites"}.
    inlinable_helpers: list[dict] = field(default_factory=list)
    # Analysis-scope accounting — honest reporting of how much of the repo Apex's
    # Python-only analysis actually covers (see _scan_analysis_scope). On a
    # polyglot repo the grade reflects only the Python subset; these fields make
    # that boundary explicit instead of silently grading a fraction as the whole.
    #   - source_file_count: source-bearing files counted (skip dirs + binary/
    #     asset extensions excluded);
    #   - python_file_count: how many of those are Python (the analysed subset);
    #   - language_breakdown: per-language file counts of the NON-Python files,
    #     keyed by normalised language name (unmapped extensions → "other"),
    #     sorted for stable rendering;
    #   - analyzed_ratio: python_file_count / source_file_count, in [0,1]
    #     (empty/all-Python repo → 1.0);
    #   - out_of_scope_ratio: 1 - analyzed_ratio.
    source_file_count: int = 0
    python_file_count: int = 0
    language_breakdown: dict[str, int] = field(default_factory=dict)
    analyzed_ratio: float = 1.0
    out_of_scope_ratio: float = 0.0
    # Polyglot hotspots: the biggest / most-churned NON-Python source files —
    # named (not deep-analysed) so the idea engine can recommend attention on the
    # largest active surface outside Apex's Python analysis scope. Populated from
    # ``scan_polyglot_facts`` (a single git pass; churn is git-only/empty in light
    # mode); an all-Python repo yields []. Each entry:
    # {"path","language","loc","churn"}.
    polyglot_hotspots: list[dict] = field(default_factory=list)


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
    # Coupling: a pair must co-change in at least this many commits to count;
    # commits touching more than MAX_COMMIT_FILES files (sweeping reformats,
    # vendoring) couple everything and mean nothing, so they're skipped.
    COCHANGE_THRESHOLD = 3
    MAX_COMMIT_FILES = 15
    # Knowledge risk: a module needs this many touches before concentration
    # means anything, and the top author must own at least this share. The
    # signal is skipped entirely for single-author projects (solo dev — a
    # 100% share carries no information).
    KNOWLEDGE_MIN_COMMITS = 5
    KNOWLEDGE_SHARE = 0.85
    # Analysis-scope accounting. A small explicit extension→language map: only
    # source-bearing files count toward the scope denominator, so binary/asset
    # files (images, fonts, archives, compiled artifacts) are excluded entirely.
    # ".py"/".pyi" are the IN-SCOPE (analysed) extensions; every other mapped
    # extension is honestly reported as outside Apex's Python analysis. Unmapped
    # source extensions are grouped under "other" so the count never lies.
    _SCOPE_PYTHON_EXTENSIONS = {".py", ".pyi"}
    _SCOPE_LANGUAGE_BY_EXT = {
        ".py": "Python", ".pyi": "Python",
        ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
        ".php": "PHP",
        ".c": "C", ".h": "C",
        ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
        ".cs": "C#",
        ".kt": "Kotlin", ".kts": "Kotlin",
        ".swift": "Swift",
        ".sh": "Shell", ".bash": "Shell",
        ".html": "HTML", ".htm": "HTML",
        ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
        ".sql": "SQL",
        ".yaml": "YAML", ".yml": "YAML",
        ".json": "JSON",
        ".md": "Markdown", ".markdown": "Markdown",
        ".toml": "TOML",
        ".xml": "XML",
    }
    # Obvious binary / asset extensions: present in a repo but carrying no source
    # Apex (or any analyser) would grade, so they're excluded from the scope
    # denominator rather than counted as "out of scope" code.
    _SCOPE_BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm", ".ogg",
        ".pyc", ".pyo", ".so", ".dll", ".dylib", ".o", ".a", ".class",
        ".exe", ".bin", ".db", ".sqlite", ".lock", ".whl", ".egg",
    }

    def __init__(self, root: str | Path, max_files: int = 2000) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def profile(self, *, light: bool = False) -> ProjectProfile:
        """Build the full project profile.

        ``light=True`` SKIPS every scan whose output the GRADE never reads, so
        ``health_score.grade`` can self-assess with a byte-identical result at a
        fraction of the cost (`apex ascend` re-grades before+after every round).
        Two skip groups, both proven safe — grade reads none of their fields:

        - the four git/doc subprocess scans (``_scan_churn``, ``_scan_debt_age``,
          ``_scan_security_exposure_age``, ``_scan_doc_drift``) → ``churn_hotspots``,
          ``change_coupling``, ``knowledge_risks``, ``debt_marker_ages``,
          ``security_finding_ages``, ``doc_drift``;
        - the three AST refactor scans (``_scan_dead_params``,
          ``_scan_extractable_blocks``, ``_scan_inlinable_helpers``) →
          ``dead_params``, ``extractable_blocks``, ``inlinable_helpers``.

        The grade's signals all come from ``_populate_python_structure`` and the
        base file walk, which always run; ``_drop_fixture_signals`` (which
        sanitizes the grade-read lists) also always runs. Default
        ``light=False`` keeps current behavior byte-identical for every other
        caller (the idea engine, seeding, develop fitness, ...).
        """
        profile = ProjectProfile(root=str(self.root))
        if not self.root.exists():
            return profile

        ext_counter: Counter[str] = Counter()
        dir_counter: Counter[str] = Counter()
        debt_counts: Counter[str] = Counter()
        security_finding_modules: list[str] = []
        correctness_bug_modules: list[str] = []

        skipped_dirs = {".turbo", ".next"}
        scanned = 0
        for path in self.root.rglob("*"):
            if scanned >= self.max_files:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            rel_str = str(rel)
            # Skip the canonical excluded dirs (incl. .claude worktrees) plus a
            # couple of JS-toolchain caches the canonical set doesn't carry.
            if is_skipped(rel) or any(part in skipped_dirs for part in rel.parts):
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
        # Analysis-scope accounting always runs (cheap; folded onto the file
        # walk's already-collected extension counts) so the grade can honestly
        # report how much of a polyglot repo its Python analysis covers.
        self._scan_analysis_scope(profile, ext_counter)
        if not light:
            # Polyglot hotspots: name the biggest / most-churned NON-Python
            # source files for the idea engine to recommend attention on. A
            # bounded git pass + walk that the GRADE never reads, so it is gated
            # out of the light path (the idea engine profiles with light=False;
            # an all-Python repo yields []).
            self._scan_polyglot_hotspots(profile)
            # Scans the GRADE never reads — skipped in light mode. The four
            # git/doc subprocess scans (cheap on a shallow repo, ~200s on a deep
            # one) and the three AST refactor scans (extractable/inlinable
            # dominate on a large codebase). _populate_python_structure above
            # already produced every field the grade consumes.
            self._scan_churn(profile)
            self._scan_debt_age(profile)
            self._scan_security_exposure_age(profile)
            self._scan_doc_drift(profile)
            self._scan_dead_params(profile)
            self._scan_extractable_blocks(profile)
            self._scan_inlinable_helpers(profile)
        self._drop_fixture_signals(profile)
        # Co-change test-gap reads the now-finalized ``change_coupling`` (git-only,
        # EMPTY in light mode) and ``module_to_tests``; it adds no new scan and in
        # light mode simply yields nothing.
        self._scan_cochange_test_gaps(profile)
        # Confluence runs LAST: it reads only the now-finalized, fixture-filtered
        # family fields and counts how many DISTINCT families name each module.
        # In light mode the git/co-change families are simply absent, so only the
        # families actually populated this run are counted — the scan never
        # claims a family ran that didn't.
        self._scan_confluences(profile)
        return profile

    def dead_params(self) -> list[dict]:
        """Just the never-read parameters — the dead-param scan IN ISOLATION.

        ``profile()`` also runs git-blame churn/age scans and the test linker,
        which take ~200s on a large repo; the develop ``dead-params`` objective's
        fitness and ranking only need this one list, so this pays for a single
        AST scan instead of the whole profile."""
        profile = ProjectProfile(root=str(self.root))
        self._scan_dead_params(profile)
        return list(profile.dead_params or [])

    def _scan_analysis_scope(self, profile: ProjectProfile,
                             ext_counter: Counter[str]) -> None:
        """Account for what fraction of the repo Apex's Python analysis covers.

        Apex grades only Python; on a polyglot repo that means the health grade
        speaks for a subset, not the whole. This scan makes the boundary honest
        and explicit. It reuses the base file walk's ``ext_counter`` (already
        built over the canonical skip-dir exclusion via ``is_skipped``) rather
        than re-walking the tree, so it stays cheap and deterministic.

        Source-bearing files are everything whose extension is NOT an obvious
        binary/asset type (``_SCOPE_BINARY_EXTENSIONS``); those form the
        denominator. Python files (``.py``/``.pyi``) are the analysed numerator.
        The non-Python remainder is bucketed by normalised language name
        (``_SCOPE_LANGUAGE_BY_EXT``), with any unmapped source extension folded
        into ``"other"`` so the breakdown's counts sum exactly. All dict outputs
        are sorted (count desc, then name) for stable rendering. Divide-by-zero
        (an empty or all-Python repo) yields ``analyzed_ratio == 1.0``.
        """
        source_total = 0
        python_total = 0
        breakdown: Counter[str] = Counter()
        for ext, count in ext_counter.items():
            if ext in self._SCOPE_BINARY_EXTENSIONS:
                continue
            source_total += count
            if ext in self._SCOPE_PYTHON_EXTENSIONS:
                python_total += count
                continue
            language = self._SCOPE_LANGUAGE_BY_EXT.get(ext, "other")
            breakdown[language] += count

        profile.source_file_count = source_total
        profile.python_file_count = python_total
        profile.language_breakdown = dict(
            sorted(breakdown.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        ratio = 1.0 if source_total == 0 else python_total / source_total
        profile.analyzed_ratio = ratio
        profile.out_of_scope_ratio = 1.0 - ratio

    def _scan_polyglot_hotspots(self, profile: ProjectProfile) -> None:
        """Name the biggest / most-churned NON-Python source files.

        Apex deep-analyses only Python; on a polyglot repo the non-Python risk
        concentrates in a handful of large, active files this scan NAMES (it does
        not pretend to analyse them). Delegates to ``scan_polyglot_facts``, which
        is a single bounded git pass ranked deterministically by
        ``(-churn, -loc, path)``; churn is git-only (0/empty outside a git repo,
        as in light mode) and an all-Python repo yields no facts, so this field
        stays empty there and seeding is byte-identical.

        Apex's OWN generated idea-report HTML (which a dashboard run may write
        INTO the very tree being profiled) is not project source worth attention,
        so it is filtered out by its stable ``<title>Apex Idea Tree</title>``
        marker. That keeps the signal honest (it names files the developer wrote,
        not Apex's artifacts) and keeps re-profiling the same tree deterministic.
        A few extra candidates are requested so the filter still yields up to 3
        real hotspots.
        """
        from app.tools.polyglot_facts import scan_polyglot_facts

        facts = scan_polyglot_facts(str(self.root), limit=6)
        hotspots: list[dict] = []
        for f in facts:
            if self._is_apex_report(f.path):
                continue
            hotspots.append(
                {"path": f.path, "language": f.language, "loc": f.loc, "churn": f.churn}
            )
            if len(hotspots) >= 3:
                break
        profile.polyglot_hotspots = hotspots

    # Stable marker the reporting layer writes into every generated idea-tree
    # page (``<title>Apex Idea Tree</title>``). An HTML file carrying it is an
    # Apex artifact, not project source.
    _APEX_REPORT_MARKER = "<title>Apex Idea Tree</title>"

    def _is_apex_report(self, rel_path: str) -> bool:
        """True if ``rel_path`` is an Apex-generated idea-report HTML page."""
        if not rel_path.lower().endswith((".html", ".htm")):
            return False
        try:
            head = (self.root / rel_path).read_text(
                encoding="utf-8", errors="ignore")[:2000]
        except OSError:
            return False
        return self._APEX_REPORT_MARKER in head

    def _scan_extractable_blocks(self, profile: ProjectProfile) -> None:
        """Long functions with a clean seam to extract — turns the engine's
        "extract a shared helper" recommendation into a concrete, copy-pasteable
        ``apex extract`` command (mirrors the dead-parameter signal). Only the
        project's own non-fixture modules; the single best seam per file."""
        from app.execution.extract_method import suggest_extractions

        skipped = {".git", "__pycache__", ".apex", ".epistemic", "node_modules",
                   ".venv", "venv", "dist", "build", ".turbo", ".next"}
        found: list[dict] = []
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            if any(part in skipped for part in rel.parts) or self._is_fixture_path(rel_str):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            suggestions = suggest_extractions(source)
            if suggestions:
                best = suggestions[0]  # already sorted: most lines saved first
                found.append({"module": rel_str, **best})
        found.sort(key=lambda d: (-d["lines_saved"], d["module"]))
        profile.extractable_blocks = found[:5]

    def _scan_inlinable_helpers(self, profile: ProjectProfile) -> None:
        """Tiny single-use helpers ``apex inline`` would cleanly accept — turns
        the "fold a thin helper back into its call site" recommendation into a
        concrete, copy-pasteable ``apex inline FUNC`` command (mirrors the
        extractable-block signal). The analyzer is conservative by construction
        (see ``suggest_inlines``); here we just exclude fixture/test paths and
        keep the strongest few (fewest call sites first, then module)."""
        from app.execution.inline_function import suggest_inlines

        found = [
            h for h in suggest_inlines(self.root)
            if not self._is_fixture_path(h["module"])
        ]
        found.sort(key=lambda d: (d["call_sites"], d["module"], d["function"]))
        profile.inlinable_helpers = found[:5]

    def _scan_dead_params(self, profile: ProjectProfile) -> None:
        """Parameters no statement in the function body ever reads.

        Dead weight on the API surface — every caller is forced to know about
        a knob that does nothing. Conservative by construction, each rule a
        real false-positive class:
          - only top-level functions whose NAME is unique project-wide
            (interface families — many modules defining the same ``apply()`` —
            conform to a shared signature, not their own needs);
          - never referenced as a bare object anywhere (callbacks, dispatch
            tables and ``set_defaults(func=...)`` impose their signature);
          - no decorators (frameworks impose signatures too);
          - a real body (stubs/protocol methods keep their params);
          - the parameter isn't ``_``-prefixed (already declared intentional)
            and isn't ``*args``/``**kwargs``.
        """
        skipped_dirs = {".git", "__pycache__", ".apex", ".epistemic", "node_modules",
                        ".venv", "venv", "dist", "build", ".turbo", ".next"}
        defs_by_name: dict[str, list[tuple[str, ast.AST]]] = {}
        object_refs: set[str] = set()
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            if any(part in skipped_dirs for part in rel.parts):
                continue
            if self._is_fixture_path(rel_str):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            scanned += 1
            call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for node in ast.walk(tree):
                # Any non-call reference means the function travels as an
                # object — its signature belongs to whoever receives it.
                if isinstance(node, ast.Name) and id(node) not in call_funcs:
                    object_refs.add(node.id)
                elif isinstance(node, ast.Attribute) and id(node) not in call_funcs:
                    object_refs.add(node.attr)
            for fn in tree.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs_by_name.setdefault(fn.name, []).append((rel_str, fn))

        found: list[dict] = []
        for name, defs in defs_by_name.items():
            if len(defs) != 1 or name in object_refs:
                continue
            rel_str, fn = defs[0]
            if fn.decorator_list:
                continue
            body = [s for s in fn.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            if all(isinstance(s, (ast.Pass, ast.Raise)) for s in body):
                continue  # stub / protocol shape — params are the contract
            read = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            a = fn.args
            for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
                if p.arg.startswith("_") or p.arg in ("self", "cls"):
                    continue
                if p.arg not in read:
                    found.append({"module": rel_str, "function": name,
                                  "param": p.arg, "line": fn.lineno})
        found.sort(key=lambda d: (d["module"], d["line"], d["param"]))
        profile.dead_params = found[:5]

    # Backticked tokens that look like file paths. No spaces (so command lines
    # with flags never match), and either a path separator or a .py suffix.
    _DOC_REF_RE = re.compile(r"`([^`\s]+)`")
    _DOC_PLACEHOLDERS = ("path/to", "your", "<", ">", "{", "}", "*", "...", "$")

    def _scan_doc_drift(self, profile: ProjectProfile) -> None:
        """Backticked file references in README/docs that don't exist on disk.

        Documentation is the project's promise surface: a README that points
        at `app/foo.py` while no such file exists is concrete, traceable
        drift — either the doc lies or the capability is missing. Runtime
        artifact dirs (.apex/…) and placeholder-looking tokens are skipped so
        the signal stays precise.
        """
        docs = [p for p in [self.root / "README.md", *sorted((self.root / "docs").glob("*.md"))]
                if p.exists()][:10]
        skipped_roots = {".git", "__pycache__", ".apex", ".epistemic", "node_modules",
                         ".venv", "venv", "dist", "build"}
        drift: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for doc in docs:
            rel_doc = doc.relative_to(self.root).as_posix()
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for ref in self._DOC_REF_RE.findall(line):
                    ref = ref.strip()
                    while ref.startswith("./"):
                        ref = ref[2:]
                    # Path-like = has a separator, doesn't start with one
                    # (slash-commands), and its final segment carries a real
                    # file extension (so `hashlib.md5/sha1` never matches).
                    if "/" not in ref or ref.startswith("/"):
                        continue
                    last = ref.split(":", 1)[0].rsplit("/", 1)[-1]
                    if "." not in last or last.rsplit(".", 1)[-1].lower() not in {
                        "py", "md", "json", "yml", "yaml", "toml", "txt",
                        "html", "css", "js", "sh", "cfg", "ini",
                    }:
                        continue
                    low = ref.lower()
                    if (low.startswith(("http://", "https://"))
                            or any(t in low for t in self._DOC_PLACEHOLDERS)):
                        continue
                    path_part = ref.split(":", 1)[0]  # allow `app/x.py:12`
                    first_seg = path_part.split("/", 1)[0]
                    if first_seg in skipped_roots or not path_part:
                        continue
                    if (self.root / path_part).exists():
                        continue
                    key = (rel_doc, path_part)
                    if key in seen:
                        continue
                    seen.add(key)
                    drift.append({"doc": rel_doc, "reference": path_part, "line": lineno})
                    if len(drift) >= 5:
                        profile.doc_drift = drift
                        return
        profile.doc_drift = drift

    def _scan_security_exposure_age(self, profile: ProjectProfile) -> None:
        """How long each flagged module's OLDEST security finding has existed.

        Uses the canonical detector for the finding lines and git blame for
        their birth dates (HEAD-anchored, like debt age) — the *exposure
        window* the idea engine narrates when prioritizing security work.
        """
        if not profile.security_finding_modules:
            return
        from app.engine.detectors import detect
        from app.tools.git_history import blame_age_days

        ages: dict[str, int] = {}
        for module in profile.security_finding_modules:
            try:
                source = (self.root / module).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            line_ages = [
                age for issue in detect(source) if issue.category == "security"
                and (age := blame_age_days(self.root, module, issue.line)) is not None
            ]
            if line_ages:
                ages[module] = max(line_ages)
        profile.security_finding_ages = ages

    def _scan_debt_age(self, profile: ProjectProfile) -> None:
        """How long each flagged module's OLDEST debt marker has waited (days).

        Uses ``git blame`` on the (<= 5) debt-marker modules and anchors "now"
        to the HEAD commit time — not the wall clock — so the result is
        deterministic for a given repo state. Non-git targets yield no ages.
        """
        if not profile.debt_marker_modules:
            return
        import subprocess

        def _git(*args: str):
            return subprocess.run(["git", *args], cwd=self.root,
                                  capture_output=True, text=True, timeout=15)

        try:
            head = _git("log", "-1", "--format=%ct")
        except Exception:
            return
        if head.returncode != 0 or not head.stdout.strip():
            return
        now = int(head.stdout.strip())

        ages: dict[str, int] = {}
        for module in profile.debt_marker_modules:
            try:
                blame = _git("blame", "--line-porcelain", "--", module)
            except Exception:
                continue
            if blame.returncode != 0:
                continue
            oldest: int | None = None
            ctime: int | None = None
            for line in blame.stdout.splitlines():
                if line.startswith("committer-time "):
                    try:
                        ctime = int(line.split()[1])
                    except (IndexError, ValueError):
                        ctime = None
                if (line.startswith("\t") and ctime is not None) and (self.DEBT_MARKER_RE.search(line)):
                    oldest = ctime if oldest is None else min(oldest, ctime)
            if oldest is not None:
                ages[module] = max(0, (now - oldest) // 86400)
        profile.debt_marker_ages = ages

    def _scan_churn(self, profile: ProjectProfile) -> None:
        """One pass over recent git history yields TWO temporal signals:

        - **churn hotspots** — modules recent commits touch most (where
          development energy goes);
        - **change coupling** — module pairs that repeatedly change in the
          *same* commit: factually coupled whether or not an import connects
          them, the hidden seam static analysis can't see.

        Mega-commits (> MAX_COMMIT_FILES files) are excluded from coupling —
        a sweeping reformat couples everything and means nothing. Non-git
        directories simply yield no signal.
        """
        import subprocess
        from itertools import combinations

        try:
            out = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:@commit@%an",
                 "-n", str(self.CHURN_COMMIT_WINDOW)],
                cwd=self.root, capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return
        if out.returncode != 0:
            return

        commits: list[tuple[str, list[str]]] = []  # (author, files)
        author, current = "", []
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("@commit@"):
                if current:
                    commits.append((author, current))
                author, current = line[len("@commit@"):], []
            elif line:
                current.append(line)
        if current:
            commits.append((author, current))

        counts: Counter[str] = Counter()
        pair_counts: Counter[tuple[str, str]] = Counter()
        author_touches: dict[str, Counter[str]] = {}  # module -> author -> n
        all_authors: set[str] = set()
        for commit_author, files in commits:
            all_authors.add(commit_author)
            pys = sorted({
                rel for rel in files
                if rel.endswith(".py") and not self._is_fixture_path(rel)
                and (self.root / rel).exists()
            })
            for rel in pys:
                counts[rel] += 1
                author_touches.setdefault(rel, Counter())[commit_author] += 1
            if 2 <= len(pys) <= self.MAX_COMMIT_FILES:
                for a, b in combinations(pys, 2):
                    pair_counts[(a, b)] += 1

        profile.churn_hotspots = [
            {"module": module, "commits": commits_n}
            for module, commits_n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            if commits_n >= self.CHURN_THRESHOLD
        ]
        profile.change_coupling = [
            {"a": a, "b": b, "commits": n}
            for (a, b), n in sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            if n >= self.COCHANGE_THRESHOLD
        ]

        # Knowledge concentration only means something when at least TWO
        # authors are genuinely active (a drive-by single commit or a bot
        # doesn't make a project multi-author).
        author_commits: Counter[str] = Counter(a for a, _files in commits)
        active = [a for a, n in author_commits.items() if n >= self.KNOWLEDGE_MIN_COMMITS]
        if len(active) >= 2:
            risks = []
            for module, by_author in author_touches.items():
                total = sum(by_author.values())
                if total < self.KNOWLEDGE_MIN_COMMITS:
                    continue
                top = by_author.most_common(1)[0][1]
                share = top / total
                if share >= self.KNOWLEDGE_SHARE:
                    risks.append({"module": module, "share": int(share * 100),
                                  "commits": total})
            risks.sort(key=lambda r: (-r["share"], -r["commits"], r["module"]))
            profile.knowledge_risks = risks[:5]

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
        if profile.impure_untested_functions:
            profile.impure_untested_functions = [
                f for f in profile.impure_untested_functions
                if not self._is_fixture_path(str(f.get("module", "")))
            ]
        if profile.hub_untested_modules:
            profile.hub_untested_modules = [
                h for h in profile.hub_untested_modules
                if not self._is_fixture_path(str(h.get("module", "")))
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
        # Quantified fan-in / heaviest-fan-out, read straight off the graph just
        # built (no second graph). Fan-in is the blast radius (in_degree); the
        # heaviest fan-out targets are this module's own dependencies, ranked by
        # how depended-on each is (the target's fan-in — shedding the most-central
        # one cuts the most convergence), then by path for determinism.
        profile.module_fanin = {
            node.path: node.in_degree
            for node in graph.values() if node.in_degree > 0
        }
        profile.module_fanout = {
            node.path: [
                target for target in sorted(
                    node.imports,
                    key=lambda t: (-(graph[t].in_degree if t in graph else 0), t),
                )
            ][:3]
            for node in graph.values() if node.imports
        }
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

        # Purity-violation: impure functions in those same risky modules that no
        # test exercises — "isolate the side effect, then cover the core". Reuses
        # the already-built candidate set and the same coverage check, so it adds
        # no extra whole-repo scan on the hot path.
        profile.impure_untested_functions = self._scan_impure_untested_functions(
            candidates, profile.module_to_tests
        )

        # Dependency hubs (high fan-in) that are also untested/shallow — the
        # highest-leverage place to add a regression net, because a break there
        # propagates to every dependent. Reuses the already-built dependency
        # graph (``n.in_degree`` = fan-in), the linker's ``module_to_tests`` (a
        # module is untested when it has no linked tests) and the shallow set —
        # no new scan. Deduped against the more-severe module-level signals
        # (fragile/hotspot), which frame such a module first.
        shallow = set(self._scan_shallow_tests(profile.module_to_tests, limit=None))
        profile.hub_untested_modules = self._scan_hub_untested_modules(
            graph, profile.module_to_tests, shallow,
            claimed=set(profile.fragile_modules) | set(profile.hotspot_modules),
        )

    @staticmethod
    def _is_test_path(rel: str) -> bool:
        r = rel.replace("\\", "/").lower()
        return (r.startswith(("tests/", "test/")) or "/tests/" in f"/{r}"
                or Path(r).stem.startswith("test_"))

    def _whole_suite_text_factory(self):
        """A memoized loader for the concatenated test-suite source.

        Read at most once per scan (the fallback corpus for modules the linker
        doesn't track), so reusing the same callable across function-level scans
        never re-walks the tree.
        """
        cache: dict[str, str] = {}

        def _whole_suite_text() -> str:
            if "v" not in cache:
                parts: list[str] = []
                for p in sorted(self.root.rglob("*.py")):
                    rel = str(p.relative_to(self.root))
                    if self._is_test_path(rel):
                        try:
                            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                        except OSError:
                            continue
                cache["v"] = "\n".join(parts)
            return cache["v"]

        return _whole_suite_text

    def _coverage_checker(self, module: str, source: str, module_to_tests: dict,
                          whole_suite_text):
        """Return an ``_exercised(qualified_name) -> bool`` for one module.

        Coverage is name-based but wrapper-aware (shared by every function-level
        scan): a function counts as covered when a linked test names it
        directly, names its enclosing class (tests driving ``Limb.run()``
        exercise ``Limb._execute``), or names a sibling function that references
        it (a private helper tested through its public wrapper). Modules the
        linker doesn't track fall back to the whole-suite corpus before being
        accused of being untested.
        """
        import ast

        if module in module_to_tests:
            test_text = ""
            for rel in module_to_tests.get(module, []) or []:
                try:
                    test_text += (self.root / rel).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
        else:
            test_text = whole_suite_text()

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

        return _exercised

    def _scan_hotspot_functions(self, candidates: list[str], module_to_tests: dict) -> list[dict]:
        """Complex functions inside risky modules that no linked test exercises.

        "Exercises" is wrapper-aware (see ``_coverage_checker``).
        """
        from app.tools.code_metrics import function_complexities
        from app.tools.cognitive_complexity import function_cognitive_complexities

        whole_suite_text = self._whole_suite_text_factory()

        out: list[dict] = []
        for module in candidates:
            if not module.endswith(".py") or self._is_test_path(module):
                continue
            try:
                source = (self.root / module).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            _exercised = self._coverage_checker(module, source, module_to_tests,
                                                whole_suite_text)

            # Branch counts keep driving the threshold (stable scores);
            # cognitive complexity narrates how hard the code READS.
            cognitive_by_name = {
                name: cog for name, _ln, cog in function_cognitive_complexities(source)
            }
            for name, lineno, complexity in function_complexities(source):
                if complexity < 8:
                    continue  # a real branching function, not a trivial one
                simple = name.rsplit(".", 1)[-1]
                if simple.startswith("__") and simple.endswith("__"):
                    continue
                if _exercised(name):
                    continue
                out.append({"module": module, "function": name,
                            "line": lineno, "complexity": complexity,
                            "cognitive": cognitive_by_name.get(name, 0)})
        out.sort(key=lambda d: (-d["complexity"], d["module"], d["function"]))
        return out[:5]

    def _scan_impure_untested_functions(self, candidates: list[str],
                                        module_to_tests: dict) -> list[dict]:
        """Impure functions inside risky modules that no linked test exercises.

        Reuses the just-added purity dimension of ``FunctionFractalAnalyzer``:
        a function is impure when it mixes observable side effects (I/O, global/
        nonlocal state, effect-module calls like ``os.system``/``logging.info``)
        with logic. An impure-AND-untested function is the high-leverage "isolate
        the side effect, then cover the now-testable core" target. Scanned over
        the SAME bounded candidate set as the complexity hotspots — no extra
        whole-repo walk on the hot path — and sharing the wrapper-aware coverage
        check, so the two scans agree on what "untested" means.
        """
        from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer

        analyzer = FunctionFractalAnalyzer()
        whole_suite_text = self._whole_suite_text_factory()

        out: list[dict] = []
        for module in candidates:
            if not module.endswith(".py") or self._is_test_path(module):
                continue
            path = self.root / module
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            try:
                fns = analyzer.analyze_file(path)
            except (OSError, SyntaxError):
                continue
            if not fns:
                continue
            _exercised = self._coverage_checker(module, source, module_to_tests,
                                                whole_suite_text)
            for fn in fns:
                if fn.get("purity") != "impure":
                    continue
                name = fn["name"]
                simple = name.rsplit(".", 1)[-1]
                if simple.startswith("__") and simple.endswith("__"):
                    continue
                if _exercised(name):
                    continue
                out.append({"module": module, "function": name,
                            "line": fn.get("lineno", 0),
                            "side_effects": list(fn.get("side_effects", []))})
        # Most side-effect reasons first (the broadest violation), then stable
        # by module/function so the ordering is deterministic.
        out.sort(key=lambda d: (-len(d["side_effects"]), d["module"], d["function"]))
        return out[:5]

    # Fan-in bar for a *hub* (not merely "depended on by >=2", which is the
    # fragility floor): a module many others import, where a regression has the
    # widest blast radius. Kept strictly above the fragility floor so the two
    # signals describe different populations rather than restating each other.
    _HUB_FAN_IN_FLOOR = 3

    def _scan_hub_untested_modules(self, graph: dict, module_to_tests: dict,
                                   shallow: set, claimed: set) -> list[dict]:
        """High-fan-in hub modules that are also untested or shallow-tested.

        A dependency HUB (``n.in_degree`` >= ``_HUB_FAN_IN_FLOOR`` — many modules
        import it) with thin coverage is the highest-leverage place to add a
        regression net: a break there propagates to every dependent. Reuses the
        already-built dependency ``graph`` (fan-in is ``in_degree``, the SAME
        measure ``fragile_modules`` uses), the linker's uncapped
        ``module_to_tests`` (a module is untested when it has no linked tests)
        and the ``shallow`` set — no new whole-repo scan. "Untested or shallow"
        is the SAME coverage notion fragility uses, just read from an uncapped
        source so a hub outside the top-5 ``untested_modules`` still counts.
        Modules already framed by a more-severe module-level signal (``claimed``
        = fragile + hotspot) are skipped so this never double-counts; mirrors how
        impure-untested dedups under the more-severe hotspot-function root.
        """
        out: list[dict] = []
        for node in graph.values():
            path = node.path
            if path in claimed:
                continue  # a more-severe signal already frames this module
            if node.in_degree < self._HUB_FAN_IN_FLOOR:
                continue  # not a hub
            if self._is_test_path(path):
                continue  # test files are not the subject of a regression net
            untested = not (module_to_tests.get(path) or [])
            if not (untested or path in shallow):
                continue  # already has real coverage
            out.append({"module": path, "fan_in": node.in_degree})
        # Widest blast radius first (most dependents), then stable by module so
        # the ordering is deterministic.
        out.sort(key=lambda d: (-d["fan_in"], d["module"]))
        return out[:5]

    # The DISTINCT signal families a confluence converges, mapped to a stable,
    # human-readable family name. Each entry yields the set of modules that
    # family names this run; a family that didn't run (light mode, no git, etc.)
    # simply contributes nothing, so confluence never over-counts. Order here is
    # irrelevant — family names are sorted at output for determinism.
    _CONFLUENCE_MIN_FAMILIES = 3

    @staticmethod
    def _confluence_families(profile: "ProjectProfile") -> dict[str, set[str]]:
        """Per-family set of modules named, reusing only existing profile fields.

        Every family is a list/dict already populated by an earlier scan; a
        module never contributes to the same family twice (sets dedup), so the
        family count is a count of DISTINCT independent pressures, not of facts.
        Families absent this run (e.g. churn/co-change in light mode) yield an
        empty set and are skipped — the scan never claims a family that didn't
        run.
        """
        def _flat(values) -> set[str]:
            return {str(v) for v in (values or []) if v}

        def _key(entries, key: str) -> set[str]:
            return {str(e.get(key, "")) for e in (entries or []) if e.get(key)}

        families: dict[str, set[str]] = {
            "complex-function": (
                _key(getattr(profile, "hotspot_functions", []), "module")
                | _flat(getattr(profile, "hotspot_modules", []))
            ),
            "high-churn": _key(getattr(profile, "churn_hotspots", []), "module"),
            "hub": _flat(getattr(profile, "dependency_hubs", [])),
            "symbol-hub": _flat(getattr(profile, "symbol_hubs", [])),
            "fragile": _flat(getattr(profile, "fragile_modules", [])),
            "untested": (
                _flat(getattr(profile, "untested_modules", []))
                | _flat(getattr(profile, "critical_untested_modules", []))
                | _key(getattr(profile, "hub_untested_modules", []), "module")
            ),
            "shallow-coverage": _flat(getattr(profile, "shallow_tested_modules", [])),
            "impure": _key(getattr(profile, "impure_untested_functions", []), "module"),
            "security": _flat(getattr(profile, "security_finding_modules", [])),
            "correctness-bug": _flat(getattr(profile, "correctness_bug_modules", [])),
            "debt-markers": _flat(getattr(profile, "debt_marker_modules", [])),
            "modernizable": _flat(getattr(profile, "modernizable_modules", [])),
            "co-change": (
                _key(getattr(profile, "change_coupling", []), "a")
                | _key(getattr(profile, "change_coupling", []), "b")
            ),
        }
        return {name: mods for name, mods in families.items() if mods}

    def _scan_confluences(self, profile: ProjectProfile) -> None:
        """Modules named by >= 3 DISTINCT signal families — signal convergence.

        A module under several independent pressures is the highest-leverage
        development target, yet no single lens names it. This reuses only fields
        already on the profile (no new scan), counts each family at most once,
        and respects light mode (absent families contribute nothing). Output is
        deterministic: family_count desc, then module asc, with a sorted family
        tuple per entry.
        """
        families = self._confluence_families(profile)
        per_module: dict[str, set[str]] = {}
        for name, modules in families.items():
            for module in modules:
                per_module.setdefault(module, set()).add(name)
        out: list[dict] = []
        for module, names in per_module.items():
            if len(names) < self._CONFLUENCE_MIN_FAMILIES:
                continue
            out.append({
                "module": module,
                "family_count": len(names),
                "families": tuple(sorted(names)),
            })
        out.sort(key=lambda d: (-d["family_count"], d["module"]))
        profile.confluence_modules = out[:5]

    def _scan_cochange_test_gaps(self, profile: ProjectProfile) -> list[dict]:
        """Co-change PAIRS that no single test exercises together — a test gap.

        ``change_coupling`` already captures module pairs that frequently change
        in the SAME commits (from git). When two modules co-change a lot but NO
        single test file references BOTH, a change to one can silently break the
        other with nothing to catch it — a grounded, high-value test gap. Reuses
        ``change_coupling`` (git-only, EMPTY under ``light=True`` — so this yields
        nothing in light mode, exactly like confluence) and the linker's
        ``module_to_tests`` (no new scan). A pair has a "shared test" when some
        test path appears in BOTH modules' linked-test lists; such pairs are
        skipped. Deterministic: cochanges desc, then pair asc; capped at 5.

        For each surviving pair, the actual code LINK is named: which symbol one
        module imports from the other (``a`` from ``b`` and ``b`` from ``a``),
        resolved by parsing the two files' ``from X import Y`` statements with
        ``ast`` and mapping ``X`` back to the other file. Each gap gains an
        additive ``links`` key: a deterministic, sorted list of
        ``{"from","to","symbol"}`` (capped at 3) so the recommendation can name
        the real interface, not just the pair. The key is OMITTED when no link is
        found (they co-change but don't directly import each other) — keeping the
        no-link dicts byte-identical to the original two-field shape.
        """
        module_to_tests = profile.module_to_tests or {}
        out: list[dict] = []
        for entry in profile.change_coupling or []:
            a, b = entry.get("a"), entry.get("b")
            if not a or not b:
                continue
            if is_skipped(a) or is_skipped(b):
                continue
            tests_a = set(module_to_tests.get(a, []) or [])
            tests_b = set(module_to_tests.get(b, []) or [])
            if tests_a & tests_b:
                continue  # a single test already exercises both — no gap
            out.append({"a": a, "b": b, "cochanges": int(entry.get("commits", 0))})
        out.sort(key=lambda d: (-d["cochanges"], d["a"], d["b"]))
        gaps = out[:5]
        # Name the concrete link only for the surviving (capped) pairs — no parse
        # for dropped entries. The module map is built once and shared.
        module_map = self._cochange_module_map(gaps)
        for gap in gaps:
            links = self._cochange_links(gap["a"], gap["b"], module_map)
            if links:
                gap["links"] = links
        profile.cochange_test_gaps = gaps
        return profile.cochange_test_gaps

    def _cochange_module_map(self, gaps: list[dict]) -> dict[str, str]:
        """Map ``dotted.module`` -> repo-relative file path for the gap modules.

        Built only from the files referenced by ``gaps`` (the <=5 surviving pairs)
        so it adds no full-repo walk. Mirrors ``DependencyGraphBuilder._module_map``
        (drops the ``.py`` suffix, collapses ``__init__``). Returns ``{}`` when no
        filesystem root is available (e.g. a profile-only scan) so link resolution
        is a clean no-op rather than an error.
        """
        if not getattr(self, "root", None):
            return {}
        paths: set[str] = set()
        for gap in gaps:
            paths.add(gap["a"])
            paths.add(gap["b"])
        mapping: dict[str, str] = {}
        for rel in paths:
            parts = list(Path(rel).with_suffix("").parts)
            if not parts:
                continue
            if parts[-1] == "__init__":
                module_name = ".".join(parts[:-1])
            else:
                module_name = ".".join(parts)
            if module_name:
                mapping[module_name] = rel
        return mapping

    def _cochange_links(self, a: str, b: str, module_map: dict[str, str]) -> list[dict]:
        """The symbols ``a`` imports from ``b`` (and ``b`` from ``a``), via ast.

        Parses both files, walks ``ImportFrom`` nodes, resolves each ``node.module``
        to a repo file (via ``module_map``, longest-prefix like the dependency
        graph) and — when it resolves to the OTHER module of the pair — records the
        imported names. Returns a deterministic, sorted list of
        ``{"from","to","symbol"}`` capped at 3. Empty when the two co-change but
        don't directly import each other, or when a file can't be parsed.
        """
        if not module_map:
            return []
        links: list[dict] = []
        for src, dst in ((a, b), (b, a)):
            for symbol in self._imported_symbols(src, dst, module_map):
                links.append({"from": src, "to": dst, "symbol": symbol})
        links.sort(key=lambda d: (d["from"], d["to"], d["symbol"]))
        return links[:3]

    def _imported_symbols(self, src: str, dst: str, module_map: dict[str, str]) -> list[str]:
        """Names ``src`` imports from ``dst`` via ``from <dst-module> import ...``."""
        root = getattr(self, "root", None)
        if not root:
            return []
        try:
            source = (root / src).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            return []
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level:
                continue  # relative imports carry no resolvable absolute module
            module = node.module or ""
            if not module:
                continue
            if self._resolve_cochange_module(module, module_map) != dst:
                continue
            for alias in node.names:
                if alias.name and alias.name != "*":
                    found.add(alias.name)
        return sorted(found)

    @staticmethod
    def _resolve_cochange_module(import_name: str, module_map: dict[str, str]) -> str | None:
        """Resolve a dotted import to a repo file (longest-prefix match)."""
        if import_name in module_map:
            return module_map[import_name]
        parts = import_name.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in module_map:
                return module_map[candidate]
            parts.pop()
        return None

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


def render_analysis_scope_line(profile: ProjectProfile) -> str:
    """One honest, factual line about how much of the repo Apex analysed.

    Pure (no I/O) and deterministic — reads only the scope fields the profiler
    already computed. The line reads as a strength: Apex states exactly what it
    did and did NOT cover, rather than implying its Python grade speaks for a
    polyglot whole. Returns ``""`` whenever there is nothing to disclose — an
    empty repo, or an all-Python one where the Python grade genuinely speaks for
    the whole project; the line appears only when real out-of-scope content
    exists (``out_of_scope_ratio > 0`` with a non-empty breakdown), so it is
    purely additive and never noise on a single-language Python project.

    When real out-of-scope content exists, the counts line is followed by a
    concrete attention clause (from ``app.tools.polyglot_facts``) naming the
    biggest / most-churned non-Python files — so the honest boundary becomes
    actionable instead of stopping at a percentage. That clause is purely
    additive: it appears ONLY inside the out-of-scope branch, so an all-Python
    repo's line is byte-identical (and empty).

    Example::

        Scope: analysing 62% of the repo (Python). 38% is outside analysis
        scope — JavaScript 41 files, HTML 12, CSS 7. Largest / most-active files
        outside analysis scope: `src/app.js` (412 LOC, 8 commits), … — Apex
        can't deep-analyse these yet, but they're where the non-Python risk
        concentrates.
    """
    if profile.source_file_count <= 0:
        return ""
    if not (profile.out_of_scope_ratio > 0 and profile.language_breakdown):
        return ""  # all-Python: the grade already speaks for the whole repo
    analysed_pct = round(profile.analyzed_ratio * 100)
    out_pct = round(profile.out_of_scope_ratio * 100)
    # language_breakdown is already sorted (count desc, then name); render the
    # first language with its " files" unit, the rest as bare counts.
    items = list(profile.language_breakdown.items())
    parts = [f"{lang} {count} files" if i == 0 else f"{lang} {count}"
             for i, (lang, count) in enumerate(items)]
    line = (
        f"Scope: analysing {analysed_pct}% of the repo (Python). "
        f"{out_pct}% is outside analysis scope — {', '.join(parts)}."
    )
    # Name the concrete files behind that percentage, reusing the profile's
    # existing root. Only reached when out-of-scope content exists, so the
    # all-Python path above never imports/runs this — output stays identical.
    from app.tools.polyglot_facts import (
        render_polyglot_attention,
        scan_polyglot_facts,
    )
    attention = render_polyglot_attention(scan_polyglot_facts(profile.root))
    if attention:
        line = f"{line} {attention}"
    return line
