"""Convert a simple ``"...%s..." % args`` expression into an f-string.

The ``%``-format sibling of :mod:`app.execution.fstring_convert` (which handles
``.format``): a STRING-LITERAL percent-format whose template uses only bare
``%s`` conversions, one per argument, each filled by a simple expression, is
exactly an f-string::

    "%s = %s" % (a, b)        -> f"{a} = {b}"
    "x=%s" % v                -> f"x={v}"
    "%s" % self.name          -> f"{self.name}"
    "100%% of %s" % v         -> f"100% of {v}"     (``%%`` is a literal percent)

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.BinOp`` with ``op == ast.Mod`` whose ``left`` is an
    ``ast.Constant`` string literal (the format template);
  - the template uses ONLY bare ``%s`` placeholders and literal ``%%`` — any
    other conversion (``%d``, ``%r``, ``%f``, mapping ``%(name)s``, a width or
    precision like ``%5s`` / ``%.2f``, or a flag) skips the occurrence: every
    ``%`` must be immediately part of a ``%s`` or a ``%%``;
  - the right side supplies the args — an ``ast.Tuple``'s elements in order, or
    else the single expression as the sole arg;
  - the number of ``%s`` placeholders EQUALS the number of args;
  - every arg is a SIMPLE expression — an ``ast.Name``, an attribute chain of
    names, or an ``ast.Constant`` — so a bare ``{<arg>}`` needs no precedence
    parens;
  - the literal's recovered source must be a plain ``"`` / ``'`` string with no
    prefix (raw / bytes / already-f are skipped) and contain no backslash; the
    literal and the whole BinOp must each live on a SINGLE line so the
    column-span splice is trivially correct.

Built text is independently re-parsed: it must be exactly an ``ast.JoinedStr``
with the expected number of ``FormattedValue`` fields, or the occurrence is
skipped. Edits are column-span replacements located by the AST (no unparse
round-trip), so comments and formatting elsewhere survive untouched.

Conservative by design — any source segment that can't be recovered skips that
occurrence, and the rewritten module must re-parse or the whole plan blocks.
Rewrites are applied bottom-up and right-to-left within a line so earlier
offsets stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import ColumnRewrite as _Rewrite
from app.execution._transform_base import is_simple_arg as _is_simple_arg
from app.execution._transform_base import literal_inner as _literal_inner
from app.execution._transform_base import plan_single_module_column_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_percent_to_fstring"]

# Shared with fstring-convert via ``app.execution._transform_base``:
#   _Rewrite       — the located single-line column-splice value (``ColumnRewrite``)
#   _is_simple_arg — the "bare {name} is safe" predicate (``is_simple_arg``)
#   _literal_inner — the plain-string-literal (quote, inner) recovery (``literal_inner``)
# The percent-specific ``%s``/``%%`` parsing, brace-escaping and BinOp matching
# below stay private — they are NOT the ``.format`` logic and must not be merged.


def _split_template(inner: str) -> list[str] | None:
    """Split the template's INNER text (literal content, quotes stripped) on
    bare ``%s`` placeholders, returning the literal segments between them.

    ``%%`` collapses to a single literal ``%`` inside a segment and is NOT a
    placeholder. The returned list has ``count + 1`` segments for ``count``
    placeholders. Returns None when any ``%`` is not immediately part of a
    ``%s`` or a ``%%`` — i.e. any other conversion / width / precision / flag /
    mapping key, or a trailing lone ``%`` — so the occurrence is skipped."""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "%":
            if i + 1 >= n:
                return None  # trailing lone '%'
            nxt = inner[i + 1]
            if nxt == "%":
                buf.append("%")  # literal percent, not a placeholder
                i += 2
                continue
            if nxt == "s":
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            return None  # any other conversion / spec / flag disqualifies
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments


def _try_binop(node: ast.BinOp, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``%``-format BinOp, return
    its rewrite, else None."""
    if not isinstance(node.op, ast.Mod):
        return None
    template = node.left
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None

    # Determine the args: a Tuple supplies its elements in order; any other
    # expression is the sole arg.
    right = node.right
    if isinstance(right, ast.Tuple):
        args: list[ast.expr] = list(right.elts)
        # A starred element can't be a positional arg we map to a placeholder.
        if any(isinstance(a, ast.Starred) for a in args):
            return None
    else:
        args = [right]
    if not all(_is_simple_arg(a) for a in args):
        return None

    # Single-line literal and single-line BinOp keep the column splice trivial.
    if template.lineno != template.end_lineno:
        return None
    if node.lineno != node.end_lineno:
        return None

    literal_src = ast.get_source_segment(source, template)
    if literal_src is None:
        return None
    parsed = _literal_inner(literal_src)
    if parsed is None:
        return None
    quote, inner = parsed

    segments = _split_template(inner)
    if segments is None:
        return None
    count = len(segments) - 1
    if count != len(args):
        return None
    if count == 0:
        return None  # nothing to interpolate — leave it alone

    arg_srcs: list[str] = []
    for arg in args:
        seg = ast.get_source_segment(source, arg)
        if seg is None:
            return None
        # A simple arg's source never contains a brace; guard anyway so the
        # built f-string can't grow an unexpected field.
        if "{" in seg or "}" in seg or "\\" in seg:
            return None
        arg_srcs.append(seg)

    # Literal braces already in the template must be escaped for the f-string.
    def _escape(text: str) -> str:
        return text.replace("{", "{{").replace("}", "}}")

    parts: list[str] = [_escape(segments[0])]
    for arg_src, seg in zip(arg_srcs, segments[1:]):
        parts.append("{" + arg_src + "}")
        parts.append(_escape(seg))
    text = "f" + quote + "".join(parts) + quote

    # CRUCIAL safety: the built text must parse to exactly a JoinedStr with the
    # expected number of FormattedValue fields, or we skip the occurrence.
    try:
        expr = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(expr, ast.JoinedStr):
        return None
    formatted = [v for v in expr.values if isinstance(v, ast.FormattedValue)]
    if len(formatted) != count:
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset, text)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every convertible string-literal ``%``-format BinOp in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            rw = _try_binop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def plan_percent_to_fstring(project_root: str | Path,
                            module_rel: str) -> RenamePlan:
    """Build the single-module percent-to-fstring plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every simple
    string-literal ``"...%s..." % args`` expression into the equivalent
    f-string. An empty plan means nothing matched (a no-op, not a failure).

    The read -> parse -> collect -> apply -> re-parse -> build-plan scaffold (and
    its blocker wording) is the shared
    :func:`~app.execution._transform_base.plan_single_module_column_rewrite`;
    only the ``%``-format-specific :func:`_collect_rewrites` is local."""
    return plan_single_module_column_rewrite(
        project_root, module_rel,
        plan_label="percent-to-fstring", collect=_collect_rewrites)
