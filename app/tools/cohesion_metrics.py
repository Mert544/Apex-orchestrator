"""Deterministic class-cohesion (LCOM-style) analyzer.

Low class cohesion is a maintainability smell: a class whose methods operate on
*disjoint* subsets of the instance attributes is really several classes glued
together and a candidate to be split. This module quantifies that smell with a
documented, deterministic LCOM variant and surfaces the worst offenders.

LCOM variant (exact definition)
-------------------------------
For one class we consider only its *cohesion-relevant* methods (see "What
counts" below). For each such method we collect the set of instance attributes
it touches — every ``self.<attr>`` *load or store* anywhere in the method body
(attribute reads, assignments, augmented assignments, and ``self.<attr>`` used
as a call target all count; the ``<attr>`` of a method call like
``self.helper()`` counts too, since methods are members).

Let ``M`` be the methods that touch at least one attribute and ``P`` be the set
of unordered method-pairs drawn from ``M`` (``|P| = |M|*(|M|-1)/2``). Let
``share`` be the number of pairs whose attribute sets intersect (share >= 1
attribute). The cohesion score is::

    cohesion = share / |P|            (the fraction of connected method-pairs)

This is the connectivity complement of the classic LCOM2/LCOM-pairs measure
(where LCOM counts *non-sharing* pairs): ``cohesion = 1 - LCOM_norm``. It lies
in [0, 1] by construction — 1.0 when every method-pair shares an attribute
(maximally cohesive), trending to 0.0 as the methods fragment into disjoint
attribute groups (a class that should be split).

Degenerate cases are defined explicitly and deterministically:

  - A class with fewer than 2 *cohesion-relevant* methods has an undefined
    pairwise score (``|P| == 0``) and is **skipped** entirely.
  - Methods that touch **no** instance attribute are dropped from ``M`` before
    forming pairs (they carry no cohesion signal); if dropping them leaves
    fewer than 2 methods, the class is skipped.

What counts as a cohesion-relevant method
-----------------------------------------
  - Regular and ``async`` methods defined directly in the class body.
  - ``@property`` and ``@<name>.setter`` accessors are included (they are part
    of the class's behaviour over its state).
  - ``@staticmethod`` and ``@classmethod`` are **excluded**: they have no
    ``self`` and so cannot contribute to instance-attribute cohesion.
  - Dunder methods (``__init__``, ``__eq__``, ...) are **excluded**: ``__init__``
    typically touches *every* attribute and would inflate cohesion, and other
    dunders are protocol glue rather than domain behaviour.

The analysis is pure, deterministic, and stdlib-only: it parses files with
``ast``, never reads the clock, never calls ``random``, and never touches the
network. Test/fixture files and excluded directories are filtered out via
:func:`app.engine.skip_dirs.iter_source_files`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["ClassCohesion", "CohesionMetrics", "analyze_cohesion"]

# How many low-cohesion classes to report at most (worst-first).
_MAX_REPORTED = 15


@dataclass(frozen=True)
class ClassCohesion:
    """One low-cohesion class flagged by the analyzer."""

    module: str
    classname: str
    methods: int
    cohesion: float


@dataclass(frozen=True)
class CohesionMetrics:
    """Result of :func:`analyze_cohesion`.

    ``low_cohesion`` is sorted ascending by ``cohesion`` (worst first), with ties
    broken deterministically by ``(module, classname)``, and capped at
    :data:`_MAX_REPORTED` entries. The counts describe the whole scan.
    """

    low_cohesion: list[ClassCohesion] = field(default_factory=list)
    files_analyzed: int = 0
    classes_analyzed: int = 0
    classes_skipped: int = 0


def _is_test_file(path: Path) -> bool:
    """True for test/fixture files, which we never grade."""
    name = path.name
    parts = path.parts
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "tests" in parts
        or "fixtures" in parts
    )


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the bare decorator names applied to ``node`` (best effort)."""
    names: set[str] = set()
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            # e.g. ``@x.setter`` -> "setter"
            names.add(target.attr)
    return names


def _self_param(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Name of the first positional parameter (the ``self`` receiver), or None."""
    if node.args.posonlyargs:
        return node.args.posonlyargs[0].arg
    if node.args.args:
        return node.args.args[0].arg
    return None


def _touched_attributes(
    node: ast.FunctionDef | ast.AsyncFunctionDef, self_name: str
) -> frozenset[str]:
    """Instance attributes ``self.<attr>`` referenced anywhere in ``node``.

    Counts every ``ast.Attribute`` whose value is the receiver ``Name`` — loads,
    stores, augmented assignments, and call targets all reduce to an
    ``ast.Attribute`` node, so a single walk captures them uniformly.
    """
    attrs: set[str] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == self_name
        ):
            attrs.add(sub.attr)
    return frozenset(attrs)


def _relevant_methods(
    cls: ast.ClassDef,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Cohesion-relevant methods of ``cls`` (see module docstring)."""
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for item in cls.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_dunder(item.name):
            continue
        decs = _decorator_names(item)
        if "staticmethod" in decs or "classmethod" in decs:
            continue
        methods.append(item)
    return methods


def _class_cohesion(cls: ast.ClassDef) -> float | None:
    """Cohesion score in [0, 1] for ``cls``, or None if undefined (skip)."""
    method_attr_sets: list[frozenset[str]] = []
    for method in _relevant_methods(cls):
        self_name = _self_param(method)
        if self_name is None:
            continue
        touched = _touched_attributes(method, self_name)
        if touched:  # drop methods that carry no attribute signal
            method_attr_sets.append(touched)

    if len(method_attr_sets) < 2:
        return None

    pairs = list(combinations(method_attr_sets, 2))
    share = sum(1 for a, b in pairs if a & b)
    return share / len(pairs)


def _module_name_from_path(path: Path) -> str:
    """Best-effort dotted module name (``app``-anchored when possible)."""
    parts = path.parts
    try:
        idx = parts.index("app")
        rel = parts[idx:]
    except ValueError:
        rel = parts[-2:] if len(parts) >= 2 else parts
    dotted = ".".join(rel)
    return dotted[:-3] if dotted.endswith(".py") else dotted


def analyze_cohesion(root: str | Path, max_files: int = 500) -> CohesionMetrics:
    """Scan ``root`` and report the lowest-cohesion classes.

    Walks every non-excluded, non-test ``.py`` file under ``root`` (capped at
    ``max_files`` for bounded work), computes the LCOM-variant cohesion of each
    class with >= 2 cohesion-relevant attribute-touching methods, and returns the
    worst offenders sorted ascending by cohesion. Pure and deterministic:
    identical inputs yield identical output. Empty/missing roots are safe.
    """
    root = Path(root)
    flagged: list[ClassCohesion] = []
    files_analyzed = 0
    classes_analyzed = 0
    classes_skipped = 0

    files = [f for f in iter_source_files(root) if not _is_test_file(f)]
    if max_files > 0:
        files = files[:max_files]

    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        files_analyzed += 1
        module = _module_name_from_path(path)

        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            cohesion = _class_cohesion(cls)
            if cohesion is None:
                classes_skipped += 1
                continue
            classes_analyzed += 1
            # Report method count consistent with the score's denominator.
            attr_methods = sum(
                1
                for m in _relevant_methods(cls)
                if (sn := _self_param(m)) is not None and _touched_attributes(m, sn)
            )
            flagged.append(
                ClassCohesion(
                    module=module,
                    classname=cls.name,
                    methods=attr_methods,
                    cohesion=round(cohesion, 4),
                )
            )

    # Worst (lowest cohesion) first; deterministic tie-break by identity.
    flagged.sort(key=lambda c: (c.cohesion, c.module, c.classname))

    return CohesionMetrics(
        low_cohesion=flagged[:_MAX_REPORTED],
        files_analyzed=files_analyzed,
        classes_analyzed=classes_analyzed,
        classes_skipped=classes_skipped,
    )
