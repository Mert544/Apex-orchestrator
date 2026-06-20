"""Shared helpers reused byte-identically by sibling semantic transforms.

Several transforms independently extracted the *same* helper while shrinking
their ``apply`` functions in parallel; those copies were genuinely identical
(same executable body) and are consolidated here so a fix lands in one place.
Each transform imports the helper under its existing private alias, so call
sites stay behavior-identical. Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import ast
import copy
import io
import tokenize
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def source_has_comment(source: str) -> bool:
    """True when ``source`` contains a ``#`` comment token (incl. pragmas).

    ``ast.unparse`` reconstructs code from the AST, which carries no comments, so
    any whole-module unparse silently deletes every ``#`` comment -- including
    ``# type: ignore`` / ``# noqa`` pragmas that are load-bearing. We detect
    comments via ``tokenize`` (robust against ``#`` inside strings, which is *not*
    a comment) so the rewrite driver can refuse rather than destroy them.

    Tokenization that fails (e.g. on a syntax error) is treated conservatively as
    "has a comment" so we never rewrite a file we could not fully inspect.
    """
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                return True
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return True
    return False


def node_offset(source: str, node: ast.AST) -> int | None:
    """Convert a node's ``(lineno, col_offset)`` into an absolute string offset.

    Returns ``None`` when the node carries no position or points past the end of
    ``source``. ``col_offset`` is a UTF-8 byte offset; the byte prefix is decoded
    so the splice lands correctly even with non-ASCII text earlier on the line.
    """
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    if lineno is None or col is None:
        return None
    lines = source.splitlines(keepends=True)
    if lineno - 1 >= len(lines):
        return None
    offset = sum(len(lines[i]) for i in range(lineno - 1))
    # col_offset is a byte offset; decode the byte prefix to a char offset so the
    # splice lands correctly even with non-ASCII text earlier on the line.
    line = lines[lineno - 1]
    prefix = line.encode("utf-8")[:col].decode("utf-8", errors="ignore")
    return offset + len(prefix)


def parse_or_none(source: str) -> ast.Module | None:
    """Parse ``source`` to a module, returning ``None`` on a syntax error.

    Consolidates the ``try: tree = ast.parse(source) except SyntaxError: return
    None`` parse-guard that several ``apply`` functions opened with, byte-for-byte.
    """
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None


def run_rewrite_transformer(
    tree: ast.Module,
    transformer: ast.NodeTransformer,
    source: str,
) -> str | None:
    """Drive a rewrite ``NodeTransformer`` and return new source, or ``None``.

    Consolidates the visit-driver tail shared byte-for-byte by the AST-rewriting
    transforms (``augmented_assign``, ``chained_comparison``, ``startswith_tuple``):
    visit the tree, bail if nothing changed, fix locations, unparse, re-parse to
    guarantee the result is syntactically valid, restore a trailing newline, and
    refuse a no-op. The caller constructs its own ``transformer`` and builds the
    patch result; only the identical middle stays here.

    Because the emit goes through ``ast.unparse`` -- which reconstructs the whole
    module from an AST that carries no comments -- it would silently delete every
    ``#`` comment (including ``# type: ignore`` / ``# noqa`` pragmas), flip quote
    styles, and collapse blank lines. A transform advertised as a one-line edit
    must not reformat the whole file, so when the source contains *any* comment we
    refuse the rewrite (return ``None``) rather than destroy it. Comment-free
    files are unaffected and rewrite exactly as before.
    """
    new_tree = transformer.visit(tree)
    if not transformer.changed:  # type: ignore[attr-defined]
        return None

    # Whole-module unparse drops comments; refuse instead of silently deleting.
    if source_has_comment(source):
        return None

    ast.fix_missing_locations(new_tree)
    try:
        new_source = ast.unparse(new_tree)
    except Exception:
        return None

    # Re-parse to guarantee the rewrite is syntactically valid before emitting.
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    if source.endswith("\n") and not new_source.endswith("\n"):
        new_source += "\n"

    if new_source == source:
        return None

    return new_source


def _comment_tokens(source: str) -> list[tuple[int, int, str]] | None:
    """The ``(start_row, start_col, text)`` of every ``#`` comment token.

    Returns ``None`` when the source cannot be tokenized (mirroring
    :func:`source_has_comment`'s conservative stance: an un-inspectable file is
    treated as "do not touch"). Positions are token ``start`` coordinates
    (1-based row, 0-based col) so a comment can be located relative to a node's
    line span.
    """
    out: list[tuple[int, int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.start[1], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    return out


def _comment_inside_span(
    tok_row: int, tok_col: int,
    lineno: int, end_lineno: int, start_char: int, end_char: int,
) -> bool:
    """True if a comment token at ``(tok_row, tok_col)`` is INSIDE the node span.

    A trailing comment sits on the node's last line but AFTER ``end_col_offset``,
    so it is OUTSIDE the span and must survive; a comment on a line strictly
    between the first and last, or before the node's start on the first line, is
    INSIDE and would be destroyed by the local unparse. ``tok_col`` and the
    char bounds are character (not byte) offsets on their respective lines."""
    if tok_row < lineno or tok_row > end_lineno:
        return False
    if lineno < tok_row < end_lineno:
        return True
    if tok_row == lineno and tok_col < start_char:
        return True
    if tok_row == end_lineno and tok_col < end_char:
        return True
    return False


def _node_span(node: ast.AST) -> tuple[int, int, int, int] | None:
    """A node's ``(lineno, end_lineno, col_offset, end_col_offset)`` or ``None``.

    ``None`` whenever any of the four position attributes is missing, so the
    caller declines rather than splice with an incomplete span."""
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    col = getattr(node, "col_offset", None)
    end_col = getattr(node, "end_col_offset", None)
    if None in (lineno, end_lineno, col, end_col):
        return None
    return lineno, end_lineno, col, end_col  # type: ignore[return-value]


def _byte_col_to_char(line: str, col: int) -> int:
    """Convert a UTF-8 byte ``col_offset`` on ``line`` to a character index.

    AST column offsets are byte offsets; decoding the byte prefix yields the char
    index so the splice lands correctly even with non-ASCII text earlier on the
    line (consistent with :func:`node_offset`)."""
    return len(line.encode("utf-8")[:col].decode("utf-8", errors="ignore"))


def _outside_span_comments(
    all_comments: list[tuple[int, int, str]],
    lineno: int, end_lineno: int, start_char: int, end_char: int,
) -> list[tuple[int, int, str]] | None:
    """The comments OUTSIDE the span, or ``None`` if any fall inside it.

    A comment inside the span would be destroyed by the local unparse, so the
    caller must refuse; we signal that by returning ``None``."""
    outside = [
        t for t in all_comments
        if not _comment_inside_span(t[0], t[1], lineno, end_lineno, start_char, end_char)
    ]
    return outside if len(outside) == len(all_comments) else None


def _reindent_segment(new_text: str, prefix: str) -> str:
    """Re-indent continuation lines of ``new_text`` to ``prefix``'s indentation.

    Only applies when ``prefix`` is pure indentation (the node started the line);
    keeps nested blocks of a multi-line unparse syntactically valid."""
    indent = " " * len(prefix) if prefix == "" or prefix.isspace() else ""
    if "\n" not in new_text or not indent:
        return new_text
    head, *rest = new_text.split("\n")
    return head + "".join("\n" + indent + r for r in rest)


def _splice_frame(
    source: str, original: ast.stmt,
) -> tuple[list[str], int, int, str, str, int, int] | None:
    """Resolve ``original``'s span into the pieces the splice needs, or ``None``.

    Returns ``(lines, lineno, end_lineno, prefix, suffix, start_char, end_char)``
    where ``prefix`` is the first line up to the node, ``suffix`` is the last line
    after it (indent / trailing comment preserved verbatim), and the char bounds
    locate the node within its first/last line. ``None`` when the node has no
    full span or its end line is past the source."""
    span = _node_span(original)
    if span is None:
        return None
    lineno, end_lineno, col, end_col = span
    lines = source.splitlines(keepends=True)
    if end_lineno > len(lines):
        return None
    first_line = lines[lineno - 1]
    last_line = lines[end_lineno - 1]
    start_char = _byte_col_to_char(first_line, col)
    end_char = _byte_col_to_char(last_line, end_col)
    return (lines, lineno, end_lineno,
            first_line[:start_char], last_line[end_char:], start_char, end_char)


def splice_node_rewrite(
    source: str,
    original: ast.stmt,
    rewritten: ast.stmt,
) -> str | None:
    """Replace just ``original``'s line span with a local unparse of ``rewritten``.

    Edits ONLY the target statement's span (``lineno``/``end_lineno`` and the
    byte ``col_offset``/``end_col_offset`` of its first/last line), renders the
    replacement by unparsing ``rewritten`` in isolation, re-indents continuation
    lines to the statement's original indent, splices it into the line list, and
    RE-PARSES the whole file to guarantee validity. Any text on the first line
    before the node (indent) and on the last line after it (a trailing ``#``
    comment, a closing ``)`` of an enclosing call, ...) is preserved verbatim, so
    a comment OUTSIDE the node survives the edit.

    Honesty guard: if a ``#`` comment lives INSIDE the rewritten span it would be
    destroyed by the local unparse, so we refuse (return ``None``). We also verify
    that the comment-token set OUTSIDE the span is byte-identical before and after
    the splice; any drift means we refuse. Returns ``None`` on any failure so the
    caller declines rather than emit a lossy patch.
    """
    frame = _splice_frame(source, original)
    if frame is None:
        return None
    lines, lineno, end_lineno, prefix, suffix, start_char, end_char = frame

    # Refuse if a comment lives INSIDE the span we are about to overwrite (the
    # local unparse carries no comments). A trailing comment after ``end_col`` is
    # OUTSIDE and survives in ``suffix``.
    all_comments = _comment_tokens(source)
    if all_comments is None:
        return None
    before_outside = _outside_span_comments(
        all_comments, lineno, end_lineno, start_char, end_char)
    if before_outside is None:
        return None

    try:
        new_text = ast.unparse(rewritten)
    except Exception:
        return None

    spliced = prefix + _reindent_segment(new_text, prefix) + suffix
    new_source = "".join(lines[: lineno - 1] + [spliced] + lines[end_lineno:])

    if not _splice_is_safe(source, new_source, before_outside):
        return None
    if source.endswith("\n") and not new_source.endswith("\n"):
        new_source += "\n"
    return new_source


def _splice_is_safe(
    source: str, new_source: str, before_outside: list[tuple[int, int, str]],
) -> bool:
    """True if ``new_source`` parses, is a real change, and kept every comment.

    Re-parses to guarantee syntactic validity, rejects a no-op, and verifies the
    outside-span comment set is byte-identical (the splice may shift line counts,
    so we compare by comment TEXT and order, not absolute coordinates)."""
    if new_source == source:
        return False
    if parse_or_none(new_source) is None:
        return False
    after = _comment_tokens(new_source)
    if after is None:
        return False
    return [t[2] for t in after] == [t[2] for t in before_outside]


def run_splice_rewrite(
    tree: ast.Module,
    transformer: ast.NodeTransformer,
    source: str,
) -> str | None:
    """Drive a rewrite ``NodeTransformer`` and emit via a comment-preserving splice.

    Comment-free files keep the prior exact whole-module ``ast.unparse`` path
    (byte-identical to before, no characterization churn). When the source has a
    comment, instead of refusing we re-run the transform on a fresh tree while
    remembering each top-level statement's ORIGINAL span, then splice only the
    statements whose local unparse changed -- so comments outside those statements
    survive. If any changed statement cannot be spliced safely (a comment inside
    its span, an un-tokenizable result, ...) we fall back to refusing (``None``),
    preserving the honesty guarantee.
    """
    new_tree = transformer.visit(tree)
    if not transformer.changed:  # type: ignore[attr-defined]
        return None

    if not source_has_comment(source):
        # Prior exact path: byte-identical to before for comment-free files.
        ast.fix_missing_locations(new_tree)
        try:
            new_source = ast.unparse(new_tree)
        except Exception:
            return None
        if parse_or_none(new_source) is None:
            return None
        if source.endswith("\n") and not new_source.endswith("\n"):
            new_source += "\n"
        return new_source if new_source != source else None

    # Comment path: splice only the statements whose unparse changed. Re-parse a
    # pristine copy so we keep ORIGINAL spans to splice against; ``new_tree`` (the
    # already-transformed tree) supplies the rewritten statements.
    pristine = parse_or_none(source)
    if pristine is None:
        return None
    ast.fix_missing_locations(new_tree)

    new_source = _splice_changed_statements(source, pristine, new_tree)
    if new_source is None or new_source == source:
        return None
    return new_source


_STMT_BODY_FIELDS = ("body", "orelse", "finalbody", "handlers")


def _changed_leaf_statements(
    orig: ast.stmt, new: ast.stmt,
) -> list[tuple[ast.stmt, ast.stmt]] | None:
    """The finest-grained changed ``(original, rewritten)`` statement pairs.

    Recurses into compound-statement bodies (``body``/``orelse``/``finalbody``/
    ``handlers``) so an edit buried inside a ``def``/``if``/``try`` splices only
    the innermost changed statement -- keeping the spliced span (and any comments
    just outside it) as small as possible. When a compound statement's HEADER
    changed (not just a nested body), the whole compound statement is the unit.
    Returns ``None`` if the two statements are not structurally parallel."""
    try:
        if ast.unparse(orig) == ast.unparse(new):
            return []
    except Exception:
        return None
    if type(orig) is not type(new):
        return [(orig, new)]

    # If a recursable body differs but the rest of the header is identical, drill
    # into that body; otherwise the header itself changed -> splice the whole node.
    nested: list[tuple[ast.stmt, ast.stmt]] = []
    for field in _STMT_BODY_FIELDS:
        sub = _recurse_body_field(orig, new, field)
        if sub is _PARSE_FAIL:
            return None
        if sub is _WHOLE_NODE:
            return [(orig, new)]
        nested.extend(sub)  # type: ignore[arg-type]

    # Anything OUTSIDE the recursable bodies that changed -> splice the whole node.
    if _header_differs(orig, new):
        return [(orig, new)]
    return nested


_WHOLE_NODE: list = []  # sentinel: a change forces splicing the whole statement
_PARSE_FAIL: list = []  # sentinel: an un-unparsable item -> caller refuses


def _recurse_body_field(orig: ast.stmt, new: ast.stmt, field: str):
    """Recurse one body field, returning nested pairs or a sentinel.

    Returns ``_WHOLE_NODE`` when this field's change must be handled by splicing
    the whole enclosing statement (length mismatch, or a non-``stmt`` entry like
    an ``ExceptHandler`` whose unparse differs), ``_PARSE_FAIL`` on an unparsable
    item, else the list of changed leaf pairs found within the field."""
    o_body = getattr(orig, field, None)
    n_body = getattr(new, field, None)
    if not isinstance(o_body, list) or not isinstance(n_body, list):
        return []
    if len(o_body) != len(n_body):
        return _WHOLE_NODE
    nested: list[tuple[ast.stmt, ast.stmt]] = []
    for o_item, n_item in zip(o_body, n_body):
        if not isinstance(o_item, ast.stmt) or not isinstance(n_item, ast.stmt):
            try:
                if ast.unparse(o_item) != ast.unparse(n_item):  # type: ignore[arg-type]
                    return _WHOLE_NODE
            except Exception:
                return _PARSE_FAIL
            continue
        sub = _changed_leaf_statements(o_item, n_item)
        if sub is None:
            return _PARSE_FAIL
        nested.extend(sub)
    return nested


def _header_differs(orig: ast.stmt, new: ast.stmt) -> bool:
    """True if ``orig``/``new`` differ once their recursable bodies are ignored."""
    o_copy = _blank_bodies(orig)
    n_copy = _blank_bodies(new)
    return ast.dump(o_copy) != ast.dump(n_copy)


def _blank_bodies(node: ast.stmt) -> ast.AST:
    """A shallow copy of ``node`` with its recursable statement bodies emptied.

    Used to compare only the compound statement's HEADER (test, args, items, ...)
    so a change confined to a nested body is not misread as a header change."""
    clone = copy.copy(node)
    for field in _STMT_BODY_FIELDS:
        if isinstance(getattr(clone, field, None), list):
            setattr(clone, field, [])
    return clone


def _splice_changed_statements(
    source: str, pristine: ast.Module, rewritten: ast.Module,
) -> str | None:
    """Splice each changed leaf statement over its original span, last-first.

    Walks the two top-level statement lists in lockstep, recursing into compound
    bodies to find the finest changed statements, then splices each from the LAST
    one backwards (so earlier line numbers stay valid). Returns ``None`` if the
    trees are not structurally parallel or any splice declines."""
    orig_stmts = list(pristine.body)
    new_stmts = list(rewritten.body)
    if len(orig_stmts) != len(new_stmts):
        return None
    pairs: list[tuple[ast.stmt, ast.stmt]] = []
    for orig, new in zip(orig_stmts, new_stmts):
        leaves = _changed_leaf_statements(orig, new)
        if leaves is None:
            return None
        pairs.extend(leaves)

    # Splice from the bottom of the file upward to keep line numbers stable.
    pairs.sort(key=lambda p: getattr(p[0], "lineno", 0), reverse=True)
    result = source
    for orig, new in pairs:
        spliced = splice_node_rewrite(result, orig, new)
        if spliced is None:
            return None
        result = spliced
    return result


def parse_and_collect_lines(
    source: str,
    collect: Callable[[ast.Module], list],
) -> tuple[list, list[str]] | None:
    """Parse, collect target nodes, and split into lines for splice-based transforms.

    Consolidates the prologue shared byte-for-byte by the line-splicing transforms
    (``collection_literal``, ``isinstance_merge``, ``negated_comparison``): parse
    the source (bail on syntax error), collect candidate nodes via ``collect``,
    bail when there are none, and split ``source`` into keepends lines. Returns
    ``(nodes, lines)`` or ``None``; the caller still drives its own splice loop.
    """
    tree = parse_or_none(source)
    if tree is None:
        return None
    nodes = collect(tree)
    if not nodes:
        return None
    return nodes, source.splitlines(keepends=True)
