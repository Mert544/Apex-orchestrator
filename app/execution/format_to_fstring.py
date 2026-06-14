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


def _literal_inner(literal_src: str) -> tuple[str, str] | None:
    """From a recovered string-literal source, return ``(quote, inner)`` for a
    plain unprefixed ``"`` / ``'`` string, else None.

    Rejects any prefix (raw / bytes / f / u), triple-quotes, and any string
    whose body contains a backslash — keeping the inner text safe to embed
    verbatim inside an f-string with the same quote char."""
    if not literal_src:
        return None
    quote = literal_src[0]
    if quote not in ("'", '"'):
        return None  # has a prefix (r/b/f/u) or isn't a plain string literal
    if literal_src[-1] != quote:
        return None
    # Triple-quoted strings are multi-line in spirit — out of scope.
    if literal_src[:3] in ("'''", '"""'):
        return None
    if len(literal_src) < 2:
        return None
    inner = literal_src[1:-1]
    if "\\" in inner:
        return None
    if quote in inner:
        return None
    return quote, inner


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
    kw_by_name: dict[str, ast.expr] = {}
    for kw in kw_args:
        if kw.arg is None:  # **kwargs unpacking
            return None
        if kw.arg in kw_by_name:
            return None  # duplicate keyword (shouldn't parse, guard anyway)
        kw_by_name[kw.arg] = kw.value

    has_auto = any(f.kind == "auto" for f in fields)
    has_index = any(f.kind == "index" for f in fields)
    if has_auto and has_index:
        return None  # str.format forbids mixing automatic and manual numbering

    pos_refs: dict[int, int] = {}  # positional index -> reference count
    name_refs: dict[str, int] = {}
    resolved: list[ast.expr] = []
    auto_counter = 0
    for field in fields:
        if field.kind == "auto":
            idx = auto_counter
            auto_counter += 1
        elif field.kind == "index":
            idx = field.key  # type: ignore[assignment]
        else:  # name
            name = field.key  # type: ignore[assignment]
            if name not in kw_by_name:
                return None
            name_refs[name] = name_refs.get(name, 0) + 1
            resolved.append(kw_by_name[name])
            continue
        if idx < 0 or idx >= len(pos_args):
            return None
        pos_refs[idx] = pos_refs.get(idx, 0) + 1
        resolved.append(pos_args[idx])

    # Every positional arg and every keyword must be consumed — a count/name
    # mismatch skips the occurrence.
    if len(pos_refs) != len(pos_args):
        return None
    if len(name_refs) != len(kw_by_name):
        return None

    # Reject re-evaluating a Call: an f-string evaluates each field, so a Call
    # referenced more than once would run more than once (behaviour change).
    for idx, count in pos_refs.items():
        if count > 1 and isinstance(pos_args[idx], ast.Call):
            return None
    for name, count in name_refs.items():
        if count > 1 and isinstance(kw_by_name[name], ast.Call):
            return None

    if not all(_is_simple_arg(a) for a in resolved):
        return None

    arg_srcs: list[str] = []
    for arg in resolved:
        seg = ast.get_source_segment(source, arg)
        if seg is None:
            return None
        # A brace in the arg source would grow an unexpected f-string field; a
        # backslash is illegal inside an f-string replacement field (< 3.12).
        if "{" in seg or "}" in seg or "\\" in seg:
            return None
        arg_srcs.append(seg)
    return arg_srcs


def _try_call(node: ast.Call, source: str) -> _Rewrite | None:
    """If ``node`` is a convertible string-literal ``.format(...)`` call, return
    its rewrite, else None."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "format":
        return None
    template = func.value
    if not isinstance(template, ast.Constant) or not isinstance(template.value, str):
        return None

    # No *args / **kwargs unpacking anywhere in the call.
    if any(isinstance(a, ast.Starred) for a in node.args):
        return None
    if any(kw.arg is None for kw in node.keywords):
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

    parsed_template = _parse_template(inner)
    if parsed_template is None:
        return None
    segments, fields = parsed_template
    if not fields:
        return None  # nothing to interpolate — leave it alone

    arg_srcs = _map_args(fields, node.args, node.keywords, source)
    if arg_srcs is None:
        return None

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
    if len(formatted) != len(fields):
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

    root = Path(project_root)
    path = root / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return plan

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{module_rel} doesn't parse: {e}")
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: conversion would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
