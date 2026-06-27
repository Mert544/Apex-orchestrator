"""Self-registering develop objective: document-returns — the RETURN-VALUE image
of ``document-raises``, the structural twin that documents the SUCCESS contract.

Where a PUBLIC function (a) HAS a docstring, (b) carries an explicit ``-> T``
return annotation, and (c) does NOT already document its return in ANY convention,
splice a faithful return section into that EXISTING docstring rendering the
annotated type ``T`` VERBATIM. Every ``<T>`` is read straight off ``fn.returns``
via :func:`ast.unparse` — never inferred — so the documented return cannot
misstate the contract. This is the DOCUMENTED-function, ANNOTATION-sourced sibling
of ``document-signature``/``pin-return-type``: ``document-signature`` MINTS a whole
docstring on an UNDOCUMENTED function, ``pin-return-type`` adds a line from the
INFERRED oracle; document-returns fires on a DOCUMENTED, ANNOTATED function and
renders the author's DECLARED annotation. The three are mutually exclusive by the
docstring + annotation predicates, so there is ZERO collision.

THE REFUSE SET (conservative by construction — the value of a documented return is
its faithfulness, so any shape we cannot render faithfully is refused, never
guessed):

  - ``-> None`` / ``-> NoReturn`` (and ``typing.NoReturn`` / a from-import alias of
    either) — there is no value to document. REFUSE.
  - NO return annotation — we document only what is DETERMINISTICALLY annotated
    (the inferred-oracle lane is ``pin-return-type``'s). REFUSE.
  - NO existing docstring — minting a whole docstring is a different, riskier
    objective (``document-signature``); we only ADD to a docstring already there.
    REFUSE.
  - the return ALREADY documented in ANY convention — Sphinx ``:returns:`` /
    ``:return:`` / ``:rtype:`` field, a Google ``Returns:`` / ``Yields:`` section
    header, or a NumPy ``Returns`` header underlined with dashes. No duplication.
    REFUSE.
  - a GENERATOR / async-generator return (``-> Iterator[...]`` / ``Iterable`` /
    ``Generator`` / ``AsyncIterator`` / ``AsyncIterable`` / ``AsyncGenerator``, and
    their ``typing.``/``collections.abc.``/alias spellings) — the value is YIELDED
    not returned and the convention differs (``Yields:``); v1 is conservative.
    REFUSE.
  - an ``@overload`` / ``@typing.overload`` stub — the implementation carries the
    canonical docstring. REFUSE.
  - a property ``@x.setter`` / ``@x.deleter`` — no meaningful return. REFUSE. (A
    plain ``@property`` getter with a non-None annotation MAY be documented.)

STYLE MATCHING. The inserted section MATCHES the docstring's existing convention so
a Sphinx field is never jammed into a Google block: a docstring already using
Google section headers (``Args:`` / ``Parameters:`` / ``Raises:`` / ``Returns:``)
gets a Google ``Returns:`` section; one using Sphinx field lists (``:param:`` /
``:raises:`` / ``:rtype:`` / ``:returns:``) gets a Sphinx ``:returns:`` (+
``:rtype:``) field; a plain-prose docstring with no recognisable sections gets the
DEFAULT — Google ``Returns:`` — chosen to AGREE with the two sibling objectives
``document-raises`` (``Raises:``) and ``pin-return-type`` (``Returns:``), which both
emit Google-style. The rendered description is a FAITHFUL rendering of the
annotation TEXT (``dict[str, int]``), never invented prose semantics.

The single write is behaviour-IDENTICAL (a return section is docstring TEXT — it
changes no runtime value; the docstring stays the function's first statement),
idempotent (a second run finds the return now documented and refuses — a
byte-identical no-op), and deterministic (pure AST → text, source order, no
clock/random). CRLF-SAFE: the inserted line(s) reuse the file's OWN line terminator
(taken from the docstring's closing-quote line), so a CRLF file is never silently
normalised (the java-document-throws CRLF lesson). One-line docstrings
(``\"\"\"Foo.\"\"\"``) are correctly EXPANDED to multi-line, preserving any raw/byte
prefix (``r\"\"\"``) and the quote style. Self-validating: the result must RE-PARSE
and every touched function must still open with its (now longer) docstring Constant
— else the change is refused. Standard one-``plan_fn``-over-every-module shape,
registered via ``_base.register_module_objective`` — same suite-gated, auto-rollback
develop loop as every other objective. ``scope_verify`` is the default ``False`` (a
docstring insert has no red baseline a full-suite gate could wrongly veto) and it is
NOT ``expensive`` (a pure-AST scan). Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.objectives.pin_return_type import _docstring_constant, _is_public
from app.execution.semantic.transforms.base import _get_indent

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)

# A return annotation whose HEAD canonical name is one of these documents NOTHING:
# ``None`` / ``NoReturn`` carry no value; the generator/async-generator types YIELD
# (convention ``Yields:``), so v1 refuses them. Compared after alias resolution, so
# ``from typing import NoReturn as NR`` -> ``-> NR`` and ``typing.NoReturn`` both hit.
_NO_VALUE_RETURNS = frozenset({"None", "NoReturn"})
_GENERATOR_RETURNS = frozenset({
    "Iterator", "Iterable", "Generator",
    "AsyncIterator", "AsyncIterable", "AsyncGenerator",
})
_REFUSE_RETURN_HEADS = _NO_VALUE_RETURNS | _GENERATOR_RETURNS

# A docstring already records a return when ANY of these matches (so a section must
# NOT be added): Sphinx ``:returns:`` / ``:return:`` / ``:rtype:`` field, a Google
# ``Returns:`` / ``Yields:`` line (the BARE section header OR the inline
# ``Returns: <type>`` form document_signature / pin_return_type emit — both anchored
# to ``returns?:`` at a line start, so a SECOND section is never appended on top), or
# a NumPy ``Returns`` header underlined with at least three dashes. Anchored to a
# (whitespace-led) line start so a mid-sentence "returns" is never a false hit.
_SPHINX_RETURN = re.compile(r"(?im)^\s*:(returns?|rtype):")
_GOOGLE_RETURN = re.compile(r"(?im)^\s*(returns?|yields?):")
_NUMPY_RETURN = re.compile(r"(?im)^[ \t]*returns?[ \t]*$\n[ \t]*-{3,}[ \t]*$")

# The docstring's CONVENTION is Sphinx when it carries a field list (``:param:`` /
# ``:raises:`` / ``:rtype:`` / ``:returns:`` / ``:type:`` / ``:yields:``); Google when
# it carries a recognised section header (``Args:`` / ``Parameters:`` / ``Raises:`` /
# ``Returns:`` / ``Yields:`` / ``Attributes:`` / ``Examples:``). Plain prose matches
# neither and falls to the Google default (sibling-consistent).
_SPHINX_FIELD = re.compile(r"(?im)^\s*:(param|parameter|raises?|rtype|returns?|type|yields?)\b")


def _safe_parse(source: str) -> ast.Module | None:
    """``ast.parse(source)`` or ``None`` — a conservative no-op on a source Apex
    cannot parse (a truncated def, or valid newer-grammar syntax on an older
    runtime). Same guarded-parse posture as ``document_raises``."""
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None


def _safe_parse_expr(text: str) -> ast.expr | None:
    """The expression a forward-ref string holds (``\"Iterator[int]\"``), or ``None``
    when it is not a parseable type expression. Guarded like :func:`_safe_parse`."""
    try:
        return ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """Map a LOCAL name to the canonical typing/abc name it was imported AS — the
    seam that lets the refuse-set see ``from typing import NoReturn as NR`` (so
    ``-> NR`` refuses) and ``from collections.abc import Iterator as It``.

    Only ``from <mod> import <name> [as <alias>]`` rows are recorded (the local
    binds to the imported member's own name); a plain ``import typing`` binds the
    MODULE, so ``typing.NoReturn`` is handled by the attribute path instead and
    needs no row here. Deterministic; last binding wins (Python's own rule)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = alias.name
    return aliases


def _head_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """The canonical HEAD name of a (possibly subscripted / dotted / forward-ref)
    return annotation, or ``None`` when it has no simple head.

    ``Subscript`` is peeled to its base (``Iterator[int]`` -> ``Iterator``); a bare
    ``Name`` is resolved through ``aliases`` (``NR`` -> ``NoReturn``); an
    ``Attribute`` yields its final attr (``typing.NoReturn`` -> ``NoReturn``,
    ``collections.abc.Iterator`` -> ``Iterator``); a string ``Constant`` is a
    FORWARD REF whose text is re-parsed as a type expression and recursed
    (``\"Iterator[int]\"`` -> ``Iterator``). ``None`` for any other shape."""
    while isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, str):
            inner = _safe_parse_expr(node.value)
            return _head_name(inner, aliases) if inner is not None else None
    return None


def _documentable_return_type(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, aliases: dict[str, str],
) -> str | None:
    """The faithful return-type TEXT to document for ``fn``, or ``None`` to refuse.

    Refuses (returns ``None``) a function with NO ``-> T`` annotation, and one whose
    annotation HEAD canonical name is in :data:`_REFUSE_RETURN_HEADS` (``None`` /
    ``NoReturn`` carry no value; the generator/async-generator types YIELD). Otherwise
    returns the annotation rendered VERBATIM via :func:`ast.unparse` (``dict[str,
    int]``) — a faithful rendering of the declared type, never invented prose."""
    if fn.returns is None:
        return None
    head = _head_name(fn.returns, aliases)
    if head in _REFUSE_RETURN_HEADS:
        return None
    return ast.unparse(fn.returns)


def _decorator_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Every decorator rendered as text (``property``, ``x.setter``,
    ``typing.overload``) — the seam the overload / property-setter guards read."""
    return [ast.unparse(dec) for dec in fn.decorator_list]


def _is_refused_decoration(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn``'s decorators put it out of scope: an ``@overload`` /
    ``@typing.overload`` stub (the impl carries the canonical docstring) or a
    property ``@x.setter`` / ``@x.deleter`` (no meaningful return). A plain
    ``@property`` getter is NOT refused here (its non-None annotation is documentable
    like any other function)."""
    for text in _decorator_names(fn):
        tail = text.split(".")[-1]
        if tail == "overload":
            return True
        if text.endswith(".setter") or text.endswith(".deleter"):
            return True
    return False


def _has_documented_return(doc: str) -> bool:
    """True when the docstring text ``doc`` already records a return in ANY
    convention, so a return section must NOT be added.

    Covers the Sphinx ``:returns:`` / ``:return:`` / ``:rtype:`` field
    (:data:`_SPHINX_RETURN`), the Google ``Returns:`` / ``Yields:`` line — the bare
    section header OR the inline ``Returns: <type>`` form document_signature /
    pin_return_type emit (:data:`_GOOGLE_RETURN`), and the NumPy ``Returns`` SECTION
    (:data:`_NUMPY_RETURN` — a bare header underlined with dashes). Any one match
    REFUSES — never a duplicate return doc. The ``Yields:`` spellings are included so
    a generator already documented as a section is never double-documented either."""
    return (
        _SPHINX_RETURN.search(doc) is not None
        or _GOOGLE_RETURN.search(doc) is not None
        or _NUMPY_RETURN.search(doc) is not None
    )


def _convention(doc: str) -> str:
    """The docstring's section CONVENTION: ``"sphinx"`` when it carries a Sphinx field
    list (``:param:`` / ``:raises:`` / ``:rtype:`` …), else ``"google"`` (a Google
    section header, OR plain prose — the sibling-consistent default). Deterministic;
    Sphinx is preferred when both shapes somehow appear (a field list is the more
    explicit signal)."""
    if _SPHINX_FIELD.search(doc) is not None:
        return "sphinx"
    return "google"


def _section_lines(convention: str, indent: str, type_text: str, le: str) -> list[str]:
    """The return-section BODY as already-indented source lines (each ending with the
    file's own terminator ``le``), in the given ``convention``.

    Google (the default): a blank separator then a ``Returns:`` header and one
    indented type line. Sphinx: a ``:returns:`` line carrying the type text plus an
    ``:rtype:`` line (the two reST return fields). Blank separators are emitted EMPTY
    (no indent) per the PEP-257 / black convention. The rendered text is the
    annotation VERBATIM, never invented prose."""
    if convention == "sphinx":
        return [
            f"{indent}:returns: {type_text}{le}",
            f"{indent}:rtype: {type_text}{le}",
        ]
    return [
        le,
        f"{indent}Returns:{le}",
        f"{indent}    {type_text}{le}",
    ]


def _line_ending(line: str) -> str:
    """The line terminator of ``line`` — ``"\\r\\n"`` / ``"\\r"`` / ``"\\n"`` (CRLF-safe
    splice: the inserted line reuses the file's OWN terminator), or ``"\\n"`` for a
    final line with none. The java-document-throws CRLF lesson, applied locally."""
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return "\n"


def _multiline_edit(
    const: ast.Constant, rows: list[str], convention: str, type_text: str,
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice that inserts the return section
    BEFORE a MULTI-LINE docstring's closing-quote line, or ``None`` to refuse.

    The new lines land at the 0-based closing-quote index (``end_lineno - 1``) at that
    line's leading whitespace — so the docstring reads ``…prose… → Returns: <T> →
    closing quotes`` — using the file's own line terminator. Refuses when the
    closing-quote indent is not pure whitespace (a corruptible header-shared shape)."""
    close_idx = (const.end_lineno or 0) - 1
    if close_idx < 0 or close_idx >= len(rows):
        return None
    indent = _get_indent(rows[close_idx])
    if not indent.isspace():
        return None
    le = _line_ending(rows[close_idx])
    section = _section_lines(convention, indent, type_text, le)
    return close_idx, close_idx, section


def _oneline_edit(
    const: ast.Constant, rows: list[str], convention: str, type_text: str,
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice that EXPANDS a single-line
    docstring (``\"\"\"Foo.\"\"\"`` on its own line) to multi-line with the return
    section, or ``None`` to refuse.

    The one docstring line is rewritten as ``<prefix+quote+body> → blank → Returns:
    <T> → <indent+closing-quote>``, preserving any raw/byte prefix and the quote
    style (the closing quote is the literal's last three source chars) and the file's
    own line terminator. Refuses a header-shared one-liner (``def f(): \"\"\"x\"\"\"`` —
    the line's leading indent is not pure whitespace) and any literal whose
    open/close quotes are too short to split safely."""
    idx = (const.lineno or 0) - 1
    if idx < 0 or idx >= len(rows):
        return None
    line = rows[idx]
    indent = _get_indent(line)
    if not indent.isspace():
        return None
    le = _line_ending(line)
    # ``col_offset`` / ``end_col_offset`` are UTF-8 BYTE offsets, NOT str indices —
    # so the literal/head_text MUST be sliced in BYTE space. Indexing the ``str``
    # ``line`` directly overshoots by one per non-ASCII char (e.g. ``Naïve`` -> a
    # stray ``"`` kept in the rebuilt head), silently corrupting __doc__ while still
    # re-parsing. Decoding from bytes restores "first rebuilt line is byte-identical
    # save for losing its closing quotes" for ASCII and non-ASCII alike.
    raw = line.encode("utf-8")
    col, end_col = const.col_offset, const.end_col_offset or 0
    literal = raw[col:end_col].decode("utf-8")
    quote = literal[-3:]
    if quote not in ('"""', "'''") or len(literal) < 6:
        return None
    # The whole source up to (but excluding) the closing quote — the indent, any
    # raw/byte prefix, the opening quote, and the one-line body — kept VERBATIM.
    head_text = raw[: end_col - 3].decode("utf-8")
    section = _section_lines(convention, indent, type_text, le)
    rebuilt = [f"{head_text}{le}", *section, f"{indent}{quote}{le}"]
    return idx, idx + 1, rebuilt


def _return_edit(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rows: list[str], type_text: str,
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice that documents ``fn``'s return, or
    ``None`` to refuse. Dispatches to :func:`_oneline_edit` for a single-line
    docstring (open and close on one line) and :func:`_multiline_edit` otherwise; the
    section convention is matched to the existing docstring text."""
    const = _docstring_constant(fn)
    if const is None or const.lineno is None or const.end_lineno is None:
        return None
    convention = _convention(ast.get_docstring(fn) or "")
    if const.lineno == const.end_lineno:
        return _oneline_edit(const, rows, convention, type_text)
    return _multiline_edit(const, rows, convention, type_text)


def _documentable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rows: list[str],
    aliases: dict[str, str],
) -> tuple[int, int, list[str]] | None:
    """A ``(start, stop, replacement_rows)`` splice for ``fn`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/non-test NAME gate (:func:`_is_public`), the
    decorator gate (:func:`_is_refused_decoration` — ``@overload`` / property
    setter/deleter), the HAS-a-docstring requirement (``ast.get_docstring`` — the
    inverse of document-signature), the documentable-annotation gate
    (:func:`_documentable_return_type` — no annotation / None / NoReturn / generator
    => refuse), the NOT-already-documented gate (:func:`_has_documented_return`), and a
    usable splice point (:func:`_return_edit`)."""
    if not _is_public(fn) or _is_refused_decoration(fn):
        return None
    doc = ast.get_docstring(fn)
    if doc is None:
        return None  # undocumented -> document-signature's lane (zero collision)
    type_text = _documentable_return_type(fn, aliases)
    if type_text is None:
        return None  # no annotation / None / NoReturn / generator -> refuse
    if _has_documented_return(doc):
        return None  # already records a return (any convention) -> no duplication
    return _return_edit(fn, rows, type_text)


def _still_all_documented(tree: ast.AST) -> bool:
    """True when EVERY public, documented, non-test function in ``tree`` still opens
    with a docstring Constant — the post-splice self-proof that no inserted return
    section displaced a docstring or broke a body."""
    return all(
        _docstring_constant(node) is not None
        for node in ast.walk(tree)
        if isinstance(node, _DEF) and _is_public(node)
        and ast.get_docstring(node) is not None
    )


def document_returns(source: str) -> str | None:
    """Return ``source`` with a faithful return section spliced into every qualifying
    documented + annotated function's docstring, or ``None`` when nothing qualifies
    (or the source does not parse).

    Each edit is applied bottom-up (descending start index) so earlier line offsets
    stay valid. Self-validating: the result must RE-PARSE and every touched function
    must still open with its docstring Constant — else the change is refused. Pure AST
    → text; deterministic (source order, no clock/random)."""
    old_tree = _safe_parse(source)
    if old_tree is None:
        return None

    rows = source.splitlines(keepends=True)
    aliases = _import_aliases(old_tree)
    defs = sorted(
        (n for n in ast.walk(old_tree) if isinstance(n, _DEF)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    edits = [e for n in defs if (e := _documentable_target(n, rows, aliases))]
    if not edits:
        return None

    for start, stop, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        rows[start:stop] = replacement
    landed = "".join(rows)

    new_tree = _safe_parse(landed)
    if new_tree is None:
        return None
    if not _still_all_documented(new_tree) or landed == source:
        return None
    return landed


def plan_document_returns(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the faithful return-section plan for one module, or an empty no-op plan.

    Documents every qualifying public function in ``module_rel`` (public name, HAS a
    docstring with no recorded return, an explicit non-None/non-generator ``-> T``
    annotation, not an overload / property setter) via :func:`document_returns`. The
    shared single-file-rewrite plumbing — refuse a test/fixture/non-library file, read
    the module, record the single rewrite with its original for rollback (or a no-op
    when nothing is documentable) — is delegated to :func:`plan_source_rewrite`, the
    one source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-returns", document_returns)


register_module_objective(
    "document-returns", plan_document_returns,
    operator="document_returns",
    description="document the return value of functions in {rel} from their return annotation",
)
