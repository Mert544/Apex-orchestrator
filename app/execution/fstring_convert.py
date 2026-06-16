"""Convert a simple ``"...{}...".format(args)`` call into an f-string.

A small, surgical modernization: a STRING-LITERAL ``.format(...)`` call whose
template uses only anonymous ``{}`` placeholders, one per positional argument,
each filled by a simple expression, is exactly an f-string::

    "{} = {}".format(a, b)        -> f"{a} = {b}"
    "x={}".format(v)              -> f"x={v}"
    "{}".format(self.name)        -> f"{self.name}"

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the call's ``func`` is an ``ast.Attribute`` ``attr == "format"`` whose
    ``.value`` is an ``ast.Constant`` string literal (the format template);
  - the template contains ONLY plain ``{}`` placeholders — no index ``{0}``,
    no name ``{x}``, no format spec ``{:0.2f}``, no conversion ``{!r}`` and no
    nested braces; escaped braces ``{{`` / ``}}`` skip the occurrence entirely;
  - the number of ``{}`` placeholders EQUALS the number of positional args;
  - every arg is positional (no keywords, no star-args) and is a SIMPLE
    expression — an ``ast.Name``, an attribute chain of names, or an
    ``ast.Constant`` — so a bare ``{<arg>}`` needs no precedence parens;
  - the literal's recovered source must be a plain ``"`` / ``'`` string with no
    prefix (raw / bytes / already-f are skipped) and contain no backslash and
    no brace other than the placeholders; the literal and the whole call must
    each live on a SINGLE line so the column-span splice is trivially correct.

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

__all__ = ["plan_fstring_convert"]

# Shared with percent-to-fstring via ``app.execution._transform_base``:
#   _Rewrite       — the located single-line column-splice value (``ColumnRewrite``)
#   _is_simple_arg — the "bare {name} is safe" predicate (``is_simple_arg``)
#   _literal_inner — the plain-string-literal (quote, inner) recovery (``literal_inner``)
# The convert-specific ``{}``-placeholder parsing and call-shape matching below
# stay private — they are NOT the percent ``%s`` logic and must not be merged.


def _split_template(inner: str) -> list[str] | None:
    """Split the template's INNER text (literal content, quotes stripped) on
    plain ``{}`` placeholders, returning the literal segments between them.

    The returned list has ``count + 1`` segments for ``count`` placeholders.
    Returns None when the template has any brace other than a plain ``{}``
    placeholder — an index/name/spec/conversion, a nested or escaped brace, or
    an unmatched brace — so the occurrence is skipped."""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "{":
            # Escaped braces are out of scope — skip the whole occurrence.
            if i + 1 < n and inner[i + 1] == "{":
                return None
            # Must be exactly "{}" — no index/name/spec/conversion inside.
            if i + 1 < n and inner[i + 1] == "}":
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            return None
        if ch == "}":
            # A lone or escaped "}}" — anything brace-y disqualifies.
            return None
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments


def _try_call(node: ast.Call, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``.format(...)`` call, return
    its rewrite, else None."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "format":
        return None
    template = func.value
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None

    # No keywords, no star-args — all positional and all simple.
    if node.keywords:
        return None
    if any(isinstance(a, ast.Starred) for a in node.args):
        return None
    if not all(_is_simple_arg(a) for a in node.args):
        return None

    # Single-line literal and single-line call keep the column splice trivial.
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
    if count != len(node.args):
        return None
    if count == 0:
        return None  # nothing to interpolate — leave it alone

    arg_srcs: list[str] = []
    for arg in node.args:
        seg = ast.get_source_segment(source, arg)
        if seg is None:
            return None
        # A simple arg's source never contains a brace; guard anyway so the
        # built f-string can't grow an unexpected field.
        if "{" in seg or "}" in seg or "\\" in seg:
            return None
        arg_srcs.append(seg)

    parts: list[str] = [segments[0]]
    for arg_src, seg in zip(arg_srcs, segments[1:]):
        parts.append("{" + arg_src + "}")
        parts.append(seg)
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
    """Every convertible string-literal ``.format(...)`` call in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rw = _try_call(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def plan_fstring_convert(project_root: str | Path,
                         module_rel: str) -> RenamePlan:
    """Build the single-module fstring-convert plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every simple
    string-literal ``"...{}...".format(args)`` call into the equivalent
    f-string. An empty plan means nothing matched (a no-op, not a failure).

    The read -> parse -> collect -> apply -> re-parse -> build-plan scaffold (and
    its blocker wording) is the shared
    :func:`~app.execution._transform_base.plan_single_module_column_rewrite`;
    only the ``.format``-specific :func:`_collect_rewrites` is local."""
    return plan_single_module_column_rewrite(
        project_root, module_rel,
        plan_label="fstring-convert", collect=_collect_rewrites)
