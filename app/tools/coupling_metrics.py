"""Deterministic per-module COUPLING analyzer (classic Ca / Ce / Instability).

For every internal Python module under ``root`` this computes the three textbook
package-coupling metrics:

  - **Afferent coupling (Ca)** — how many *other* internal modules import this
    one (incoming dependencies; a high Ca means many things rely on you).
  - **Efferent coupling (Ce)** — how many *other* internal modules this one
    imports (outgoing dependencies; a high Ce means you rely on many things).
  - **Instability (I)** — ``Ce / (Ca + Ce)`` clamped to ``[0, 1]``. ``I == 0`` is
    maximally STABLE (everyone depends on it, it depends on no one); ``I == 1`` is
    maximally UNSTABLE (it depends on others, no one depends on it). When a module
    has no internal coupling at all (``Ca + Ce == 0``) we define ``I = 0`` — there
    is no division and an isolated leaf is treated as stable, not unstable.

Import-resolution rule (how an ``import`` becomes an internal module path)
-------------------------------------------------------------------------
We first build a *module map* from every non-skipped ``*.py`` file on disk: the
file's ``root``-relative path with the ``.py`` suffix dropped and the separators
turned into dots becomes its dotted module name (a ``__init__.py`` maps to its
package, i.e. the trailing ``__init__`` segment is removed). Then, parsing each
file's AST:

  - ``import a.b.c`` and ``import a.b.c as x`` contribute the dotted name
    ``a.b.c``;
  - ``from a.b import name`` contributes the module ``a.b``; for relative
    imports (``from . import x`` / ``from ..pkg import y``) we resolve the leading
    dots against the importing file's own package before joining.

Each candidate dotted name is matched against the module map by longest-prefix:
``a.b.c`` is tried, then ``a.b``, then ``a`` — the first that is a known internal
module wins; anything that resolves to nothing is stdlib/third-party and ignored.
A ``from pkg import sub`` where ``pkg.sub`` is itself an internal module is also
credited to ``pkg.sub`` (sub-module imports), then falling back to ``pkg``.
Self-edges are dropped, and each ordered (source, target) pair counts once.

Pure, deterministic (sorted walk, no clock/random/network), stdlib-only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = [
    "ModuleCoupling",
    "CouplingMetrics",
    "analyze_coupling",
]

_HIGHLIGHT_CAP = 15


@dataclass(frozen=True)
class ModuleCoupling:
    """Coupling metrics for a single internal module."""

    module: str
    ca: int
    ce: int
    instability: float


@dataclass
class CouplingMetrics:
    """Whole-project coupling report.

    ``modules`` is the full per-module list, sorted deterministically (most
    unstable first, then by descending fan, then module name). ``most_unstable``
    and ``most_stable`` are coupling-bearing highlights (``Ca + Ce > 0``), each
    capped at ~15 entries.
    """

    modules: list[ModuleCoupling] = field(default_factory=list)
    most_unstable: list[ModuleCoupling] = field(default_factory=list)
    most_stable: list[ModuleCoupling] = field(default_factory=list)

    @property
    def module_count(self) -> int:
        return len(self.modules)


def _module_name_for(rel: Path) -> str:
    """Dotted internal module name for a ``root``-relative ``*.py`` path."""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_module_map(root: Path, max_files: int) -> dict[str, Path]:
    """Map every internal dotted module name -> its ``root``-relative path."""
    mapping: dict[str, Path] = {}
    for path in iter_source_files(root)[:max_files]:
        rel = path.relative_to(root)
        name = _module_name_for(rel)
        if name:
            mapping[name] = rel
    return mapping


def _resolve(candidate: str, module_map: dict[str, Path]) -> str | None:
    """Longest-prefix match of a dotted name against known internal modules."""
    parts = candidate.split(".")
    while parts:
        name = ".".join(parts)
        if name in module_map:
            return name
        parts.pop()
    return None


def _resolve_group(group: list[str], module_map: dict[str, Path]) -> str | None:
    """First internal module a prioritized candidate list resolves to.

    Candidates are tried in order (most specific first); each is itself matched
    by longest prefix, so unknown trailing attributes still fall back correctly.
    """
    for candidate in group:
        target = _resolve(candidate, module_map)
        if target is not None:
            return target
    return None


def _relative_base(level: int, module: str | None, self_module: str) -> str:
    """Resolve a relative ``from`` import's base dotted name.

    Climbs ``level`` packages up from ``self_module``'s own package, then joins
    the explicit ``module`` (if any). Returns ``""`` when nothing resolves.
    """
    pkg_parts = self_module.split(".")[:-1] if self_module else []
    climb = level - 1
    if climb:
        pkg_parts = pkg_parts[:-climb] if climb <= len(pkg_parts) else []
    prefix = ".".join(pkg_parts)
    return f"{prefix}.{module}" if module else prefix


def _import_groups(node: ast.Import) -> list[list[str]]:
    """Candidate lists for a plain ``import a.b.c`` statement."""
    return [[alias.name] for alias in node.names if alias.name]


def _from_groups(node: ast.ImportFrom, self_module: str) -> list[list[str]]:
    """Candidate lists for a ``from base import name`` statement.

    Prefers the ``base.name`` sub-module over the ``base`` package, so importing
    a sub-module does not also inflate the package's afferent fan-in. Relative
    imports are resolved against ``self_module``'s package first.
    """
    if node.level:
        base = _relative_base(node.level, node.module, self_module)
    else:
        base = node.module or ""
    if not base:
        return []
    groups: list[list[str]] = []
    for alias in node.names:
        if alias.name and alias.name != "*":
            groups.append([f"{base}.{alias.name}", base])
        else:
            groups.append([base])
    return groups


def _candidate_groups(tree: ast.AST, self_module: str) -> list[list[str]]:
    """Per-import-statement prioritized candidate lists.

    Each list is ordered most-specific-first; resolution takes the first entry
    that is a known internal module, so a single import contributes at most one
    edge. For ``from pkg import sub`` the ``pkg.sub`` sub-module is preferred over
    the ``pkg`` package, so importing a sub-module does not also inflate the
    package's afferent fan-in. Relative imports are resolved against
    ``self_module``'s package first.
    """
    groups: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            groups.extend(_import_groups(node))
        elif isinstance(node, ast.ImportFrom):
            groups.extend(_from_groups(node, self_module))
    return groups


def analyze_coupling(root: str | Path, max_files: int = 500) -> CouplingMetrics:
    """Compute Ca / Ce / Instability for every internal module under ``root``.

    Walks at most ``max_files`` non-skipped ``*.py`` files (deterministic order),
    builds the internal import graph from each file's AST, then derives the
    classic coupling metrics. Empty-safe and side-effect free.
    """
    root = Path(root)
    module_map = _build_module_map(root, max_files)
    if not module_map:
        return CouplingMetrics()

    # Edges: source module -> set of internal target modules it imports.
    efferent: dict[str, set[str]] = {name: set() for name in module_map}
    afferent: dict[str, set[str]] = {name: set() for name in module_map}

    for source, rel in module_map.items():
        try:
            text = (root / rel).read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            # Unreadable / unparseable file contributes no edges but stays a node.
            continue
        for group in _candidate_groups(tree, source):
            target = _resolve_group(group, module_map)
            if target is None or target == source:
                continue
            efferent[source].add(target)
            afferent[target].add(source)

    modules = [
        _make_metric(name, len(afferent[name]), len(efferent[name]))
        for name in module_map
    ]
    modules.sort(key=_sort_key)

    coupled = [m for m in modules if (m.ca + m.ce) > 0]
    most_unstable = sorted(coupled, key=_sort_key)[:_HIGHLIGHT_CAP]
    most_stable = sorted(coupled, key=_stable_key)[:_HIGHLIGHT_CAP]

    return CouplingMetrics(
        modules=modules,
        most_unstable=most_unstable,
        most_stable=most_stable,
    )


def _make_metric(module: str, ca: int, ce: int) -> ModuleCoupling:
    total = ca + ce
    instability = 0.0 if total == 0 else ce / total
    return ModuleCoupling(module=module, ca=ca, ce=ce, instability=instability)


def _sort_key(m: ModuleCoupling) -> tuple[float, int, int, str]:
    # Most unstable first, then biggest fan (Ce then Ca), then module name asc.
    return (-m.instability, -m.ce, -m.ca, m.module)


def _stable_key(m: ModuleCoupling) -> tuple[float, int, int, str]:
    # Most stable first: lowest instability, then biggest afferent fan-in.
    return (m.instability, -m.ca, -m.ce, m.module)
