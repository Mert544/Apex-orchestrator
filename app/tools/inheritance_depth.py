"""Deterministic Depth-of-Inheritance-Tree (DIT) analyzer.

Across the project's own classes, build the class -> base graph, resolve base
names to project classes where possible, and compute each class's inheritance
depth (DIT) and number of declared base classes. Two maintainability smells are
flagged:

  - **deep chains**: ``depth >= max_depth`` (default 4) — long inheritance
    chains are hard to reason about and brittle to change;
  - **wide multiple inheritance**: ``len(bases) >= 3`` — many simultaneous
    bases complicate MRO and coupling.

Definitions
-----------
*Depth (DIT)* is the number of edges on the LONGEST path from a class up to a
root (a class with no resolvable project base). A class with no bases — or whose
bases are all external/stdlib/unknown — has depth ``0``. Each resolved project
base adds one level above it; depth is ``1 + max(depth(base) for resolved
bases)``.

Base resolution (and its limitation)
------------------------------------
Bases are resolved by SIMPLE NAME within the project: a base spelled ``B`` (or
``pkg.mod.B``, whose final attribute is taken) is matched to a project class
named ``B``. This is intentionally cross-module by class name and therefore:

  - ambiguous when two project modules define a same-named class — the first in
    deterministic (sorted) scan order wins;
  - unable to resolve aliased imports (``import B as C``) or dynamically built
    bases; such bases are treated as EXTERNAL, contributing no depth (they make
    the class a depth-1 leaf relative to them, i.e. add nothing).

Unknown / stdlib / unresolved bases simply stop the chain.

Cycle guard
-----------
Name-based resolution can manufacture cycles (e.g. ``A(B)`` and ``B(A)`` across
modules, or a class re-using an ancestor's name). Depth is computed with a
recursion stack: any class already on the current resolution path is skipped
(contributes no depth), so a cycle terminates instead of recursing forever.
Per-class memoization keeps the walk linear.

Purity
------
Deterministic, stdlib-only. No clock, no random, no network. Sorted file walk
via :func:`app.engine.skip_dirs.iter_source_files`; test/fixture files excluded.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["InheritanceDepth", "analyze_inheritance_depth"]

_DEEP_CAP = 15
_MULTI_BASE_THRESHOLD = 3


@dataclass
class InheritanceDepth:
    """Result of an inheritance-depth (DIT) scan over a project."""

    deep_classes: list[dict] = field(default_factory=list)
    multi_inheritance: list[dict] = field(default_factory=list)
    max_depth: int = 0
    mean_depth: float = 0.0
    class_count: int = 0


def _is_excluded(path: Path) -> bool:
    """True for test/fixture files, which should not skew project DIT."""
    name = path.name
    parts = path.parts
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    return any(p in ("tests", "test", "fixtures", "fixture") for p in parts)


def _base_name(node: ast.expr) -> str | None:
    """Final simple name of a base expression (``pkg.mod.B`` -> ``B``).

    Returns ``None`` for subscripts/calls and other non-name bases that cannot
    be resolved to a project class by name.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _module_name(path: Path, root: Path) -> str:
    """Path label relative to ``root`` (posix slashes preserved)."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return rel.as_posix()


def _collect_classes(root: Path, max_files: int) -> list[dict]:
    """Collect every project class as ``{module, classname, bases}``.

    Deterministic: files come pre-sorted from ``iter_source_files``; classes are
    yielded in source order within each file.
    """
    classes: list[dict] = []
    count = 0
    for path in iter_source_files(root, "*.py"):
        if max_files and count >= max_files:
            break
        if _is_excluded(path):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        count += 1
        module = _module_name(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [n for n in (_base_name(b) for b in node.bases) if n]
                classes.append({
                    "module": module,
                    "classname": node.name,
                    "bases": bases,
                })
    return classes


def _build_index(classes: list[dict]) -> dict[str, int]:
    """Map a class simple name to the index of the FIRST defining class.

    First-in-sorted-scan-order wins, making ambiguous names deterministic.
    """
    index: dict[str, int] = {}
    for i, cls in enumerate(classes):
        index.setdefault(cls["classname"], i)
    return index


def _depth_of(
    i: int,
    classes: list[dict],
    index: dict[str, int],
    memo: dict[int, int],
    stack: frozenset[int],
) -> int:
    """Longest resolved inheritance path above class ``i`` (in edges).

    ``stack`` holds classes on the current resolution path; any base resolving
    back onto it is a cycle and contributes no depth, guaranteeing termination.
    """
    if i in memo:
        return memo[i]
    best = 0
    cyclic = False
    next_stack = stack | {i}
    for base in classes[i]["bases"]:
        j = index.get(base)
        if j is None or j == i:
            # External / unresolved / direct self-reference: stops the chain.
            continue
        if j in next_stack:
            cyclic = True
            continue
        best = max(best, 1 + _depth_of(j, classes, index, memo, next_stack))
    # Only memoize when this class's depth was not curtailed by an in-progress
    # cycle frame, so the cached value is the true (cycle-free) depth.
    if not cyclic:
        memo[i] = best
    return best


def analyze_inheritance_depth(
    root, max_files: int = 500, max_depth: int = 4
) -> InheritanceDepth:
    """Compute per-class DIT over a project and flag maintainability smells.

    Parameters
    ----------
    root:
        Project root to scan (str or Path).
    max_files:
        Cap on parsed source files (deterministic sorted order). ``0`` = no cap.
    max_depth:
        Threshold at/above which a class's depth is reported as a deep chain.

    Returns an :class:`InheritanceDepth`. Empty-safe: a project with no classes
    yields empty lists and zeroed stats.
    """
    root_path = Path(root)
    classes = _collect_classes(root_path, max_files)
    if not classes:
        return InheritanceDepth()

    index = _build_index(classes)
    memo: dict[int, int] = {}
    empty: frozenset[int] = frozenset()

    depths = [_depth_of(i, classes, index, memo, empty) for i in range(len(classes))]

    deep_classes: list[dict] = []
    multi_inheritance: list[dict] = []
    for cls, depth in zip(classes, depths):
        record = {
            "module": cls["module"],
            "classname": cls["classname"],
            "depth": depth,
            "bases": list(cls["bases"]),
        }
        if depth >= max_depth:
            deep_classes.append(record)
        if len(cls["bases"]) >= _MULTI_BASE_THRESHOLD:
            multi_inheritance.append(dict(record))

    # Deterministic ordering: deepest first, then module/classname for ties.
    deep_classes.sort(key=lambda r: (-r["depth"], r["module"], r["classname"]))
    deep_classes = deep_classes[:_DEEP_CAP]
    multi_inheritance.sort(
        key=lambda r: (-len(r["bases"]), r["module"], r["classname"])
    )

    max_d = max(depths)
    mean_d = sum(depths) / len(depths)

    return InheritanceDepth(
        deep_classes=deep_classes,
        multi_inheritance=multi_inheritance,
        max_depth=max_d,
        mean_depth=round(mean_d, 4),
        class_count=len(classes),
    )
