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
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
    "plan_single_module_rewrite",
    "parse_trees",
    "resolve_sole_definition",
    "read_module_source",
    "parse_module_source",
    "record_module_rewrite",
    "finalize_module_rewrite",
    "arg_source",
    "collect_arg_sources",
    "recover_fstring_template",
    "TemplateScanStep",
    "scan_template",
    "pin_signature_lines",
    "AccumulatorRewrite",
    "is_name_target",
    "single_line_segment",
    "apply_comprehension_rewrites",
    "single_name_assign_rhs",
    "accumulator_seed",
    "IN_MEMORY_ROOT",
    "source_override",
]


# Sentinel ``project_root`` value handed to an on-disk ``plan_<name>(root, rel)``
# transform when its source is being supplied IN MEMORY (no filesystem read).
# A caller that wants to dry-run a transform against a source string it already
# holds (the simplification scanner) opens a :func:`source_override` block, then
# calls the unmodified ``plan_<name>(IN_MEMORY_ROOT, rel)``; ``read_module_source``
# returns the registered source instead of touching disk. The value is a path that
# can never exist on a real tree, so an accidental fall-through to a disk read
# fails closed (records a "cannot read" blocker) rather than reading a stray file.
IN_MEMORY_ROOT = "<apex-in-memory>"

# Thread-local registry of ``module_rel -> source`` overrides active for the
# current thread. Thread-local (not a module global) so a concurrent caller in
# another thread never sees this thread's injected sources — the override is a
# strictly scoped, single-thread construct used only inside a ``with
# source_override(...)`` block. Determinism is preserved: the same source in →
# the same plan out, with no filesystem, clock, or randomness involved.
_SOURCE_OVERRIDES = threading.local()


def _active_source_overrides() -> dict[str, str] | None:
    """The override map registered for the current thread, or ``None`` when no
    :func:`source_override` block is active."""
    return getattr(_SOURCE_OVERRIDES, "stack", None)


@contextmanager
def source_override(sources: dict[str, str]):
    """Register ``module_rel -> source`` overrides for the duration of the block.

    Inside the block, any :func:`read_module_source` call whose ``module_rel`` is
    a key of ``sources`` returns the provided string verbatim instead of reading
    ``project_root / module_rel`` from disk — letting an on-disk
    ``plan_<name>(IN_MEMORY_ROOT, rel)`` transform run on an in-memory source with
    no filesystem write or re-read. The previous override map (if any) is restored
    on exit, so nested blocks compose. Keys are forward-slash relative paths, the
    exact spelling the transforms key ``is_fixture_path`` and the plan mappings
    off, so the resulting plan is byte-identical to the on-disk dry-run."""
    previous = getattr(_SOURCE_OVERRIDES, "stack", None)
    _SOURCE_OVERRIDES.stack = sources
    try:
        yield
    finally:
        _SOURCE_OVERRIDES.stack = previous


def read_module_source(
    plan: object, project_root: str | Path, module_rel: str,
) -> str | None:
    """Read ``project_root / module_rel`` as UTF-8 text, or ``None`` (after
    appending a ``f"cannot read {module_rel}"`` blocker to ``plan.blockers``) if
    it can't be read.

    This is the identical read step the single-module source transforms
    (bool-return, chain-comparison, dict-get, merge-isinstance, set-literal,
    redundant-else, ...) each carried verbatim. ``plan`` only needs a ``blockers``
    list, so this stays decoupled from any concrete plan type and keeps
    ``_transform_base`` free of a back-import on the transforms.

    If a :func:`source_override` block is active and ``module_rel`` is one of its
    keys, the registered source string is returned verbatim and the filesystem is
    never touched — the in-memory dry-run path used by the simplification scanner.
    The returned string is byte-identical to what the on-disk read would have
    produced, so the resulting plan is unchanged."""
    overrides = _active_source_overrides()
    if overrides is not None and module_rel in overrides:
        return overrides[module_rel]
    path = Path(project_root) / module_rel
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return None


def parse_module_source(
    plan: object, module_rel: str, source: str,
) -> ast.Module | None:
    """Parse ``source`` into its module tree, or ``None`` (after appending a
    ``f"{module_rel} doesn't parse: {e}"`` blocker to ``plan.blockers``) on a
    :class:`SyntaxError`.

    This is the identical parse step the single-module source transforms shared
    verbatim. ``plan`` only needs a ``blockers`` list, so this stays decoupled
    from any concrete plan type."""
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(f"{module_rel} doesn't parse: {e}")
        return None


def record_module_rewrite(
    plan: object, module_rel: str, source: str, new_source: str, edits: int,
) -> object:
    """Record a completed single-module rewrite onto ``plan`` and return it.

    Stores the original source under ``plan.originals[module_rel]``, the rewritten
    text under ``plan.new_contents[module_rel]``, and the rewrite count under
    ``plan.edits_by_file[module_rel]``. This is the identical finalise step every
    single-module source transform carried verbatim; returning ``plan`` lets the
    caller end on ``return record_module_rewrite(...)``. ``plan`` only needs those
    three mapping attributes, so this stays decoupled from any concrete plan type."""
    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = edits
    return plan


def finalize_module_rewrite(
    plan: object,
    module_rel: str,
    source: str,
    new_source: str,
    edits: int,
    *,
    reparse_phrase: str,
) -> object:
    """Verify ``new_source`` re-parses, then record the rewrite onto ``plan``.

    The shared tail every single-module source transform carried verbatim: if
    ``new_source`` doesn't parse, append a
    ``f"{module_rel}: {reparse_phrase} would not re-parse ({e}) — blocked"``
    blocker and return ``plan`` unchanged; if the rewrite is a no-op
    (``new_source == source``) return ``plan`` unchanged; otherwise record it via
    :func:`record_module_rewrite`. ``reparse_phrase`` is the transform's own verb
    phrase (e.g. ``"simplification"``, ``"merge"``, ``"chaining"``) so the blocker
    text stays identical to the inlined version. ``plan`` only needs a ``blockers``
    list and the three rewrite mappings, so this stays decoupled from any concrete
    plan type."""
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(
            f"{module_rel}: {reparse_phrase} would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan
    return record_module_rewrite(plan, module_rel, source, new_source, edits)


def plan_single_module_rewrite(
    project_root: str | Path,
    module_rel: str,
    *,
    plan_label: str,
    collect: Callable[[ast.Module, str], list],
    apply: Callable[[str, list], str],
    reparse_phrase: str,
) -> RenamePlan:
    """The read -> parse -> collect -> apply -> re-parse -> build-plan scaffold the
    single-module source transforms (chain-comparison, dict-get, merge-isinstance,
    set-literal, redundant-else, ...) each carried verbatim in their ``plan_*``
    bodies.

    ``plan_label`` is the :class:`RenamePlan` ``new`` tag (e.g. ``"chain-comparison"``).
    ``collect(tree, source)`` returns the transform's list of located rewrites;
    ``apply(source, rewrites)`` splices them into the new source. A fixture subject
    or an empty rewrite set yields an empty plan (a no-op, not a failure); an
    unreadable file, a parse failure, or a result that won't re-parse records a
    blocker via the same helpers (:func:`read_module_source`,
    :func:`parse_module_source`, :func:`finalize_module_rewrite`) — so
    ``reparse_phrase`` keeps the blocker text identical to the inlined version.
    Behaviour-identical to the per-module ``plan_*`` bodies it replaces, since it
    just sequences the existing primitives."""
    plan = RenamePlan(old=module_rel, new=plan_label)
    if is_fixture_path(module_rel):
        return plan

    source = read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    rewrites = collect(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = apply(source, rewrites)
    return finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase=reparse_phrase)


def parse_trees(files: list[tuple[str, str]]) -> dict[str, ast.Module]:
    """Parse every ``(rel, text)`` source into its module tree, silently
    skipping the ones that don't parse.

    A syntactically-broken module is invisible to the AST-located transforms —
    they can't reason about it — so it is dropped rather than raised on. This is
    the identical ``_parse_trees`` body the project-wide signature transforms
    (param-rename, param-drop, param-reorder, keywordify, move-module,
    cross-file-rename) each carried privately, hoisted here verbatim."""
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except (SyntaxError, RecursionError, MemoryError):
            continue
    return trees


def resolve_sole_definition(
    plan: object, trees: dict[str, ast.Module], func_name: str,
) -> tuple[str, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    """The single top-level definition of ``func_name`` across ``trees``, or
    ``None`` (after appending a blocker to ``plan.blockers``) unless it is
    defined exactly once at top level.

    A definition is a top-level ``def`` or ``async def`` whose name matches.
    This is the identical body the signature family's ``_resolve_definition`` /
    ``_sole_definition`` / ``_locate_definition`` helpers (param-drop, param-add,
    param-reorder) each carried — same blocker message, same exactly-one gate —
    hoisted here once. ``plan`` only needs a ``blockers`` list, so this stays
    decoupled from any concrete plan type and keeps ``_transform_base`` free of
    a back-import on the transforms."""
    definitions = [
        (rel, fn) for rel, tree in trees.items() for fn in tree.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and fn.name == func_name
    ]
    if len(definitions) != 1:
        plan.blockers.append(
            f"'{func_name}' must be defined exactly once at top level "
            f"(found {len(definitions)})")
        return None
    return definitions[0]


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


def text_is_valid(text: str, count: int) -> bool:
    """True iff ``text`` re-parses to exactly a JoinedStr with ``count``
    FormattedValue fields — the crucial safety re-parse before committing.

    This is the identical safety re-parse the f-string transforms
    (fstring-convert, percent-to-fstring) each carried privately."""
    try:
        expr = ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError, MemoryError):
        return False
    if not isinstance(expr, ast.JoinedStr):
        return False
    formatted = [v for v in expr.values if isinstance(v, ast.FormattedValue)]
    return len(formatted) == count


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
    except (SyntaxError, RecursionError, MemoryError) as e:
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
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(
            f"{module_rel}: conversion would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan


def arg_source(arg: ast.expr, source: str) -> str | None:
    """The recovered source of one ``arg``, or None if it can't be recovered or
    contains a brace/backslash.

    A simple arg's source never contains a brace; the guard holds anyway so the
    built f-string can't grow an unexpected field. This is the identical helper
    the f-string transforms (fstring-convert, percent-to-fstring) copied
    verbatim (modulo a one-word docstring difference)."""
    seg = ast.get_source_segment(source, arg)
    if seg is None:
        return None
    if "{" in seg or "}" in seg or "\\" in seg:
        return None
    return seg


def collect_arg_sources(args: list[ast.expr], source: str) -> list[str] | None:
    """Recover every arg's source in order, or None to skip.

    This is the identical helper the f-string transforms (fstring-convert,
    percent-to-fstring) copied verbatim (modulo a one-word docstring
    difference); it delegates each arg to :func:`arg_source`."""
    arg_srcs: list[str] = []
    for arg in args:
        seg = arg_source(arg, source)
        if seg is None:
            return None
        arg_srcs.append(seg)
    return arg_srcs


@dataclass(frozen=True)
class TemplateScanStep:
    """One step of a left-to-right placeholder-template scan (see
    :func:`scan_template`). ``consumed`` is how many characters of the template
    this step accounts for (>= 1). Exactly one of two outcomes:

    * ``field`` set — the chars at this position are a PLACEHOLDER: the buffered
      literal so far is flushed to a segment and ``field`` is recorded (its type
      is the caller's own field object — opaque here).
    * ``field`` None — the chars are LITERAL: ``literal`` is appended to the
      buffer (a plain char passes ``literal=<that char>``; an escape like ``%%``
      passes ``literal="%"`` with ``consumed=2``).
    """

    consumed: int
    field: object | None = None
    literal: str | None = None


def scan_template(
    inner: str,
    step: Callable[[str, int], "TemplateScanStep | None"],
) -> tuple[list[str], object] | None:
    """Split a template's INNER text into ``(segments, fields)`` by walking it
    left-to-right, delegating every position to ``step(inner, i)``.

    This is the byte-identical scan SKELETON that the ``{}`` form
    (format-to-fstring's ``_parse_template``) and the ``%`` form
    (percent-to-fstring's ``_split_template``) each carried verbatim — a
    ``while`` loop accumulating a literal ``buf``, flushing it to ``segments``
    on each placeholder and appending the parsed field. ONLY the per-position
    decision (what counts as a placeholder, an escape, or a disqualifier)
    differed, so that is the injected ``step``; the loop lives here once.

    ``step`` returns a :class:`TemplateScanStep`, or ``None`` to DISQUALIFY the
    whole template (the transform then skips the occurrence). Returns
    ``(segments, fields)`` with ``len(segments) == len(fields) + 1``, or ``None``
    if any step disqualified. ``fields`` is a ``list`` of whatever the caller's
    placeholder steps carried."""
    segments: list[str] = []
    fields: list[object] = []
    buf: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        s = step(inner, i)
        if s is None:
            return None
        if s.field is not None:
            segments.append("".join(buf))
            buf = []
            fields.append(s.field)
        else:
            buf.append(s.literal if s.literal is not None else inner[i])
        i += s.consumed
    segments.append("".join(buf))
    return segments, fields


def recover_fstring_template(
    template: ast.Constant,
    source: str,
    arg_count: int,
    *,
    split: Callable[[str], tuple[list[str], object] | None],
) -> tuple[str, list[str], object] | None:
    """Recover the literal, split it on placeholders, and check the count.

    Returns ``(quote, segments, extra)`` when the literal recovers to a plain
    string whose placeholder count (``len(segments) - 1``) both equals
    ``arg_count`` and is nonzero, else None (nothing to interpolate is left
    alone). ``split(inner)`` returns ``(segments, extra)``: the ``count + 1``
    literal segments around the placeholders, plus a transform-specific payload —
    ``None`` for the ``{}`` form (fstring-convert), the parsed per-placeholder
    conversion fields for the ``%`` form (percent-to-fstring). The splitter is
    the ONLY part that differs between the transforms; carrying ``extra`` through
    here is what lets BOTH reuse this one recover/count tail instead of cloning
    it (a numeric ``%`` conversion needs its format spec alongside the segments,
    which is exactly what ``extra`` delivers)."""
    literal_src = ast.get_source_segment(source, template)
    if literal_src is None:
        return None
    parsed = literal_inner(literal_src)
    if parsed is None:
        return None
    quote, inner = parsed

    result = split(inner)
    if result is None:
        return None
    segments, extra = result
    count = len(segments) - 1
    if count != arg_count:
        return None
    if count == 0:
        return None  # nothing to interpolate — leave it alone
    return quote, segments, extra


def pin_signature_lines(
    plan: object,
    source: str,
    defmod: str,
    span: tuple[int, int, int, int] | None,
) -> tuple[tuple[int, int, int, int], list[str]] | None:
    """Validate a pinned signature span and return ``(span, src_lines)``.

    Given the ``(...)`` header span already located by the caller (via
    ``_signature_span``), this splits ``source`` into keep-ends lines, rebuilds
    the exact signature text and refuses (returns ``None`` with a blocker) when
    the span could not be pinned (``span is None``) or the header carries a
    comment that rebuilding would silently drop.

    This is the byte-identical core the signature family's ``_signature_lines``
    (param-add) and ``_pin_signature`` (param-drop) each carried verbatim — they
    only differed in whether they returned ``(span, src_lines)`` or just ``span``,
    both of which the caller now derives from this single return. ``plan`` only
    needs a ``blockers`` list, so this stays decoupled from any concrete plan
    type and keeps ``_transform_base`` free of a back-import on the transforms."""
    if span is None:
        plan.blockers.append(f"{defmod}: could not pin the signature span")
        return None
    sl, sc, el, ec = span
    src_lines = source.splitlines(keepends=True)
    sig_text = (
        src_lines[sl - 1][sc:ec] if sl == el
        else src_lines[sl - 1][sc:] + "".join(src_lines[sl:el - 1]) + src_lines[el - 1][:ec])
    if "#" in sig_text:
        plan.blockers.append(
            f"{defmod}: the signature block contains a comment — rebuilding "
            "it would drop the comment, so this stays a human edit")
        return None
    return span, src_lines


class AccumulatorRewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) with a
    single comprehension line at ``indent`` spaces.

    This is the identical ``_Rewrite`` value the accumulator-loop comprehension
    transforms (list comprehension, dict comprehension) each carried privately."""

    __slots__ = ("lo", "hi", "indent", "text")

    def __init__(self, lo: int, hi: int, indent: int, text: str) -> None:
        self.lo = lo
        self.hi = hi
        self.indent = indent
        self.text = text


def is_name_target(target: ast.AST) -> bool:
    """A plain ``Name`` or a ``Tuple``/``List`` of plain Names (recursively) —
    no attribute/subscript/starred targets.

    This is the identical loop-target predicate the accumulator-loop comprehension
    transforms (list comprehension, dict comprehension) each carried verbatim."""
    if isinstance(target, ast.Name):
        return True
    if isinstance(target, (ast.Tuple, ast.List)):
        return bool(target.elts) and all(is_name_target(e) for e in target.elts)
    return False


def single_line_segment(source: str, node: ast.AST) -> str | None:
    """``ast.get_source_segment`` for ``node``, but only when ``node`` lives on a
    single line — multi-line segments are rejected so the rewrite stays trivial.

    This is the identical helper the accumulator-loop comprehension transforms
    (list comprehension, dict comprehension) each carried verbatim."""
    if getattr(node, "lineno", None) != getattr(node, "end_lineno", None):
        return None
    return ast.get_source_segment(source, node)


def apply_comprehension_rewrites(
    source: str, rewrites: list[AccumulatorRewrite],
) -> str:
    """Apply all comprehension rewrites bottom-up so earlier line numbers stay
    valid, preserving the original last line's trailing-newline behaviour.

    This is the identical ``_apply`` body the accumulator-loop comprehension
    transforms (list comprehension, dict comprehension) each carried verbatim; it
    delegates the bottom-up line splice to :func:`apply_line_rewrites`."""
    lines = source.splitlines(keepends=True)

    def _line(rw: AccumulatorRewrite) -> str:
        newline = "\n" if lines[rw.hi - 1].endswith("\n") else ""
        return " " * rw.indent + rw.text + newline

    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, [_line(rw)]) for rw in rewrites],
    )


def single_name_assign_rhs(stmt: ast.AST) -> tuple[str, ast.expr] | None:
    """For ``<name> = <rhs>`` with a single plain-``Name`` target, return
    ``(name, rhs)``; else None.

    Rejects a non-``Assign`` statement, a multi-target / chained assignment, and
    any non-``Name`` target (``a, b = ...``, ``x: T = ...``, ``obj.x = ...``). The
    caller checks ``rhs`` against its own empty-literal predicate (``[]`` vs
    ``{}``). This is the byte-identical head the accumulator-loop comprehension
    transforms' ``_assign_name`` helpers each carried verbatim — they only
    differed in the trailing RHS-literal check, which stays in each caller."""
    if not isinstance(stmt, ast.Assign):
        return None
    if len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None
    return target.id, stmt.value


def accumulator_seed(
    block: list[ast.stmt], idx: int,
    assign_name: Callable[[ast.AST], str | None],
) -> tuple[str, ast.For] | None:
    """For an accumulator at ``block[idx]``, return ``(name, for_stmt)``; else None.

    ``assign_name(block[idx])`` is the transform's empty-literal assignment matcher
    (``<name> = []`` for lists, ``<name> = {}`` for dicts). Returns None when the
    statement is not such an assignment, when there is no next sibling, or when the
    next sibling is not a ``for`` — exactly the cases each transform's
    ``_try_accumulator`` head treated as "skip this occurrence" (return 1). This is
    the byte-identical preamble those heads each carried verbatim; the caller maps a
    None result to ``return 1`` and otherwise proceeds with the recovered
    ``(name, for_stmt)``."""
    stmt = block[idx]
    name = assign_name(stmt)
    if name is None:
        return None
    nxt = block[idx + 1] if idx + 1 < len(block) else None
    if not isinstance(nxt, ast.For):
        return None
    return name, nxt
