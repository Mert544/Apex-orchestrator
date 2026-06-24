"""Add ``@typing.final`` to a METHOD of a project-own class that is PROVABLY never
overridden anywhere in the project's own source — the method-level sibling of the
class-level :mod:`app.execution.final_marker` (add-final).

``@typing.final`` on a METHOD is a PURE runtime no-op exactly as it is on a class —
CPython only records the intent and otherwise returns the function unchanged; the
decorator is consulted by TYPE CHECKERS only. So sealing a method ``@final`` is
behaviour-preserving BY CONSTRUCTION: there is *nothing* at runtime to break. The
decorator documents and (for a type checker) ENFORCES a real design intent — "this
method is the final word, do not override it in a subclass" — the one-line
annotation a careful author writes by hand. Where a linter only FLAGS the
opportunity, :func:`add_final_method_decorator` WRITES it, deterministically and
for free.

SOUNDNESS — the only failure mode. Because the decorator has no runtime effect, a
green suite proves nothing *behavioural*; but it also cannot break anything. The
single honesty risk is a FALSE "final" claim — sealing a method ``C.m`` that IS
overridden in a subclass (a type checker would then reject the override). That risk
is closed STRUCTURALLY and CONSERVATIVELY, NOT by the suite: a whole-project
over-approximate subclass scan collects, for every class, the method names defined
by ANY class whose by-NAME transitive base-closure includes that class's name — a
bare ``class X(C)``, a dotted ``class X(pkg.C)`` (matched by its final ``.attr``),
AND a subscripted ``class X(C[int])`` (matched by the subscript head), at any depth
of the hierarchy. ``C.m`` is sealable ONLY when ``m`` is absent from that
subclass-method set.

CRITICAL ASYMMETRY (vs a deferred add-override): we REFUSE on any ambiguity —
over-refusing is SAFE here (we simply do not seal), so we do NOT need a hard
binding-aware base resolution. When in doubt, refuse.

A method ``C.m`` is sealed ``@final`` ONLY when ALL of these hold (otherwise an
honest no-op):

  - ``C`` is a TOP-LEVEL class and ``m`` is a plain ``def`` / ``async def`` in
    ``C``'s body (not a nested or dynamically-created method);
  - NO potential subclass of ``C`` — any class whose by-name transitive base
    closure includes ``C``'s name — defines a method named ``m`` (the structural
    never-overridden proof above);
  - ``m`` is NOT a dunder (``__init__`` / ``__eq__`` / … — dunders are routinely
    overridden by design, and sealing one would be the wrong intent);
  - ``m`` does NOT already carry ``@final`` / ``@typing.final`` (idempotent: a
    second run sees the decorator it landed and is a byte-identical no-op);
  - ``m`` is NOT a ``@property`` / ``@staticmethod`` / ``@classmethod`` /
    ``@overload`` / ``@abstractmethod`` (a descriptor changes the override story,
    an ``@overload`` is a signature stub, and an ``@abstractmethod`` is MEANT to be
    overridden — all refused per spec);
  - ``C`` is NOT a ``Protocol`` / ``ABC`` (nor an ``ABCMeta`` ``metaclass=``): a
    protocol / abstract base exists to be implemented, so ITS methods are meant to
    be overridden — refuse the whole class;
  - the name ``final`` can be bound UNAMBIGUOUSLY to ``typing.final`` in the module
    (reusing :mod:`app.execution.final_marker`'s binding check): emit a bare
    ``@final`` when ``from typing import final`` is/where it can be added, or the
    dotted ``@typing.final`` when ``final`` is shadowed but ``typing`` is bound. If
    NEITHER form can be proven, refuse (the round-16 ``final``-shadow lesson).

``typing.final`` exists since Python 3.8, so this lands on the project's 3.10
floor with NO version gate. Deterministic (pure AST walk + line splice, no
clock/random), stdlib-only, zero-token, idempotent. Reuses
:func:`app.execution.freeze_dataclass._used_as_base_names` /
:func:`~app.execution.freeze_dataclass.project_sources` for the whole-project
subclass scan groundwork (and ``_base_name`` for dotted/subscripted base names),
and :mod:`app.execution.final_marker`'s ``_final_binding`` / ``_ensure_final_import``
/ ``_decorator_text`` / ``_needs_import`` / ``_decorator_is_final`` / ``_insert_decorator``
so the ``@final`` binding/import machinery (and the indent-preserving header splice,
which is identical for a ``def`` and a ``class``) is emitted EXACTLY as add-final does.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import rejoin_guarded
from app.execution.final_marker import (
    _decorator_is_final,
    _decorator_text,
    _ensure_final_import,
    _final_binding,
    _insert_decorator,
    _needs_import,
)
from app.execution.freeze_dataclass import (
    _base_name,
    is_public_name,
    project_sources,
)

__all__ = [
    "add_final_method_decorator",
    "finalizable_methods",
    "method_has_final_decorator",
    "subclass_method_names",
    "project_sources",
]

# Bases / metaclasses marking a class as an extension point by design — a
# protocol / abstract base exists to be IMPLEMENTED, so ITS methods are meant to
# be overridden; sealing one would be the wrong intent. Matched by the FINAL
# ``.attr`` of a dotted base too (``abc.ABC`` -> ``ABC``), so an import-style
# variant is caught (mirrors final_marker's class-level check, minus the Enum
# family — an enum's own methods are not the override-intent concern here, but a
# subclassing enum is still caught by the subclass-method scan).
_ABSTRACT_BASE_NAMES = frozenset({"Protocol", "ABC"})
_ABCMETA_NAMES = frozenset({"ABCMeta"})

# Method decorators that take a method OUT of the plain-instance-method scope:
# a descriptor (``property`` / ``staticmethod`` / ``classmethod``) changes the
# override story, an ``@overload`` is a typing signature stub, and an
# ``@abstractmethod`` is MEANT to be overridden. Any of these → refuse. Matched by
# the FINAL ``.attr`` of a dotted decorator too (``abc.abstractmethod`` ->
# ``abstractmethod``), a conservative over-approximation (an unrelated same-named
# decorator also refuses — soundness over recall).
_SKIP_METHOD_DECORATORS = frozenset({
    "property", "staticmethod", "classmethod", "overload", "abstractmethod",
    "cached_property", "abstractproperty", "setter", "getter", "deleter",
})


def _decorator_attr_name(dec: ast.expr) -> str | None:
    """The bare name a decorator expression contributes: a simple ``Name``'s
    ``id`` (``staticmethod``), the FINAL ``.attr`` of a dotted ``Attribute``
    (``abc.abstractmethod`` -> ``"abstractmethod"``, ``x.setter`` -> ``"setter"``),
    or — for a CALLED decorator ``deco(...)`` — the name of its callable. ``None``
    for any other shape."""
    if isinstance(dec, ast.Call):
        return _decorator_attr_name(dec.func)
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def method_has_final_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` already carries a ``@final`` / ``@typing.final`` decorator
    (the idempotency guard — a second run sees it and stops). Reuses
    final_marker's ``_decorator_is_final`` shape check."""
    return any(_decorator_is_final(dec) for dec in fn.decorator_list)


def _has_skip_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` carries a decorator that takes it out of plain-instance-
    method scope (``property`` / ``staticmethod`` / ``classmethod`` / ``overload``
    / ``abstractmethod`` and friends — see :data:`_SKIP_METHOD_DECORATORS`)."""
    return any(_decorator_attr_name(dec) in _SKIP_METHOD_DECORATORS
               for dec in fn.decorator_list)


def _is_dunder(name: str) -> bool:
    """True for a dunder name (``__init__`` / ``__eq__`` / …): leading AND trailing
    double underscore, longer than the bare ``__``. Dunders are routinely
    overridden by design, so a dunder is refused."""
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _is_abstract_base_class(cls: ast.ClassDef) -> bool:
    """True when ``cls`` is a ``Protocol`` / ``ABC`` (or an ``ABCMeta``
    ``metaclass=``) — a class whose methods are MEANT to be overridden, so none of
    its methods may be sealed. Matched by the final ``.attr`` of a base/keyword
    value, a conservative over-approximation (an unrelated same-named base also
    refuses — soundness over recall)."""
    for base in cls.bases:
        if _base_name(base) in _ABSTRACT_BASE_NAMES:
            return True
    for kw in cls.keywords:
        if kw.arg == "metaclass" and _base_name(kw.value) in _ABCMETA_NAMES:
            return True
    return False


def _class_base_names(cls: ast.ClassDef) -> set[str]:
    """The set of bare BASE names ``cls`` lists, via final_marker/freeze's
    ``_base_name`` (so a bare ``Name``, a dotted ``Attribute``'s final ``.attr``,
    and a subscripted base's head are all resolved). ``object`` is dropped — every
    class inherits it, so it is not a meaningful override edge."""
    names: set[str] = set()
    for base in cls.bases:
        name = _base_name(base)
        if name is not None and name != "object":
            names.add(name)
    return names


def _method_names(cls: ast.ClassDef) -> set[str]:
    """The names of ``cls``'s own plain ``def`` / ``async def`` methods (a
    conservative over-approximation: every method name in the body, regardless of
    its decorators — a same-named overriding method counts however it is spelled)."""
    return {stmt.name for stmt in cls.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))}


class _ClassFacts(NamedTuple):
    """The two whole-project, name-keyed over-approximations the subclass scan
    folds together: ``bases`` maps each class NAME to the union of every base name
    any same-named class lists; ``methods`` maps each class NAME to the union of
    every method name any same-named class defines."""

    bases: dict[str, set[str]]
    methods: dict[str, set[str]]


def _collect_class_facts(sources: list[str]) -> _ClassFacts:
    """Fold every class across ``sources`` into a name-keyed :class:`_ClassFacts`.

    Purely by NAME (an over-approximation): two classes that share a name in
    different modules have their base-name sets and method-name sets UNIONED, so
    the subclass scan can never miss a real override (soundness over recall). A
    source that does not parse contributes nothing — its own seals are gated by the
    same per-module parse, and the suite is the backstop."""
    bases: dict[str, set[str]] = {}
    methods: dict[str, set[str]] = {}
    for src in sources:
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases.setdefault(node.name, set()).update(_class_base_names(node))
            methods.setdefault(node.name, set()).update(_method_names(node))
    return _ClassFacts(bases=bases, methods=methods)


def _descendant_names(target: str, facts: _ClassFacts) -> set[str]:
    """Every class NAME whose by-name transitive base closure includes ``target``
    — i.e. every potential (direct or indirect) subclass of ``target``.

    Walks the name-keyed inheritance graph (``facts.bases``: child name -> its base
    names) outward from ``target``: a class is a descendant when one of its bases is
    ``target`` or a descendant already found. Conservative and bounded — the visited
    set guarantees termination even on a cyclic by-name graph (two modules each
    naming the other a base). ``target`` itself is NOT included."""
    descendants: set[str] = set()
    frontier = {target}
    while frontier:
        nxt: set[str] = set()
        for name, base_names in facts.bases.items():
            if name in descendants or name == target:
                continue
            if base_names & frontier:
                descendants.add(name)
                nxt.add(name)
        frontier = nxt
    return descendants


def subclass_method_names(target: str, sources: list[str]) -> set[str]:
    """Every method name defined by ANY potential subclass of class ``target``
    across ``sources`` — the conservative never-overridden over-approximation.

    A method ``target.m`` is sealable ONLY when ``m`` is absent from this set. The
    subclass relation is taken by NAME and transitively (see
    :func:`_descendant_names`), covering bare, dotted, and subscripted bases at any
    depth — a same-named unrelated class causes a SAFE over-refusal, but a real
    override is never missed."""
    facts = _collect_class_facts(sources)
    names: set[str] = set()
    for descendant in _descendant_names(target, facts):
        names |= facts.methods.get(descendant, set())
    return names


class _ModuleContext(NamedTuple):
    """Per-module facts the finalizability gate needs beyond the method/class: the
    module's raw ``source`` and physical ``lines`` (for the public-surface check and
    the splice), whether to apply the public-surface ``refuse_public`` gate (set by
    the objective; off for in-isolation reasoning), the proven ``binding`` of
    ``typing.final`` (final_marker's ``_FinalBinding``), and the whole-project
    ``facts`` the subclass scan reads."""

    source: str
    lines: list[str]
    refuse_public: bool
    binding: object  # final_marker._FinalBinding
    facts: _ClassFacts


def _module_context(
    source: str, scan_sources: list[str], *, refuse_public: bool = False
) -> _ModuleContext:
    """Build the :class:`_ModuleContext` for ``source`` whose subclass scan spans
    ``scan_sources``. ``source`` must already parse (the caller guards this); its
    ``final``/``typing`` bindings come from its OWN tree via final_marker.
    ``refuse_public`` turns on the public-surface refusal (default ``False`` for
    in-isolation reasoning, where "public API" is undefined without an
    importable-module context)."""
    return _ModuleContext(
        source=source,
        lines=source.splitlines(),
        refuse_public=refuse_public,
        binding=_final_binding(ast.parse(source)),
        facts=_collect_class_facts(scan_sources),
    )


def _is_sealable_method(
    cls: ast.ClassDef,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    ctx: _ModuleContext,
) -> bool:
    """True when ``cls.fn`` is a plain instance method safe to seal ``@final``.

    Gates (all must hold): not already ``@final``; not a dunder; no
    property/staticmethod/classmethod/overload/abstractmethod decorator; and NO
    potential subclass of ``cls`` defines a method named ``fn.name``. ``cls``-level
    gates (abstract base, provable ``typing.final`` binding) are checked once by the
    caller before any of its methods reach here."""
    if method_has_final_decorator(fn):
        return False
    if _is_dunder(fn.name):
        return False
    if _has_skip_decorator(fn):
        return False
    descendants = _descendant_names(cls.name, ctx.facts)
    for descendant in descendants:
        if fn.name in ctx.facts.methods.get(descendant, set()):
            return False
    return True


def _binding_allows_final(binding: object) -> bool:
    """True when ``typing.final`` is provably spellable in the module — a bare
    ``@final`` is/where it can be importable, or a dotted ``@typing.final`` is
    provable. Reads final_marker's ``_FinalBinding`` flags."""
    return bool(binding.bare_ok or binding.dotted_ok or binding.can_add_import)


def _sealable_methods_in_class(
    cls: ast.ClassDef, ctx: _ModuleContext
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every sealable plain instance method of ``cls``, in source order, or ``[]``
    when ``cls`` is an abstract base (Protocol / ABC / ABCMeta) — whose methods are
    meant to be overridden — when ``cls`` is PUBLIC SURFACE (an ``__all__``-listed
    name, or — with no ``__all__`` — a top-level non-underscore class: external code
    may subclass that published class and override the method, which ``@final`` would
    break for a type checker, and the project-own scan cannot see that) — or when
    ``typing.final`` cannot be proven spellable. The public-surface gate is applied
    only when ``ctx.refuse_public`` (the objective sets it)."""
    if _is_abstract_base_class(cls):
        return []
    if ctx.refuse_public and is_public_name(cls.name, ctx.source):
        return []  # public class — an external subclass may override its methods
    if not _binding_allows_final(ctx.binding):
        return []
    return [stmt for stmt in cls.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _is_sealable_method(cls, stmt, ctx)]


def _all_sealable_methods(
    tree: ast.Module, ctx: _ModuleContext
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every sealable method across all top-level classes in ``tree``, in source
    order (class order, then method order within each class)."""
    out: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.extend(_sealable_methods_in_class(node, ctx))
    return out


def finalizable_methods(source: str) -> list[str]:
    """The ``Class.method`` names sealable when ``source`` is considered IN
    ISOLATION (single-module subclass scan).

    Convenience for tests / single-file reasoning: ``source`` is its own whole
    project, so the subclass scan sees only this module, and the public-surface
    refusal is OFF (``refuse_public=False`` — "public API" is undefined without a
    real project context; the objective turns it on). Sorted by source order.
    Returns ``[]`` on a syntax error. The objective's real plan uses the WHOLE
    project, which can only ADD refusals (more potential subclasses defining the
    method, the public-surface refusal), never remove them."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    ctx = _module_context(source, [source])
    out: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for fn in _sealable_methods_in_class(node, ctx):
            out.append(f"{node.name}.{fn.name}")
    return out


def add_final_method_decorator(
    source: str,
    project_sources: list[str] | None = None,
    *,
    refuse_public: bool = False,
) -> str | None:
    """Seal ``@typing.final`` on every sealable method in ``source``, or ``None``
    when nothing changes.

    ``project_sources`` is the whole-project source set the subclass
    over-approximation scans (it MUST include ``source`` itself); when ``None``,
    ``source`` is scanned in isolation (the conservative single-module floor). When
    ``refuse_public`` is set (the objective sets it — the file reaching it is a real
    importable module), a method of a PUBLIC-surface CLASS (an ``__all__``-listed
    name, or — with no ``__all__`` — a top-level non-underscore class) is REFUSED:
    external code we cannot see may subclass the class and override the method, which
    ``@final`` would make a type checker reject — a false "final" the project-own scan
    and the (no-op-decorator) suite can never catch. Methods are decorated in REVERSE
    source order so earlier line spans stay valid, then the ``from typing import
    final`` import is ensured once (only when the bare ``@final`` form needs it).
    Deterministic and idempotent (an already-``@final`` method is not re-touched); the
    result is re-``ast.parse``d before return, so a malformed rewrite yields ``None``
    rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    scan_sources = [source] if project_sources is None else project_sources
    ctx = _module_context(source, scan_sources, refuse_public=refuse_public)

    methods = _all_sealable_methods(tree, ctx)
    if not methods:
        return None

    text = _decorator_text(ctx.binding)
    out_lines = list(ctx.lines)
    for fn in sorted(methods, key=lambda fn: fn.lineno, reverse=True):
        out_lines = _insert_decorator(out_lines, fn, text)
    if _needs_import(ctx.binding):
        out_lines = _ensure_final_import(out_lines)
    return rejoin_guarded(source, out_lines)
