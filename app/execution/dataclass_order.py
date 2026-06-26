"""Add ``order=True`` to a project's own ``@dataclass`` that does NOT already set
``order=`` and defines NONE of the comparison dunders ``__lt__``/``__le__``/
``__gt__``/``__ge__`` itself.

``@dataclass(order=True)`` makes the dataclass orderable: it generates the four
comparison operators ``__lt__``/``__le__``/``__gt__``/``__ge__`` from the field
tuple, so instances sort and compare by their fields. When a value dataclass has
none of those operators of its own — they are simply absent, so ``a < b`` raises
``TypeError`` today — adding ``order=True`` is a runtime-ADDITIVE modernization a
linter only FLAGS but :func:`add_dataclass_order` WRITES, deterministically and
for free. This is the dataclass sibling of :mod:`app.execution.freeze_dataclass`
(``frozen=True``) and ``seal-total-ordering`` (``@functools.total_ordering`` for
non-dataclass classes).

SOUNDNESS — runtime-additive + provenance-gated. ``order=True`` only ADDS the
four comparison ops; it never overwrites one the author wrote — in fact
``@dataclass`` RAISES ``TypeError: Cannot overwrite attribute __lt__`` at class-
definition time if you ask for ``order=True`` on a class that already defines one
of the four. So this engine refuses unless ALL of these hold (otherwise an honest
no-op):

  - the class is decorated ``@dataclass`` / ``@dataclasses.dataclass`` (bare or
    called) PROVABLY bound to the stdlib (the :func:`freeze_dataclass.
    _stdlib_dataclass_binding` provenance gate — a ``pydantic`` / locally-shadowed
    ``dataclass`` is refused, soundness over recall);
  - that decorator does NOT already pass ``order=`` (idempotent: a second run sees
    ``order=True`` and is a byte-identical no-op) and does NOT carry a ``**``
    unpacking keyword whose keys we cannot know (it MIGHT already pass ``order=`` —
    appending ours would raise ``TypeError: got multiple values for ... 'order'``);
  - that decorator does NOT set ``eq=False`` — ``order=True`` REQUIRES ``eq=True``
    (the dataclass default); ``@dataclass(eq=False, order=True)`` raises
    ``ValueError: eq must be true if order is true`` at class-definition time;
  - the class body defines NONE of ``__lt__``/``__le__``/``__gt__``/``__ge__`` as a
    ``def`` (defining ``order=True`` alongside a hand-written ordering dunder is the
    ``TypeError: Cannot overwrite attribute`` above);
  - the decorator occupies a SINGLE uncommented physical line (the ``ast.unparse``
    re-emit drops comments and collapses a multi-line decorator — refuse rather
    than risk that content loss, via :func:`freeze_dataclass._is_single_line_rewritable`).

The residual risk — a FIELD whose type is not orderable (two instances only get
compared somewhere the static engine cannot see) — surfaces at runtime as a
``TypeError`` the moment something sorts them, which the objective layer's full-
suite gate + byte-for-byte rollback catches (the same engine every objective
uses). The static rails above close every class-definition-time failure; the suite
gate closes the dynamic field-orderability residual.

The rewrite edits the decorator ONLY — ``@dataclass`` -> ``@dataclass(order=True)``,
``@dataclass()`` -> ``@dataclass(order=True)``, ``@dataclass(frozen=True)`` ->
``@dataclass(frozen=True, order=True)`` — by re-emitting the decorator expression
and splicing its line span. The result is re-``ast.parse``d before it is returned
(via :func:`freeze_dataclass`'s ``rejoin_guarded``), so a malformed rewrite is
dropped rather than landed. Deterministic (pure AST walk + line splice, no
clock/random), stdlib-only, zero-token, idempotent.

Reuses :mod:`app.execution.freeze_dataclass`'s decorator-rewrite machinery
unchanged: ``_stdlib_dataclass_binding`` (provenance), ``_is_stdlib_dataclass_name``,
``_decorator_func``, ``_is_dataclass_name``, ``_is_single_line_rewritable``, and
``app.execution.dataclass_rewrite`` ``_node_line_span`` / ``rejoin_guarded``.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import _node_line_span, rejoin_guarded
from app.execution.freeze_dataclass import (
    _decorator_func,
    _is_dataclass_name,
    _is_single_line_rewritable,
    _is_stdlib_dataclass_name,
    _stdlib_dataclass_binding,
)

__all__ = [
    "add_dataclass_order",
    "orderable_classes",
    "is_ordered_dataclass_decorator",
]

# The four ordering dunders ``@dataclass(order=True)`` generates. A class that
# defines ANY of them itself cannot also ask for ``order=True`` — ``@dataclass``
# raises ``TypeError: Cannot overwrite attribute <name>`` at definition time — so
# the presence of any one is a hard refusal.
_ORDER_DUNDERS = frozenset({"__lt__", "__le__", "__gt__", "__ge__"})


def _decorator_blocks_order(dec: ast.expr) -> bool:
    """True when a called ``@dataclass(...)`` already settles the ``order``
    question and must be left alone, OR carries a shape we cannot safely splice:

      - an explicit ``order=`` keyword (any value) — idempotent / a deliberate
        choice, never override it;
      - ``eq=False`` — ``order=True`` REQUIRES ``eq=True`` (the default), so
        ``@dataclass(eq=False, order=True)`` raises ``ValueError`` at definition
        time; refuse rather than land a class that won't import;
      - a ``**`` unpacking keyword (``kw.arg is None``) whose dict keys we cannot
        know statically — it MIGHT already carry ``order``, and appending
        ``order=True`` would emit valid syntax that raises ``TypeError: got
        multiple values for keyword argument 'order'`` at import.

    A bare ``@dataclass`` has no keywords, so this is ``False``."""
    if not isinstance(dec, ast.Call):
        return False
    for kw in dec.keywords:
        if kw.arg in ("order", None):
            return True
        if kw.arg == "eq" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
    return False


def is_ordered_dataclass_decorator(dec: ast.expr) -> bool:
    """True when ``dec`` is a ``@dataclass`` decorator we will NOT add
    ``order=True`` to: it already settles ``order=`` / sets ``eq=False`` / unpacks
    ``**`` (the idempotency-and-refusal guard — see :func:`_decorator_blocks_order`).
    A SHAPE check on the ``dataclass`` name (provenance is gated separately)."""
    return _is_dataclass_name(_decorator_func(dec)) and _decorator_blocks_order(dec)


def _class_defines_order_dunder(cls: ast.ClassDef) -> bool:
    """True when ``cls``'s body defines ANY of ``__lt__``/``__le__``/``__gt__``/
    ``__ge__`` as a ``def`` / ``async def``.

    Asking for ``order=True`` on such a class raises ``TypeError: Cannot overwrite
    attribute`` at class-definition time, so any one of them is a hard refusal."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name in _ORDER_DUNDERS:
                return True
    return False


def _class_assigns_order_dunder(cls: ast.ClassDef) -> bool:
    """True when ``cls``'s body binds any of the four ordering dunders by a NON-def
    statement — a plain ``__lt__ = _cmp`` / annotated ``__lt__: X = ...`` class-body
    assignment. Such a binding ALSO becomes an attribute ``@dataclass(order=True)``
    would try to overwrite (``TypeError: Cannot overwrite attribute`` at definition
    time), and it is an unmodelled shape we will not splice past — refuse."""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id in _ORDER_DUNDERS:
                    return True
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id in _ORDER_DUNDERS:
                return True
    return False


def _orderable_decorator(
    cls: ast.ClassDef, bare_ok: bool, dotted_ok: bool
) -> ast.expr | None:
    """The class's STDLIB ``@dataclass`` / ``@dataclasses.dataclass`` decorator
    that we may add ``order=True`` to, or ``None``.

    ``bare_ok`` / ``dotted_ok`` are the module's proven stdlib bindings (from
    :func:`freeze_dataclass._stdlib_dataclass_binding`): a decorator is considered
    only when :func:`freeze_dataclass._is_stdlib_dataclass_name` accepts it under
    those flags, so a ``pydantic`` / locally-shadowed ``dataclass`` is skipped.
    Returns ``None`` when the class carries no such decorator, OR when one is present
    but already settles ``order=`` / sets ``eq=False`` / unpacks ``**`` (idempotent /
    a refusal — :func:`_decorator_blocks_order`)."""
    for dec in cls.decorator_list:
        if not _is_stdlib_dataclass_name(_decorator_func(dec), bare_ok, dotted_ok):
            continue
        if _decorator_blocks_order(dec):
            return None  # already order=/eq=False/**opts — leave it
        return dec
    return None


def _emit_ordered_decorator(dec: ast.expr) -> ast.expr:
    """A NEW decorator expression equal to ``dec`` with ``order=True`` added.

    A bare ``@dataclass`` / ``@dataclasses.dataclass`` becomes a call
    ``@dataclass(order=True)``; an existing ``@dataclass(...)`` call keeps its
    args/keywords and gains a trailing ``order=True`` keyword. ``dec`` is known to
    carry no ``order=`` / ``eq=False`` / ``**`` already (the caller checked)."""
    order_kw = ast.keyword(arg="order", value=ast.Constant(value=True))
    if isinstance(dec, ast.Call):
        return ast.Call(func=dec.func, args=list(dec.args),
                        keywords=[*dec.keywords, order_kw])
    return ast.Call(func=dec, args=[], keywords=[order_kw])


def _rewrite_decorator(dec: ast.expr, lines: list[str]) -> tuple[int, int, list[str]]:
    """The ``(start, end, [new_line])`` line-splice that rewrites ONE decorator's
    source span to its ``order=True`` form.

    Preserves the decorator's leading indentation and re-emits the modified
    expression via ``ast.unparse`` behind the ``@`` sigil. The decorator is known
    to occupy a SINGLE physical line with no inline comment (the orderability gate
    checks this via :func:`freeze_dataclass._is_single_line_rewritable`); a
    multi-line or commented decorator is REFUSED upstream rather than collapsed.
    ``rejoin_guarded`` re-parses the result, dropping a malformed splice."""
    start, end = _node_line_span(dec)
    header = lines[start]
    indent = header[: len(header) - len(header.lstrip())]
    new_dec = _emit_ordered_decorator(dec)
    new_line = f"{indent}@{ast.unparse(new_dec)}"
    return start, end, [new_line]


def _is_orderable(
    cls: ast.ClassDef, lines: list[str], bare_ok: bool, dotted_ok: bool
) -> ast.expr | None:
    """The ``@dataclass`` decorator to add ``order=True`` to on ``cls``, or
    ``None`` when ``cls`` fails ANY soundness gate.

    Gates (all must hold): a not-yet-ordered, eq-not-disabled, non-``**`` PROVABLY-
    stdlib ``@dataclass`` decorator on a SINGLE uncommented physical line is present;
    and ``cls``'s body defines NONE of ``__lt__``/``__le__``/``__gt__``/``__ge__``
    (by ``def`` OR by assignment) — otherwise ``@dataclass(order=True)`` would raise
    ``TypeError: Cannot overwrite attribute`` at class-definition time."""
    dec = _orderable_decorator(cls, bare_ok, dotted_ok)
    if dec is None:
        return None
    if not _is_single_line_rewritable(dec, lines):
        return None  # multi-line / commented decorator — refuse (would lose content)
    if _class_defines_order_dunder(cls):
        return None  # a hand-written ordering dunder — order=True would TypeError
    if _class_assigns_order_dunder(cls):
        return None  # an assigned ordering dunder — unmodelled + would TypeError
    return dec


def orderable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that are orderable (eligible
    for ``order=True``), in source order. Returns ``[]`` on a syntax error.

    Convenience for tests / single-file reasoning: the proof is purely intra-module
    (no whole-project scan), so this sees exactly what the objective's plan does."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = source.splitlines()
    bare_ok, dotted_ok = _stdlib_dataclass_binding(tree)
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_orderable(
            node, lines, bare_ok, dotted_ok
        ):
            out.append(node.name)
    return out


def _collect_order_edits(
    tree: ast.Module, lines: list[str], bare_ok: bool, dotted_ok: bool
) -> list[tuple[int, int, list[str]]]:
    """The ``(start, end, new_lines)`` decorator splice for every orderable
    top-level class in ``tree``, in source order."""
    edits: list[tuple[int, int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        dec = _is_orderable(node, lines, bare_ok, dotted_ok)
        if dec is None:
            continue
        edits.append(_rewrite_decorator(dec, lines))
    return edits


def add_dataclass_order(source: str) -> str | None:
    """Add ``order=True`` to every orderable ``@dataclass`` in ``source``, or
    ``None`` when nothing changes.

    The proof is purely intra-module (no whole-project scan): a class is eligible
    iff it is a provably-stdlib ``@dataclass`` not already ordered (nor ``eq=False``
    / ``**``-unpacking), defines none of the four ordering dunders itself, and its
    decorator is a single uncommented physical line. Classes are rewritten in
    REVERSE source order so earlier line spans stay valid. Deterministic and
    idempotent (an already-ordered dataclass is not re-touched); the result is
    re-``ast.parse``d before return (``rejoin_guarded``), so a malformed rewrite
    yields ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    lines = source.splitlines()
    bare_ok, dotted_ok = _stdlib_dataclass_binding(tree)
    edits = _collect_order_edits(tree, lines, bare_ok, dotted_ok)
    if not edits:
        return None

    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so spans stay valid
    out_lines = list(lines)
    for start, end, new_lines in edits:
        out_lines[start:end] = new_lines
    return rejoin_guarded(source, out_lines)
