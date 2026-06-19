"""Deterministic async-safety analyzer.

Inside ``async def`` functions a synchronous blocking call stalls the WHOLE
event loop — every other coroutine on that loop is frozen until the call
returns. This analyzer parses each source file with :mod:`ast` and flags two
conservative, well-understood smells:

1. **Blocking calls inside a coroutine.** Only a fixed, documented allow-list of
   KNOWN blockers is reported, to keep false positives near zero. A call is
   flagged when its name matches one of:

   =====================  ============================================
   Pattern                Why it blocks the loop
   =====================  ============================================
   ``time.sleep(...)``    busy/idle wait on the calling thread
   ``requests.<verb>``    synchronous HTTP (``get``/``post``/``put``/
                          ``patch``/``delete``/``head``/``options``/
                          ``request``)
   ``open(...)``          synchronous file I/O (bare builtin call)
   ``input(...)``         blocks on stdin (bare builtin call)
   ``subprocess.<x>``     spawns and waits on a child process
                          (``run``/``call``/``check_call``/
                          ``check_output``/``Popen``)
   ``os.system(...)``     synchronous shell-out
   =====================  ============================================

   The match is purely name-based over the call's attribute chain (e.g.
   ``time.sleep``) or bare builtin name (``open``/``input``); arguments are not
   inspected. This is a heuristic, not a proof — an aliased import
   (``from time import sleep``) is intentionally NOT chased, to stay
   conservative and deterministic.

2. **Awaitless coroutines.** An ``async def`` whose body contains no ``await``
   (and no ``async for`` / ``async with``) usually shouldn't be ``async`` at
   all — awaiting it adds overhead with no concurrency benefit. ``await`` nodes
   nested in a *non-async* inner function do not count toward the enclosing
   coroutine.

Public API: :func:`analyze_async_safety`. Pure and deterministic — no clock,
randomness, or network; test and fixture files are excluded. Results are sorted
deterministically and each capped at :data:`_MAX_FINDINGS`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["AsyncSafety", "analyze_async_safety"]

# Cap on each emitted finding list, keeping reports bounded and reviewable.
_MAX_FINDINGS = 15

# Synchronous HTTP verbs exposed by ``requests`` (and look-alikes).
_REQUESTS_VERBS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request"}
)

# Blocking ``subprocess`` entry points that spawn and wait on a child.
_SUBPROCESS_CALLS = frozenset(
    {"run", "call", "check_call", "check_output", "Popen"}
)

# Bare builtin calls that perform synchronous I/O.
_BLOCKING_BUILTINS = frozenset({"open", "input"})


@dataclass
class AsyncSafety:
    """Findings from :func:`analyze_async_safety`.

    ``blocking_calls`` items: ``{module, function, line, call}``.
    ``awaitless_async`` items: ``{module, function, line}``.
    Counts mirror the (uncapped) totals discovered.
    """

    blocking_calls: list[dict] = field(default_factory=list)
    awaitless_async: list[dict] = field(default_factory=list)
    blocking_call_count: int = 0
    awaitless_async_count: int = 0


def _attr_chain(func: ast.expr) -> str | None:
    """Dotted name for an attribute call (``time.sleep``), else the bare builtin
    name (``open``), else ``None`` for anything we can't name statically."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        chain: list[str] = []
        current: ast.expr = func
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            chain.append(current.id)
            return ".".join(reversed(chain))
    return None


def _classify_blocking(call: ast.Call) -> str | None:
    """Return the canonical blocking-call label (e.g. ``"time.sleep"``,
    ``"requests.get"``, ``"open"``) if ``call`` matches a known blocker."""
    name = _attr_chain(call.func)
    if name is None:
        return None
    # Bare builtin blockers.
    if name in _BLOCKING_BUILTINS:
        return name
    # Attribute-rooted blockers: <root>...<attr>. ``root`` is the leftmost
    # segment, ``attr`` the final one (handles nested chains like a.b.time.sleep
    # — root "a", attr "sleep" — which simply won't match below).
    if "." in name:
        root = name.split(".", 1)[0]
        attr = name.rsplit(".", 1)[1]
        if root == "time" and attr == "sleep":
            return "time.sleep"
        if root == "os" and attr == "system":
            return "os.system"
        if root == "requests" and attr in _REQUESTS_VERBS:
            return f"requests.{attr}"
        if root == "subprocess" and attr in _SUBPROCESS_CALLS:
            return f"subprocess.{attr}"
    return None


def _has_await(node: ast.AsyncFunctionDef) -> bool:
    """True if the coroutine body contains an ``await`` / ``async for`` /
    ``async with`` that belongs to THIS function (not a nested def/lambda,
    whose awaits bind to their own scope)."""
    return any(_await_in(child) for child in node.body)


def _await_in(node: ast.AST) -> bool:
    """Recursively scan ``node`` (inclusive) for an awaiting construct, without
    descending into nested function definitions or lambdas."""
    if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
        return True
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if _await_in(child):
            return True
    return False


def _module_name(path: Path, root: Path) -> str:
    """Stable ``a.b.c`` module label from the root-relative path."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _is_excluded(path: Path) -> bool:
    """Skip test files and fixtures (their blocking calls are intentional)."""
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    parts = path.parts
    return "tests" in parts or "fixtures" in parts


def analyze_async_safety(root: str | Path, max_files: int = 500) -> AsyncSafety:
    """Scan ``root`` for event-loop-blocking calls inside coroutines and for
    ``async def`` functions that never ``await``.

    Deterministic and side-effect free. ``max_files`` caps the (sorted) file
    walk for bounded cost. See the module docstring for the blocking-call list
    and the awaitless rule.
    """
    root = Path(root)
    files = list(iter_source_files(root))[:max_files]

    blocking: list[dict] = []
    awaitless: list[dict] = []

    for path in files:
        if _is_excluded(path):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue

        module = _module_name(path, root)

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            function = node.name

            # Awaitless coroutine.
            if not _has_await(node):
                awaitless.append(
                    {"module": module, "function": function, "line": node.lineno}
                )

            # Blocking calls within this coroutine's own body (not nested defs).
            for call in _iter_own_calls(node):
                label = _classify_blocking(call)
                if label is not None:
                    blocking.append(
                        {
                            "module": module,
                            "function": function,
                            "line": call.lineno,
                            "call": label,
                        }
                    )

    blocking.sort(key=lambda d: (d["module"], d["function"], d["line"], d["call"]))
    awaitless.sort(key=lambda d: (d["module"], d["function"], d["line"]))

    return AsyncSafety(
        blocking_calls=blocking[:_MAX_FINDINGS],
        awaitless_async=awaitless[:_MAX_FINDINGS],
        blocking_call_count=len(blocking),
        awaitless_async_count=len(awaitless),
    )


def _iter_own_calls(node: ast.AsyncFunctionDef):
    """Yield every ``ast.Call`` lexically inside ``node`` but NOT inside a nested
    function/lambda — those have their own (possibly sync) scope."""
    stack: list[ast.AST] = [
        child
        for child in node.body
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Call):
            yield current
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            stack.append(child)
