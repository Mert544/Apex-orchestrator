"""Add ``@enum.unique`` to a top-level ``Enum`` subclass PROVEN to carry distinct
simple-literal member values.

``@enum.unique`` has exactly ONE runtime effect: at class-creation time it raises
``ValueError`` iff two members share a value (by ``==``); on an already-distinct
enum it is a complete no-op. So landing ``@enum.unique`` is behaviour-preserving BY
CONSTRUCTION on an enum whose member values are statically proven all-distinct —
and an import-time crash on one that is not. The decorator documents AND enforces a
real design intent — "every member of this enum is a distinct value, never an
implicit alias" — the guard a careful author writes by hand to lock the invariant
against a future duplicate-value alias. Where a linter only FLAGS the opportunity,
:func:`add_enum_unique_decorator` WRITES it, deterministically and for free. This is
the enum-level sibling of add-final.

SOUNDNESS — the only failure mode is a FALSE enforce that would raise at import. It
is closed STATICALLY, not by the suite: the decorator is landed ONLY when the engine
has PROVEN from the AST that every member value is a frozen simple literal AND no two
member values are ``==``-equal. Crucially the collision scan compares the MATERIALISED
Python values with ``==`` (not type-tagged keys), so the Python footgun
``1 == True == 1.0`` is caught — an enum mixing ``1`` and ``True`` (or ``1`` and
``1.0``) is REFUSED, never sealed, because ``@enum.unique`` would itself raise on it.
Any value the engine cannot reduce to a frozen scalar — ``auto()``, a call, a name, a
tuple, a binop, an f-string — forces a whole-enum refusal (over-approximate toward
refusal: soundness over recall). An ``auto()``-valued enum may well be unique at
runtime, but Apex cannot PROVE it statically, so it REFUSES — landing nothing rather
than guessing (the same "when in doubt, refuse" posture as add-final).

A class is sealed ``@enum.unique`` ONLY when ALL of these hold (else an honest no-op):

  - it is a TOP-LEVEL ``Enum`` subclass by base name (``Enum`` / ``IntEnum`` /
    ``StrEnum`` / ``ReprEnum`` / ``Flag`` / ``IntFlag``, bare or dotted ``enum.Enum``);
  - it does NOT already carry ``@unique`` / ``@enum.unique`` (idempotent: a second
    run sees the decorator it landed and is a byte-identical no-op);
  - it has at least ONE member (an empty enum has nothing to make unique — refused
    as noise);
  - EVERY member value is a distinct simple literal (the soundness proof above);
  - the name ``unique`` can be bound UNAMBIGUOUSLY to ``enum.unique`` in the module:
    via an existing/added ``from enum import unique`` (no local shadow, no
    differently-sourced import) emitting a bare ``@unique``, OR — when ``unique`` is
    shadowed but ``enum`` is provably bound — emitting ``@enum.unique``. If NEITHER
    form can be proven, refuse.

``enum.unique`` exists since Python 3.4, so this lands on the project's 3.10 floor
with NO version gate. Deterministic (pure AST walk + line splice, no clock/random),
stdlib-only, zero-token, idempotent. Reuses
:func:`app.execution.dataclass_rewrite._import_insertion_index` /
:func:`~app.execution.dataclass_rewrite.rejoin_guarded` for the canonical import
spot and the "splice, preserve newline, re-``ast.parse`` guard" epilogue,
:func:`app.execution.final_marker._insert_decorator` for the indent-preserving
header splice (identical for a ``class`` header), and the generic
:func:`app.execution.final_marker._shadows_name` shadow probe.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded
from app.execution.final_marker import _insert_decorator, _shadows_name

__all__ = [
    "add_enum_unique_decorator",
    "uniqueable_enums",
    "enum_has_unique_decorator",
]

# The base names that mark a class as an ``Enum`` subclass. Matched by the FINAL
# ``.attr`` of a dotted base too (``enum.Enum`` -> ``"Enum"``), so an import-style
# variant is caught. A conservative over-approximation: an unrelated same-named base
# also counts as an enum — but the member-distinctness proof still gates the seal.
_ENUM_BASE_NAMES = frozenset({"Enum", "IntEnum", "StrEnum", "ReprEnum",
                              "Flag", "IntFlag"})


def _base_attr_name(base: ast.expr) -> str | None:
    """The bare name a base expression contributes: a simple ``Name``'s ``id``
    (``Enum``), or the FINAL ``.attr`` of a dotted ``Attribute`` (``enum.Enum`` ->
    ``"Enum"``). Any other shape (subscript, call) contributes ``None``."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _is_enum_class(cls: ast.ClassDef) -> bool:
    """True when ``cls`` has at least one base naming an ``Enum`` family member
    (bare ``Enum`` or dotted ``enum.Enum``, matched by the final ``.attr``)."""
    return any(_base_attr_name(base) in _ENUM_BASE_NAMES for base in cls.bases)


def _decorator_is_unique(dec: ast.expr) -> bool:
    """True when ``dec`` is the ``@unique`` SHAPE — a bare ``Name`` ``unique`` or a
    dotted ``Attribute`` ``....unique`` (``@enum.unique``); a called ``@unique()``
    is unwrapped first. A SHAPE check only (used for the idempotency guard — an
    already-``@unique``-shaped enum is left alone regardless of where it came from)."""
    if isinstance(dec, ast.Call):
        return _decorator_is_unique(dec.func)
    if isinstance(dec, ast.Name):
        return dec.id == "unique"
    return isinstance(dec, ast.Attribute) and dec.attr == "unique"


def enum_has_unique_decorator(cls: ast.ClassDef) -> bool:
    """True when ``cls`` already carries a ``@unique`` / ``@enum.unique`` decorator
    (the idempotency guard — a second run sees it and stops)."""
    return any(_decorator_is_unique(dec) for dec in cls.decorator_list)


def _is_dunder(name: str) -> bool:
    """True for a dunder name (``__slots__``) — enum machinery, never a member."""
    return name.startswith("__") and name.endswith("__")


def _member_target_name(stmt: ast.stmt) -> str | None:
    """The member name a class-body statement BINDS, or ``None`` when the statement
    is not a member assignment.

    A member is a top-level ``Assign`` with a SINGLE bare-``Name`` target whose id
    is not a dunder, OR an ``AnnAssign`` with a value and a bare-``Name`` target
    (``X: int = 1``). A dunder target, a multi/tuple/star target, or an ``AnnAssign``
    with NO value (a bare ``x: int`` type declaration that binds nothing) yields
    ``None`` — handled by the caller as inert or unmodelled."""
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        target = stmt.target
    else:
        return None
    if isinstance(target, ast.Name) and not _is_dunder(target.id):
        return target.id
    return None


def _is_inert_body_stmt(stmt: ast.stmt) -> bool:
    """True when ``stmt`` is a class-body statement INERT for member purposes — a
    docstring / bare expression, a ``def`` / ``async def``, a nested ``ClassDef``,
    ``pass``, a dunder assignment, or an ``AnnAssign`` with no value (a bare type
    declaration). Such statements are tolerated and ignored; anything else at the
    class top level forces a whole-enum refusal."""
    if isinstance(stmt, (ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef, ast.Pass)):
        return True
    if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
        return True  # ``x: int`` — a bare type declaration binds no member
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
        return (len(targets) == 1 and isinstance(targets[0], ast.Name)
                and _is_dunder(targets[0].id))
    return False


def _member_values(cls: ast.ClassDef) -> list[ast.expr] | None:
    """The member value nodes of ``cls`` in source order, or ``None`` when its body
    contains an UNMODELLED statement (a ``for`` / ``while`` / ``with`` / ``if`` /
    ``try``, a tuple/star target, an augmented assign, a ``del``).

    Over-approximate toward refusal: if any class-top-level statement is neither a
    member assignment nor an inert statement, we cannot enumerate the members
    exactly, so the whole enum is refused (``None``). Mirrors the conservative
    unmodelled-binder refusal in ``module_exports._collect_defined_names``."""
    values: list[ast.expr] = []
    for stmt in cls.body:
        name = _member_target_name(stmt)
        if name is not None:
            values.append(stmt.value)  # type: ignore[arg-type]
        elif not _is_inert_body_stmt(stmt):
            return None  # an unmodelled binder — refuse the whole enum
    return values


def _literal_value(node: ast.expr) -> tuple[object, ...] | None:
    """The materialised Python value of a SIMPLE-LITERAL member value, wrapped in a
    1-tuple so ``None``/``0``/``False`` are distinguishable from "not a literal".

    ACCEPTED: an ``ast.Constant`` whose value is ``int`` / ``str`` / ``bytes`` /
    ``bool`` / ``float`` / ``complex`` / ``None``; OR a unary minus/plus applied to
    a numeric ``ast.Constant`` (``-1``, ``+2``). REFUSED (``None``): ``auto()`` /
    any other call, a name / attribute / subscript, a tuple/list/dict/set, an
    f-string, a binop — anything whose runtime value we cannot compare statically."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bool, int, float, complex, str, bytes)):
            return (node.value,)
        if node.value is None:
            return (None,)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(
                operand.value, (int, float, complex)) and not isinstance(
                operand.value, bool):
            return (-operand.value if isinstance(node.op, ast.USub)
                    else +operand.value,)
    return None


def _has_value_collision(values: list[ast.expr]) -> bool:
    """True when ``values`` are NOT all distinct simple literals — either some value
    is not an accepted literal, or two materialised values are ``==``-equal.

    The collision scan compares MATERIALISED Python values with ``==`` (not
    type-tagged keys), so the footgun ``1 == True == 1.0`` is caught: an enum mixing
    those would make ``@enum.unique`` raise, so it is reported as a collision and
    refused. ``True`` (collision) over-approximates toward refusal."""
    seen: list[object] = []
    for node in values:
        materialised = _literal_value(node)
        if materialised is None:
            return True  # not a provable simple literal — refuse
        value = materialised[0]
        if any(existing == value for existing in seen):
            return True  # an ``==``-colliding pair — @unique would raise; refuse
        seen.append(value)
    return False


def _fold_importfrom(node: ast.ImportFrom, name: str,
                     blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``from ... import ...`` into ``(has_blessed, has_other)`` for the
    binding scan: a ``from enum import <name>`` with NO asname is blessed; any other
    import binding ``name`` (other module, or aliased) is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name) != name:
            continue
        if node.module == "enum" and alias.name == name and alias.asname is None:
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _fold_import(node: ast.Import, name: str,
                 blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``import ...`` into ``(has_blessed, has_other)``. A bare ``import
    enum`` (no asname) is blessed ONLY when the scanned ``name`` is ``enum`` itself
    (the dotted-decorator case); any other binding of ``name`` is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name.split(".")[0]) != name:
            continue
        if alias.name == "enum" and alias.asname is None and name == "enum":
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _import_bindings(tree: ast.AST, name: str) -> tuple[bool, bool]:
    """``(has_blessed, has_other)`` for bindings of ``name`` from ``enum`` in
    ``tree``. ``has_blessed`` iff a ``from enum import <name>`` (no asname) — for
    ``name == "unique"`` — or a bare ``import enum`` — for ``name == "enum"`` — is
    present. ``has_other`` for ANY other import that binds ``name`` (a
    differently-sourced or aliased import)."""
    blessed = (False, False)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            blessed = _fold_importfrom(node, name, blessed)
        elif isinstance(node, ast.Import):
            blessed = _fold_import(node, name, blessed)
    return blessed


class _UniqueBinding(NamedTuple):
    """How the module can spell ``enum.unique`` provably.

    ``bare_ok``: a bare ``@unique`` is provably ``enum.unique`` — ``unique`` is
    already imported ``from enum`` (no asname) AND nothing shadows the name.
    ``dotted_ok``: a dotted ``@enum.unique`` is provable — ``enum`` is imported bare
    AND unshadowed. ``can_add_import``: a fresh ``from enum import unique`` may be
    added — ``unique`` is bound by NOTHING today (no import, no local shadow). The
    decorator is addable iff ``bare_ok or dotted_ok or can_add_import``."""

    bare_ok: bool
    dotted_ok: bool
    can_add_import: bool


def _unique_binding(tree: ast.AST) -> _UniqueBinding:
    """Compute the :class:`_UniqueBinding` for a module's ``tree`` — which spelling
    of ``enum.unique`` is provable, and whether a fresh import may be added.

    ``unique`` is usable bare when ``from enum import unique`` is present with no
    asname, nothing else binds ``unique``, and no local shadow exists. ``enum`` is
    usable dotted when ``import enum`` is present unshadowed and nothing else
    rebinds it. A fresh ``from enum import unique`` is addable only when ``unique``
    is bound by nothing at all (no import, no shadow), so the insert is safe."""
    unique_blessed, unique_other = _import_bindings(tree, "unique")
    unique_shadow = _shadows_name(tree, "unique")
    bare_ok = unique_blessed and not unique_other and not unique_shadow

    enum_blessed, enum_other = _import_bindings(tree, "enum")
    dotted_ok = enum_blessed and not enum_other and not _shadows_name(tree, "enum")

    can_add_import = not unique_blessed and not unique_other and not unique_shadow
    return _UniqueBinding(bare_ok=bare_ok, dotted_ok=dotted_ok,
                          can_add_import=can_add_import)


def _binding_usable(binding: _UniqueBinding) -> bool:
    """True when SOME spelling of ``enum.unique`` is provable (bare, dotted, or a
    fresh import is addable). When ``False`` no enum can be sealed."""
    return binding.bare_ok or binding.dotted_ok or binding.can_add_import


def _is_uniqueable(cls: ast.ClassDef, binding: _UniqueBinding) -> bool:
    """True when ``cls`` is a top-level enum safe to seal ``@enum.unique``.

    Gates (all must hold): a provable spelling of ``enum.unique`` exists in the
    module; ``cls`` is an ``Enum`` subclass by base; it does NOT already carry
    ``@unique``; its body models exactly as member assignments + inert statements
    (no unmodelled binder); it has at least one member; and no two member values
    ``==``-collide (every value a distinct simple literal)."""
    if not _binding_usable(binding):
        return False
    if not _is_enum_class(cls):
        return False
    if enum_has_unique_decorator(cls):
        return False
    values = _member_values(cls)
    if not values:  # None (unmodelled body) or [] (empty enum) — refuse
        return False
    return not _has_value_collision(values)


def _decorator_text(binding: _UniqueBinding) -> str:
    """The decorator spelling to emit: bare ``@unique`` when ``unique`` is (or will
    be) importable from ``enum``, else the dotted ``@enum.unique`` (used only when
    ``unique`` is shadowed but ``enum`` is bound)."""
    if binding.bare_ok or binding.can_add_import:
        return "@unique"
    return "@enum.unique"


def _needs_import(binding: _UniqueBinding) -> bool:
    """True when a fresh ``from enum import unique`` must be inserted — the bare
    ``@unique`` form was chosen via ``can_add_import`` (not already importable)."""
    return binding.can_add_import and not binding.bare_ok


def _is_single_line_widenable_enum_import(line: str) -> bool:
    """True when ``line`` is a CLEAN single-line ``from enum import a, b`` that the
    string-splitting widen can safely re-emit — no surrounding parentheses (a
    multi-line block), no inline ``#`` comment, no backslash continuation. Anything
    that fails these is widened UNSAFELY by the splitter, so the caller inserts a
    fresh ``from enum import unique`` line instead."""
    stripped = line.strip()
    if not stripped.startswith("from enum import "):
        return False
    if "(" in stripped or ")" in stripped:
        return False  # parenthesized (likely multi-line) import — not clean
    if "#" in stripped or stripped.endswith("\\"):
        return False  # inline comment or line continuation — not clean
    return True


def _existing_enum_import_index(lines: list[str]) -> int | None:
    """Index of a CLEANLY single-line-widenable top-level ``from enum import ...``
    line, or ``None`` (then the caller inserts a fresh line)."""
    for i, line in enumerate(lines):
        if _is_single_line_widenable_enum_import(line):
            return i
    return None


def _imported_enum_names(line: str) -> set[str]:
    """The import items a CLEAN single-line ``from enum import a, b as c`` line
    carries — each kept VERBATIM (an ``X as Y`` alias preserved whole), empty pieces
    dropped. The caller guarantees ``line`` is clean, so a naive comma split is safe."""
    return {item.strip() for item in line.split("import", 1)[1].split(",")
            if item.strip()}


def _widen_enum_import(lines: list[str], idx: int) -> list[str]:
    """Add ``unique`` to the clean single-line ``from enum import ...`` at ``idx``
    (items kept sorted), preserving the line's leading indentation."""
    line = lines[idx]
    indent = line[: len(line) - len(line.lstrip())]
    names = _imported_enum_names(line) | {"unique"}
    out = list(lines)
    out[idx] = f"{indent}from enum import " + ", ".join(sorted(names))
    return out


def _insert_fresh_unique_import(lines: list[str]) -> list[str]:
    """Insert a fresh ``from enum import unique`` line at the canonical spot (after
    the docstring / ``__future__`` imports), keeping a blank line before the code
    that follows. A second ``from enum import`` is valid Python, so this is the
    sound fallback when no existing enum import can be cleanly widened on one line."""
    insert_at = _import_insertion_index(lines)
    block = ["from enum import unique"]
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def _ensure_unique_import(lines: list[str]) -> list[str]:
    """Ensure ``from enum import unique`` is importable: widen an existing CLEAN
    single-line ``from enum import ...`` in place (only ``unique`` added), else
    insert a fresh ``from enum import unique`` line at the canonical spot.

    A parenthesized / multi-line / commented enum import is NOT cleanly widenable on
    one line, so it is left untouched and a second ``from enum import unique`` line
    is inserted instead (valid Python) — never corrupting the source."""
    idx = _existing_enum_import_index(lines)
    if idx is not None:
        return _widen_enum_import(lines, idx)
    return _insert_fresh_unique_import(lines)


def uniqueable_enums(source: str) -> list[str]:
    """The names of top-level enums in ``source`` sealable ``@enum.unique`` when
    ``source`` is considered IN ISOLATION (the proof is purely intra-module).

    Convenience for tests / single-file reasoning. Sorted by source order. Returns
    ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    binding = _unique_binding(tree)
    return [node.name for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_uniqueable(node, binding)]


def _uniqueable_enum_nodes(
    tree: ast.Module, binding: _UniqueBinding
) -> list[ast.ClassDef]:
    """Every uniqueable top-level enum node in ``tree``, in source order."""
    return [node for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_uniqueable(node, binding)]


def add_enum_unique_decorator(source: str) -> str | None:
    """Add ``@enum.unique`` to every uniqueable top-level enum in ``source``, or
    ``None`` when nothing changes.

    The soundness proof is purely intra-module (a single enum's own member values
    are statically distinct simple literals or not), so NO whole-project scan is
    needed. Enums are decorated in REVERSE source order so earlier line spans stay
    valid, then the ``from enum import unique`` import is ensured once (only when the
    bare ``@unique`` form needs it). Deterministic and idempotent (an already-
    ``@unique`` enum is not re-touched); the result is re-``ast.parse``d before
    return, so a malformed rewrite yields ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    binding = _unique_binding(tree)
    nodes = _uniqueable_enum_nodes(tree, binding)
    if not nodes:
        return None

    text = _decorator_text(binding)
    out_lines = list(source.splitlines())
    for cls in sorted(nodes, key=lambda c: c.lineno, reverse=True):
        out_lines = _insert_decorator(out_lines, cls, text)
    if _needs_import(binding):
        out_lines = _ensure_unique_import(out_lines)
    return rejoin_guarded(source, out_lines)
