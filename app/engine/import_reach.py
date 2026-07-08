"""Project-internal import reachability — which imports really execute a module.

Impact scoping used to match a test to a changed module only by the module's
own dotted path and its parent packages. Two real import shapes slip through
that net, and both were caught on a real external validation run (`packaging`):

* a test importing a SUBMODULE of a changed package executes that package's
  ``__init__`` (``import pkg.sub._x`` runs ``pkg/sub/__init__.py``), and
* a test importing ``pkg.api`` executes everything ``api`` itself imports,
  transitively (``api`` does ``from pkg._impl import f``).

Missing either means a broken change can be stamped "verified" — the one thing
Apex must never do. This module closes the CLASS, not the instance: it builds
the project's own import graph (absolute and relative imports, plus the
implicit execute-your-ancestor-``__init__`` edges) and answers, for a changed
module, every import name whose import would execute it.

Deterministic, stdlib-only. Errors degrade safely in the honest direction: a
module that fails to parse contributes no graph edges, so matching falls back
to being no worse than the old prefix rule (scope can only ever WIDEN vs. the
pre-fix behavior, never narrow). The graph is cached per project root on a
(path, mtime, size) fingerprint, so a develop session pays the parse cost once
per tree state, not once per changed file.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS as _SKIP_DIRS
from app.engine.source_roots import source_roots as _source_roots

__all__ = ["reaching_import_names"]

# root-path -> (stat fingerprint, import-name index, reverse import graph)
_CACHE: dict[str, tuple[tuple, dict[str, str], dict[str, set[str]]]] = {}
_CACHE_MAX = 4


def reaching_import_names(project_root: Path | str,
                          module_rel: str) -> tuple[set[str], tuple[str, ...]]:
    """Every import name whose import executes ``module_rel``.

    Returns ``(exact, package_prefixes)``:

    * ``exact`` — the dotted import names (raw and source-root-stripped) of
      ``module_rel`` itself and of every project module that reaches it
      through the import graph — a direct importer, a transitive importer, or
      a submodule whose import executes an ancestor ``__init__`` on the way;
    * ``package_prefixes`` — for each of those that is a package ``__init__``,
      its dotted name plus a trailing dot: an import of ANYTHING under that
      prefix (including names the graph cannot see, e.g. a compiled extension
      module) executes the package ``__init__`` and therefore the change.

    Both are computed from the cached project import graph; the result is
    deterministic for a given tree state.
    """
    root = Path(project_root)
    index, importers = _index_and_importers(root)
    exact: set[str] = set()
    prefixes: set[str] = set()
    for rel in _reverse_reachable(importers, Path(module_rel).as_posix()):
        names = _import_names_of(rel, _root_prefixes(root))
        exact.update(names)
        if rel.endswith("__init__.py"):
            prefixes.update(f"{name}." for name in names)
    return exact, tuple(sorted(prefixes))


def _reverse_reachable(importers: dict[str, set[str]], start: str) -> set[str]:
    """``start`` plus every module that (transitively) imports it — a plain
    BFS over the reverse import graph; cycles terminate via the seen-set."""
    seen = {start}
    frontier = [start]
    while frontier:
        for rel in importers.get(frontier.pop(), ()):
            if rel not in seen:
                seen.add(rel)
                frontier.append(rel)
    return seen


def _index_and_importers(root: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    """The (import-name -> rel-path index, reverse import graph) pair for the
    project's own non-test modules, cached on a stat fingerprint of those files
    so an unchanged tree never pays the parse cost twice."""
    files = _project_files(root)
    key = str(root.resolve())
    fingerprint = tuple(files)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == fingerprint:
        return hit[1], hit[2]
    index, importers = _build_graph(root, [rel for rel, _, _ in files])
    if key not in _CACHE and len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (fingerprint, index, importers)
    return index, importers


def _project_files(root: Path) -> list[tuple[str, int, int]]:
    """(rel-path, mtime_ns, size) for every project module the graph covers —
    sorted, skipping cache/vcs dirs and test files (tests are the QUERY side of
    covering-scope, not nodes of the shippable-module graph)."""
    out: list[tuple[str, int, int]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if _is_test_path(rel):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((rel, st.st_mtime_ns, st.st_size))
    return out


def _is_test_path(rel: str) -> bool:
    """Same convention as covering-scope's test discovery: under ``tests/`` or
    named ``test_*.py``."""
    p = Path(rel)
    return "tests" in p.parts or p.name.startswith("test_")


def _build_graph(root: Path,
                 rels: list[str]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Index every module under each import name it answers to, then record the
    reverse edges: for each module, who executes it when imported."""
    prefixes = _root_prefixes(root)
    index: dict[str, str] = {}
    names_of: dict[str, list[str]] = {}
    for rel in rels:
        names_of[rel] = _import_names_of(rel, prefixes)
        for name in names_of[rel]:
            index.setdefault(name, rel)
    importers: dict[str, set[str]] = {}
    for rel in rels:
        _add_edges(root, rel, names_of[rel], index, importers)
    return index, importers


def _root_prefixes(root: Path) -> tuple[str, ...]:
    """The strippable source-root path prefixes (``src/``, pyproject-declared),
    each with a trailing slash, ready for ``startswith``."""
    return tuple(f"{r}/" for r in _source_roots(root))


def _import_names_of(rel: str, root_prefixes: tuple[str, ...]) -> list[str]:
    """The import name(s) a project file answers to: its raw dotted path, plus
    the source-root-stripped dotted path on a ``src/`` (or declared) layout."""
    names = []
    raw = _module_dotted(rel)
    if raw:
        names.append(raw)
    for prefix in root_prefixes:
        if rel.startswith(prefix):
            stripped = _module_dotted(rel[len(prefix):])
            if stripped and stripped not in names:
                names.append(stripped)
    return names


def _module_dotted(rel: str) -> str:
    """A repo-relative path as its dotted import path (``a/b.py`` -> ``a.b``;
    a package ``__init__`` collapses to the package). Mirrors
    ``mutation_tester._module_dotted_path`` — kept local because that module
    imports THIS one, and a 4-line mirror beats an import cycle."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _add_edges(root: Path, rel: str, own_names: list[str],
               index: dict[str, str], importers: dict[str, set[str]]) -> None:
    """Record every module whose execution ``rel``'s import triggers: each
    ancestor package ``__init__`` (importing ``pkg.mod`` runs
    ``pkg/__init__.py``) and each project module its own import statements
    resolve to. A parse failure contributes the ancestor edges only. A file
    with NO import name at all (a repo-root ``__init__.py`` — its dotted path
    collapses to empty) is skipped: it is not addressable by any import
    statement, so it can contribute no edges (honest degrade, no crash)."""
    if not own_names:
        return
    for name in own_names:
        parts = name.split(".")
        for i in range(1, len(parts)):
            target = index.get(".".join(parts[:i]))
            if target is not None and target != rel:
                importers.setdefault(target, set()).add(rel)
    try:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return
    is_pkg = rel.endswith("__init__.py")
    for name in _absolute_imports(tree, own_names[-1], is_pkg):
        target = _resolve(name, index)
        if target is not None and target != rel:
            importers.setdefault(target, set()).add(rel)


def _absolute_imports(tree: ast.Module, dotted: str, is_pkg: bool) -> set[str]:
    """Every dotted name this module imports, with relative imports resolved
    against the module's own package position (``from . import x`` inside
    ``pkg.mod`` -> ``pkg.x``). For ``from a import b`` both ``a`` and ``a.b``
    are recorded so either can name a project module."""
    names: set[str] = set()
    base = dotted.split(".") if is_pkg else dotted.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _from_target(node, base)
            if target:
                names.add(target)
                names.update(f"{target}.{alias.name}" for alias in node.names)
    return names


def _from_target(node: ast.ImportFrom, base: list[str]) -> str | None:
    """The absolute dotted source a ``from ... import`` pulls from; a relative
    import is resolved against ``base`` (the module's own package parts).
    ``None`` when the relative level escapes the project top (broken import —
    no edge is the honest degrade)."""
    if not node.level:
        return node.module
    if node.level - 1 > len(base):
        return None
    anchor = base[: len(base) - (node.level - 1)]
    if node.module:
        anchor = anchor + node.module.split(".")
    return ".".join(anchor) if anchor else None


def _resolve(name: str, index: dict[str, str]) -> str | None:
    """The project module ``name`` lands in — the longest dotted prefix of
    ``name`` that names an indexed module (``pkg.api.helper`` resolves to
    ``pkg/api.py``; a fully external name resolves to ``None``)."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        rel = index.get(".".join(parts[:i]))
        if rel is not None:
            return rel
    return None
