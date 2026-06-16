"""Runtime config-surface census — who reads ``os.environ`` / ``os.getenv``.

Every project pulls some of its behaviour from the environment, but *where* it
reads that configuration is a quiet design signal. A codebase that funnels all of
its ``os.environ[...]`` / ``os.getenv(...)`` reads through one ``settings``/``config``
module has a deliberate, auditable config surface; a codebase where the same reads
are sprinkled across a dozen unrelated modules has a *centralization smell* — no
single place tells you what the program expects from its environment, and a renamed
or missing key fails far from where it is defined.

This analyzer sweeps the project's *own* sources and turns those reads into a
deterministic ledger: which distinct config KEYS are read, how often, and from how
many modules each comes — plus a top-level verdict on whether the reads are
*scattered* across many modules rather than centralized.

Detection (AST-based, so a ``getenv`` substring in a comment or an unrelated
attribute never counts):

  - ``os.environ["KEY"]`` / ``os.environ['KEY']`` — a subscript of the ``os.environ``
    attribute (or a bare ``environ`` imported ``from os``). Constant string subscript
    → that key; anything else → ``<dynamic>``.
  - ``os.environ.get("KEY"[, default])`` / ``environ.get(...)`` — first positional arg.
  - ``os.getenv("KEY"[, default])`` / ``getenv(...)`` (imported ``from os``) — first
    positional arg.

The key name is extracted only when the first argument / subscript is a string
constant; every non-constant form (a variable, an f-string, a call) is recorded as
the literal key ``<dynamic>`` so it is still counted and attributed, just not named.

Reuses :func:`app.engine.skip_dirs.iter_source_files`, so agent worktrees, caches,
and vendored trees are excluded and the file cap stays reproducible. Tests and
fixtures are excluded — their config reads are not part of the project's surface.
Deterministic, pure, stdlib-only: same tree → same :class:`ConfigSurface`, with no
clock, randomness, subprocess, or network.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import is_skipped, iter_source_files

__all__ = ["ConfigSurface", "analyze_config_surface"]

# Sentinel key recorded when a read's key is not a string constant.
DYNAMIC_KEY = "<dynamic>"

# Cap on the number of itemised keys returned (the head, not the totals).
_KEY_CAP = 20

# A config read is considered "scattered" when it is spread thinly across many
# modules: at least this many distinct reader modules AND an average of no more
# than this many reads per module (i.e. no single module dominates / centralizes).
_SCATTER_MIN_MODULES = 3
_SCATTER_MAX_READS_PER_MODULE = 3.0


@dataclass
class ConfigSurface:
    """A deterministic census of runtime config reads under one project root.

    ``keys`` is the stable, capped head of distinct config keys, each
    ``{key, count, modules}`` where ``count`` is the total reads of that key and
    ``modules`` the number of distinct modules that read it. ``total_reads`` is the
    full count of config reads across all scanned files; ``reader_modules`` is the
    number of distinct modules that perform at least one read. ``scattered`` is the
    verdict (reads spread across many modules rather than centralized) and
    ``scatter_score`` its grounding ratio: distinct reader modules over total reads,
    in ``[0, 1]`` — higher means more dispersed (1.0 = every read in a different
    module), 0.0 when there are no reads.
    """

    keys: list[dict[str, Any]] = field(default_factory=list)
    total_reads: int = 0
    reader_modules: int = 0
    scattered: bool = False
    scatter_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "keys": [dict(k) for k in self.keys],
            "total_reads": self.total_reads,
            "reader_modules": self.reader_modules,
            "scattered": self.scattered,
            "scatter_score": self.scatter_score,
        }


def _const_str(node: ast.AST | None) -> str | None:
    """Return the string value if ``node`` is a string constant, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_os_environ(node: ast.AST, environ_names: set[str]) -> bool:
    """True if ``node`` refers to ``os.environ`` (or a bare imported ``environ``)."""
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return isinstance(node.value, ast.Name) and node.value.id == "os"
    return isinstance(node, ast.Name) and node.id in environ_names


def _is_os_getenv(func: ast.AST) -> bool:
    """True if ``func`` is the ``os.getenv`` attribute access."""
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "getenv"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )


def _os_import_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound by ``from os import ...`` treated as the unqualified forms.

    Returns ``(getenv_names, environ_names)`` — the local names under which ``getenv``
    and ``environ`` were imported from ``os`` (honouring ``as`` aliases).
    """
    getenv_names: set[str] = set()
    environ_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "getenv":
                    getenv_names.add(local)
                elif alias.name == "environ":
                    environ_names.add(local)
    return getenv_names, environ_names


def _first_arg_key(node: ast.Call) -> str:
    """Key of a call read: its first positional arg as a constant, else dynamic."""
    arg = node.args[0] if node.args else None
    return _const_str(arg) or DYNAMIC_KEY


def _is_config_call(func: ast.AST, getenv_names: set[str], environ_names: set[str]) -> bool:
    """True if ``func`` is a recognised env-reading call target.

    Covers ``os.getenv(...)``, ``os.environ.get(...)`` / ``environ.get(...)``, and a
    bare ``getenv(...)`` name imported ``from os``.
    """
    if _is_os_getenv(func):
        return True
    if isinstance(func, ast.Attribute) and func.attr == "get":
        return _is_os_environ(func.value, environ_names)
    return isinstance(func, ast.Name) and func.id in getenv_names


def _read_key(
    node: ast.AST, getenv_names: set[str], environ_names: set[str]
) -> str | None:
    """Return the config key ``node`` reads, or ``None`` if it is not a config read.

    Covers ``os.environ[...]`` / ``environ[...]`` subscripts, ``os.getenv(...)``,
    ``os.environ.get(...)`` / ``environ.get(...)``, and bare ``getenv(...)`` imported
    from ``os``. The key is the constant string when present, else :data:`DYNAMIC_KEY`.
    """
    # Subscript: os.environ["X"] / environ["X"]
    if isinstance(node, ast.Subscript) and _is_os_environ(node.value, environ_names):
        return _const_str(node.slice) or DYNAMIC_KEY
    if isinstance(node, ast.Call) and _is_config_call(node.func, getenv_names, environ_names):
        return _first_arg_key(node)
    return None


def _iter_reads(source: str):
    """Yield ``key`` strings for every config read in ``source``.

    A ``from os import getenv, environ`` makes the bare names usable, so both the
    ``os.``-qualified and the imported forms are recognised. The key is the constant
    string when present, otherwise :data:`DYNAMIC_KEY`.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return

    getenv_names, environ_names = _os_import_names(tree)
    for node in ast.walk(tree):
        key = _read_key(node, getenv_names, environ_names)
        if key is not None:
            yield key


def _is_test_or_fixture(rel: Path) -> bool:
    """True for the project's own tests/fixtures, excluded from the config surface."""
    if is_skipped(rel):
        return True
    parts = rel.parts
    if any(p in ("tests", "test", "fixtures", "fixture", "testdata") for p in parts):
        return True
    name = rel.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def analyze_config_surface(root: str | Path, max_files: int = 500) -> ConfigSurface:
    """Census runtime config reads in the Python sources under ``root``.

    Walks at most ``max_files`` source files (excluding worktrees, caches, vendored
    trees, and the project's own tests/fixtures), AST-parsing each and recording every
    ``os.environ[...]`` / ``os.environ.get(...)`` / ``os.getenv(...)`` read. Each read
    contributes its constant key (or :data:`DYNAMIC_KEY` when the key is not a string
    constant) and the reading module.

    The returned ``keys`` head is sorted by descending count, then descending module
    spread, then key name, and capped at ~20. ``scattered`` flags a centralization
    smell — config reads spread thinly across many modules. Pure and deterministic:
    same tree → same result.
    """
    root = Path(root)
    # key -> total count
    key_counts: dict[str, int] = {}
    # key -> set of modules reading it
    key_modules: dict[str, set[str]] = {}
    reader_modules: set[str] = set()
    total_reads = 0

    files = list(iter_source_files(root))[: max(0, max_files)]
    for path in files:
        rel = path.relative_to(root)
        if _is_test_or_fixture(rel):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel_str = rel.as_posix()
        for key in _iter_reads(source):
            total_reads += 1
            key_counts[key] = key_counts.get(key, 0) + 1
            key_modules.setdefault(key, set()).add(rel_str)
            reader_modules.add(rel_str)

    # Deterministic order: most-read first, then widest spread, then key name.
    ordered = sorted(
        key_counts,
        key=lambda k: (-key_counts[k], -len(key_modules[k]), k),
    )
    keys: list[dict[str, Any]] = [
        {"key": k, "count": key_counts[k], "modules": len(key_modules[k])}
        for k in ordered[:_KEY_CAP]
    ]

    n_modules = len(reader_modules)
    scatter_score = (n_modules / total_reads) if total_reads else 0.0
    reads_per_module = (total_reads / n_modules) if n_modules else 0.0
    scattered = (
        n_modules >= _SCATTER_MIN_MODULES
        and reads_per_module <= _SCATTER_MAX_READS_PER_MODULE
    )

    return ConfigSurface(
        keys=keys,
        total_reads=total_reads,
        reader_modules=n_modules,
        scattered=scattered,
        scatter_score=scatter_score,
    )
