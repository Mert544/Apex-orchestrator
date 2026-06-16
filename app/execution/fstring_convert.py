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
from app.execution._transform_base import collect_arg_sources as _collect_arg_sources
from app.execution._transform_base import is_simple_arg as _is_simple_arg
from app.execution._transform_base import plan_single_module_column_rewrite
from app.execution._transform_base import recover_fstring_template as _recover_fstring_template
from app.execution._transform_base import text_is_valid as _text_is_valid
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fstring_convert"]

# Shared with percent-to-fstring via ``app.execution._transform_base``:
#   _Rewrite                 — the located single-line column-splice value (``ColumnRewrite``)
#   _is_simple_arg           — the "bare {name} is safe" predicate (``is_simple_arg``)
#   _collect_arg_sources     — the recover-every-arg-source loop (``collect_arg_sources``)
#   _recover_fstring_template — the literal-recover/count tail (``recover_fstring_template``)
#   _text_is_valid           — the JoinedStr safety re-parse (``text_is_valid``)
# The convert-specific ``{}``-placeholder parsing (``_split_template``), call-shape
# matching and ``{arg}`` splicing (``_build_text``) below stay private — they are
# NOT the percent ``%s`` logic and must not be merged.


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


def _format_template(node: ast.Call) -> ast.Constant | None:
    """The string-literal template of a ``"...".format(...)`` call (``.format``
    attribute on a ``str`` ``ast.Constant``), else None."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "format":
        return None
    template = func.value
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None
    return template


def _args_ok(node: ast.Call) -> bool:
    """True iff the call's args are all positional and all simple — no keywords,
    no star-args."""
    if node.keywords:
        return False
    if any(isinstance(a, ast.Starred) for a in node.args):
        return False
    return all(_is_simple_arg(a) for a in node.args)


def _single_line(template: ast.Constant, node: ast.Call) -> bool:
    """True iff the literal and the whole call each live on a single line, so the
    column splice is trivial."""
    return (template.lineno == template.end_lineno
            and node.lineno == node.end_lineno)


def _match_call(node: ast.Call) -> ast.Constant | None:
    """Return the string-literal template of a single-line, all-positional,
    all-simple ``"...".format(...)`` call, else None."""
    template = _format_template(node)
    if template is None:
        return None
    if not _args_ok(node):
        return None
    if not _single_line(template, node):
        return None
    return template


def _build_text(quote: str, segments: list[str], arg_srcs: list[str]) -> str:
    """Splice the literal segments and ``{arg}`` fields into the f-string text."""
    parts: list[str] = [segments[0]]
    for arg_src, seg in zip(arg_srcs, segments[1:]):
        parts.append("{" + arg_src + "}")
        parts.append(seg)
    return "f" + quote + "".join(parts) + quote


def _recover_template(
    template: ast.Constant, source: str, arg_count: int,
) -> tuple[str, list[str], int] | None:
    """Recover the literal, split it on ``{}`` placeholders, and check the count.

    Thin ``{}``-specific binding of the shared
    :func:`~app.execution._transform_base.recover_fstring_template` — it supplies
    the ``{}`` placeholder :func:`_split_template`; the recover/count tail (the
    byte-identical body once shared with percent-to-fstring) lives there once."""
    return _recover_fstring_template(
        template, source, arg_count, split=_split_template)


def _try_call(node: ast.Call, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``.format(...)`` call, return
    its rewrite, else None."""
    template = _match_call(node)
    if template is None:
        return None

    recovered = _recover_template(template, source, len(node.args))
    if recovered is None:
        return None
    quote, segments, count = recovered

    arg_srcs = _collect_arg_sources(node.args, source)
    if arg_srcs is None:
        return None

    text = _build_text(quote, segments, arg_srcs)
    if not _text_is_valid(text, count):
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
