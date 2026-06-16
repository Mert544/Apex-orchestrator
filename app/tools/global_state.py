"""Deterministic detector for risky module-level MUTABLE GLOBAL STATE.

Module-level mutable state is hidden coupling: it is shared across every import
of the module, so two callers (or two threads, or two tests) silently see each
other's writes. It defeats test isolation, breaks thread-safety reasoning, and
makes behavior order-dependent. This analyzer flags two shapes of it:

  1. ``mutable_globals`` — a module-level assignment whose value is a MUTABLE
     container: a list/dict/set literal (``[1]``, ``{}``, ``{1, 2}``) or a call
     to a known mutable-container builtin (``list()``, ``dict()``, ``set()``).
     A bare ``{}`` is a dict.

  2. ``global_mutations`` — a function that names a module global via a
     ``global X`` statement, signalling intent to rebind or mutate it. We report
     one entry per (function, global-name) pair.

It is deliberately CONSERVATIVE — false positives are noise, so we EXCLUDE:

  - **UPPER_SNAKE constants**: the naming convention is a promise "do not
    mutate", so ``REGISTRY = {}`` named ``REGISTRY`` is fine but ``registry = {}``
    is flagged. (A leading underscore is ignored when judging the case, so
    ``_CACHE`` still counts as a constant.)
  - **``__all__``**: a dunder export list, not shared runtime state.
  - **type aliases / immutable values**: tuples, frozensets, strings, ints,
    floats, bools, ``None``, and ``frozenset(...)``/``tuple(...)`` calls — none
    are mutable shared state.
  - **class bodies**: assignments inside a ``class`` (including dataclass and
    Enum bodies) are attributes/fields, not module globals.
  - **fixtures/tests**: any file under a ``tests`` dir or named ``test_*``/
    ``conftest.py`` is skipped — its globals are intentional shared fixtures.

Pure and deterministic: no clock, randomness, network, or filesystem writes.
Results are sorted and capped (~15 each) so output is stable input-for-input.
Reuses :func:`app.engine.skip_dirs.iter_source_files` so worktree copies and
caches are never walked. Public entry point: :func:`analyze_global_state`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["GlobalState", "analyze_global_state"]

_CAP = 15

# Builtins that construct a NEW mutable container when called.
_MUTABLE_CTORS = frozenset({"list", "dict", "set"})
# Builtins that construct an IMMUTABLE value — never shared-state risks.
_IMMUTABLE_CTORS = frozenset({"tuple", "frozenset"})


@dataclass
class GlobalState:
    """Result of a mutable-global-state scan.

    ``mutable_globals`` entries: ``{module, name, line, kind}`` where ``kind`` is
    one of ``list``/``dict``/``set`` (literal or constructor).
    ``global_mutations`` entries: ``{module, function, name, line}``.
    Both lists are deterministically sorted and capped at ~15; the ``*_count``
    fields report the PRE-cap totals so a truncated list is still honest.
    """

    mutable_globals: list[dict] = field(default_factory=list)
    global_mutations: list[dict] = field(default_factory=list)
    mutable_globals_count: int = 0
    global_mutations_count: int = 0
    files_scanned: int = 0


def _is_constant_name(name: str) -> bool:
    """True for UPPER_SNAKE constants and dunder names (``__all__``).

    Leading/trailing underscores are stripped first, so ``_CACHE`` and
    ``__all__`` both count as constants and are excluded.
    """
    if name.startswith("__") and name.endswith("__"):
        return True  # dunder (e.g. __all__): not shared runtime state
    core = name.strip("_")
    if not core:
        return True  # all-underscore name, treat as a dunder/constant
    return core.upper() == core and any(c.isalpha() for c in core)


def _mutable_kind(value: ast.expr) -> str | None:
    """Return ``"list"``/``"dict"``/``"set"`` if ``value`` is a mutable container,
    else ``None``. Literals and known mutable-constructor calls qualify; every
    immutable value (tuple/frozenset/str/int/...) returns ``None``."""
    if isinstance(value, ast.List):
        return "list"
    if isinstance(value, ast.Dict):
        return "dict"
    if isinstance(value, ast.Set):
        return "set"
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name):
            if func.id in _MUTABLE_CTORS:
                return func.id
            if func.id in _IMMUTABLE_CTORS:
                return None
    return None


def _assigned_names(target: ast.expr) -> list[str]:
    """Plain ``Name`` targets of an assignment (skips tuple-unpacking and
    attribute/subscript targets, which are not simple module globals)."""
    if isinstance(target, ast.Name):
        return [target.id]
    return []


def _is_test_file(path: Path) -> bool:
    name = path.name
    if name == "conftest.py" or name.startswith("test_") or name.startswith("test"):
        return True
    return "tests" in path.parts


def _module_name(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.with_suffix("").parts
    return ".".join(parts)


def _scan_file(path: Path, module: str, mutables: list[dict], muts: list[dict]) -> None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return

    # Module-level assignments only (direct children of Module). Class bodies
    # and nested scopes are intentionally NOT walked here.
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue

        kind = _mutable_kind(value)
        if kind is None:
            continue
        for name in (n for t in targets for n in _assigned_names(t)):
            if _is_constant_name(name):
                continue
            mutables.append(
                {"module": module, "name": name, "line": node.lineno, "kind": kind}
            )

    # Functions that declare a module global via ``global X``.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                for gname in sub.names:
                    muts.append(
                        {
                            "module": module,
                            "function": node.name,
                            "name": gname,
                            "line": sub.lineno,
                        }
                    )


def analyze_global_state(root: str | Path, max_files: int = 500) -> GlobalState:
    """Scan ``root`` for risky module-level mutable global state.

    Walks up to ``max_files`` source files (worktrees/caches excluded via
    :func:`iter_source_files`), skipping tests/fixtures. Returns a
    :class:`GlobalState` with deterministically sorted, ~15-capped findings and
    pre-cap counts. Empty-safe: a tree with no risky state yields empty lists and
    zero counts.
    """
    root = Path(root)
    mutables: list[dict] = []
    muts: list[dict] = []
    scanned = 0

    for path in iter_source_files(root):
        if scanned >= max_files:
            break
        if _is_test_file(path):
            continue
        scanned += 1
        module = _module_name(path, root)
        _scan_file(path, module, mutables, muts)

    mutables.sort(key=lambda d: (d["module"], d["line"], d["name"]))
    muts.sort(key=lambda d: (d["module"], d["line"], d["function"], d["name"]))

    return GlobalState(
        mutable_globals=mutables[:_CAP],
        global_mutations=muts[:_CAP],
        mutable_globals_count=len(mutables),
        global_mutations_count=len(muts),
        files_scanned=scanned,
    )
