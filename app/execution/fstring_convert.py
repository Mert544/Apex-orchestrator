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

from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fstring_convert"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its repetition is often deliberate
    boilerplate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _is_simple_arg(node: ast.AST) -> bool:
    """A bare ``{name}`` can fill ``{}`` only for a SIMPLE expression: a Name,
    an attribute chain of Names, or a Constant. Anything else (calls,
    subscripts, binops, ...) is rejected so precedence never bites."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_simple_arg(node.value)
    return False


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


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: (r.lineno, r.col), reverse=True):
        line = lines[rw.lineno - 1]
        lines[rw.lineno - 1] = line[:rw.col] + rw.text + line[rw.end_col:]
    return "".join(lines)


def plan_fstring_convert(project_root: str | Path,
                         module_rel: str) -> RenamePlan:
    """Build the single-module fstring-convert plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every simple
    string-literal ``"...{}...".format(args)`` call into the equivalent
    f-string. An empty plan means nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="fstring-convert")
    if _is_fixture_path(module_rel):
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

    new_source = _apply(source, rewrites)
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
