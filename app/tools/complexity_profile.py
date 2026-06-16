"""Cyclomatic-complexity DISTRIBUTION across a project's own functions.

Where ``code_metrics.function_complexities`` answers "how complex is *this*
function" and ``cognitive_complexity`` answers "how hard is it to *read*", this
module answers a portfolio question: across every function in the tree, **how is
complexity spread**? A codebase with one 40-branch monster and a thousand flat
helpers is a different maintenance proposition from one where everything sits at
12 — and a single mean hides that. So we report the full shape: a bucketed
histogram, how many functions cross a configurable threshold, the
mean/median/max, and the named worst offenders (hotspots).

McCabe cyclomatic complexity, self-contained
--------------------------------------------
The standard McCabe number is ``decision_points + 1`` per function — one path
through a flat function, one extra independent path per branch. We count a
decision point for each of the following AST nodes inside the function body
(nested ``def``/``lambda`` bodies are EXCLUDED — they get their own entry):

  - ``If``                  — each ``if``/``elif`` (an ``elif`` is a nested
                              ``If`` in the AST, so it is counted naturally);
                              a plain ``else`` adds nothing.
  - ``IfExp``               — a ternary ``a if c else b``.
  - ``For`` / ``AsyncFor``  — loop header.
  - ``While``               — loop header.
  - ``ExceptHandler``       — each ``except`` clause (a ``try`` with three
                              excepts = three decision points; the ``try``/
                              ``else``/``finally`` themselves add nothing).
  - ``With`` / ``AsyncWith``— each context manager *item* (``with a, b:`` is two
                              decision points — two acquisitions that can fail).
  - ``BoolOp``              — each additional operand of an ``and``/``or`` chain:
                              ``a and b`` adds 1, ``a and b and c`` adds 2
                              (``len(values) - 1`` short-circuit branches).
  - ``comprehension``       — each ``for`` clause of a comprehension/generator,
                              PLUS each ``if`` filter on it (``[x for x in xs if
                              p if q]`` adds 1 + 2 = 3).
  - ``assert``              — an ``assert`` is an implicit ``if not …: raise``.

We deliberately do NOT count ``match``/``case``, ``try``/``finally``, or
boolean ``not`` — keeping the rule set small, defensible, and identical to the
"+1 per short-circuit, +1 per loop/branch/except/with-item/assert" convention
documented above. The function's own complexity is ``1 + sum(decision points)``,
so a flat function is exactly ``1``.

Deterministic, stdlib-only (``ast`` + sorted file walk), empty-safe, pure: no
clock, no randomness, no network. Same tree -> same profile.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import iter_source_files
from app.engine.skip_dirs import module_dotted_name as _module_name

__all__ = [
    "ComplexityProfile",
    "analyze_complexity",
    "cyclomatic_complexity",
    "function_cyclomatic_complexities",
]

# Bucket edges for the histogram. Each label maps to an inclusive range; the
# last bucket is open-ended. Insertion order here is the report order.
_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("1-5", 1, 5),
    ("6-10", 6, 10),
    ("11-15", 11, 15),
    ("16-20", 16, 20),
    ("21+", 21, 10**9),
)

# Cap on the number of hotspots reported, so a huge tree's output stays bounded.
_HOTSPOT_CAP = 15


def _decision_points(node: ast.AST) -> int:
    """Decision points contributed by a single AST node (0 for most nodes).

    The per-node weights documented in the module docstring. Crucially this is a
    *node-local* count: chained boolean operators and multi-item ``with``/
    comprehensions contribute more than one, which a naive ``isinstance`` walk
    would miss.
    """
    if isinstance(node, ast.BoolOp):
        # `a and b` => 1 branch, `a and b and c` => 2 (len(values) - 1).
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        # The `for` clause itself, plus each `if` filter attached to it.
        return 1 + len(node.ifs)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        # Each context manager item is an acquisition that can branch.
        return len(node.items)
    if isinstance(
        node,
        (
            ast.If,
            ast.IfExp,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.ExceptHandler,
            ast.Assert,
        ),
    ):
        return 1
    return 0


def cyclomatic_complexity(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """McCabe cyclomatic complexity of ONE function-definition node.

    ``1 + sum of decision points`` over the function body, EXCLUDING the bodies
    of nested ``def``/``async def``/``lambda`` (each is reported as its own
    function). A flat function with no branches returns ``1``.
    """
    complexity = 1
    for child in fn.body:
        # A nested ``def``/``async def`` at statement level owns its own
        # complexity (reported separately), so it must not leak branches into
        # the enclosing function — skip it just like a nested child below.
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        complexity += _walk_decision_points(child)
    return complexity


def _walk_decision_points(node: ast.AST) -> int:
    """Sum decision points in ``node`` and its descendants, but do NOT descend
    into nested function/lambda bodies (they own their own complexity)."""
    total = _decision_points(node)
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        total += _walk_decision_points(child)
    return total


def function_cyclomatic_complexities(source: str) -> list[tuple[str, int, int]]:
    """``(qualified_name, lineno, complexity)`` for every function in ``source``.

    Methods are qualified ``Class.method``; nested defs extend the chain
    (``outer.inner``). Unparsable source yields ``[]`` — empty-safe by design.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return _function_cyclomatic_complexities_tree(tree)


def _function_cyclomatic_complexities_tree(tree: ast.Module) -> list[tuple[str, int, int]]:
    """Core walk shared by the source- and tree-based entry points."""
    out: list[tuple[str, int, int]] = []

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{node.name}"
                out.append((name, node.lineno, cyclomatic_complexity(node)))
                walk(node.body, f"{name}.")
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.")

    walk(tree.body, "")
    return out


@dataclass
class ComplexityProfile:
    """The cyclomatic-complexity distribution across a project's functions.

    Empty-safe: a tree with no readable functions yields a zeroed profile
    (every histogram bucket ``0``, ``total == 0``, ``mean == median == 0.0``,
    ``max == 0``, no hotspots).
    """

    total: int                                          # functions measured
    histogram: dict[str, int]                           # bucket label -> count
    over_threshold: int                                 # complexity > threshold
    threshold: int                                      # the threshold used
    mean: float                                         # mean complexity
    median: float                                       # median complexity
    max: int                                            # worst single function
    hotspots: list[dict[str, Any]] = field(default_factory=list)
    files_scanned: int = 0                              # source files parsed

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "histogram": dict(self.histogram),
            "over_threshold": self.over_threshold,
            "threshold": self.threshold,
            "mean": self.mean,
            "median": self.median,
            "max": self.max,
            "hotspots": [dict(h) for h in self.hotspots],
            "files_scanned": self.files_scanned,
        }


def _empty_histogram() -> dict[str, int]:
    return {label: 0 for label, _lo, _hi in _BUCKETS}


def _bucket_for(complexity: int) -> str:
    """The histogram bucket label a complexity falls into (clamped at 1)."""
    value = max(complexity, 1)
    for label, lo, hi in _BUCKETS:
        if lo <= value <= hi:
            return label
    return _BUCKETS[-1][0]  # unreachable: last bucket is open-ended


def _median(values: list[int]) -> float:
    """Median of a NON-empty sorted-or-unsorted list; 0.0 for empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def analyze_complexity(
    root: str | Path,
    max_files: int = 500,
    threshold: int = 12,
) -> ComplexityProfile:
    """Compute the cyclomatic-complexity distribution under ``root``.

    Walks ``root`` for ``*.py`` (skipping the canonical excluded dirs via
    :func:`iter_source_files`, so agent worktrees/venvs never inflate the count),
    measures every function with the McCabe rule documented at module top, and
    summarizes the spread.

    ``max_files`` caps how many source files are parsed (deterministic: the file
    list is sorted, so the cap is reproducible). ``threshold`` (default ``12``)
    is the line above which a function counts toward ``over_threshold`` — strictly
    greater than, so ``threshold`` itself is considered acceptable.

    Returns a :class:`ComplexityProfile`. An empty / function-free tree yields a
    zeroed, safe profile rather than raising.
    """
    root = Path(root)
    files = list(iter_source_files(root))
    if max_files and max_files > 0:
        files = files[:max_files]

    complexities: list[int] = []
    histogram = _empty_histogram()
    records: list[tuple[int, str, str]] = []  # (complexity, module, function)
    files_scanned = 0

    from app.tools.python_structure import parse_cached

    for path in files:
        try:
            # Read solely to reproduce the original ``files_scanned`` semantics
            # (a file counts as scanned iff it is READABLE, even if it later
            # fails to parse or holds no functions). The expensive ``ast.parse``
            # is served from the shared per-build cache below, not redone here.
            path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1
        tree = parse_cached(path)
        if tree is None:
            # Unparseable (or, racing, now-unreadable): no functions, exactly the
            # ``function_cyclomatic_complexities`` SyntaxError -> [] branch.
            continue
        funcs = _function_cyclomatic_complexities_tree(tree)
        if not funcs:
            continue
        module = _module_name(path, root)
        for name, _lineno, complexity in funcs:
            complexities.append(complexity)
            histogram[_bucket_for(complexity)] += 1
            records.append((complexity, module, name))

    total = len(complexities)
    if total == 0:
        return ComplexityProfile(
            total=0,
            histogram=histogram,
            over_threshold=0,
            threshold=threshold,
            mean=0.0,
            median=0.0,
            max=0,
            hotspots=[],
            files_scanned=files_scanned,
        )

    over_threshold = sum(1 for c in complexities if c > threshold)
    mean = round(sum(complexities) / total, 2)
    median = _median(complexities)
    max_complexity = max(complexities)

    # Worst first; ties broken by module then function name for a stable order.
    records.sort(key=lambda r: (-r[0], r[1], r[2]))
    hotspots = [
        {"module": module, "function": function, "complexity": complexity}
        for complexity, module, function in records[:_HOTSPOT_CAP]
    ]

    return ComplexityProfile(
        total=total,
        histogram=histogram,
        over_threshold=over_threshold,
        threshold=threshold,
        mean=mean,
        median=median,
        max=max_complexity,
        hotspots=hotspots,
        files_scanned=files_scanned,
    )
