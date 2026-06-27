"""Self-registering develop objective: document-attributes — the CLASS-ATTRIBUTE
image of ``document-returns``, the structural twin that documents a class's
declared STATE.

Where a PUBLIC class (a) HAS a docstring and (b) does NOT already document its
attributes in ANY convention, splice an ``Attributes:`` section into that EXISTING
docstring listing one line per class-body annotated field (``ast.AnnAssign``) as
``name (TYPE)`` with ``TYPE`` rendered VERBATIM via :func:`ast.unparse`. Every
``TYPE`` is read straight off the field's ``.annotation`` — never inferred — so the
documented attribute cannot misstate the declared type. This is the DOCUMENTED-class,
ANNOTATION-sourced sibling of ``document-returns``/``document-raises``: those mint a
return/raises section on a DOCUMENTED FUNCTION; document-attributes fires on a
DOCUMENTED CLASS and renders its declared class-level annotations. It selects only
``ast.ClassDef`` nodes, so there is ZERO overlap with the function-scoped doc
objectives.

THE REFUSE SET (conservative by construction — the value of documented attributes is
their faithfulness, so any shape we cannot render faithfully is refused, never
guessed):

  - NO existing class docstring — minting a whole docstring is a different, riskier
    objective (``document-signature``); we only ADD to a docstring already there.
    REFUSE.
  - NO class-body annotated field — an ``Attributes:`` section with no attributes is
    content-free. A class whose only state is INSTANCE assignment (``self.x = ...``
    in ``__init__``, with no class-level ``x: T`` annotation) is OUT OF SCOPE: reading
    a type off ``self.x = 0`` would be INFERENCE, which this objective never does.
    REFUSE.
  - attributes ALREADY documented in ANY convention — a Google ``Attributes:``
    section header, a Sphinx ``:ivar:`` / ``:cvar:`` / ``:var:`` field, or a NumPy
    ``Attributes`` header underlined with dashes. This also REFUSES a PARTIALLY
    documented class (a half-filled ``Attributes:`` block, or only some fields carry
    an ``:ivar:``): we never merge into an author's partial block — the WHOLE class is
    refused. No duplication. REFUSE.
  - a class EVERY one of whose annotated fields has an UNREADABLE annotation — each
    field whose annotation does not round-trip through :func:`ast.unparse` is dropped
    from the section (emit the readable ones only); if that leaves NOTHING readable,
    REFUSE the whole class.
  - a private/dunder/``test_`` class NAME (:func:`_is_public`) — never a public
    surface symbol. REFUSE.

STYLE MATCHING. The inserted section MATCHES the docstring's existing convention so a
Sphinx field is never jammed into a Google block: a docstring already using Google
section headers gets a Google ``Attributes:`` section; one using Sphinx field lists
(``:param:`` / ``:ivar:`` / ``:rtype:`` …) gets Sphinx ``:ivar: name`` (+ ``:vartype
name:``) fields; a plain-prose docstring with no recognisable sections gets the
DEFAULT — Google ``Attributes:`` — chosen to AGREE with the sibling objectives, which
all emit Google-style. The rendered description is a FAITHFUL rendering of the
annotation TEXT (``dict[str, int]``), never invented prose semantics.

THE RE-PLUMBED SPLICE. The byte-aware existing-docstring splice (single-line
EXPANSION vs multi-line insert, CRLF-safe, the UTF-8 BYTE-offset P0) is the canonical
:func:`document_returns.splice_docstring_section`, reached by passing this module's
``Attributes:`` ``section_fn``; the parse / class-walk / bottom-up apply / re-parse /
self-validate loop is the canonical :func:`document_returns.apply_section_edits`, which
is generic over its ``node_types`` + ``still_valid`` (the CLASS family overrides them to
walk ``ast.ClassDef`` and validate classes). So the splice + driver machinery lives ONCE
in ``document_returns`` and is reused here, never copy-pasted — the same canonical
helpers ``document-param`` and ``document-yields`` route through.

The single write is behaviour-IDENTICAL (an attributes section is docstring TEXT — it
changes no runtime value; the docstring stays the class's first statement),
idempotent (a second run finds the attributes now documented and refuses — a
byte-identical no-op), and deterministic (pure AST → text, source/field order, no
clock/random). CRLF-SAFE: the inserted line(s) reuse the file's OWN line terminator
(taken from the docstring's closing-quote line), so a CRLF file is never silently
normalised. The ``col_offset`` / ``end_col_offset`` UTF-8 BYTE-offset splice (the
proven P0) keeps a one-line docstring (``\"\"\"Foo.\"\"\"``) EXPANSION byte-faithful for
non-ASCII bodies, preserving any raw/byte prefix (``r\"\"\"``) and the quote style.
Self-validating: the result must RE-PARSE and every touched class must still open with
its (now longer) docstring Constant — else the change is refused. Standard
one-``plan_fn``-over-every-module shape, registered via
``_base.register_module_objective`` — same suite-gated, auto-rollback develop loop as
every other objective. ``scope_verify`` is the default ``False`` (a docstring insert
has no red baseline a full-suite gate could wrongly veto) and it is NOT ``expensive``
(a pure-AST scan). Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.objectives.document_returns import (
    apply_section_edits,
    splice_docstring_section,
)
from app.execution.objectives.pin_return_type import _docstring_constant, _is_public

# A docstring already records attributes when ANY of these matches (so a section must
# NOT be added — including onto a PARTIALLY filled block): a Sphinx ``:ivar:`` /
# ``:cvar:`` / ``:var:`` field (the instance/class-var reST spellings), a Google
# ``Attributes:`` line (the bare section header OR an inline ``Attributes: x`` form),
# or a NumPy ``Attributes`` header underlined with at least three dashes. Anchored to a
# (whitespace-led) line start so a mid-sentence "attributes" is never a false hit.
_SPHINX_ATTR = re.compile(r"(?im)^\s*:(ivar|cvar|var)\b")
_GOOGLE_ATTR = re.compile(r"(?im)^\s*attributes:")
_NUMPY_ATTR = re.compile(r"(?im)^[ \t]*attributes[ \t]*$\n[ \t]*-{3,}[ \t]*$")

# The docstring's CONVENTION is Sphinx when it carries a field list (``:param:`` /
# ``:ivar:`` / ``:rtype:`` / ``:returns:`` / ``:type:`` / ``:raises:``); Google when it
# carries a recognised section header. Plain prose matches neither and falls to the
# Google default (sibling-consistent). Widens document_returns' field words with the
# attribute-var spellings so an ``:ivar:``-only docstring still reads as Sphinx (the
# reason this objective keeps its OWN convention detector rather than importing the
# return one — the return detector has no ``:ivar:``/``:cvar:``/``:vartype:`` word).
_SPHINX_FIELD = re.compile(
    r"(?im)^\s*:(param|parameter|raises?|rtype|returns?|type|yields?|ivar|cvar|var|vartype)\b")


def _readable_annotation(node: ast.expr) -> str | None:
    """The faithful attribute-type TEXT rendered VERBATIM via :func:`ast.unparse`
    (``dict[str, int]``), or ``None`` when the annotation does not round-trip
    (unreadable — dropped from the section). A faithful rendering of the DECLARED
    type, never inferred prose."""
    try:
        return ast.unparse(node)
    except (ValueError, RecursionError, MemoryError, TypeError):
        return None


def _class_attributes(cls: ast.ClassDef) -> list[tuple[str, str]]:
    """The ``(name, type_text)`` pairs to document for ``cls`` — one per CLASS-BODY
    annotated field (``ast.AnnAssign``) with a simple ``Name`` target and a READABLE
    annotation, in source order.

    Only DIRECT children of the class body are walked (``cls.body``), so a field
    annotated inside a nested function/class is never mis-attributed to ``cls``. A
    non-``Name`` target (``self.x: int`` / ``a.b: int`` / ``d['k']: int``) is skipped —
    it is not a class-level NAME binding (``self.x`` is INSTANCE state, out of scope:
    documenting it would be inference). A field whose annotation is UNREADABLE
    (:func:`_readable_annotation` ⇒ ``None``) is dropped (emit the readable ones only).
    Deterministic: source order, last duplicate name wins nothing (each AnnAssign is
    its own line)."""
    pairs: list[tuple[str, str]] = []
    for stmt in cls.body:
        if not isinstance(stmt, ast.AnnAssign):
            continue
        if not isinstance(stmt.target, ast.Name):
            continue
        type_text = _readable_annotation(stmt.annotation)
        if type_text is None:
            continue
        pairs.append((stmt.target.id, type_text))
    return pairs


def _has_documented_attributes(doc: str) -> bool:
    """True when the docstring text ``doc`` already records attributes in ANY
    convention, so an attributes section must NOT be added.

    Covers the Sphinx ``:ivar:`` / ``:cvar:`` / ``:var:`` field
    (:data:`_SPHINX_ATTR`), the Google ``Attributes:`` line — the bare section header
    OR the inline ``Attributes: x`` form (:data:`_GOOGLE_ATTR`), and the NumPy
    ``Attributes`` SECTION (:data:`_NUMPY_ATTR` — a bare header underlined with
    dashes). Any one match REFUSES — so a PARTIALLY documented class (a half-filled
    ``Attributes:`` block, or only some fields carrying ``:ivar:``) is refused WHOLE,
    never merged into."""
    return (
        _SPHINX_ATTR.search(doc) is not None
        or _GOOGLE_ATTR.search(doc) is not None
        or _NUMPY_ATTR.search(doc) is not None
    )


def _convention(doc: str) -> str:
    """The docstring's section CONVENTION: ``"sphinx"`` when it carries a Sphinx field
    list (``:param:`` / ``:ivar:`` / ``:rtype:`` …), else ``"google"`` (a Google
    section header, OR plain prose — the sibling-consistent default). Deterministic;
    Sphinx is preferred when both shapes somehow appear (a field list is the more
    explicit signal). Kept LOCAL (not the document_returns one) because the attribute
    var spellings ``:ivar:`` / ``:cvar:`` / ``:vartype:`` must read as Sphinx here."""
    if _SPHINX_FIELD.search(doc) is not None:
        return "sphinx"
    return "google"


def _section_lines(
    convention: str, indent: str, attrs: list[tuple[str, str]], le: str,
) -> list[str]:
    """The attributes-section BODY as already-indented source lines (each ending with
    the file's own terminator ``le``), in the given ``convention``.

    Google (the default): a blank separator then an ``Attributes:`` header and one
    indented ``name (TYPE)`` line per field. Sphinx: a ``:ivar name: TYPE`` line plus a
    ``:vartype name: TYPE`` line per field (the two reST attribute fields). Blank
    separators are emitted EMPTY (no indent) per the PEP-257 / black convention. The
    rendered text is the annotation VERBATIM, never invented prose."""
    if convention == "sphinx":
        rows: list[str] = []
        for name, type_text in attrs:
            rows.append(f"{indent}:ivar {name}: {type_text}{le}")
            rows.append(f"{indent}:vartype {name}: {type_text}{le}")
        return rows
    body = [f"{indent}    {name} ({type_text}){le}" for name, type_text in attrs]
    return [le, f"{indent}Attributes:{le}", *body]


def _attr_edit(
    cls: ast.ClassDef, rows: list[str], attrs: list[tuple[str, str]],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice that documents ``cls``'s
    attributes, or ``None`` to refuse. Builds the convention-matched ``Attributes:``
    ``section_fn`` and hands it to the SHARED byte-aware
    :func:`document_returns.splice_docstring_section` (single-line expansion vs
    multi-line insert) — so the byte-offset / CRLF / indent-guard machinery lives ONCE
    in ``document_returns`` and is reused here, never copy-pasted. ``splice_docstring_section``
    probes the docstring via ``_docstring_constant``, which is generic over any node
    carrying a ``body`` (a ``ClassDef`` included), so a class routes through it unchanged."""
    convention = _convention(ast.get_docstring(cls) or "")
    return splice_docstring_section(
        cls, rows, lambda indent, le: _section_lines(convention, indent, attrs, le))


def _documentable_target(
    cls: ast.ClassDef, rows: list[str],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice for ``cls`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/non-test NAME gate (:func:`_is_public`), the HAS-a-
    docstring requirement (``ast.get_docstring`` — the inverse of document-signature),
    the NOT-already-documented gate (:func:`_has_documented_attributes` — refuses a
    full OR partial attribute block), the HAS-a-readable-annotated-field gate
    (:func:`_class_attributes` — empty ⇒ content-free / inference-only / all-unreadable
    ⇒ refuse), and a usable splice point (:func:`_attr_edit`)."""
    if not _is_public(cls):
        return None
    doc = ast.get_docstring(cls)
    if doc is None:
        return None  # undocumented -> document-signature's lane (zero collision)
    if _has_documented_attributes(doc):
        return None  # already records attributes (full or partial) -> no duplication
    attrs = _class_attributes(cls)
    if not attrs:
        return None  # no readable class-level annotated field -> content-free, refuse
    return _attr_edit(cls, rows, attrs)


def _still_all_documented(tree: ast.AST) -> bool:
    """True when EVERY public, documented class in ``tree`` still opens with a docstring
    Constant — the post-splice self-proof that no inserted attributes section displaced
    a docstring or broke a body. The CLASS analogue of
    :func:`document_returns.still_all_documented` (which checks functions); handed to the
    shared :func:`document_returns.apply_section_edits` as its ``still_valid`` override."""
    return all(
        _docstring_constant(node) is not None
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_public(node)
        and ast.get_docstring(node) is not None
    )


def document_attributes(source: str) -> str | None:
    """Return ``source`` with a faithful ``Attributes:`` section spliced into every
    qualifying documented class's docstring, or ``None`` when nothing qualifies (or the
    source does not parse).

    A thin wrapper over the shared :func:`document_returns.apply_section_edits` driver,
    overridden to the CLASS family — it walks ``ast.ClassDef`` nodes and self-validates
    with :func:`_still_all_documented` — routing each class through the attribute-
    specific gate stack (:func:`_documentable_target`). The driver applies the splices
    bottom-up, re-parses, and refuses unless every touched class still opens with its
    docstring. Pure AST → text; deterministic (source/field order, no clock/random)."""
    return apply_section_edits(
        source,
        lambda cls, rows, _tree: _documentable_target(cls, rows),
        node_types=(ast.ClassDef,),
        still_valid=_still_all_documented,
    )


def plan_document_attributes(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the faithful attributes-section plan for one module, or an empty no-op plan.

    Documents every qualifying public class in ``module_rel`` (public name, HAS a
    docstring with no recorded attributes, at least one readable class-level annotated
    field) via :func:`document_attributes`. The shared single-file-rewrite plumbing —
    refuse a test/fixture/non-library file, read the module, record the single rewrite
    with its original for rollback (or a no-op when nothing is documentable) — is
    delegated to :func:`plan_source_rewrite`, the one source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-attributes", document_attributes)


register_module_objective(
    "document-attributes", plan_document_attributes,
    operator="document_attributes",
    description="document the class attributes of classes in {rel} from their class-level annotations",
)
