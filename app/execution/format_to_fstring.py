"""Convert a simple ``"...{}...".format(args)`` call into an f-string.

The ``.format`` sibling of :mod:`app.execution.fstring_convert` (which handles
only anonymous ``{}`` fields) and :mod:`app.execution.percent_to_fstring` (which
handles ``%``-formatting): a STRING-LITERAL ``.format(...)`` call whose template
uses only *bare* replacement fields — auto-numbered ``{}``, explicit positional
``{0}`` / ``{1}``, or named ``{name}`` — each filled by a simple expression, is
exactly an f-string::

    "{}".format(x)            -> f"{x}"
    "{0}-{1}".format(a, b)    -> f"{a}-{b}"
    "{n}".format(n=v)         -> f"{v}"
    "x={}".format(self.name)  -> f"x={self.name}"

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the call's ``func`` is an ``ast.Attribute`` ``attr == "format"`` whose
    ``.value`` is an ``ast.Constant`` string literal (the format template);
  - NO ``*args`` / ``**kwargs`` unpacking anywhere in the call;
  - the template uses ONLY *bare* replacement fields: empty ``{}``, a bare
    integer index ``{0}``, or a bare identifier ``{name}``. Any format spec
    (``{:0.2f}``), conversion (``{!r}``), attribute/index access inside the
    field (``{a.b}`` / ``{a[0]}``), nested field, or escaped brace ``{{`` / ``}}``
    skips the occurrence entirely;
  - Python forbids mixing auto-numbering ``{}`` with manual numbering ``{0}`` in
    one template, so a template that mixes the two is skipped (it would raise at
    runtime anyway);
  - every empty/index field resolves to a positional arg and every named field
    resolves to a ``name=`` keyword arg; every referenced positional index and
    keyword name must exist, the positional args must be EXACTLY consumed (no
    extra unreferenced positional arg), and no unreferenced keyword may be left
    over — a count/name mismatch skips the occurrence;
  - every mapped arg is a SIMPLE expression — an ``ast.Name``, attribute chain
    of names, ``ast.Subscript``, ``ast.Constant``, or ``ast.Call`` — so a bare
    ``{<arg>}`` needs no precedence parens. A ``Call`` arg that is referenced by
    more than one field is rejected: an f-string would evaluate it once per
    field, which can change behaviour (``.format`` evaluates each arg once);
  - the literal's recovered source must be a plain ``"`` / ``'`` string with no
    prefix (raw / bytes / already-f are skipped) and contain no backslash; the
    literal and the whole call must each live on a SINGLE line so the column-span
    splice is trivially correct. The f-string reuses the template's quote, and
    any arg whose source contains that quote is rejected so quoting can't break.

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

from app.execution._transform_base import apply_column_rewrites, is_fixture_path
from app.execution._transform_base import literal_inner as _literal_inner
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_format_to_fstring"]


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


class _Field:
    """One parsed replacement field. ``kind`` is ``"auto"`` (empty ``{}``),
    ``"index"`` (``{0}``, ``key`` is the int), or ``"name"`` (``{x}``, ``key``
    is the identifier str)."""

    __slots__ = ("kind", "key")

    def __init__(self, kind: str, key: int | str | None) -> None:
        self.kind = kind
        self.key = key


def _is_simple_arg(node: ast.AST) -> bool:
    """A bare ``{name}`` can fill a field only for a SIMPLE expression whose
    source needs no precedence parens: a Name, an attribute chain, a Subscript,
    a Constant, or a Call. Anything else (binops, ternaries, ...) is rejected."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_simple_arg(node.value)
    if isinstance(node, ast.Subscript):
        return _is_simple_arg(node.value)
    if isinstance(node, ast.Call):
        return True
    return False


def _classify_field(spec: str) -> _Field | None:
    """Classify the text BETWEEN one field's braces. Only a bare field is
    supported: empty (``""``), a non-negative integer index (``"0"``), or a
    plain identifier (``"name"``). A format spec (``:``), conversion (``!``),
    attribute access (``.``), or index access (``[``) returns None."""
    if any(c in spec for c in (":", "!", ".", "[", "]", "{", "}")):
        return None
    if spec == "":
        return _Field("auto", None)
    if spec.isdigit():
        return _Field("index", int(spec))
    if spec.isidentifier():
        return _Field("name", spec)
    return None


def _parse_template(inner: str) -> tuple[list[str], list[_Field]] | None:
    """Split the template's INNER text (literal content, quotes stripped) into
    literal segments and parsed replacement fields.

    Returns ``(segments, fields)`` where ``segments`` has ``len(fields) + 1``
    entries (the literal text around the fields). Returns None when the template
    contains anything outside the supported shape — an escaped brace ``{{`` /
    ``}}``, a lone ``}``, a format spec or conversion (anything but a bare index
    or identifier inside the braces), attribute/index access inside a field, or
    an unterminated field — so the occurrence is skipped."""
    segments: list[str] = []
    fields: list[_Field] = []
    buf: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "{":
            # Escaped brace — out of scope (we don't re-escape templates).
            if i + 1 < n and inner[i + 1] == "{":
                return None
            close = inner.find("}", i + 1)
            if close == -1:
                return None  # unterminated field
            spec = inner[i + 1:close]
            field = _classify_field(spec)
            if field is None:
                return None
            segments.append("".join(buf))
            buf = []
            fields.append(field)
            i = close + 1
            continue
        if ch == "}":
            # A lone or escaped '}}' — anything else brace-y disqualifies.
            return None
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments, fields


def _keywords_by_name(kw_args: list[ast.keyword]) -> dict[str, ast.expr] | None:
    """Map every keyword to its value, or None on ``**kwargs`` unpacking or a
    duplicate keyword (the latter shouldn't parse, but is guarded anyway)."""
    kw_by_name: dict[str, ast.expr] = {}
    for kw in kw_args:
        if kw.arg is None:  # **kwargs unpacking
            return None
        if kw.arg in kw_by_name:
            return None  # duplicate keyword (shouldn't parse, guard anyway)
        kw_by_name[kw.arg] = kw.value
    return kw_by_name


def _mixes_numbering(fields: list[_Field]) -> bool:
    """True iff the fields mix auto-numbered ``{}`` with explicit-index ``{0}``
    numbering — which ``str.format`` forbids."""
    has_auto = any(f.kind == "auto" for f in fields)
    has_index = any(f.kind == "index" for f in fields)
    return has_auto and has_index


def _resolve_fields(
    fields: list[_Field],
    pos_args: list[ast.expr],
    kw_by_name: dict[str, ast.expr],
) -> tuple[list[ast.expr], dict[int, int], dict[str, int]] | None:
    """Resolve each field to its arg in order, returning
    ``(resolved, pos_refs, name_refs)`` (the reference-count maps) or None.

    Empty fields auto-number 0, 1, 2, ...; index fields use their int key; named
    fields draw from ``kw_by_name``. Mixing auto-numbered with explicit-index
    fields is rejected (``str.format`` forbids it); a missing index or keyword
    skips the occurrence."""
    if _mixes_numbering(fields):
        return None  # str.format forbids mixing automatic and manual numbering

    pos_refs: dict[int, int] = {}  # positional index -> reference count
    name_refs: dict[str, int] = {}
    resolved: list[ast.expr] = []
    auto_counter = 0
    for field in fields:
        if field.kind == "name":
            name = field.key  # type: ignore[assignment]
            if name not in kw_by_name:
                return None
            name_refs[name] = name_refs.get(name, 0) + 1
            resolved.append(kw_by_name[name])
            continue
        if field.kind == "auto":
            idx = auto_counter
            auto_counter += 1
        else:  # index
            idx = field.key  # type: ignore[assignment]
        if idx < 0 or idx >= len(pos_args):
            return None
        pos_refs[idx] = pos_refs.get(idx, 0) + 1
        resolved.append(pos_args[idx])
    return resolved, pos_refs, name_refs


def _refs_consume_all(
    pos_refs: dict[int, int],
    name_refs: dict[str, int],
    pos_args: list[ast.expr],
    kw_by_name: dict[str, ast.expr],
) -> bool:
    """True iff every positional arg and every keyword is referenced exactly
    once across the fields — a count/name mismatch leaves leftovers."""
    if len(pos_refs) != len(pos_args):
        return False
    if len(name_refs) != len(kw_by_name):
        return False
    return True


def _no_recalled_call(
    pos_refs: dict[int, int],
    name_refs: dict[str, int],
    pos_args: list[ast.expr],
    kw_by_name: dict[str, ast.expr],
) -> bool:
    """True iff no ``Call`` arg is referenced by more than one field.

    An f-string evaluates each field, so a Call referenced more than once would
    run more than once (a behaviour change ``.format`` doesn't make)."""
    for idx, count in pos_refs.items():
        if count > 1 and isinstance(pos_args[idx], ast.Call):
            return False
    for name, count in name_refs.items():
        if count > 1 and isinstance(kw_by_name[name], ast.Call):
            return False
    return True


def _arg_sources(resolved: list[ast.expr], source: str) -> list[str] | None:
    """Recover each resolved arg's source in order, or None to skip.

    A brace in the arg source would grow an unexpected f-string field; a
    backslash is illegal inside an f-string replacement field (< 3.12)."""
    arg_srcs: list[str] = []
    for arg in resolved:
        seg = ast.get_source_segment(source, arg)
        if seg is None:
            return None
        if "{" in seg or "}" in seg or "\\" in seg:
            return None
        arg_srcs.append(seg)
    return arg_srcs


def _map_args(
    fields: list[_Field],
    pos_args: list[ast.expr],
    kw_args: list[ast.keyword],
    source: str,
) -> list[str] | None:
    """Resolve each field to its argument's recovered source text, in field
    order, or None to skip.

    Empty/index fields draw from ``pos_args`` (empty auto-numbers 0, 1, 2, ...);
    named fields draw from ``kw_args`` by keyword name. Mixing auto-numbered with
    explicit-index fields is rejected (``str.format`` forbids it). Every
    referenced positional index and keyword name must exist; every positional arg
    must be referenced (no leftover) and every keyword must be referenced. Each
    mapped arg must be a simple expression with a recoverable, brace/backslash/
    quote-free source. A ``Call`` arg referenced by more than one field is
    rejected (an f-string would re-evaluate it)."""
    kw_by_name = _keywords_by_name(kw_args)
    if kw_by_name is None:
        return None

    resolution = _resolve_fields(fields, pos_args, kw_by_name)
    if resolution is None:
        return None
    resolved, pos_refs, name_refs = resolution

    if not _refs_consume_all(pos_refs, name_refs, pos_args, kw_by_name):
        return None
    if not _no_recalled_call(pos_refs, name_refs, pos_args, kw_by_name):
        return None
    if not all(_is_simple_arg(a) for a in resolved):
        return None

    return _arg_sources(resolved, source)


def _has_unpacking(node: ast.Call) -> bool:
    """True iff the call carries ``*args`` or ``**kwargs`` unpacking anywhere —
    which makes the positional/keyword mapping non-trivial, so we skip it."""
    if any(isinstance(a, ast.Starred) for a in node.args):
        return True
    return any(kw.arg is None for kw in node.keywords)


def _format_template(node: ast.Call) -> ast.Constant | None:
    """The string-literal template of a single-line ``"...".format(...)`` call
    with no ``*args`` / ``**kwargs`` unpacking, else None.

    Requires ``node.func`` to be an ``Attribute`` ``attr == "format"`` over an
    ``ast.Constant`` ``str``, and both the literal and the whole call to live on
    a single line (so the column-span splice is trivially correct)."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "format":
        return None
    template = func.value
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None

    if _has_unpacking(node):
        return None

    # Single-line literal and single-line call keep the column splice trivial.
    if template.lineno != template.end_lineno:
        return None
    if node.lineno != node.end_lineno:
        return None
    return template


def _template_parts(
    template: ast.Constant, source: str,
) -> tuple[str, list[str], list[_Field]] | None:
    """Recover the template literal and parse it into ``(quote, segments,
    fields)``, or None to skip.

    Skips an unrecoverable literal source, a prefixed/triple-quoted/backslashed
    literal, an out-of-shape template, and an empty field set (nothing to
    interpolate — leave it alone)."""
    literal_src = ast.get_source_segment(source, template)
    if literal_src is None:
        return None
    parsed = _literal_inner(literal_src)
    if parsed is None:
        return None
    quote, inner = parsed

    parsed_template = _parse_template(inner)
    if parsed_template is None:
        return None
    segments, fields = parsed_template
    if not fields:
        return None  # nothing to interpolate — leave it alone
    return quote, segments, fields


def _build_fstring(quote: str, segments: list[str], arg_srcs: list[str]) -> str:
    """Splice the literal segments and recovered arg sources into f-string text,
    reusing the template's ``quote``."""
    parts: list[str] = [segments[0]]
    for arg_src, seg in zip(arg_srcs, segments[1:]):
        parts.append("{" + arg_src + "}")
        parts.append(seg)
    return "f" + quote + "".join(parts) + quote


def _reparses_as_fstring(text: str, field_count: int) -> bool:
    """True iff ``text`` re-parses to exactly a ``JoinedStr`` with ``field_count``
    ``FormattedValue`` fields — the crucial safety check before any rewrite."""
    try:
        expr = ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError, MemoryError):
        return False
    if not isinstance(expr, ast.JoinedStr):
        return False
    formatted = [v for v in expr.values if isinstance(v, ast.FormattedValue)]
    return len(formatted) == field_count


def _try_call(node: ast.Call, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``.format(...)`` call, return
    its rewrite, else None."""
    template = _format_template(node)
    if template is None:
        return None

    parts = _template_parts(template, source)
    if parts is None:
        return None
    quote, segments, fields = parts

    arg_srcs = _map_args(fields, node.args, node.keywords, source)
    if arg_srcs is None:
        return None

    text = _build_fstring(quote, segments, arg_srcs)

    # CRUCIAL safety: the built text must parse to exactly a JoinedStr with the
    # expected number of FormattedValue fields, or we skip the occurrence.
    if not _reparses_as_fstring(text, len(fields)):
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


def plan_format_to_fstring(project_root: str | Path,
                           module_rel: str) -> RenamePlan:
    """Build the single-module format-to-fstring plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every simple
    string-literal ``"...{}...".format(args)`` call (auto-numbered, explicit
    index, or named fields) into the equivalent f-string. An empty plan means
    nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="format-to-fstring")
    if is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="conversion")
