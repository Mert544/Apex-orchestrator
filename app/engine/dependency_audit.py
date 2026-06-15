"""Deterministic dependency audit — Apex's own blind spot, closed.

Apex grades its host project's *code* in depth, yet never looks at the project's
declared DEPENDENCIES. This module cross-checks the two: it reads the declared
deps (``pyproject.toml`` ``[project.dependencies]`` / ``optional-dependencies``
and any ``requirements*.txt``) against the third-party modules the project's
``.py`` files actually import, and surfaces three honest signals:

  - *possibly unused* — declared but never imported anywhere;
  - *possibly undeclared* — imported third-party but not declared;
  - *unpinned* — declared with no version specifier.

It is a HEURISTIC, named so out loud. Extras, optional/conditional imports, and
import-name vs PyPI-name mismatches can all produce false positives — so the
report says "possibly" and the CLI never fails a build off it. The import↔PyPI
mapping is deliberately small and conservative (only well-known mismatches like
``yaml``→``pyyaml``); everything else is assumed to match, which is true for the
large majority of packages.

Pure: deterministic (every list sorted), stdlib-only (``tomllib``/``ast``),
LLM-free, no network. Same input -> same output.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # py311+: stdlib; py310: graceful no-pyproject-parse degrade
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on <3.11
    tomllib = None  # type: ignore[assignment]

from app.engine.skip_dirs import is_skipped

__all__ = [
    "DependencyFindings",
    "audit_dependencies",
    "render_dependency_audit_markdown",
]

# Conservative import-name -> PyPI-name map. ONLY well-known mismatches: the vast
# majority of packages import under their PyPI name (requests↔requests), so an
# absent entry means "assume they match". Keep this SMALL on purpose — a wrong
# guess here manufactures false unused/undeclared findings.
_IMPORT_TO_PYPI: dict[str, str] = {
    "yaml": "pyyaml",
    "pil": "pillow",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "git": "gitpython",
    "attr": "attrs",
    "dateutil": "python-dateutil",
}


@dataclass(frozen=True)
class DependencyFindings:
    """The deterministic result of a dependency audit (all lists sorted).

    Names are normalized for comparison (lowercased, ``-``/``_`` unified) so the
    cross-checks are case- and separator-insensitive.
    """

    declared: list[str]                 # declared dep PyPI-names, normalized
    imported_third_party: list[str]     # top-level third-party modules imported, mapped+normalized
    unused: list[str]                   # declared but never imported ("possibly unused")
    undeclared: list[str]               # imported third-party not declared ("possibly undeclared")
    unpinned: list[str]                 # declared deps with no version pin


def _normalize(name: str) -> str:
    """Lowercase and unify separators so ``PyYAML`` == ``pyyaml`` and
    ``python_dateutil`` == ``python-dateutil``."""
    return name.strip().lower().replace("_", "-")


def _map_import_name(mod: str) -> str:
    """Map a top-level import name to its (normalized) PyPI distribution name,
    using the conservative table then assuming a match."""
    low = mod.strip().lower()
    return _normalize(_IMPORT_TO_PYPI.get(low, low))


def _strip_requirement(spec: str) -> tuple[str, bool]:
    """Parse one declared requirement string into ``(name, pinned)``.

    Strips PEP 508 extras (``pkg[extra]``), environment markers (``; python_version``),
    and version specifiers (``>=``, ``==``, ``~=``, ``!=``, ``<``, ``>``, ``===``).
    ``pinned`` is True when ANY version specifier is present. Returns ``("", ...)``
    for blank/comment/url lines the caller should drop.
    """
    s = spec.strip()
    if not s or s.startswith("#"):
        return "", False
    # Drop an inline comment and an environment marker.
    s = s.split("#", 1)[0].split(";", 1)[0].strip()
    if not s:
        return "", False
    # requirements.txt directives / VCS+URL installs: not a plain name we can map.
    if s.startswith("-") or "://" in s or s.startswith("git+"):
        return "", False
    # Locate the first version-operator character to split name from spec.
    pinned = False
    name = s
    for i, ch in enumerate(s):
        if ch in "<>=!~ ":
            name = s[:i]
            pinned = any(op in s[i:] for op in ("<", ">", "=", "!", "~"))
            break
    # Strip extras: pkg[a,b] -> pkg
    name = name.split("[", 1)[0].strip()
    return name, pinned


def _parse_pyproject(root: Path) -> list[tuple[str, bool]]:
    """Return ``(name, pinned)`` for every dep in ``pyproject.toml``'s
    ``[project.dependencies]`` and ``[project.optional-dependencies]``. Defensive:
    a missing file, unreadable bytes, or absent ``tomllib`` yields ``[]``."""
    path = root / "pyproject.toml"
    if tomllib is None or not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    out: list[tuple[str, bool]] = []
    deps = project.get("dependencies")
    if isinstance(deps, list):
        for item in deps:
            if isinstance(item, str):
                out.append(_strip_requirement(item))
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                for item in group:
                    if isinstance(item, str):
                        out.append(_strip_requirement(item))
    return out


def _parse_requirements(root: Path) -> list[tuple[str, bool]]:
    """Return ``(name, pinned)`` for every dep across ``requirements*.txt`` files
    at the project root. Defensive per-file; unreadable files are skipped."""
    out: list[tuple[str, bool]] = []
    for path in sorted(root.glob("requirements*.txt")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            out.append(_strip_requirement(line))
    return out


def _local_top_packages(root: Path) -> set[str]:
    """Project-own top-level package/module names to exclude from third-party
    imports: any top-level dir holding an ``__init__.py`` (a package) plus the
    stems of top-level ``.py`` modules and any top-level non-package source dir
    that contains ``.py`` files (e.g. ``tests``)."""
    local: set[str] = set()
    try:
        entries = list(root.iterdir())
    except OSError:
        return local
    for entry in entries:
        name = entry.name
        if name.startswith(".") or is_skipped(name):
            continue
        if entry.is_dir():
            if (entry / "__init__.py").is_file():
                local.add(name.lower())
            elif any(entry.rglob("*.py")):
                # a source dir like tests/ that imports may reference
                local.add(name.lower())
        elif entry.is_file() and entry.suffix == ".py":
            local.add(entry.stem.lower())
    return local


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py")
        if not is_skipped(p.relative_to(root))
    )


def _top_level_imports(tree: ast.AST) -> set[str]:
    """Top-level module names imported by an AST. Relative imports
    (``from . import x``, level > 0) are skipped — they are always project-local."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top:
                    names.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import -> local
            if node.module:
                top = node.module.split(".", 1)[0]
                if top:
                    names.add(top)
    return names


def _collect_third_party_imports(root: Path) -> set[str]:
    """Walk every kept ``.py`` file and return the set of third-party top-level
    import names, mapped to normalized PyPI-names. Excludes stdlib, the project's
    own top-level packages, and relative imports. Unparseable files are skipped."""
    stdlib = {m.lower() for m in sys.stdlib_module_names}
    local = _local_top_packages(root)
    third: set[str] = set()
    for path in _iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for mod in _top_level_imports(tree):
            low = mod.lower()
            if low in stdlib or low in local:
                continue
            third.add(_map_import_name(mod))
    return third


def audit_dependencies(root: str) -> DependencyFindings:
    """Cross-check declared deps against actually-imported third-party modules.

    Reads declared deps from ``pyproject.toml`` and ``requirements*.txt`` (PyPI
    names, normalized; recording which carry NO version pin), collects the
    project's third-party top-level imports via ``ast`` (excluding stdlib,
    project-own packages, and relative imports; mapping import↔PyPI names
    conservatively), then computes the set differences.

    Deterministic and defensive: a missing/empty project yields empty lists, not
    an exception. Every list in the result is sorted.
    """
    base = Path(root)

    declared_raw = _parse_pyproject(base) + _parse_requirements(base)
    declared_norm: dict[str, bool] = {}
    for name, pinned in declared_raw:
        if not name:
            continue
        key = _normalize(name)
        # If a dep appears twice, treat it as pinned if ANY occurrence pins it.
        declared_norm[key] = declared_norm.get(key, False) or pinned

    declared = sorted(declared_norm)
    imported = _collect_third_party_imports(base)

    declared_set = set(declared)
    unused = sorted(declared_set - imported)
    undeclared = sorted(imported - declared_set)
    unpinned = sorted(name for name, pinned in declared_norm.items() if not pinned)

    return DependencyFindings(
        declared=declared,
        imported_third_party=sorted(imported),
        unused=unused,
        undeclared=undeclared,
        unpinned=unpinned,
    )


def render_dependency_audit_markdown(f: DependencyFindings) -> str:
    """A calm, honest report. Empty-ish repos get a single clean line; otherwise
    a heuristic-labelled summary plus the three "possibly" lists and unpinned."""
    if not f.declared and not f.imported_third_party:
        return "Dependency audit: no dependency issues found (no declared deps or third-party imports detected)."

    lines: list[str] = []
    lines.append(
        "Dependency audit (heuristic — extras/optional imports may cause false "
        f"positives): {len(f.declared)} declared, "
        f"{len(f.imported_third_party)} third-party imports."
    )

    if not (f.unused or f.undeclared or f.unpinned):
        lines.append("No dependency issues found.")
        return "\n".join(lines)

    if f.unused:
        lines.append("Possibly unused (declared, never imported): " + ", ".join(f.unused))
    if f.undeclared:
        lines.append("Possibly undeclared (imported, not declared): " + ", ".join(f.undeclared))
    if f.unpinned:
        lines.append("Unpinned (no version specifier): " + ", ".join(f.unpinned))

    return "\n".join(lines)
