"""Self-registering develop objective: document-yields — the GENERATOR image of
``document-returns``, the structural twin that documents the YIELD contract.

Where a PUBLIC GENERATOR function — its own body contains a ``yield`` / ``yield
from`` AND it carries an iterator/generator return annotation (``-> Iterator[T]`` /
``Iterable[T]`` / ``Generator[Y, S, R]`` / ``AsyncIterator[T]`` / ``AsyncGenerator[Y,
S]``, and their ``typing.`` / ``collections.abc.`` / from-import-alias spellings) —
(a) HAS a docstring and (b) does NOT already document its yield in ANY convention,
splice a faithful ``Yields:`` section into that EXISTING docstring rendering the
ELEMENT type VERBATIM. The element is read straight off the annotation subscript via
:func:`ast.unparse` (``Iterator[int]`` -> ``int``; ``Generator[Row, None, None]`` ->
``Row``) — never inferred — so the documented yield cannot misstate the contract.

THE BOUNDARY (the prime invariant). ``document-returns`` already REFUSES any
iterator/generator return (its ``_GENERATOR_RETURNS`` refuse-head set) AND, being the
return documenter, never even looks for a ``yield``; ``document-yields`` REQUIRES one
in the function's own scope. The two are therefore MUTUALLY EXCLUSIVE on a generator:
exactly one fires, and a generator gets a ``Yields:`` section, never a ``Returns:``.
``document-yields`` reuses the SAME element-source predicate (``_GENERATOR_RETURNS``,
the alias-aware ``_head_name``) and the SAME byte-aware existing-docstring splice
(``splice_docstring_section``) as ``document-returns`` by import — no copy-paste — so
the two stay airtight twins of one another. The shared refuse set is IMPORTED, never
duplicated, so the boundary is a single source of truth.

THE YIELD WALKER (``_is_generator``). It mirrors the descend-but-stop-at-nested-scope
rule of ``document_raises._walk_escaping_raises``: it descends plain control flow and
the children of every statement but STOPS at any new scope — ``def`` / ``async def`` /
``class`` (and, since a ``lambda`` / comprehension body is never an ``ast.stmt``, a
generator expression's yield is invisible too). A ``yield`` that belongs to a NESTED
function is NOT this function's, so it does not make THIS function a generator (and a
nested helper that yields never mis-attributes a ``Yields:`` to its non-generator
parent). Only a ``yield`` / ``yield from`` in ``fn``'s OWN scope qualifies it.

THE REFUSE SET (conservative by construction — the value of a documented yield is its
faithfulness, so any shape we cannot render faithfully is refused, never guessed):

  - NOT a generator — no ``yield`` / ``yield from`` in the function's OWN scope
    (a nested ``def``/``lambda``/genexp that yields does not count). REFUSE.
  - NO return annotation, or one whose canonical HEAD is not a recognised
    iterator/generator name (a plain ``-> list[int]`` is ``document-returns``'
    lane). REFUSE.
  - a BARE ``Iterator`` / ``Generator`` (etc.) with NO subscript — there is no
    element type to render. REFUSE.
  - NO existing docstring — minting a whole docstring is a different objective
    (``document-signature``); we only ADD to a docstring already there. REFUSE.
  - the yield ALREADY documented — a Google ``Yields:`` section header (bare or the
    inline ``Yields: <type>`` form) or a Sphinx ``:yields:`` / ``:ytype:`` field.
    No duplication. REFUSE.
  - a private / dunder / ``test_`` name. REFUSE.

STYLE MATCHING reuses ``document-returns``' detector: a docstring carrying a Sphinx
field list gets a Sphinx ``:yields:`` (+ ``:ytype:``) field; a Google section or
plain prose gets a Google ``Yields:`` section (the sibling-consistent default). The
rendered description is the ELEMENT annotation TEXT VERBATIM, never invented prose.

THE RE-PLUMBED SPLICE. The byte-aware existing-docstring splice (single-line EXPANSION
vs multi-line insert, CRLF-safe, the UTF-8 BYTE-offset P0) is the canonical
:func:`document_returns.splice_docstring_section`, reached by passing this module's
``Yields:`` ``section_fn``; the parse / import-alias / function-walk / bottom-up apply /
re-parse / self-validate loop is the canonical :func:`document_returns.apply_section_edits`
(the FUNCTION family — its ``_DEF`` + ``still_all_documented`` defaults), the SAME driver
``document-returns`` and ``document-param`` route through — so a generator is documented
exactly where ``document-returns`` refuses it (the airtight boundary), with zero
copy-paste.

The single write is behaviour-IDENTICAL (a ``Yields:`` section is docstring TEXT — it
changes no runtime value; the docstring stays the function's first statement),
idempotent (a second run finds the yield now documented and refuses — a byte-identical
no-op), and deterministic (pure AST -> text, source order, no clock/random). CRLF-SAFE
and one-line-EXPANDING via the shared byte-aware splice. Self-validating: the result
must RE-PARSE and every touched function must still open with its docstring Constant —
else the change is refused. Standard one-``plan_fn``-over-every-module shape, registered
via ``_base.register_module_objective``. ``scope_verify`` is the default ``False`` (a
docstring insert has no red baseline a full-suite gate could wrongly veto) and it is
NOT ``expensive`` (a pure-AST scan). Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.objectives.document_returns import (
    _GENERATOR_RETURNS,
    _convention,
    _head_name,
    _import_aliases,
    apply_section_edits,
    splice_docstring_section,
)
from app.execution.objectives.pin_return_type import _is_public

# A generator/async-generator return whose FIRST type argument is the YIELDED element:
# ``Generator[Y, S, R]`` / ``AsyncGenerator[Y, S]`` yield ``Y`` (the element is the
# FIRST of several args); ``Iterator[T]`` / ``Iterable[T]`` / ``AsyncIterator[T]`` /
# ``AsyncIterable[T]`` yield their SOLE arg ``T``. Either way the element is the first
# subscript argument, so ONE rule (``_element_text`` reads ``slice``'s first arg)
# covers the whole family — and every name here is already in :data:`_GENERATOR_RETURNS`
# (imported from ``document_returns``), the SAME set that objective refuses, keeping the
# boundary a single source of truth.

# A docstring already records a yield when ANY of these matches (so a ``Yields:`` must
# NOT be added): a Sphinx ``:yields:`` / ``:yield:`` / ``:ytype:`` field, or a Google
# ``Yields:`` line — the BARE section header OR the inline ``Yields: <type>`` form.
# Anchored to a (whitespace-led) line start so a mid-sentence "yields" is never a hit.
_SPHINX_YIELD = re.compile(r"(?im)^\s*:(yields?|ytype):")
_GOOGLE_YIELD = re.compile(r"(?im)^\s*yields?:")

# Nodes that OPEN A NEW SCOPE: a ``yield`` inside one of these belongs to THAT scope,
# not the function under test, so the walk PRUNES them. ``def`` / ``async def`` /
# ``class`` (nested statement scopes) and ``lambda`` / the four comprehension forms
# (expression scopes — a ``GeneratorExp`` / ``ListComp`` / ``SetComp`` / ``DictComp``,
# each with their own implicit function). The ``document_raises`` stop-at-scope rule,
# widened to the expression scopes a yield can also hide in.
_NESTED_SCOPE = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
    ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp,
)


def _yields_in_own_scope(node: ast.AST) -> bool:
    """True when a ``yield`` / ``yield from`` appears in ``node``'s OWN scope — every
    descendant is visited EXCEPT the interior of a nested scope (:data:`_NESTED_SCOPE`),
    which is pruned because its yields belong to that inner function.

    One uniform walk over both statements and expressions (a yield can sit in statement
    position, ``yield v``, or expression position, ``x = yield v``), pruning at the
    scope boundary — the descend-but-stop-at-scope rule of
    :func:`document_raises._walk_escaping_raises`, applied to yields."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(child, _NESTED_SCOPE):
            continue  # a nested scope's yields are not ours
        if _yields_in_own_scope(child):
            return True
    return False


def _is_generator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` is a GENERATOR — a ``yield`` / ``yield from`` in its OWN scope
    (nested defs / lambdas / comprehensions excluded), the predicate that makes it
    ``document-yields``' business and not ``document-returns``'.

    Each body statement that is ITSELF a nested scope (a helper ``def`` / ``class``) is
    skipped outright; the rest are walked with :func:`_yields_in_own_scope` (which prunes
    deeper nested scopes), so a yielding nested helper never mis-qualifies its
    non-generator parent."""
    return any(
        not isinstance(stmt, _NESTED_SCOPE) and _yields_in_own_scope(stmt)
        for stmt in fn.body
    )


def _element_text(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, aliases: dict[str, str],
) -> str | None:
    """The faithful YIELDED-element TEXT to document for ``fn``, or ``None`` to refuse.

    Refuses (returns ``None``) a function with NO ``-> T`` annotation, one whose
    canonical HEAD name is not a recognised iterator/generator
    (:data:`document_returns._GENERATOR_RETURNS`), and a BARE ``Iterator`` /
    ``Generator`` with no subscript (no element to render). Otherwise the element is the
    FIRST subscript argument — the sole arg of ``Iterator[T]`` / ``Iterable[T]`` /
    ``AsyncIterator[T]``, or ``Y`` of ``Generator[Y, S, R]`` / ``AsyncGenerator[Y, S]``
    — rendered VERBATIM via :func:`ast.unparse` (``int``, ``dict[str, Row]``), never
    invented prose."""
    ann = fn.returns
    if ann is None:
        return None
    if _head_name(ann, aliases) not in _GENERATOR_RETURNS:
        return None
    if not isinstance(ann, ast.Subscript):
        return None  # bare ``Iterator`` / ``Generator`` -> no element type -> refuse
    arg = ann.slice
    if isinstance(arg, ast.Tuple):
        if not arg.elts:
            return None
        arg = arg.elts[0]  # ``Generator[Y, S, R]`` / ``AsyncGenerator[Y, S]`` -> ``Y``
    return ast.unparse(arg)


def _has_documented_yield(doc: str) -> bool:
    """True when the docstring text ``doc`` already records a yield in ANY convention,
    so a ``Yields:`` section must NOT be added.

    Covers the Sphinx ``:yields:`` / ``:yield:`` / ``:ytype:`` field
    (:data:`_SPHINX_YIELD`) and the Google ``Yields:`` line — the bare section header
    OR the inline ``Yields: <type>`` form (:data:`_GOOGLE_YIELD`). Any one match REFUSES
    — never a duplicate yield doc."""
    return _SPHINX_YIELD.search(doc) is not None or _GOOGLE_YIELD.search(doc) is not None


def _yield_section(convention: str, indent: str, type_text: str, le: str) -> list[str]:
    """The yield-section BODY as already-indented source lines (each ending with the
    file's own terminator ``le``), in the given ``convention``.

    Google (the default): a blank separator then a ``Yields:`` header and one indented
    element-type line. Sphinx: a ``:yields:`` line carrying the element text plus a
    ``:ytype:`` line (the two reST yield fields). Blank separators are emitted EMPTY (no
    indent) per the PEP-257 / black convention. The rendered text is the element
    annotation VERBATIM, never invented prose. The ``Returns:`` analogue is
    ``document_returns._section_lines``; the two are the only thing that differs between
    the sibling objectives."""
    if convention == "sphinx":
        return [
            f"{indent}:yields: {type_text}{le}",
            f"{indent}:ytype: {type_text}{le}",
        ]
    return [
        le,
        f"{indent}Yields:{le}",
        f"{indent}    {type_text}{le}",
    ]


def _documentable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rows: list[str],
    aliases: dict[str, str],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice for ``fn`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/non-test NAME gate (:func:`_is_public`), the
    IS-A-GENERATOR gate (:func:`_is_generator` — a ``yield`` in its OWN scope; the
    boundary that keeps this objective and ``document-returns`` mutually exclusive), the
    HAS-a-docstring requirement (``ast.get_docstring`` — the inverse of
    document-signature), the element-type gate (:func:`_element_text` — no annotation /
    not a recognised iterator-generator / bare-unsubscripted => refuse), the
    NOT-already-documented gate (:func:`_has_documented_yield`), and a usable splice
    point via the SHARED byte-aware :func:`document_returns.splice_docstring_section`
    (a ``Yields:`` section built by :func:`_yield_section`)."""
    if not _is_public(fn) or not _is_generator(fn):
        return None
    doc = ast.get_docstring(fn)
    if doc is None:
        return None  # undocumented -> document-signature's lane (zero collision)
    type_text = _element_text(fn, aliases)
    if type_text is None:
        return None  # no/unrecognised annotation or bare-unsubscripted -> refuse
    if _has_documented_yield(doc):
        return None  # already records a yield (any convention) -> no duplication
    convention = _convention(doc)
    return splice_docstring_section(
        fn, rows, lambda indent, le: _yield_section(convention, indent, type_text, le))


def document_yields(source: str) -> str | None:
    """Return ``source`` with a faithful ``Yields:`` section spliced into every
    qualifying documented generator's docstring, or ``None`` when nothing qualifies
    (or the source does not parse).

    A thin wrapper over the shared :func:`document_returns.apply_section_edits` driver
    (the FUNCTION family), supplying the ``Yields:`` gate stack
    (:func:`_documentable_target`) with per-module import aliases derived from the tree
    — so a generator is documented exactly where ``document-returns`` refuses it (the
    airtight boundary). Self-validating + deterministic."""
    return apply_section_edits(
        source,
        lambda fn, rows, tree: _documentable_target(fn, rows, _import_aliases(tree)))


def plan_document_yields(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the faithful ``Yields:``-section plan for one module, or an empty no-op
    plan.

    Documents every qualifying public generator in ``module_rel`` (public name, HAS a
    docstring with no recorded yield, a ``yield`` in its own scope, a recognised
    subscripted iterator/generator annotation) via :func:`document_yields`. The shared
    single-file-rewrite plumbing — refuse a test/fixture/non-library file, read the
    module, record the single rewrite with its original for rollback (or a no-op when
    nothing is documentable) — is delegated to :func:`plan_source_rewrite`, the one
    source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-yields", document_yields)


register_module_objective(
    "document-yields", plan_document_yields,
    operator="document_yields",
    description="document the yielded element of generators in {rel} from their return annotation",
)
