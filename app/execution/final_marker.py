"""Add ``@typing.final`` to a top-level class PROVABLY never subclassed anywhere
in the project's own source.

``@typing.final`` is a PURE runtime no-op — the decorator only sets
``__final__ = True`` on the class and returns it unchanged; it carries no runtime
semantics and is consulted by TYPE CHECKERS only. So marking a class ``@final`` is
the strongest possible behaviour-preservation story: there is *nothing* at runtime
to break. The decorator documents and (for a type checker) ENFORCES a real design
intent — "this is a leaf class, do not subclass it" — the one-line annotation a
careful author writes by hand. Where a linter only FLAGS the opportunity,
:func:`add_final_decorator` WRITES it, deterministically and for free.

SOUNDNESS — the only failure mode. Because the decorator has no runtime effect, a
green suite proves nothing *behavioural*; but it also cannot break anything. The
single honesty risk is a FALSE "final" claim — marking ``@final`` a class that IS
subclassed somewhere (a type checker would then reject the subclass). That is
closed STRUCTURALLY, not by the suite: a whole-project over-approximate subclass
scan (:func:`app.execution.freeze_dataclass._used_as_base_names`, reused unchanged)
collects every name ever used as a base — a bare ``class X(Foo)``, a dotted
``class X(pkg.Foo)`` (matched by its final ``.attr``), AND a subscripted
``class X(Foo[int])`` (matched by the subscript's head name) — and a class is a
candidate ONLY when its name is absent from that set. The over-approximation may
refuse an unrelated same-named class (soundness over recall), but never misses a
real subclass.

A class is marked ``@final`` ONLY when ALL of these hold (otherwise an honest
no-op):

  - it is a TOP-LEVEL class whose name is NOT used as a base anywhere in the
    project (the structural never-subclassed proof above);
  - it does NOT already carry ``@final`` / ``@typing.final`` (idempotent: a second
    run sees the decorator it landed and is a byte-identical no-op);
  - it is NOT an abstract base meant to be subclassed — no ``Protocol`` / ``ABC``
    base, no ``ABCMeta`` / ``abc.ABCMeta`` ``metaclass=`` (those are extension
    points by design — sealing them would be wrong intent);
  - it is NOT an ``Enum`` subclass (an enum is already implicitly final-ish and
    special — ``@final`` adds nothing and an enum's bases are out of scope);
  - the name ``final`` can be bound UNAMBIGUOUSLY to ``typing.final`` in the
    module: either via an existing/added ``from typing import final`` (no local
    shadow, no differently-sourced import) emitting bare ``@final``, OR — when
    ``final`` is shadowed but ``typing`` is provably bound (``import typing``, no
    shadow) — emitting ``@typing.final``. If NEITHER form can be proven, refuse
    (the round-16 ``final``-shadow lesson: never add a decorator under a name that
    may not be ``typing.final``).

``typing.final`` exists since Python 3.8, so this lands on the project's 3.10
floor with NO version gate. Deterministic (pure AST walk + line splice, no
clock/random), stdlib-only, zero-token, idempotent. Reuses
:func:`app.execution.freeze_dataclass._used_as_base_names` /
:func:`~app.execution.freeze_dataclass.project_sources` for the whole-project
subclass scan, :func:`app.execution.dataclass_rewrite._import_insertion_index` /
:func:`~app.execution.dataclass_rewrite.rejoin_guarded` for the canonical import
spot and the "splice, preserve newline, re-``ast.parse`` guard" epilogue.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded
from app.execution.freeze_dataclass import _used_as_base_names, project_sources

__all__ = [
    "add_final_decorator",
    "finalizable_classes",
    "class_has_final_decorator",
    "project_sources",
]

# The bases / metaclasses that mark a class as an extension point by design — an
# abstract base / protocol / enum is MEANT to be subclassed (or is already
# special), so sealing it ``@final`` would be the wrong intent. Matched by the
# FINAL ``.attr`` of a dotted base too (``abc.ABC`` -> ``ABC``), so an import-style
# variant is caught.
_ABSTRACT_BASE_NAMES = frozenset({"Protocol", "ABC", "Enum", "IntEnum", "StrEnum",
                                  "Flag", "IntFlag"})
_ABCMETA_NAMES = frozenset({"ABCMeta"})


def _base_attr_name(base: ast.expr) -> str | None:
    """The bare name a base/keyword-value expression contributes: a simple
    ``Name``'s ``id`` (``Protocol``), or the FINAL ``.attr`` of a dotted
    ``Attribute`` (``abc.ABC`` -> ``"ABC"``, ``enum.Enum`` -> ``"Enum"``). Any
    other shape (subscript ``Generic[T]``, call) contributes ``None`` — its head
    is handled separately where it matters."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _subscript_head_name(base: ast.expr) -> str | None:
    """The head name of a SUBSCRIPTED base ``H[...]`` (``Protocol[T]`` ->
    ``"Protocol"``, ``enum.Enum`` is not subscripted). ``None`` for a non-subscript
    base. Lets an abstract-base check see ``class P(Protocol[T])``."""
    if isinstance(base, ast.Subscript):
        return _base_attr_name(base.value)
    return None


def _is_abstract_or_special_base(cls: ast.ClassDef) -> bool:
    """True when ``cls`` is an abstract base / protocol / enum — a class MEANT to
    be subclassed (or already special), which must NOT be sealed ``@final``.

    Refuses when any base (bare, dotted, or subscripted head) names ``Protocol`` /
    ``ABC`` / an ``Enum`` family, OR a ``metaclass=`` keyword names ``ABCMeta`` /
    ``abc.ABCMeta``. The name match is by the final ``.attr``, so ``abc.ABC`` and a
    bare ``ABC`` are both caught (a conservative over-approximation: an unrelated
    same-named base also refuses — soundness over recall)."""
    for base in cls.bases:
        name = _base_attr_name(base) or _subscript_head_name(base)
        if name in _ABSTRACT_BASE_NAMES:
            return True
    for kw in cls.keywords:
        if kw.arg == "metaclass" and _base_attr_name(kw.value) in _ABCMETA_NAMES:
            return True
    return False


def _decorator_is_final(dec: ast.expr) -> bool:
    """True when ``dec`` is the ``@final`` SHAPE — a bare ``Name`` ``final`` or a
    dotted ``Attribute`` ``....final`` (``@typing.final``). A SHAPE check only
    (it does not prove the name binds ``typing.final``); used for the idempotency
    guard, which only needs the shape — an already-``@final``-shaped class is left
    alone regardless of where ``final`` came from."""
    if isinstance(dec, ast.Name):
        return dec.id == "final"
    return isinstance(dec, ast.Attribute) and dec.attr == "final"


def class_has_final_decorator(cls: ast.ClassDef) -> bool:
    """True when ``cls`` already carries a ``@final`` / ``@typing.final`` decorator
    (the idempotency guard — a second run sees it and stops)."""
    return any(_decorator_is_final(dec) for dec in cls.decorator_list)


def _shadows_name(tree: ast.AST, name: str) -> bool:
    """True when ``name`` is bound anywhere in ``tree`` by a NON-import statement —
    a ``def`` / ``class`` of that name, or any ``Store``-context assignment target
    (``name = ...``, ``for name in``, ``with x as name``, a walrus). Such a binding
    shadows a same-named ``typing`` import, so the decorator can no longer be proven
    to be ``typing.final`` under that name (the round-16 ``final``-shadow lesson).
    Import-form rebindings are handled by :func:`_import_bindings`."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id == name:
                return True
    return False


def _fold_importfrom(node: ast.ImportFrom, name: str,
                     blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``from ... import ...`` into ``(has_blessed, has_other)`` for the
    binding scan: a ``from typing import <name>`` with NO asname is blessed; any
    other import binding ``name`` (other module, or aliased) is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name) != name:
            continue
        if node.module == "typing" and alias.name == name and alias.asname is None:
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _fold_import(node: ast.Import, name: str,
                 blessed: tuple[bool, bool]) -> tuple[bool, bool]:
    """Fold one ``import ...`` into ``(has_blessed, has_other)``. A bare ``import
    typing`` (no asname) is blessed ONLY when the scanned ``name`` is ``typing``
    itself (the dotted-decorator case); any other binding of ``name`` is other."""
    has_blessed, has_other = blessed
    for alias in node.names:
        if (alias.asname or alias.name.split(".")[0]) != name:
            continue
        if alias.name == "typing" and alias.asname is None and name == "typing":
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _import_bindings(tree: ast.AST, name: str) -> tuple[bool, bool]:
    """``(has_blessed, has_other)`` for bindings of ``name`` from ``typing`` in
    ``tree``. ``has_blessed`` iff a ``from typing import <name>`` (no asname) — for
    ``name == "final"`` — or a bare ``import typing`` — for ``name == "typing"`` —
    is present. ``has_other`` for ANY other import that binds ``name`` (a
    differently-sourced or aliased import), meaning ``name`` may not be the
    ``typing`` one."""
    blessed = (False, False)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            blessed = _fold_importfrom(node, name, blessed)
        elif isinstance(node, ast.Import):
            blessed = _fold_import(node, name, blessed)
    return blessed


class _FinalBinding(NamedTuple):
    """How the module can spell ``typing.final`` provably.

    ``bare_ok``: a bare ``@final`` is provably ``typing.final`` — ``final`` is
    already imported ``from typing`` (no asname) AND nothing shadows the name.
    ``dotted_ok``: a dotted ``@typing.final`` is provable — ``typing`` is imported
    bare AND unshadowed. ``can_add_import``: a fresh ``from typing import final``
    may be added — the name ``final`` is bound by NOTHING today (no import, no
    local shadow), so adding the import introduces no conflict. The decorator is
    addable iff ``bare_ok or dotted_ok or can_add_import``."""

    bare_ok: bool
    dotted_ok: bool
    can_add_import: bool


def _final_binding(tree: ast.AST) -> _FinalBinding:
    """Compute the :class:`_FinalBinding` for a module's ``tree`` — which spelling
    of ``typing.final`` is provable, and whether a fresh import may be added.

    ``final`` is usable bare when ``from typing import final`` is present with no
    asname, nothing else binds ``final``, and no local shadow exists. ``typing`` is
    usable dotted when ``import typing`` is present unshadowed and nothing else
    rebinds it. A fresh ``from typing import final`` is addable only when ``final``
    is bound by nothing at all (no import, no shadow), so the insert is safe."""
    final_blessed, final_other = _import_bindings(tree, "final")
    final_shadow = _shadows_name(tree, "final")
    bare_ok = final_blessed and not final_other and not final_shadow

    typ_blessed, typ_other = _import_bindings(tree, "typing")
    dotted_ok = typ_blessed and not typ_other and not _shadows_name(tree, "typing")

    can_add_import = not final_blessed and not final_other and not final_shadow
    return _FinalBinding(bare_ok=bare_ok, dotted_ok=dotted_ok,
                         can_add_import=can_add_import)


class _ModuleContext(NamedTuple):
    """Per-module facts the finalizability gate needs beyond the class: the
    module's physical source ``lines`` (for the splice), the proven ``binding`` of
    ``typing.final``, and the whole-project ``used_as_base`` over-approximation."""

    lines: list[str]
    binding: _FinalBinding
    used_as_base: set[str]


def _module_context(source: str, scan_sources: list[str]) -> _ModuleContext:
    """Build the :class:`_ModuleContext` for ``source`` whose used-as-base scan
    spans ``scan_sources``. ``source`` must already parse (the caller guards this);
    its ``final``/``typing`` bindings come from its OWN tree."""
    return _ModuleContext(
        lines=source.splitlines(),
        binding=_final_binding(ast.parse(source)),
        used_as_base=_used_as_base_names(scan_sources),
    )


def _is_finalizable(cls: ast.ClassDef, ctx: _ModuleContext) -> bool:
    """True when ``cls`` is a top-level class safe to seal ``@final``.

    Gates (all must hold): no existing ``@final`` decorator; the name is NOT used
    as a base anywhere in the project; ``cls`` is not an abstract base / protocol /
    enum (nor an ``ABCMeta`` metaclass); and ``typing.final`` is provably spellable
    in the module (bare ``@final`` already importable, a dotted ``@typing.final``
    provable, or a fresh ``from typing import final`` safely addable)."""
    if class_has_final_decorator(cls):
        return False
    if cls.name in ctx.used_as_base:
        return False
    if _is_abstract_or_special_base(cls):
        return False
    b = ctx.binding
    return b.bare_ok or b.dotted_ok or b.can_add_import


def _decorator_text(binding: _FinalBinding) -> str:
    """The decorator spelling to emit: bare ``@final`` when ``final`` is (or will
    be) importable from ``typing``, else the dotted ``@typing.final``. Prefers the
    bare form (it pairs with the ``from typing import final`` ensure step); the
    dotted form is used only when ``final`` is shadowed but ``typing`` is bound."""
    if binding.bare_ok or binding.can_add_import:
        return "@final"
    return "@typing.final"


def _class_def_index(cls: ast.ClassDef) -> int:
    """The 0-based line index of ``cls``'s ``class`` header (the line just below
    its decorator list, if any) — where the ``@final`` line is inserted so it sits
    directly above the ``class`` keyword and below any existing decorators."""
    return cls.lineno - 1


def _insert_decorator(lines: list[str], cls: ast.ClassDef, text: str) -> list[str]:
    """Insert the ``@final`` decorator line directly above ``cls``'s ``class``
    header, preserving the header's leading indentation (so a nested-but-top-level
    class — none here, but harmless — keeps its column) and leaving any existing
    decorators in place above it."""
    idx = _class_def_index(cls)
    header = lines[idx]
    indent = header[: len(header) - len(header.lstrip())]
    out = list(lines)
    out.insert(idx, f"{indent}{text}")
    return out


def _needs_import(binding: _FinalBinding) -> bool:
    """True when a fresh ``from typing import final`` must be inserted — the bare
    ``@final`` form was chosen via ``can_add_import`` (not already importable)."""
    return binding.can_add_import and not binding.bare_ok


def _is_single_line_widenable_typing_import(line: str) -> bool:
    """True when ``line`` is a CLEAN single-line ``from typing import a, b`` that the
    string-splitting widen can safely re-emit.

    A clean line carries the import names on ONE physical line with no surrounding
    parentheses (``from typing import (`` opens a multi-LINE block whose names span
    other lines — splitting just the open line would emit ``from typing import (,
    final``), no inline ``#`` comment (it would be swallowed into the re-emitted
    name list), and no backslash continuation. Anything that fails these is widened
    UNSAFELY by the splitter, so it is rejected here and the caller inserts a fresh
    ``from typing import final`` line instead (a second from-import is valid
    Python)."""
    stripped = line.strip()
    if not stripped.startswith("from typing import "):
        return False
    if "(" in stripped or ")" in stripped:
        return False  # parenthesized (likely multi-line) import — not clean
    if "#" in stripped or stripped.endswith("\\"):
        return False  # inline comment or line continuation — not clean
    return True


def _existing_typing_import_index(lines: list[str]) -> int | None:
    """Index of a CLEANLY single-line-widenable top-level ``from typing import ...``
    line, or ``None``.

    Only a clean single-line import (see
    :func:`_is_single_line_widenable_typing_import`) is returned, because the widen
    re-emits the line by string-splitting on ``,`` — a parenthesized/multi-line or
    commented ``from typing import`` cannot be widened that way without corrupting
    the source. When none is clean the caller falls back to inserting a fresh
    ``from typing import final`` line."""
    for i, line in enumerate(lines):
        if _is_single_line_widenable_typing_import(line):
            return i
    return None


def _imported_typing_names(line: str) -> set[str]:
    """The import items a CLEAN single-line ``from typing import a, b as c`` line
    carries — each kept VERBATIM (an ``X as Y`` alias is preserved whole, so the
    re-emit is value-identical), the comma split's empty pieces dropped.

    The caller guarantees ``line`` is a clean single-line import (no parens, no
    inline comment, no continuation — :func:`_is_single_line_widenable_typing_import`),
    so a naive comma split is safe here: there is no ``#`` to swallow and no ``(`` to
    mis-read as a name."""
    return {item.strip() for item in line.split("import", 1)[1].split(",")
            if item.strip()}


def _widen_typing_import(lines: list[str], idx: int) -> list[str]:
    """Add ``final`` to the clean single-line ``from typing import ...`` at ``idx``
    (items kept sorted), preserving the line's leading indentation. ``idx`` is known
    to point at a cleanly-widenable line (the index finder guarantees it)."""
    line = lines[idx]
    indent = line[: len(line) - len(line.lstrip())]
    names = _imported_typing_names(line) | {"final"}
    out = list(lines)
    out[idx] = f"{indent}from typing import " + ", ".join(sorted(names))
    return out


def _insert_fresh_final_import(lines: list[str]) -> list[str]:
    """Insert a fresh ``from typing import final`` line at the canonical spot (after
    the docstring / ``__future__`` imports), keeping a blank line before the code
    that follows. A second ``from typing import`` is valid Python, so this is the
    sound fallback when no existing typing import can be cleanly widened on one
    line (a parenthesized / multi-line / commented import)."""
    insert_at = _import_insertion_index(lines)
    block = ["from typing import final"]
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def _ensure_final_import(lines: list[str]) -> list[str]:
    """Ensure ``from typing import final`` is importable: widen an existing CLEAN
    single-line ``from typing import ...`` in place (only ``final`` added), else
    insert a fresh ``from typing import final`` line at the canonical spot.

    The caller only calls this when a fresh binding is needed (``_needs_import``),
    so an existing ``from typing import final`` — which would make the import
    unnecessary — never reaches here. A parenthesized / multi-line / commented
    typing import is NOT cleanly widenable on one line, so it is left untouched and
    a second ``from typing import final`` line is inserted instead (valid Python) —
    closing the silent-no-op recall gap on the common parenthesized-import file
    without ever corrupting the source."""
    idx = _existing_typing_import_index(lines)
    if idx is not None:
        return _widen_typing_import(lines, idx)
    return _insert_fresh_final_import(lines)


def finalizable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` finalizable when ``source`` is
    considered IN ISOLATION (single-module subclass scan).

    Convenience for tests / single-file reasoning: ``source`` is its own whole
    project, so the used-as-base scan sees only this module. Sorted by source
    order. Returns ``[]`` on a syntax error. The objective's real plan uses the
    WHOLE project, which can only ADD refusals (more base uses), never remove
    them."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    ctx = _module_context(source, [source])
    return [node.name for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_finalizable(node, ctx)]


def _finalizable_class_nodes(
    tree: ast.Module, ctx: _ModuleContext
) -> list[ast.ClassDef]:
    """Every finalizable top-level class node in ``tree``, in source order."""
    return [node for node in tree.body
            if isinstance(node, ast.ClassDef) and _is_finalizable(node, ctx)]


def add_final_decorator(
    source: str, project_sources: list[str] | None = None
) -> str | None:
    """Add ``@typing.final`` to every finalizable top-level class in ``source``, or
    ``None`` when nothing changes.

    ``project_sources`` is the whole-project source set the used-as-base
    over-approximation scans (it MUST include ``source`` itself); when ``None``,
    ``source`` is scanned in isolation (the conservative single-module floor).
    Classes are decorated in REVERSE source order so earlier line spans stay valid,
    then the ``from typing import final`` import is ensured once (only when the bare
    ``@final`` form needs it). Deterministic and idempotent (an already-``@final``
    class is not re-touched); the result is re-``ast.parse``d before return, so a
    malformed rewrite yields ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    scan_sources = [source] if project_sources is None else project_sources
    ctx = _module_context(source, scan_sources)

    nodes = _finalizable_class_nodes(tree, ctx)
    if not nodes:
        return None

    text = _decorator_text(ctx.binding)
    out_lines = list(ctx.lines)
    for cls in sorted(nodes, key=_class_def_index, reverse=True):
        out_lines = _insert_decorator(out_lines, cls, text)
    if _needs_import(ctx.binding):
        out_lines = _ensure_final_import(out_lines)
    return rejoin_guarded(source, out_lines)
