"""Self-registering develop objective: document-signature.

Land a docstring on an UNDOCUMENTED public function — but ONLY when every line
of that docstring states a PROVEN fact, never a guess. The generated docstring
carries exactly two kinds of fact:

  - the function's PARAMETER NAMES, read straight off the AST (an ``Args:``
    block, one line per parameter — names only, no invented descriptions), and
  - a ``Returns: <type>`` line whose ``<type>`` comes from the EXISTING proven
    return-type oracle in
    :mod:`app.execution.semantic.transforms.type_annotations`
    (``_infer_return_type`` — the same agreeing-literal / fixed-result-builtin /
    pure-procedure-``None`` inference the ``infer-type-hints`` objective lands as
    ``-> T``), or, when the function already carries an explicit ``-> T``
    annotation, that author-declared annotation itself (also a proven fact).

CRITICAL GATE — emit ONLY when the return type is PROVABLE. If the oracle
refuses (an ambiguous / non-literal / fall-through return), this objective
REFUSES too: it lands NOTHING — no placeholder skeleton, no ``Returns: Any``,
no guess. That is the honest under-claim Apex promises; a docstring that named a
type it could not prove would be exactly the wrong-but-verified noise to avoid
(a docstring changes no runtime value, so no test could ever catch the lie).

Also REFUSED (left byte-for-byte alone): an already-documented function (it has
a docstring), a private/dunder name (a leading ``_``), a ``test_*`` function,
and any test/fixture file (the suite Apex is gated by is never edited).

The single write is behaviour-preserving (docstring TEXT only — it inserts a
string-literal first statement, changing no runtime value), idempotent (a second
run finds the function now documented and refuses, so it is a byte-identical
no-op), and deterministic (pure AST → text, source order, no clock/random). The
docstring PLACEMENT/indent mechanics are reused from
:mod:`app.execution.semantic.transforms.docstring` (``_body_insertion``); the
proven return type is reused from ``type_annotations`` — neither is modified.

Standard module-objective shape (one ``plan_fn`` over every own module), so it
registers via ``_base.register_module_objective`` — same suite-gated,
auto-rollback develop loop as every other objective. Stdlib-only, zero-token.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.semantic.transforms.docstring import _body_insertion
from app.execution.semantic.transforms.type_annotations import _infer_return_type

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)


def _is_public_undocumented(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` is a PUBLIC, currently-UNDOCUMENTED, non-test function.

    Refuses (returns ``False``) for: a name with a leading ``_`` (private or a
    dunder — never a public-surface symbol), a ``test_`` function (part of the
    suite), and a function that already has a docstring (``ast.get_docstring``
    is not ``None``). Each refusal keeps the objective from touching a symbol it
    must leave alone, and the already-documented check is what makes the pass
    idempotent — a second run sees the docstring and refuses."""
    name = fn.name
    if name.startswith("_") or name.startswith("test_"):
        return False
    return ast.get_docstring(fn) is None


def _provable_return_type(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The PROVEN return type NAME for ``fn``, or ``None`` when not provable.

    Two proven sources, in order:
      1. an EXISTING explicit ``-> T`` annotation (``fn.returns``) — an
         author-declared fact, read verbatim via :func:`ast.unparse`. (The
         oracle below deliberately refuses an already-annotated function, so
         this branch is what documents a typed-but-undocumented function.)
      2. otherwise the EXISTING return-type oracle ``_infer_return_type`` from
         ``type_annotations`` — the only other source ever used. It returns the
         string ``"None"`` for a proven pure procedure (PROVABLE ⇒ documented as
         ``Returns: None``) and Python ``None`` when the return type is NOT
         provable (an ambiguous/non-literal/fall-through return) ⇒ REFUSE.

    Never guesses: a Python ``None`` here means "not provable", and the caller
    lands nothing for that function — the critical gate."""
    if fn.returns is not None:
        return ast.unparse(fn.returns)
    return _infer_return_type(fn)


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Every parameter NAME of ``fn``, in signature order — pure AST facts.

    Covers positional-only, normal, ``*vararg``, keyword-only and ``**kwarg``
    parameters; ``self``/``cls`` are included verbatim (they are real
    parameters). Names only — no types or descriptions are invented."""
    args = fn.args
    names = [a.arg for a in (*args.posonlyargs, *args.args)]
    if args.vararg is not None:
        names.append("*" + args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg is not None:
        names.append("**" + args.kwarg.arg)
    return names


def _docstring_lines(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, indent: str, return_type: str,
) -> list[str]:
    """The full docstring as already-indented source lines (with newlines).

    A summary derived from the function name (a fact, mirroring the existing
    docstring transform's name-based body), an optional ``Args:`` block listing
    each parameter NAME, and a ``Returns: <type>`` line carrying the PROVEN
    type. Every line is a fact; nothing is invented."""
    params = _param_names(fn)
    # Blank separator lines are emitted EMPTY (no indent) so the generated
    # docstring carries no trailing whitespace (PEP 257 / black convention).
    out = [f'{indent}"""{fn.name}.\n', "\n"]
    if params:
        out.append(f"{indent}Args:\n")
        out.extend(f"{indent}    {name}\n" for name in params)
        out.append("\n")
    out.append(f"{indent}Returns: {return_type}\n")
    out.append(f'{indent}"""\n')
    return out


def _documentable_target(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str],
) -> tuple[int, list[str]] | None:
    """``(insert_line_index, docstring_lines)`` for ``fn`` when it qualifies, or
    ``None`` to refuse it.

    Applies, in order: the public/undocumented/non-test gate
    (:func:`_is_public_undocumented`), the PROVABLE-return-type gate
    (:func:`_provable_return_type` — ``None`` ⇒ refuse, the critical gate), and
    a usable docstring insertion point (:func:`_body_insertion` from the shared
    docstring transform, which yields the line index + body indent and handles
    multi-line signatures)."""
    if not _is_public_undocumented(fn):
        return None
    return_type = _provable_return_type(fn)
    if return_type is None:
        return None  # critical gate: no provable return type -> land nothing
    spot = _body_insertion(fn, lines)
    if spot is None:
        return None
    insert_at, body_indent = spot
    # A single-line-body def (`def f(): return 1`) has no own-line body, so the
    # shared `_body_insertion` reports the HEADER text as the "indent" (e.g.
    # `def f(): `). Splicing a docstring with that prefix corrupts the line; the
    # batch self-validation then rejects the WHOLE module — silently dropping
    # every OTHER function's doc. A real body indent is pure whitespace, so refuse
    # a target whose computed indent is not (rare; documenting it is not worth the
    # lost-contributions risk).
    if not body_indent.isspace():
        return None
    return insert_at, _docstring_lines(fn, body_indent, return_type)


def _public_undocumented_count(tree: ast.AST) -> int:
    """How many public, undocumented, non-test functions ``tree`` still has — the
    self-validation counter (it must drop by exactly the number we documented)."""
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, _DEF) and _is_public_undocumented(node)
    )


def document_signatures(source: str) -> str | None:
    """Return ``source`` with a proven docstring added to every qualifying public
    function, or ``None`` when nothing qualifies (or the source does not parse).

    Splices each docstring as the function's first body statement, bottom-up so
    earlier line indices stay valid (mirroring the docstring transform). Self-
    validating: the result must re-parse AND the public-undocumented count must
    drop by exactly the number of functions documented — else the change is
    refused (returns ``None``). Pure AST → text; deterministic (source order)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None

    lines = source.splitlines(keepends=True)
    nodes = [n for n in ast.walk(tree) if isinstance(n, _DEF)]
    nodes.sort(key=lambda n: (n.lineno, n.col_offset))

    placements: list[tuple[int, list[str]]] = []
    for fn in nodes:
        target = _documentable_target(fn, lines)
        if target is not None:
            placements.append(target)
    if not placements:
        return None

    new_lines = list(lines)
    for insert_at, doc_lines in sorted(placements, key=lambda p: p[0], reverse=True):
        new_lines = new_lines[:insert_at] + doc_lines + new_lines[insert_at:]
    new_source = "".join(new_lines)

    try:
        new_tree = ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None
    if _public_undocumented_count(new_tree) != (
        _public_undocumented_count(tree) - len(placements)
    ):
        return None
    return new_source if new_source != source else None


def plan_document_signature(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the proven-docstring plan for one module, or an empty no-op plan.

    Documents every qualifying public function in ``module_rel`` (public name, no
    docstring, not ``test_*``, and a PROVABLE return type) via
    :func:`document_signatures`. The shared single-file-rewrite plumbing — refuse a
    test/fixture file, read the module, record the single rewrite with its original
    for rollback (or a no-op when nothing is provable) — is delegated to
    :func:`plan_source_rewrite`, the one source of truth for that shape."""
    return plan_source_rewrite(
        project_root, module_rel, "document-signature", document_signatures)


register_module_objective(
    "document-signature", plan_document_signature,
    operator="document_signature",
    description="document the public signature of functions in {rel}",
)
