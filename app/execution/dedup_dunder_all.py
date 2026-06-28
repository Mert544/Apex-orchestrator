"""De-duplicate an existing module-level ``__all__`` of string literals, PRESERVING
first-appearance order.

The CONTENTS of ``__all__`` are a membership SET — ``from m import *`` consults only
WHICH names appear, never how many times or in what order — so dropping a duplicate
string entry is behaviour-IDENTICAL: nothing observable changes. This is the
de-duplication HALF of the public-surface tidy family. Its sibling
:mod:`app.execution.sort_dunder_all` SORTS ``__all__`` into lexicographic order (and
de-dupes as a side effect of ``sorted(set(...))``); this one keeps the author's
ORIGINAL order and only removes the repeats — the minimal, order-faithful fix for a
copy-paste duplicate. Where a linter only FLAGS a duplicated ``__all__`` entry,
:func:`dedup_module_all` rewrites it, deterministically and for free.

DISTINCT from sort-dunder-all: sort-dunder-all owns canonical ORDERING (and acts on
any non-canonical list, duplicate or not); dedup-dunder-all owns ONLY the duplicate
removal and is a no-op on a duplicate-free list whatever its order — so it never
reorders a deliberately-grouped ``__all__`` a sort would churn. (On a list that is
BOTH unsorted AND duplicated the two would each act; they are separate, opt-in
objectives and the engine picks at most one per module per wave.)

REFUSES (returns ``None``, an honest no-op) unless ``__all__`` is a PLAIN literal
``list``/``tuple`` of string-literal elements WITH at least one duplicate AND no
comment inside its statement span. The full refusal scan is REUSED WHOLESALE from
:mod:`app.execution.sort_dunder_all` (a computed ``__all__`` — a name, a ``BinOp``
``_BASE + [...]``, a ``list(...)`` / ``sorted(...)`` call, a comprehension; an
``__all__ += [...]`` / ``.append`` / ``.extend`` / ``.insert``; a conditional
re-binding / second store; a non-string / starred element; more than one ``__all__``;
unparseable source → REFUSE). On top of that shared gate this module ALSO refuses a
``__all__`` whose statement span carries ANY comment: removing a duplicate line could
ORPHAN that comment (comment-loss), so the whole declaration is refused rather than
silently dropping a maintainer's note (over-approximate toward refusal). A
duplicate-FREE ``__all__`` is a no-op (sort-dunder-all, not this, reorders).

Deterministic (first-seen de-dup over ``str`` is total and order-stable; pure AST +
``tokenize`` scan + line splice, no clock/random), stdlib-only, zero-token, idempotent
(the de-duplicated ``__all__`` has no remaining duplicate, so a second run is a
byte-identical no-op). The parser, refusal scan, and splice tail are REUSED WHOLESALE
from :mod:`app.execution.sort_dunder_all` (``_sortable_all`` for the gate,
``resplice_all_names`` for the "render, splice, preserve newline, re-``ast.parse``
guard" epilogue); this module adds only the duplicate-and-comment gate and the
first-seen de-dup (where sort applies ``sorted(set(...))``).
"""

from __future__ import annotations

import ast
import io
import tokenize

from app.execution.sort_dunder_all import _sortable_all, resplice_all_names

__all__ = [
    "dedup_module_all",
    "all_has_duplicates",
]


def _dedup_first_seen(names: list[str]) -> list[str]:
    """``names`` with later duplicates removed, KEEPING first-appearance order.

    A total, deterministic, order-stable function over ``str`` — the de-dup analogue
    of ``sorted(set(...))`` but order-preserving. ``["b", "a", "b"] -> ["b", "a"]``."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _span_has_comment(source: str, start_lineno: int, end_lineno: int) -> bool:
    """True when a ``COMMENT`` token falls on lines ``[start_lineno, end_lineno]``
    (1-based, inclusive) of ``source`` — the line span of the ``__all__`` statement.

    Tokenises the whole module (so a ``#`` inside a string literal is correctly NOT a
    comment) and checks each comment token's start line against the span. Removing a
    duplicate line from a block that carries a comment could orphan that comment, so
    the caller refuses when this is true (comment-loss). A tokenisation failure is
    treated as "a comment might be present" → refuse (over-approximate toward
    refusal), the same fail-safe discipline the rest of the gate keeps."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT and start_lineno <= tok.start[0] <= end_lineno:
                return True
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return True
    return False


def _dedupable_all(source: str) -> tuple[ast.stmt, list[str]] | None:
    """The ``(stmt, current_names)`` of a module with exactly ONE plain
    string-literal ``__all__`` that is NOT dynamically assembled, carries a real
    DUPLICATE, and has NO comment in its statement span; else ``None``.

    Runs the shared sort-dunder-all gate WHOLESALE (parse, single top-level
    ``__all__``, plain literal of string literals, no dynamic mutation anywhere —
    every refusal of the sibling), then adds the two dedup-specific gates: require
    an actual duplicate (a duplicate-free list is sort-dunder-all's business, a
    no-op here) and refuse a commented span (comment-loss). Does NOT itself splice —
    the caller renders the de-duplicated block."""
    gated = _sortable_all(source)
    if gated is None:
        return None  # not a plain single string-literal __all__, or dynamic — refuse
    _tree, stmt, names = gated
    if _dedup_first_seen(names) == names:
        return None  # no duplicate — sort-dunder-all (not this) may reorder
    start = stmt.lineno
    end = getattr(stmt, "end_lineno", stmt.lineno)
    if _span_has_comment(source, start, end):
        return None  # a comment in the span would be orphaned by a dropped dup — refuse
    return stmt, names


def all_has_duplicates(source: str) -> bool:
    """True iff ``source`` has a single plain string-literal ``__all__`` that carries
    a removable DUPLICATE and no comment in its span (so there is a real change to
    make). ``False`` on any refusal, a duplicate-free list, or a commented span. Pure
    (no clock/random)."""
    return _dedupable_all(source) is not None


def dedup_module_all(source: str) -> str | None:
    """De-duplicate the module-level ``__all__`` in ``source`` PRESERVING
    first-appearance order, or ``None`` when nothing changes.

    Runs the shared + dedup-specific gate (single plain string-literal ``__all__``,
    no dynamic mutation, a real duplicate, no comment in span), computes
    ``deduped = first-seen-order(current)`` and — since a duplicate is present it is
    strictly shorter — re-renders the whole ``__all__`` statement's line span
    (preserving the container kind and the header indentation, one quoted name per
    line) and returns the re-``ast.parse``d result. A duplicate-free / computed /
    dynamic / commented / non-string ``__all__``, more than one ``__all__``, or
    unparseable source yields ``None``. Deterministic and idempotent (the result has
    no remaining duplicate, so a second run is a byte-identical no-op)."""
    gated = _dedupable_all(source)
    if gated is None:
        return None
    stmt, current = gated
    deduped = _dedup_first_seen(current)
    # A duplicate was present (gate guarantees it), so ``deduped`` is strictly shorter
    # — there is always a real change here; the shared splice's rejoin guard still drops
    # a no-op/broken splice defensively. Same re-render tail as sort_module_all, derived
    # via the shared ``resplice_all_names`` (the two differ ONLY in deriving the names).
    return resplice_all_names(source, stmt, deduped)
