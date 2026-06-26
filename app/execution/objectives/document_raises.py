"""Self-registering develop objective: document-raises — the Python sibling of
the shipped JS ``document-raises-jsdoc`` (``@throws``).

Land a docstring carrying one ``Raises: <ErrorName>`` line per DISTINCT *escaping*
literal ``raise <ErrorName>(...)`` in a PUBLIC, currently-UNDOCUMENTED function.
Every name is read VERBATIM off a real ``raise ErrorName(...)`` node — never
inferred — so the docstring cannot misstate the failure contract. This is the
FAILURE-CONTRACT image of ``document-signature`` (a Raises line names a fact the
signature does NOT carry — a signature lists no exception names — so it is never a
content-free restatement), built from PURE AST facts and reusing the
``document-signature`` lane (public/undocumented/test gates, the
``_body_insertion`` placement, the single-line-body guard, and the re-parse +
undocumented-count-drops self-validation) VERBATIM by import.

THE ESCAPE WALKER (``_escaping_raises``). It mirrors the descend-but-stop-at-
nested-scope rule of :func:`app.tools.exception_hygiene._direct_raises`: it
descends plain control flow (``if``/``for``/``while``/``with`` and the
non-swallowing parts of ``try``) but STOPS at any new scope — ``def``/``async
def``/``class`` (and, since a ``lambda`` body is never an ``ast.stmt``, a lambda's
raises are invisible too). A raise there belongs to that scope, not this function,
so it is NOT attributed (escape-only attribution). It adds the inverse the
hygiene walker lacks — a TRY/EXCEPT SWALLOW GUARD: any ``ast.Try`` whose
``handlers`` is non-empty (a ``try … except …``, with or without ``finally``)
could swallow a raise, so the WHOLE function becomes UNPROVABLE and is REFUSED; a
``try … finally`` with NO ``except`` does NOT swallow, so its ``body``/``orelse``/
``finalbody`` are descended normally.

THE HONESTY GATE (mirrors ``document_raises_jsdoc._is_landable``). A raise is
PROVABLE iff ``r.exc`` is an ``ast.Call`` whose ``func`` is a BARE ``ast.Name``
whose ``id`` is a CamelCase exception identifier (``id[0].isupper()`` — the Python
image of the JS ``new Identifier`` rule, keeping a lowercase factory call like
``make_error()`` out of the ``Raises:`` line). Anything else makes the whole
function UNPROVABLE → refuse: a bare re-raise (``raise``), a ``raise <var>``, a
``raise fn()`` with a lowercase callee, or a dotted ``raise mod.Err(...)``. The
walker returns ``None`` for an unprovable shape (refuse the whole function), ``[]``
for no escaping raise (an honest no-op — never a content-free ``Raises:``), and
the DISTINCT names in SOURCE ORDER otherwise. The objective lands ONLY when the
set is non-None AND non-empty.

The single write is behaviour-IDENTICAL (a docstring is a string-literal first
statement — it changes no runtime value), idempotent (a second run finds the
function now documented and refuses — a byte-identical no-op), and deterministic
(pure AST → text, source order, no clock/random). Standard one-``plan_fn``-over-
every-module shape, registered via ``_base.register_module_objective`` — same
suite-gated, auto-rollback develop loop as every other objective.
``scope_verify`` is the default ``False`` (a docstring insert has no red-baseline a
full-suite gate could wrongly veto), and it is NOT ``expensive`` (a pure-AST scan,
unlike the node-spawning JS sibling). Stdlib-only, zero-token, offline.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.objectives.document_signature import (
    _DEF,
    _is_public_undocumented,
    _public_undocumented_count,
)
from app.execution.semantic.transforms.docstring import _body_insertion

# A raise belongs to the innermost enclosing scope; the walk stops at any of these
# exactly as :func:`app.tools.exception_hygiene._direct_raises` does (a ``lambda``
# body is never an ``ast.stmt``, so it is never walked into and needs no entry).
_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _safe_parse(source: str) -> ast.Module | None:
    """``ast.parse(source)`` or ``None`` — a conservative no-op on a source Apex
    cannot parse (a truncated def, or valid newer-grammar syntax on an older
    runtime). Same guarded-parse posture as ``document_signature``."""
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None


def _proven_raise_name(node: ast.Raise) -> str | None:
    """The CamelCase exception name a literal ``raise <Name>(...)`` PROVES, or
    ``None`` when the raise is an unprovable shape.

    Provable iff ``node.exc`` is an ``ast.Call`` whose ``func`` is a bare
    ``ast.Name`` with a CamelCase ``id`` (``id[0].isupper()`` — the Python image
    of the JS ``new Identifier`` rule, keeping a lowercase factory like
    ``make_error()`` out of the ``Raises:`` line). ``None`` therefore covers a bare
    re-raise (``node.exc is None``), a ``raise <var>``, a dotted ``raise
    mod.Err(...)``, and a lowercase-callee ``raise fn()`` — every shape whose name
    cannot be read verbatim."""
    exc = node.exc
    if not (isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)):
        return None
    ident = exc.func.id
    return ident if ident and ident[0].isupper() else None


def _escaping_raises(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str] | None:
    """The DISTINCT exception names a PROVEN literal ``raise <Name>(...)`` lets
    ESCAPE ``fn``, in source order — or ``None`` when the body is unprovable.

    Return contract (mirrors the JS driver's ``throws_types``):
      - ``None``  — an UNPROVABLE shape is present, so the whole function is
        refused. That is: any raise :func:`_proven_raise_name` cannot read (a bare
        re-raise, a ``raise <var>``, a lowercase-callee ``raise fn()``, a dotted
        ``raise mod.Err(...)``), OR any ``ast.Try``/``ast.TryStar`` with a
        non-empty ``except`` that could SWALLOW a raise (the swallow guard), OR any
        ``ast.With``/``ast.AsyncWith`` body containing a raise (a context manager
        could swallow it — ``contextlib.suppress`` and any ``__exit__`` returning
        truthy).
      - ``[]``    — nothing escapes (an honest no-op; never a content-free Raises).
      - ``[name, …]`` — the DISTINCT provable names, first-seen order.

    Descends plain control flow and the non-swallowing parts of ``try`` but STOPS
    at any new scope (``def``/``async def``/``class``; a ``lambda`` body is not a
    statement, so it is never entered) — escape-only attribution, the same walk
    shape as :func:`app.tools.exception_hygiene._direct_raises`."""
    names: list[str] = []

    def walk(nodes: list[ast.stmt], under_with: bool = False) -> bool:
        """Append every provable escaping name; return ``False`` (and stop) the
        moment an unprovable shape appears — a swallowing ``try``/``try*`` with
        handlers, an unreadable raise, OR a raise inside a ``with``/``async with``
        whose context manager could suppress it (``contextlib.suppress`` and any
        ``__exit__`` returning truthy)."""
        for node in nodes:
            if isinstance(node, (ast.Try, ast.TryStar)):
                if node.handlers:
                    return False  # try/except(*) could swallow → refuse
                # try/finally with NO except does NOT swallow: descend the parts
                # that actually run (body, the no-exception else, and finally).
                if not (walk(node.body, under_with)
                        and walk(node.orelse, under_with)
                        and walk(node.finalbody, under_with)):
                    return False
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                # A context manager's __exit__ may suppress the raise (e.g.
                # contextlib.suppress), so a raise inside the body is no longer
                # provably escaping. Descend under the swallow flag.
                if not walk(node.body, under_with=True):
                    return False
            elif isinstance(node, ast.Raise):
                if under_with:
                    return False  # an enclosing context manager could swallow it
                name = _proven_raise_name(node)
                if name is None:
                    return False
                if name not in names:
                    names.append(name)
            elif not isinstance(node, _SCOPE):  # new scope's raises are not ours
                kids = [c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt)]
                if not walk(kids, under_with):
                    return False
        return True

    return names if walk(fn.body) else None


def _raises_lines(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, indent: str, names: list[str],
) -> list[str]:
    """The full docstring as already-indented source lines (with newlines).

    A summary derived from the function name (a fact, mirroring
    ``document_signature._docstring_lines``), then a ``Raises:`` block with one
    line per DISTINCT escaping exception name in source order. Every line is a
    fact; nothing is invented. Blank separator lines are emitted EMPTY (no indent)
    per the PEP-257 / black convention, exactly as ``_docstring_lines`` does."""
    out = [f'{indent}"""{fn.name}.\n', "\n", f"{indent}Raises:\n"]
    out.extend(f"{indent}    {name}\n" for name in names)
    out.append(f'{indent}"""\n')
    return out


def _documentable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str],
) -> tuple[int, list[str]] | None:
    """``(insert_line_index, docstring_lines)`` for ``fn`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/undocumented/non-test gate
    (:func:`document_signature._is_public_undocumented`), the ESCAPING-RAISES gate
    (:func:`_escaping_raises` — ``None`` ⇒ unprovable shape ⇒ refuse, ``[]`` ⇒
    nothing to document ⇒ refuse, the honesty gate), and a usable docstring
    insertion point (:func:`_body_insertion` from the shared docstring transform).
    A single-line-body def reports its HEADER text as the "indent"; a real body
    indent is pure whitespace, so a non-whitespace indent is refused (mirrors
    ``document_signature``) — splicing there would corrupt the line and the batch
    self-validation would then silently drop every sibling's doc."""
    if not _is_public_undocumented(fn):
        return None
    names = _escaping_raises(fn)
    if not names:  # None (unprovable) OR [] (no escaping raise) -> refuse
        return None
    spot = _body_insertion(fn, lines)
    if spot is None:
        return None
    insert_at, body_indent = spot
    if not body_indent.isspace():
        return None
    return insert_at, _raises_lines(fn, body_indent, names)


def document_raises(source: str) -> str | None:
    """Return ``source`` with a proven ``Raises:`` docstring added to every
    qualifying public function, or ``None`` when nothing qualifies (or the source
    does not parse).

    Splices each docstring as the function's first body statement, bottom-up so
    earlier line indices stay valid (mirroring the docstring transform). Self-
    validating: the result must re-parse AND the public-undocumented count must
    drop by exactly the number of functions documented — else the change is refused
    (returns ``None``). Pure AST → text; deterministic (source order)."""
    old_tree = _safe_parse(source)
    if old_tree is None:
        return None

    rows = source.splitlines(keepends=True)
    defs = sorted(
        (n for n in ast.walk(old_tree) if isinstance(n, _DEF)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    edits = [spot for n in defs if (spot := _documentable_target(n, rows))]
    if not edits:
        return None

    # Apply bottom-up (descending insert index) so the earlier offsets stay valid.
    for at, doc in sorted(edits, key=lambda e: e[0], reverse=True):
        rows[at:at] = doc
    landed = "".join(rows)

    new_tree = _safe_parse(landed)
    if new_tree is None:
        return None
    dropped = _public_undocumented_count(old_tree) - _public_undocumented_count(new_tree)
    if dropped != len(edits) or landed == source:
        return None  # the count must fall by EXACTLY the edits we made (self-proof)
    return landed


def plan_document_raises(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the proven ``Raises:``-docstring plan for one module, or an empty
    no-op plan.

    Documents every qualifying public function in ``module_rel`` (public name, no
    docstring, not ``test_*``, and at least one PROVEN escaping ``raise
    <Name>(...)``) via :func:`document_raises`. The shared single-file-rewrite
    plumbing — refuse a test/fixture/non-library file, read the module, record the
    single rewrite with its original for rollback (or a no-op when nothing is
    provable) — is delegated to :func:`plan_source_rewrite`, the one source of
    truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-raises", document_raises)


register_module_objective(
    "document-raises", plan_document_raises,
    operator="document_raises",
    description="document the raised exceptions of functions in {rel} with a Raises: docstring",
)
