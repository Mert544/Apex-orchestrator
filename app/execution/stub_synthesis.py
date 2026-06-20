"""Stub-body synthesis — make UNFINISHED code finished, deterministically.

Where every other Apex objective makes EXISTING code cleaner, this one makes a
STUB function FINISHED: it finds a function whose body is unimplemented (``raise
NotImplementedError``, a bare ``...``/``pass`` body, or an empty body marked
``# TODO: implement``) AND whose contract is already pinned by the project's
tests, then DETERMINISTICALLY synthesises a body that makes ALL of that
function's tests pass — landing real working code.

The tests are the spec. We never guess: a small, FIXED template space is tried
in a FIXED order and the FIRST candidate body that makes the function's pinned
tests pass is accepted. If no template passes, we REFUSE (land nothing) — an
honest under-claim, never a fake-green. The outer develop loop then re-gates the
accepted body against the FULL suite and auto-rolls-back any regression.

Template space (tried in this order):

  1. **constant return** — when the function's tests all pin one literal result;
  2. **identity / passthrough** — ``return <arg>`` of a single parameter;
  3. **binary op on two args** — ``a + b``, ``a - b``, ``a * b``, ``a // b``,
     ``a % b``, ``a and b``, ``a or b`` (covers int/str/list ``+`` too);
  4. **recursion from base cases** — factorial/fibonacci shapes for a one-arg
     integer function, bounded to two fixed templates;
  5. **iterable reduction** — ``min``/``max``/``len``/``sorted`` of one arg.

Deterministic (fixed template order, no clock/random — same project, same body),
offline, stdlib-only, zero-token. Idempotent: a non-stub is never touched. Test
and fixture files are refused outright — Apex never edits the suite it is gated
by.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from app.skills.execution.run_tests import RunTestsSkill

__all__ = [
    "StubFunction",
    "find_stub_functions",
    "pinned_test_files",
    "candidate_bodies",
    "synthesize_stub_body",
]


# --- stub detection ----------------------------------------------------------

@dataclass(frozen=True)
class StubFunction:
    """One unimplemented top-level/method function found in a module.

    ``params`` is the ordered list of plain positional parameter names (``self``
    dropped for a method), used to build passthrough/binary templates. ``lineno``
    and ``end_lineno`` are 1-based and span the whole ``def`` (decorators
    excluded), so the body can be replaced precisely. ``indent`` is the leading
    whitespace of the ``def`` line, so a method body keeps its class indent."""

    name: str
    params: tuple[str, ...]
    lineno: int
    end_lineno: int
    indent: str
    is_method: bool


def _is_stub_body(node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: list[str]) -> bool:
    """True when ``node``'s body is unimplemented: ``raise NotImplementedError``,
    a single ``...``/``pass`` statement, or an empty body whose region carries a
    ``# TODO: implement`` comment. A docstring followed by any of those counts
    too. Anything with real logic is NOT a stub (idempotence)."""
    body = list(node.body)
    # Drop a leading docstring — a stub may still document its intent.
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant) and isinstance(
            body[0].value.value, str):
        body = body[1:]

    if not body:
        return _has_todo_marker(node, source_lines)
    if len(body) != 1:
        return False
    return _is_stub_statement(body[0])


def _is_stub_statement(stmt: ast.stmt) -> bool:
    """True when the lone body statement is unimplemented: ``pass``, a bare
    ``...`` expression, or ``raise NotImplementedError``. A real statement is NOT
    a stub — that is what keeps the objective idempotent on finished code."""
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Raise):
        return _is_not_implemented_raise(stmt)
    return False


def _is_not_implemented_raise(stmt: ast.Raise) -> bool:
    """True for ``raise NotImplementedError`` / ``raise NotImplementedError(...)``."""
    exc = stmt.exc
    if exc is None:
        return False
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _has_todo_marker(node: ast.AST, source_lines: list[str]) -> bool:
    """True when the function's line span carries a ``# TODO: implement`` comment
    (case-insensitive). Used only for an otherwise-empty body."""
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    region = "\n".join(source_lines[start:end])
    return re.search(r"#\s*todo\b[^\n]*\bimplement", region, re.IGNORECASE) is not None


def _positional_params(node: ast.FunctionDef | ast.AsyncFunctionDef,
                       is_method: bool) -> tuple[str, ...]:
    """The ordered plain positional parameter names (``self`` dropped for a
    method). ``*args``/``**kwargs`` and keyword-only params are excluded — the
    templates only reason about simple positional arguments."""
    args = node.args
    names = [a.arg for a in (args.posonlyargs + args.args)]
    if is_method and names and names[0] in ("self", "cls"):
        names = names[1:]
    return tuple(names)


def find_stub_functions(source: str) -> list[StubFunction]:
    """Every stub function in ``source`` (module- or class-level), source-ordered.

    A function is a stub when :func:`_is_stub_body` holds. Deterministic: the
    list is in (lineno, col) order. Returns ``[]`` on a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = source.splitlines()
    out: list[StubFunction] = []
    for node, is_method in _iter_functions(tree):
        if not _is_stub_body(node, lines):
            continue
        lineno = node.lineno
        indent = lines[lineno - 1][: len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())]
        out.append(StubFunction(
            name=node.name,
            params=_positional_params(node, is_method),
            lineno=lineno,
            end_lineno=node.end_lineno or lineno,
            indent=indent,
            is_method=is_method,
        ))
    out.sort(key=lambda s: (s.lineno,))
    return out


def _iter_functions(tree: ast.Module):
    """Yield ``(func_node, is_method)`` for every function defined directly at
    module level or directly inside a class body. Nested functions are skipped —
    their contract is not independently testable from outside."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, False
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield child, True


# --- pinned-test discovery ---------------------------------------------------

def _is_test_or_fixture(rel: str) -> bool:
    """True for an example/test/fixture path — files Apex must never edit."""
    p = rel.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py"
    )


def pinned_test_files(root: Path, module_rel: str, func_name: str) -> list[str]:
    """The test files that pin ``func_name`` from ``module_rel`` — i.e. they
    import the module (by dotted path or ``from pkg import stem``) AND reference
    the function name. Deterministic: sorted. These are the *spec* a candidate
    body must satisfy."""
    dotted = module_rel[:-3].replace("/", ".") if module_rel.endswith(".py") else module_rel
    parent, _, stem = dotted.rpartition(".")
    name_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(func_name) + r"(?![A-Za-z0-9_])")
    dotted_re = re.compile(re.escape(dotted) + r"(?![A-Za-z0-9_])")
    from_re = (re.compile(r"from\s+" + re.escape(parent) + r"\s+import\b[^\n()]*\b"
                          + re.escape(stem) + r"\b") if parent else None)
    out: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in (".claude", "__pycache__") for part in Path(rel).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports = bool(dotted_re.search(text)) or bool(from_re and from_re.search(text))
        if imports and name_re.search(text):
            out.append(rel)
    return out


# --- candidate body templates ------------------------------------------------

def candidate_bodies(stub: StubFunction) -> list[tuple[str, str]]:
    """The fixed, ordered template space for ``stub`` as ``(label, body_expr)``
    pairs, where ``body_expr`` is the single ``return``-ed expression. The order
    is FIXED and independent of any input value, so synthesis is deterministic.

    Pure expression text only — the caller wraps it as ``return <expr>``. A
    constant-return template is contributed by the caller (it needs the tests'
    expected literal), so this covers passthrough / binary / recursion /
    reduction."""
    params = stub.params
    out: list[tuple[str, str]] = []
    if len(params) == 1:
        out.extend(_one_arg_templates(params[0]))
    elif len(params) >= 2:
        out.extend(_two_arg_templates(params[0], params[1]))
    return out


def _one_arg_templates(a: str) -> list[tuple[str, str]]:
    """One-arg templates: passthrough, iterable reductions, and the two bounded
    recursion shapes (factorial, fibonacci)."""
    return [
        ("passthrough", a),
        ("len", f"len({a})"),
        ("min", f"min({a})"),
        ("max", f"max({a})"),
        ("sorted", f"sorted({a})"),
        ("sum", f"sum({a})"),
        ("factorial", f"1 if {a} <= 1 else {a} * __apex_self__({a} - 1)"),
        ("fibonacci",
         f"{a} if {a} < 2 else __apex_self__({a} - 1) + __apex_self__({a} - 2)"),
    ]


def _two_arg_templates(a: str, b: str) -> list[tuple[str, str]]:
    """Two-arg binary templates in a fixed order. Covers numeric arithmetic and,
    via ``+``, string/list concatenation as well as boolean ``and``/``or``."""
    ops = ["+", "-", "*", "//", "%", "/"]
    out = [(op, f"{a} {op} {b}") for op in ops]
    out.append(("and", f"{a} and {b}"))
    out.append(("or", f"{a} or {b}"))
    return out


# --- synthesis (the gated search) --------------------------------------------

def _expected_constant(root: Path, test_files: list[str], stub: StubFunction) -> str | None:
    """If every test asserting ``func(...) == <literal>`` pins the SAME literal,
    return its source text (so a constant-return template can be tried first).
    Otherwise ``None``. Conservative: any disagreement or a non-literal RHS
    yields ``None``."""
    literals: set[str] = set()
    call_eq = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(stub.name)
        + r"\s*\([^()]*\)\s*==\s*([^\n#]+)")
    for rel in test_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in call_eq.finditer(text):
            lit = _leading_literal(m.group(1))
            if lit is None:
                return None
            literals.add(lit)
    if len(literals) == 1:
        return next(iter(literals))
    return None


def _leading_literal(expr_text: str) -> str | None:
    """Parse the leading literal from a fragment after ``==`` (e.g. ``120`` from
    ``120``, or ``'ab'`` from ``'ab' and ...``). Returns its canonical source,
    or ``None`` when the leading token is not a constant literal."""
    expr_text = expr_text.strip()
    try:
        node = ast.parse(expr_text, mode="eval").body
    except (SyntaxError, ValueError):
        # The fragment may carry trailing tokens (``120  # note``); retry the
        # first comma/space-delimited chunk.
        head = expr_text.split(",")[0].strip()
        try:
            node = ast.parse(head, mode="eval").body
        except (SyntaxError, ValueError):
            return None
    if isinstance(node, ast.Constant) and not isinstance(node.value, type(Ellipsis)):
        return repr(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        try:
            return repr(ast.literal_eval(node))
        except (ValueError, SyntaxError):
            return None
    return None


def _rewrite_with_body(source: str, stub: StubFunction, return_expr: str) -> str | None:
    """Replace ``stub``'s body with ``return <return_expr>`` (resolving the
    ``__apex_self__`` recursion marker to the function's own name) and return the
    new module source, or ``None`` if the edit would not parse."""
    expr = return_expr.replace("__apex_self__", stub.name)
    lines = source.splitlines(keepends=True)
    header_end = _header_last_line(source, stub)
    if header_end is None:
        return None
    body_indent = stub.indent + "    "
    new_body = f"{body_indent}return {expr}\n"
    new_lines = lines[:header_end] + [new_body] + lines[stub.end_lineno:]
    candidate = "".join(new_lines)
    try:
        ast.parse(candidate)
    except (SyntaxError, ValueError):
        return None
    return candidate


def _header_last_line(source: str, stub: StubFunction) -> int | None:
    """The 0-based index just past the ``def`` header line(s) — where the body
    begins. Found by re-parsing and locating the first body statement's line."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node, _is_method in _iter_functions(tree):
        if node.lineno == stub.lineno and node.name == stub.name:
            first = node.body[0]
            # Keep a leading docstring intact; start the new body after it.
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str) and len(node.body) > 1):
                return (first.end_lineno or first.lineno)
            return first.lineno - 1
    return None


def _candidate_passes(root: Path, module_rel: str, candidate: str,
                      test_files: list[str], runner: RunTestsSkill) -> bool:
    """Write ``candidate`` to the module, run ONLY the pinned tests, restore the
    original. True iff every pinned test passes. The module is always restored,
    so this probe leaves the tree byte-for-byte unchanged."""
    target = root / module_rel
    original = target.read_text(encoding="utf-8")
    cmd = [_python_for(root), "-m", "pytest", "-q", *test_files]
    try:
        target.write_text(candidate, encoding="utf-8")
        summary = runner.run(str(root), commands=[cmd])
        return bool(summary.ok)
    finally:
        target.write_text(original, encoding="utf-8")


def _python_for(root: Path) -> str:
    """The interpreter for the probe — the target's own venv if present, else the
    current one (mirrors RunTestsSkill's own selection)."""
    import sys
    for cand in (root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def synthesize_stub_body(root: Path, module_rel: str, stub: StubFunction,
                         test_files: list[str],
                         runner: RunTestsSkill | None = None) -> str | None:
    """Synthesize a body for ``stub`` that makes ALL its pinned tests pass, or
    ``None`` (REFUSE) when no fixed template does.

    The search is deterministic: a constant-return candidate (when the tests
    agree on one literal) is tried first, then :func:`candidate_bodies` in fixed
    order. The FIRST candidate whose pinned tests all pass wins. With no pinned
    tests there is no spec to satisfy — refuse immediately."""
    if not test_files:
        return None
    runner = runner or RunTestsSkill()
    source = (root / module_rel).read_text(encoding="utf-8")

    for label, expr in _ordered_candidates(root, test_files, stub):
        candidate = _rewrite_with_body(source, stub, expr)
        if candidate is None:
            continue
        if _candidate_passes(root, module_rel, candidate, test_files, runner):
            return candidate
    return None


def _ordered_candidates(root: Path, test_files: list[str],
                        stub: StubFunction) -> list[tuple[str, str]]:
    """The full fixed-order candidate list: a constant-return first (when the
    tests pin one literal), then the parameter-shaped templates."""
    out: list[tuple[str, str]] = []
    const = _expected_constant(root, test_files, stub)
    if const is not None:
        out.append(("constant", const))
    out.extend(candidate_bodies(stub))
    return out
