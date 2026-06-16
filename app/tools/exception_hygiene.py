"""Exception-handling HYGIENE profile across a project's own modules.

Where the security/quality detector emits line-level *findings* on individual
handlers, this module answers a portfolio question: across the whole tree, **how
healthy is the exception-handling discipline**? It counts and locates the
recurring anti-patterns that make failures silent, un-debuggable, or impossible
to reason about, and reports a single bounded, deterministic summary.

The five rules (each conservative — we only flag what the AST proves)
---------------------------------------------------------------------
  - ``bare_except``        — a bare ``except:`` clause (``handler.type is
                             None``). Catches *everything* including
                             ``KeyboardInterrupt``/``SystemExit``, so it is the
                             broadest possible net and almost never intended.

  - ``broad_except``       — ``except Exception`` or ``except BaseException``
                             (with or without an ``as`` binding, and including a
                             tuple like ``except (Exception, ValueError)``). A
                             named catch-all: less wrong than a bare ``except``,
                             still a "catches more than you meant" smell. We
                             match only those two builtin names by their bare
                             identifier; an alias or attribute access is NOT
                             flagged (we cannot prove what it resolves to).

  - ``swallowed``          — a handler whose body is *exactly* a single ``pass``
                             or a single ``...`` (``Expr(Constant(Ellipsis))``).
                             The exception is caught and silently discarded with
                             no logging, re-raise, or recovery. A body with a
                             comment still parses to just ``pass``, so this is the
                             classic "swallow and move on" pattern. A docstring-
                             only body (a string Expr) is NOT counted — that is
                             unusual but not provably a swallow.

  - ``raise_without_from`` — a bare ``raise NewError(...)`` *inside* an
                             ``except`` body that does NOT use ``raise ... from
                             ...`` (and is not a bare ``raise`` re-raise). This
                             loses the ``__cause__`` chain (PEP 3134), so the
                             original traceback context is dropped. A bare
                             ``raise`` (re-raising the active exception) and a
                             ``raise X from Y`` / ``raise X from None`` are both
                             considered correct and NOT flagged. We look only at
                             ``raise`` statements lexically directly within the
                             handler body (a ``raise`` nested in a function
                             ``def`` inside the handler is its own scope and is
                             skipped).

  - ``large_try``          — a ``try`` whose guarded block holds more than
                             ``max_try_body`` top-level statements (default 12).
                             A sprawling ``try`` body obscures *which* statement
                             the handler is actually guarding and tends to catch
                             failures from code that never needed protection.
                             Only the ``try`` body is measured (not ``else`` /
                             ``finally``), and only its direct children are
                             counted, so a small ``try`` wrapping a large
                             ``for`` loop is one statement, not many.

Scope & determinism
--------------------
Walks ``root`` via :func:`app.engine.skip_dirs.iter_source_files` (so agent
worktrees, venvs, and caches never inflate the counts), parsing each file once
with :mod:`ast`. Test files and fixtures (``tests/`` / ``test/`` dirs,
``test_*.py``, ``conftest.py``, anything under a ``fixtures/`` dir) are excluded
— their deliberately-malformed handlers would poison the metric.

Stdlib-only, empty-safe, pure: no clock, no randomness, no network. Same tree ->
same profile. The offender list is sorted (module, line, kind) and capped so a
huge tree's output stays bounded.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import iter_source_files
from app.engine.skip_dirs import module_dotted_name as _module_name

__all__ = [
    "ExceptionHygiene",
    "analyze_exception_hygiene",
]

# Builtin catch-all names that count as "overly broad" when used as a bare name.
_BROAD_NAMES = frozenset({"Exception", "BaseException"})

# Default top-level-statement count above which a ``try`` body is "large".
# Strictly greater-than, so a body of exactly this many is still acceptable.
_DEFAULT_MAX_TRY_BODY = 12

# Cap on offenders reported so output stays bounded on a huge tree.
_OFFENDER_CAP = 20


def _is_test_or_fixture_path(rel: str) -> bool:
    """True for a test/fixture definition site we must exclude.

    Covers ``tests/``/``test/`` directories (anywhere in the path), ``fixtures/``
    directories, ``test_*.py`` files, and ``conftest.py`` — the places that hold
    intentionally-broken handlers which would corrupt a hygiene metric.
    """
    r = rel.replace("\\", "/").lower()
    name = r.rsplit("/", 1)[-1]
    padded = f"/{r}"
    return (
        r.startswith(("tests/", "test/", "fixtures/"))
        or "/tests/" in padded
        or "/test/" in padded
        or "/fixtures/" in padded
        or name.startswith("test_")
        or name == "conftest.py"
    )


def _is_bare_except(handler: ast.ExceptHandler) -> bool:
    """A bare ``except:`` — no exception type at all."""
    return handler.type is None


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """``except Exception``/``except BaseException`` (or a tuple containing one).

    Conservative: matches only the bare builtin *names*. ``except myexc`` or
    ``except mod.Exception`` is not flagged because we cannot prove the target.
    """
    typ = handler.type
    if typ is None:
        return False
    candidates: list[ast.expr] = (
        list(typ.elts) if isinstance(typ, ast.Tuple) else [typ]
    )
    return any(
        isinstance(c, ast.Name) and c.id in _BROAD_NAMES for c in candidates
    )


def _is_swallowed(handler: ast.ExceptHandler) -> bool:
    """Handler body is exactly a single ``pass`` or a single ``...``.

    A comment-only body parses to a lone ``pass``, so this is the canonical
    silent-swallow pattern. A docstring-only (string ``Expr``) body is *not*
    treated as a swallow.
    """
    body = handler.body
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _direct_raises(handler: ast.ExceptHandler) -> list[ast.Raise]:
    """``raise`` statements lexically *directly* in the handler body.

    We descend through plain control flow (``if``/``for``/``while``/``with``/
    nested ``try``) but stop at any new scope (``def``/``async def``/``lambda``/
    ``class``) — a ``raise`` there belongs to that scope, not this handler.
    """
    found: list[ast.Raise] = []

    def walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.Raise):
                found.append(node)
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue  # new scope; its raises are not ours
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    # Recurse into nested statement bodies one node at a time.
                    walk([child])

    walk(handler.body)
    return found


def _raises_without_from(handler: ast.ExceptHandler) -> list[ast.Raise]:
    """``raise NewError(...)`` in the handler that drop the ``from`` chain.

    A bare ``raise`` (re-raise of the active exception) is fine. A ``raise X
    from Y`` (including ``from None``) is fine. Only ``raise <expr>`` with no
    ``cause`` and an explicit value loses chaining and is returned.
    """
    return [
        r
        for r in _direct_raises(handler)
        if r.exc is not None and r.cause is None
    ]


def _try_body_size(node: ast.Try) -> int:
    """Number of top-level statements in the ``try`` body (not else/finally)."""
    return len(node.body)


@dataclass(frozen=True)
class ExceptionHygiene:
    """Project-wide exception-handling hygiene profile (see module docstring).

    All counts are non-negative totals across every scanned (non-test) module.
    ``offenders`` is a deterministic, capped list of ``{module, line, kind}``
    dicts sorted by ``(module, line, kind)``. Empty-safe: a tree with no
    handlers yields all-zero counts and an empty ``offenders`` list.
    """

    bare_except: int = 0
    broad_except: int = 0
    swallowed: int = 0
    raise_without_from: int = 0
    large_try: int = 0
    offenders: list[dict[str, Any]] = field(default_factory=list)
    files_scanned: int = 0
    max_try_body: int = _DEFAULT_MAX_TRY_BODY

    @property
    def total(self) -> int:
        """Sum of all five category counts — one number for "how bad"."""
        return (
            self.bare_except
            + self.broad_except
            + self.swallowed
            + self.raise_without_from
            + self.large_try
        )


def _scan_source(
    source: str,
    module: str,
    max_try_body: int,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Scan one module's source, returning per-category counts and offenders.

    Returns ``({}, [])``-equivalent (zeroed counts, empty offenders) on a
    syntax error, so a single unparseable file never aborts the whole scan.
    """
    counts = {
        "bare_except": 0,
        "broad_except": 0,
        "swallowed": 0,
        "raise_without_from": 0,
        "large_try": 0,
    }
    offenders: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return counts, offenders

    def record(line: int, kind: str) -> None:
        counts[kind] += 1
        offenders.append({"module": module, "line": line, "kind": kind})

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if _is_bare_except(node):
                record(node.lineno, "bare_except")
            elif _is_broad_except(node):
                # `elif`: a bare except is already the broadest; don't double-count.
                record(node.lineno, "broad_except")
            if _is_swallowed(node):
                record(node.lineno, "swallowed")
            for r in _raises_without_from(node):
                record(r.lineno, "raise_without_from")
        elif isinstance(node, ast.Try):
            if _try_body_size(node) > max_try_body:
                record(node.lineno, "large_try")

    return counts, offenders


def analyze_exception_hygiene(
    root: str | Path,
    max_files: int = 500,
    max_try_body: int = _DEFAULT_MAX_TRY_BODY,
) -> ExceptionHygiene:
    """Compute the exception-handling hygiene profile under ``root``.

    Walks ``root`` for ``*.py`` (skipping the canonical excluded dirs via
    :func:`iter_source_files`, so agent worktrees/venvs never inflate counts),
    excludes test files and fixtures, and applies the five conservative rules
    documented at module top to every parseable module.

    ``max_files`` caps how many source files are parsed (deterministic: the file
    list is sorted, so the cap is reproducible). ``max_try_body`` (default
    ``12``) is the top-level-statement count above which a ``try`` body is
    flagged ``large_try`` — strictly greater-than, so ``max_try_body`` itself is
    acceptable.

    Returns an :class:`ExceptionHygiene`. An empty / handler-free tree yields a
    zeroed, safe profile rather than raising. ``offenders`` is sorted by
    ``(module, line, kind)`` and capped at twenty entries.
    """
    root = Path(root)
    files = list(iter_source_files(root))
    if max_files and max_files > 0:
        files = files[:max_files]

    counts = {
        "bare_except": 0,
        "broad_except": 0,
        "swallowed": 0,
        "raise_without_from": 0,
        "large_try": 0,
    }
    all_offenders: list[dict[str, Any]] = []
    files_scanned = 0

    for path in files:
        rel = path.relative_to(root).as_posix() if _under(path, root) else path.name
        if _is_test_or_fixture_path(rel):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1
        module = _module_name(path, root)
        file_counts, file_offenders = _scan_source(source, module, max_try_body)
        for key, value in file_counts.items():
            counts[key] += value
        all_offenders.extend(file_offenders)

    # Deterministic order; kind breaks ties when two offenders share module+line.
    all_offenders.sort(key=lambda o: (o["module"], o["line"], o["kind"]))

    return ExceptionHygiene(
        bare_except=counts["bare_except"],
        broad_except=counts["broad_except"],
        swallowed=counts["swallowed"],
        raise_without_from=counts["raise_without_from"],
        large_try=counts["large_try"],
        offenders=all_offenders[:_OFFENDER_CAP],
        files_scanned=files_scanned,
        max_try_body=max_try_body,
    )


def _under(path: Path, root: Path) -> bool:
    """True if ``path`` is inside ``root`` (so a relative path can be derived)."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
