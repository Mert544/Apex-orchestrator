"""Fix B904: ``raise X(...)`` inside ``except E as err:`` → ``raise X(...) from err``.

Raising a fresh exception inside an except block without ``from`` discards the
original traceback chain. When the handler *binds* the caught exception, adding
``from <name>`` is a pure, behavior-safe append (the chain is restored; nothing
else changes). Handlers without a binding are left alone — inventing a binding
would be a bigger edit than this transform promises.

The append is spliced by COLUMN OFFSET (the raise's ``end_col_offset`` on its end
line), never by textual ``str.replace`` — a textual replace would rewrite the
FIRST occurrence of the raise's source on the physical line, and if that text also
appears earlier (e.g. inside a string literal:
``tag = "raise RuntimeError(1)"; raise RuntimeError(1)``) it would splice ``from
err`` INTO the string, leave the real raise un-caused, re-parse cleanly (the
never-fake-green floor is blind to a same-text splice) and churn forever. The
offset splice operates on the exact character position just past the raise
expression, so it is collision-proof.

It also refuses when the bound name is no longer the caught exception at the raise
— the handler ``del``\\ s it (``from err`` would raise ``UnboundLocalError``,
changing the exception TYPE + control flow) or REBINDS it (``from err`` would chain
a fabricated, semantically-wrong cause). Any such ``del``/(re)binding of the name
BEFORE the target raise (in the handler's own scope) declines the fix.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        new_content = _chain_handler(source, handler)
        if new_content is None:
            continue
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_content,
                "expected_old_content": source,
            }],
            transform_type="raise_with_from",
            rationale=[
                f"Chained the re-raised exception to its cause (`from {handler.name}`) "
                f"in {rel_path}, preserving the original traceback."
            ],
        )

    return None


def _chain_handler(source: str, handler: ast.ExceptHandler) -> str | None:
    """The full source with ``handler``'s first fixable raise chained ``from
    <handler.name>``, or ``None`` when this handler offers no safe single-line
    chain (no fixable raise / multi-line raise / the binding was del'd or rebound /
    a degenerate offset). Pure — does not mutate ``source``."""
    target = _first_fixable_raise(handler.body)
    if target is None:
        return None
    seg = ast.get_source_segment(source, target)
    if not seg or "\n" in seg:
        return None  # multi-line raise: line surgery would be fragile — skip
    if not _name_still_caught_exception(handler, target):
        return None  # the binding was del'd/rebound -> chaining it would change behavior
    return _splice_from(source, target, handler.name)


def _splice_from(source: str, target: ast.Raise, name: str) -> str | None:
    """``source`` with `` from <name>`` inserted at ``target``'s ``end_col_offset``
    on its end line, or ``None`` for a degenerate offset.

    The COLUMN-OFFSET splice (vs. a textual ``str.replace``) is collision-proof: it
    inserts at the exact character position past the raise expression, so a string
    literal that happens to repeat the raise's source on the line is never touched."""
    lines = source.splitlines(keepends=True)
    end_idx = (target.end_lineno or target.lineno) - 1
    end_col = target.end_col_offset
    if end_col is None or not 0 <= end_idx < len(lines):
        return None
    line = lines[end_idx]
    if end_col > len(line):
        return None  # offset past the line end (defensive — single-line raise only)
    lines[end_idx] = f"{line[:end_col]} from {name}{line[end_col:]}"
    return "".join(lines)


def _first_fixable_raise(body: list) -> ast.Raise | None:
    """The first ``raise Ctor(...)`` without a cause, in handler scope.

    Mirrors the detector's walk: nested functions/classes/try blocks are their
    own contexts and are skipped.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
            continue
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call) and stmt.cause is None:
            return stmt
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
            found = _first_fixable_raise(stmt.body) or _first_fixable_raise(
                getattr(stmt, "orelse", [])
            )
            if found is not None:
                return found
    return None


def _name_still_caught_exception(handler: ast.ExceptHandler, target: ast.Raise) -> bool:
    """True iff ``handler.name`` still names the CAUGHT exception at ``target``.

    Walks every node in the handler body that lexically PRECEDES ``target`` (by
    position) and returns ``False`` the moment the bound name is unbound (``del
    err``) or (re)bound (``err = ...`` / ``err: T = ...`` / ``err += ...`` / ``(err
    := ...)`` / ``for err in ...`` / ``with ... as err`` / ``import ... as err`` / a
    nested ``except ... as err`` shadow / a comprehension target). Either makes
    ``raise X(...) from err`` change behavior — an ``UnboundLocalError`` (wrong
    exception TYPE + control flow) or a fabricated, semantically-wrong ``__cause__``
    — so the transform must decline. Conservative: any doubt → refuse (``False``).

    Scope is the handler's OWN statements; a nested ``def``/``lambda`` binding the
    same name is a separate scope, but a (re)binding there still PRECEDES the target
    raise lexically only if it physically sits above it, and a raise inside such a
    nested scope is already skipped by :func:`_first_fixable_raise`. Counting those
    extra (re)bindings can only make this MORE conservative (refuse), never less —
    which is the safe direction."""
    name = handler.name
    raise_pos = (target.lineno, target.col_offset)
    for node in ast.walk(handler):
        if node is target or node is handler:
            continue  # the handler's OWN ``as <name>`` is the caught binding, not a rebind
        pos = (getattr(node, "lineno", None), getattr(node, "col_offset", None))
        # Only bindings that lexically precede the target raise matter. A node with
        # no position (rare) is treated conservatively as "before" the raise.
        if pos[0] is not None and pos >= raise_pos:
            continue
        if _node_unbinds_or_rebinds(node, name):
            return False
    return True


def _node_unbinds_or_rebinds(node: ast.AST, name: str) -> bool:
    """True iff ``node`` ``del``\\ s or (re)binds the bare ``name``.

    Covers every binding form a handler statement can introduce for ``name``:
    ``del``, ``=`` / annotated / augmented assignment, the walrus ``:=``, ``for``
    targets, ``with``/``except`` ``as`` clauses, and ``import ... as``. Split across
    two category helpers so each stays simple: :func:`_target_form_binds` for the
    nodes carrying assignment/del TARGETS, :func:`_as_clause_binds` for the nodes
    carrying a bare bound NAME (an ``as``/``import`` clause)."""
    return _target_form_binds(node, name) or _as_clause_binds(node, name)


def _target_form_binds(node: ast.AST, name: str) -> bool:
    """True iff a ``del``/assignment-like ``node`` binds ``name`` through a TARGET.

    ``del`` / ``=`` / ``+=`` / ``err: T = …`` / ``(err := …)`` / ``for err in …`` /
    a comprehension ``for``. A bare ``ast.Name`` store anywhere in the target
    (including tuple/list unpacking and a starred target) counts. An ``AnnAssign``
    with no value (a bare annotation ``err: T``) does NOT rebind, so it is allowed."""
    if isinstance(node, ast.Delete):
        return any(_target_binds(t, name) for t in node.targets)
    if isinstance(node, ast.Assign):
        return any(_target_binds(t, name) for t in node.targets)
    if isinstance(node, ast.AugAssign):
        return _target_binds(node.target, name)
    if isinstance(node, ast.AnnAssign):
        return node.value is not None and _target_binds(node.target, name)
    if isinstance(node, ast.NamedExpr):
        return _target_binds(node.target, name)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return _target_binds(node.target, name)
    return False


def _as_clause_binds(node: ast.AST, name: str) -> bool:
    """True iff ``node`` binds ``name`` through an ``as``/``import`` clause:
    ``with … as err`` / a nested ``except … as err`` shadow / ``import … as err``
    (or ``import err`` binding the top-level package name)."""
    if isinstance(node, ast.withitem):
        return node.optional_vars is not None and _target_binds(node.optional_vars, name)
    if isinstance(node, ast.ExceptHandler):
        return node.name == name
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return any((alias.asname or alias.name.split(".")[0]) == name for alias in node.names)
    return False


def _target_binds(target: ast.AST, name: str) -> bool:
    """True iff an assignment/del ``target`` binds the bare ``name`` (recursing into
    tuple/list unpacking and starred targets).

    An attribute or subscript target (``err.x = ...`` / ``err[0] = ...``) mutates an
    object the name still points at — it does NOT rebind ``err`` itself — so it is
    safe and returns ``False``."""
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, ast.Starred):
        return _target_binds(target.value, name)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_binds(el, name) for el in target.elts)
    return False
