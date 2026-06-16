from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files


@dataclass
class ModuleStructure:
    path: str
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


# Process-level cache for the expensive per-file work (read + ``ast.parse`` +
# tree walk). A single ideate/dashboard build constructs FIVE separate analyzers
# (code_metrics, dependency_graph, project_profile, ...), each re-reading and
# re-parsing the ENTIRE source tree — ~2,500 redundant parses, ~18s of pure
# waste, since the files do not change within one build.
#
# Key: ``(absolute_resolved_path, st_mtime_ns)``. The absolute path keeps two
# different roots that touch the same file from colliding; the mtime makes the
# cache self-invalidating — a file rewritten between builds (tests rely on this)
# gets a fresh key and is re-analyzed. We cache the parse result (imports +
# symbols), NOT the ``ModuleStructure``, because only the latter's ``path`` is
# root-relative: the same file under a different root reuses the cached parse but
# still gets its own relative path, so output is byte-for-byte identical to today.
_PARSE_CACHE: dict[tuple[str, int], tuple[list[str], list[str]] | None] = {}

# Process-level cache for the raw ``ast.Module`` parse, shared by the three
# per-function complexity analyzers (code_metrics, cognitive_complexity,
# complexity_profile). Each of those used to run its OWN ``ast.parse`` over the
# whole tree — three full re-parses per build for one metric family. Routing
# them through :func:`parse_cached` collapses that to a single parse per file.
#
# Key: ``(absolute_resolved_path, st_mtime_ns)`` — the SAME scheme as
# ``_PARSE_CACHE`` but a DISTINCT dict, so the existing ``(imports, symbols)``
# entries are never touched and the two caches invalidate independently. mtime
# is a cache key ONLY; it never reaches any analyzer's output, so determinism
# (same file content -> same tree -> same metric) is preserved.
_TREE_CACHE: dict[tuple[str, int], ast.Module | None] = {}


def _is_type_checking_test(test: ast.expr) -> bool:
    """True if an ``if`` test is ``TYPE_CHECKING`` (bare or ``typing.TYPE_CHECKING``).

    Imports guarded by such a block never execute at runtime, so they are
    type-only and must not be counted as real import edges.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class PythonStructureAnalyzer:
    def __init__(self, root: str | Path, max_files: int = 500) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def analyze(self) -> list[ModuleStructure]:
        if not self.root.exists():
            return []

        results: list[ModuleStructure] = []
        scanned = 0
        # iter_source_files is sorted AND prunes excluded/worktree dirs, so the
        # max_files cap below is applied AFTER filtering: deterministic across
        # machines (CI vs local), kept in sync with the all-files module map, and
        # never filled with .claude worktree copies (which sort first and would
        # otherwise crowd out every real module before the cap is reached).
        for path in iter_source_files(self.root):
            if scanned >= self.max_files:
                break
            scanned += 1
            structure = self._analyze_file(path)
            if structure is not None:
                results.append(structure)
        return results

    def _analyze_file(self, path: Path) -> ModuleStructure | None:
        parsed = _parse_file(path)
        if parsed is None:
            return None
        imports, symbols = parsed
        rel = str(path.relative_to(self.root))
        # Copy the cached lists so a caller mutating ModuleStructure.imports/symbols
        # cannot corrupt a shared cache entry reused by the next analyzer.
        return ModuleStructure(path=rel, imports=list(imports), symbols=list(symbols))


def parse_cached(path: str | Path) -> ast.Module | None:
    """Read + ``ast.parse`` ``path`` into an ``ast.Module``, memoized per build.

    Returns the SAME tree object an unguarded ``ast.parse(path.read_text(...))``
    would produce, so any analyzer that walks it gets byte-identical results —
    the only change is that the file is read + parsed AT MOST ONCE per process
    (keyed by ``(absolute path, st_mtime_ns)``), instead of once per analyzer.

    Returns ``None`` for unreadable / unparseable files (and caches that ``None``
    so a known-bad file is not retried by the next analyzer). When the file has
    no stable stat key, falls back to an uncached parse so behavior matches the
    callers' original ``read_text`` + ``ast.parse`` exactly.
    """
    p = Path(path)
    try:
        stat = p.stat()
    except (OSError, ValueError):
        return _parse_tree(p)

    key = (str(p.resolve()), stat.st_mtime_ns)
    if key in _TREE_CACHE:
        return _TREE_CACHE[key]

    tree = _parse_tree(p)
    _TREE_CACHE[key] = tree
    return tree


def _parse_tree(path: Path) -> ast.Module | None:
    """Uncached read + ``ast.parse`` of one file; ``None`` if it can't be read
    or doesn't parse. Mirrors the analyzers' original error handling exactly."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        return ast.parse(source)
    except (SyntaxError, OSError, ValueError):
        return None


def _parse_file(path: Path) -> tuple[list[str], list[str]] | None:
    """Read + parse ``path`` into ``(sorted imports, sorted symbols)``, memoized.

    Keyed by ``(absolute path, st_mtime_ns)`` so the same file is read + parsed +
    walked AT MOST ONCE per build, yet a file that changes between builds (new
    mtime) is re-analyzed. Returns ``None`` for unreadable / unparseable files
    (and caches that ``None`` so a known-bad file isn't retried each scanner).
    """
    try:
        stat = path.stat()
    except (OSError, ValueError):
        # No stat -> no stable key. Fall through to the uncached path so callers
        # still see today's behavior (e.g. read_text raising on a bad argument).
        return _parse_source(path)

    key = (str(path.resolve()), stat.st_mtime_ns)
    if key in _PARSE_CACHE:
        return _PARSE_CACHE[key]

    parsed = _parse_source(path)
    _PARSE_CACHE[key] = parsed
    return parsed


def _parse_source(path: Path) -> tuple[list[str], list[str]] | None:
    """Uncached read + parse + extract. Single source of the import/symbol graph."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (SyntaxError, OSError, ValueError):
        return None

    imports: list[str] = []
    symbols: list[str] = []

    # Imports under `if TYPE_CHECKING:` are type-only — they never run, so they
    # are NOT real import edges. Counting them lets a type-hint import that was
    # added to BREAK a cycle get miscounted AS a cycle (a false positive that
    # cost real grade points). Collect those nodes and skip them below. The
    # `else` arm of such a block DOES run, so only its `body` is excluded.
    type_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        type_only.add(id(inner))

    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                imports.append(module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)

    return sorted(set(imports)), sorted(set(symbols))
