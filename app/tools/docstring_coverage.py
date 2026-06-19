"""Deterministic docstring-coverage analyzer, weighted by PUBLICNESS.

Documentation debt is not uniform: an undocumented public ``parse_config`` is a
real gap (callers depend on it), while an undocumented ``_helper`` is private
implementation detail. So this analyzer measures coverage over the PUBLIC API
surface only — public (non-underscore) modules, classes, and functions are the
denominator; private (``_``-prefixed) symbols are exempt and never penalize a
project's ratio.

What counts as a "public symbol":

  - a MODULE whose file stem does not start with ``_`` (``__init__.py`` is
    treated as the package's public surface and IS counted);
  - a top-level CLASS whose name does not start with ``_``;
  - a top-level or method FUNCTION whose name does not start with ``_``, EXCEPT
    that dunder methods (``__init__``, ``__repr__``, ...) are exempt — they are
    framework protocol, rarely docstringed, and would only add noise. A method
    is public only when its enclosing class is also public.

Coverage is ``documented_public / total_public``. Documentation is detected with
``ast.get_docstring`` (so a leading string literal in the right position counts,
nothing else). Pure and offline: no clock, no random, no network, no filesystem
writes; the same tree always yields the same :class:`DocstringCoverage`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["DocstringCoverage", "analyze_docstring_coverage"]

# How many undocumented-public entries to surface. Enough to act on, capped so a
# wholly-undocumented tree doesn't emit a thousand-line list.
_UNDOCUMENTED_CAP = 15


@dataclass
class DocstringCoverage:
    """Docstring coverage of a project's PUBLIC API surface.

    ``overall_public_ratio`` is ``documented_public / total_public`` in
    ``[0, 1]`` (a project with no public symbols is fully — vacuously —
    documented: ratio ``1.0``). ``undocumented_public`` lists the gaps as
    ``{"module", "symbol", "kind"}`` dicts (``kind`` is one of ``"module"``,
    ``"class"``, ``"function"``), sorted deterministically and capped at
    :data:`_UNDOCUMENTED_CAP`.
    """

    overall_public_ratio: float = 1.0
    documented_public: int = 0
    total_public: int = 0
    documented_modules: int = 0
    total_modules: int = 0
    documented_classes: int = 0
    total_classes: int = 0
    documented_functions: int = 0
    total_functions: int = 0
    undocumented_public: list[dict[str, str]] = field(default_factory=list)


def _is_fixture_path(rel: str) -> bool:
    """Test/example/fixture modules are excluded from the API surface — their
    docstring habits say nothing about the project's public-doc discipline."""
    p = rel.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/example/" in p
        or "/tests/" in p or "/test/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _is_public_name(name: str) -> bool:
    """A class/function name is public iff it does not start with ``_``.

    Dunders (``__x__``) also start with ``_`` and so are non-public here, which
    is what we want: ``__init__`` and friends are protocol, not documented API.
    """
    return not name.startswith("_")


def _is_public_module(stem: str) -> bool:
    """A module is public unless its file stem starts with ``_`` — with the one
    carve-out that ``__init__`` IS the package's public surface and counts."""
    if stem == "__init__":
        return True
    return not stem.startswith("_")


@dataclass
class _Counts:
    """Running tallies threaded through the per-file walk (kind -> documented/total)."""

    documented_modules: int = 0
    total_modules: int = 0
    documented_classes: int = 0
    total_classes: int = 0
    documented_functions: int = 0
    total_functions: int = 0


def _analyze_module(
    rel: str, tree: ast.Module, counts: _Counts, undocumented: list[dict[str, str]]
) -> None:
    """Tally one parsed module's public symbols into ``counts`` and record any
    undocumented ones in ``undocumented`` (unbounded here; capped by the caller)."""
    # The module itself.
    counts.total_modules += 1
    if ast.get_docstring(tree) is not None:
        counts.documented_modules += 1
    else:
        undocumented.append({"module": rel, "symbol": "<module>", "kind": "module"})

    # Top-level classes and their public methods, plus top-level functions.
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if not _is_public_name(node.name):
                continue
            counts.total_classes += 1
            if ast.get_docstring(node) is not None:
                counts.documented_classes += 1
            else:
                undocumented.append(
                    {"module": rel, "symbol": node.name, "kind": "class"}
                )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not _is_public_name(item.name):
                        continue
                    symbol = f"{node.name}.{item.name}"
                    counts.total_functions += 1
                    if ast.get_docstring(item) is not None:
                        counts.documented_functions += 1
                    else:
                        undocumented.append(
                            {"module": rel, "symbol": symbol, "kind": "function"}
                        )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_public_name(node.name):
                continue
            counts.total_functions += 1
            if ast.get_docstring(node) is not None:
                counts.documented_functions += 1
            else:
                undocumented.append(
                    {"module": rel, "symbol": node.name, "kind": "function"}
                )


def analyze_docstring_coverage(
    root: str | Path, max_files: int = 500
) -> DocstringCoverage:
    """Measure public-API docstring coverage under ``root``.

    Walks every non-excluded ``*.py`` file (skipping VCS/cache/worktree dirs via
    :func:`iter_source_files`, and test/example/fixture modules via
    :func:`_is_fixture_path`), tallying public modules, classes, and functions
    and whether each carries a docstring. At most ``max_files`` source files are
    read, applied AFTER filtering so the cap is deterministic and never filled
    with worktree copies. Returns a :class:`DocstringCoverage`; an empty or
    missing tree yields the vacuous ``1.0`` result.
    """
    root = Path(root)
    counts = _Counts()
    undocumented: list[dict[str, str]] = []

    if root.exists():
        scanned = 0
        for path in iter_source_files(root):
            if scanned >= max_files:
                break
            rel = str(path.relative_to(root))
            if _is_fixture_path(rel):
                continue
            if not _is_public_module(path.stem):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source)
            except (SyntaxError, OSError, ValueError, RecursionError, MemoryError):
                continue
            scanned += 1
            _analyze_module(rel, tree, counts, undocumented)

    documented_public = (
        counts.documented_modules
        + counts.documented_classes
        + counts.documented_functions
    )
    total_public = (
        counts.total_modules + counts.total_classes + counts.total_functions
    )
    ratio = 1.0 if total_public == 0 else documented_public / total_public

    # Deterministic ordering: module path, then kind, then symbol. Cap last so the
    # surfaced gaps are stable across machines regardless of walk order.
    undocumented.sort(key=lambda e: (e["module"], e["kind"], e["symbol"]))

    return DocstringCoverage(
        overall_public_ratio=ratio,
        documented_public=documented_public,
        total_public=total_public,
        documented_modules=counts.documented_modules,
        total_modules=counts.total_modules,
        documented_classes=counts.documented_classes,
        total_classes=counts.total_classes,
        documented_functions=counts.documented_functions,
        total_functions=counts.total_functions,
        undocumented_public=undocumented[:_UNDOCUMENTED_CAP],
    )
