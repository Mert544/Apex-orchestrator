"""Type-annotation transform — add PROVABLE type hints to unannotated functions.

Two surfaces live here:

  - :func:`apply` — the original, naive single-function ``-> None`` rewrite the
    semantic-patch generator drives (``add_type_annotations`` title). Its
    contract is unchanged: annotate the FIRST unannotated function's return as
    ``-> None``. Kept byte-for-byte so existing callers/tests are unaffected.

  - :func:`plan_type_annotations` — the develop-objective surface: a
    ``RenamePlan`` that annotates EVERY function in a module whose types are
    *provable from the AST*, never a guess. This is what the suite-gated
    ``apex develop --objective infer-type-hints`` campaign composes.

What counts as PROVABLE (the only things ever annotated):

  - **Return type** from the function's ``return`` statements when every return
    yields a literal of the SAME concrete type
    (``int``/``str``/``bool``/``float``/``list``/``dict``/``tuple``/``set``/
    ``bytes``), or ``-> None`` when the function has no value-returning ``return``
    and no ``yield`` (a pure procedure). Mixed return types, a non-literal
    return, a generator (``yield``), or an existing ``-> T`` are left alone.
  - **Parameter type** from a non-None literal DEFAULT (``def f(x=0)`` →
    ``x: int = 0``). A ``None`` default is ambiguous (the real type is
    ``Optional[...]``), so it is skipped. ``*args`` / ``**kwargs`` and any
    already-annotated parameter are skipped.

Never guesses: when a type is not provable from the AST the function (or that
one parameter) is left exactly as it was — an honest under-claim. Annotations
are behaviour-preserving: they add ``-> T`` / ``param: T`` text only, never
change runtime values. Deterministic: AST-only, no clock/random, a stable
left-to-right walk. Test/fixture files are refused by the plan layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

from ..result import SemanticPatchResult

__all__ = ["apply", "plan_type_annotations", "infer_annotations"]


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    lines = source.splitlines(keepends=True)
    modified = False

    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))) and (node.returns is None):
            lineno = node.lineno - 1
            line = lines[lineno]
            stripped = line.rstrip()
            if (stripped.endswith(":")) and ("->" not in stripped):
                new_line = stripped[:-1] + " -> None:\n"
                lines[lineno] = new_line
                modified = True
                break

    if not modified:
        return None

    new_content = "".join(lines)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="add_type_annotations",
        rationale=[f"Added missing return type annotation in {rel_path}."],
    )


# --- Provable inference (develop objective) ----------------------------------

# Concrete literal node -> the type name to annotate with. Only these
# unambiguous literal shapes are ever inferred.
def _literal_type(node: ast.expr) -> str | None:
    """The provable type NAME for a literal expression, or ``None`` if the
    expression's type is not provable from the AST alone.

    ``bool`` is checked before ``int`` because ``True``/``False`` are
    ``ast.Constant`` with a ``bool`` value (and ``bool`` is a subclass of
    ``int`` — we want the precise ``bool``)."""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        if isinstance(value, bytes):
            return "bytes"
        return None
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.Tuple):
        return "tuple"
    return None


def _own_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Every ``return`` that belongs to ``fn`` itself — descending into the body
    but NOT into a nested function/lambda, whose returns are their own."""
    out: list[ast.Return] = []

    def walk(body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # a nested function's returns are not ours
            if isinstance(stmt, ast.Return):
                out.append(stmt)
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    walk([child])
                elif isinstance(child, ast.excepthandler):
                    walk(child.body)

    walk(fn.body)
    return out


def _has_own_yield(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if ``fn`` itself is a generator — a ``yield``/``yield from`` that
    belongs to it, not to a nested function/lambda (whose yields are their own).
    A generator's runtime return is an iterator, so it must never be inferred."""
    found = False

    def walk(node: ast.AST) -> None:
        nonlocal found
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # a nested scope's yields are not ours
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                found = True
                return
            walk(child)

    walk(fn)
    return found


def _infer_return_type(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The provable return type for ``fn``, or ``None`` if not provable.

    - A generator (own ``yield``) is never inferred (its return is an iterator).
    - ``-> None`` when there is no value return (``return`` with no value, or no
      return at all) — a pure procedure.
    - Otherwise every value return must be a literal of the SAME concrete type;
      a bare ``return`` mixed with value returns, or differing literal types, or
      any non-literal return, is ambiguous → ``None`` (skip)."""
    if fn.returns is not None:
        return None  # already annotated — never overwrite
    if _has_own_yield(fn):
        return None

    returns = _own_returns(fn)
    value_returns = [r for r in returns if r.value is not None]
    has_bare = any(r.value is None for r in returns)

    if not value_returns:
        # No value ever returned: a pure procedure returns None.
        return "None"

    if has_bare:
        # Mixes ``return`` (=> None) with ``return <expr>`` — ambiguous union.
        return None

    types: set[str] = set()
    for r in value_returns:
        t = _literal_type(r.value)  # r.value is not None here
        if t is None:
            return None  # a non-literal return — not provable
        types.add(t)
    if len(types) != 1:
        return None  # disagreeing literal types — ambiguous
    return next(iter(types))


def _annotatable_params(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, str]]:
    """``(arg, type_name)`` for each parameter whose type is PROVABLE from a
    non-None literal default. ``*args``/``**kwargs`` are excluded (their default
    cannot be expressed as a defaulted positional/kw arg). Already-annotated
    params are skipped. None defaults are ambiguous (Optional) and skipped."""
    args = fn.args
    out: list[tuple[ast.arg, str]] = []

    # Positional (posonly + normal) defaults align to the TAIL of the list.
    positional = args.posonlyargs + args.args
    pos_defaults = args.defaults
    if pos_defaults:
        offset = len(positional) - len(pos_defaults)
        for i, default in enumerate(pos_defaults):
            arg = positional[offset + i]
            if arg.annotation is not None:
                continue
            t = _literal_type(default)
            if t is None or t == "None":
                continue
            out.append((arg, t))

    # Keyword-only defaults align 1:1 with kwonlyargs (None entry = no default).
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is None or arg.annotation is not None:
            continue
        t = _literal_type(default)
        if t is None or t == "None":
            continue
        out.append((arg, t))

    return out


def _function_edits(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, source: str, line_starts: list[int]
) -> list[tuple[int, int, str]]:
    """The ``(start, end, text)`` splice edits for one function: a ``: T`` after
    each provably-typed defaulted param, and a `` -> T`` before the header colon
    when the return is provable. Offsets are absolute into ``source``."""
    edits: list[tuple[int, int, str]] = []
    for arg, type_name in _annotatable_params(fn):
        off = _end_offset(arg, line_starts)
        if off is not None:
            edits.append((off, off, f": {type_name}"))

    ret = _infer_return_type(fn)
    if ret is not None:
        colon = _header_colon_offset(fn, source, line_starts)
        if colon is not None:
            edits.append((colon, colon, f" -> {ret}"))
    return edits


def infer_annotations(source: str) -> str | None:
    """Return ``source`` with every provable annotation added, or ``None`` when
    nothing provable changes (or the source does not parse).

    Edits are applied by byte offset, right-to-left, so earlier offsets stay
    valid as later ones are spliced in. Pure AST → text; deterministic."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None

    func_nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    # Deterministic order (source order) — offsets are absolute so order only
    # affects which edits we collect, not their application.
    func_nodes.sort(key=lambda n: (n.lineno, n.col_offset))

    line_starts = _line_start_offsets(source.splitlines(keepends=True))
    edits: list[tuple[int, int, str]] = []
    for fn in func_nodes:
        edits.extend(_function_edits(fn, source, line_starts))

    if not edits:
        return None

    # Apply right-to-left so offsets stay valid.
    edits.sort(key=lambda e: e[0], reverse=True)
    out = source
    for start, end, text in edits:
        out = out[:start] + text + out[end:]

    if out == source:
        return None
    # The result must still parse — a defensive guard; provable edits always do.
    try:
        ast.parse(out)
    except (SyntaxError, ValueError):
        return None
    return out


def _line_start_offsets(lines: list[str]) -> list[int]:
    """Absolute byte offset where each 1-based line begins (index 0 unused)."""
    offsets = [0, 0]
    acc = 0
    for line in lines:
        acc += len(line)
        offsets.append(acc)
    return offsets


def _abs_offset(lineno: int, col: int, line_starts: list[int]) -> int | None:
    if 0 < lineno < len(line_starts):
        return line_starts[lineno] + col
    return None


def _end_offset(node: ast.AST, line_starts: list[int]) -> int | None:
    """Absolute offset just past ``node`` (uses end_lineno/end_col_offset)."""
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if end_lineno is None or end_col is None:
        return None
    return _abs_offset(end_lineno, end_col, line_starts)


def _header_scan_start(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, line_starts: list[int]
) -> int | None:
    """Where to begin scanning for the header ``:`` — just past the LAST
    parameter (so the first top-level colon is the header's), or, with no
    parameters, the function's own header position. (The *function* node's end
    is the body's end, which would find the wrong colon.)"""
    args = fn.args
    anchor: ast.AST | None = (
        args.kwarg
        or (args.kwonlyargs[-1] if args.kwonlyargs else None)
        or args.vararg
        or (args.args[-1] if args.args else None)
        or (args.posonlyargs[-1] if args.posonlyargs else None)
    )
    start = _end_offset(anchor, line_starts) if anchor is not None else None
    if start is None:
        start = _abs_offset(fn.lineno, fn.col_offset, line_starts)
    return start


def _scan_top_level_colon(source: str, start: int) -> int | None:
    """Offset of the first ``:`` at bracket-depth 0 from ``start``, skipping
    string literals and ``#`` comments. None if none is found."""
    depth = 0
    i = start
    n = len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "#":
            nl = source.find("\n", i)
            if nl == -1:
                return None
            i = nl
            continue
        elif ch == ":" and depth <= 0:
            return i
        i += 1
    return None


def _header_colon_offset(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, source: str, line_starts: list[int]
) -> int | None:
    """Offset of the ``:`` that ends the def header (where ``-> T`` is inserted).

    Scans from just past the parameter list and returns the first top-level
    ``:``; ``-> T`` is then spliced immediately before that colon."""
    start = _header_scan_start(fn, line_starts)
    if start is None:
        return None
    return _scan_top_level_colon(source, start)


# --- Develop-objective plan --------------------------------------------------

def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (mirrors the existing 'would edit a test/fixture file' block). A
    local copy on purpose: this transform stays a self-contained module."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_") or Path(p).name.endswith("_test.py")
        or Path(p).name == "conftest.py"
    )


def plan_type_annotations(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the provable-type-hint plan for one module, or an empty no-op plan.

    Annotates every function in ``module_rel`` whose return and/or defaulted
    parameters are provable from the AST. Test/fixture files are refused (empty
    plan). An empty plan means nothing provable to add — a no-op, not a failure.
    The single write goes in ``new_contents`` with the original in ``originals``
    so the verified-apply engine can roll it back if the suite fails."""
    plan = RenamePlan(old=module_rel, new="infer-type-hints")

    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    path = Path(project_root) / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    new_source = infer_annotations(source)
    if new_source is None or new_source == source:
        return plan  # nothing provable to add — no-op

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = 1
    return plan
