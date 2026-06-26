"""Add ``@functools.total_ordering`` to a project's own regular class that defines
``__eq__`` AND EXACTLY ONE of the ordering dunders ``__lt__`` / ``__le__`` /
``__gt__`` / ``__ge__`` but is MISSING the other three.

``@functools.total_ordering`` is a stdlib class decorator that, at class-creation
time, FILLS IN the comparison operators a class does not define from the one it does
plus ``__eq__`` — and it explicitly SKIPS any operator already present. So on a class
that has ``__eq__`` + exactly one order op and is missing the other three, landing the
decorator only ADDS the three absent operators (``a <= b`` / ``a > b`` / ``a >= b``
start behaving consistently with the one operator the author wrote), and never
overwrites a method that is already defined. It is the canonical stdlib
boilerplate-killer a careful author reaches for, and the comparison-dunder sibling of
synthesize-dunders (which fills ``__repr__`` / ``__eq__`` / ``__hash__``). Where a
linter only FLAGS the opportunity, :func:`seal_total_ordering` WRITES it,
deterministically and for free.

SOUNDNESS — the change is RUNTIME-ADDITIVE (like enforce-enum-unique and
complete-match-exhaustiveness): the three filled operators were either ABSENT (calling
them raised ``TypeError`` — now they work) or inherited identity defaults any correct
comparison supersedes, so no currently-passing test can regress on a class with the
proven shape. The honesty risk — landing it where the author intended an asymmetric /
partial comparison — is closed by the STATIC RAIL (the exact precondition
``@total_ordering`` documents) PLUS the dynamic suite gate + byte-rollback:

A class is sealed ``@total_ordering`` ONLY when ALL of these hold (else an honest
no-op):

  - it is a TOP-LEVEL ``ClassDef`` whose body is fully MODELLED (every statement is a
    ``def`` / docstring / bare expr / ``pass`` / nested class / simple assignment — an
    unmodelled binder such as a ``for`` / ``if`` / ``try`` / ``with`` that could
    create a comparison method dynamically forces a whole-class refusal, the
    conservative ``enum_unique._member_values`` posture);
  - it defines ``__eq__`` IN THIS CLASS BODY as a ``def`` (an INHERITED ``__eq__`` is
    not provably present — refuse, mirroring synthesize-dunders' inherited-eq rail; an
    ``__eq__`` bound by ASSIGNMENT / lambda rather than ``def`` is unmodelled —
    refuse);
  - EXACTLY ONE of ``{__lt__, __le__, __gt__, __ge__}`` is defined in this body as a
    ``def``, and NONE of the other three are defined at all (zero / two-or-more /
    all-four order ops, or any order op bound by assignment / lambda → refuse);
  - it does NOT already carry ``@total_ordering`` / ``@functools.total_ordering``
    (idempotent: a second run sees the decorator it landed and is a byte-identical
    no-op);
  - the name ``total_ordering`` can be bound UNAMBIGUOUSLY to
    ``functools.total_ordering`` in the module: via an existing / added
    ``from functools import total_ordering`` (no local shadow, no differently-sourced
    import) emitting a bare ``@total_ordering``, OR — when ``total_ordering`` is
    shadowed but ``functools`` is provably bound — emitting ``@functools.total_ordering``.
    If NEITHER form can be proven, refuse.

``functools.total_ordering`` exists since Python 3.2, so this lands on the project's
3.10 floor with NO version gate. Deterministic (pure AST walk + line splice, no
clock/random), stdlib-only, zero-token, idempotent. Reuses
:func:`app.execution.dataclass_rewrite._import_insertion_index` /
:func:`~app.execution.dataclass_rewrite.rejoin_guarded` for the canonical import spot
and the "splice, preserve newline, re-``ast.parse`` guard" epilogue,
:func:`app.execution.final_marker._insert_decorator` for the indent-preserving header
splice, and the generic :func:`app.execution.final_marker._shadows_name` shadow probe,
with the ``from functools import total_ordering`` widen/insert idiom adapted from
:mod:`app.execution.enum_unique`.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded
from app.execution.final_marker import _insert_decorator, _shadows_name
from app.execution.freeze_dataclass import _class_only_object_base

__all__ = [
    "seal_total_ordering",
    "orderable_classes",
    "class_has_total_ordering_decorator",
]

# The four comparison dunders ``@total_ordering`` fills in from one. Order-irrelevant
# set membership only — never a tuple, so determinism never depends on iteration order.
_ORDER_DUNDERS = frozenset({"__lt__", "__le__", "__gt__", "__ge__"})


def _decorator_is_total_ordering(dec: ast.expr) -> bool:
    """True when ``dec`` is the ``@total_ordering`` SHAPE — a bare ``Name``
    ``total_ordering`` or a dotted ``Attribute`` ``....total_ordering``
    (``@functools.total_ordering``); a called ``@total_ordering()`` is unwrapped
    first. A SHAPE check only (the idempotency guard — an already-``@total_ordering``
    -shaped class is left alone regardless of where it came from)."""
    if isinstance(dec, ast.Call):
        return _decorator_is_total_ordering(dec.func)
    if isinstance(dec, ast.Name):
        return dec.id == "total_ordering"
    return isinstance(dec, ast.Attribute) and dec.attr == "total_ordering"


def class_has_total_ordering_decorator(cls: ast.ClassDef) -> bool:
    """True when ``cls`` already carries a ``@total_ordering`` /
    ``@functools.total_ordering`` decorator (the idempotency guard — a second run sees
    it and stops)."""
    return any(_decorator_is_total_ordering(dec) for dec in cls.decorator_list)


def _is_def(stmt: ast.stmt, name: str) -> bool:
    """True when ``stmt`` is a ``def`` / ``async def`` named exactly ``name`` — the
    ONLY shape that provably defines a comparison method (a method bound by assignment
    or lambda is unmodelled and refused by the caller)."""
    return (isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            and stmt.name == name)


def _assignment_target_names(stmt: ast.stmt) -> set[str]:
    """The names a single class-body ``Assign`` / ``AnnAssign`` BINDS via a bare
    ``Name`` target (``__lt__ = ...`` / ``__eq__: object = ...``). Used to detect a
    comparison dunder bound by ASSIGNMENT / lambda rather than ``def`` — an unmodelled
    binder the caller refuses on."""
    names: set[str] = set()
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        names.add(stmt.target.id)
    return names


def _is_modelled_body_stmt(stmt: ast.stmt) -> bool:
    """True when ``stmt`` is a class-body statement the engine can fully MODEL for
    dunder detection — a ``def`` / ``async def`` (a method), a docstring / bare
    expression, a nested ``ClassDef``, ``pass``, or a simple ``Assign`` / ``AnnAssign``
    (a class-var binding whose targets are read by :func:`_assignment_target_names`).

    Anything else at the class top level — a ``for`` / ``while`` / ``with`` / ``if`` /
    ``try`` / ``del`` / augmented assign that could create a comparison method
    DYNAMICALLY — is an unmodelled binder, so the whole class is refused (the
    conservative ``enum_unique._member_values`` posture: soundness over recall)."""
    return isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Expr,
                             ast.ClassDef, ast.Pass, ast.Assign, ast.AnnAssign))


class _BodyShape(NamedTuple):
    """What the engine proved about ``cls``'s body for the total-ordering gate.

    ``modelled``: every body statement is enumerable (no unmodelled binder).
    ``eq_def``: ``__eq__`` is defined as a ``def`` in this body. ``assigned_dunders``:
    the comparison dunders (``__eq__`` or any order op) bound by ASSIGNMENT / lambda
    rather than ``def`` (any presence forces a refuse). ``order_defs``: the order ops
    defined as a ``def`` in this body."""

    modelled: bool
    eq_def: bool
    assigned_dunders: frozenset[str]
    order_defs: frozenset[str]


def _body_shape(cls: ast.ClassDef) -> _BodyShape:
    """Scan ``cls.body`` ONCE into a :class:`_BodyShape`.

    Walks every top-level statement: a ``def`` named ``__eq__`` sets ``eq_def``; a
    ``def`` named an order dunder joins ``order_defs``; an ``Assign`` / ``AnnAssign``
    target that is a comparison dunder (``__eq__`` or an order op) joins
    ``assigned_dunders`` (the assignment / lambda case the caller refuses); any
    statement that is not modellable clears ``modelled``."""
    modelled = True
    eq_def = False
    assigned: set[str] = set()
    order_defs: set[str] = set()
    comparison = _ORDER_DUNDERS | {"__eq__"}
    for stmt in cls.body:
        if not _is_modelled_body_stmt(stmt):
            modelled = False
            continue
        if _is_def(stmt, "__eq__"):
            eq_def = True
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name in _ORDER_DUNDERS:
                order_defs.add(stmt.name)
        else:
            assigned |= _assignment_target_names(stmt) & comparison
    return _BodyShape(modelled=modelled, eq_def=eq_def,
                      assigned_dunders=frozenset(assigned),
                      order_defs=frozenset(order_defs))


def _fold_importfrom(node: ast.ImportFrom, name: str,
                     blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``from ... import ...`` into ``(has_blessed, has_other)`` for the
    binding scan: a ``from functools import <name>`` with NO asname is blessed; any
    other import binding ``name`` (other module, or aliased) is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name) != name:
            continue
        if node.module == "functools" and alias.name == name and alias.asname is None:
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _fold_import(node: ast.Import, name: str,
                 blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``import ...`` into ``(has_blessed, has_other)``. A bare ``import
    functools`` (no asname) is blessed ONLY when the scanned ``name`` is ``functools``
    itself (the dotted-decorator case); any other binding of ``name`` is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name.split(".")[0]) != name:
            continue
        if alias.name == "functools" and alias.asname is None and name == "functools":
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _import_bindings(tree: ast.AST, name: str) -> tuple[bool, bool]:
    """``(has_blessed, has_other)`` for bindings of ``name`` from ``functools`` in
    ``tree``. ``has_blessed`` iff a ``from functools import <name>`` (no asname) — for
    ``name == "total_ordering"`` — or a bare ``import functools`` — for
    ``name == "functools"`` — is present. ``has_other`` for ANY other import that binds
    ``name`` (a differently-sourced or aliased import)."""
    blessed = (False, False)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            blessed = _fold_importfrom(node, name, blessed)
        elif isinstance(node, ast.Import):
            blessed = _fold_import(node, name, blessed)
    return blessed


class _OrderingBinding(NamedTuple):
    """How the module can spell ``functools.total_ordering`` provably.

    ``bare_ok``: a bare ``@total_ordering`` is provably ``functools.total_ordering`` —
    ``total_ordering`` is already imported ``from functools`` (no asname) AND nothing
    shadows the name. ``dotted_ok``: a dotted ``@functools.total_ordering`` is provable
    — ``functools`` is imported bare AND unshadowed. ``can_add_import``: a fresh
    ``from functools import total_ordering`` may be added — ``total_ordering`` is bound
    by NOTHING today (no import, no local shadow). The decorator is addable iff
    ``bare_ok or dotted_ok or can_add_import``."""

    bare_ok: bool
    dotted_ok: bool
    can_add_import: bool


def _ordering_binding(tree: ast.AST) -> _OrderingBinding:
    """Compute the :class:`_OrderingBinding` for a module's ``tree`` — which spelling
    of ``functools.total_ordering`` is provable, and whether a fresh import may be
    added.

    ``total_ordering`` is usable bare when ``from functools import total_ordering`` is
    present with no asname, nothing else binds ``total_ordering``, and no local shadow
    exists. ``functools`` is usable dotted when ``import functools`` is present
    unshadowed and nothing else rebinds it. A fresh ``from functools import
    total_ordering`` is addable only when ``total_ordering`` is bound by nothing at all
    (no import, no shadow), so the insert is safe."""
    to_blessed, to_other = _import_bindings(tree, "total_ordering")
    to_shadow = _shadows_name(tree, "total_ordering")
    bare_ok = to_blessed and not to_other and not to_shadow

    ft_blessed, ft_other = _import_bindings(tree, "functools")
    dotted_ok = ft_blessed and not ft_other and not _shadows_name(tree, "functools")

    can_add_import = not to_blessed and not to_other and not to_shadow
    return _OrderingBinding(bare_ok=bare_ok, dotted_ok=dotted_ok,
                            can_add_import=can_add_import)


def _binding_usable(binding: _OrderingBinding) -> bool:
    """True when SOME spelling of ``functools.total_ordering`` is provable (bare,
    dotted, or a fresh import is addable). When ``False`` no class can be sealed."""
    return binding.bare_ok or binding.dotted_ok or binding.can_add_import


def _is_orderable(cls: ast.ClassDef, binding: _OrderingBinding) -> bool:
    """True when ``cls`` is a top-level class safe to seal ``@total_ordering``.

    Gates (all must hold): a provable spelling of ``functools.total_ordering`` exists
    in the module; ``cls`` does NOT already carry ``@total_ordering``; it has NO base
    other than the implicit ``object`` and no class keywords; its body is fully
    modelled (no unmodelled binder); ``__eq__`` is defined in this body as a ``def``;
    NO comparison dunder is bound by assignment / lambda; and EXACTLY ONE of the four
    order ops is defined in this body as a ``def`` (so the other three are absent).

    The object-only-base rail (mirroring ``seal_hashable_eq`` / ``add_slots`` via the
    shared ``freeze_dataclass._class_only_object_base`` predicate) is what makes the
    fill SOUND. ``@total_ordering`` derives the missing ops from ``max(roots)`` where
    ``roots`` is EVERY order dunder NON-default on the class — INCLUDING any INHERITED
    from a base (``getattr(cls, op) is not getattr(object, op)``). So a class with a
    base carrying a bespoke order op would have that inherited op join ``roots`` and
    possibly WIN the ``max(roots)`` selection, deriving the comparison surface from a
    method this parse-only intra-module view never inspected — contradicting the body
    op the rail proved. A base's inherited comparison surface cannot be proven absent
    here, so ANY non-``object`` base (or a class keyword such as ``metaclass=``) is a
    refusal."""
    if not _binding_usable(binding):
        return False
    if class_has_total_ordering_decorator(cls):
        return False
    if not _class_only_object_base(cls):
        return False  # an inherited order op could win max(roots) — refuse, can't prove absent
    shape = _body_shape(cls)
    if not shape.modelled:
        return False  # an unmodelled binder could create a comparison method — refuse
    if not shape.eq_def:
        return False  # inherited / assignment-bound __eq__ is not provably present
    if shape.assigned_dunders:
        return False  # a comparison dunder bound by assignment / lambda — unmodelled
    return len(shape.order_defs) == 1


def _decorator_text(binding: _OrderingBinding) -> str:
    """The decorator spelling to emit: bare ``@total_ordering`` when
    ``total_ordering`` is (or will be) importable from ``functools``, else the dotted
    ``@functools.total_ordering`` (used only when ``total_ordering`` is shadowed but
    ``functools`` is bound)."""
    if binding.bare_ok or binding.can_add_import:
        return "@total_ordering"
    return "@functools.total_ordering"


def _needs_import(binding: _OrderingBinding) -> bool:
    """True when a fresh ``from functools import total_ordering`` must be inserted —
    the bare ``@total_ordering`` form was chosen via ``can_add_import`` (not already
    importable)."""
    return binding.can_add_import and not binding.bare_ok


def _is_single_line_widenable_functools_import(line: str) -> bool:
    """True when ``line`` is a CLEAN single-line ``from functools import a, b`` that the
    string-splitting widen can safely re-emit — no surrounding parentheses (a
    multi-line block), no inline ``#`` comment, no backslash continuation. Anything
    that fails these is widened UNSAFELY by the splitter, so the caller inserts a fresh
    ``from functools import total_ordering`` line instead."""
    stripped = line.strip()
    if not stripped.startswith("from functools import "):
        return False
    if "(" in stripped or ")" in stripped:
        return False  # parenthesized (likely multi-line) import — not clean
    if "#" in stripped or stripped.endswith("\\"):
        return False  # inline comment or line continuation — not clean
    return True


def _existing_functools_import_index(lines: list[str]) -> int | None:
    """Index of a CLEANLY single-line-widenable top-level ``from functools import ...``
    line, or ``None`` (then the caller inserts a fresh line)."""
    for i, line in enumerate(lines):
        if _is_single_line_widenable_functools_import(line):
            return i
    return None


def _imported_functools_names(line: str) -> set[str]:
    """The import items a CLEAN single-line ``from functools import a, b as c`` line
    carries — each kept VERBATIM (an ``X as Y`` alias preserved whole), empty pieces
    dropped. The caller guarantees ``line`` is clean, so a naive comma split is safe."""
    return {item.strip() for item in line.split("import", 1)[1].split(",")
            if item.strip()}


def _widen_functools_import(lines: list[str], idx: int) -> list[str]:
    """Add ``total_ordering`` to the clean single-line ``from functools import ...`` at
    ``idx`` (items kept sorted), preserving the line's leading indentation."""
    line = lines[idx]
    indent = line[: len(line) - len(line.lstrip())]
    names = _imported_functools_names(line) | {"total_ordering"}
    out = list(lines)
    out[idx] = f"{indent}from functools import " + ", ".join(sorted(names))
    return out


def _insert_fresh_functools_import(lines: list[str]) -> list[str]:
    """Insert a fresh ``from functools import total_ordering`` line at the canonical
    spot (after the docstring / ``__future__`` imports), keeping a blank line before
    the code that follows. A second ``from functools import`` is valid Python, so this
    is the sound fallback when no existing functools import can be cleanly widened on
    one line."""
    insert_at = _import_insertion_index(lines)
    block = ["from functools import total_ordering"]
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def _ensure_total_ordering_import(lines: list[str]) -> list[str]:
    """Ensure ``from functools import total_ordering`` is importable: widen an existing
    CLEAN single-line ``from functools import ...`` in place (only ``total_ordering``
    added), else insert a fresh ``from functools import total_ordering`` line at the
    canonical spot.

    A parenthesized / multi-line / commented functools import is NOT cleanly widenable
    on one line, so it is left untouched and a second ``from functools import
    total_ordering`` line is inserted instead (valid Python) — never corrupting the
    source."""
    idx = _existing_functools_import_index(lines)
    if idx is not None:
        return _widen_functools_import(lines, idx)
    return _insert_fresh_functools_import(lines)


def orderable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` sealable ``@total_ordering`` when
    ``source`` is considered IN ISOLATION (the proof is purely intra-module).

    Convenience for tests / single-file reasoning. Sorted by source order. Returns
    ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    binding = _ordering_binding(tree)
    return [node.name for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_orderable(node, binding)]


def _orderable_class_nodes(
    tree: ast.Module, binding: _OrderingBinding
) -> list[ast.ClassDef]:
    """Every orderable top-level class node in ``tree``, in source order."""
    return [node for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_orderable(node, binding)]


def seal_total_ordering(source: str) -> str | None:
    """Add ``@functools.total_ordering`` to every orderable top-level class in
    ``source``, or ``None`` when nothing changes.

    The soundness proof is purely intra-module (a single class's own body proves
    ``__eq__`` + exactly one order op + the other three absent), so NO whole-project
    scan is needed. Classes are decorated in REVERSE source order so earlier line spans
    stay valid, then the ``from functools import total_ordering`` import is ensured once
    (only when the bare ``@total_ordering`` form needs it). Deterministic and idempotent
    (an already-``@total_ordering`` class is not re-touched); the result is
    re-``ast.parse``d before return, so a malformed rewrite yields ``None`` rather than
    landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    binding = _ordering_binding(tree)
    nodes = _orderable_class_nodes(tree, binding)
    if not nodes:
        return None

    text = _decorator_text(binding)
    out_lines = list(source.splitlines())
    for cls in sorted(nodes, key=lambda c: c.lineno, reverse=True):
        out_lines = _insert_decorator(out_lines, cls, text)
    if _needs_import(binding):
        out_lines = _ensure_total_ordering_import(out_lines)
    return rejoin_guarded(source, out_lines)
