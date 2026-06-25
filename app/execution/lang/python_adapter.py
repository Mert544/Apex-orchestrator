"""``PythonAdapter`` — the canonical, OFF-BY-DEFAULT Python realisation of the
:class:`LanguageAdapter` seam.

This adapter exists so the Protocol has its canonical FIRST instance (Python
wins the registry dispatch for ``.py`` files), but it is a PARALLEL accessor
only: it is NOT wired into the live Python develop path. The existing Python
enumeration/objective call sites (``SourceIndex.build``, ``objective_compiler``'s
own-module list, every ``objectives/*.py`` and ``semantic/transforms/*.py``)
keep calling their CURRENT functions directly, so Python module lists and
emitted text are unchanged — byte-identical by construction.

Every method is a literal DELEGATION to the existing predicates/parsers:

* ``owns`` = ``rel.endswith(".py") and not is_fixture_path(rel) and not
  _is_non_library_file(rel)`` — the SAME gate ``SourceIndex.build`` and the
  single-file transform family already enforce.
* ``parse`` / ``reparses`` = ``ast.parse`` — the same call ``parse_module_source``
  and ``finalize_module_rewrite`` make.
* ``locate`` = the byte span of the named top-level function, derived from its
  ``ast`` ``col_offset``/``end_col_offset`` via line offsets (the body span a
  splice would target).
* ``apply`` = a pure byte-span splice over that range, the Python image of the
  JS ``_splice_body``.

Deterministic, stdlib-only (``ast``), zero-token. Importing this module forms no
app import cycle — it depends only on the seam types and the leaf predicate
helpers, never on ``objective_compiler``.
"""

from __future__ import annotations

import ast

from app.execution._transform_base import is_fixture_path
from app.execution.cross_file_rename import _is_non_library_file
from app.execution.lang.adapter import (
    Edit,
    ParseTree,
    Target,
    TargetQuery,
)

__all__ = ["PythonAdapter"]


def _line_starts(source: str) -> list[int]:
    """Byte offset of the start of each 1-indexed line, so an ``ast`` (lineno,
    col) maps to an absolute offset. Index 0 is unused (lines are 1-indexed);
    index ``n`` is the offset of line ``n``."""
    offsets = [0, 0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _node_span(node: ast.AST, source: str) -> tuple[int, int] | None:
    """The absolute ``(start, end)`` byte span of ``node`` in ``source`` from its
    ``ast`` line/col offsets, or ``None`` when the offsets are unavailable (a
    synthesised node). The same derivation ``ast.get_source_segment`` performs,
    kept explicit so the span is the splice target."""
    starts = _line_starts(source)
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if end_lineno is None or end_col is None:
        return None
    if node.lineno >= len(starts) or end_lineno >= len(starts):
        return None
    return (starts[node.lineno] + node.col_offset, starts[end_lineno] + end_col)


class PythonAdapter:
    """The Python :class:`LanguageAdapter` delegator — calls the existing
    predicates/parsers verbatim. Registered so the Protocol has its canonical
    first instance, but the live Python path does NOT route through it."""

    name = "python"

    def owns(self, rel: str) -> bool:
        """True for a library ``.py`` source — the SAME gate the source index and
        single-file transforms enforce: a ``.py`` file that is neither a
        test/fixture nor a non-library (packaging/config) script."""
        return (rel.endswith(".py")
                and not is_fixture_path(rel)
                and not _is_non_library_file(rel))

    def parse(self, source: str) -> ParseTree | None:
        """The parsed module, or ``None`` when ``source`` does not parse — the
        same ``ast.parse`` (and refusal) ``parse_module_source`` performs."""
        try:
            return ParseTree(tree=ast.parse(source))
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None

    def locate(self, tree: ParseTree, source: str,
               query: TargetQuery) -> Target | None:
        """The byte span of the top-level function named ``query.name``, or
        ``None`` when it is absent or defined more than once (ambiguous — refuse,
        never guess). The span is derived from the ``ast`` node's offsets."""
        module = tree.tree
        defs = [n for n in getattr(module, "body", [])
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == query.name]
        if len(defs) != 1:
            return None
        span = _node_span(defs[0], source)
        if span is None:
            return None
        return Target(name=query.name, span=span)

    def apply(self, source: str, target: Target, edit: Edit) -> str | None:
        """``source`` with ``target``'s span replaced by ``edit.body``, or
        ``None`` when the span is stale — a pure byte-span splice, the Python
        image of the JS ``_splice_body``."""
        start, end = target.span
        if not (0 <= start <= end <= len(source)):
            return None
        return source[:start] + edit.body + source[end:]

    def reparses(self, new_source: str) -> bool:
        """True when ``new_source`` re-parses — the same try/``ast.parse`` proof
        ``finalize_module_rewrite`` uses to refuse a malformed splice."""
        try:
            ast.parse(new_source)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return False
        return True
