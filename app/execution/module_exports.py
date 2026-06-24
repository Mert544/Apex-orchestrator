"""Declare a module-level ``__all__`` of the names a leaf module DEFINES.

The honest gap this closes: a student or team writes a module of public helpers
— ``def load(...)``, ``class Engine: ...``, ``TIMEOUT = 30`` — but never declares
``__all__``. Without it, ``from module import *`` falls back to its DEFAULT
behaviour: it imports *every* module-level name that does not start with ``_``,
which silently includes the module's IMPORTED publics (``re``, ``os``,
``annotations`` from ``from __future__ import annotations``, ``log`` from
``from math import log``). A maintainer never wants those re-exported. So v2
emits the IDIOMATIC ``__all__``: the sorted PUBLIC names the module DEFINES
LOCALLY (top-level ``def`` / ``async def`` / ``class`` / simple ``Assign`` /
``AnnAssign``-with-value), EXCLUDING every imported name and ``__all__`` itself.

Why this stays behaviour-PROVING (the soundness core): ``__all__`` is consulted
by ONE thing only — ``from module import *``. Direct ``import module`` and
``from module import name`` never look at it. The DEFAULT star set is "every
module-level bound public name", which is ``defined_publics | imported_publics``.
Emitting ``defined_publics`` alone DROPS ``imported_publics`` from the star set.

  - When ``imported_publics`` is EMPTY, the emitted set EQUALS the default star
    set → behaviour-IDENTICAL → SAFE. Land it (subject to the refusals below).
  - When ``imported_publics`` is NON-EMPTY, emitting defined-only SHRINKS the
    star set, which is only observable through a ``from <thismodule> import *``.
    So we scan the WHOLE project (tests-INCLUSIVE, via
    :func:`app.execution.freeze_dataclass.all_module_sources`, the same
    over-approximate whole-project scan add-final / seal-final-method use) for
    ANY star import that COULD resolve to this module. If NONE exists, no
    consumer can observe the shrink → provably behaviour-identical project-wide
    → SAFE, land it. If ANY potential consumer exists → REFUSE (honest no-op):
    we cannot prove the consumer doesn't bind a dropped imported name.

The defined-public set is computed from the AST: every module-level name bound by
a ``def`` / ``async def`` / ``class``, or a plain ``Assign`` / ``AnnAssign``-WITH-
a-value target, that does NOT start with ``_``. Sorted (deterministic), inserted
AFTER a leading shebang and PEP-263 coding line, ANY leading comment / license
header, the module docstring, and the leading ``__future__`` imports — and BEFORE
the first real statement (see :func:`_safe_insertion_index`, which is AST-based so
``module.__doc__`` is always preserved even when a comment header precedes the
docstring).

It REFUSES (returns ``None`` — an honest no-op, lands nothing) whenever the change
cannot be PROVEN safe or would be noise:

  - the module already declares ``__all__`` (idempotent — a second run is a
    byte-identical no-op);
  - the module has a ``from x import *`` ANYWHERE — the star binds names we cannot
    enumerate from the AST, so the default public set is unknowable statically;
  - the module contains a walrus ``:=`` (``ast.NamedExpr``) ANYWHERE — a walrus
    binds its target in the enclosing scope, so a module-level walrus (even inside
    a comprehension, which by PEP 572 leaks the name to module scope) binds a
    public name we do not model; refuse the whole module;
  - the module DEFINES no public name — an empty ``__all__`` is pure noise;
  - a module-level binding construct we do not model exactly could leak a public
    name (a top-level ``for`` / ``while`` / ``with`` / ``if`` / ``try`` binding a
    public name, a tuple/starred unpacking, a top-level ``del``) — over-
    approximate and REFUSE the whole module;
  - excluding imports would shrink the star set AND a star-import consumer of this
    module exists project-wide (the soundness refusal above);
  - the source does not parse (never rewrite broken Python).

The result is re-``ast.parse``d before it is returned (via ``rejoin_guarded``), so
a malformed splice is dropped rather than landed. Deterministic (pure AST walk +
line splice, no clock/random), stdlib-only, zero-token, idempotent. Reuses
:mod:`app.execution.dataclass_rewrite` helpers ``_import_insertion_index`` (wrapped
LOCALLY by :func:`_line_based_insertion_index`, the parse-failure fallback for
:func:`_safe_insertion_index`, never modified) and ``rejoin_guarded``, and
:func:`app.execution.freeze_dataclass.all_module_sources` for the whole-project
star-consumer scan.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import _import_insertion_index, rejoin_guarded

__all__ = [
    "defined_public_names",
    "imported_public_names",
    "public_star_names",
    "has_module_all",
    "has_star_import",
    "has_walrus",
    "module_dotted_targets",
    "project_has_star_consumer",
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
    """True for a top-level statement that BINDS NO new defined module-level name
    we must model — safe to ignore for the DEFINED-public scan.

    Inert: a bare expression statement (docstring, a call), ``pass``, an
    ``AnnAssign`` with no value (binds nothing), an ``assert``, or any
    ``import``/``from ... import`` (imports never contribute a DEFINED name in v2 —
    they are scanned separately by :func:`imported_public_names`). A top-level
    ``del`` is deliberately NOT inert: ``ast.Delete`` is absent from the tuple
    below, so a ``del`` REFUSES the whole module (it can REMOVE a name from the
    default star set — over-approximate rather than emit an ``__all__`` listing a
    name ``del`` later unbinds). Anything NOT inert and NOT a modelled definition
    is an UNMODELLED binder → the caller refuses the whole module."""
    if isinstance(node, (ast.Expr, ast.Pass, ast.Assert, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.AnnAssign) and node.value is None:
        return True
    return False


def _collect_defined_names(tree: ast.Module) -> list[str] | None:
    """Every module-level name DEFINED LOCALLY in ``tree`` — defs/classes and
    simple assignments, EXCLUDING imports — in source order, or ``None`` when an
    UNMODELLED binder is present.

    ``None`` is the conservative over-approximate refusal: a top-level
    ``for``/``while``/``with``/``if``/``try`` (or any binder whose runtime names
    we do not enumerate exactly, including tuple/starred/attribute assignment
    targets, and a ``del``) could leak or remove a public name, so the WHOLE
    module is refused rather than emit a possibly-divergent set. Imports bind no
    DEFINED name (they are inert here) and are enumerated separately by
    :func:`imported_public_names`. (A walrus is caught separately by the whole-tree
    :func:`has_walrus` scan in :func:`public_star_names`.)"""
    names: list[str] = []
    for node in tree.body:
        definition = _names_from_definition(node)
        if definition:
            names.extend(definition)
            continue
        targets = _all_name_targets(node)
        if targets:
            bound = _simple_bound_names(targets)
            if bound is None:
                return None  # unmodelled assignment target — refuse the module
            names.extend(bound)
            continue
        if not _is_inert_top_level(node):
            return None  # an unmodelled binder (control flow, del, ...) — refuse
    return names


def imported_public_names(source: str) -> set[str]:
    """The PUBLIC names ``source`` binds via a top-level ``import`` /
    ``from ... import`` (``_``-excluded, ``__all__`` never an import target).

    These are exactly the names the DEFAULT star set leaks but the idiomatic v2
    ``__all__`` DROPS. Empty when the module imports nothing public — in which case
    the v2 set equals the default star set and the change is behaviour-identical
    with no project scan needed. ``set()`` on a syntax error / star import."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return set()
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(_names_from_import(node))
    return {name for name in imported if _is_public(name)}


def defined_public_names(source: str) -> list[str] | None:
    """The sorted PUBLIC names ``source`` DEFINES LOCALLY (defs/classes/simple
    assignments), EXCLUDING all imports and ``__all__`` itself, or ``None``.

    This is the v2 ``__all__`` payload — the idiomatic "API this module DEFINES",
    not the accidental star-leak of its imports. ``None`` is an honest refusal: the
    source does not parse, it has a ``from x import *``, it contains a walrus, or it
    has an unmodelled top-level binder whose runtime names we cannot prove. Sorted
    and de-duplicated, so it is deterministic. An EMPTY list means the module
    defines no public name (the caller treats that as noise and refuses)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    if has_star_import(source):
        return None  # star import — default public set is unknowable statically
    if has_walrus(source):
        return None  # a walrus binds a module-level name we do not model — refuse
    collected = _collect_defined_names(tree)
    if collected is None:
        return None  # an unmodelled binder is present — refuse the whole module
    public = {name for name in collected if _is_public(name) and name != "__all__"}
    return sorted(public)


def public_star_names(source: str) -> list[str] | None:
    """The sorted v2 ``__all__`` payload for ``source`` — its DEFINED public names,
    excluding imports — or ``None`` on a refusal.

    Thin alias of :func:`defined_public_names`, kept as the module's historical
    public entry point. (v1 returned the full default star set INCLUDING imported
    publics; v2 returns the defined-only set, the idiomatic public API.) The
    soundness of dropping imported publics is enforced by the whole-project scan in
    :func:`add_module_all`, not here — this is the pure name computation."""
    return defined_public_names(source)


def module_dotted_targets(module_rel: str) -> set[str]:
    """The dotted import paths an ABSOLUTE ``from <target> import *`` could use to
    name the module at ``module_rel``.

    A regular ``pkg/sub/mod.py`` is imported as ``pkg.sub.mod`` (one target). A
    package's own ``pkg/sub/__init__.py`` is imported as ``pkg.sub`` — but a
    consumer may ALSO spell it ``pkg.sub.__init__`` (a legal, if unusual, import),
    so BOTH dotted forms are returned for the ``__init__`` case. Over-approximating
    here only ADDS potential observers (more refusals), never misses one. Returns
    an empty set for a non-``.py`` path (never matched)."""
    rel = module_rel.replace("\\", "/")
    if not rel.endswith(".py"):
        return set()
    stem = rel[:-3]
    parts = stem.split("/")
    if parts and parts[-1] == "__init__":
        package = ".".join(parts[:-1])
        targets = {".".join(parts)}  # the explicit ``pkg.sub.__init__`` spelling
        if package:
            targets.add(package)  # the canonical ``pkg.sub`` spelling
        return targets
    return {".".join(parts)}


def _is_star_import(node: ast.AST) -> bool:
    """True for a ``from ... import *`` node (any level)."""
    return isinstance(node, ast.ImportFrom) and any(
        alias.name == "*" for alias in node.names
    )


def _source_observes_star(source: str, targets: set[str]) -> bool:
    """True when ``source`` contains a ``from ... import *`` that COULD resolve to
    a module named by one of ``targets``.

    Two observer shapes (both over-approximated toward MORE refusals — soundness
    over recall):

      - an ABSOLUTE ``from <t> import *`` whose ``node.module`` is in ``targets``
        (``node.level == 0``) — a definite observer of this module's star set;
      - ANY RELATIVE star import (``node.level >= 1``: ``from . import *``,
        ``from .name import *``, ``from .. import *``). We cannot resolve a
        relative target from source text alone WITHOUT the importer's package
        position, so — exactly as the spec's "treat ANY ``import *`` you cannot
        PROVE targets a different module as a potential observer" — we treat every
        relative star import as a potential observer. This can only OVER-refuse
        (an honest no-op), never miss the real consumer.

    ``False`` on a syntax error (a module that does not parse cannot be proven to
    observe, but it also cannot be IMPORTED to observe at runtime — and the scan is
    only a gate that ADDS refusals; the source under rewrite is itself re-parsed
    separately)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    for node in ast.walk(tree):
        if not _is_star_import(node):
            continue
        if node.level >= 1:  # type: ignore[attr-defined]
            return True  # an unresolved relative star import — potential observer
        if node.module in targets:  # type: ignore[attr-defined]
            return True  # an absolute star import naming this module
    return False


def project_has_star_consumer(sources: list[str], targets: set[str]) -> bool:
    """True when ANY source in ``sources`` (the whole-project, tests-INCLUSIVE set)
    contains a ``from ... import *`` that could observe a module named by
    ``targets`` — see :func:`_source_observes_star`.

    The same over-approximate whole-project scan add-final's used-as-base and
    seal-final-method's transitive-subclass scans use: when it says ``True`` a
    consumer MIGHT exist, so dropping imported publics from the star set cannot be
    proven safe → refuse. When it says ``False`` NO consumer exists anywhere → the
    shrink is provably unobservable project-wide → safe."""
    return any(_source_observes_star(src, targets) for src in sources)


def _render_all_block(names: list[str]) -> list[str]:
    """The source lines of an ``__all__ = [ ... ]`` declaration for ``names``,
    one quoted name per line (multi-line, the same shape wire-exports emits)."""
    block = ["__all__ = ["]
    block.extend(f'    "{name}",' for name in names)
    block.append("]")
    return block


def _is_coding_line(line: str) -> bool:
    """True for a PEP-263 source-encoding declaration comment (``# -*- coding:
    utf-8 -*-`` or the bare ``# coding: utf-8`` / ``# coding=utf-8`` form).

    PEP 263 only honours such a line on physical line 1 or 2, so the caller checks
    it only at those positions. Matched by the comment shape (a ``#`` line that
    mentions ``coding`` followed by ``:`` or ``=``) without a regex, so a normal
    comment that merely contains the word ``coding`` in prose is NOT mistaken for
    an encoding line."""
    stripped = line.strip()
    if not stripped.startswith("#"):
        return False
    body = stripped[1:].strip()
    return body.startswith(("coding:", "coding=", "-*-")) and "coding" in body


def _prologue_length(lines: list[str]) -> int:
    """The count of leading shebang / PEP-263 coding lines that MUST stay at the
    top of the file: a ``#!`` shebang on physical line 1, then a PEP-263 coding
    line on line 1 or 2. Returns 0, 1, or 2 — these lines have special meaning ONLY
    at the very top, so each is recognised only at its sanctioned position."""
    prologue = 0
    if prologue < len(lines) and lines[prologue].startswith("#!"):
        prologue += 1  # a shebang only counts on physical line 1
    if prologue < len(lines) and prologue <= 1 and _is_coding_line(lines[prologue]):
        prologue += 1  # a PEP-263 coding line only counts on line 1 or 2
    return prologue


def _line_based_insertion_index(lines: list[str]) -> int:
    """The pre-AST line-based spot — the shared ``_import_insertion_index`` run
    RELATIVE TO and never above a leading shebang / PEP-263 coding line.

    Wraps (never modifies) the shared ``_import_insertion_index`` another engineer
    owns: a leading ``#!`` shebang (physical line 1) and a PEP-263 coding line
    (line 1 or 2) MUST stay at the top of the file. ``_import_insertion_index`` does
    not know about them — given a shebang on line 1 it returns 0 (the shebang is
    neither blank nor a docstring quote), so the block would land ABOVE required
    line-1/2 content. We therefore run it on the lines BELOW the prologue and add
    the prologue length back. Used ONLY as the fallback when the source fails to
    parse (:func:`_safe_insertion_index` is AST-based on parseable source)."""
    prologue = _prologue_length(lines)
    if prologue == 0:
        return _import_insertion_index(lines)  # byte-identical to the bare helper
    return prologue + _import_insertion_index(lines[prologue:])


def _is_docstring_node(node: ast.stmt) -> bool:
    """True when ``node`` is a module-docstring expression — a bare ``Expr`` whose
    value is a string ``Constant`` (the same shape ``ast.get_docstring`` reads)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_future_import(node: ast.stmt) -> bool:
    """True for a ``from __future__ import ...`` statement (a leading ``__future__``
    import is skipped over so ``__all__`` lands after it, matching v1's spot)."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _docstring_end_index(body: list[ast.stmt], prologue: int) -> int:
    """The 0-based line index just PAST the module docstring, or ``prologue`` when
    the module has no docstring.

    ``body[0].end_lineno`` is the docstring's last physical line (1-based), which is
    exactly the 0-based index of the line AFTER it. Robust to any leading comment /
    license header before the docstring — the comments are not AST statements, so
    ``body[0]`` is still the docstring node. (Fix for the shipped-v2 defect where a
    comment header before the docstring made ``_import_insertion_index`` return 0 —
    placing ``__all__`` above the docstring and nulling ``module.__doc__``.)"""
    if body and _is_docstring_node(body[0]):
        return body[0].end_lineno or prologue  # type: ignore[attr-defined]
    return prologue


def _future_end_index(body: list[ast.stmt]) -> int:
    """The 0-based line index just past the LAST leading ``from __future__`` import
    (those that lead the body, after any docstring), or 0 when there are none.

    Only ``__future__`` imports are stepped over — regular ``import``/``from`` are
    NOT, so ``__all__`` keeps landing BEFORE them, byte-identical to v1's canonical
    spot. The scan stops at the first non-docstring, non-``__future__`` statement."""
    end = 0
    for node in body:
        if _is_docstring_node(node):
            continue
        if _is_future_import(node):
            end = max(end, node.end_lineno or end)  # type: ignore[attr-defined]
            continue
        break  # the first real statement ends the leading __future__ run
    return end


def _first_code_line_index(body: list[ast.stmt], prologue: int) -> int:
    """The 0-based line index of the first statement that is NOT the docstring and
    NOT a leading ``__future__`` import — the ceiling ``__all__`` must not cross.

    Returns ``prologue`` when there is no such statement (an empty / docstring-only /
    ``__future__``-only module), so the caller never advances into nothing."""
    for node in body:
        if _is_docstring_node(node) or _is_future_import(node):
            continue
        return (node.lineno or prologue) - 1  # type: ignore[attr-defined]
    return prologue


def _skip_header_filler(lines: list[str], start: int, ceiling: int) -> int:
    """Advance ``start`` past blank lines and standalone ``#`` comment lines up to
    (never reaching) ``ceiling`` — so ``__all__`` lands right before the first real
    statement, after any trailing header comments / blanks. Pure index walk."""
    index = start
    while index < ceiling and (
        not lines[index].strip() or lines[index].lstrip().startswith("#")
    ):
        index += 1
    return index


def _safe_insertion_index(lines: list[str]) -> int:
    """Where the ``__all__`` block may land — AFTER any shebang / PEP-263 coding
    line, the module docstring, and the leading ``from __future__`` imports, and
    BEFORE the first real statement, regardless of a leading comment / license
    header above the docstring.

    AST-based (the fix for the shipped-v2 residual defect): the pre-AST line walk
    skipped a shebang + coding line but NOT a general leading comment block, so a
    ``# license`` header before the docstring made ``_import_insertion_index``
    return 0 — splicing ``__all__`` as the module's FIRST statement and nulling
    ``module.__doc__``. We instead parse the source and read the docstring's
    ``end_lineno`` directly (comments are not statements, so the docstring is still
    located), take the max of the prologue, the docstring end, and the last leading
    ``__future__`` import end, then skip trailing header filler up to the first
    real statement. The result never sits above the prologue and never crosses into
    code. Falls back to the line-based spot ONLY when the source fails to parse
    (never rewrite broken Python). Deterministic and idempotent."""
    prologue = _prologue_length(lines)
    try:
        body = ast.parse("\n".join(lines)).body
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return _line_based_insertion_index(lines)  # unparseable — line-based floor
    anchor = max(prologue, _docstring_end_index(body, prologue), _future_end_index(body))
    return _skip_header_filler(lines, anchor, _first_code_line_index(body, prologue))


def _insert_all_block(lines: list[str], names: list[str]) -> list[str]:
    """Splice an ``__all__`` block at the safe import spot — after any shebang /
    PEP-263 coding line, the module docstring, and the ``__future__``/import block,
    before the first other statement — keeping a blank line before following code."""
    insert_at = _safe_insertion_index(lines)
    block = _render_all_block(names)
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def add_module_all(
    source: str,
    *,
    module_rel: str | None = None,
    project_sources: list[str] | None = None,
) -> str | None:
    """Add a module-level ``__all__`` of ``source``'s DEFINED public names, or
    ``None`` when nothing changes or the change cannot be PROVEN safe.

    The emitted set is the sorted public names the module DEFINES locally,
    EXCLUDING all imports (the idiomatic public API). Because excluding imports can
    SHRINK the ``from module import *`` star set, the change is landed only when
    provably behaviour-identical project-wide:

      - ``imported_publics`` EMPTY → the set already equals the default star set →
        behaviour-identical → safe;
      - ``imported_publics`` NON-EMPTY → safe ONLY when NO ``from <thismodule>
        import *`` consumer exists anywhere in the project. ``module_rel`` +
        ``project_sources`` supply the whole-project (tests-INCLUSIVE) scan set; if
        a potential star consumer exists, REFUSE. When ``module_rel`` is ``None``
        (single-source reasoning / tests with no project shape) and there ARE
        imported publics, the conservative floor scans ``source`` ITSELF for a
        star consumer — and refuses if it cannot otherwise prove the project is
        clean.

    Returns ``None`` — an honest no-op — when the module already declares
    ``__all__`` (idempotent), has a ``from x import *``, contains a walrus, DEFINES
    no public name (an empty ``__all__`` is noise), has an unmodelled top-level
    binder, the soundness scan finds a star consumer of a shrunk set, or does not
    parse. Otherwise inserts ``__all__ = [...]`` at the safe spot (after any
    shebang / PEP-263 coding line + docstring + imports). Deterministic and
    idempotent; the result is re-``ast.parse``d before return so a malformed
    rewrite is dropped, not landed."""
    if has_module_all(source):
        return None  # already declared — idempotent no-op
    names = defined_public_names(source)
    if not names:
        return None  # refused (unparseable / star / walrus / unmodelled) or empty
    imported = imported_public_names(source)
    if imported and not _shrink_is_safe(source, module_rel, project_sources):
        return None  # excluding imports shrinks the star set AND a consumer exists
    lines = source.splitlines()
    out_lines = _insert_all_block(lines, names)
    return rejoin_guarded(source, out_lines)


def _shrink_is_safe(
    source: str, module_rel: str | None, project_sources: list[str] | None
) -> bool:
    """Whether dropping imported publics from the star set is PROVABLY unobservable.

    Called only when ``imported_publics`` is non-empty (the set really shrinks). It
    is safe iff NO ``from <thismodule> import *`` consumer exists in the
    whole-project scan set. ``targets`` is this module's dotted import path(s);
    when ``module_rel`` is unknown we cannot build an absolute target, so we fall
    back to scanning for ANY relative star import (the conservative floor) in the
    given sources (or ``source`` itself), refusing on any potential observer."""
    targets = module_dotted_targets(module_rel) if module_rel else set()
    sources = project_sources if project_sources is not None else [source]
    return not project_has_star_consumer(sources, targets)
