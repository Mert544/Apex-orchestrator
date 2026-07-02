"""Add ``typing.Final`` to a top-level module CONSTANT (``NAME = <literal>``)
that is PROVABLY never REBOUND anywhere in the project's own source.

``typing.Final`` is a PURE runtime no-op — CPython does NOT enforce it. The name
is a type-checker-only marker: annotating ``NAME: Final = 3`` compiles and runs
byte-for-byte the same as ``NAME = 3`` (the annotation lands in
``__annotations__`` and is otherwise inert). So marking a never-rebound module
constant ``Final`` is the strongest possible behaviour-preservation story: there
is *nothing* at runtime to break — unlike a ``let``->``const`` rewrite, whose
wrong application throws at runtime. The annotation documents and (for a type
checker) ENFORCES a real design intent — "this is a constant, do not rebind it" —
the one-line annotation a careful author writes by hand, paying down a
``pylint`` ``invalid-name`` / immutability-contract finding. Where a linter only
FLAGS the opportunity, :func:`add_final_constant` WRITES it, deterministically and
for free.

SOUNDNESS — the only failure mode. Because the annotation has no runtime effect, a
green suite proves nothing *behavioural*; but it also cannot break anything. The
single honesty risk is a FALSE "final" claim — annotating ``Final`` a name that IS
rebound somewhere (a type checker would then reject the reassignment). That is
closed STRUCTURALLY, not by the suite: a whole-project over-approximate REBIND
scan (:func:`rebound_names`, reused over the same project source set
``freeze-dataclass`` scans) collects every name ever bound by anything OTHER than
the single ``NAME = <literal>`` declaration — a later plain ``NAME = ...``, an
annotated ``NAME: T = ...``, an augmented ``NAME += ...``, a ``for NAME in`` /
``with x as NAME`` / walrus ``NAME :=`` target, a ``def NAME`` / ``class NAME``, a
parameter named ``NAME``, an import binding ``NAME``, or a ``global NAME`` inside a
function — and a name is a candidate ONLY when it is absent from that set. The
over-approximation may refuse an unrelated same-named LOCAL in another scope
(soundness over recall — a module-scope name and a function-local of the same name
are indistinguishable to this name-only scan), but never misses a real rebind.

``Final`` only forbids REBINDING, never in-place MUTATION: ``NAMES: Final =
["a"]`` followed by ``NAMES.append("b")`` is perfectly legal (the ``.append``
mutates the list, it does not rebind ``NAMES``), so an in-place mutation of the
value is NOT a refusal — the rebind scan looks only at ``Store``/``Del`` on the
NAME itself, never at attribute/subscript stores whose base happens to be the name.

A constant is annotated ``Final`` ONLY when ALL of these hold (otherwise an honest
no-op):

  - it is a TOP-LEVEL ``NAME = <literal>`` / ``NAME: T = <literal>`` whose NAME is
    UPPER_SNAKE_CASE (the PEP-8 module-constant convention — a lower-case name is
    an ordinary variable, out of scope) — a constant a linter would flag;
  - the value is a LITERAL — an ``ast.Constant`` (str / bytes / number / bool /
    ``None``), optionally under a unary ``+`` / ``-`` on a numeric literal
    (``-1`` / ``+2.0``). A computed / call / name / container value is out of
    scope (not a "literal constant" — refuse-on-ambiguity);
  - the NAME is NOT REBOUND anywhere in the project (the structural never-rebound
    proof above — tests INCLUDED via the objective's whole-project scan set);
  - it is NOT already annotated ``Final`` / ``typing.Final`` (idempotent: a second
    run sees the annotation it landed and is a byte-identical no-op);
  - the name ``Final`` can be bound UNAMBIGUOUSLY to ``typing.Final`` in the
    module: either via an existing/added ``from typing import Final`` (no local
    shadow, no differently-sourced import) emitting ``NAME: Final``, OR — when
    ``Final`` is shadowed but ``typing`` is provably bound (``import typing``, no
    shadow) — emitting ``NAME: typing.Final``. If NEITHER form can be proven,
    refuse (the same ``final``-shadow discipline add-final uses).

``typing.Final`` exists since Python 3.8, so this lands on the project's 3.10
floor with NO version gate. Deterministic (pure AST walk + line splice, no
clock/random), stdlib-only, zero-token, idempotent. Reuses
:func:`app.execution.dataclass_rewrite._import_insertion_index` /
:func:`~app.execution.dataclass_rewrite.rejoin_guarded` for the canonical import
spot and the "splice, preserve newline, re-``ast.parse`` guard" epilogue, and the
``Final``-binding provability machinery mirrors
:mod:`app.execution.final_marker`'s ``_final_binding`` (adapted for the ``Final``
annotation name rather than the ``final`` decorator name).
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from app.execution.dataclass_rewrite import rejoin_guarded
from app.execution.final_marker import (
    _FinalBinding,
    _ensure_final_import,
    _final_binding as _final_marker_binding,
    _needs_import,
)

__all__ = [
    "add_final_constant",
    "finalizable_constants",
    "rebound_names",
    "assignment_is_final_annotated",
]


def _is_const_name(name: str) -> bool:
    """True when ``name`` is the UPPER_SNAKE_CASE PEP-8 module-constant convention:
    at least one letter, only ``A-Z`` / ``0-9`` / ``_``, and not a dunder.

    A dunder (``__all__``, ``__version__``) is excluded — it is module metadata a
    tool reads, not a constant a reader thinks of as ``Final``; a lower-case name
    (``config`` / ``x``) is an ordinary variable, out of scope. Requiring at least
    one ASCII letter rejects a pure ``_`` / digit name."""
    if not name or name.startswith("__"):
        return False
    if not any("A" <= ch <= "Z" for ch in name):
        return False
    return all(ch == "_" or ch.isdigit() or "A" <= ch <= "Z" for ch in name)


def _is_literal_value(value: ast.expr) -> bool:
    """True when ``value`` is a LITERAL constant expression: an ``ast.Constant``
    (str / bytes / number / bool / ``None``), or a unary ``+`` / ``-`` on a NUMERIC
    ``ast.Constant`` (``-1`` / ``+2.0``).

    Deliberately narrow — a ``Name`` / ``Call`` / container / f-string value is NOT
    a plain literal constant (refuse-on-ambiguity). ``Final`` would still be a
    runtime no-op on those, but the objective's contract is a LITERAL module
    constant, so a non-literal value is out of scope."""
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)):
        operand = value.operand
        return isinstance(operand, ast.Constant) and isinstance(
            operand.value, (int, float, complex)) and not isinstance(
            operand.value, bool)
    return False


def _annotation_is_final(annotation: ast.expr | None) -> bool:
    """True when ``annotation`` is a ``Final`` / ``Final[...]`` / ``typing.Final``
    (or ``typing.Final[...]``) — the idempotency guard (a second run sees it and
    stops). A SHAPE check only (it does not prove the name binds ``typing.Final``);
    an already-``Final``-shaped assignment is left alone regardless of provenance."""
    if annotation is None:
        return False
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name):
        return target.id == "Final"
    return isinstance(target, ast.Attribute) and target.attr == "Final"


def assignment_is_final_annotated(node: ast.stmt) -> bool:
    """True when ``node`` is an ``AnnAssign`` whose annotation is already
    ``Final``-shaped (see :func:`_annotation_is_final`)."""
    return isinstance(node, ast.AnnAssign) and _annotation_is_final(node.annotation)


class _ConstAssign(NamedTuple):
    """A finalizable top-level constant assignment: the statement ``node``, the
    constant ``name``, and the existing annotation ``expr`` (``None`` for a plain
    ``Assign``, else the ``AnnAssign``'s declared type to preserve as
    ``Final[<expr>]``)."""

    node: ast.stmt
    name: str
    annotation: ast.expr | None


def _const_assign(node: ast.stmt) -> _ConstAssign | None:
    """``node`` as a candidate constant assignment, or ``None``.

    Accepts a plain ``NAME = <literal>`` (a single ``Name`` target) and an
    annotated ``NAME: T = <literal>`` (a ``Name`` target WITH a value), both with an
    UPPER_SNAKE_CASE constant name and a literal value. A multi-target
    (``A = B = 1``) / tuple-unpack (``A, B = ...``) assignment, an annotation-only
    ``NAME: T`` (no value), an already-``Final`` annotation, or a non-literal value
    is refused (``None``)."""
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        name = node.targets[0].id
        if not _is_const_name(name) or not _is_literal_value(node.value):
            return None
        return _ConstAssign(node=node, name=name, annotation=None)
    if isinstance(node, ast.AnnAssign):
        if node.value is None or not isinstance(node.target, ast.Name):
            return None
        if _annotation_is_final(node.annotation):
            return None  # already Final — idempotent no-op
        name = node.target.id
        if not _is_const_name(name) or not _is_literal_value(node.value):
            return None
        return _ConstAssign(node=node, name=name, annotation=node.annotation)
    return None


def _final_binding(tree: ast.AST) -> _FinalBinding:
    """The :class:`app.execution.final_marker._FinalBinding` for a module's ``tree``
    — which spelling of ``typing.Final`` is provable, and whether a fresh import may
    be added, for the ``Final`` ANNOTATION name.

    Reuses ``final_marker``'s name-parameterized :func:`_final_binding` (the SAME
    provability computation add-final uses for the ``final`` decorator, applied here
    to the capital ``Final`` annotation name — the single source of truth for "is this
    the stdlib ``typing.Final``, unshadowed, and can a fresh import be added"). The
    scanned name being ``Final`` (not ``final``) is the ONE thing that differs, so this
    is a one-line composition; the whole binding computation is shared."""
    return _final_marker_binding(tree, "Final")


def _bindings_in_tree(tree: ast.Module, keep_lineno: int | None) -> set[str]:
    """Every NAME bound anywhere in ``tree`` EXCEPT by the single top-level
    declaration statement at line ``keep_lineno`` — the per-module half of the
    whole-project rebind scan.

    Collects: any ``Store``/``Del``-context ``Name`` (a plain / annotated / augmented
    assignment target, a ``for`` / ``with as`` / walrus / comprehension target, a
    ``del NAME``), every ``def`` / ``async def`` / ``class`` name, every function
    parameter name, and every ``global`` / ``nonlocal`` declared name. The bindings
    introduced by the top-level statement at ``keep_lineno`` (the constant's OWN
    declaration) are skipped, so the constant's own ``NAME = <literal>`` does not
    count as a rebind of itself. ``keep_lineno`` is matched by the statement's source
    line (positions are identical across re-parses of the same bytes), which is why
    the scan re-parses each source itself rather than relying on a node identity that
    would not survive a separate parse. Deliberately name-only (it does not
    distinguish module scope from a function-local of the same name), so a same-named
    local elsewhere is an over-approximate refuse — soundness over recall.

    An IMPORT binding (``from mod import NAME`` / ``import NAME``) is deliberately NOT
    collected: an import binds ``NAME`` in the IMPORTER's own namespace — it does NOT
    rebind the source module's constant, so a type checker never rejects the source's
    ``Final`` because an importer imported (or even later reassigned its OWN copy of)
    the name. Counting imports would make EVERY imported constant look "rebound" and
    finalize nothing. A genuine reassignment in another module (a ``NAME = ...`` store
    there) IS still collected — a conservative over-refuse for an unrelated same-named
    global elsewhere, never a missed real own-module rebind.

    An attribute / subscript store (``NAME.attr = ...`` / ``NAME[k] = ...``) is NOT a
    binding of ``NAME`` — its target ``Name`` carries a ``Load`` context — so an
    in-place MUTATION of the constant's value never counts as a rebind (``Final``
    forbids rebinding, not mutation)."""
    keep_nodes: set[int] = set()
    if keep_lineno is not None:
        for stmt in tree.body:
            if stmt.lineno == keep_lineno:
                keep_nodes = set(map(id, ast.walk(stmt)))
                break
    bound: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in keep_nodes:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return bound


def rebound_names(sources: list[str], own_source: str,
                  keep: ast.stmt | None) -> set[str]:
    """Every NAME rebound anywhere across ``sources`` (the whole-project rebind
    over-approximation), EXCLUDING the single declaration ``keep`` in ``own_source``.

    For ``own_source`` the top-level declaration statement ``keep`` (matched by its
    source LINE, since ``sources`` re-parses each text and node identities do not
    survive a separate parse) has its own targets skipped — so the constant's own
    ``NAME = <literal>`` does not count against it; every OTHER binding of a name — in
    this module or any other — is collected. A source that does not parse contributes
    nothing (the same per-module parse guard every scan uses)."""
    keep_lineno = keep.lineno if keep is not None else None
    rebound: set[str] = set()
    for src in sources:
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        this_keep = keep_lineno if src == own_source else None
        rebound |= _bindings_in_tree(tree, this_keep)
    return rebound


class _ModuleContext(NamedTuple):
    """Per-module facts the finalizability gate needs: the module's physical
    ``lines`` (for the splice), the proven ``binding`` of ``typing.Final``, and the
    whole-project ``rebound`` name over-approximation (which already excludes the
    constant's own declaration)."""

    lines: list[str]
    binding: _FinalBinding
    rebound: set[str]


def _is_finalizable(cand: _ConstAssign, ctx: _ModuleContext) -> bool:
    """True when ``cand`` is a top-level constant safe to annotate ``Final``.

    Gates (all must hold): its NAME is NOT rebound anywhere in the project (the
    structural never-rebound proof — ``ctx.rebound`` already excludes the constant's
    own declaration), and ``typing.Final`` is provably spellable in the module (bare
    ``Final`` already importable, a dotted ``typing.Final`` provable, or a fresh
    ``from typing import Final`` safely addable). The literal-value / const-name /
    not-already-``Final`` gates were applied when the candidate was built."""
    if cand.name in ctx.rebound:
        return False
    b = ctx.binding
    return b.bare_ok or b.dotted_ok or b.can_add_import


def _annotation_text(binding: _FinalBinding, annotation: ast.expr | None) -> str:
    """The annotation to emit for the constant: ``Final`` when ``Final`` is (or will
    be) importable from ``typing``, else the dotted ``typing.Final``; carrying an
    existing declared type as ``Final[<type>]`` when the source was an annotated
    ``NAME: T = <literal>``.

    Prefers the bare ``Final`` (it pairs with the ``from typing import Final`` ensure
    step); the dotted form is used only when ``Final`` is shadowed but ``typing`` is
    bound. An existing annotation is re-emitted via ``ast.unparse`` inside the
    ``Final[...]`` subscript, preserving the declared type."""
    if binding.bare_ok or binding.can_add_import:
        head = "Final"
    else:
        head = "typing.Final"
    if annotation is None:
        return head
    return f"{head}[{ast.unparse(annotation)}]"


def _splice_annotation(
    node: ast.stmt, lines: list[str], annotation_text: str
) -> tuple[int, int, list[str]] | None:
    """The ``(start, end, new_lines)`` line-splice that inserts ``: <annotation_text>``
    between the constant's NAME and its ``=``, or ``None`` when the assignment's
    ``NAME <maybe: T> =`` header is not a clean SINGLE-line prefix we can splice.

    Only the ``NAME ... =`` head up to the FIRST top-level ``=`` is rewritten, so the
    value expression (which may span several lines) is left byte-identical. The whole
    node must start and its value must begin such that the ``=`` sits on the node's
    FIRST physical line — a header split across lines (rare for a constant) is refused
    rather than risk mis-splicing. Preserves the line's leading indentation (always
    empty at module top level, but kept for robustness)."""
    start = node.lineno - 1
    header = lines[start]
    # The value's own start column marks where the RHS begins; the `=` is the last
    # `=` before it on the header line. Refuse if the value does not begin on `start`.
    value = node.value  # type: ignore[attr-defined]
    if value is None or value.lineno - 1 != start:
        return None
    eq_index = header.rfind("=", 0, value.col_offset)
    if eq_index == -1:
        return None
    indent = header[: len(header) - len(header.lstrip())]
    name = node.target.id if isinstance(node, ast.AnnAssign) else node.targets[0].id  # type: ignore[union-attr]
    rest = header[eq_index:]  # from the `=` onward (keeps the RHS on this line)
    new_line = f"{indent}{name}: {annotation_text} {rest}"
    return start, start + 1, [new_line]


def _candidates(tree: ast.Module) -> list[_ConstAssign]:
    """Every top-level constant-assignment candidate in ``tree``, in source order
    (literal-value + const-name + not-already-``Final`` gated by ``_const_assign``)."""
    out: list[_ConstAssign] = []
    for node in tree.body:
        cand = _const_assign(node)
        if cand is not None:
            out.append(cand)
    return out


def finalizable_constants(source: str) -> list[str]:
    """The names of top-level constants in ``source`` finalizable when ``source`` is
    considered IN ISOLATION (single-module rebind scan).

    Convenience for tests / single-file reasoning: ``source`` is its own whole
    project, so the rebind scan sees only this module. Sorted by source order.
    Returns ``[]`` on a syntax error. The objective's real plan uses the WHOLE
    project, which can only ADD rebinds (a reassignment in another module), never
    remove them."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[str] = []
    for cand in _candidates(tree):
        rebound = rebound_names([source], source, cand.node)
        ctx = _ModuleContext(lines=source.splitlines(),
                             binding=_final_binding(tree), rebound=rebound)
        if _is_finalizable(cand, ctx):
            out.append(cand.name)
    return out


def add_final_constant(
    source: str,
    project_sources: list[str] | None = None,
) -> str | None:
    """Add ``typing.Final`` to the FIRST finalizable top-level constant in
    ``source``, or ``None`` when nothing changes.

    ``project_sources`` is the whole-project source set the rebind
    over-approximation scans (it MUST include ``source`` itself); when ``None``,
    ``source`` is scanned in isolation (the conservative single-module floor). Only
    the FIRST finalizable constant is annotated per call (one clean, idempotent edit
    — a second run finds it already ``Final`` and moves to the next), which keeps the
    ``from typing import Final`` ensure trivially a single insert and the splice
    unambiguous. Deterministic and idempotent (an already-``Final`` constant is
    skipped); the result is re-``ast.parse``d before return, so a malformed rewrite
    yields ``None`` rather than landing broken Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    scan_sources = [source] if project_sources is None else project_sources
    lines = source.splitlines()
    binding = _final_binding(tree)

    for cand in _candidates(tree):
        rebound = rebound_names(scan_sources, source, cand.node)
        ctx = _ModuleContext(lines=lines, binding=binding, rebound=rebound)
        if not _is_finalizable(cand, ctx):
            continue
        text = _annotation_text(binding, cand.annotation)
        splice = _splice_annotation(cand.node, lines, text)
        if splice is None:
            continue  # header not cleanly spliceable — try the next candidate
        start, end, new_lines = splice
        out_lines = list(lines)
        out_lines[start:end] = new_lines
        if _needs_import(binding):
            out_lines = _ensure_final_import(out_lines, "Final")
        return rejoin_guarded(source, out_lines)
    return None
