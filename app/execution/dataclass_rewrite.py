"""Convert a hand-written boilerplate ``__init__`` class into a ``@dataclass``.

The boilerplate every student and team writes by hand: a class whose
``__init__`` does nothing but copy its parameters onto ``self`` —
``self.x = x`` for each parameter, in order, and nothing else. Python's
``@dataclass`` generates exactly that constructor (plus ``__repr__`` and
``__eq__``) from a list of typed fields, so the hand-written ``__init__`` is
pure noise. :func:`rewrite_dataclasses` LANDS the cleaner, behaviour-equivalent
form: it adds ``@dataclass`` (and ``from dataclasses import dataclass``), emits
one field per parameter (preserving order, the parameter's annotation if
present, and its default), and DELETES the redundant ``__init__``.

Strict by design — anything that is not pure field-assignment boilerplate is
REFUSED (the class is left exactly as it was), because only a pure ``self.x =
x`` constructor is provably reproduced by ``@dataclass``:

  - the body must be EXACTLY ``self.<name> = <name>`` assignments, one per
    non-self parameter, names matching the parameters, in order (a leading
    docstring is tolerated, nothing else — no validation ``if``, no computed
    attribute, no call);
  - no ``*args`` / ``**kwargs`` (a dataclass field cannot express them);
  - no base classes (a non-dataclass base breaks the generated ``__init__``);
  - no class-level decorator already present (a decorator may conflict, and an
    existing ``@dataclass`` is left alone — idempotent);
  - an EMPTY mutable literal default (``[]`` / ``{}`` / ``set()``) becomes
    ``field(default_factory=...)`` so per-instance state stays correct (the
    classic dataclass footgun handled for the user); a NON-EMPTY mutable default
    (``[1, 2]``, ``{1: 2}``, ``list([1])`` …) is REFUSED — emitting it verbatim
    is invalid (a dataclass raises ``ValueError`` for a mutable default at
    import) and a ``default_factory`` rewrite would drop its contents and change
    shared-default into fresh-per-instance, so neither preserves behaviour.

Equality/hashing are preserved exactly. ``@dataclass`` defaults to ``eq=True``,
which would give a previously-identity class value-``==`` AND make it unhashable
(``__hash__`` set to ``None``) — a behaviour change a green suite can miss. So a
class that defines NO ``__eq__`` is emitted as ``@dataclass(eq=False)`` (identity
``==`` and hashability preserved); a class that defines its own ``__eq__`` keeps
the default ``@dataclass`` because a dataclass never overwrites a user-defined
``__eq__``/``__hash__`` (the converter deletes only the boilerplate ``__init__``).

Behaviour-equivalent: positional construction, keyword construction, defaults,
attribute access, ``==``, and ``hash()`` all survive because ``@dataclass``
regenerates the same ``__init__`` the boilerplate spelled out by hand (and the
``eq=`` argument keeps equality identical). Deterministic (AST-only,
stable source order, no clock/random), stdlib-only, zero-token, idempotent (an
already-``@dataclass`` class — or any class that is not pure boilerplate — is a
byte-identical no-op). The result is re-``ast.parse``d before it is returned.
"""

from __future__ import annotations

import ast
import re

__all__ = [
    "rewrite_dataclasses",
    "convertible_classes",
    "is_boilerplate_init",
]

# A PEP-263 source-encoding cookie (``# -*- coding: utf-8 -*-`` / ``# coding:
# utf-8`` / ``# coding=utf-8``). The interpreter honours this magic comment ONLY
# on physical line 1 or 2, so the prologue scan recognises it only at those
# positions — a normal comment that merely mentions ``coding`` further down the
# file is never mistaken for one.
_CODING_COOKIE = re.compile(r"coding[:=]\s*([-\w.]+)")

# Mutable literal defaults that MUST become ``field(default_factory=...)`` —
# sharing one list/dict/set across instances is the classic dataclass bug.
_EMPTY_FACTORY: dict[str, str] = {
    "list": "list",
    "dict": "dict",
    "set": "set",
}


def _find_init(cls: ast.ClassDef) -> ast.FunctionDef | None:
    """The class's own ``__init__`` def, or ``None`` if it has none (or it is
    an async def, which a plain dataclass cannot reproduce)."""
    for stmt in cls.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
            return stmt
    return None


def _init_params(init: ast.FunctionDef) -> list[ast.arg] | None:
    """The non-self positional parameters of ``__init__``, or ``None`` when the
    signature is one a dataclass cannot reproduce (``*args``/``**kwargs``,
    keyword-only params, positional-only params, or a missing leading
    ``self``)."""
    args = init.args
    if args.vararg is not None or args.kwarg is not None:
        return None  # *args / **kwargs — not expressible as fields
    if args.kwonlyargs or args.posonlyargs:
        return None  # keyword-only / positional-only — out of scope
    positional = args.args
    if not positional or positional[0].arg != "self":
        return None
    return positional[1:]


def _assignment_target_name(stmt: ast.stmt) -> str | None:
    """For a ``self.<name> = <value>`` statement, the ``<name>``; else ``None``.

    Refuses anything that is not a single plain ``self.<attr> = <expr>``:
    augmented/annotated assignment, tuple targets, a non-``self`` target, or a
    nested attribute (``self.a.b``)."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Attribute):
        return None
    if not isinstance(target.value, ast.Name) or target.value.id != "self":
        return None
    return target.attr


def _is_pure_param_copy(stmt: ast.stmt, param_name: str) -> bool:
    """True when ``stmt`` is exactly ``self.<param_name> = <param_name>`` — the
    boilerplate copy of one parameter onto its identically-named attribute."""
    if _assignment_target_name(stmt) != param_name:
        return False
    value = stmt.value  # type: ignore[attr-defined]
    return isinstance(value, ast.Name) and value.id == param_name


def is_boilerplate_init(cls: ast.ClassDef) -> bool:
    """True when ``cls`` is a PURE field-assignment class safe to convert.

    Strict: an ``__init__(self, p1, p2=...)`` whose body is exactly one
    ``self.<p> = <p>`` per parameter (in order, names matching), with an
    optional leading docstring and nothing else; no ``*args``/``**kwargs``, no
    base classes, no existing class decorator. Anything else is refused."""
    if cls.bases or cls.keywords or cls.decorator_list:
        return False  # a base class or any decorator breaks dataclass semantics
    init = _find_init(cls)
    if init is None or init.decorator_list:
        return False
    params = _init_params(init)
    if not params:
        return False  # no convertible params (or an unrepresentable signature)

    if not _class_body_is_field_safe(cls, init, {p.arg for p in params}):
        return False

    body = list(init.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]  # a docstring is tolerated

    if len(body) != len(params):
        return False  # extra statements (or missing copies) — real logic
    for stmt, param in zip(body, params):
        if not _is_pure_param_copy(stmt, param.arg):
            return False
    return True


def _class_body_names(stmt: ast.stmt) -> list[str]:
    """The top-level class-body names a single statement BINDS — assignment
    targets and the target of an annotated assignment. Used to detect a
    class-level attribute that would collide with an ``__init__`` parameter."""
    names: list[str] = []
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    elif isinstance(stmt, ast.AnnAssign):
        if isinstance(stmt.target, ast.Name):
            names.append(stmt.target.id)
    return names


def _class_defines_eq(cls: ast.ClassDef) -> bool:
    """True when ``cls`` defines ``__eq__`` ITSELF — as a method (sync/async) or
    a class-body binding (``__eq__ = ...``).

    Drives the decorator's ``eq=`` argument so ``==`` is preserved exactly:

      - a class with NO ``__eq__`` has IDENTITY equality and is hashable
        (Python's default), so it must become ``@dataclass(eq=False)`` — the
        generated ``eq=True`` would flip ``==`` from identity to value-equality
        AND set ``__hash__ = None`` (unhashable), an observable change;
      - a class that DOES define ``__eq__`` keeps the default ``@dataclass``
        (``eq=True``): a dataclass never overwrites a user-defined ``__eq__`` (or
        ``__hash__``), so its ``==``/``hash()`` survive verbatim — the converter
        deletes only the boilerplate ``__init__``, never ``__eq__``/``__hash__``.
    """
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            stmt.name == "__eq__"
        ):
            return True
        if "__eq__" in _class_body_names(stmt):
            return True
    return False


def _class_body_is_field_safe(
    cls: ast.ClassDef, init: ast.FunctionDef, param_names: set[str]
) -> bool:
    """True when no NON-``__init__`` top-level class-body statement would change
    dataclass semantics. Refuses when:

      - a class-level attribute binds a name equal to an ``__init__`` parameter —
        ``@dataclass`` would read that binding as the field's DEFAULT, turning a
        required parameter into an optional one (a behaviour change);
      - ``__slots__`` is declared — ``@dataclass`` + slots changes semantics
        (the generated default would clash with the slot descriptor)."""
    for stmt in cls.body:
        if stmt is init:
            continue
        bound = _class_body_names(stmt)
        if "__slots__" in bound:
            return False  # dataclass + __slots__ — out of scope
        if any(name in param_names for name in bound):
            return False  # class attr collides with a param → becomes a default
    return True


# Sentinel: the default is NOT a mutable container, so it is reproduced verbatim
# (kept distinct from ``None``, which means "mutable but unsafe — refuse").
_NOT_MUTABLE = object()


def _is_empty_container_literal(default: ast.expr) -> bool | None:
    """Whether ``default`` is an EMPTY container literal/constructor, or ``None``
    if it is not a container at all. ``True`` -> safe ``default_factory``;
    ``False`` -> a NON-EMPTY mutable default (refuse); ``None`` -> not a
    container (caller reproduces it verbatim).

    Empty: ``[]`` / ``{}`` / ``set()`` / ``list()`` / ``dict()``. Non-empty:
    ``[1]`` / ``{1: 2}`` / ``{1, 2}`` (a set literal is always non-empty — there
    is no empty-set literal) / ``list([1])`` / ``dict(a=1)``."""
    if isinstance(default, ast.List):
        return not default.elts
    if isinstance(default, ast.Dict):
        return not default.keys
    if isinstance(default, ast.Set):
        return False  # no empty-set literal exists; a non-empty one is mutable
    if isinstance(default, ast.Call) and isinstance(default.func, ast.Name):
        if default.func.id in _EMPTY_FACTORY:
            return not default.args and not default.keywords
    return None


def _mutable_default_field(default: ast.expr) -> str | None | object:
    """For a mutable-container default: the ``field(default_factory=...)`` text
    when EMPTY, ``None`` when NON-EMPTY (refuse — see :func:`_default_field_text`),
    or :data:`_NOT_MUTABLE` when ``default`` is not a container at all."""
    empty = _is_empty_container_literal(default)
    if empty is None:
        return _NOT_MUTABLE
    if not empty:
        return None  # non-empty mutable default — neither verbatim nor factory
    factory = _factory_name(default)
    return f"field(default_factory={factory})"


def _factory_name(default: ast.expr) -> str:
    """The ``default_factory`` name for an EMPTY container default (``list`` /
    ``dict`` / ``set``)."""
    if isinstance(default, ast.List):
        return "list"
    if isinstance(default, ast.Dict):
        return "dict"
    if isinstance(default, ast.Set):
        return "set"
    func = default.func  # type: ignore[attr-defined]
    return _EMPTY_FACTORY[func.id]


def _default_field_text(default: ast.expr) -> str | None:
    """The source text for a parameter default, or ``None`` if it cannot be
    safely reproduced.

    An EMPTY mutable literal (``[]``/``{}``/``set()``/``list()``/``dict()``)
    becomes ``field(default_factory=...)`` so per-instance state stays correct.
    A NON-EMPTY mutable literal (``[1, 2]``, ``{1: 2}``, ``{1, 2}``,
    ``list([1])`` …) is REFUSED (``None``): emitting it verbatim is invalid (a
    dataclass raises ``ValueError`` for a mutable default AT IMPORT), and
    converting it to ``default_factory`` would drop its contents AND change
    shared-mutable-default behaviour into fresh-per-instance — neither is
    behaviour-preserving, so the whole class is refused. Any other (immutable)
    default is emitted via ``ast.unparse`` verbatim."""
    mutable = _mutable_default_field(default)
    if mutable is not _NOT_MUTABLE:
        return mutable  # type: ignore[return-value]
    try:
        return ast.unparse(default)
    except (ValueError, AttributeError):
        return None


def _param_defaults(init: ast.FunctionDef) -> dict[int, ast.expr]:
    """Map of positional-(after-self) index -> default expression. Defaults
    align to the TAIL of the parameter list, so the first defaulted index is
    ``len(params) - len(defaults)``."""
    params = init.args.args[1:]  # drop self
    defaults = init.args.defaults
    out: dict[int, ast.expr] = {}
    if defaults:
        offset = len(params) - len(defaults)
        for i, default in enumerate(defaults):
            out[offset + i] = default
    return out


def _field_lines(
    init: ast.FunctionDef, params: list[ast.arg], indent: str
) -> list[str] | None:
    """One ``name: type [= default]`` field line per parameter, or ``None`` if
    any default cannot be reproduced. Uses the parameter's own annotation when
    present, falling back to a bare ``typing.Any`` so the field is still a valid
    dataclass field (value-preserving — it only adds an annotation)."""
    defaults = _param_defaults(init)
    lines: list[str] = []
    for idx, param in enumerate(params):
        if param.annotation is not None:
            try:
                ann = ast.unparse(param.annotation)
            except (ValueError, AttributeError):
                return None
        else:
            ann = "Any"
        line = f"{indent}{param.arg}: {ann}"
        if idx in defaults:
            default_text = _default_field_text(defaults[idx])
            if default_text is None:
                return None
            line += f" = {default_text}"
        lines.append(line)
    return lines


def _class_indent(cls: ast.ClassDef, lines: list[str]) -> str:
    """The body indentation of ``cls`` (the leading whitespace of its first body
    statement). Defaults to four spaces if it cannot be read."""
    first = cls.body[0]
    line = lines[first.lineno - 1]
    return line[: len(line) - len(line.lstrip())] or "    "


def _needs_any(field_lines: list[str]) -> bool:
    """True when any field fell back to the ``Any`` annotation (so the import
    must be ensured)."""
    return any(line.split(":", 1)[1].lstrip().startswith("Any") for line in field_lines)


def _needs_field_import(field_lines: list[str]) -> bool:
    """True when any field uses ``field(...)`` (so ``field`` must be imported)."""
    return any("field(" in line for line in field_lines)


def _rewrite_one_class(cls: ast.ClassDef, lines: list[str]) -> tuple[
    int, int, list[str], bool, bool
] | None:
    """Compute the replacement for ONE convertible class.

    Returns ``(start_idx, end_idx, new_lines, needs_field, needs_any)`` where
    ``[start_idx:end_idx)`` is the 0-based slice of ``lines`` to replace, or
    ``None`` if the class is not convertible. The new lines are the class with
    a ``@dataclass`` decorator, the emitted fields, and the ``__init__``
    deleted (all other body statements preserved)."""
    if not is_boilerplate_init(cls):
        return None
    init = _find_init(cls)
    assert init is not None
    params = _init_params(init)
    assert params is not None

    indent = _class_indent(cls, lines)
    field_lines = _field_lines(init, params, indent)
    if field_lines is None:
        return None

    header_line = lines[cls.lineno - 1]
    decorator_indent = header_line[: len(header_line) - len(header_line.lstrip())]
    header_idx = cls.lineno - 1
    init_start, init_end = _node_line_span(init)

    # The class header line (``class Foo:``), then a LEADING DOCSTRING (kept as
    # the first body statement so it stays ``__doc__`` — emitting it after the
    # fields would let ``@dataclass`` overwrite ``__doc__`` with its generated
    # ``Foo(...)`` signature, a wrong-but-verified behaviour change), then the
    # fields, then everything below __init__ (other methods preserved).
    body_first = cls.body[0].lineno - 1
    pre = lines[header_idx:body_first]
    doc_lines, body_start = _leading_docstring_lines(cls, lines, body_first)
    above = _body_lines_excluding(lines, cls, init, body_start, init_start, init_end)

    # ``eq=False`` preserves identity-``==`` + hashability when the class has no
    # ``__eq__``; a class that defines its own ``__eq__`` keeps the default
    # ``@dataclass`` (a dataclass never overwrites a user ``__eq__``/``__hash__``).
    decorator = "@dataclass" if _class_defines_eq(cls) else "@dataclass(eq=False)"
    new_lines = [f"{decorator_indent}{decorator}"]
    new_lines.extend(pre)
    new_lines.extend(doc_lines)  # docstring stays at body position 0
    new_lines.extend(field_lines)
    if above and above[0].strip():
        new_lines.append("")  # one blank line between fields and kept methods
    new_lines.extend(above)

    needs_field = _needs_field_import(field_lines)
    needs_any = _needs_any(field_lines)
    cls_start, cls_end = _node_line_span(cls)
    return cls_start, cls_end, new_lines, needs_field, needs_any


def rejoin_guarded(source: str, out_lines: list[str]) -> str | None:
    """Re-join ``out_lines`` into module text (preserving ``source``'s trailing
    newline), then the standard never-land-broken-Python epilogue: ``None`` when
    the result is byte-identical to ``source`` (no change) or when it does not
    ``ast.parse`` (a malformed rewrite is dropped, not landed). The single source
    of truth for the "splice, preserve newline, re-parse guard" tail every
    line-splicing rewrite shares (``rewrite_dataclasses`` and
    :mod:`app.execution.future_annotations`)."""
    trailing = "\n" if source.endswith("\n") else ""
    result_text = "\n".join(out_lines) + trailing
    if result_text == source:
        return None
    try:
        ast.parse(result_text)
    except (SyntaxError, ValueError):
        return None  # never land broken Python
    return result_text


def apply_reverse_line_inserts(
    source: str, lines: list[str], edits: list[tuple[int, list[str]]]
) -> str | None:
    """Apply ``(insert_index, new_lines)`` block INSERTS to ``lines`` and return the
    guarded module text, or ``None`` when ``edits`` is empty.

    The shared tail of every "splice whole blocks at body positions" rewrite
    (``dunder_synthesis.synthesize_dunders`` / ``hashable_eq.seal_hashable_eq``): the
    inserts are applied in REVERSE index order so each earlier line span stays valid as
    later ones grow, then :func:`rejoin_guarded` re-joins (preserving the trailing
    newline) and re-``ast.parse``s so a malformed splice yields ``None`` rather than
    landing broken Python. An EMPTY ``edits`` is a no-op (``None``). Pure: it never
    reads the clock / random / disk, and sorting by the integer index is total and
    stable, so the result is deterministic."""
    if not edits:
        return None
    edits.sort(key=lambda e: e[0], reverse=True)  # reverse so indices stay valid
    out_lines = list(lines)
    for index_at, body in edits:
        out_lines[index_at:index_at] = body
    return rejoin_guarded(source, out_lines)


def _node_line_span(node: ast.AST) -> tuple[int, int]:
    """The 0-based ``[start, end)`` line slice a node occupies."""
    start = node.lineno - 1  # type: ignore[attr-defined]
    end = getattr(node, "end_lineno", node.lineno)  # type: ignore[attr-defined]
    return start, end


def _leading_docstring_lines(
    cls: ast.ClassDef, lines: list[str], body_first: int
) -> tuple[list[str], int]:
    """When ``cls`` opens with a docstring on its OWN line(s), its source lines
    and the index just PAST it; otherwise ``([], body_first)``.

    The docstring must stay the FIRST body statement so it remains the class's
    ``__doc__`` — emitting it after the generated fields would let ``@dataclass``
    replace ``__doc__`` with its synthesised ``Foo(...)`` signature. A class with
    no leading docstring yields no docstring lines and an unchanged body start,
    so its rewrite is byte-identical to before. A docstring sharing the ``class
    Foo:`` header line (which a convertible class never has) is left in place so
    the header is not dropped."""
    if ast.get_docstring(cls) is None:
        return [], body_first
    first = cls.body[0]
    if not isinstance(first, ast.Expr):
        return [], body_first  # not a bare string-expression statement
    doc_start, doc_end = _node_line_span(first)
    if doc_start <= cls.lineno - 1:
        return [], body_first  # docstring shares the class header line
    return lines[doc_start:doc_end], doc_end


def _body_lines_excluding(
    lines: list[str],
    cls: ast.ClassDef,
    init: ast.FunctionDef,
    body_start: int,
    init_start: int,
    init_end: int,
) -> list[str]:
    """Every body line from ``body_start`` (which already skips any leading
    docstring) EXCEPT the ``__init__`` definition. Walks the class body lines,
    dropping the ``__init__`` span and any blank line directly adjacent to it so
    no double blank survives."""
    _, cls_end = _node_line_span(cls)
    kept: list[str] = []
    i = body_start
    while i < cls_end:
        if init_start <= i < init_end:
            i = init_end
            # skip a single trailing blank line left by the removed __init__
            while i < cls_end and not lines[i].strip():
                i += 1
            continue
        kept.append(lines[i])
        i += 1
    # When the class had ONLY an __init__, ``kept`` is empty — the emitted
    # fields already form a valid class body, so nothing extra is needed.
    return kept


def convertible_classes(source: str) -> list[str]:
    """The names of top-level classes in ``source`` that are convertible — pure
    boilerplate-``__init__`` classes safe to turn into ``@dataclass``. Sorted by
    source order. Returns ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and is_boilerplate_init(node):
            out.append(node.name)
    return out


def _ensure_imports(
    lines: list[str], needs_field: bool, needs_any: bool
) -> list[str]:
    """Ensure every import the rewrite relies on is present, as ONE inserted
    block (no doubled blank lines).

    Ensures ``from dataclasses import dataclass`` (plus ``field`` when a
    ``field(default_factory=...)`` was emitted) and, when any field fell back to
    the ``Any`` annotation, ``from typing import Any``. Idempotent: an existing
    ``dataclasses`` import is widened in place (only the missing names added);
    an already-importable ``Any`` is left alone; a fresh import block is
    inserted after the module docstring / ``__future__`` imports."""
    needed = {"dataclass"}
    if needs_field:
        needed.add("field")

    new_imports: list[str] = []
    if needs_any and not _existing_typing_any(lines):
        new_imports.append("from typing import Any")

    if _existing_dataclasses_import(lines) is not None:
        lines = _widen_existing_import(lines, needed)
    else:
        new_imports.append("from dataclasses import " + ", ".join(sorted(needed)))

    if not new_imports:
        return lines
    insert_at = _import_insertion_index(lines)
    block = list(new_imports)
    if insert_at < len(lines) and lines[insert_at].strip():
        block.append("")  # keep a blank line before the following code
    return lines[:insert_at] + block + lines[insert_at:]


def _existing_dataclasses_import(lines: list[str]) -> int | None:
    """Index of a top-level ``from dataclasses import ...`` line, or ``None``."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from dataclasses import "):
            return i
    return None


def _widen_existing_import(lines: list[str], needed: set[str]) -> list[str]:
    """Add any missing names to an existing ``from dataclasses import ...``."""
    idx = _existing_dataclasses_import(lines)
    if idx is None:
        return lines
    line = lines[idx]
    imported = {
        name.strip()
        for name in line.split("import", 1)[1].split(",")
        if name.strip()
    }
    missing = needed - imported
    if not missing:
        return lines  # already covers everything — idempotent no-op
    merged = sorted(imported | needed)
    new_lines = list(lines)
    new_lines[idx] = "from dataclasses import " + ", ".join(merged)
    return new_lines


def _is_coding_cookie(line: str) -> bool:
    """True for a PEP-263 source-encoding comment (``# -*- coding: utf-8 -*-`` or
    the bare ``# coding: utf-8`` / ``# coding=utf-8`` form).

    Matched only on a ``#`` comment line whose body carries the standard
    ``coding[:=]<name>`` token (the :data:`_CODING_COOKIE` regex), so an ordinary
    comment that merely mentions the word ``coding`` in prose is not mistaken for
    an encoding declaration. The caller checks it only on physical line 1 or 2
    (the only positions PEP 263 honours)."""
    stripped = line.strip()
    if not stripped.startswith("#"):
        return False
    return _CODING_COOKIE.search(stripped) is not None


def _prologue_length(lines: list[str]) -> int:
    """The count of leading lines that MUST stay at the very top of the file: a
    ``#!`` shebang on physical line 1, then a PEP-263 coding cookie on line 1 or 2.

    Returns 0, 1, or 2 — these lines carry meaning ONLY at the top, so each is
    recognised solely at its sanctioned position. A file with neither yields 0, so
    the insertion index below is byte-identical to its pre-fix behaviour. (Mirrors
    :func:`app.execution.module_exports._prologue_length`, kept local here to avoid
    an import cycle — ``module_exports`` imports this module, not the reverse.)"""
    prologue = 0
    if prologue < len(lines) and lines[prologue].startswith("#!"):
        prologue += 1  # a shebang only counts on physical line 1
    if prologue < len(lines) and prologue <= 1 and _is_coding_cookie(lines[prologue]):
        prologue += 1  # a PEP-263 coding cookie only counts on line 1 or 2
    return prologue


def _import_insertion_index(lines: list[str]) -> int:
    """Where a new import should go: after a leading shebang / PEP-263 coding
    cookie, a module docstring, and any ``from __future__`` imports, before the
    first real statement.

    The prologue (a ``#!`` shebang on line 1 and a coding cookie on line 1/2) is
    stepped over FIRST — those lines are inert ONLY at the top of the file, so an
    import inserted above them would demote a real cookie past the line-1/2 window
    and silently disable it. When there is no shebang/cookie the prologue length is
    0 and the result is byte-identical to the docstring/``__future__`` behaviour."""
    n = len(lines)
    i = _prologue_length(lines)  # never land an import above a shebang / cookie
    # Skip a leading module docstring (single- or triple-quoted block).
    while i < n and not lines[i].strip():
        i += 1
    if i < n and (lines[i].lstrip().startswith(('"""', "'''", '"', "'"))):
        i = _skip_docstring(lines, i)
    # Skip blank lines and __future__ imports.
    while i < n and (not lines[i].strip()
                     or lines[i].strip().startswith("from __future__")):
        i += 1
    return i


def _skip_docstring(lines: list[str], start: int) -> int:
    """Index just past a module docstring beginning at ``start``."""
    first = lines[start].lstrip()
    for quote in ('"""', "'''"):
        if first.startswith(quote):
            if first.count(quote) >= 2 and len(first) > len(quote):
                return start + 1  # single-line triple-quoted
            i = start + 1
            while i < len(lines):
                if quote in lines[i]:
                    return i + 1
                i += 1
            return i
    return start + 1  # a single-quoted one-line docstring


def _collect_class_edits(
    tree: ast.Module, lines: list[str]
) -> tuple[list[tuple[int, int, list[str]]], bool, bool]:
    """The ``(start, end, new_lines)`` replacement for every convertible
    top-level class, plus whether any field needs ``field``/``Any`` imports."""
    edits: list[tuple[int, int, list[str]]] = []
    needs_field = False
    needs_any = False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        result = _rewrite_one_class(node, lines)
        if result is None:
            continue
        start, end, new_lines, cls_field, cls_any = result
        edits.append((start, end, new_lines))
        needs_field = needs_field or cls_field
        needs_any = needs_any or cls_any
    return edits, needs_field, needs_any


def rewrite_dataclasses(source: str) -> str | None:
    """Convert every pure boilerplate-``__init__`` top-level class in ``source``
    to a ``@dataclass``, or return ``None`` when nothing changes.

    Deterministic and idempotent: classes are rewritten in REVERSE source order
    so earlier line spans stay valid, the ``dataclasses`` import is ensured once,
    and the result is re-``ast.parse``d before return (a defensive guard — a
    malformed rewrite yields ``None`` rather than landing broken Python)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None

    lines = source.splitlines()
    edits, needs_field, needs_any = _collect_class_edits(tree, lines)
    if not edits:
        return None

    # Apply in reverse so earlier spans stay valid.
    edits.sort(key=lambda e: e[0], reverse=True)
    out_lines = list(lines)
    for start, end, new_lines in edits:
        out_lines[start:end] = new_lines

    out_lines = _ensure_imports(out_lines, needs_field, needs_any)
    return rejoin_guarded(source, out_lines)


def _existing_typing_any(lines: list[str]) -> bool:
    """True when ``Any`` is already importable (``from typing import ... Any``
    or ``import typing``)."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("from typing import ") and _imports_name(stripped, "Any"):
            return True
        if stripped in ("import typing", "import typing as t"):
            return True
    return False


def _imports_name(import_line: str, name: str) -> bool:
    names = {
        part.strip()
        for part in import_line.split("import", 1)[1].split(",")
        if part.strip()
    }
    return name in names
