"""Restore the canonical field-based ``__hash__`` on a project's own regular
(non-``@dataclass``) class that defines ``__eq__`` in its OWN body but does NOT
define ``__hash__`` and is NOT already deliberately unhashable.

THE PYTHON RULE this lands against: defining ``__eq__`` on a class sets
``__hash__ = None`` IMPLICITLY, so instances become UNHASHABLE — a
``TypeError: unhashable type`` the moment one is used as a ``set`` member or a
``dict`` key. Authors routinely write a value-``__eq__`` and forget to restore the
``__hash__`` that pairs with it. :func:`seal_hashable_eq` LANDS exactly that
canonical ``def __hash__(self): return hash((self.f1, self.f2, ...))`` over the
SAME proven pure-copy field set ``synthesize_dunders`` already trusts — RESTORING
set/dict-key usability where instances currently raise at runtime. A real landed
capability (instances become dict-key / set usable where they raised before), not
advice.

It REUSES synthesize-dunders' canonical-``__hash__`` emit
(``dunder_synthesis._hash_method_lines`` over ``_field_tuple``) and the
add-slots / dataclassify body-splice machinery
(``dataclass_rewrite._class_indent`` / ``_leading_docstring_lines`` /
``rejoin_guarded``, the same trio ``slots_synthesis`` splices with). The field set
is the pure-``self.x = x`` copy set ``synthesize_dunders`` extracts
(``slots_synthesis._init_field_names`` -> ``dataclass_rewrite._is_pure_param_copy``
/ ``_init_params``), so the ``hash`` ranges over EXACTLY the fields the author's
constructor copies — never an invented field (an honest under-claim).

SOUNDNESS — RUNTIME-ADDITIVE. The restored ``__hash__`` only RE-ENABLES an
operation that was a hard ``TypeError`` (an unhashable instance in a ``set`` /
``dict`` key): nothing currently-green relied on the instance being unhashable that
a value-``__hash__`` over the eq-fields would break (a consistent ``__eq__``/
``__hash__`` pair is the canonical contract ``@dataclass`` itself emits and
``synthesize_dunders`` already trusts). The honesty argument is PURELY INTRA-MODULE
— the class's OWN body proves ``__eq__`` is present (by ``def``), ``__hash__`` is
absent (no ``def`` AND no assignment, incl. ``__hash__ = None``), and the field set
is its own ``__init__`` copy set — so NO whole-project scan and NO base class is
needed (UNLIKE ``synthesize_dunders``, whose inherited-``__eq__`` contract needs a
project-own base scan): the hash contract is the class's OWN. This is strictly
simpler / safer than synthesize-dunders. The single residual — a FIELD whose own
value is itself unhashable, so ``hash((..., self.bad, ...))`` raises ``TypeError``
when something hashes an instance — surfaces only at hash time and is caught by the
full-suite gate + byte rollback (the exact ``synthesize_dunders`` rationale).

A class is sealed ONLY when ALL of these hold (otherwise an honest no-op):

  - it is a TOP-LEVEL ``ClassDef`` defining ``__eq__`` in THIS body as a ``def``
    (an INHERITED ``__eq__`` is not provably present; an ``__eq__`` bound by
    ASSIGNMENT / lambda rather than ``def`` is unmodelled — REFUSE);
  - it does NOT define ``__hash__`` at all — neither a ``def`` NOR a class-body
    binding (``__hash__ = None`` is a DELIBERATE unhashable choice the author made;
    ``__hash__ = some_fn`` is a hand-written hash — either way REFUSE, never
    overwrite);
  - it is NOT ``@dataclass`` / ``@dataclasses.dataclass`` -decorated (that path is
    ``eq=``'s own ``__hash__`` story — ``dataclassify`` / freeze own it);
  - it has NO base other than the implicit ``object`` and no class keywords (so an
    Enum / Protocol / ABC subclass — and any inherited-hash contract — is out of
    scope; the hash we restore is the class's OWN);
  - its field set is statically ENUMERABLE and NON-EMPTY — a boilerplate
    ``__init__`` of ``self.<p> = <p>`` copies; a ``*args`` / ``**kwargs`` capture, a
    non-literal ``setattr``, or a real ``__init__`` body beyond copies leaves no
    enumerable copy set and refuses.

The ``__hash__`` method is spliced at the class-body indent at the END of the class
body (one preceding blank line so it does not weld onto the statement above);
classes are processed in REVERSE source order so earlier line spans stay valid, and
``dataclass_rewrite.rejoin_guarded`` re-``ast.parse``s the result so a malformed
splice is NEVER landed (and a byte-identical no-change yields ``None``).
Deterministic (pure AST walk + line splice over the source bytes, source-order
stable, no clock / random / network), stdlib-only, zero-token, idempotent (a second
run sees the ``__hash__`` it landed and is a byte-identical no-op).
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import (
    _class_body_names,
    _class_indent,
    _find_init,
    apply_reverse_line_inserts,
)
from app.execution.dunder_synthesis import _hash_method_lines
from app.execution.freeze_dataclass import _class_only_object_base
from app.execution.slots_synthesis import _init_field_names

__all__ = [
    "seal_hashable_eq",
    "hashable_eq_classes",
]


def _is_dataclass_decorated(cls: ast.ClassDef) -> bool:
    """True when ``cls`` carries a ``@dataclass`` / ``@dataclasses.dataclass``
    decorator (bare or called) by NAME SHAPE — such a class is out of scope here
    (``dataclassify`` / freeze own its ``eq=``/hash story), so it is refused.
    Mirrors ``dunder_synthesis._is_dataclass_decorated``."""
    for dec in cls.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Name) and func.id == "dataclass":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "dataclass":
            return True
    return False


def _defines_eq_by_def(cls: ast.ClassDef) -> bool:
    """True when ``cls`` defines ``__eq__`` in its OWN body as a ``def`` / ``async
    def`` — the ONLY shape that provably pairs a value-equality with the
    ``__hash__`` we restore. An INHERITED ``__eq__`` is not provably present here,
    and an ``__eq__`` bound by ASSIGNMENT / lambda is unmodelled — neither counts
    (mirrors ``total_ordering._is_def``)."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            stmt.name == "__eq__"
        ):
            return True
    return False


def _defines_hash(cls: ast.ClassDef) -> bool:
    """True when ``cls`` defines ``__hash__`` ITSELF in ANY form — a ``def`` /
    ``async def`` method, OR a class-body binding (``__hash__ = None`` /
    ``__hash__ = some_fn`` / ``__hash__: ... = ...``).

    The presence / idempotency guard: ``__hash__ = None`` is a DELIBERATE
    unhashable choice the author made (NOT an accident — REFUSE, never re-enable);
    a hand-written ``def __hash__`` or ``__hash__ = other`` is the author's own
    hash (REFUSE, never overwrite); and a second run sees the ``__hash__`` def this
    objective landed and is a byte-identical no-op. Reuses
    ``dataclass_rewrite._class_body_names`` for the binding case (the
    ``dunder_synthesis._class_defines_dunder`` shape)."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            stmt.name == "__hash__"
        ):
            return True
        if "__hash__" in _class_body_names(stmt):
            return True
    return False


def _proven_fields(cls: ast.ClassDef) -> list[str] | None:
    """The ordered field set the ``__hash__`` tuple ranges over — the SUBSET of
    ``__init__`` statements that are exactly ``self.<p> = <p>`` pure-parameter
    copies, in source order — or ``None`` when ``cls`` has no usable ``__init__`` /
    an unenumerable signature.

    The enumerable-``__init__`` pure-copy extraction is shared VERBATIM with
    add-slots / synthesize-dunders — delegated to
    ``slots_synthesis._init_field_names`` (which reuses
    ``dataclass_rewrite._init_params`` for the enumerability gate — ``None`` on
    ``*args`` / ``**kwargs`` / keyword-only / positional-only / missing ``self`` —
    and ``_is_pure_param_copy`` for the per-statement field test). An EMPTY proven
    subset is returned as ``[]`` — the caller refuses it (nothing to hash over)."""
    init = _find_init(cls)
    if init is None:
        return None  # no constructor to read fields from
    return _init_field_names(init)


def _class_body_end(cls: ast.ClassDef) -> int:
    """The 0-based line index just PAST the last body statement of ``cls`` — where
    the new ``__hash__`` block is spliced (the end of the class body). Uses the
    maximum ``end_lineno`` over the body statements so a multi-line trailing method
    is fully cleared (mirrors ``dunder_synthesis._class_body_end``)."""
    end = cls.body[0].lineno
    for stmt in cls.body:
        end = max(end, getattr(stmt, "end_lineno", stmt.lineno))
    return end


def _plan_one_class(
    cls: ast.ClassDef, lines: list[str]
) -> tuple[int, list[str]] | None:
    """The ``(insert_index, hash_lines)`` splice for ONE class, or ``None`` when it
    fails any gate (an honest no-op).

    Gates (all must hold): not ``@dataclass``-decorated; NO base other than
    ``object`` and no class keywords; defines ``__eq__`` in this body as a ``def``;
    does NOT define ``__hash__`` (by ``def`` or any binding, incl. ``__hash__ =
    None``); and has a NON-EMPTY statically-enumerable pure-copy field set. The
    ``__hash__`` is emitted via ``dunder_synthesis._hash_method_lines`` over that
    proven field set — the SAME canonical shape synthesize-dunders trusts — preceded
    by one blank line so it does not weld onto the statement above it."""
    if _is_dataclass_decorated(cls):
        return None  # dataclassify / freeze own a @dataclass's eq=/hash story
    if not _class_only_object_base(cls):
        return None  # a base / class keyword — the hash contract is not the class's own
    if not _defines_eq_by_def(cls):
        return None  # no provable body-__eq__ — instances were never made unhashable here
    if _defines_hash(cls):
        return None  # __hash__ already defined / __hash__ = None — deliberate, refuse
    fields = _proven_fields(cls)
    if not fields:
        return None  # no enumerable / non-empty pure-copy field set — nothing to hash over

    indent = _class_indent(cls, lines)
    body = ["", *_hash_method_lines(fields, indent)]
    return _class_body_end(cls), body


def _collect_edits(
    tree: ast.Module, lines: list[str]
) -> list[tuple[int, list[str]]]:
    """The ``(insert_index, hash_lines)`` splice for every eligible top-level class
    in ``tree``, in source order."""
    edits: list[tuple[int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        plan = _plan_one_class(node, lines)
        if plan is None:
            continue
        edits.append(plan)
    return edits


def seal_hashable_eq(source: str) -> str | None:
    """Splice the canonical field-based ``__hash__`` over the proven copy-field set
    into every eligible top-level class in ``source``, or ``None`` when nothing
    changes.

    The soundness argument is PURELY INTRA-MODULE — a single class's own body proves
    a body-``__eq__`` is present (by ``def``), ``__hash__`` is absent (no ``def`` and
    no binding, incl. ``__hash__ = None``), there is no base other than ``object``,
    and the field set is its own ``__init__`` copy set — so NO whole-project scan is
    needed (UNLIKE synthesize-dunders). The restored ``__hash__`` is RUNTIME-ADDITIVE
    (it re-enables a hard ``TypeError`` on an unhashable instance), and the lone
    residual (a field whose value is itself unhashable) is caught by the full suite
    gate + ``apply_rename`` byte-rollback. Classes are spliced in REVERSE source order
    so earlier line spans stay valid; the result is re-``ast.parse``d via
    ``dataclass_rewrite.rejoin_guarded`` so a malformed splice yields ``None`` rather
    than landing broken Python. Deterministic and idempotent."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    lines = source.splitlines()
    edits = _collect_edits(tree, lines)
    return apply_reverse_line_inserts(source, lines, edits)


def hashable_eq_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that would gain a restored
    ``__hash__`` when ``source`` is considered IN ISOLATION (the proof is purely
    intra-module, so isolation is the real scope).

    Convenience for tests / single-file reasoning. Sorted by source order. Returns
    ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = source.splitlines()
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _plan_one_class(node, lines) is not None:
            out.append(node.name)
    return out
