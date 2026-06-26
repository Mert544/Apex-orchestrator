"""Self-registering develop objective: pin-return-type — the DOCUMENTED-function
image of ``infer-type-hints``.

Where a function HAS a docstring but carries no ``-> T`` annotation and its return
type is PROVABLE, splice a single ``Returns: <T>`` line into that EXISTING
docstring (only when the docstring lacks one). It lands the SAME proven type
``infer-type-hints`` would put in the signature — but as DOCUMENTATION, for
annotation-averse codebases that prefer a documented contract to a typed one. The
``<T>`` is read straight from the PROVEN return-type oracle
:func:`app.execution.semantic.transforms.type_annotations._infer_return_type`
(the agreeing-literal / fixed-result-builtin / pure-procedure-``None`` inference)
— never a guess.

INVERSE OF document-signature / document-raises. Those fire on an UNDOCUMENTED
function (and MINT a whole docstring); pin-return-type fires on a DOCUMENTED one
and ADDS one line into the docstring already there. The two are mutually exclusive
by the docstring predicate, so there is ZERO collision: a function with no
docstring is document-signature's territory and is REFUSED here.

THE ORACLE IS THE GATE. ``_infer_return_type`` returns Python ``None`` on ANY
ambiguity — and, decisively, ``None`` whenever the function ALREADY carries an
explicit ``-> T`` (``fn.returns is not None``). So importing the BARE oracle (NOT
the document_signature ``_provable_return_type`` wrapper, which would instead
surface the annotation text) makes the "no ``-> T``" requirement automatic: an
already-annotated function is refused for free (its documented return would only
ECHO the signature), as is a generator, a bare-return-mixed-with-value body, a
fall-through body, and any disagreeing / non-literal return. We land NOTHING for
those — the honest under-claim Apex promises (a docstring changes no runtime
value, so a wrong-but-verified type line is exactly the noise to avoid).

NEVER OVERWRITE A HUMAN'S STATED RETURN. If the existing docstring already records
a return — ``Returns:`` / ``Return:`` / ``:return:`` / ``:returns:`` / ``@returns``
/ ``@return`` (Google / reST / epydoc spellings) — the function is REFUSED. We only
ever ADD a return fact a docstring is missing, never replace one a maintainer
wrote.

Also REFUSED (left byte-for-byte alone): a private/dunder name (leading ``_``), a
``test_`` function, a test/fixture/non-library file (the suite Apex is gated by is
never edited), a non-parsing source, and a docstring whose closing-quote line
cannot be safely located — a single-line docstring (``\"\"\"x\"\"\"``, open and close
on one line) or one whose closing-quote indent is not pure whitespace (the
document_signature-style indent guard). Splicing into those would corrupt the line
and the self-validation would then refuse the WHOLE module.

The single write is behaviour-IDENTICAL (a ``Returns:`` line is docstring TEXT —
it changes no runtime value; the docstring stays the function's first statement),
idempotent (a second run finds the ``Returns:`` line now present and refuses, a
byte-identical no-op), and deterministic (pure AST → text, source order, no
clock/random). Self-validating: the result must RE-PARSE and each touched
function's first body statement must still be its (now one-line-longer) docstring
Constant — else the change is refused. Standard one-``plan_fn``-over-every-module
shape, registered via ``_base.register_module_objective`` — same suite-gated,
auto-rollback develop loop as every other objective. ``scope_verify`` is the
default ``False`` (a docstring line has no red baseline a full-suite gate could
wrongly veto) and it is NOT ``expensive`` (a pure-AST scan). The return-type
oracle and the indent helper are reused read-only by import; neither is modified.
Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.semantic.transforms.base import _get_indent
from app.execution.semantic.transforms.type_annotations import _infer_return_type

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)

# A docstring that ALREADY records a return, in any of the conventional spellings:
# Google (``Returns:`` / ``Return:``), reST/Sphinx (``:returns:`` / ``:return:``),
# epydoc (``@returns`` / ``@return``). Matched case-insensitively at the start of
# any (whitespace-led) line of the cleaned docstring text. Its presence REFUSES the
# function — we never overwrite a maintainer's stated return contract.
_RETURN_FIELD = re.compile(r"(?im)^\s*(returns?:|:returns?:|@returns?\b)")


def _is_public(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` is a PUBLIC, non-test function — the NAME half of the
    document_signature gate only.

    Refuses (returns ``False``) a leading-``_`` name (private or a dunder — never a
    public-surface symbol) and a ``test_`` function (part of the suite). Crucially
    this does NOT also require an absent docstring — pin-return-type fires on a
    DOCUMENTED function, the inverse of document_signature, so the docstring
    predicate is applied separately by the caller (a PRESENT docstring is required,
    not forbidden)."""
    name = fn.name
    return not (name.startswith("_") or name.startswith("test_"))


def _has_existing_return_field(doc: str) -> bool:
    """True when the docstring text ``doc`` already records a return in any
    conventional spelling (Google / reST / epydoc), so a ``Returns:`` line must NOT
    be added. Pure regex over the cleaned docstring body — see :data:`_RETURN_FIELD`."""
    return _RETURN_FIELD.search(doc) is not None


def _returns_insertion(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str],
) -> tuple[int, str] | None:
    """``(insert_index, indent)`` for splicing a ``Returns:`` line into ``fn``'s
    EXISTING docstring, or ``None`` to refuse.

    The docstring is ``fn``'s first body statement — a string-literal ``ast.Expr``
    whose ``value`` Constant spans from its opening-quote line (``value.lineno``) to
    its closing-quote line (``value.end_lineno``). The new line is inserted at the
    0-based index ``end_lineno - 1`` — i.e. directly BEFORE the closing-quote line —
    at that line's leading whitespace, so the docstring reads ``…prose… → Returns:
    <T> → closing quotes``.

    Refuses (returns ``None``) when:
      - the first body statement is not a string-literal expression (no docstring
        node to splice into — belt-and-braces with the caller's
        ``ast.get_docstring`` check);
      - the docstring is a SINGLE LINE (``value.lineno == value.end_lineno``, e.g.
        ``\"\"\"x\"\"\"`` with open and close on one line) — there is no own closing-quote
        line to insert before without rewriting the literal;
      - the closing-quote line's leading indent is NOT pure whitespace (a header-
        shared one-liner reports the ``def …:`` text as its "indent"; splicing there
        corrupts the line). Mirrors the document_signature single-line-body guard."""
    body = getattr(fn, "body", None)
    if not body:
        return None
    first = body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return None
    const = first.value
    open_lineno = getattr(const, "lineno", None)
    close_lineno = getattr(const, "end_lineno", None)
    if open_lineno is None or close_lineno is None:
        return None
    if open_lineno == close_lineno:
        return None  # single-line docstring: no own closing-quote line to precede
    close_idx = close_lineno - 1
    if close_idx >= len(lines):
        return None
    indent = _get_indent(lines[close_idx])
    if not indent.isspace():
        return None  # not a trustworthy body indent — refuse rather than corrupt
    return close_idx, indent


def _pinnable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str],
) -> tuple[int, str] | None:
    """``(insert_index, returns_line)`` for ``fn`` when it qualifies, or ``None``.

    Applies, in order: the public/non-test NAME gate (:func:`_is_public`), the
    HAS-A-DOCSTRING requirement (``ast.get_docstring`` — the inverse of
    document_signature; a function with NO docstring is refused as that objective's
    territory), the NO-EXISTING-RETURN-FIELD gate (:func:`_has_existing_return_field`
    — never overwrite a stated return), the PROVABLE-and-unannotated return gate
    (:func:`_infer_return_type` — Python ``None`` ⇒ refuse; this also subsumes the
    already-``-> T`` / generator / fall-through / ambiguous cases the bare oracle
    rejects), and a usable docstring closing-quote splice point
    (:func:`_returns_insertion`)."""
    if not _is_public(fn):
        return None
    doc = ast.get_docstring(fn)
    if doc is None:
        return None  # undocumented -> document-signature's territory (zero collision)
    if _has_existing_return_field(doc):
        return None  # already records a return -> never overwrite a human's contract
    return_type = _infer_return_type(fn)
    if return_type is None:
        return None  # not provable / already -> T / generator / ambiguous -> refuse
    spot = _returns_insertion(fn, lines)
    if spot is None:
        return None
    insert_at, indent = spot
    return insert_at, f"{indent}Returns: {return_type}\n"


def _docstring_constant(fn: ast.AST) -> ast.Constant | None:
    """The string-literal ``Constant`` that is ``fn``'s docstring, or ``None`` —
    the self-validation probe (a pinned function's first statement must still be its
    docstring after the splice, never displaced)."""
    body = getattr(fn, "body", None)
    if not body:
        return None
    head = body[0]
    if (isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant)
            and isinstance(head.value.value, str)):
        return head.value
    return None


def _still_all_documented(tree: ast.AST) -> bool:
    """True when EVERY public, non-test function in ``tree`` still opens with a
    docstring Constant — the post-splice self-proof that no inserted ``Returns:``
    line displaced a docstring or broke a body. (A function with no docstring is
    irrelevant here; only the ones pin-return-type may touch are checked.)"""
    return all(
        _docstring_constant(node) is not None
        for node in ast.walk(tree)
        if isinstance(node, _DEF) and _is_public(node)
        and ast.get_docstring(node) is not None
    )


def pin_return_types(source: str) -> str | None:
    """Return ``source`` with a proven ``Returns: <T>`` line spliced into every
    qualifying documented function's existing docstring, or ``None`` when nothing
    qualifies (or the source does not parse).

    Each line is inserted before its docstring's closing quotes, bottom-up so
    earlier line indices stay valid. Self-validating: the result must RE-PARSE and
    every touched-class function must still open with its docstring Constant — else
    the change is refused (returns ``None``). Pure AST → text; deterministic (source
    order, no clock/random)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None

    rows = source.splitlines(keepends=True)
    defs = sorted(
        (n for n in ast.walk(tree) if isinstance(n, _DEF)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    edits = [spot for n in defs if (spot := _pinnable_target(n, rows))]
    if not edits:
        return None

    # Apply highest-index-first so each earlier insertion offset stays valid.
    for at, line in sorted(edits, key=lambda e: e[0], reverse=True):
        rows[at:at] = [line]
    pinned = "".join(rows)

    try:
        new_tree = ast.parse(pinned)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None
    if not _still_all_documented(new_tree):
        return None  # a splice displaced a docstring -> refuse the whole module
    return pinned if pinned != source else None


def plan_pin_return_type(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the proven ``Returns:``-line plan for one module, or an empty no-op
    plan.

    Pins a ``Returns: <T>`` line into every qualifying documented function in
    ``module_rel`` (public name, HAS a docstring with no recorded return, no ``-> T``
    annotation, and a PROVABLE return type) via :func:`pin_return_types`. The shared
    single-file-rewrite plumbing — refuse a test/fixture/non-library file, read the
    module, record the single rewrite with its original for rollback (or a no-op when
    nothing is provable) — is delegated to :func:`plan_source_rewrite`, the one
    source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "pin-return-type", pin_return_types)


register_module_objective(
    "pin-return-type", plan_pin_return_type,
    operator="pin_return_type",
    description="pin the proven return type into the existing docstring of functions in {rel}",
)
