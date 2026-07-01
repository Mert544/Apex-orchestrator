"""Add ``@functools.wraps(<callee>)`` to a decorator-factory's inner WRAPPER
function that calls its outer's single parameter but carries no ``wraps`` yet.

The boilerplate every student and team forgets: a hand-written decorator
factory —

    def with_timeout(timeout):
        def decorator(func):
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
        return decorator

— whose innermost ``wrapper`` calls the enclosing function's parameter
(``func``) but never copies its metadata (``__name__``/``__doc__``/
``__module__``/``__qualname__``/``__dict__``) onto the wrapper, so every
decorated function silently loses its identity (``help()``, introspection,
``functools.singledispatch``, pickling of bound methods, and any tool that
reads ``__name__`` all see ``"wrapper"`` instead of the real name).
``functools.wraps(callee)`` is the stdlib's one-line fix for exactly this — a
class decorator wired for functions — and :func:`add_functools_wraps` LANDS it
deterministically, for free, no LLM.

BEHAVIOUR-IDENTICAL by construction: ``functools.wraps`` copies METADATA ONLY
(``__module__``, ``__name__``, ``__qualname__``, ``__doc__``, ``__dict__``, and
sets ``__wrapped__``) — it changes NOT ONE byte of control flow, return value,
or exception behaviour of the wrapper it decorates. Same soundness class as
``add-from-future-annotations`` / ``document-signature``: a reparse-identical
metadata-only edit, no test suite needed to prove it safe.

The shape :func:`add_functools_wraps` detects, per top-level-or-nested
FunctionDef (the "outer"):

  - the outer's body TAIL is exactly ``return <name>`` where ``<name>`` is a
    ``Name`` (never a call/attribute — "wrapper not the direct return value"
    would refuse that);
  - EXACTLY ONE nested ``FunctionDef``/``AsyncFunctionDef`` is defined DIRECTLY
    in the outer's own body (a sibling statement — never inside an ``if``/
    ``for``/``with``), named ``<name>`` (so the tail actually returns IT, not
    some other binding) — "multiple nested funcs / no single unambiguous
    returned wrapper" is the refusal when this fails;
  - the outer has EXACTLY ONE "plausible callee" among its regular parameters —
    a parameter the wrapper's body CALLS (as ``Name(...)``, anywhere, including
    inside a nested lambda) at least once. Zero calls -> nothing to wrap (an
    honest no-op, not every decorator factory calls its wrapped function by
    name inside the wrapper); two or more DIFFERENT called parameters is
    "ambiguous" -> refuse (which single one is being wrapped is not provable);
  - the callee's name is NOT reassigned/rebound anywhere in the outer's OWN
    body BEFORE the wrapper closes over it (a plain ``=``, ``for x in``,
    ``with ... as x``, a walrus, or a nested ``def``/``class`` of that name) —
    "callee name reassigned/shadowed" would make ``func`` inside the wrapper
    refer to something else, so the ``@functools.wraps(func)`` we would emit
    might not even wrap the right thing;
  - the wrapper does NOT already carry a ``functools.wraps``/``wraps``
    decorator (any spelling — bare ``@wraps(x)`` or dotted
    ``@functools.wraps(x)``) — the idempotency guard.

Refused (module-wide, before any per-function scan): unparseable source, and —
via the shared :func:`app.execution.cross_file_rename.plan_source_rewrite` — a
test/fixture/non-library file (Apex never edits the suite, and never decorates
a packaging/config script nobody imports as an API).

Deterministic (pure AST walk + line splice, no clock/random), stdlib-only,
zero-token, idempotent (a second run sees the ``@functools.wraps`` it landed
and refuses — the wrapper now carries it). Reuses
:func:`app.execution.dataclass_rewrite._import_insertion_index` /
:func:`~app.execution.dataclass_rewrite.rejoin_guarded` for the canonical
import spot and the "splice, preserve newline, re-parse guard" epilogue, and
:func:`app.execution.final_marker._insert_decorator` for the
indent-preserving header splice — the same helpers
:mod:`app.execution.total_ordering` reuses for its own decorator-add shape, so
no helper body is copy-pasted here.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded
from app.execution.final_marker import _insert_decorator

__all__ = [
    "add_functools_wraps",
    "wrappable_functions",
]

_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


class _WrapTarget(NamedTuple):
    """One landable ``@functools.wraps(<callee>)`` insertion: the nested wrapper
    ``FunctionDef``/``AsyncFunctionDef`` node to decorate, and the ``callee``
    parameter name it closes over."""

    wrapper: ast.FunctionDef | ast.AsyncFunctionDef
    callee: str


def _regular_param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The REGULAR (positional-or-keyword, including positional-only) parameter
    names of ``fn``, in signature order — the only params eligible to be "the
    callee" (a ``*args``/``**kwargs``/keyword-only param is never what a
    decorator factory's single wrapped callable is bound to in this shape)."""
    return [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]


def _returned_wrapper_name(outer: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The bare name ``outer``'s body TAILS with (``return <name>``), or
    ``None`` when the tail is not exactly that shape (an empty body, a
    non-``Return`` last statement, a ``return`` with no value, or a
    ``return <expr>`` that is not a plain ``Name`` — "wrapper not the direct
    return value")."""
    if not outer.body:
        return None
    tail = outer.body[-1]
    if not isinstance(tail, ast.Return) or tail.value is None:
        return None
    if not isinstance(tail.value, ast.Name):
        return None
    return tail.value.id


def _sole_direct_nested_def(
    outer: ast.FunctionDef | ast.AsyncFunctionDef, name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The ONE ``FunctionDef``/``AsyncFunctionDef`` named ``name`` defined
    DIRECTLY in ``outer``'s own body (a sibling statement — never nested inside
    an ``if``/``for``/``with``/``try``), or ``None`` when zero or MORE THAN ONE
    direct nested def in the body carries that name ("multiple nested funcs /
    no single unambiguous returned wrapper"). Only direct-body statements are
    scanned (not ``ast.walk``): a def buried inside a conditional is not
    provably "the" wrapper the tail always returns."""
    matches = [stmt for stmt in outer.body
               if isinstance(stmt, _DEF_TYPES) and stmt.name == name]
    return matches[0] if len(matches) == 1 else None


def _name_rebound_before(outer: ast.FunctionDef | ast.AsyncFunctionDef,
                         wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
                         name: str) -> bool:
    """True when ``name`` is REBOUND anywhere in ``outer``'s own direct-body
    statements strictly BEFORE ``wrapper`` (a plain ``=``, ``for x in``,
    ``with ... as x``, a walrus, or a nested ``def``/``class`` of that name) —
    the "callee name reassigned/shadowed before the wrapper closes over it"
    refusal. Only the OUTER's own direct-body statements before the wrapper are
    scanned (the parameter itself is bound once, at call time; a rebinding
    inside a DIFFERENT nested function does not affect what ``wrapper`` closes
    over, so is deliberately not walked here — only same-scope shadowing
    matters)."""
    for stmt in outer.body:
        if stmt is wrapper:
            return False  # reached the wrapper with no prior rebinding
        for node in ast.walk(stmt):
            if isinstance(node, _DEF_TYPES + (ast.ClassDef,)) and node.name == name:
                return True
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name:
                return True
    return False  # wrapper not found among outer's own statements — never reached


def _decorator_is_wraps(dec: ast.expr) -> bool:
    """True when ``dec`` is the ``@wraps``/``@functools.wraps`` SHAPE — a bare
    ``Name`` ``wraps`` or a dotted ``Attribute`` ``....wraps``; a called
    ``@wraps(x)`` is unwrapped first. A SHAPE check only (the idempotency
    guard)."""
    if isinstance(dec, ast.Call):
        return _decorator_is_wraps(dec.func)
    if isinstance(dec, ast.Name):
        return dec.id == "wraps"
    return isinstance(dec, ast.Attribute) and dec.attr == "wraps"


def _already_wrapped(wrapper: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``wrapper`` already carries a ``@wraps``/``@functools.wraps``
    decorator (any spelling) — the idempotency guard."""
    return any(_decorator_is_wraps(dec) for dec in wrapper.decorator_list)


def _calls_name(node: ast.AST, name: str) -> bool:
    """True when ANY ``Call`` inside ``node`` (walked, so a call buried in a
    nested ``lambda`` counts — the ``with_timeout`` shape calls ``func`` inside
    a ``lambda: func(*args, **kwargs)``) targets the bare ``Name`` ``name`` —
    ``name(...)``, never an attribute/subscript call. This is what makes a
    parameter "plausible" as the wrapped callee."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == name):
            return True
    return False


def _plausible_callee(
    outer: ast.FunctionDef | ast.AsyncFunctionDef,
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """The ONE outer parameter the wrapper calls by name, or ``None`` when zero
    or MORE THAN ONE of the outer's regular parameters are called inside the
    wrapper's body ("outer takes >1 plausible callee parameter (ambiguous)" —
    or nothing plausible at all, an honest no-op)."""
    candidates = [p for p in _regular_param_names(outer) if _calls_name(wrapper, p)]
    return candidates[0] if len(candidates) == 1 else None


def _wrap_target(
    outer: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _WrapTarget | None:
    """The landable :class:`_WrapTarget` for ``outer``, or ``None`` to refuse
    it. Applies every gate in the module docstring's shape list, in order."""
    returned_name = _returned_wrapper_name(outer)
    if returned_name is None:
        return None
    wrapper = _sole_direct_nested_def(outer, returned_name)
    if wrapper is None:
        return None
    if _already_wrapped(wrapper):
        return None
    callee = _plausible_callee(outer, wrapper)
    if callee is None:
        return None
    if _name_rebound_before(outer, wrapper, callee):
        return None
    return _WrapTarget(wrapper=wrapper, callee=callee)


def wrappable_functions(source: str) -> list[str]:
    """The WRAPPER function names in ``source`` (source order) that
    :func:`add_functools_wraps` would land ``@functools.wraps`` on when
    ``source`` is considered in isolation. Convenience for tests / single-file
    reasoning. Returns ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, _DEF_TYPES):
            target = _wrap_target(node)
            if target is not None:
                out.append(target.wrapper.name)
    return out


def _has_functools_import(tree: ast.AST) -> bool:
    """True when ``functools`` is ALREADY importable as a bare dotted name in
    ``tree`` — a top-level ``import functools`` (any asname-free form) is
    present anywhere in the module. ``@functools.wraps`` always uses the dotted
    spelling, so ONLY a plain ``import functools`` (never
    ``from functools import wraps``) satisfies it; a second, harmless
    ``import functools`` line is inserted otherwise (valid Python, never
    corrupting)."""
    return any(
        isinstance(node, ast.Import)
        and any(alias.name == "functools" and alias.asname is None
                for alias in node.names)
        for node in ast.walk(tree)
    )


def _insert_functools_import(lines: list[str]) -> list[str]:
    """Insert a fresh ``import functools`` line at the canonical spot (after the
    docstring / ``__future__`` imports), keeping a blank line before the code
    that follows — the same placement discipline
    :func:`app.execution.total_ordering._insert_fresh_functools_import` uses
    for its ``from functools import total_ordering`` line."""
    insert_at = _import_insertion_index(lines)
    block = ["import functools"]
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def add_functools_wraps(source: str) -> str | None:
    """Add ``@functools.wraps(<callee>)`` to every landable wrapper in
    ``source``, or ``None`` when nothing changes.

    Walks every FunctionDef/AsyncFunctionDef as a candidate "outer", collects
    each landable :class:`_WrapTarget`, then decorates every wrapper in REVERSE
    source order (so earlier line spans stay valid) and ensures
    ``import functools`` is present exactly once more than it already is (only
    when at least one target landed). Deterministic and idempotent (an
    already-``@functools.wraps``-carrying wrapper is not re-touched); the
    result is re-``ast.parse``d before return, so a malformed rewrite yields
    ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    targets: list[_WrapTarget] = []
    for node in ast.walk(tree):
        if isinstance(node, _DEF_TYPES):
            target = _wrap_target(node)
            if target is not None:
                targets.append(target)
    if not targets:
        return None

    out_lines = list(source.splitlines())
    for target in sorted(targets, key=lambda t: t.wrapper.lineno, reverse=True):
        out_lines = _insert_decorator(
            out_lines, target.wrapper, f"@functools.wraps({target.callee})")
    if not _has_functools_import(tree):
        out_lines = _insert_functools_import(out_lines)
    return rejoin_guarded(source, out_lines)
