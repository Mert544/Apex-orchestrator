"""Public-API wiring — populate a package's ``__init__.py`` re-export surface.

The boilerplate every student/team writes by hand: for a package whose
``__init__.py`` is empty (or missing exports), re-export every PUBLIC top-level
symbol from its sibling modules and pin a complete ``__all__``, so
``from pkg import X`` works without the caller reaching into ``pkg.module``.

This is the pure, deterministic engine behind the ``wire-exports`` develop
objective (:mod:`app.execution.objectives.wire_exports`). It only computes the
candidate ``__init__.py`` text and the names it would export — it never writes
and never runs anything. The objective's plan layer owns the apply (suite-gated,
auto-rolled-back) and the IMPORT ORACLE that proves every emitted name actually
resolves before the change is allowed to stand.

Determinism (the whole point): modules are scanned in SORTED relative-path order,
symbols are emitted sorted, ``__all__`` is sorted — same package, same
``__init__.py``, byte-for-byte. Name COLLISIONS across modules are resolved
honestly: the first module in sorted order wins; a colliding name from a later
module is SKIPPED, never guessed. A package already fully exported produces the
identical text (a byte-for-byte no-op). Stdlib-only, no LLM, no clock, no random.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import is_test_or_fixture_path

__all__ = [
    "WirePlan",
    "public_symbols_of_module",
    "collect_package_exports",
    "render_init_source",
    "rendered_all_names",
    "plan_init_text",
]

# Protocol / runtime dunders that may be top-level bindings in an existing
# ``__init__`` but must NEVER be folded into ``__all__`` — they are import
# machinery, not re-exportable attributes, and ``from pkg import *`` would fail
# trying to resolve them as names.
_PROTOCOL_DUNDERS = frozenset({
    "__getattr__",
    "__dir__",
    "__all__",
    "__path__",
    "__getattribute__",
    "__setattr__",
})


@dataclass
class WirePlan:
    """The result of analysing one package's export surface.

    ``exports`` maps each exported name to the dotted-relative module it comes
    from (e.g. ``{"Engine": "engine", "load": "io"}``), already collision-resolved
    (first sorted module wins). ``skipped`` records names dropped because an
    earlier module already claimed them — honest under-claim, surfaced for audit.
    ``init_source`` is the full candidate ``__init__.py`` text (``None`` when there
    is nothing to export). ``skipped_reason`` is set when the package is refused
    outright (a test/fixture package, an unreadable/unparseable ``__init__``)."""

    package_rel: str
    exports: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    init_source: str | None = None
    refused_reason: str | None = None


def _is_public(name: str) -> bool:
    """A name is part of the public surface when it does not start with ``_``.
    Dunders and single-underscore privates are both excluded."""
    return bool(name) and not name.startswith("_")


def _node_export_names(node: ast.stmt) -> list[str]:
    """Candidate export names a single top-level node defines, in source order.

    A pre-filter only: ``def``/``async def``/``class`` contribute their name;
    a plain assignment its ``Store`` targets; an annotated assignment WITH a value
    its target. ``_``-prefix / ``__all__`` / dedup filtering happens in the caller.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [
            t.id for t in node.targets
            if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)
        ]
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.value is not None:
            return [node.target.id]
    return []


def public_symbols_of_module(source: str) -> list[str]:
    """Public top-level symbols defined by one module's source, in source order.

    Collects top-level ``def`` / ``async def`` / ``class`` names and module-level
    assignment targets, skipping ``_``-prefixed names and ``__all__`` itself.
    Returns ``[]`` for source that does not parse — a syntactically broken module
    contributes nothing rather than blocking the whole package."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for node in tree.body:
        for name in _node_export_names(node):
            if name != "__all__" and _is_public(name) and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _existing_init_bindings(init_source: str) -> set[str]:
    """Names already imported / bound at the top level of an existing
    ``__init__.py`` — these are left to the human and never re-emitted.

    Includes ``import``/``from`` aliases as well as ``def``/``class`` definitions:
    a name the human already bound (however) must not be re-wired by us. This is
    the COLLISION/leave-alone set — distinct from the FOLD set (the names we add to
    ``__all__``), which excludes bare imports; see :func:`_existing_public_definitions`."""
    try:
        tree = ast.parse(init_source)
    except (SyntaxError, RecursionError, MemoryError):
        return set()
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
    return bound


def _existing_public_definitions(init_source: str) -> set[str]:
    """The existing ``__init__``'s OWN public surface — the names safe to fold into
    ``__all__``, EXCLUDING bare ``import``/``from`` aliases.

    A bare ``import os`` / ``from collections import OrderedDict`` is an
    implementation-detail dependency, not the package's public API; auto-folding it
    into ``__all__`` would make ``from pkg import *`` re-export ``os``/``sys`` and
    fool API/doc tooling into treating them as public (the names resolve, so the
    oracle passes — a semantic over-claim). The package's OWN public surface is:

    * top-level ``def`` / ``async def`` / ``class`` definitions,
    * top-level assignment targets (module-level constants/objects defined here),
    * names a human EXPLICITLY listed in a literal ``__all__`` (their deliberate
      choice — honored even if one happens to be an imported name like ``os``).

    ``_``-prefixed names and protocol dunders are excluded (the caller also drops
    ``_PROTOCOL_DUNDERS``). Returns ``set()`` for source that does not parse."""
    try:
        tree = ast.parse(init_source)
    except (SyntaxError, RecursionError, MemoryError):
        return set()
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_public(node.name):
                defined.add(node.name)
        else:
            for name in _node_export_names(node):
                if name != "__all__" and _is_public(name):
                    defined.add(name)
    # Honor an explicit human ``__all__`` verbatim — if they deliberately listed a
    # name (even an imported one), it is their declared public surface, keep it.
    explicit = _existing_all(init_source)
    if explicit is not None:
        defined.update(explicit)
    return defined


def _module_rels(package_dir: Path) -> list[str]:
    """The package's own non-``__init__`` module STEMS, sorted.

    Only direct ``*.py`` children are scanned (a package's immediate surface);
    sub-packages own their own ``__init__``. Sorted so collision resolution and
    emission are deterministic."""
    stems = [
        p.stem for p in package_dir.glob("*.py")
        if p.name != "__init__.py" and _is_public(p.stem)
    ]
    return sorted(stems)


def collect_package_exports(package_dir: str | Path, init_source: str) -> WirePlan:
    """Resolve the export surface for one package directory.

    Scans each sibling module in sorted order, collecting its public symbols; the
    FIRST module (sorted) to define a name wins, and the same name from a later
    module is recorded in ``skipped`` rather than guessed. Names already bound in
    the existing ``__init__`` are left untouched. Returns a :class:`WirePlan` whose
    ``exports`` is the resolved name → module map (module is the dotted-relative
    stem)."""
    pkg = Path(package_dir)
    plan = WirePlan(package_rel=pkg.name)
    already = _existing_init_bindings(init_source)

    for stem in _module_rels(pkg):
        try:
            text = (pkg / f"{stem}.py").read_text(encoding="utf-8")
        except OSError:
            continue
        for name in public_symbols_of_module(text):
            if name in already:
                continue  # the human already wired it — leave it
            if name in plan.exports:
                plan.skipped.append(name)  # a later module's collision — under-claim
                continue
            plan.exports[name] = stem
    return plan


def render_init_source(plan: WirePlan, existing_init: str) -> str | None:
    """Render the full candidate ``__init__.py`` text for a resolved plan.

    Emits sorted ``from .module import Name`` lines (grouped and sorted by module,
    then by name) followed by a sorted ``__all__``. When the existing ``__init__``
    already binds names, those bound names are folded into ``__all__`` too so the
    package's complete public surface is declared. Returns ``None`` when there is
    nothing to add (no new exports AND the existing init already declares
    ``__all__``) — the caller treats that as a no-op."""
    new_names = sorted(plan.exports)
    all_names = rendered_all_names(plan, existing_init)
    if not all_names:
        return None

    lines: list[str] = []
    header = existing_init.rstrip("\n")
    if header.strip():
        lines.append(header)
        lines.append("")

    # Group imports by module (sorted), names sorted within each module.
    by_module: dict[str, list[str]] = {}
    for name in new_names:
        by_module.setdefault(plan.exports[name], []).append(name)
    for module in sorted(by_module):
        names = ", ".join(sorted(by_module[module]))
        lines.append(f"from .{module} import {names}")

    if new_names:
        lines.append("")
    lines.append("__all__ = [")
    for name in all_names:
        lines.append(f'    "{name}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


def rendered_all_names(plan: WirePlan, existing_init: str) -> list[str]:
    """The exact sorted ``__all__`` :func:`render_init_source` would emit: the
    newly-wired exports UNION the existing ``__init__``'s OWN public surface.

    The fold set is the package's public surface ONLY — top-level ``def``/``class``
    definitions, module-level assignment targets, and any name a human explicitly
    listed in a literal ``__all__`` (see :func:`_existing_public_definitions`). A
    bare ``import os`` / ``from collections import OrderedDict`` is implementation
    detail, NOT public surface, and is NEVER auto-folded into ``__all__`` — doing so
    would make ``from pkg import *`` re-export ``os``/``sys`` and mislead API/doc
    tooling (the names resolve, so the oracle would pass — a semantic over-claim).
    Protocol dunders (``__getattr__``/``__dir__``/…) are excluded too — import
    machinery, not re-exportable attributes. The objective feeds THIS full list to
    the import oracle so a folded-in name that does not resolve is caught, never
    landed."""
    new_names = set(plan.exports)
    folded = {
        name for name in _existing_public_definitions(existing_init)
        if name not in _PROTOCOL_DUNDERS
    }
    return sorted(new_names | folded)


def _existing_all(init_source: str) -> list[str] | None:
    """The literal string list assigned to a top-level ``__all__``, or ``None``
    when the module declares no (literal) ``__all__``."""
    try:
        tree = ast.parse(init_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ) and isinstance(node.value, (ast.List, ast.Tuple)):
            names = [
                el.value for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            ]
            return names
    return None


def plan_init_text(
    project_root: str | Path, init_rel: str,
) -> tuple[str | None, WirePlan]:
    """Compute the candidate ``__init__.py`` text for the package at ``init_rel``.

    Returns ``(new_source, plan)``. ``new_source`` is ``None`` when the package is
    refused (a test/fixture package) or there is nothing to change (already fully
    exported → byte-identical, reported as ``None`` no-op). The returned text is
    re-``ast.parse``d here, so a caller that writes it is guaranteed valid syntax.
    """
    root = Path(project_root)
    rel = Path(init_rel)
    if rel.name != "__init__.py" or is_test_or_fixture_path(rel.parent):
        return None, WirePlan(package_rel=init_rel, refused_reason="not a wireable package")

    package_dir = root / rel.parent
    try:
        existing = (root / rel).read_text(encoding="utf-8")
    except OSError:
        existing = ""

    plan = collect_package_exports(package_dir, existing)
    candidate = render_init_source(plan, existing)
    plan.init_source = candidate
    if candidate is None or candidate == existing:
        return None, plan  # nothing to add — idempotent no-op

    # An already-complete __all__ that already names every export is a no-op even
    # if whitespace differs: do not churn a package that is functionally wired.
    existing_all = _existing_all(existing)
    if existing_all is not None and set(existing_all) >= set(plan.exports):
        return None, plan

    try:
        ast.parse(candidate)  # never hand the apply layer invalid syntax
    except SyntaxError:
        return None, plan
    return candidate, plan
