r"""Remove a redundant ``f`` prefix — an f-string with NO placeholders is just a
plain string with extra ceremony, so drop the ``f``::

    x = f"hello world"   ->   x = "hello world"
    log(f"done")         ->   log("done")
    r = rf"raw\d"        ->   r = r"raw\d"

This is exactly what ruff flags as ``F541`` ("f-string without any
placeholders"). An f-string literal whose only parts are constant text carries no
interpolation, so the ``f`` prefix is pure noise; stripping it is value-preserving
and the resulting bytes are identical at runtime.

PROVABLY-SAFE SUBSET — fire ONLY when the strip is unimpeachable.
================================================================
The match is an ``ast.JoinedStr`` (the AST node for an f-string) whose ``values``
contain ZERO ``ast.FormattedValue`` children — i.e. only ``ast.Constant`` parts,
or a single constant, or nothing. A node with even one ``FormattedValue`` (a
``{...}`` interpolation) is NEVER touched: dropping the ``f`` there would be a
syntax error or silently change behaviour.

Beyond "no placeholders", several conservative blockers keep the rewrite safe:

  - **Implicit concatenation.** ``f"a" f"b"`` and ``f"a" "b"`` parse to a SINGLE
    ``JoinedStr`` node spanning BOTH literals, yet only the first (or some) carry
    the ``f``. Stripping the one leading ``f`` would leave a half-rewritten,
    possibly meaning-changed expression. The node's source segment is tokenised
    and the rewrite fires ONLY when the segment is exactly ONE ``STRING`` token —
    a lone literal, no concatenation. Any multi-token segment is skipped.

  - **Escaped braces.** ``f"{{x}}"`` has no ``FormattedValue`` (the doubled braces
    are literal), but its RENDERED value is ``{x}`` whereas the plain string
    ``"{{x}}"`` renders ``{{x}}`` — so the strip is NOT value-preserving. Any
    literal whose source contains a ``{`` or ``}`` is skipped, conservatively.

  - **Prefix recovery.** The literal's prefix (the run of letters before the
    opening quote) must contain an ``f``/``F`` and otherwise consist only of
    ``r``/``R`` (a raw flag, kept). ``rf"..."`` -> ``r"..."``, ``fr"..."`` ->
    ``r"..."``, ``F"..."`` -> ``"..."``. If the prefix is anything the strip can't
    reason about, the occurrence is skipped.

Only the leading ``f``/``F`` character is removed; the quotes, the raw flag and
every byte of content are preserved exactly. The edit is a single-line column
splice on the PREFIX (which always lives on the literal's start line at
``col_offset``), so multi-line triple-quoted f-strings rewrite correctly and
comments/formatting elsewhere survive — no unparse round-trip.

Rewrites are applied bottom-up and right-to-left (the shared
:func:`app.execution._transform_base.apply_column_rewrites`) so earlier offsets
stay valid when several share a line. The rewritten module must re-parse and the
plain-string value must match the f-string's, or the whole plan blocks.
Deterministic, stdlib-only (``ast`` + ``tokenize``); reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    is_fixture_path,
)
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_remove_redundant_fstring"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


class _Rewrite:
    """One located prefix strip: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text`` (the prefix sans ``f``)."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _has_placeholder(node: ast.JoinedStr) -> bool:
    """True iff the f-string has ANY ``{...}`` interpolation, i.e. at least one
    ``ast.FormattedValue`` part. Such a node is never a redundant f-string."""
    return any(isinstance(v, ast.FormattedValue) for v in node.values)


def _single_string_token(segment: str) -> str | None:
    """Return the lone ``STRING`` token text of ``segment`` if (and only if)
    ``segment`` tokenises to EXACTLY one string literal, else ``None``.

    This is the implicit-concatenation guard: ``f"a" f"b"`` / ``f"a" "b"`` yield
    two ``STRING`` tokens and are rejected, so the half-rewrite is never produced.
    A segment that fails to tokenise (truncated/odd source) is rejected too."""
    strings: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(segment).readline):
            if tok.type == tokenize.STRING:
                strings.append(tok.string)
            elif tok.type in (
                tokenize.NEWLINE, tokenize.NL,
                tokenize.ENDMARKER, tokenize.ENCODING,
                tokenize.INDENT, tokenize.DEDENT,
            ):
                continue
            else:
                return None  # an unexpected token — not a lone literal
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    if len(strings) != 1:
        return None  # zero or implicit-concatenation — skip
    return strings[0]


def _strip_prefix(literal: str) -> str | None:
    """Given a single string literal's source, return its prefix WITHOUT the
    ``f``/``F``, or ``None`` if the strip is not provably safe.

    The prefix is the run of letters before the opening quote (``"`` or ``'``). It
    must contain exactly one ``f``/``F`` and otherwise only ``r``/``R`` (a raw
    flag, preserved). Any other letter (e.g. ``b`` — a bytes literal can't carry
    ``f`` anyway) or a missing/duplicate ``f`` means skip."""
    quote_idx = None
    for i, ch in enumerate(literal):
        if ch in ("'", '"'):
            quote_idx = i
            break
    if quote_idx is None or quote_idx == 0:
        return None  # no prefix (already plain) or no quote found — skip
    prefix = literal[:quote_idx]
    lowered = prefix.lower()
    if lowered.count("f") != 1:
        return None  # not exactly one f — skip
    if any(c not in ("f", "r") for c in lowered):
        return None  # an unexpected prefix letter (e.g. bytes) — skip
    # Drop ONLY the f/F char, keep the r/R (and its case) intact.
    return "".join(ch for ch in prefix if ch not in ("f", "F"))


def _try_node(node: ast.JoinedStr, source: str) -> _Rewrite | None:
    """If ``node`` is a placeholder-free, single-literal f-string with a strippable
    prefix and no ``{``/``}`` in its source, return the prefix-strip rewrite, else
    ``None``."""
    if _has_placeholder(node):
        return None  # has an interpolation — never touch
    segment = ast.get_source_segment(source, node)
    if segment is None:
        return None  # can't recover the source — skip
    literal = _single_string_token(segment)
    if literal is None:
        return None  # implicit concatenation / unrecoverable — skip
    if "{" in literal or "}" in literal:
        return None  # escaped braces render differently when plain — skip
    new_prefix = _strip_prefix(literal)
    if new_prefix is None:
        return None  # prefix not provably strippable — skip

    # The prefix occupies the literal's start line, starting at col_offset; its
    # length is (orig prefix length) = the quote position within the literal.
    quote_idx = len(literal) - len(literal.lstrip("rRfF"))
    start_col = node.col_offset
    return _Rewrite(node.lineno, start_col, start_col + quote_idx, new_prefix)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every provably-redundant f-string prefix in ``tree``.

    JoinedStr nodes never nest into another redundant match (an inner f-string in
    a placeholder is its own FormattedValue, which blocks the outer node), so no
    nested-span pruning is needed."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            rw = _try_node(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply prefix strips bottom-up and right-to-left so earlier column offsets
    stay valid when several share a line."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_remove_redundant_fstring(
        project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module remove-redundant-fstring plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan strips the ``f``/``F``
    prefix from every f-string literal that provably carries NO placeholder (an
    ``ast.JoinedStr`` with zero ``FormattedValue`` parts, a lone literal — not
    implicit concatenation — with no ``{``/``}`` in its source and a strippable
    ``f``/``rf``/``fr``/``F`` prefix). An f-string with any interpolation, an
    implicit concatenation, or escaped braces is left untouched. An empty plan (no
    new_contents, no blockers) means nothing matched — a no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new="remove-redundant-fstring")
    if _is_fixture_path(module_rel):
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

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="rewrite")
