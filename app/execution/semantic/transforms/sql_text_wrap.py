"""Land a SQL fix: wrap a STATIC raw-SQL literal in SQLAlchemy ``text()``.

Apex already DETECTS SQL reaching a DB sink, but for the genuinely dangerous
shapes (f-string / ``str.format()`` / ``%`` / concat) it only FLAGS them — those
build SQL from non-constants and can't be safely auto-parametrized, so the honest
move is a comment, not a rewrite (Apex can't prove the fix).

There is one shape where a fix DOES land cleanly: a sink call whose SQL argument
is a *static string literal*, e.g. ``session.execute("SELECT 1")`` /
``await conn.execute("...")``. Modern SQLAlchemy raises ``ArgumentError`` if you
pass a bare string to ``Connection.execute`` / ``Session.execute``; the supported
form is ``execute(text("..."))``. Wrapping the literal in ``text()`` is
behaviour-adjacent (it makes the call the API actually accepts) and provably safe
to do mechanically because the SQL text is a constant — no interpolation, nothing
to parametrize. We add the ``from sqlalchemy import text`` import alongside.

The rewrite is deliberately paranoid and REFUSES (no rewrite, the dynamic finding
stays FLAGGED byte-for-byte) on anything it can't prove safe:

  * the SQL arg is NOT a plain ``str`` ``Constant`` — an f-string
    (``ast.JoinedStr``), a ``"...".format(...)`` call, a ``"..." % x`` / ``"..." +
    x`` BinOp, a bare ``Name``, or any other expression is left alone;
  * the call already wraps the literal in ``text(...)`` — idempotent no-op.

Emission goes through the comment-preserving splice path
(:func:`run_splice_rewrite`), so a ``#`` comment near the call survives. The
result is re-parsed before it is emitted. Deterministic, stdlib + AST only,
offline (no clock / no randomness).
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_splice_rewrite as _run_splice_rewrite
from .base import import_insert_index

# DB-API cursor verbs + the realistic async/driver fetch verbs, mirroring the
# detector's ``_SQL_SINKS``. A static literal reaching any of these is the shape
# SQLAlchemy now rejects unless wrapped in ``text()``.
_SQL_SINKS = frozenset({
    "execute", "executemany", "cursor",
    "fetch", "fetchrow", "fetchval", "fetchmany",
})

_IMPORT_LINE = "from sqlalchemy import text\n"


def _is_text_wrapped(arg: ast.expr) -> bool:
    """True if ``arg`` is already a ``text(...)`` call (idempotency guard)."""
    return (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id == "text"
    )


def _static_sql_literal_arg(node: ast.Call) -> ast.Constant | None:
    """The first-arg static ``str`` literal of a SQL-sink call, else ``None``.

    Returns the literal ONLY for ``recv.<sink>("<static sql>")``-shaped calls
    whose first positional argument is a plain ``str`` ``ast.Constant``. Any
    dynamic shape (f-string, ``.format()``, ``%``/``+`` BinOp, a ``Name``, an
    already-``text()``-wrapped arg, ``*args``) returns ``None`` so the call is
    left untouched and its existing detector flag stays byte-identical.
    """
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in _SQL_SINKS):
        return None
    if not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Starred):
        return None
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return None
    return arg


class _SqlTextWrapTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # Recurse first so a nested sink (rare) is still considered.
        self.generic_visit(node)
        literal = _static_sql_literal_arg(node)
        if literal is None:
            return node
        if _is_text_wrapped(literal):
            return node  # already wrapped — idempotent no-op
        wrapped = ast.Call(
            func=ast.Name(id="text", ctx=ast.Load()),
            args=[literal],
            keywords=[],
        )
        new_args = list(node.args)
        new_args[0] = ast.copy_location(wrapped, literal)
        new_call = ast.Call(func=node.func, args=new_args, keywords=node.keywords)
        self.changed = True
        return ast.copy_location(new_call, node)


def _has_text_import(tree: ast.Module) -> bool:
    """True if ``text`` is already imported (``from sqlalchemy import text``)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "text" for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == "text" for alias in node.names):
                return True
    return False


def _insert_import(new_source: str) -> str:
    """Insert ``from sqlalchemy import text`` after any docstring/future imports.

    Idempotent: a source that already imports ``text`` is returned unchanged.
    """
    tree = _parse_or_none(new_source)
    if tree is None or _has_text_import(tree):
        return new_source
    lines = new_source.splitlines(keepends=True)
    at = import_insert_index(tree)
    lines.insert(at, _IMPORT_LINE)
    return "".join(lines)


def apply(rel_path: str, source: str, title: str = "") -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    transformer = _SqlTextWrapTransformer()
    new_source = _run_splice_rewrite(tree, transformer, source)
    if new_source is None:
        return None

    new_source = _insert_import(new_source)
    if new_source == source:
        return None
    if _parse_or_none(new_source) is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="sql_text_wrap",
        rationale=[
            f"Wrapped a static raw-SQL literal in SQLAlchemy text() in {rel_path} "
            f"(the API-supported form; dynamic SQL stays flagged, not rewritten)."
        ],
    )
