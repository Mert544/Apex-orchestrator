"""Shared primitives for the single-module source transforms.

The deterministic, AST-located rewrites under ``app/execution/`` (bool-return,
merge-isinstance, fix-not-in-is, chain-comparison, set-literal, ternary-bool,
collapse-startswith, list/dict comprehension, redundant-else) each used to carry
their own private copy of the same four helpers. That repetition is exactly what
``apex grade`` flagged as duplication, so the identical primitives live here once
and every transform imports them.

This is a **library** (leading underscore in the filename) — it is never an
objective and exposes no ``plan_*`` entry point. Each primitive matches the EXACT
semantics the transforms relied on, so the extraction is behaviour-preserving:

- :func:`is_fixture_path` — the example/test/fixture exclusion every transform
  copied verbatim.
- :func:`apply_column_rewrites` — the bottom-up, right-to-left single-line column
  splice used by the column-span transforms (merge-isinstance et al.).
- :func:`apply_line_rewrites` — the bottom-up inclusive line-span replacement
  used by the line-span transforms (bool-return, comprehension, dict).
- :func:`iter_statement_blocks` — the statement-list walker used by the
  block-scanning transforms (bool-return, comprehension, redundant-else).
- :func:`is_simple_arg` / :func:`literal_inner` — the string-literal / simple-arg
  predicates the f-string transforms (fstring-convert, percent-to-fstring) copied
  verbatim.
- :class:`ColumnRewrite` / :func:`plan_single_module_column_rewrite` — the
  read -> parse -> collect -> apply -> re-parse -> build-plan scaffold the
  single-module column-splice f-string transforms shared identically.

Deterministic and stdlib-only — no time, no randomness.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

__all__ = [
    "is_fixture_path",
    "apply_column_rewrites",
    "apply_line_rewrites",
    "iter_statement_blocks",
    "is_simple_arg",
    "literal_inner",
    "ColumnRewrite",
    "plan_single_module_column_rewrite",
]


def is_fixture_path(path: str) -> bool:
    """True for example/test/fixture code, which the transforms exclude as a
    subject (its repetition is often deliberate boilerplate).

    A path is a fixture when, lower-cased with ``\\`` normalised to ``/``, it
    starts with an ``examples/`` / ``example/`` / ``tests/`` / ``test/`` /
    ``fixtures/`` segment, contains ``/examples/``, ``/tests/`` or ``/fixtures/``
    anywhere, or its basename starts with ``test_``. This is the identical helper
    that was copied across the transform modules — a local copy because importing
    it from health_score created a health_score <-> dedup import cycle."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def apply_column_rewrites(
    source: str,
    rewrites: Iterable[tuple[int, int, int, str]],
) -> str:
    """Splice single-line column-span rewrites into ``source``.

    Each rewrite is ``(lineno, col_offset, end_col_offset, new_text)`` with a
    1-based ``lineno`` and 0-based column offsets (AST conventions): on that line,
    ``[col_offset, end_col_offset)`` is replaced by ``new_text``. Rewrites are
    applied bottom-up and right-to-left — sorted by ``(lineno, col_offset)``
    descending — so earlier offsets stay valid when several share a line or one
    is nested in another. This is the loop the column-span transforms duplicated."""
    lines = source.splitlines(keepends=True)
    for lineno, col, end_col, text in sorted(
            rewrites, key=lambda r: (r[0], r[1]), reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:col] + text + line[end_col:]
    return "".join(lines)


def apply_line_rewrites(
    source: str,
    rewrites: Iterable[tuple[int, int, list[str]]],
) -> str:
    """Replace inclusive 1-based line spans in ``source``.

    Each rewrite is ``(lo_lineno, hi_lineno, new_lines)``: lines ``[lo, hi]``
    (1-based, inclusive) are replaced by the ``new_lines`` list. Rewrites are
    applied bottom-up — sorted by ``lo_lineno`` descending — so earlier line
    numbers stay valid. ``new_lines`` carries its own trailing newlines (or not),
    so the caller preserves the original last line's trailing-newline behaviour by
    matching it; this helper splices verbatim. This is the loop the line-span
    transforms (bool-return, comprehension, dict-comprehension) duplicated."""
    lines = source.splitlines(keepends=True)
    for lo, hi, new_lines in sorted(rewrites, key=lambda r: r[0], reverse=True):
        lines[lo - 1:hi] = new_lines
    return "".join(lines)


def iter_statement_blocks(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    """Yield every list-of-statements in ``tree`` (module body, function/class
    bodies, if/for/while/with/try blocks, and except-handler bodies).

    Order doesn't matter — the transforms sort their rewrites before applying.
    This is the walker the block-scanning transforms (bool-return, comprehension,
    dict-comprehension, redundant-else) duplicated."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and all(
                    isinstance(s, ast.stmt) for s in block):
                yield block
        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                if isinstance(handler, ast.ExceptHandler) and handler.body:
                    yield handler.body


# Operand node types that NEVER need wrapping parens when their source is spliced
# verbatim into a binding-operator context (``==`` ``!=`` ``in`` ``is`` ``<`` …):
# each is atomic or self-bracketing, so surrounding precedence can't re-associate
# it. Anything else — a ternary (``a if c else d``), ``or``/``and``, ``lambda``, a
# walrus, a nested comparison — binds looser than the operator it is spliced
# beside, so it MUST be parenthesised or the rewrite silently changes meaning
# (``not (a == (b if c else d))`` -> ``a != b if c else d`` == ``(a != b) if c
# else d``). ``ast.get_source_segment`` strips an operand's own wrapping parens,
# so the splice site can't rely on them surviving.
_ATOMIC_OPERANDS = (ast.Name, ast.Constant, ast.Attribute, ast.Subscript, ast.Call)


def operand_needs_parens(node: ast.expr) -> bool:
    """True if ``node`` must be wrapped in parens to keep its meaning when its
    source is spliced into a binding-operator expression."""
    return not isinstance(node, _ATOMIC_OPERANDS)


def splice_operand(source: str, node: ast.expr) -> str | None:
    """The source text of ``node``, parenthesised iff precedence could otherwise
    change its meaning when spliced beside a binding operator. ``None`` if the
    source can't be recovered (the caller skips the occurrence)."""
    src = ast.get_source_segment(source, node)
    if src is None:
        return None
    return f"({src})" if operand_needs_parens(node) else src


def is_simple_arg(node: ast.AST) -> bool:
    """A bare ``{name}`` interpolation can fill a placeholder only for a SIMPLE
    expression: a Name, an attribute chain of Names, or a Constant. Anything else
    (calls, subscripts, binops, ...) is rejected so precedence never bites.

    This is the identical predicate the f-string transforms (fstring-convert and
    percent-to-fstring) each copied verbatim."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return is_simple_arg(node.value)
    return False


def literal_inner(literal_src: str) -> tuple[str, str] | None:
    """From a recovered string-literal source, return ``(quote, inner)`` for a
    plain unprefixed ``"`` / ``'`` string, else None.

    Rejects any prefix (raw / bytes / f / u), triple-quotes, and any string whose
    body contains a backslash — keeping the inner text safe to embed verbatim
    inside an f-string with the same quote char. This is the identical helper the
    f-string transforms (fstring-convert, percent-to-fstring) copied verbatim."""
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


class ColumnRewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``.

    This is the identical ``_Rewrite`` value the single-line column-splice
    f-string transforms each carried privately."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def plan_single_module_column_rewrite(
    project_root: str | Path,
    module_rel: str,
    *,
    plan_label: str,
    collect: Callable[[ast.Module, str], list[ColumnRewrite]],
) -> RenamePlan:
    """The read -> parse -> collect -> apply -> re-parse -> build-plan scaffold the
    single-module column-splice f-string transforms shared identically.

    ``plan_label`` is the :class:`RenamePlan` ``new`` tag (e.g. ``"fstring-convert"``).
    ``collect(tree, source)`` returns every :class:`ColumnRewrite` to apply; the
    rewrites are spliced bottom-up and right-to-left (via
    :func:`apply_column_rewrites`) so earlier column offsets stay valid. A fixture
    subject or an empty rewrite set yields an empty plan (a no-op, not a failure);
    an unreadable file, a parse failure, or a result that won't re-parse records a
    blocker. Behaviour-identical to the per-module ``plan_*`` bodies it replaces."""
    plan = RenamePlan(old=module_rel, new=plan_label)
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

    rewrites = collect(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = apply_column_rewrites(
        source,
        ((r.lineno, r.col, r.end_col, r.text) for r in rewrites),
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
