"""Declare a module-level ``__all__`` on a leaf module that lacks one.

The honest gap this closes: a student or team writes a module of public helpers
— ``def load(...)``, ``class Engine: ...``, ``TIMEOUT = 30`` — but never declares
``__all__``. Without it, ``from module import *`` falls back to its DEFAULT
behaviour: it imports *every* module-level name that does not start with ``_``.
That default set is implicit and silently widens every time a new public name (or
a re-exported import) is added. ``add_module_all`` LANDS an EXPLICIT
``__all__ = [...]`` pinned to EXACTLY that current default set — deterministically,
for free, no LLM.

Why this is behaviour-IDENTICAL (the soundness core): ``__all__`` is consulted by
ONE thing only — ``from module import *``. Direct ``import module`` and
``from module import name`` never look at it. When NO ``__all__`` exists, the
star-import set is precisely "every module-level bound name not starting with
``_``". So computing ``__all__`` as that SAME set changes nothing: ``import *``
imports the identical names; everything else is untouched. This is the leaf-module
sibling of wire-exports (which writes a PACKAGE ``__init__`` re-export surface);
here we declare the public surface a module DEFINES directly.

The public set is computed from the AST and is the union of every module-level
name bound by a ``def`` / ``async def`` / ``class``, a plain ``Assign`` /
``AnnAssign``-WITH-a-value target, or an ``import`` / ``from ... import`` binding —
that does NOT start with ``_``. Sorted (deterministic), inserted after the module
docstring + the ``__future__`` / import block (the canonical spot, reusing
``_import_insertion_index``).

It REFUSES (returns ``None`` — an honest no-op, lands nothing) whenever the static
public set cannot be PROVEN equal to the runtime star-import set, or the change
would be noise:

  - the module already declares ``__all__`` (idempotent — a second run is a
    byte-identical no-op);
  - the module has a ``from x import *`` ANYWHERE — the star binds names we cannot
    enumerate from the AST, so the default public set is unknowable statically
    (mirrors ``unused_imports._has_star_import``); land nothing;
  - the module contains a walrus ``:=`` (``ast.NamedExpr``) ANYWHERE — a walrus
    binds its target in the enclosing scope, so a module-level walrus (even inside
    a comprehension, which by PEP 572 leaks the name to module scope) binds a
    public name we do not model; refuse the whole module (``has_walrus``);
  - the module has NO public module-level names — an empty ``__all__`` is pure
    noise;
  - a module-level binding construct we do not model exactly could leak a public
    name into the runtime star set (a top-level ``for`` / ``while`` / ``with`` /
    ``if`` / ``try`` that binds a public name, a tuple/starred unpacking,
    ``global``/``nonlocal`` at module scope) — over-approximate and REFUSE the
    whole module rather than emit a set that might differ from the default;
  - the source does not parse (never rewrite broken Python).

The result is re-``ast.parse``d before it is returned (via ``rejoin_guarded``), so
a malformed splice is dropped rather than landed. Deterministic (pure AST walk +
line splice, no clock/random), stdlib-only, zero-token, idempotent. Reuses
:mod:`app.execution.dataclass_rewrite` helpers ``_import_insertion_index`` (so the
``__all__`` lands in exactly the canonical import spot) and ``rejoin_guarded`` (the
shared "splice, preserve trailing newline, re-parse guard" epilogue).
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded

__all__ = [
    "public_star_names",
    "has_module_all",
    "has_star_import",
    "has_walrus",
    "add_module_all",
]


def _is_public(name: str) -> bool:
    """A name is part of the default star surface iff it is non-empty and does
    not start with ``_`` (dunders and single-underscore privates both excluded)."""
    return bool(name) and not name.startswith("_")


def _all_name_targets(node: ast.stmt) -> list[ast.expr]:
    """The assignment-target expressions of one top-level ``Assign``/``AnnAssign``.

    An ``AnnAssign`` WITHOUT a value (``x: int``) binds nothing at runtime, so it
    is NOT a star-set member and contributes no target here. An ``Assign`` may
    have several targets (``a = b = 1``); each is returned for inspection."""
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [node.target]
    return []


def _simple_bound_names(targets: list[ast.expr]) -> list[str] | None:
    """The plain ``Name`` ids of assignment ``targets``, or ``None`` when ANY
    target is not a bare ``Name`` (tuple/list/starred unpacking, an attribute or
    subscript target). ``None`` signals an unmodelled binder the caller must
    REFUSE on — we never half-enumerate a complex target."""
    names: list[str] = []
    for target in targets:
        if not isinstance(target, ast.Name):
            return None
        names.append(target.id)
    return names


def has_module_all(source: str) -> bool:
    """True when ``source`` already assigns a top-level ``__all__`` (any form —
    a literal list, a tuple, or a computed expression). ``False`` on a syntax
    error. A module that already declares ``__all__`` is left untouched."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return True
        if isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ) and node.target.id == "__all__":
            return True
    return False


def has_star_import(source: str) -> bool:
    """True when ``source`` does ``from x import *`` ANYWHERE (any scope).

    A star import binds names we cannot enumerate statically, so the module's
    default public set is unknowable from the AST — the whole module is refused
    (mirrors :func:`app.execution.unused_imports._has_star_import`). ``False`` on
    a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "*" for alias in node.names
        ):
            return True
    return False


def has_walrus(source: str) -> bool:
    """True when ``source`` contains a walrus ``:=`` (``ast.NamedExpr``) ANYWHERE.

    A walrus binds its target in the ENCLOSING scope, not the comprehension's — so
    a module-level walrus (``RESULT = (computed := 41)``, a bare ``(cache := {})``,
    a default ``X: int = (Y := 5)``, a ``@(deco := f)`` decorator, or even a
    comprehension ``[y := i for i in range(3)]`` which by PEP 572 leaks ``y`` to
    module scope) binds a real module-level name that ``from m import *`` would
    export. We do NOT model which walrus targets reach module scope, so the
    presence of ANY walrus is a conservative whole-module refusal — the computed
    ``__all__`` must never OMIT a name the default star set carries. ``False`` on a
    syntax error. (Walks the whole tree, mirroring :func:`has_star_import`.)"""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    return any(isinstance(node, ast.NamedExpr) for node in ast.walk(tree))


def _names_from_definition(node: ast.stmt) -> list[str]:
    """The single bound name a top-level ``def``/``async def``/``class`` defines."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    return []


def _names_from_import(node: ast.stmt) -> list[str]:
    """The local names a top-level ``import``/``from ... import`` binds.

    ``import a.b.c`` binds ``a``; ``import a.b as c`` binds ``c``;
    ``from x import y as z`` binds ``z``. A ``from x import *`` is handled by the
    caller's whole-module refusal, never reached as a bound name here."""
    if not isinstance(node, (ast.Import, ast.ImportFrom)):
        return []
    return [(alias.asname or alias.name).split(".")[0] for alias in node.names]


def _is_inert_top_level(node: ast.stmt) -> bool:
    """True for a top-level statement that BINDS NO module-level name — safe to
    ignore (it cannot add to or remove from the default star set).

    Inert: a bare expression statement (docstring, a call), ``pass``, ``import``
    machinery already counted by the caller, an ``AnnAssign`` with no value
    (binds nothing), or an ``assert``. A top-level ``del`` is deliberately NOT
    inert: ``ast.Delete`` is absent from the tuple below, so a ``del`` REFUSES the
    whole module (it can REMOVE a name from the default star set — over-approximate
    rather than emit an ``__all__`` listing a name ``del`` later unbinds). Anything
    NOT inert and NOT a modelled binder is an UNMODELLED binder → the caller
    refuses the whole module."""
    if isinstance(node, (ast.Expr, ast.Pass, ast.Assert, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.AnnAssign) and node.value is None:
        return True
    return False


def _collect_top_level_names(tree: ast.Module) -> list[str] | None:
    """Every module-level bound name in ``tree`` (defs/classes/imports/simple
    assignments), in source order, or ``None`` when an UNMODELLED binder is
    present.

    ``None`` is the conservative over-approximate refusal: a top-level
    ``for``/``while``/``with``/``if``/``try`` (or any binder whose runtime names
    we do not enumerate exactly, including tuple/starred/attribute assignment
    targets) could leak a public name into the runtime star set, so the WHOLE
    module is refused rather than emit a possibly-divergent set. (A walrus, which
    can leak a target from inside an expression, is caught separately by the
    whole-tree :func:`has_walrus` scan in :func:`public_star_names`.)"""
    names: list[str] = []
    for node in tree.body:
        definition = _names_from_definition(node)
        if definition:
            names.extend(definition)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(_names_from_import(node))
            continue
        targets = _all_name_targets(node)
        if targets:
            bound = _simple_bound_names(targets)
            if bound is None:
                return None  # unmodelled assignment target — refuse the module
            names.extend(bound)
            continue
        if not _is_inert_top_level(node):
            return None  # an unmodelled binder (control flow, walrus, ...) — refuse
    return names


def public_star_names(source: str) -> list[str] | None:
    """The sorted PUBLIC default-star-import set of ``source``, or ``None``.

    The set is every module-level bound name not starting with ``_``, computed
    from the modelled top-level binders (defs/classes, simple assignments,
    imports). ``None`` is an honest refusal: the source does not parse, it has a
    ``from x import *`` (the star set is unknowable), it contains a walrus ``:=``
    (which binds a module-level name we do not model — see :func:`has_walrus`), or
    it contains an unmodelled top-level binder (control flow / complex unpacking)
    whose runtime names we cannot prove. ``__all__`` itself is excluded from the
    set. The result is sorted and de-duplicated, so it is deterministic."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    if has_star_import(source):
        return None  # star import — default public set is unknowable statically
    if has_walrus(source):
        return None  # a walrus binds a module-level name we do not model — refuse
    collected = _collect_top_level_names(tree)
    if collected is None:
        return None  # an unmodelled binder is present — refuse the whole module
    public = {name for name in collected if _is_public(name) and name != "__all__"}
    return sorted(public)


def _render_all_block(names: list[str]) -> list[str]:
    """The source lines of an ``__all__ = [ ... ]`` declaration for ``names``,
    one quoted name per line (multi-line, the same shape wire-exports emits)."""
    block = ["__all__ = ["]
    block.extend(f'    "{name}",' for name in names)
    block.append("]")
    return block


def _insert_all_block(lines: list[str], names: list[str]) -> list[str]:
    """Splice an ``__all__`` block at the canonical import spot — after a module
    docstring and the ``__future__``/import block, before the first other
    statement — keeping a blank line before any code that follows."""
    insert_at = _import_insertion_index(lines)
    block = _render_all_block(names)
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def add_module_all(source: str) -> str | None:
    """Add a module-level ``__all__`` pinned to ``source``'s default star set, or
    ``None`` when nothing changes.

    Returns ``None`` — an honest no-op — when the module already declares
    ``__all__`` (idempotent), has a ``from x import *`` (the public set is
    unknowable), contains a walrus ``:=`` (which binds an unmodelled module-level
    name), has no public module-level names (an empty ``__all__`` is noise),
    contains an unmodelled top-level binder (the set cannot be proven), or does
    not parse. Otherwise inserts ``__all__ = [...]`` at the canonical spot.
    Behaviour-identical (only ``from module import *`` consults ``__all__`` and the
    set equals the current default). Deterministic and idempotent; the result is
    re-``ast.parse``d before return so a malformed rewrite is dropped, not landed."""
    if has_module_all(source):
        return None  # already declared — idempotent no-op
    names = public_star_names(source)
    if not names:
        return None  # refused (unparseable / star / unmodelled) or no public names
    lines = source.splitlines()
    out_lines = _insert_all_block(lines, names)
    return rejoin_guarded(source, out_lines)
