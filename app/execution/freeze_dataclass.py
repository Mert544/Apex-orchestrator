"""Add ``frozen=True`` to a project's own ``@dataclass`` whose fields are NEVER
mutated anywhere in the project's own source.

A frozen dataclass is immutable and hashable: ``@dataclass(frozen=True)`` makes
every field read-only after construction (assigning to one raises
``FrozenInstanceError``) and gives the class a ``__hash__``. When a dataclass's
fields are only ever READ — never assigned, augmented, deleted, or ``setattr``-ed
— freezing it is a behaviour-preserving modernization: a linter only FLAGS the
opportunity, but :func:`freeze_dataclass_decorator` WRITES it, deterministically
and for free.

SOUNDNESS — the whole point. A green suite ALONE is insufficient here: an
*untested* mutation path would stay green yet raise ``FrozenInstanceError`` at
runtime once the class is frozen. So this engine STATICALLY OVER-APPROXIMATES
mutation across the WHOLE project and refuses conservatively. The freeze is
proposed ONLY when ALL of these hold (otherwise an honest no-op):

  - the class is decorated ``@dataclass`` / ``@dataclasses.dataclass`` (bare or
    called) with NO ``frozen=`` keyword already present (idempotent: a second run
    sees ``frozen=True`` and is a byte-identical no-op);
  - the class has NO base classes other than ``object`` — a frozen dataclass may
    not inherit from (nor be inherited by) a non-frozen one;
  - the class's NAME is NOT used as a base anywhere in the project — subclassing
    a now-frozen dataclass with a non-frozen one is a ``TypeError`` at
    class-definition time. A simple ``Name`` base, a dotted ``Attribute`` base
    (``pkg.C``, matched by its final ``.attr``), AND a subscripted base
    (``class Sub(C[int])`` / ``pkg.C[int]``, matched by the subscript's head name)
    all count, so a generic-subscript subclass is caught too — a conservative
    over-approximation that may refuse an unrelated same-named class (soundness
    over recall);
  - NONE of the class's field NAMES appears as an attribute STORE TARGET anywhere
    in the project's own source — the conservative whole-project over-approximation
    covering ``<expr>.<field> = ...`` (``ast.Attribute`` in ``Store`` context),
    augmented ``<expr>.<field> += ...``, ``del <expr>.<field>``, and
    ``setattr(<expr>, "<field>", ...)``. This is intentionally over-conservative —
    a same-named attribute on an UNRELATED object causes a false-positive REFUSE
    (soundness over recall). It also automatically catches a mutating
    ``__post_init__`` (``self.<field> = ...``);
  - the class actually has >= 1 field (a class-body ``AnnAssign`` that is not a
    ``ClassVar``).

The mutated-field-name scan (:func:`mutated_attribute_names`) is a clean, reusable
whole-project over-approximation — a future ``add-slots`` objective (``__slots__``
also requires no never-mutated-field violations) reuses it unchanged.

The rewrite edits the decorator ONLY — ``@dataclass`` -> ``@dataclass(frozen=True)``,
``@dataclass()`` -> ``@dataclass(frozen=True)``, ``@dataclass(eq=True)`` ->
``@dataclass(eq=True, frozen=True)`` — by re-emitting the decorator expression and
splicing its line span. The result is re-``ast.parse``d before it is returned, so
a malformed rewrite is dropped rather than landed. Deterministic (pure AST walk +
line splice, no clock/random), stdlib-only, zero-token, idempotent.

Reuses :func:`app.execution.dataclass_rewrite.rejoin_guarded` for the shared
"splice, preserve the trailing newline, re-``ast.parse`` guard" epilogue and
``_node_line_span`` for the decorator's line slice.
"""

from __future__ import annotations

import ast
import io
import tokenize
from typing import NamedTuple

from app.execution.dataclass_rewrite import _node_line_span, rejoin_guarded

__all__ = [
    "freeze_dataclass_decorator",
    "freezable_classes",
    "mutated_attribute_names",
    "dataclass_field_names",
    "is_frozen_dataclass_decorator",
    "project_sources",
    "all_module_sources",
]


def _decorator_func(dec: ast.expr) -> ast.expr:
    """The CALLABLE part of a decorator: ``dec`` itself for a bare
    ``@dataclass`` / ``@dataclasses.dataclass``, or ``dec.func`` for a called
    ``@dataclass(...)``."""
    return dec.func if isinstance(dec, ast.Call) else dec


def _is_dataclass_name(func: ast.expr) -> bool:
    """True when ``func`` has the NAME SHAPE of the ``dataclass`` decorator —
    either a bare ``dataclass`` ``Name`` or a dotted ``....dataclass``
    ``Attribute``. A SHAPE check only: it does NOT prove the name binds the
    stdlib ``dataclasses.dataclass`` (a ``pydantic`` / local ``dataclass`` has the
    same shape). Provenance is checked by :func:`_stdlib_dataclass_binding` +
    :func:`_is_stdlib_dataclass_name`. Kept for the idempotency guard, which only
    needs the shape (an already-``frozen=`` decorator is left alone regardless of
    provenance)."""
    if isinstance(func, ast.Name):
        return func.id == "dataclass"
    return isinstance(func, ast.Attribute) and func.attr == "dataclass"


def _shadows_name(tree: ast.AST, name: str) -> bool:
    """True when ``name`` is bound anywhere in ``tree`` by a NON-import statement
    — a ``def``/``class`` of that name, or any ``Store``-context assignment target
    (``name = ...``, ``for name in``, ``with x as name``, a walrus, ...). Such a
    binding shadows a same-named stdlib import, so the decorator can no longer be
    proven to be the stdlib one. (Import-form rebindings are handled by
    :func:`_import_bindings`.)"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id == name:
                return True
    return False


def _import_bindings(tree: ast.AST, name: str, blessed_module: str) -> tuple[bool, bool]:
    """Scan ``tree``'s imports for bindings of ``name``: ``(has_blessed, has_other)``.

    ``has_blessed`` is True iff a ``from <blessed_module> import <name>`` with NO
    ``asname`` is present (the only import that PROVES ``name`` is the stdlib
    binding). ``has_other`` is True for ANY other import that binds ``name`` — a
    differently-sourced ``from X import name``, an aliased ``import ... as name``,
    or a ``from blessed import name as ...`` — each of which means ``name`` may not
    be the stdlib one. ``import dataclasses`` (no asname) is the blessed form when
    ``name == "dataclasses"``."""
    has_blessed = False
    has_other = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            has_blessed, has_other = _scan_importfrom(
                node, name, blessed_module, has_blessed, has_other)
        elif isinstance(node, ast.Import):
            has_blessed, has_other = _scan_import(
                node, name, blessed_module, has_blessed, has_other)
    return has_blessed, has_other


def _scan_importfrom(
    node: ast.ImportFrom, name: str, blessed_module: str,
    has_blessed: bool, has_other: bool,
) -> tuple[bool, bool]:
    """Fold one ``from ... import ...`` into the ``(has_blessed, has_other)`` pair
    for the binding scan of :func:`_import_bindings`."""
    for alias in node.names:
        bound = alias.asname or alias.name
        if bound != name:
            continue
        is_blessed = (
            node.module == blessed_module
            and alias.name == name
            and alias.asname is None
        )
        if is_blessed:
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _scan_import(
    node: ast.Import, name: str, blessed_module: str,
    has_blessed: bool, has_other: bool,
) -> tuple[bool, bool]:
    """Fold one ``import ...`` into the ``(has_blessed, has_other)`` pair. A bare
    ``import dataclasses`` (no asname) is the blessed form ONLY when the scanned
    ``name`` is the module name itself (the dotted-decorator case)."""
    for alias in node.names:
        bound = alias.asname or alias.name.split(".")[0]
        if bound != name:
            continue
        is_blessed = (
            alias.name == blessed_module
            and alias.asname is None
            and name == blessed_module
        )
        if is_blessed:
            has_blessed = True
        else:
            has_other = True
    return has_blessed, has_other


def _stdlib_dataclass_binding(tree: ast.AST) -> tuple[bool, bool]:
    """``(bare_ok, dotted_ok)`` — whether the module PROVABLY binds the stdlib
    ``dataclasses.dataclass`` in each decorator form.

    ``bare_ok``: a bare ``@dataclass`` is the stdlib one iff the module has
    ``from dataclasses import dataclass`` (no ``asname``) AND nothing else binds
    the name ``dataclass`` (no local ``def``/``class``/assignment, no
    differently-sourced or aliased import). ``dotted_ok``: a dotted
    ``@dataclasses.dataclass`` is the stdlib one iff the module has ``import
    dataclasses`` (no ``asname``) AND nothing rebinds the name ``dataclasses``.
    This REJECTS ``pydantic.dataclasses.dataclass`` (handled separately — its
    value is an ``Attribute``, not a ``Name`` ``dataclasses``), a ``pydantic``
    bare ``dataclass`` import, and any local shadow (soundness over recall)."""
    bare_blessed, bare_other = _import_bindings(tree, "dataclass", "dataclasses")
    bare_ok = bare_blessed and not bare_other and not _shadows_name(tree, "dataclass")
    dot_blessed, dot_other = _import_bindings(tree, "dataclasses", "dataclasses")
    dotted_ok = (
        dot_blessed and not dot_other and not _shadows_name(tree, "dataclasses")
    )
    return bare_ok, dotted_ok


def _is_stdlib_dataclass_name(func: ast.expr, bare_ok: bool, dotted_ok: bool) -> bool:
    """True when ``func`` is the stdlib ``dataclass`` decorator GIVEN the module's
    proven bindings ``(bare_ok, dotted_ok)`` from :func:`_stdlib_dataclass_binding`.

    A bare ``Name`` ``dataclass`` is accepted only when ``bare_ok``; a dotted
    ``Attribute`` ``dataclass`` only when ``dotted_ok`` AND its value is exactly
    the ``Name`` ``dataclasses`` (so ``pydantic.dataclasses.dataclass``, whose
    value is an ``Attribute``, is rejected)."""
    if isinstance(func, ast.Name):
        return func.id == "dataclass" and bare_ok
    if isinstance(func, ast.Attribute) and func.attr == "dataclass":
        return (
            dotted_ok
            and isinstance(func.value, ast.Name)
            and func.value.id == "dataclasses"
        )
    return False


def _decorator_has_frozen(dec: ast.expr) -> bool:
    """True when a called ``@dataclass(...)`` already passes a ``frozen=``
    keyword, OR carries a ``**`` unpacking keyword (``kw.arg is None``) whose
    dict keys we cannot know statically.

    In the first case freezing would be redundant / would override an explicit
    choice. In the second case the unpacked dict MIGHT already carry ``frozen``,
    and appending ``frozen=True`` would emit ``@dataclass(**opts, frozen=True)``
    — valid syntax (the re-parse guard does NOT catch it) that raises
    ``TypeError: got multiple values for keyword argument 'frozen'`` at import.
    So we conservatively refuse to freeze any ``**``-unpacking call. A bare
    ``@dataclass`` has no keywords, so this is ``False``."""
    if not isinstance(dec, ast.Call):
        return False
    return any(kw.arg in ("frozen", None) for kw in dec.keywords)


def is_frozen_dataclass_decorator(dec: ast.expr) -> bool:
    """True when ``dec`` is a ``@dataclass`` decorator we will NOT add
    ``frozen=True`` to: it already carries a ``frozen=`` keyword (the idempotency
    guard — a second run sees it and stops) OR a ``**`` unpacking keyword whose
    keys we cannot know (a conservative refuse — see :func:`_decorator_has_frozen`)."""
    return _is_dataclass_name(_decorator_func(dec)) and _decorator_has_frozen(dec)


def _dataclass_decorator(
    cls: ast.ClassDef, bare_ok: bool, dotted_ok: bool
) -> ast.expr | None:
    """The class's STDLIB ``@dataclass`` / ``@dataclasses.dataclass`` decorator
    that does NOT already pass ``frozen=``, or ``None``.

    ``bare_ok`` / ``dotted_ok`` are the module's proven stdlib bindings (from
    :func:`_stdlib_dataclass_binding`): a decorator is considered only when
    :func:`_is_stdlib_dataclass_name` accepts it under those flags, so a
    ``pydantic`` / locally-shadowed ``dataclass`` is skipped. Returns ``None``
    when the class carries no such decorator at all, OR when one is present but
    already names ``frozen=`` / unpacks ``**`` (idempotent — nothing to do)."""
    for dec in cls.decorator_list:
        if not _is_stdlib_dataclass_name(_decorator_func(dec), bare_ok, dotted_ok):
            continue
        if _decorator_has_frozen(dec):
            return None  # already frozen (or explicitly frozen=False) — leave it
        return dec
    return None


def _is_classvar(annotation: ast.expr | None) -> bool:
    """True when ``annotation`` is a ``ClassVar`` / ``ClassVar[...]`` /
    ``typing.ClassVar`` — a class-level constant that is NOT a dataclass field."""
    if annotation is None:
        return False
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name):
        return target.id == "ClassVar"
    return isinstance(target, ast.Attribute) and target.attr == "ClassVar"


def dataclass_field_names(cls: ast.ClassDef) -> list[str]:
    """The dataclass FIELD names declared in ``cls``'s body, in source order.

    A field is a top-level ``AnnAssign`` with a simple ``Name`` target that is
    not annotated ``ClassVar`` (the marker dataclasses use for a non-field
    class attribute). Bare assignments and methods are not fields."""
    names: list[str] = []
    for stmt in cls.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if _is_classvar(stmt.annotation):
            continue
        names.append(stmt.target.id)
    return names


def _class_only_object_base(cls: ast.ClassDef) -> bool:
    """True when ``cls`` has NO base class other than the implicit ``object``.

    A frozen dataclass may not mix with a non-frozen one in a hierarchy, so any
    explicit base (or any class keyword such as ``metaclass=``) is a refusal.
    A bare ``object`` base is allowed (it is the implicit default)."""
    if cls.keywords:
        return False  # metaclass=/other class keywords — out of scope
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "object":
            continue
        return False
    return True


def _setattr_field_name(call: ast.Call) -> str | None:
    """For the BUILTIN ``setattr(<expr>, "<field>", <value>)`` with a
    STRING-LITERAL field, that field name; else ``None``.

    Matches ONLY the builtin ``Name`` form (``func.id == "setattr"``), because the
    ``(obj, name, value)`` arg layout it reads from ``call.args[1]`` is the
    builtin's. A method call ``obj.setattr(name, value)`` (``ast.Attribute``) is
    NOT the builtin — its first positional arg is the NAME, not the object, so
    reading ``args[1]`` would mis-attribute the wrong field; and a real such
    method's body is scanned for ``<expr>.<attr> = ...`` separately. A non-literal
    name (``setattr(o, k, v)``) cannot be resolved statically, so it contributes
    no name here (the suite gate remains the backstop for that dynamic case)."""
    func = call.func
    if not (isinstance(func, ast.Name) and func.id == "setattr"):
        return None
    if len(call.args) < 2:
        return None
    name_arg = call.args[1]
    if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
        return name_arg.value
    return None


def _node_mutated_name(node: ast.AST) -> str | None:
    """The attribute name a SINGLE node mutates, or ``None``.

    Covers the four mutation shapes: ``<expr>.<attr> = ...`` (an ``ast.Attribute``
    in ``Store`` context, which also covers augmented ``+=`` and ``del``, since
    Python marks all three with a ``Store``/``Del`` context on the attribute), and
    ``setattr(<expr>, "<attr>", ...)``."""
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.attr
    if isinstance(node, ast.Call):
        return _setattr_field_name(node)
    return None


def mutated_attribute_names(source: str) -> set[str]:
    """Every attribute name used as a STORE/DEL target (or a literal ``setattr``
    name) anywhere in ``source`` — the conservative mutation over-approximation.

    Walks the whole module. Covers ``<expr>.<attr> = ...``, augmented
    ``<expr>.<attr> += ...``, ``del <expr>.<attr>``, and
    ``setattr(<expr>, "<attr>", ...)``. Deliberately ignores the base expression
    (``<expr>``), so a same-named attribute on an UNRELATED object is included —
    a false positive that causes a SAFE refuse. Returns ``set()`` on a syntax
    error (a module we cannot parse contributes no names — the freeze of any
    OTHER module is gated by the same per-module parse, and the suite is the
    backstop)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        name = _node_mutated_name(node)
        if name is not None:
            names.add(name)
    return names


def _emit_frozen_decorator(dec: ast.expr) -> ast.expr:
    """A NEW decorator expression equal to ``dec`` with ``frozen=True`` added.

    A bare ``@dataclass`` / ``@dataclasses.dataclass`` becomes a call
    ``@dataclass(frozen=True)``; an existing ``@dataclass(...)`` call keeps its
    args/keywords and gains a trailing ``frozen=True`` keyword. ``dec`` is known
    to carry no ``frozen=`` already (the caller checked)."""
    frozen_kw = ast.keyword(arg="frozen", value=ast.Constant(value=True))
    if isinstance(dec, ast.Call):
        return ast.Call(func=dec.func, args=list(dec.args),
                        keywords=[*dec.keywords, frozen_kw])
    return ast.Call(func=dec, args=[], keywords=[frozen_kw])


def _line_has_comment(line: str) -> bool:
    """True when ``line`` carries a ``#`` COMMENT *token* (not a ``#`` inside a
    string/identifier). Uses :mod:`tokenize` so ``x = "#hash"`` is NOT flagged.
    A line that does not tokenize cleanly is treated, conservatively, as if it
    had a comment (refuse rather than risk dropping content)."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(line).readline):
            if tok.type == tokenize.COMMENT:
                return True
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return True
    return False


def _is_single_line_rewritable(dec: ast.expr, lines: list[str]) -> bool:
    """True when ``dec``'s source span is a SINGLE physical line with no inline
    ``#`` comment — the only shape the ``ast.unparse`` re-emit can reproduce
    without silent loss.

    The rewrite re-emits via ``ast.unparse``, which DROPS comments and COLLAPSES
    a multi-line decorator onto one line. Rather than risk that content loss we
    refuse anything multi-line or commented. When unsure we refuse."""
    start, end = _node_line_span(dec)
    if start + 1 != end:
        return False  # multi-line decorator — refuse (would collapse, losing layout)
    return not _line_has_comment(lines[start])


def _rewrite_decorator(dec: ast.expr, lines: list[str]) -> tuple[int, int, list[str]]:
    """The ``(start, end, [new_line])`` line-splice that rewrites ONE decorator's
    source span to its ``frozen=True`` form.

    Preserves the decorator's leading indentation and re-emits the modified
    expression via ``ast.unparse`` behind the ``@`` sigil. The decorator is known
    to occupy a SINGLE physical line with no inline comment (the freezability
    gate checks this via :func:`_is_single_line_rewritable`); a multi-line or
    commented decorator is REFUSED upstream rather than collapsed, because the
    ``ast.unparse`` re-emit would drop comments and join the lines.
    ``rejoin_guarded`` re-parses the result, dropping a malformed splice."""
    start, end = _node_line_span(dec)
    header = lines[start]
    indent = header[: len(header) - len(header.lstrip())]
    new_dec = _emit_frozen_decorator(dec)
    new_line = f"{indent}@{ast.unparse(new_dec)}"
    return start, end, [new_line]


class _ModuleContext(NamedTuple):
    """The per-module facts the freezability gate needs beyond the class itself:
    the module's physical source ``lines`` (for the single-line-rewrite check),
    the proven stdlib bindings ``bare_ok`` / ``dotted_ok``, and the whole-project
    ``used_as_base`` / ``mutated`` over-approximations."""

    lines: list[str]
    bare_ok: bool
    dotted_ok: bool
    used_as_base: set[str]
    mutated: set[str]


def _module_context(source: str, scan_sources: list[str]) -> _ModuleContext:
    """Build the :class:`_ModuleContext` for ``source`` whose mutation /
    used-as-base scans span ``scan_sources``. ``source`` must already parse (the
    caller guards this); its proven stdlib ``dataclass`` bindings are read from
    its OWN module tree, not the cross-module scan set."""
    bare_ok, dotted_ok = _stdlib_dataclass_binding(ast.parse(source))
    return _ModuleContext(
        lines=source.splitlines(),
        bare_ok=bare_ok,
        dotted_ok=dotted_ok,
        used_as_base=_used_as_base_names(scan_sources),
        mutated=_whole_project_mutated(scan_sources),
    )


def _is_freezable(cls: ast.ClassDef, ctx: _ModuleContext) -> ast.expr | None:
    """The ``@dataclass`` decorator to freeze on ``cls``, or ``None`` when ``cls``
    fails ANY soundness gate.

    Gates (all must hold): a not-yet-frozen, PROVABLY-stdlib ``@dataclass``
    decorator on a SINGLE uncommented physical line is present; ``cls`` has only
    the implicit ``object`` base and no class keywords; ``cls``'s name is not used
    as a base elsewhere; ``cls`` has >= 1 field; and NONE of its field names
    appears in the whole-project ``mutated`` set."""
    dec = _dataclass_decorator(cls, ctx.bare_ok, ctx.dotted_ok)
    if dec is None:
        return None
    if not _is_single_line_rewritable(dec, ctx.lines):
        return None  # multi-line / commented decorator — refuse (would lose content)
    if not _class_only_object_base(cls):
        return None
    if cls.name in ctx.used_as_base:
        return None
    fields = dataclass_field_names(cls)
    if not fields:
        return None  # a dataclass with no fields gains nothing from freezing
    if any(name in ctx.mutated for name in fields):
        return None  # a field is (over-approximately) mutated somewhere — refuse
    return dec


def project_sources(project_root, module_rel: str, this_source: str) -> list[str]:
    """Every own-module source text used for the whole-project mutation /
    used-as-base scan, with ``module_rel``'s text guaranteed to be ``this_source``
    (the exact bytes being rewritten, so the scan is consistent with the rewrite).

    Falls back to JUST ``this_source`` when the source index is unavailable (e.g.
    a bare directory with no project shape) — then the scan is single-module, which
    is STILL sound for ``__post_init__`` / in-module mutation and is the
    conservative floor."""
    try:
        from app.engine.objective_compiler import _own_modules

        sources = {rel: src for rel, src in _own_modules(project_root)}
    except Exception:
        sources = {}
    sources[module_rel] = this_source
    return list(sources.values())


def all_module_sources(project_root, module_rel: str, this_source: str) -> list[str]:
    """Every ``.py`` source text in the project — INCLUDING tests and fixtures —
    for a whole-project subclass / used-as-base scan, with ``module_rel``'s text
    guaranteed to be ``this_source`` (the exact bytes being rewritten, so the scan
    is consistent with the rewrite).

    The tests-INCLUSIVE sibling of :func:`project_sources`. The ``@final`` family
    (add-final, seal-final-method) uses THIS, not ``project_sources``: a class
    subclassed — or a method overridden — ONLY in a test file (a mock / fake /
    stub) is a REAL subclass/override that ``@typing.final`` breaks for a TYPE
    CHECKER, and a pytest suite can NEVER catch that (the decorator is a pure
    runtime no-op). Excluding tests would make such a subject look like a leaf and
    wrongly seal it — a false "final" the suite cannot see. So the scan must span
    every module, tests included. freeze-dataclass deliberately does NOT use this:
    its wrong-freeze is a RUNTIME ``TypeError`` / ``FrozenInstanceError`` the suite
    DOES catch (and roll back), so it keeps the tighter own-module ``project_sources``
    scan.

    Falls back to JUST ``this_source`` when the file walk is unavailable (e.g. a
    bare directory with no project shape) — then the scan is single-module, which
    is STILL sound for an in-module subclass/override and is the conservative floor."""
    from pathlib import Path

    try:
        from app.engine.source_index import _py_files

        sources = {rel: src for rel, src in _py_files(Path(project_root))}
    except Exception:
        sources = {}
    sources[module_rel] = this_source
    return list(sources.values())


def _base_name(base: ast.expr) -> str | None:
    """The bare name a BASE expression contributes to the used-as-base set: the
    ``id`` of a simple ``Name`` base, the FINAL ``.attr`` of a dotted ``Attribute``
    base (so ``pkg.C`` contributes ``"C"``), or — for a SUBSCRIPTED base ``H[...]``
    (``Foo[int]``, ``pkg.Foo[int]``) — the head name of ``H`` (``"Foo"``). The
    subscript head matters for soundness: ``class Sub(Foo[int])`` really subclasses
    ``Foo``, so ``Foo`` must be recorded as used-as-base — otherwise freeze-dataclass
    would wrongly freeze it (a non-frozen subclass of a frozen dataclass is a
    ``TypeError`` at definition time) and add-final would wrongly seal it. A call or
    any other base form contributes nothing. Mirrors
    :func:`app.execution.final_marker._subscript_head_name`."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Subscript):
        return _base_name(base.value)
    return None


def _used_as_base_names(sources: list[str]) -> set[str]:
    """Every class name used as a BASE in any ``ClassDef`` across ``sources``.

    A class subclassed anywhere cannot be frozen (a non-frozen subclass of a
    frozen dataclass is a ``TypeError`` at definition time). A simple ``Name``
    base is resolved by its ``id``; a dotted ``Attribute`` base (``pkg.C``) is
    over-approximated by its FINAL ``.attr`` (``"C"``); a subscripted base
    (``C[int]`` / ``pkg.C[int]``) is resolved by its head name (``"C"``). This may
    refuse an unrelated, same-named class — a SAFE over-refusal (soundness over
    recall) — but never misses the real subclass case (bare, dotted, or generic),
    whose freeze would otherwise raise ``TypeError`` at the subclass's import."""
    names: set[str] = set()
    for src in sources:
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = _base_name(base)
                if name is not None:
                    names.add(name)
    return names


def _whole_project_mutated(sources: list[str]) -> set[str]:
    """Union of :func:`mutated_attribute_names` over every source in ``sources``
    — the whole-project attribute-mutation over-approximation."""
    mutated: set[str] = set()
    for src in sources:
        mutated |= mutated_attribute_names(src)
    return mutated


def freezable_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that are freezable when
    ``source`` is considered IN ISOLATION (single-module scan).

    Convenience for tests / single-file reasoning: uses ``source`` itself as the
    whole project, so the used-as-base and mutation scans see only this module.
    Sorted by source order. Returns ``[]`` on a syntax error. The objective's
    real plan uses the WHOLE project, which can only ADD refusals (more mutation
    sites / more base uses), never remove them."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    ctx = _module_context(source, [source])
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_freezable(node, ctx):
            out.append(node.name)
    return out


def _collect_freeze_edits(
    tree: ast.Module, ctx: _ModuleContext
) -> list[tuple[int, int, list[str]]]:
    """The ``(start, end, new_lines)`` decorator splice for every freezable
    top-level class in ``tree``, in source order."""
    edits: list[tuple[int, int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        dec = _is_freezable(node, ctx)
        if dec is None:
            continue
        edits.append(_rewrite_decorator(dec, ctx.lines))
    return edits


def freeze_dataclass_decorator(
    source: str, project_sources: list[str] | None = None
) -> str | None:
    """Add ``frozen=True`` to every freezable ``@dataclass`` in ``source``, or
    ``None`` when nothing changes.

    ``project_sources`` is the whole-project source set the mutation /
    used-as-base over-approximation scans (it MUST include ``source`` itself); when
    ``None``, ``source`` is scanned in isolation (the conservative single-module
    floor). Classes are rewritten in REVERSE source order so earlier line spans
    stay valid. Deterministic and idempotent (an already-frozen dataclass is not
    re-touched); the result is re-``ast.parse``d before return, so a malformed
    rewrite yields ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    scan_sources = [source] if project_sources is None else project_sources
    ctx = _module_context(source, scan_sources)

    edits = _collect_freeze_edits(tree, ctx)
    if not edits:
        return None

    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so spans stay valid
    out_lines = list(ctx.lines)
    for start, end, new_lines in edits:
        out_lines[start:end] = new_lines
    return rejoin_guarded(source, out_lines)
