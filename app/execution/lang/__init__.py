"""Append-only registry of :class:`LanguageAdapter`s — let a language register
ITSELF, exactly as ``develop_registry`` lets a develop objective self-register.

A language adapter is a structural plug-in (see :mod:`app.execution.lang.adapter`).
This registry holds the live adapters and dispatches a file to the FIRST one
that ``owns`` it. Registration is append-only and idempotent (re-registering
the same ``name`` replaces it — last write wins, harmless under re-import), and
:func:`adapters` returns them in a DETERMINISTIC order: Python first (it is the
canonical, off-by-default delegator and must win the dispatch for ``.py``
files), then every other adapter sorted by ``name``. So ``adapter_for("m.py")``
is always the Python adapter and the order never depends on import timing.

Mirrors ``develop_registry``'s discipline — deterministic, append-only — and
imports nothing heavy at module top, so importing ``app.execution.lang`` forms
no app import cycle.
"""

from __future__ import annotations

from app.execution.lang.adapter import (
    Edit,
    LanguageAdapter,
    ParseTree,
    Span,
    Target,
    TargetQuery,
)

__all__ = [
    "register_adapter",
    "adapter_for",
    "adapters",
    "clear_registry",
    # re-exported seam types, so callers import the whole vocabulary from here
    "LanguageAdapter",
    "ParseTree",
    "TargetQuery",
    "Target",
    "Edit",
    "Span",
]

# Python sorts FIRST in :func:`adapters` regardless of registration order — it is
# the canonical delegator and must win the ``.py`` dispatch.
_PYTHON = "python"

_REGISTRY: dict[str, LanguageAdapter] = {}
_BUILTINS_LOADED = False


def register_adapter(adapter: LanguageAdapter) -> LanguageAdapter:
    """Register (or replace) ``adapter`` by its ``name``. Returns the adapter so
    it can be used as ``ADAPTER = register_adapter(JavaScriptAdapter())``.
    Re-registering the same name is harmless (last write wins)."""
    _REGISTRY[adapter.name] = adapter
    return adapter


def _ensure_builtins() -> None:
    """Register the built-in adapters (Python + JavaScript + Java) ONCE, on first
    use. Imported lazily — the adapter modules pull in ``cross_file_rename`` /
    the test runner / the language drivers, so importing them at module top would
    couple this leaf package to that heavy graph; deferring keeps ``import
    app.execution.lang`` cheap and cycle-free. Idempotent: built-ins load at most
    once. Order of registration is irrelevant — :func:`adapters` puts Python first
    and sorts every other adapter by ``name`` (so ``java`` sorts before
    ``javascript``), a total order independent of registration timing."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True  # set first: a re-entrant import never double-loads
    from app.execution.lang.java_adapter import JavaAdapter
    from app.execution.lang.js_adapter import JavaScriptAdapter
    from app.execution.lang.python_adapter import PythonAdapter

    register_adapter(PythonAdapter())
    register_adapter(JavaScriptAdapter())
    register_adapter(JavaAdapter())


def _order_key(name: str) -> tuple[int, str]:
    """Sort key putting Python first, then every other adapter alphabetically —
    a total, deterministic order independent of registration timing."""
    return (0 if name == _PYTHON else 1, name)


def adapters() -> list[LanguageAdapter]:
    """The registered adapters in deterministic order (Python first, then sorted
    by name). A fresh list each call, so a caller cannot mutate the registry."""
    _ensure_builtins()
    return [_REGISTRY[name] for name in sorted(_REGISTRY, key=_order_key)]


def adapter_for(rel: str) -> LanguageAdapter | None:
    """The first adapter (in :func:`adapters` order) whose ``owns(rel)`` is True,
    or ``None`` when no language claims ``rel`` (e.g. a test file, or a suffix no
    adapter handles). Deterministic: Python wins ``.py``, the rest by name."""
    for adapter in adapters():
        if adapter.owns(rel):
            return adapter
    return None


def clear_registry() -> None:
    """Drop all registrations and reset built-in loading — for tests only."""
    global _BUILTINS_LOADED
    _REGISTRY.clear()
    _BUILTINS_LOADED = False
