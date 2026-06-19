"""Type-hint coverage — how much of a project's OWN code is type-annotated.

A deterministic, stdlib-only AST analyzer that walks a project's first-party
Python (excluding tests and fixtures) and asks, per function/method: is it
*fully* annotated? A function counts as annotated only when **every parameter
that needs a hint carries one AND the return type is declared**. From those
per-function verdicts it derives a per-module ratio and a project-level ratio,
and surfaces the worst-annotated modules so a brief can point at where types
are thinnest.

Annotation-completeness rules (documented here, applied in
:func:`_function_is_annotated`):

  - A function is *fully annotated* iff its return type is declared (``-> T``)
    AND every counted parameter has an annotation.
  - ``self`` / ``cls`` are NOT counted — the first positional parameter of a
    method is conventionally unannotated, so requiring a hint there would
    penalise idiomatic code. (Detected structurally: any method whose first
    positional param is literally named ``self`` or ``cls``.)
  - ``*args`` / ``**kwargs`` ARE counted: annotating them is meaningful
    (``*args: int``), so an un-annotated varargs leaves the function partial.
  - Keyword-only and positional-only params are counted like normal params.
  - ``@property`` getters and ``__init__`` are treated like any other method:
    ``__init__`` still needs ``-> None`` and its params hinted; a property
    getter still needs ``-> T``. We do NOT special-case dunders away — the
    only structural exception is the ``self``/``cls`` receiver above. This
    keeps the rule simple and the score honest.
  - A function with zero counted parameters is annotated iff it has a return
    hint (e.g. ``def f() -> None`` is fully annotated; ``def f()`` is not).

Test/fixture exclusion: files under a ``tests`` directory, named ``test_*.py``
/ ``*_test.py`` / ``conftest.py``, or living under a ``fixtures`` directory are
skipped — they are not the project's shipped surface and inflate/deflate the
score noisily. Directory-name skips (``.git``, ``.claude`` worktrees, …) come
from the canonical :func:`app.engine.skip_dirs.iter_source_files`.

Deterministic: same tree → same numbers. No clock, randomness, or network.
Unreadable/unparseable files are silently skipped (they contribute nothing).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import (
    is_test_or_fixture_name as _is_test_or_fixture,
)
from app.engine.skip_dirs import iter_source_files

__all__ = ["TypeHintCoverage", "analyze_type_hint_coverage"]

# How many worst-annotated modules to surface.
_WORST_CAP = 10


@dataclass
class TypeHintCoverage:
    """Project-level type-hint coverage report.

    ``overall_ratio`` is in [0, 1] — the fraction of counted functions that are
    fully annotated, project-wide. ``worst_modules`` lists the least-annotated
    modules (lowest ratio first), capped at ~10, each a dict of
    ``{module, ratio, annotated, total}``.
    """

    overall_ratio: float = 0.0
    annotated_functions: int = 0
    total_functions: int = 0
    worst_modules: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _receiver_skipped(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Number of leading positional params to ignore: 1 for a ``self``/``cls``
    receiver, else 0. Purely structural — we look at the first positional name,
    not at whether the function lexically sits in a class, so module-level
    functions are never mistaken for methods."""
    posonly = fn.args.posonlyargs
    positional = posonly + fn.args.args
    if positional and positional[0].arg in ("self", "cls"):
        return 1
    return 0


def _function_is_annotated(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Apply the completeness rules: every counted param hinted AND a return hint.

    See the module docstring for the exact rules (self/cls excluded; *args /
    **kwargs and kw-only / pos-only params counted; return always required)."""
    if fn.returns is None:
        return False

    skip = _receiver_skipped(fn)
    args = fn.args
    counted: list[ast.arg] = []
    # posonly + normal args, dropping the self/cls receiver if present.
    counted.extend((args.posonlyargs + args.args)[skip:])
    counted.extend(args.kwonlyargs)
    if args.vararg is not None:
        counted.append(args.vararg)
    if args.kwarg is not None:
        counted.append(args.kwarg)

    return all(arg.annotation is not None for arg in counted)


def _iter_functions(tree: ast.Module):
    """Yield every function/method node in a module, including nested defs.

    Nested functions are real definitions whose annotations matter, so they are
    counted too; this keeps the metric independent of how code is structured."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _module_counts(source: str) -> tuple[int, int]:
    """``(annotated, total)`` function counts for one module's source.

    Unparseable source yields ``(0, 0)`` — it simply contributes nothing rather
    than crashing the whole project scan."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return (0, 0)
    total = 0
    annotated = 0
    for fn in _iter_functions(tree):
        total += 1
        if _function_is_annotated(fn):
            annotated += 1
    return (annotated, total)


def analyze_type_hint_coverage(
    root: str | Path, max_files: int = 500
) -> TypeHintCoverage:
    """Measure type-hint coverage of a project's first-party Python under ``root``.

    Walks at most ``max_files`` non-test, non-fixture ``*.py`` files (after the
    canonical directory skips), computes per-module annotated/total counts, and
    returns a :class:`TypeHintCoverage`. Empty or degenerate projects (no files,
    no functions) return safe zero defaults — never a ``ZeroDivisionError``.

    Deterministic: ``iter_source_files`` yields a sorted, filtered list, the
    ``max_files`` cap is applied after filtering, and ``worst_modules`` is sorted
    by a total order (ratio asc, then total desc, then module path asc).
    """
    root = Path(root)
    if not root.exists():
        return TypeHintCoverage()

    project_annotated = 0
    project_total = 0
    per_module: list[dict[str, Any]] = []
    scanned = 0

    for path in iter_source_files(root):
        if scanned >= max_files:
            break
        rel = path.relative_to(root)
        if _is_test_or_fixture(rel):
            continue
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        annotated, total = _module_counts(source)
        if total == 0:
            # A module with no functions is neither well- nor badly-annotated;
            # it is excluded from both the ratio and the worst list.
            continue
        project_annotated += annotated
        project_total += total
        per_module.append(
            {
                "module": str(rel),
                "ratio": round(annotated / total, 4),
                "annotated": annotated,
                "total": total,
            }
        )

    overall = round(project_annotated / project_total, 4) if project_total else 0.0

    # Worst first: lowest ratio, then larger modules (more functions) break ties
    # so the biggest offender ranks above a tiny one at the same ratio, then the
    # module path for a fully deterministic total order.
    worst = sorted(
        per_module,
        key=lambda m: (m["ratio"], -m["total"], m["module"]),
    )[:_WORST_CAP]

    return TypeHintCoverage(
        overall_ratio=overall,
        annotated_functions=project_annotated,
        total_functions=project_total,
        worst_modules=worst,
    )
