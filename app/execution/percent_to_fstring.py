"""Convert a simple ``"...%..." % args`` expression into an f-string.

The ``%``-format sibling of :mod:`app.execution.fstring_convert` (which handles
``.format``): a STRING-LITERAL percent-format whose template uses only the
PROVEN-equivalent conversions below, one per argument, each filled by a simple
expression, is exactly an f-string::

    "%s = %s" % (a, b)        -> f"{a} = {b}"
    "x=%s" % v                -> f"x={v}"
    "%s" % self.name          -> f"{self.name}"
    "100%% of %s" % v         -> f"100% of {v}"     (``%%`` is a literal percent)
    "%d" % n                  -> f"{n:d}"
    "%.2f" % x                -> f"{x:.2f}"
    "%05d" % n                -> f"{n:05d}"
    "%-10s" % s               -> f"{s!s:<10}"
    "%x" % n                  -> f"{n:x}"

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.BinOp`` with ``op == ast.Mod`` whose ``left`` is an
    ``ast.Constant`` string literal (the format template);
  - the template uses ONLY conversions Apex can map BYTE-FOR-BYTE (see
    :func:`_parse_conversion`) and literal ``%%``. Anything outside that proven
    set — a mapping key ``%(name)s``, dynamic width ``*``, ``%c``/``%a``, an
    unsupported/ambiguous flag combo, or a lone trailing ``%`` — skips the
    occurrence rather than risk a semantics change (under-claim, never mis-claim);
  - the right side supplies the args — an ``ast.Tuple``'s elements in order, or
    else the single expression as the sole arg;
  - the number of placeholders EQUALS the number of args;
  - every arg is a SIMPLE expression — an ``ast.Name``, an attribute chain of
    names, or an ``ast.Constant`` — so a bare ``{<arg>...}`` field needs no
    precedence parens;
  - the literal's recovered source must be a plain ``"`` / ``'`` string with no
    prefix (raw / bytes / already-f are skipped) and contain no backslash; the
    literal and the whole BinOp must each live on a SINGLE line so the
    column-span splice is trivially correct.

Built text is independently re-parsed: it must be exactly an ``ast.JoinedStr``
with the expected number of ``FormattedValue`` fields, or the occurrence is
skipped. Edits are column-span replacements located by the AST (no unparse
round-trip), so comments and formatting elsewhere survive untouched.

Conservative by design — any source segment that can't be recovered, and any
conversion whose f-string equivalence is not provable byte-for-byte, skips that
occurrence; the rewritten module must re-parse or the whole plan blocks.
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
from app.execution._transform_base import scan_template as _scan_template
from app.execution._transform_base import TemplateScanStep as _ScanStep
from app.execution._transform_base import text_is_valid as _text_is_valid
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_percent_to_fstring"]

# Shared with fstring-convert via ``app.execution._transform_base``:
#   _Rewrite                 — the located single-line column-splice value (``ColumnRewrite``)
#   _is_simple_arg           — the "bare {name} is safe" predicate (``is_simple_arg``)
#   _collect_arg_sources     — the recover-every-arg-source loop (``collect_arg_sources``)
#   _recover_fstring_template — the literal-recover/count tail (``recover_fstring_template``)
#   _text_is_valid           — the JoinedStr safety re-parse (``text_is_valid``)
# The percent-specific conversion parsing (``_parse_conversion`` / ``_split_template``),
# brace-escaping (``_escape`` / ``_build_text``) and BinOp matching below stay private —
# they are NOT the ``.format`` logic and must not be merged.

# Conversion chars Apex can map BYTE-FOR-BYTE to an f-string field. The mapping is
# proven by the round-trip tests in ``tests/test_percent_to_fstring.py``:
#   - ``s``/``r`` -> a ``{}`` / ``{!r}`` field (string coercion preserved);
#   - radix integers ``x``/``X``/``o`` -> a numeric ``{:...}`` field; a precision
#     is NOT allowed (printf ignores it differently than ``format`` for ints).
#     DECIMAL ``d``/``i`` are deliberately NOT here: ``"%d" % 3.14`` TRUNCATES to
#     ``"3"``, but ``f"{3.14:d}"`` RAISES ``ValueError`` — the success paths
#     diverge on a float arg (which the transform cannot rule out statically), so
#     ``d``/``i`` are refused rather than risk turning a working truncation into a
#     crash. (Radix ``x``/``X``/``o`` reject floats in BOTH forms, so they stay.)
#   - floats ``f``/``F``/``e``/``E``/``g``/``G`` -> a numeric ``{:...}`` field
#     (a precision IS allowed). ``%c`` / ``%a`` and mapping keys are refused.
_STRING_CONV = {"s", "r"}
_INT_CONV = {"x": "x", "X": "X", "o": "o"}
_FLOAT_CONV = {"f", "F", "e", "E", "g", "G"}
# printf flag char -> f-string sign/alt/zero token (alignment is handled apart).
_FLAGS = set("-+ 0#")


class _Field:
    """One parsed ``%`` conversion ready to splice as an f-string field.

    ``conversion`` is the ``!s`` / ``!r`` coercion (or ``""``); ``spec`` is the
    text after the ``:`` (or ``""`` for a bare ``{}``). The field for an arg
    source ``src`` is ``{`` + ``src`` + ``conversion`` + (``:`` + ``spec`` when
    ``spec``) + ``}``."""

    __slots__ = ("conversion", "spec")

    def __init__(self, conversion: str, spec: str) -> None:
        self.conversion = conversion
        self.spec = spec


def _build_numeric_spec(flags: str, width: str, prec: str, conv: str) -> str:
    """The f-string format spec for a numeric conversion (int or float).

    Emits ``[align][sign][#][0][width][.prec]conv`` in the canonical f-spec
    order. The printf flag normalisations that keep it byte-equivalent: ``-``
    becomes the ``<`` alignment and, when present, the ``0`` flag is dropped
    (printf ignores ``0`` with ``-``); ``+`` wins over a space flag (printf
    precedence). ``prec`` carries its own leading dot or is empty (ints never
    pass a precision — :func:`_classify` refuses that)."""
    minus = "-" in flags
    align = "<" if minus else ""
    sign = "+" if "+" in flags else (" " if " " in flags else "")
    alt = "#" if "#" in flags else ""
    zero = "" if minus else ("0" if "0" in flags else "")
    return f"{align}{sign}{alt}{zero}{width}{prec}{conv}"


def _parse_conversion(inner: str, i: int) -> tuple[_Field, int] | None:
    """Parse one ``%`` conversion starting at ``inner[i] == '%'``.

    Returns ``(field, next_index)`` for a PROVEN-equivalent conversion, or None
    to refuse (skip the whole occurrence). Grammar accepted (no mapping key, no
    ``*`` dynamic width):

        % [flags] [width] [.precision] conv

    where ``flags`` is a run of ``- + space 0 #``, ``width`` is digits, and
    ``conv`` is one of the supported chars. A precision is allowed only for
    float conversions; on int/string conversions it is refused."""
    n = len(inner)
    j = i + 1
    flags = ""
    while j < n and inner[j] in _FLAGS:
        flags += inner[j]
        j += 1
    width = ""
    while j < n and inner[j].isdigit():
        width += inner[j]
        j += 1
    prec = ""
    if j < n and inner[j] == ".":
        prec = "."
        j += 1
        while j < n and inner[j].isdigit():
            prec += inner[j]
            j += 1
    if j >= n:
        return None  # trailing partial conversion
    conv = inner[j]
    field = _classify(conv, flags, width, prec)
    if field is None:
        return None
    return field, j + 1


def _classify(conv: str, flags: str, width: str, prec: str) -> _Field | None:
    """Build the :class:`_Field` for ``conv`` with parsed ``flags``/``width``/
    ``prec``, or None when the combination isn't a proven-equivalent map."""
    if conv in _STRING_CONV:
        if prec:
            return None  # string precision (truncation) — out of scope, refuse
        if any(f in flags for f in "+ 0#"):
            return None  # sign/zero/alt are meaningless for %s — refuse
        if not width:
            # No width => no alignment to apply (a bare ``-`` is a no-op in
            # printf). Emit the historical {}/{!r} field with no spec.
            return _Field("" if conv == "s" else "!r", "")
        coercion = "!s" if conv == "s" else "!r"
        align = "<" if "-" in flags else ">"
        return _Field(coercion, f"{align}{width}")
    if conv in _INT_CONV:
        if prec:
            return None  # int precision diverges from format() — refuse
        return _Field("", _build_numeric_spec(flags, width, "", _INT_CONV[conv]))
    if conv in _FLOAT_CONV:
        return _Field("", _build_numeric_spec(flags, width, prec, conv))
    return None  # %c, %a, %%-handled-elsewhere, or any unknown conversion


def _split_template(inner: str) -> tuple[list[str], list[_Field]] | None:
    """Split the template's INNER text (literal content, quotes stripped) into
    literal segments and the parsed conversion :class:`_Field` for each
    placeholder.

    ``%%`` collapses to a single literal ``%`` inside a segment and is NOT a
    placeholder. Returns ``(segments, fields)`` with ``len(segments) ==
    len(fields) + 1``. Returns None when any ``%`` is not a ``%%`` and not a
    PROVEN-equivalent conversion (see :func:`_parse_conversion`), or a lone
    trailing ``%`` — so the occurrence is skipped."""
    def _step(s: str, i: int) -> _ScanStep | None:
        ch = s[i]
        if ch == "%":
            if i + 1 >= len(s):
                return None  # trailing lone '%'
            if s[i + 1] == "%":
                return _ScanStep(consumed=2, literal="%")  # literal percent
            parsed = _parse_conversion(s, i)
            if parsed is None:
                return None  # unsupported conversion / spec / flag disqualifies
            field, end = parsed
            return _ScanStep(consumed=end - i, field=field)
        return _ScanStep(consumed=1, literal=ch)

    return _scan_template(inner, _step)


def _binop_args(node: ast.BinOp) -> list[ast.expr] | None:
    """The args a ``%``-format BinOp supplies, or None to skip.

    A Tuple right side supplies its elements in order (a starred element can't be
    a positional arg we map to a placeholder); any other expression is the sole
    arg. Every arg must be a SIMPLE expression."""
    right = node.right
    if isinstance(right, ast.Tuple):
        args: list[ast.expr] = list(right.elts)
        if any(isinstance(a, ast.Starred) for a in args):
            return None
    else:
        args = [right]
    if not all(_is_simple_arg(a) for a in args):
        return None
    return args


def _match_binop(node: ast.BinOp) -> tuple[ast.Constant, list[ast.expr]] | None:
    """Return ``(template, args)`` for a single-line, simple-arg ``%``-format
    BinOp, else None.

    Gates ``op == Mod`` with a ``str`` ``ast.Constant`` left side, resolves the
    args (:func:`_binop_args`), and requires both the literal and the whole BinOp
    to live on a single line so the column splice is trivial."""
    if not isinstance(node.op, ast.Mod):
        return None
    template = node.left
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None
    args = _binop_args(node)
    if args is None:
        return None
    if template.lineno != template.end_lineno:
        return None
    if node.lineno != node.end_lineno:
        return None
    return template, args


def _escape(text: str) -> str:
    """Escape literal braces already in the template for the f-string."""
    return text.replace("{", "{{").replace("}", "}}")


def _field_text(arg_src: str, field: _Field) -> str:
    """The f-string replacement field for ``arg_src`` and its parsed ``field``:
    ``{`` ``arg`` ``[!s|!r]`` ``[:spec]`` ``}``."""
    spec = ":" + field.spec if field.spec else ""
    return "{" + arg_src + field.conversion + spec + "}"


def _build_text(
    quote: str, segments: list[str], fields: list[_Field], arg_srcs: list[str],
) -> str:
    """Splice the escaped literal segments and the converted fields into the
    f-string text."""
    parts: list[str] = [_escape(segments[0])]
    for arg_src, field, seg in zip(arg_srcs, fields, segments[1:]):
        parts.append(_field_text(arg_src, field))
        parts.append(_escape(seg))
    return "f" + quote + "".join(parts) + quote


def _recover_template(
    template: ast.Constant, source: str, arg_count: int,
) -> tuple[str, list[str], list[_Field]] | None:
    """Recover the literal, split it on placeholders, and check the count.

    Thin ``%``-specific binding of the shared
    :func:`~app.execution._transform_base.recover_fstring_template` — it supplies
    the ``%`` placeholder :func:`_split_template`, whose ``extra`` payload is the
    list of per-placeholder format :class:`_Field`\\ s (the part the numeric /
    aligned conversions need to map byte-for-byte). The recover/count tail lives
    in the shared helper once, so this is not a clone of the ``{}`` form's copy.
    Returns ``(quote, segments, fields)`` or None when nothing interpolates."""
    return _recover_fstring_template(
        template, source, arg_count, split=_split_template)


def _try_binop(node: ast.BinOp, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``%``-format BinOp, return
    its rewrite, else None."""
    matched = _match_binop(node)
    if matched is None:
        return None
    template, args = matched

    recovered = _recover_template(template, source, len(args))
    if recovered is None:
        return None
    quote, segments, fields = recovered

    arg_srcs = _collect_arg_sources(args, source)
    if arg_srcs is None:
        return None

    text = _build_text(quote, segments, fields, arg_srcs)
    if not _text_is_valid(text, len(fields)):
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
