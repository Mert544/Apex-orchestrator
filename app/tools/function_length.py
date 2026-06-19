"""Deterministic FUNCTION-LENGTH analyzer — a flat-but-long counterpart to
cyclomatic complexity.

Cyclomatic complexity scores how *branchy* a function is; a function can be
perfectly flat (no branches, complexity 1) yet still be 200 lines of sequential
statements that no one can hold in their head. This module measures that other
axis: the **lines of code per function body** — the distribution across a tree,
how many functions exceed a length threshold, and the longest offenders.

It is AST-based and operates on each function's ``lineno``..``end_lineno`` span.
Stdlib-only, no clock/random/network, byte-for-byte deterministic on the same
input. Fixture/example/test code is excluded (it carries deliberate flaws and is
throwaway), exactly as the project grade and seeding signals already exclude it.

The LOC-counting rule (documented and pinned by tests):

  For a function we count the **body** lines only — from the first body
  statement's start line through the last body statement's ``end_lineno``. The
  ``def`` line, decorators and the (possibly multi-line) signature are NOT
  counted: they are scaffolding, not work. From that body span we then EXCLUDE:

    * blank lines (only whitespace);
    * comment-only lines (first non-space character is ``#``);
    * every physical line of a leading **docstring** (a bare string expression
      that is the function's first body statement), across all its lines.

  What remains — non-blank, non-comment, non-docstring body lines — is the
  function's ``loc``. A function whose entire body is a docstring (``loc == 0``),
  or a ``def f(): ...`` one-liner, is handled safely.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import is_skipped, iter_source_files

__all__ = ["FunctionLength", "analyze_function_length"]

# How many of the longest functions to retain in ``longest``. Capped so a single
# signal never floods a report and output stays small/deterministic.
_LONGEST_CAP = 15

# Histogram buckets, low-inclusive / high-exclusive, plus an open-ended tail.
# Chosen to straddle the common review thresholds (a "screenful" ~ 20-30 lines,
# the 50-line default, and the genuinely-large 100+ tail).
_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-10", 0, 11),
    ("11-25", 11, 26),
    ("26-50", 26, 51),
    ("51-100", 51, 101),
    ("100+", 101, 1_000_000_000),
)


@dataclass
class FunctionLength:
    """Result of a function-length scan over a source tree.

    All fields are empty-safe (a tree with no analyzable functions yields zeros,
    an all-zero histogram and an empty ``longest``).
    """

    histogram: dict[str, int] = field(
        default_factory=lambda: {label: 0 for label, _lo, _hi in _BUCKETS}
    )
    over_threshold: int = 0
    threshold: int = 50
    total_functions: int = 0
    mean: float = 0.0
    median: float = 0.0
    max: int = 0
    longest: list[dict] = field(default_factory=list)


def _is_fixture_path(rel: str) -> bool:
    """True for example/fixture/test code, which is throwaway and excluded.

    Mirrors the predicate the project grade and seeding signals use, kept local
    to avoid an import cycle. ``rel`` is a root-relative POSIX-ish path string.
    """
    p = rel.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _docstring_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """Physical line numbers occupied by ``node``'s leading docstring, if any.

    A docstring is a bare string-constant expression that is the function's very
    first body statement; it may span several physical lines, all of which are
    returned so the LOC rule can subtract every one.
    """
    if not node.body:
        return set()
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        end = first.end_lineno if first.end_lineno is not None else first.lineno
        return set(range(first.lineno, end + 1))
    return set()


def _function_loc(
    node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]
) -> int:
    """Count body LOC for one function per the documented rule.

    ``lines`` is the 0-indexed list of physical source lines for the whole file.
    """
    if not node.body:
        return 0

    start = node.body[0].lineno
    # Last body statement's end is the true body end; ``end_lineno`` can be None
    # on very old ASTs, so fall back conservatively to the start line.
    last = node.body[-1]
    end = last.end_lineno if last.end_lineno is not None else last.lineno

    skip = _docstring_lines(node)
    count = 0
    for lineno in range(start, end + 1):
        if lineno in skip:
            continue
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            continue
        stripped = lines[idx].strip()
        if not stripped:
            continue  # blank line
        if stripped.startswith("#"):
            continue  # comment-only line
        count += 1
    return count


def _qualified_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """Build a ``Class.method`` / ``Outer.inner`` dotted name from parent links.

    Only enclosing ``ClassDef``/``FunctionDef`` names contribute, so module-level
    functions stay bare and methods are class-qualified — deterministic and stable
    regardless of walk order.
    """
    parts: list[str] = [node.name]  # type: ignore[attr-defined]
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(cur.name)
        cur = parents.get(cur)
    return ".".join(reversed(parts))


def _module_name(rel: Path) -> str:
    """Root-relative path → dotted module name (``app/x/y.py`` → ``app.x.y``)."""
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


def _median(values: list[int]) -> float:
    """Median of a non-empty sorted-able list; 0.0 for empty (empty-safe)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _relative_path(path: Path, root_path: Path) -> Path:
    """``path`` made relative to ``root_path``; ``path`` itself when unrelated."""
    try:
        return path.relative_to(root_path)
    except ValueError:
        return path


def _parse_source(path: Path) -> tuple[list[str], ast.Module] | None:
    """Read and parse ``path``; ``None`` if unreadable/unparsable (skipped)."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    return source.splitlines(), tree


def _parent_links(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    """Map each AST node to its parent, for deterministic qualified names."""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _file_entries(
    tree: ast.Module, file_lines: list[str], module: str
) -> list[dict]:
    """Body-LOC ``{module, function, loc}`` records for every function in ``tree``."""
    parents = _parent_links(tree)
    entries: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        entries.append(
            {
                "module": module,
                "function": _qualified_name(node, parents),
                "loc": _function_loc(node, file_lines),
            }
        )
    return entries


def _scan_root(root_path: Path, max_files: int) -> list[dict]:
    """Collect function records from every in-scope, non-fixture file under root."""
    entries: list[dict] = []
    scanned = 0
    for path in iter_source_files(root_path):
        if max_files and scanned >= max_files:
            break
        rel = _relative_path(path, root_path)
        if is_skipped(rel) or _is_fixture_path(rel.as_posix()):
            continue
        scanned += 1
        parsed = _parse_source(path)
        if parsed is None:
            continue
        file_lines, tree = parsed
        entries.extend(_file_entries(tree, file_lines, _module_name(rel)))
    return entries


def _aggregate(result: FunctionLength, entries: list[dict]) -> None:
    """Fill ``result`` in place from collected records (no-op when empty)."""
    locs = [e["loc"] for e in entries]
    result.total_functions = len(locs)
    result.max = max(locs)
    result.mean = round(sum(locs) / len(locs), 2)
    result.median = _median(locs)
    result.over_threshold = sum(1 for v in locs if v > result.threshold)
    for label, lo, hi in _BUCKETS:
        result.histogram[label] = sum(1 for v in locs if lo <= v < hi)
    entries.sort(key=lambda e: (-e["loc"], e["module"], e["function"]))
    result.longest = entries[:_LONGEST_CAP]


def analyze_function_length(
    root: str | Path, max_files: int = 500, threshold: int = 50
) -> FunctionLength:
    """Scan ``root`` and return a :class:`FunctionLength` of body-LOC per function.

    Walks every in-scope, non-fixture ``*.py`` file (excluded dirs and worktree
    copies pruned by :func:`iter_source_files`), capped at ``max_files`` after
    sorting so the cap is reproducible. For each function/method it computes body
    LOC via the documented rule, then aggregates: a bucketed ``histogram``, the
    count ``over_threshold`` (``loc > threshold``), ``mean``/``median``/``max``,
    and the ``longest`` functions (``{module, function, loc}``) sorted by
    ``(-loc, module, function)`` and capped at ~15.

    Pure and deterministic: no clock, randomness or network; unreadable or
    unparsable files are skipped silently. An empty or function-free tree yields a
    zero-filled, empty-safe result with the requested ``threshold`` recorded.
    """
    root_path = Path(root)
    result = FunctionLength(threshold=threshold)
    if not root_path.exists():
        return result

    entries = _scan_root(root_path, max_files)
    if not entries:
        return result

    _aggregate(result, entries)
    return result
