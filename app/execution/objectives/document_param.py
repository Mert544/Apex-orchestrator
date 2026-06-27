"""Self-registering develop objective: document-param — the PARAMETER image of
``document-returns``, the structural twin that documents the INPUT contract.

Where a PUBLIC function (a) HAS a docstring, (b) carries at least one parameter with
a DECLARED type annotation, and (c) does NOT already document its parameters in ANY
convention, splice a faithful ``Args:`` section into that EXISTING docstring listing
one ``name (TYPE):`` line per declared-annotated parameter, the type ``TYPE`` read
straight off ``arg.annotation`` via :func:`ast.unparse` — never inferred — so the
documented parameter type cannot misstate the contract. This is the Python mirror of
the shipped ``js-document-param-types`` (``@param {T} name``) and the sibling of
``document-returns`` (``Returns:``): together they let Apex complete a Google-style
docstring (summary + Args + Returns) across develop passes. Like ``document-returns``
it only ADDS its own section to a docstring already there — ``document-signature``
MINTS a whole docstring on an UNDOCUMENTED function; this one never invents a summary.
The two are mutually exclusive by the docstring predicate, so there is ZERO collision.

THE HONESTY GATE (mirrors ``js_document_param_types._is_landable``). An ``Args:`` block
listing only parameter NAMES is a pure RESTATEMENT of the signature and adds nothing,
so the section lands ONLY when AT LEAST ONE parameter has a DECLARED annotation, and
ONLY the annotated parameters get a line (an unannotated parameter is SKIPPED — never a
bare ``name`` line with no type, the signature-restatement noise document-signature
forbids). A function whose every documentable parameter is unannotated is REFUSED — an
honest no-op, never a content-free ``Args:`` block.

THE REFUSE SET (conservative by construction — the value of a documented parameter is
its faithfulness, so any shape we cannot render faithfully is refused, never guessed):

  - NO existing docstring — minting a whole docstring is a different, riskier
    objective (``document-signature``); we only ADD to a docstring already there.
    REFUSE.
  - NO parameter carries a declared annotation — a content-free ``Args:`` block.
    REFUSE (the honesty gate).
  - NO parameters, or only ``self`` / ``cls`` after filtering — nothing to document.
    REFUSE.
  - the parameters ALREADY documented in ANY convention — a Google ``Args:`` /
    ``Arguments:`` / ``Parameters:`` section header, ANY Sphinx ``:param ...:`` /
    ``:parameter ...:`` / ``:type ...:`` / ``:arg ...:`` / ``:keyword ...:`` field, or a
    NumPy ``Parameters`` header underlined with dashes. This includes the PARTIAL case
    (some parameters documented, not all): a half-filled block is REFUSED WHOLE — we
    never merge new lines into it (fragile, corrupts ordering, and the re-parse floor
    cannot catch a redundant/duplicate param line). REFUSE.
  - a ``*args`` / ``**kwargs`` whose annotation is not a simple readable NAME — the
    whole function is REFUSED rather than emitting a partial/guessy block (a partial
    ``Args:`` desyncs the batch self-validation). A bare ``*args`` (no annotation) is
    simply skipped like any other unannotated parameter.
  - an ``@overload`` / ``@typing.overload`` stub — the implementation carries the
    canonical docstring. REFUSE.
  - a property ``@x.setter`` / ``@x.deleter`` — the canonical doc lives on the getter.
    REFUSE. (A plain ``@property`` getter MAY be documented.)
  - a private / dunder / ``test_`` name — REFUSE (reuses ``document_returns._is_public``).
  - a one-line docstring whose closing-quote line shares non-whitespace header text —
    REFUSE (the ``document_returns`` single-line indent guard).
  - source not ``ast.parse``-able — a conservative no-op.

STYLE MATCHING. The inserted section MATCHES the docstring's existing convention so a
Sphinx field is never jammed into a Google block: a docstring already using Sphinx
field lists (``:param:`` / ``:raises:`` / ``:rtype:`` …) gets Sphinx ``:param name:`` +
``:type name: T`` lines; one using Google section headers (or plain prose) gets a
Google ``Args:`` block — the DEFAULT, chosen to AGREE with ``document-returns`` (which
also defaults to Google). The convention detector and line-ending / byte-aware splice
helpers are REUSED from ``document_returns`` by import (no copy-paste — keeps the grade
de-dup detector quiet). The rendered text is the annotation VERBATIM (``dict[str,
int]``), never invented prose.

The single write is behaviour-IDENTICAL (an ``Args:`` section is docstring TEXT — it
changes no runtime value; the docstring stays the function's first statement),
idempotent (a second run finds the parameters now documented and refuses — a
byte-identical no-op), and deterministic (pure AST → text, source order, no
clock/random). CRLF-SAFE and byte-aware FROM THE START: ``col_offset`` /
``end_col_offset`` are UTF-8 BYTE offsets, so the one-line-expansion splice slices the
literal in BYTE space (encode → slice → decode) — non-ASCII / astral one-liners
round-trip exactly. Self-validating: the result must RE-PARSE and every touched
function must still open with its (now longer) docstring Constant — else the change is
refused. Standard one-``plan_fn``-over-every-module shape, registered via
``_base.register_module_objective`` — same suite-gated, auto-rollback develop loop as
every other objective. ``scope_verify`` is the default ``False`` (a docstring insert has
no red baseline a full-suite gate could wrongly veto) and it is NOT ``expensive`` (a
pure-AST scan). Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.objectives.document_returns import (
    _convention,
    _is_refused_decoration,
    apply_section_edits,
    splice_docstring_section,
)
from app.execution.objectives.pin_return_type import _is_public

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)

# The first positional parameter is the implicit receiver on a method and carries no
# documentable type for the caller, so it is filtered before the honesty gate.
_RECEIVER_NAMES = frozenset({"self", "cls"})

# A docstring already records its PARAMETERS when ANY of these matches (so a section
# must NOT be added — including the PARTIAL case, where only some params are listed):
#   * Google — an ``Args:`` / ``Arguments:`` / ``Parameters:`` section header.
#   * Sphinx — ANY ``:param ...:`` / ``:parameter ...:`` / ``:type ...:`` / ``:arg ...:``
#     / ``:keyword ...:`` field (a single one means the block is already begun).
#   * NumPy  — a bare ``Parameters`` header underlined with at least three dashes.
# All anchored to a (whitespace-led) line start so a mid-sentence word is never a false
# hit; the Sphinx field word boundary (``\b``) keeps ``:parameters_note:`` out.
_GOOGLE_PARAMS = re.compile(r"(?im)^\s*(args|arguments|parameters):")
_SPHINX_PARAMS = re.compile(r"(?im)^\s*:(param|parameter|type|arg|keyword)\b")
_NUMPY_PARAMS = re.compile(r"(?im)^[ \t]*parameters[ \t]*$\n[ \t]*-{3,}[ \t]*$")


def _has_documented_params(doc: str) -> bool:
    """True when the docstring text ``doc`` already records its parameters in ANY
    convention, so an ``Args:`` section must NOT be added.

    Covers the Google ``Args:`` / ``Arguments:`` / ``Parameters:`` section header
    (:data:`_GOOGLE_PARAMS`), ANY Sphinx ``:param:`` / ``:type:`` / ``:arg:`` /
    ``:keyword:`` field (:data:`_SPHINX_PARAMS`), and the NumPy ``Parameters`` SECTION
    (:data:`_NUMPY_PARAMS`). Any one match REFUSES — never a duplicate param doc, and
    never a merge into a HALF-filled block (a single ``:param x:`` among missing
    siblings still trips :data:`_SPHINX_PARAMS`, so the partial case refuses whole)."""
    return (
        _GOOGLE_PARAMS.search(doc) is not None
        or _SPHINX_PARAMS.search(doc) is not None
        or _NUMPY_PARAMS.search(doc) is not None
    )


def _positional_and_kw_args(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    """The positional-or-keyword parameters of ``fn`` in source order — the
    positional-only, normal, and keyword-only ``ast.arg`` nodes — with the implicit
    receiver (a leading ``self`` / ``cls``) dropped.

    The ``*args`` / ``**kwargs`` collectors are handled separately (their annotation,
    if any, is a strict simple-name gate), so they are not part of this list."""
    a = fn.args
    ordered = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    if ordered and ordered[0].arg in _RECEIVER_NAMES:
        ordered = ordered[1:]
    return ordered


def _is_simple_name_annotation(annotation: ast.expr) -> bool:
    """True when ``annotation`` is a SIMPLE readable name — a bare ``ast.Name``
    (``int``), a dotted ``ast.Attribute`` (``typing.Any``), or a subscript of either
    (``list[int]``). A ``*args`` / ``**kwargs`` annotation that is NOT one of these
    (a literal, a call, a lambda, …) is the unreadable shape that refuses the whole
    function — never a guessy partial line."""
    node = annotation
    while isinstance(node, ast.Subscript):
        node = node.value
    return isinstance(node, (ast.Name, ast.Attribute))


def _collector_blocks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when a ``*args`` / ``**kwargs`` collector carries an annotation that is
    NOT a simple readable name — the shape that REFUSES the whole function (a partial
    ``Args:`` block would desync the batch self-validation). A bare ``*args`` with no
    annotation does not block (it is simply skipped, like any unannotated param)."""
    for collector in (fn.args.vararg, fn.args.kwarg):
        if collector is not None and collector.annotation is not None \
                and not _is_simple_name_annotation(collector.annotation):
            return True
    return False


def _annotated_params(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str]] | None:
    """The ``(name, type_text)`` pairs to document for ``fn`` — one per
    positional/keyword parameter that carries a DECLARED annotation, the type rendered
    VERBATIM via :func:`ast.unparse` — or ``None`` to refuse the whole function.

    Refuses (returns ``None``) when ``fn`` has no documentable parameter at all (no
    params, or only ``self`` / ``cls``), when a ``*args`` / ``**kwargs`` collector has
    an unreadable annotation (:func:`_collector_blocks`), or when NOT ONE parameter
    carries an annotation (the honesty gate — a names-only ``Args:`` block restates the
    signature). An UNANNOTATED parameter is SKIPPED (never a bare ``name`` line), so the
    returned list holds only the annotated parameters, in source order."""
    params = _positional_and_kw_args(fn)
    if not params:
        return None  # no params, or only self/cls -> nothing to document
    if _collector_blocks(fn):
        return None  # an unreadable *args/**kwargs annotation -> refuse the function
    annotated = [(p.arg, ast.unparse(p.annotation))
                 for p in params if p.annotation is not None]
    if not annotated:
        return None  # no declared annotation anywhere -> honest no-op (refuse)
    return annotated


def _section_lines(
    convention: str, indent: str, params: list[tuple[str, str]], le: str,
) -> list[str]:
    """The ``Args:`` section BODY as already-indented source lines (each ending with
    the file's own terminator ``le``), in the given ``convention``.

    Google (the default): a blank separator then an ``Args:`` header and one
    ``name (TYPE):`` line per annotated parameter. Sphinx: a ``:param name:`` line plus
    a ``:type name: TYPE`` line per parameter (the two reST parameter fields). Blank
    separators are emitted EMPTY (no indent) per the PEP-257 / black convention. Each
    ``TYPE`` is the annotation VERBATIM, never invented prose."""
    if convention == "sphinx":
        out: list[str] = []
        for name, type_text in params:
            out.append(f"{indent}:param {name}:{le}")
            out.append(f"{indent}:type {name}: {type_text}{le}")
        return out
    body = [le, f"{indent}Args:{le}"]
    body += [f"{indent}    {name} ({type_text}):{le}" for name, type_text in params]
    return body


def _param_edit(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rows: list[str],
    params: list[tuple[str, str]],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice that documents ``fn``'s parameters,
    or ``None`` to refuse. Builds the convention-matched ``Args:`` ``section_fn`` and
    hands it to the SHARED :func:`splice_docstring_section` (single-line expansion vs
    multi-line insert, byte-aware) — so the byte-aware splice machinery lives ONCE in
    ``document_returns`` and is reused here, never copy-pasted."""
    convention = _convention(ast.get_docstring(fn) or "")
    return splice_docstring_section(
        fn, rows, lambda indent, le: _section_lines(convention, indent, params, le))


def _documentable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rows: list[str],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice for ``fn`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/non-test NAME gate (:func:`_is_public`), the
    decorator gate (:func:`_is_refused_decoration` — ``@overload`` / property
    setter/deleter), the HAS-a-docstring requirement (``ast.get_docstring`` — the
    inverse of document-signature), the declared-parameter gate
    (:func:`_annotated_params` — no documentable/annotated param, or an unreadable
    ``*args``/``**kwargs`` => refuse), the NOT-already-documented gate
    (:func:`_has_documented_params` — covers the partial case too), and a usable splice
    point (:func:`_param_edit`)."""
    if not _is_public(fn) or _is_refused_decoration(fn):
        return None
    doc = ast.get_docstring(fn)
    if doc is None:
        return None  # undocumented -> document-signature's lane (zero collision)
    params = _annotated_params(fn)
    if params is None:
        return None  # no declared param annotation / unreadable collector -> refuse
    if _has_documented_params(doc):
        return None  # already records params (any convention, incl. partial) -> refuse
    return _param_edit(fn, rows, params)


def document_param(source: str) -> str | None:
    """Return ``source`` with a faithful ``Args:`` section spliced into every
    qualifying documented function's docstring from its DECLARED parameter
    annotations, or ``None`` when nothing qualifies (or the source does not parse).

    A thin wrapper over the shared :func:`apply_section_edits` driver: each function is
    routed through :func:`_documentable_target` (the param-specific gate stack). The
    driver applies the splices bottom-up, re-parses, and self-validates that every
    touched function still opens with its docstring — else it refuses. Deterministic."""
    return apply_section_edits(
        source, lambda fn, rows, _tree: _documentable_target(fn, rows))


def plan_document_param(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the faithful ``Args:``-section plan for one module, or an empty no-op plan.

    Documents every qualifying public function in ``module_rel`` (public name, HAS a
    docstring with no recorded parameters, at least one declared parameter annotation,
    not an overload / property setter) via :func:`document_param`. The shared
    single-file-rewrite plumbing — refuse a test/fixture/non-library file, read the
    module, record the single rewrite with its original for rollback (or a no-op when
    nothing is documentable) — is delegated to :func:`plan_source_rewrite`, the one
    source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-param", document_param)


register_module_objective(
    "document-param", plan_document_param,
    operator="document_param",
    description="document the parameters of functions in {rel} from their declared type annotations",
)
