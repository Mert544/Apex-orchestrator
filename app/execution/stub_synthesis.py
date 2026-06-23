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

  1. **identity / passthrough** — ``return <arg>`` of a single parameter;
  2. **binary op on two args** — ``a + b``, ``a - b``, ``a * b``, ``a // b``,
     ``a % b``, ``a and b``, ``a or b`` (covers int/str/list ``+`` too);
  3. **recursion from base cases** — factorial/fibonacci shapes for a one-arg
     integer function, bounded to two fixed templates;
  4. **iterable reduction** — ``min``/``max``/``len``/``sorted`` of one arg;
  5. **constant return** (LAST RESORT) — only when the tests all pin ONE literal
     result AND that literal is witnessed by >=2 distinct argument tuples (or the
     function takes no args). Tried last so a parameter-shaped body that also
     passes wins over a bare literal — a single pinned example must NOT overfit
     to ``return <literal>``.

Deterministic (fixed template order, no clock/random — same project, same body),
offline, stdlib-only, zero-token. Idempotent: a non-stub is never touched. Test
and fixture files are refused outright — Apex never edits the suite it is gated
by.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.skills.execution.run_tests import RunTestsSkill

__all__ = [
    "StubFunction",
    "find_stub_functions",
    "pinned_test_files",
    "pinned_test_nodes",
    "candidate_bodies",
    "ordered_candidate_exprs",
    "synthesize_expr_from_witnesses",
    "can_fill_stub_in_process",
    "module_has_fillable_stub",
    "fill_stub_body",
    "synthesize_stub_body",
    "AmbiguityDiagnosis",
    "ambiguity_reason",
    "render_ambiguity_reason",
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
    body must satisfy.

    Import-linkage is matched against EVERY importable dotted path for the module:
    the raw path-joined one AND each source-root-stripped one
    (:func:`_module_dotted_paths`). On a ``src/`` (or pyproject-declared) layout a
    test importing ``mylib.calc`` reaches ``src/mylib/calc.py`` — the naive
    ``src.mylib.calc`` would never match, so the stub would silently never land.
    The raw path stays in the candidate set, so a non-src project is byte-identical
    to before."""
    name_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(func_name) + r"(?![A-Za-z0-9_])")
    matchers = _import_matchers(root, module_rel)
    out: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in (".claude", "__pycache__") for part in Path(rel).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports = any(dotted_re.search(text)
                      or (from_re and from_re.search(text))
                      for dotted_re, from_re in matchers)
        if imports and name_re.search(text):
            out.append(rel)
    return out


def _module_dotted_paths(root: Path, module_rel: str) -> list[str]:
    """Every importable dotted path for ``module_rel``, deterministic and sorted:
    the raw path-joined one (``src.mylib.calc``) AND each source-root-stripped one
    (``mylib.calc``, when a leading ``src/`` or pyproject-declared root is peeled).

    Deterministic, stdlib-only. The source roots come from
    :func:`app.engine.mutation_tester._source_roots` (the same ``src/`` + pyproject
    detection ``covering_test_files`` uses) so impact-scoping and stub-synthesis
    agree on what a module's importable name is."""
    from app.engine.mutation_tester import _source_roots

    posix = module_rel.replace("\\", "/")
    raw = posix[:-3].replace("/", ".") if posix.endswith(".py") else posix
    paths = {raw}
    for source_root in _source_roots(root):
        prefix = source_root + "/"
        if posix.startswith(prefix):
            stripped = posix[len(prefix):]
            paths.add(stripped[:-3].replace("/", ".") if stripped.endswith(".py")
                      else stripped)
    return sorted(paths)


def _import_matchers(root: Path, module_rel: str):
    """One ``(dotted_re, from_re)`` pair per importable dotted path of the module
    (:func:`_module_dotted_paths`). ``dotted_re`` matches a direct ``import
    pkg.mod`` / dotted reference; ``from_re`` matches ``from pkg import mod`` (only
    when the path has a parent package). Both reuse the original linkage shape,
    just applied to every acceptable dotted path so a ``src/``-layout import is no
    longer missed. Deterministic (the dotted paths are sorted)."""
    matchers = []
    for dotted in _module_dotted_paths(root, module_rel):
        parent, _, stem = dotted.rpartition(".")
        dotted_re = re.compile(re.escape(dotted) + r"(?![A-Za-z0-9_])")
        from_re = (re.compile(r"from\s+" + re.escape(parent) + r"\s+import\b[^\n()]*\b"
                              + re.escape(stem) + r"\b") if parent else None)
        matchers.append((dotted_re, from_re))
    return matchers


def pinned_test_nodes(root: Path, module_rel: str, func_name: str) -> list[str]:
    """The pytest NODE IDs that pin ``func_name`` from ``module_rel`` — i.e. the
    ``tests/test_x.py::test_y`` items, at FUNCTION granularity, of the tests that
    name the symbol. Returns whole-FILE paths as a fallback for any pinned file
    whose node-ID discovery finds nothing (so nothing that used to land via the
    whole-file gate stops landing).

    This is the Blocker-2 fix: a shared test file ``tests/test_mathutils.py`` may
    pin several sibling stubs (``add``, ``scale``, ``running_total``). Gating a
    candidate ``add`` body against the whole FILE re-runs ``test_running_total``
    too — and if ``running_total`` is unsynthesizable, the file stays RED and
    ``add`` is refused even though its OWN node (``::test_add``) passes. Gating
    against the per-symbol node IDs lets ``add`` land on its own tests while the
    unsynthesizable sibling's red node is simply not in ``add``'s gate (it was
    never going to pass — pre-existing, not caused by the fill; never-fake-green
    holds because each landed stub is still gated against its OWN real tests).

    A node is selected when its ``def test_*`` function body/decorators REFERENCE
    ``func_name`` by name — the same import-linkage + name-reference shape
    :func:`pinned_test_files` uses, applied at function granularity. Deterministic:
    files sorted, then functions in source order; AST-based, stdlib-only."""
    name_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(func_name) + r"(?![A-Za-z0-9_])")
    out: list[str] = []
    for rel in pinned_test_files(root, module_rel, func_name):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        nodes = _test_nodes_referencing(text, rel, name_re)
        out.extend(nodes if nodes else [rel])  # fallback: whole file when none found
    return out


def _test_nodes_referencing(text: str, rel: str,
                            name_re: re.Pattern[str]) -> list[str]:
    """The ``rel::test_name`` node IDs of every top-level ``def test_*`` in ``text``
    whose source segment references the stub's symbol, DIRECTLY or via one level of
    indirection. Deterministic: source order. ``[]`` on a syntax error (the caller
    then falls back to the whole file, so a parse hiccup never drops a contract).

    A ``test_*`` is selected when:

    * (a) its source segment references the symbol by name (current behavior —
      also catches a ``@pytest.mark.parametrize`` test whose body is
      ``assert symbol(n) == expected``, since ``symbol`` is literally in the body),
      OR
    * (c) its body CALLS a MODULE-LOCAL helper — a top-level ``def`` in the same
      file that does NOT start with ``test`` — whose own body references the
      symbol. This is the indirect-pinning fix: ``test_add_indirect`` whose body is
      ``_check_add(2, 3, 5)`` pins ``add`` through ``_check_add``, so its node
      (``::test_add_indirect``) must be in ``add``'s gate — otherwise discovery
      finds nothing, the gate falls back to the whole FILE, and an unsynthesizable
      sibling re-vetoes the landable stub. One level only (we never recurse into a
      helper's own helper calls). AST-based, stdlib-only."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    helpers = _helpers_referencing(tree, text, name_re)
    out: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        seg = ast.get_source_segment(text, node) or ""
        if name_re.search(seg) or _calls_any_helper(node, helpers):
            out.append(f"{rel}::{node.name}")
    return out


def _helpers_referencing(tree: ast.Module, text: str,
                         name_re: re.Pattern[str]) -> set[str]:
    """The names of top-level ``def``s in ``tree`` that are NOT tests (their name
    does not start with ``test``) and whose source segment references the symbol
    (``name_re``). These are the module-local helpers a ``test_*`` may call to pin
    the symbol one level indirectly. Deterministic; a parse-less, purely structural
    scan over the module body."""
    helpers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("test"):
            continue
        seg = ast.get_source_segment(text, node) or ""
        if name_re.search(seg):
            helpers.add(node.name)
    return helpers


def _calls_any_helper(node: ast.AST, helpers: set[str]) -> bool:
    """True when ``node``'s body contains a direct call to any name in ``helpers``
    (``_check_add(...)``). Only a bare-``Name`` callee counts — a one-level
    module-local helper invocation — so we never chase attribute calls or recurse.
    ``helpers`` empty short-circuits to ``False``."""
    if not helpers:
        return False
    for child in ast.walk(node):
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id in helpers):
            return True
    return False


# --- candidate body templates ------------------------------------------------

def candidate_bodies(stub: StubFunction,
                     witnesses: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """The fixed, ordered template space for ``stub`` as ``(label, body_expr)``
    pairs, where ``body_expr`` is the single ``return``-ed expression. The order
    is FIXED and independent of any input value, so synthesis is deterministic.

    Pure expression text only — the caller wraps it as ``return <expr>``. A
    constant-return template is contributed by the caller as a LAST resort (it
    needs the tests' expected literal), so this covers passthrough / scalar
    arithmetic / string / comparison / binary / recursion / reduction — the
    parameter-shaped templates that take priority.

    ``witnesses`` are the ``(args_text, expected_text)`` pairs parsed from the
    pinned tests; they only let value-dependent templates PROPOSE a constant ``k``
    (``n * k``, ``s.replace(a, b)``). Inference never decides acceptance — a
    proposed body is still gated against ALL pinned tests by the caller, so a
    wrong ``k`` is rejected, never landed (never-fake-green). With no witnesses,
    only the value-free templates are offered."""
    params = stub.params
    out: list[tuple[str, str]] = []
    if len(params) == 1:
        out.extend(_one_arg_templates(params[0], witnesses or []))
    elif len(params) >= 2:
        out.extend(_two_arg_templates(params[0], params[1], witnesses or []))
    return out


def _one_arg_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One-arg templates in FIXED order: scalar arithmetic on one arg with an
    inferred constant, parity/comparison-to-constant, abs/round, string-method
    chains, iterable reductions, and the two bounded recursion shapes. Recursion
    is LAST among the value-free shapes so a simpler parameter body wins first.

    Value-dependent shapes (``n * k`` etc., ``s.replace(a, b)``) only appear when
    a constant is inferable from ``witnesses``; the inference merely PROPOSES the
    body, which the caller still gates against every pinned test.

    Templates whose shape cannot possibly match the witnesses' ARGUMENT type are
    pruned (string methods are skipped for an int argument; scalar arithmetic and
    recursion are skipped for a string argument), so the candidate list stays
    small and the gate runs few probes. With no witnesses (the pure structural
    view) every shape is offered."""
    kind = _arg_kind(witnesses)
    out: list[tuple[str, str]] = [("passthrough", a)]
    if kind in (None, "int", "float", "iterable"):
        out.extend(_scalar_arith_templates(a, witnesses))
        out.extend(_parity_compare_templates(a, witnesses))
        out.extend([
            ("abs", f"abs({a})"),
            ("round", f"round({a})"),
        ])
        out.extend(_round_ndigits_templates(a, witnesses))
    out.append(("len", f"len({a})"))
    if kind in (None, "str"):
        out.extend(_string_templates(a, witnesses))
    if kind in (None, "iterable"):
        out.extend([
            ("min", f"min({a})"),
            ("max", f"max({a})"),
            ("sorted", f"sorted({a})"),
            ("sum", f"sum({a})"),
            ("mean", f"sum({a}) / len({a})"),
        ])
        out.extend(_reduction_join_templates(a, witnesses))
    out.extend(_affine_string_templates(a, witnesses))
    out.extend(_constant_index_templates(a, witnesses))
    out.extend(_slice_templates(a, witnesses))
    out.extend(_index_templates(a, witnesses))
    out.extend(_one_arg_builtin_templates(a, kind, witnesses))
    if kind in (None, "int") and _recursion_allowed(witnesses):
        out.extend([
            ("factorial", f"1 if {a} <= 1 else {a} * __apex_self__({a} - 1)"),
            ("fibonacci",
             f"{a} if {a} < 2 else __apex_self__({a} - 1) + __apex_self__({a} - 2)"),
        ])
    return out


def _arg_kind(witnesses: list[tuple[str, str]]) -> str | None:
    """The single argument's type across the witnesses — ``"int"`` / ``"float"`` /
    ``"str"`` / ``"iterable"`` — or ``None`` when there are no witnesses or the
    type is mixed/unknown (then every template is offered and the gate decides).
    Used only to prune impossible templates, never to accept one."""
    if not witnesses:
        return None
    kinds: set[str] = set()
    for args_text, _expected in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 1:
            return None
        kinds.add(_value_kind(value[0]))
    return next(iter(kinds)) if len(kinds) == 1 else None


def _value_kind(value: object) -> str:
    """Classify a literal argument value into a template-shape bucket."""
    if isinstance(value, bool):
        return "int"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return "iterable"
    return "other"


def _recursion_allowed(witnesses: list[tuple[str, str]]) -> bool:
    """True when the recursion shapes (factorial/fibonacci) may be OFFERED — only
    once at least TWO DISTINCT argument tuples witness the contract, the same
    overfit floor the constant template uses. A single witness (``double(3) == 6``)
    must NOT be allowed to land a factorial body, so with <2 distinct tuples
    recursion is withheld. With NO witness list at all (the pure structural view
    used by callers that gate elsewhere) the shapes are still offered."""
    if not witnesses:
        return True
    distinct = {args for args, _expected in witnesses}
    return len(distinct) >= 2


def _scalar_arith_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Scalar arithmetic on one arg. The witness-DERIVED shapes (``n * k`` /
    ``n + k`` / ``n - k`` / ``n // k`` / ``n % k`` for each constant ``k`` inferred
    from the witnesses) come FIRST; the value-free ``n * 2`` / ``n + n`` come
    AFTER. The order matters: when both an intent-shaped derived body and a
    value-free body fit the thin witnesses, the witness-derived one must win
    (``triple(2)==6,triple(5)==15`` lands ``n * 3``, not a coincidental
    value-free shape). Constants are tried in fixed (sorted) order so synthesis
    stays deterministic; the ambiguity guard still refuses if two DIFFERENT
    shapes both fit."""
    out: list[tuple[str, str]] = []
    for k in _numeric_constants(witnesses):
        out.append((f"n*{k}", f"{a} * {k}"))
        out.append((f"n+{k}", f"{a} + {k}"))
        out.append((f"n-{k}", f"{a} - {k}"))
        out.append((f"n//{k}", f"{a} // {k}"))
        out.append((f"n%{k}", f"{a} % {k}"))
    out.append(("n*2", f"{a} * 2"))
    out.append(("n+n", f"{a} + {a}"))
    return out


def _round_ndigits_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The witness-DERIVED ``round(n, k)`` shapes — one per small ``ndigits`` constant
    ``k`` written in the witnesses — offered AFTER the value-free ``round(n)`` so a
    plain round wins when both fit. A non-zero ``k`` rounds to ``k`` decimals
    (``round(3.14159, 2) == 3.14``), a shape a bare ``round`` can never produce, so
    it only lands on a contract whose expected values actually carry that precision.

    OVERFIT FLOOR + the ``%d`` float-truncation lesson: ``round(n, k)`` bakes the
    witness's own ``k`` into the body, so it is offered ONLY when at least TWO
    DISTINCT argument tuples witness the contract (:func:`_string_floor_met`) — one
    example (``r(3.14159) == 3.14``) could pin an arbitrary ``k`` that is wrong for
    the next input. The accept-gate's TYPE-EXACT comparison is the divergence
    guard the ``%d`` class taught us: ``round(2, 2)`` is ``2`` (``int``) while a
    truncating intent might expect ``2.0`` (``float``), and ``round`` of a non-float
    that the witnesses don't support is simply rejected — never a fake-green. With
    NO witnesses (the structural view) the shapes are withheld (no ``k`` to derive);
    a lone ``round(n)`` already covers the value-free case. Deterministic: ``k`` in
    sorted order."""
    if not _string_floor_met(witnesses):
        return []
    out: list[tuple[str, str]] = []
    for k in _round_ndigits_constants(witnesses):
        out.append((f"round({k})", f"round({a}, {k})"))
    return out


def _round_ndigits_constants(witnesses: list[tuple[str, str]]) -> list[str]:
    """The small positive ``ndigits`` constants to try in ``round(n, k)``, mined from
    the number of fractional digits in each witnessed EXPECTED float (``3.14`` -> 2)
    and any small int literal present. Deterministic: sorted, de-duplicated, capped to
    a sane precision so the candidate list stays tiny. ``k == 0`` is excluded — that
    is the value-free ``round(n)`` already offered earlier."""
    seen: set[int] = set()
    for _args, expected in witnesses:
        seen.update(_fractional_digit_counts(expected))
        for value in _int_literals(expected):
            if 0 < value <= 10:
                seen.add(value)
    return [str(k) for k in sorted(k for k in seen if 0 < k <= 10)]


def _fractional_digit_counts(text: str) -> set[int]:
    """The count of fractional digits of every float literal in ``text`` (``'3.14'``
    -> ``{2}``, ``'1.5, 2.25'`` -> ``{1, 2}``). Used to propose a ``round`` ndigits.
    A non-float / non-parseable fragment yields ``set()``. Trailing zeros are counted
    as written (``'2.50'`` -> 2) since the literal's text is the author's precision."""
    out: set[int] = set()
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            frac = repr(node.value).partition(".")[2]
            if frac:
                out.add(len(frac))
    return out


def _parity_compare_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Boolean shapes on one arg. The witness-DERIVED comparison-to-constant
    shapes (``n == k``, ``n < k``, ``n <= k``, ``n > k``, ``n >= k`` for each
    ``k`` from the witnesses) come FIRST; the value-free parity (``n % 2 == 0`` /
    ``== 1``) comes AFTER. This is the DEFECT-2 reorder: a thin contract like
    ``is_big(5)==False,is_big(200)==True`` must prefer the intent-shaped ``n >= k``
    over the coincidental parity ``n % 2 == 0`` — and where BOTH still fit, the
    ambiguity guard refuses. A genuine parity contract (``is_even(2)==True,
    is_even(3)==False,is_even(4)==True``) pins no comparison ``k`` that fits, so
    parity remains the only match and still lands."""
    out: list[tuple[str, str]] = []
    for k in _numeric_constants(witnesses):
        out.append((f"n=={k}", f"{a} == {k}"))
        out.append((f"n<{k}", f"{a} < {k}"))
        out.append((f"n<={k}", f"{a} <= {k}"))
        out.append((f"n>{k}", f"{a} > {k}"))
        out.append((f"n>={k}", f"{a} >= {k}"))
    out.append(("even", f"{a} % 2 == 0"))
    out.append(("odd", f"{a} % 2 == 1"))
    return out


def _string_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """String-method shapes on one arg: the value-free chains (``s.lower()``,
    ``s.upper()``, ``s.strip()``, ``s.title()``, ``s.lower().strip()``) plus, for
    each ordered pair / single string constant inferable from the witnesses,
    ``s.replace(a, b)`` and ``s.split(sep)``. Constants come from the EXPECTED and
    ARGUMENT text of the witnesses so common slug/clean shapes are reachable.

    The value-free chains are ALWAYS offered — they carry no witness-derived
    literal, so a single example cannot overfit them (``shout_down('HELLO') ==
    'hello'`` honestly lands ``s.lower()``). The value-DERIVED ``replace(old, new)``
    / ``split(sep)`` shapes, by contrast, bake the witness's own string constants
    into the body, so one example degenerates to a literal map (``shout('hi') ==
    'HI!'`` would land ``text.replace('hi', 'HI!')`` — green on the one witness,
    wrong for any other input). They carry the SAME >=2-distinct-witness overfit
    floor the value-derived numeric constants use (:func:`_string_floor_met`): they
    are offered only when at least TWO DISTINCT argument tuples witness the
    contract, so a genuine transform with two discriminating examples still lands
    while a single example REFUSES. With NO witness list (the pure structural view)
    the shapes are still offered — that caller gates elsewhere."""
    out: list[tuple[str, str]] = [
        ("lower", f"{a}.lower()"),
        ("upper", f"{a}.upper()"),
        ("strip", f"{a}.strip()"),
        ("title", f"{a}.title()"),
        ("lower.strip", f"{a}.lower().strip()"),
    ]
    if not _string_floor_met(witnesses):
        return out  # single example — refuse the witness-derived replace/split
    strings = _string_constants(witnesses)
    for old, new in _ordered_string_pairs(strings):
        out.append((f"replace({old},{new})", f"{a}.replace({old}, {new})"))
        out.append((f"lower.replace({old},{new})",
                    f"{a}.lower().replace({old}, {new})"))
    for sep in strings:
        out.append((f"split({sep})", f"{a}.split({sep})"))
    out.extend(_str_predicate_templates(a, witnesses))
    return out


def _string_floor_met(witnesses: list[tuple[str, str]]) -> bool:
    """True when the witness-DERIVED string templates (``replace``/``split``) may
    be OFFERED — only once at least TWO DISTINCT argument tuples witness the
    contract, the same overfit floor the value-derived numeric constants use
    (:func:`_derived_constants`). A single witness (``shout('hi') == 'HI!'``) bakes
    its own literals into a ``replace`` body that is wrong for every other input,
    so with <2 distinct argument tuples the derived shapes are withheld (the
    value-free ``.lower()/.upper()/...`` chains in :func:`_string_templates` are
    unaffected — they carry no witness literal). With NO witness list at all (the
    pure structural view used by callers that gate elsewhere) the shapes are still
    offered. Deterministic."""
    if not witnesses:
        return True
    distinct = {args for args, _expected in witnesses}
    return len(distinct) >= 2


def _str_predicate_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg STRING-PREDICATE family: ``return a.startswith(k)`` /
    ``return a.endswith(k)`` for a string constant ``k`` mined from the witnesses,
    so a boolean prefix/suffix check is reachable. ``is_http('http://x') == True,
    is_http('ftp://y') == False`` lands ``s.startswith('http')`` — the witnessed
    prefix that reproduces every expected bool.

    Mirrors the witness-derived string-method discipline of ``replace``/``split``
    in :func:`_string_templates`: ``k`` is mined (:func:`_str_prefix_constant` /
    :func:`_str_suffix_constant`) from the witnessed strings whose expected bool is
    ``True`` (their common prefix / suffix), then VERIFIED to reproduce EVERY
    witness's expected bool before being emitted — the caller still gates it
    against all pinned tests, never-fake-green.

    SOUNDNESS: the body returns a ``bool`` (no domain/raise issues — ``str``
    arguments are guaranteed by the str-only family this lives in). The contract
    must DISCRIMINATE — at least one witness expecting ``True`` AND one expecting
    ``False`` (:func:`_discriminating_str_predicate_witnesses`); an all-``True`` /
    all-``False`` contract collapses to a constant the constant-last fallback owns,
    so this family refuses it rather than baking a coincidental ``k`` that another
    family should answer.

    OVERFIT FLOOR: offered ONLY when at least TWO DISTINCT argument tuples witness
    the contract (:func:`_string_floor_met`, the same floor the witness-derived
    ``replace``/``split`` shapes use). A single witness cannot discriminate at all
    (it pins one bool), so with <2 distinct tuples no predicate is derived. With NO
    witness list (the structural view) nothing is mined — there is no expected bool
    to verify against. The existing type-exact accept-gate and off-witness str
    canary probes (:func:`_str_canary_probes`) stay the sole ambiguity arbiters.
    Deterministic: a fixed (startswith-then-endswith) order, at most one ``k`` each."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _discriminating_str_predicate_witnesses(witnesses)
    if pairs is None:
        return []
    out: list[tuple[str, str]] = []
    prefix = _str_prefix_constant(pairs)
    if prefix is not None:
        out.append((f"startswith({prefix!r})", f"{a}.startswith({prefix!r})"))
    suffix = _str_suffix_constant(pairs)
    if suffix is not None:
        out.append((f"endswith({suffix!r})", f"{a}.endswith({suffix!r})"))
    return out


def _discriminating_str_predicate_witnesses(
    witnesses: list[tuple[str, str]],
) -> list[tuple[str, bool]] | None:
    """The ``(str_arg, expected_bool)`` pairs for the string-predicate miner, or
    ``None`` when the family cannot be mined. Every witness must be ONE LITERAL
    ``str`` argument with a LITERAL ``bool`` expected value (a ``bool`` is
    type-distinct from ``int`` — a ``startswith`` result is always a ``bool``), and
    the contract must DISCRIMINATE: at least one ``True`` AND one ``False`` expected
    (else the predicate collapses to a constant another family owns). A non-literal,
    multi-arg, non-``str``-argument, or non-``bool``-expected shape yields ``None`` —
    never guessed. Deterministic: source order."""
    out: list[tuple[str, bool]] = []
    saw_true = saw_false = False
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or not isinstance(value[0], str):
            return None
        if type(expected) is not bool:
            return None
        out.append((value[0], expected))
        saw_true = saw_true or expected
        saw_false = saw_false or not expected
    if not (out and saw_true and saw_false):
        return None
    return out


def _str_prefix_constant(pairs: list[tuple[str, bool]]) -> str | None:
    """The string constant ``k`` for ``a.startswith(k)``, or ``None`` when no single
    ``k`` reproduces every witness's expected bool. ``k`` is the longest common
    PREFIX of the ``True``-expecting strings (the natural prefix a human checks); it
    is VERIFIED that ``s.startswith(k) == expected`` for EVERY pair before it is
    returned (an empty ``k`` — no shared prefix — would make ``startswith`` always
    ``True`` and so fail a ``False`` witness, refusing). Deterministic, total."""
    trues = [s for s, expected in pairs if expected]
    k = _longest_common_prefix(trues)
    if not k:
        return None
    return k if all(s.startswith(k) == expected for s, expected in pairs) else None


def _str_suffix_constant(pairs: list[tuple[str, bool]]) -> str | None:
    """The string constant ``k`` for ``a.endswith(k)``, or ``None`` when no single
    ``k`` reproduces every witness's expected bool. ``k`` is the longest common
    SUFFIX of the ``True``-expecting strings; it is VERIFIED that
    ``s.endswith(k) == expected`` for EVERY pair before it is returned (an empty
    ``k`` would make ``endswith`` always ``True`` and fail a ``False`` witness,
    refusing). Deterministic, total."""
    trues = [s for s, expected in pairs if expected]
    suffixes = [s[::-1] for s in trues]
    k = _longest_common_prefix(suffixes)[::-1]
    if not k:
        return None
    return k if all(s.endswith(k) == expected for s, expected in pairs) else None


def _longest_common_prefix(strings: list[str]) -> str:
    """The longest string that PREFIXES every member of ``strings`` (``""`` for an
    empty list or no shared prefix). Deterministic, total — a pure character scan."""
    if not strings:
        return ""
    shortest = min(strings, key=len)
    for i, ch in enumerate(shortest):
        if any(s[i] != ch for s in strings):
            return shortest[:i]
    return shortest


def _reduction_join_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg REDUCTION / JOIN family for an iterable arg, in FIXED order:
    the witness-DERIVED shapes that PIN intent FIRST, then the value-free shapes.

    Two derived shapes (each baking a witnessed literal, so each under the
    >=2-distinct-witness overfit floor):

    * ``sep.join(a)`` — for every string separator ``sep`` mined from the witnesses
      (:func:`_string_constants`, the same derivation ``replace``/``split`` use), so
      ``join_words(["a", "b"]) == "a b"`` reaches ``" ".join(words)``. Offered ONLY
      when the witnessed elements are strings (:func:`_join_arg_is_str_iterable`) —
      ``"".join`` of a non-str iterable always raises, so it could never land and
      must not bloat the gate;
    * ``max(a, default=k)`` / ``min(a, default=k)`` — where ``k`` is the EXPECTED
      value of a witness whose argument is the EMPTY collection
      (:func:`_empty_collection_defaults`): ``top([]) == 0`` pins ``default=0``. The
      floor demands the empty-collection witness PLUS a second distinct witness (a
      lone ``f([]) == 0`` cannot tell ``max(a, default=0)`` from a bare ``return 0``),
      so a single witness derives no default.

    Then the value-free joins (``"".join(a)``, ``" ".join(a)``) — pure, carrying no
    witness literal, gate-verified — offered AFTER the derived shapes (so a derived
    separator wins when both fit) and BEFORE the constant-last fallback. ``max(a)`` /
    ``min(a)`` are already offered just above in :func:`_one_arg_templates`, so they
    are not repeated here. Deterministic: separators / defaults in sorted order. With
    NO witnesses (the structural view) only the value-free joins are offered (no
    literal to derive)."""
    out: list[tuple[str, str]] = []
    if _string_floor_met(witnesses) and _join_arg_is_str_iterable(witnesses):
        for sep in _string_constants(witnesses):
            literal = ast.literal_eval(sep)
            if literal in ("", " "):
                continue  # value-free joins below already cover these
            out.append((f"join({sep})", f"{sep}.join({a})"))
    for default in _empty_collection_defaults(witnesses):
        out.append((f"max(default={default})", f"max({a}, default={default})"))
        out.append((f"min(default={default})", f"min({a}, default={default})"))
    if _join_arg_is_str_iterable(witnesses):
        out.append(("join('')", f"''.join({a})"))
        out.append(("join(' ')", f"' '.join({a})"))
    return out


def _join_arg_is_str_iterable(witnesses: list[tuple[str, str]]) -> bool:
    """True when the join shapes may be OFFERED for the single iterable arg: every
    LITERAL witnessed argument is a list/tuple whose elements are ALL strings (a
    ``str.join`` of a non-str element always raises, so such a shape could never
    land). An empty collection contributes no element evidence but does not veto
    (``join([]) == ""`` is a valid str-join). With NO witnesses (the structural
    view) the shapes are offered so the gate decides. A non-literal / non-sequence
    witness withholds them (we never guess the element type). Deterministic."""
    if not witnesses:
        return True
    saw_str_element = False
    for args_text, _expected in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 1:
            return False
        seq = value[0]
        if not isinstance(seq, (list, tuple)):
            return False
        for el in seq:
            if not isinstance(el, str):
                return False
            saw_str_element = True
    return saw_str_element


def _empty_collection_defaults(witnesses: list[tuple[str, str]]) -> list[str]:
    """The default constants ``k`` for ``max(a, default=k)`` / ``min(a, default=k)``,
    mined from any witness whose single argument is the EMPTY collection: its expected
    value IS the default a reduction returns on an empty iterable (``top([]) == 0`` →
    ``0``). Each default is the canonical ``repr`` source of that expected literal.

    OVERFIT FLOOR: a default is offered ONLY when the empty-collection witness is
    accompanied by at least one further DISTINCT witness (>=2 distinct argument
    tuples) — a lone ``f([]) == 0`` is indistinguishable from a bare ``return 0`` and
    must not pin a reduction shape. With <2 distinct witnesses, or no empty-collection
    witness, no default is derived (the plain ``max(a)`` / ``min(a)`` cover the
    non-empty case). Deterministic: sorted by repr, de-duplicated."""
    if not _string_floor_met(witnesses):
        return []
    seen: set[str] = set()
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 1:
            continue
        seq = value[0]
        if not isinstance(seq, (list, tuple, set, frozenset)) or len(seq) != 0:
            continue
        default = _literal_value(expected_text)
        if default is not _NO_LITERAL:
            seen.add(repr(default))
    return sorted(seen)


def _affine_string_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg AFFINE-STRING (f-string) family: ``return f"{p}{a}{s}"`` for a
    common literal PREFIX ``p`` and SUFFIX ``s`` mined from the witnesses whose
    EXPECTED value is a ``str`` and whose output is ``p + str(arg) + s`` (so the arg
    sits verbatim between a fixed prefix and suffix). ``label(3) == "item-3"`` lands
    ``f"item-{n}"``; ``greet("Bob") == "Hi Bob!"`` lands ``f"Hi {name}!"``.

    The body is the NATURAL one a human writes: an f-string ``{a}`` already
    stringifies, so an int arg (``f"item-{n}"``) and a str arg (``f"Hi {name}!"``)
    share the SAME body shape — no redundant ``str()`` wrapper is ever added. The
    mining merely checks ``output == p + str(arg) + s`` (the f-string's own
    stringification rule), so the verified body round-trips on every witness or is
    rejected by the type-exact accept-gate. The DEGENERATE empty-prefix/empty-suffix
    split is NOT emitted here: ``f"{a}"`` is pure stringification, identical to the
    long-standing value-free ``str(a)`` builtin, so re-offering it would only shadow
    that existing body and shift existing idea sets — a genuine affine shape always
    carries a non-empty prefix OR suffix.

    OVERFIT FLOOR: a prefix/suffix bakes witnessed literals into the body, so it is
    offered ONLY when at least TWO DISTINCT argument tuples witness the contract
    (:func:`_string_floor_met`) — a single ``label(3) == "item-3"`` cannot tell
    ``f"item-{n}"`` from a bare ``return "item-3"`` constant, so one witness derives
    NO affine body. With NO witness list (the pure structural view) nothing is
    offered — there is no expected text to mine a prefix/suffix from.

    AMBIGUITY / OFF-WITNESS CANARY: every (prefix, suffix) split CONSISTENT across
    ALL witnesses is offered as its own candidate, longest-prefix-first then
    deterministically tie-broken (:func:`_affine_splits`), and each is verified to
    reproduce every witness (:func:`_affine_split_holds`). A split that is only
    coincidental on one witness (``f("aa") == "aaa"`` admits ``f"a{x}"`` and
    ``f"{x}a"`` IN ISOLATION) cannot survive a second DISTINCT argument — a fixed
    literal "a" added to "bb" gives "abb"/"bba", never "bbb" — so the >=2-distinct
    floor itself dissolves a coincidental split before it is ever offered. Where a
    genuine affine split still competes with ANOTHER offered shape (e.g. the empty/
    empty case competes with passthrough / ``.lower()`` etc.), the EXISTING ambiguity
    guard evaluates each off-witness via :func:`_str_canary_probes` and REFUSES when
    they diverge, exactly like the min-vs-last-vs-len guards — the affine candidate
    rides the same canary mechanism, never a parallel one. A contract that pins
    exactly one split with no diverging rival still lands.

    LITERAL witnesses only: a non-literal argument / expected yields no usable split
    and is skipped (never guessed). Deterministic: splits in fixed order."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _affine_witness_pairs(witnesses)
    if pairs is None:
        return []
    out: list[tuple[str, str]] = []
    for prefix, suffix in _affine_splits(pairs):
        if not prefix and not suffix:
            continue  # f"{a}" is pure stringification (== str(a)), not an affine
            # shape — the value-free ``str(a)`` builtin already covers it, so emitting
            # it here would only shadow that long-standing body. The genuine affine
            # family always carries a non-empty prefix OR suffix literal.
        out.append((f"affine({prefix!r},{suffix!r})", _affine_fstring(a, prefix, suffix)))
    return out


def _affine_witness_pairs(witnesses: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    """The ``(str(arg), output)`` pairs for the affine miner: one per witness whose
    single LITERAL argument and LITERAL ``str`` expected value are recoverable, with
    the argument rendered through ``str`` exactly as an f-string ``{a}`` would. ``None``
    when ANY witness is not a single-literal-arg / literal-str-output shape (the family
    cannot be mined then — never guessed). An empty result (no qualifying witness) also
    yields ``None``. Deterministic: source order."""
    out: list[tuple[str, str]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 1:
            return None
        expected = _literal_value(expected_text)
        if expected is _NO_LITERAL or not isinstance(expected, str):
            return None
        out.append((str(value[0]), expected))
    return out or None


def _affine_splits(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Every ``(prefix, suffix)`` such that EVERY ``(mid, output)`` pair satisfies
    ``output == prefix + mid + suffix`` — the affine splits consistent across all
    witnesses. A split is admitted only when, in each output, the witnessed ``mid``
    occurs at the position implied by the prefix length AND the residual head/tail
    match the prefix/suffix exactly (so the arg sits verbatim in the middle).

    Enumerated from the FIRST witness's output by every start index where its ``mid``
    occurs, then VERIFIED against all witnesses; a candidate that fails any witness is
    dropped. Deterministic and total: longest-prefix-first, then by ``repr`` of
    ``(prefix, suffix)`` so ties break the same way every run."""
    first_mid, first_out = pairs[0]
    candidates: list[tuple[str, str]] = []
    start = first_out.find(first_mid)
    while start != -1:
        prefix = first_out[:start]
        suffix = first_out[start + len(first_mid):]
        if _affine_split_holds(prefix, suffix, pairs):
            candidates.append((prefix, suffix))
        start = first_out.find(first_mid, start + 1)
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda ps: (-len(ps[0]), repr(ps)))
    return candidates


def _affine_split_holds(prefix: str, suffix: str,
                        pairs: list[tuple[str, str]]) -> bool:
    """True when ``output == prefix + mid + suffix`` for EVERY ``(mid, output)`` pair —
    the verification that an affine split derived from one witness reproduces them all.
    A split that fails any witness is not affine for this contract."""
    return all(output == prefix + mid + suffix for mid, output in pairs)


def _affine_fstring(a: str, prefix: str, suffix: str) -> str:
    """The f-string body source ``f"{prefix}{a}{suffix}"`` with ``prefix``/``suffix``
    embedded SAFELY: the literal text is escaped for an f-string literal (``{`` -> ``{{``,
    ``}`` -> ``}}``) and the whole string is built from a ``repr``-derived double-quoted
    literal so quotes/backslashes/newlines round-trip exactly. The result evaluates and
    unparses identically on every witness or is rejected by the gate — never a fuzzy
    match. ``f"item-{n}"`` / ``f"Hi {name}!"`` come out as the natural human spelling."""
    return 'f"' + _fstring_inner(prefix) + "{" + a + "}" + _fstring_inner(suffix) + '"'


def _fstring_inner(text: str) -> str:
    """The literal TEXT of ``text`` rendered for the inside of a DOUBLE-QUOTED f-string:
    ``repr`` yields a safe quoted literal (escaping quotes/backslashes/control chars);
    its inner body is normalised to a double-quote context (a literal ``"`` escaped, a
    needless ``\\'`` un-escaped) and every literal brace is doubled (``{`` -> ``{{``)
    so the f-string parser reads it as text, not a replacement field. No surrounding
    quotes — the caller wraps the whole ``f"..."`` once. Empty text yields ``""``."""
    inner = repr(text)[1:-1]
    inner = inner.replace("\\'", "'").replace('"', '\\"')
    return inner.replace("{", "{{").replace("}", "}}")


def _constant_index_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg CONSTANT-INDEX family: ``return a[k]`` for each fixed integer index
    ``k`` mined from the witnesses. ``second([1, 2, 3]) == 2, second([5, 9, 1]) == 9``
    lands ``xs[1]`` — the position the expected value sits at in EVERY witnessed
    sequence. This fills the gap between the ``a[0]`` / ``a[-1]`` endpoint builtins
    (:func:`_one_arg_builtin_templates`) and the value-free reductions: a body for an
    arbitrary interior index that no other template can spell.

    Indices come from :func:`_constant_index_constants` — the TYPE-EXACT intersection
    of the (non-negative) positions where each witness's expected value occurs in that
    witness's own sequence literal, so the index reproduces every witness by
    construction (the caller still gates it against all pinned tests, never-fake-green).

    OVERFIT FLOOR: offered ONLY when at least TWO DISTINCT argument tuples witness the
    contract (:func:`_string_floor_met`, the same floor the witness-derived string /
    numeric / reduction shapes use). A single witness cannot tell ``xs[0]`` from a bare
    ``return 1`` (``first([1, 2, 3]) == 1`` fits both), so with <2 distinct tuples no
    index is derived. Index ``0`` is intentionally omitted — the ``a[0]`` ``first``
    builtin already covers it, and only an interior / non-zero index is NEW value (the
    ``a[-1]`` ``last`` builtin likewise covers the tail, so negative indices are not
    mined here). With NO witness list (the structural view) no index is derived — there
    is no literal to mine. Deterministic: indices in sorted order, de-duplicated."""
    out: list[tuple[str, str]] = []
    for idx in _constant_index_constants(witnesses):
        out.append((f"index[{idx}]", f"{a}[{idx}]"))
    return out


def _constant_index_constants(witnesses: list[tuple[str, str]]) -> list[int]:
    """The fixed integer indices ``k`` to try in ``a[k]``, mined as the TYPE-EXACT
    INTERSECTION of the non-negative positions where each witness's expected value sits
    in that witness's own sequence literal. ``second([1, 2, 3]) == 2`` contributes the
    positions ``{1}`` (only index 1 holds an ``int`` equal to ``2``); intersecting with
    ``second([5, 9, 1]) == 9``'s ``{1}`` yields ``[1]`` -> ``xs[1]``.

    Each witness must be a single SEQUENCE argument (``list`` / ``tuple`` / ``str``)
    with a LITERAL expected value; any witness that is not (a non-literal, multi-arg, or
    non-sequence shape) yields NO index — the family cannot be mined then, never guessed.
    A position counts only when the element's TYPE matches the expected value's type
    exactly (``1`` does not match ``True``), mirroring the accept-gate's type-exact
    comparison so a mined index can never imply a value the gate would reject.

    Index ``0`` is dropped from the result — the ``a[0]`` ``first`` builtin already
    spells it, so re-emitting it would only shadow that long-standing body; the genuine
    new value is an interior / non-zero index (``xs[1]``, ``xs[2]``). Negative positions
    are not mined (the ``a[-1]`` ``last`` builtin owns the tail). Gated behind the
    >=2-distinct-witness overfit floor (:func:`_string_floor_met`). Deterministic:
    sorted, de-duplicated; an empty / single / non-sequence witness set yields ``[]``."""
    if not _string_floor_met(witnesses):
        return []
    common: set[int] | None = None
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or expected is _NO_LITERAL:
            return []
        seq = value[0]
        if not isinstance(seq, (list, tuple, str)):
            return []
        positions = {
            i for i, el in enumerate(seq)
            if type(el) is type(expected) and el == expected
        }
        common = positions if common is None else (common & positions)
        if not common:
            return []
    return sorted(idx for idx in (common or set()) if idx != 0)


def _index_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg INDEX-METHOD family: ``return a.index(k)`` for each fixed element ``k``
    mined from the witnesses — the int POSITION at which the literal ``k`` FIRST occurs in
    the sequence. ``find_three([5, 3, 9]) == 1, find_three([3, 8]) == 0`` lands
    ``xs.index(3)`` — the place a known element sits, which is the INVERSE of the
    constant-index family (``a[k]`` returns the element AT position ``k``; ``a.index(k)``
    returns the POSITION of element ``k``), and a value no scalar / slice / reduction
    template can spell.

    Elements come from :func:`_index_method_constants` — the TYPE-EXACT intersection of the
    elements ``k`` whose ``seq.index(k)`` equals that witness's expected int across EVERY
    witness, so the body reproduces every witness by construction (the caller still gates it
    against all pinned tests, never-fake-green; ``.index`` raises ``ValueError`` when ``k``
    is absent, so a witness lacking ``k`` makes the candidate raise and the gate rejects it).

    OVERFIT FLOOR: offered ONLY when at least TWO DISTINCT argument tuples witness the
    contract (:func:`_string_floor_met`, the same floor the constant-index / slice / string
    / numeric shapes use). A single witness cannot tell ``xs.index(3)`` from a bare
    ``return 0`` (``find_three([3, 8]) == 0`` fits both), so with <2 distinct tuples no
    element is mined. With NO witness list (the structural view) nothing is mined — there is
    no literal to derive. Deterministic: elements in sorted order, de-duplicated. The
    existing type-exact accept-gate and off-witness sequence-canary probes stay the sole
    ambiguity arbiters."""
    out: list[tuple[str, str]] = []
    for k in _index_method_constants(witnesses):
        out.append((f"index({k!r})", f"{a}.index({k!r})"))
    return out


def _index_method_constants(witnesses: list[tuple[str, str]]) -> list[object]:
    """The fixed elements ``k`` to try in ``a.index(k)``, mined as the TYPE-EXACT
    INTERSECTION over the witnesses of the elements whose ``seq.index(k)`` equals that
    witness's expected int. ``find_three([5, 3, 9]) == 1`` contributes the element at
    position ``1`` whose first occurrence is ``1`` (``3``); intersecting with
    ``find_three([3, 8]) == 0``'s element at position ``0`` (``3``) yields ``[3]`` ->
    ``xs.index(3)``.

    Each witness must be a single SEQUENCE argument (``list`` / ``tuple`` / ``str``) with a
    LITERAL ``int`` expected value (the position ``.index`` returns is always an ``int``; a
    non-``int`` expected — or a ``bool``, which is type-distinct from ``int`` — can never be
    an ``.index`` result and refuses the whole family). The candidate element for a witness
    is ``seq[expected]``, but ONLY when its FIRST occurrence is exactly ``expected``
    (``seq.index(el) == expected``) — an earlier duplicate would make ``.index`` return a
    smaller position, so such an element is dropped rather than mined into a body the gate
    would reject. A position out of range, a non-literal, multi-arg, or non-sequence shape
    yields NO element — the family is mined, never guessed.

    The element's TYPE must match its sequence slot exactly (``True`` is not mined for a
    ``1`` slot), mirroring ``.index``'s ``==`` semantics so a mined element can never
    resolve to a different position than the witness pins. Gated behind the
    >=2-distinct-witness overfit floor (:func:`_string_floor_met`). Deterministic: sorted,
    de-duplicated; an empty / single / non-sequence / non-int-expected witness set yields
    ``[]``."""
    if not _string_floor_met(witnesses):
        return []
    common: set | None = None
    for args_text, expected_text in witnesses:
        element = _index_witness_element(args_text, expected_text)
        if element is _NO_LITERAL:
            return []
        candidates = {_Hashed(element)}
        common = candidates if common is None else (common & candidates)
        if not common:
            return []
    return sorted((h.value for h in (common or set())), key=repr)


def _index_witness_element(args_text: str, expected_text: str) -> object:
    """The single element ``k`` a witness supports for ``a.index(k)``, or the sentinel
    ``_NO_LITERAL`` when the witness cannot be mined. The witness must be one LITERAL
    SEQUENCE argument with a LITERAL ``int`` expected position in range; the element is
    ``seq[expected]`` and is accepted ONLY when its FIRST occurrence is exactly
    ``expected`` (``seq.index(element) == expected``), so an earlier duplicate — which
    would make ``.index`` return a smaller position — refuses rather than mines a body
    the gate would reject. ``bool`` is type-distinct from ``int`` (a position is always
    an ``int``)."""
    value = _literal_tuple(args_text)
    expected = _literal_value(expected_text)
    if value is None or len(value) != 1 or type(expected) is not int:
        return _NO_LITERAL
    seq = value[0]
    if not isinstance(seq, (list, tuple, str)) or not 0 <= expected < len(seq):
        return _NO_LITERAL
    element = seq[expected]
    return element if seq.index(element) == expected else _NO_LITERAL


@dataclass(frozen=True)
class _Hashed:
    """A hashable, TYPE-EXACT wrapper for a mined element so it can intersect across
    witnesses in a set even when the element is unhashable (a list ``str`` is hashable, but
    a list element could be a list) and so ``1`` never collides with ``True``. Equality is
    type-exact value equality; the hash falls back to the type when the value is unhashable
    so distinct types stay distinct buckets."""

    value: object

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, _Hashed)
                and type(self.value) is type(other.value)
                and self.value == other.value)

    def __hash__(self) -> int:
        try:
            return hash((type(self.value).__name__, self.value))
        except TypeError:
            return hash(type(self.value).__name__)


def _slice_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg SLICE family: ``return a[i:j]`` / ``a[:k]`` / ``a[k:]`` for fixed
    bounds mined from the witnesses. ``head([3, 1, 2, 4]) == [3, 1],
    head([5, 9, 1]) == [5, 9]`` lands ``xs[:2]`` — the prefix length that reproduces
    EVERY witnessed expected slice from that witness's own sequence literal. This
    spells a contiguous sub-sequence body (a prefix, a suffix, or an interior
    window) that no scalar index or reduction template can.

    Three sub-families, each TYPE-EXACT and reproducing every witness by construction
    (the caller still gates against all pinned tests, never-fake-green):

    * PREFIX ``a[:k]`` — :func:`_prefix_bounds`, the bounds ``k`` where ``seq[:k]``
      equals the expected slice for every witness;
    * SUFFIX ``a[k:]`` — :func:`_suffix_bounds`, the bounds ``k`` where ``seq[k:]``
      equals it (a suffix runs to each sequence's OWN end, so varying-length tails
      are reproduced by one ``k``);
    * CLOSED ``a[i:j]`` — :func:`_closed_bounds`, the finite ``(i, j)`` pairs where
      ``seq[i:j]`` equals it across every witness (an absolute ``j`` consistent for
      all).

    OVERFIT FLOOR: offered ONLY when at least TWO DISTINCT argument tuples witness
    the contract (:func:`_string_floor_met`, the same floor the constant-index /
    string / numeric shapes use). A single witness cannot tell ``xs[:2]`` from a
    bare constant (``head([3, 1, 2]) == [3, 1]`` fits both ``xs[:2]`` and a literal
    return), so with <2 distinct tuples no slice is mined. The identity slice
    ``a[:]`` and any EMPTY slice are dropped — passthrough already spells the whole
    sequence and an empty result needs no slice. With NO witness list (the
    structural view) nothing is mined. Deterministic: prefixes then suffixes then
    closed windows, each in sorted bound order, de-duplicated."""
    out: list[tuple[str, str]] = []
    for k in _prefix_bounds(witnesses):
        out.append((f"slice[:{k}]", f"{a}[:{k}]"))
    for k in _suffix_bounds(witnesses):
        out.append((f"slice[{k}:]", f"{a}[{k}:]"))
    for start, stop in _closed_bounds(witnesses):
        out.append((f"slice[{start}:{stop}]", f"{a}[{start}:{stop}]"))
    return out


def _slice_witness_seqs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[list | tuple | str, object]] | None:
    """The ``(sequence, expected)`` pairs to mine slice bounds from, or ``None`` when
    the family cannot be mined. Gated behind the >=2-distinct-witness overfit floor
    (:func:`_string_floor_met`). Every witness must be a single SEQUENCE argument
    (``list`` / ``tuple`` / ``str``) with a LITERAL expected value of the SAME type
    (a slice preserves its sequence's type, so a witness whose expected type differs
    can never be a slice and refuses the whole family). A non-literal, multi-arg, or
    non-sequence shape yields ``None`` — the family is mined, never guessed."""
    if not _string_floor_met(witnesses):
        return None
    pairs: list[tuple[list | tuple | str, object]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or expected is _NO_LITERAL:
            return None
        seq = value[0]
        if not isinstance(seq, (list, tuple, str)):
            return None
        if type(expected) is not type(seq):
            return None
        pairs.append((seq, expected))
    return pairs


def _prefix_bounds(witnesses: list[tuple[str, str]]) -> list[int]:
    """The bounds ``k`` for ``a[:k]`` (non-identity, non-empty prefixes), mined as the
    INTERSECTION over the witnesses of the lengths ``k`` where ``seq[:k]`` equals the
    expected slice. ``k`` ranges over ``1 .. len(seq) - 1`` per witness, so the empty
    prefix (``k == 0``) and the whole-sequence identity (``k >= len(seq)``, which
    passthrough already covers) are never mined. Deterministic: sorted, de-duplicated;
    a non-sequence / single / empty witness set yields ``[]``."""
    return _intersect_slice_bounds(witnesses, _prefix_positions)


def _suffix_bounds(witnesses: list[tuple[str, str]]) -> list[int]:
    """The bounds ``k`` for ``a[k:]`` (non-identity, non-empty suffixes), mined as the
    INTERSECTION over the witnesses of the starts ``k`` where ``seq[k:]`` equals the
    expected slice. ``k`` ranges over ``1 .. len(seq) - 1`` per witness, so the whole
    sequence (``k == 0``, passthrough's job) and the empty suffix (``k >= len(seq)``)
    are never mined; one ``k`` reproduces tails of DIFFERING length because ``k:`` runs
    to each sequence's own end. Deterministic: sorted, de-duplicated; ``[]`` for a
    non-sequence / single / empty witness set."""
    return _intersect_slice_bounds(witnesses, _suffix_positions)


def _closed_bounds(witnesses: list[tuple[str, str]]) -> list[tuple[int, int]]:
    """The finite ``(start, stop)`` pairs for ``a[start:stop]`` (non-identity,
    non-empty interior windows), mined as the INTERSECTION over the witnesses of the
    pairs where ``seq[start:stop]`` equals the expected slice. Both bounds are finite
    and ``0 <= start < stop <= len(seq)`` per witness, so empty windows are excluded;
    a pair is mined only when its ABSOLUTE ``stop`` reproduces every witness (the
    open-ended ``a[:k]`` / ``a[k:]`` families own the prefix / suffix shapes whose end
    or start floats per witness). Deterministic: sorted, de-duplicated; ``[]`` for a
    non-sequence / single / empty witness set."""
    return _intersect_slice_bounds(witnesses, _closed_positions)


def _intersect_slice_bounds(
    witnesses: list[tuple[str, str]],
    positions: Callable[[list | tuple | str, object], set],
) -> list:
    """Intersect a per-witness bound set across all witnesses, deterministically
    sorted. ``positions(seq, expected)`` returns the bounds that reproduce one
    witness (an empty set short-circuits to ``[]``); the result is their common
    intersection. Returns ``[]`` when the family cannot be mined
    (:func:`_slice_witness_seqs` -> ``None``)."""
    pairs = _slice_witness_seqs(witnesses)
    if pairs is None:
        return []
    common: set | None = None
    for seq, expected in pairs:
        bounds = positions(seq, expected)
        common = bounds if common is None else (common & bounds)
        if not common:
            return []
    return sorted(common or set())


def _prefix_positions(seq: list | tuple | str, expected: object) -> set[int]:
    """The lengths ``k`` in ``1 .. len(seq) - 1`` where ``seq[:k]`` reproduces
    ``expected`` (TYPE-EXACT — slicing preserves type, so the comparison is on equal
    types). Excludes ``k == 0`` (empty) and ``k == len(seq)`` (identity passthrough),
    and — for a ``str`` sequence — any length-1 prefix (:func:`_min_slice_len`: a
    single character is the index family's job, never a slice's)."""
    lo = _min_slice_len(seq)
    return {k for k in range(1, len(seq)) if k >= lo and seq[:k] == expected}


def _suffix_positions(seq: list | tuple | str, expected: object) -> set[int]:
    """The starts ``k`` in ``1 .. len(seq) - 1`` where ``seq[k:]`` reproduces
    ``expected``. Excludes ``k == 0`` (identity passthrough) and ``k == len(seq)``
    (empty), and — for a ``str`` sequence — any length-1 suffix (the suffix length is
    ``len(seq) - k``; :func:`_min_slice_len` keeps single-char tails for the index
    family)."""
    lo = _min_slice_len(seq)
    n = len(seq)
    return {k for k in range(1, n) if (n - k) >= lo and seq[k:] == expected}


def _closed_positions(
    seq: list | tuple | str, expected: object,
) -> set[tuple[int, int]]:
    """The finite ``(start, stop)`` pairs with ``0 <= start < stop <= len(seq)`` where
    ``seq[start:stop]`` reproduces ``expected``, EXCLUDING the prefixes (``start == 0``)
    and suffixes (``stop == len(seq)``) the open-ended families already own, the empty
    windows (``start == stop`` cannot occur since ``start < stop``), and — for a ``str``
    sequence — any length-1 window (``stop - start == 1``; :func:`_min_slice_len`)."""
    n = len(seq)
    lo = _min_slice_len(seq)
    return {
        (start, stop)
        for start in range(1, n)
        for stop in range(start + 1, n)
        if (stop - start) >= lo and seq[start:stop] == expected
    }


def _min_slice_len(seq: list | tuple | str) -> int:
    """The minimum RESULT length a mined slice may have for ``seq``: ``2`` for a
    ``str``, ``1`` otherwise. A length-1 ``str`` slice (``s[i:i+1]``) is value- AND
    type-identical to the character index ``s[i]`` on every non-empty input yet
    DIVERGES on the empty-string canary (the index raises, the slice yields ``''``),
    which would make the slice family compete with — and steal the contract from — the
    constant-index / endpoint families for what is really single-character extraction.
    Excluding length-1 str slices keeps that extraction the index family's domain (the
    #D family) and leaves the slice family to genuine multi-char sub-strings. A
    length-1 ``list``/``tuple`` slice returns a length-1 SEQUENCE, a different type
    from the element the index returns, so it never competes — those stay allowed."""
    return 2 if isinstance(seq, str) else 1


def _has_set_arg(witnesses: list[tuple[str, str]] | None) -> bool:
    """True when ANY witnessed single argument is a ``set``/``frozenset`` literal.
    ``list(a)``/``tuple(a)`` are withheld for such a witness because materializing
    an unordered collection of non-int elements is PYTHONHASHSEED-dependent — the
    same non-determinism that excludes ``set(a)``. A non-literal / multi-arg / no
    witness view returns ``False`` so the structural (gate-elsewhere) path keeps
    offering the shapes unchanged."""
    if not witnesses:
        return False
    for args_text, _expected in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 1:
            continue
        if isinstance(value[0], (set, frozenset)):
            return True
    return False


def _one_arg_builtin_templates(
    a: str,
    kind: str | None,
    witnesses: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Value-free one-arg builtin / unary-operator shapes, in FIXED source order,
    offered AFTER the witness-derived scalar/string/reduction templates and BEFORE
    the constant-last fallback. Each is a pure expression over the single parameter
    so the gate (or the in-process matcher) verifies it; a shape whose witness type
    cannot support it is pruned by ``kind`` and simply not offered (it never crashes
    — the matcher also swallows a stray ``TypeError`` for the unpruned ``None``
    view). The shapes:

    * ``-{a}`` (negation), ``int({a})`` — numeric coercions (int/float args);
    * ``{a}[0]`` / ``{a}[-1]`` (first/last), ``list({a})`` / ``tuple({a})`` — sequence
      projections (iterable / str args, where indexing and materialization are
      meaningful); ``tuple`` differs from ``list`` only in RESULT TYPE, which the
      type-exact accept-gate distinguishes, so the right one lands on its witnesses.
      ``list({a})`` / ``tuple({a})`` are WITHHELD when a witnessed argument is a
      ``set``/``frozenset``: materializing an unordered collection of non-int
      elements yields a PYTHONHASHSEED-dependent order, the same non-deterministic
      value oracle that already excludes ``set({a})`` — landing such a body would
      break the determinism invariant;
    * ``str({a})``, ``not {a}``, ``bool({a})`` — type-agnostic, offered for every
      kind (any value can be stringified or truth-tested). ``set({a})`` is
      deliberately NOT offered: a ``set`` return is hash-iteration-order-sensitive,
      so its value oracle is non-deterministic and the determinism invariant forbids
      landing it; an emptiness check ``len({a}) == 0`` is likewise omitted because the
      already-present ``not {a}`` is provably equivalent on every length-bearing arg.

    ``abs`` / ``len`` / ``sorted`` / ``sum`` already appear earlier in
    :func:`_one_arg_templates`, so they are not repeated here. Order is fixed and
    value-independent, preserving determinism."""
    out: list[tuple[str, str]] = []
    if kind in (None, "int", "float"):
        out.append(("neg", f"-{a}"))
    # ``int(a)`` parses a numeric string as well as truncating a float, so it is
    # offered for str args too (a common ``parse`` intent); only an iterable arg,
    # which ``int`` cannot coerce, prunes it.
    if kind in (None, "int", "float", "str"):
        out.append(("int", f"int({a})"))
    if kind in (None, "str", "iterable"):
        out.append(("first", f"{a}[0]"))
        out.append(("last", f"{a}[-1]"))
        if not _has_set_arg(witnesses):
            out.append(("list", f"list({a})"))
            out.append(("tuple", f"tuple({a})"))
    out.append(("str", f"str({a})"))
    out.append(("not", f"not {a}"))
    out.append(("bool", f"bool({a})"))
    return out


def _two_arg_templates(a: str, b: str,
                       witnesses: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Two-arg binary templates in a fixed order. Covers numeric arithmetic and,
    via ``+``, string/list concatenation; boolean ``and``/``or``; comparison;
    and ``a.join(b)`` for the ``sep.join(xs)`` shape. The widened builtin / operator
    shapes (``min``/``max``, membership, identity, power, indexing, f-string format,
    ``a.get(b)`` mapping access) follow, all offered BEFORE the constant-last fallback.

    ``min(a, b)`` / ``max(a, b)`` carry an OVERFIT FLOOR: a single example, or a
    batch that never crosses ``a<b`` AND ``a>b``, leaves them indistinguishable from
    a plain ``a``/``b`` passthrough, so they are withheld unless the witnesses
    DISCRIMINATE (at least one ``a<b`` and one ``a>b``). The other VALUE-FREE widened
    shapes are pure and gate-verified, so they need no floor (a non-matching one is
    rejected, never landed). The VALUE-DERIVED format/get shapes that bake a witness
    literal (``f"{a}{sep}{b}"`` with a derived ``sep``; ``a.get(b, default)`` with a
    derived ``default``) carry the same >=2-distinct-witness overfit floor the
    derived numeric/string shapes use, so one example cannot overfit a literal in."""
    witnesses = witnesses or []
    ops = ["+", "-", "*", "//", "%", "/"]
    out = [(op, f"{a} {op} {b}") for op in ops]
    out.append(("and", f"{a} and {b}"))
    out.append(("or", f"{a} or {b}"))
    out.append(("<", f"{a} < {b}"))
    out.append(("<=", f"{a} <= {b}"))
    out.append(("==", f"{a} == {b}"))
    out.append(("join", f"{a}.join({b})"))
    if _minmax_discriminated(witnesses):
        out.append(("min", f"min({a}, {b})"))
        out.append(("max", f"max({a}, {b})"))
    out.append(("pow", f"{a} ** {b}"))
    out.append(("in", f"{a} in {b}"))
    out.append(("not in", f"{a} not in {b}"))
    out.append(("is", f"{a} is {b}"))
    out.append(("rin", f"{b} in {a}"))
    out.append(("index", f"{a}[{b}]"))
    # f-string concat: distinct from ``a + b`` (it stringifies mixed types, e.g.
    # ``str`` + ``int``), value-free, gate-verified. The witness-derived
    # ``f"{a}{sep}{b}"`` (a literal separator) follows under the overfit floor.
    out.append(("fstr", f'f"{{{a}}}{{{b}}}"'))
    out.extend(_fstring_sep_templates(a, b, witnesses))
    # mapping access: ``a.get(b)`` (value-free) then ``a.get(b, default)`` (derived
    # default, floored). A non-mapping ``a`` simply fails the gate — never landed.
    out.append(("get", f"{a}.get({b})"))
    out.extend(_get_default_templates(a, b, witnesses))
    return out


def _fstring_sep_templates(a: str, b: str,
                           witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The witness-DERIVED ``f"{a}{sep}{b}"`` shapes — one per literal string ``sep``
    written in the witnesses — offered AFTER the value-free ``f"{a}{b}"`` so a plain
    concat wins when both fit. Each bakes a witnessed separator into the body
    (``join_with("a", "b") == "a-b"`` lands ``f"{a}-{b}"``), so it carries the same
    >=2-distinct-witness overfit floor (:func:`_string_floor_met`) the derived string
    shapes use: one example could pin an arbitrary separator. With NO witnesses (the
    structural view) it is withheld (no ``sep`` to derive). Deterministic: separators
    in sorted ``repr`` order; the literal is embedded verbatim so the body round-trips
    exactly on every witness or is rejected by the gate (never a fuzzy match)."""
    if not _string_floor_met(witnesses):
        return []
    out: list[tuple[str, str]] = []
    for sep in _string_constants(witnesses):
        literal = ast.literal_eval(sep)
        if literal == "":
            continue  # empty separator is just ``f"{a}{b}"``, already offered
        out.append((f"fstr({sep})", f'f"{{{a}}}{literal}{{{b}}}"'))
    return out


def _get_default_templates(a: str, b: str,
                           witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The witness-DERIVED ``a.get(b, default)`` shapes — one per literal default
    written in the witnesses' EXPECTED values — offered AFTER the value-free
    ``a.get(b)`` so a plain get wins when both fit. Each bakes a witnessed default
    into the body, so it carries the same >=2-distinct-witness overfit floor
    (:func:`_string_floor_met`). The defaults are the witnessed expected literals
    (a ``.get`` with a default returns either a stored value or that default, so the
    default is itself a witnessed result). Deterministic: defaults in sorted ``repr``
    order. With NO witnesses the shape is withheld (no default to derive)."""
    if not _string_floor_met(witnesses):
        return []
    out: list[tuple[str, str]] = []
    for default in _expected_literals(witnesses):
        out.append((f"get(default={default})", f"{a}.get({b}, {default})"))
    return out


def _expected_literals(witnesses: list[tuple[str, str]]) -> list[str]:
    """Every literal EXPECTED value across the witnesses, as canonical ``repr`` source,
    deterministic (sorted by repr, de-duplicated). Used to propose a ``.get`` default:
    a ``dict.get(key, default)`` returns the default for a missing key, so the default
    is one of the witnessed results. Non-literal expecteds are skipped (never guessed)."""
    seen: set[str] = set()
    for _args, expected in witnesses:
        value = _literal_value(expected)
        if value is not _NO_LITERAL:
            seen.add(repr(value))
    return sorted(seen)


def _minmax_discriminated(witnesses: list[tuple[str, str]]) -> bool:
    """True when the two-arg witnesses DISCRIMINATE ``min``/``max`` from a plain
    passthrough: at least one literal witness has ``a < b`` and another has
    ``a > b``. With only ``a < b`` cases (or a single example), ``min(a, b)`` and
    ``a`` are indistinguishable on the witnesses, so offering them would let an
    arbitrary guess land — the overfit floor withholds them until the contract
    actually exercises both orderings. Non-literal / non-orderable witnesses are
    ignored (they cannot establish an ordering). Deterministic."""
    saw_lt = saw_gt = False
    for args_text, _expected in witnesses:
        value = _literal_tuple(args_text)
        if value is None or len(value) != 2:
            continue
        a, b = value[0], value[1]
        try:
            if a < b:
                saw_lt = True
            elif a > b:
                saw_gt = True
        except TypeError:
            continue
    return saw_lt and saw_gt


# --- witness extraction (for value-dependent templates) ----------------------

def _numeric_constants(witnesses: list[tuple[str, str]]) -> list[str]:
    """Small integer constants to try in scalar/comparison templates, inferred
    from the witnesses. Two sources, both deterministic (sorted, capped):

    * **literal-present** ints — any int written in an arg or expected fragment.
      These are structurally in the spec, so they need no overfit floor (the run
      gate still rejects a non-matching one).
    * **arithmetically-derived** ints — ``expected - arg`` / ``expected // arg``
      from single-arg witnesses (so ``double(3) == 6`` proposes ``k = 2``). A
      derived constant can OVERFIT a lone example (``f(2) == 5`` would yield
      ``n + 3``), so it is offered ONLY when at least TWO DISTINCT argument tuples
      witness the contract AND the derived ``k`` is CONSISTENT across them — the
      same >=2-witness floor recursion and the constant template use."""
    seen: set[int] = set()
    for args, expected in witnesses:
        for text in (args, expected):
            for value in _int_literals(text):
                seen.add(value)
    seen.update(_derived_constants(witnesses))
    ordered = sorted(v for v in seen if -64 <= v <= 64)
    return [str(v) for v in ordered]


def _derived_constants(witnesses: list[tuple[str, str]]) -> set[int]:
    """The arithmetically-derived constants (``expected - arg``, ``expected //
    arg``) that are CONSISTENT across at least TWO DISTINCT single-arg witnesses.
    A constant derived from a single example is withheld (it would overfit); one
    that disagrees between witnesses is dropped. This is the overfit floor applied
    to value-dependent scalar templates."""
    diffs: list[int] = []
    quots: list[int] = []
    tuples: set[tuple[int, ...]] = set()
    for args, expected in witnesses:
        ai = _int_literals(args)
        ei = _int_literals(expected)
        if len(ai) == 1 and len(ei) == 1:
            tuples.add((ai[0],))
            diffs.append(ei[0] - ai[0])
            if ai[0] != 0 and ei[0] % ai[0] == 0:
                quots.append(ei[0] // ai[0])
    if len(tuples) < 2:
        return set()  # floor: a single example cannot pin a derived constant
    out: set[int] = set()
    if len(diffs) == len(tuples) and len(set(diffs)) == 1:
        out.add(diffs[0])  # one consistent offset across >=2 distinct inputs
    if len(quots) == len(tuples) and len(set(quots)) == 1:
        out.add(quots[0])  # one consistent multiplier across >=2 distinct inputs
    return out


def _int_literals(text: str) -> list[int]:
    """Every integer literal appearing as a constant in ``text`` (a test fragment),
    source-ordered. Non-parseable fragments yield ``[]``."""
    out: list[int] = []
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool):
            out.append(node.value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) \
                and isinstance(node.operand, ast.Constant) \
                and isinstance(node.operand.value, int):
            out.append(-node.operand.value)
    return out


def _string_constants(witnesses: list[tuple[str, str]]) -> list[str]:
    """Every string literal seen in the witnesses' arguments and expected values,
    plus the single-character separators implied by an expected slug (the chars
    that appear in the expected but not the argument). Deterministic: sorted,
    de-duplicated, each rendered as canonical ``repr`` source."""
    seen: set[str] = set()
    for args, expected in witnesses:
        for text in (args, expected):
            for value in _str_literals(text):
                seen.add(value)
    # Common single-character separators so slug/clean shapes are reachable even
    # when only one side names them (e.g. " " and "-" for "Hello World"->"hello-world").
    seen.update({" ", "-", "_", ",", ".", "/", ""})
    return [repr(s) for s in sorted(seen)]


def _str_literals(text: str) -> list[str]:
    """Every string literal appearing as a constant in ``text``, source-ordered."""
    out: list[str] = []
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def _ordered_string_pairs(strings: list[str]) -> list[tuple[str, str]]:
    """All ordered (old, new) pairs of distinct string constants for ``replace``.
    Deterministic: the input order (already sorted) is preserved; a constant is
    never paired with itself."""
    out: list[tuple[str, str]] = []
    for old in strings:
        for new in strings:
            if old != new:
                out.append((old, new))
    return out


def _function_witnesses(root: Path, test_files: list[str],
                        stub: StubFunction) -> list[tuple[str, str]]:
    """The ``(args_text, expected_text)`` pairs the pinned tests ENFORCEABLY
    assert for ``stub`` — every ``func(<args>) == <expected>`` in the test files
    that does NOT live inside a test function marked ``@pytest.mark.xfail`` /
    ``xfail`` / ``@pytest.mark.skip`` / ``skipif`` / ``@unittest.skip``. An
    xfail/skip assertion pins NO enforceable contract (its failure is allowed or
    it never runs), so it must not be mined for witnesses — otherwise a wrong body
    that fails only an xfail assertion gets stamped "verified" while the suite
    stays green. Used to PROPOSE value-dependent template constants and to gate
    in-process synthesis. Deterministic: source order within each sorted file.

    Two INDIRECT forms are also mined so a stub pinned through them is actually
    synthesizable, not just gated right:

    * ``@pytest.mark.parametrize`` — each literal ROW of the decorator is bound to
      the test's params and substituted into the ``symbol(params) == param``
      assert (``@parametrize("n,e", [(2, 6), (5, 15)])`` + ``assert scale(n) == e``
      recovers ``scale(2) == 6``, ``scale(5) == 15``);
    * a ONE-LEVEL module-local helper — when ``test_x`` calls ``_h(lit, lit, lit)``
      and ``_h(a, b, expected)`` asserts ``symbol(a, b) == expected``, the literals
      are resolved through the helper's params (``add(2, 3) == 5``).

    Only LITERAL arguments are resolved (re-using the existing literal extraction);
    a non-literal row/argument is skipped — never guessed. An assert that one of
    these indirect miners resolves is EXCLUDED from the direct regex pass (its raw
    ``symbol(n) == e`` text is non-literal and would otherwise poison the evaluable
    witness set); a DIRECT assert keeps the exact regex output, byte-for-byte as
    before. This only ADDS witnesses that were always there — the accept-gate is
    unchanged, the ambiguity guard still applies, never-fake-green holds."""
    call_eq = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(stub.name)
        + r"\s*\(([^()]*)\)\s*==\s*([^\n#]+)")
    out: list[tuple[str, str]] = []
    for rel in sorted(test_files):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.extend(_witnesses_in_file(text, stub, call_eq))
    return out


def _witnesses_in_file(text: str, stub: StubFunction,
                       call_eq: re.Pattern[str]) -> list[tuple[str, str]]:
    """Every enforceable ``(args_text, expected_text)`` witness mined from ONE test
    file's ``text``: the indirect (parametrize + module-local-helper) literal
    witnesses first, then the direct regex witnesses for any assert NOT already
    resolved by an indirect miner.

    Suppression is ASSERT-PRECISE: only the exact source lines of asserts that an
    indirect miner turned into a LITERAL witness are skipped in the direct pass (so
    the non-literal raw form of a parametrize/helper assert doesn't poison the
    evaluable set). An assert the indirect miners did NOT resolve keeps its direct
    regex output byte-for-byte — guaranteeing the change is strictly additive (it
    never removes a witness the direct pass used to yield). Deterministic.

    The ``is``-SINGLETON witnesses (``symbol(...) is None/True/False``) are mined
    last and APPENDED: the ``==`` regex never matches an ``is`` compare, so the
    direct pass above is byte-identical, and these only ADD the very common
    identity-equality idiom (``assert cfg(d, 'k') is None``) the regex used to drop
    — letting e.g. a ``d.get(k)`` shape land on a missing-key contract."""
    excluded = _unenforced_line_ranges(text)
    indirect, resolved_lines = _indirect_witnesses(text, stub)
    out: list[tuple[str, str]] = list(indirect)
    for m in call_eq.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if _line_in_ranges(line, excluded):
            continue  # assertion lives in an xfail/skip test — not a contract
        if line in resolved_lines:
            continue  # this exact assert already mined as a literal indirectly
        out.append((m.group(1).strip(), m.group(2).strip()))
    out.extend(_singleton_witnesses(text, stub, excluded))
    return out


# The only objects whose ``is`` comparison IS a value-equality contract: the three
# interned singletons. ``x is 5`` / ``x is 'k'`` are NOT mined — CPython interns
# small ints/strings but identity is not a value contract there (the idiom is a
# bug, not a spec), so the miner stays restricted to exactly None/True/False.
_SINGLETON_EXPECTED: dict[object, str] = {None: "None", True: "True", False: "False"}


def _singleton_witnesses(text: str, stub: StubFunction,
                         excluded: list[tuple[int, int]]) -> list[tuple[str, str]]:
    """The ``(args_text, expected_text)`` witnesses mined from the identity-equality
    idiom ``symbol(<args>) is None`` / ``is True`` / ``is False`` — the idiomatic way
    to pin a function that returns one of those singletons (a ``dict.get`` miss
    returns ``None``, a predicate returns ``True``/``False``). The expected text is
    the singleton's source (``"None"``/``"True"``/``"False"``), which flows through
    the SAME literal parsing, accept-gate, and ambiguity guard as a ``== None`` would
    — only the recognised SYNTAX is widened, never the acceptance rule.

    Conservative by construction:

    * only the three interned SINGLETONS are mined; ``symbol(x) is 5`` (a non-singleton
      ``is``) yields NO witness — identity on a small int/str is not a value contract;
    * only a single, non-chained ``is`` compare with a bare-``Name`` ``symbol(...)``
      call on one side counts (mirrors the ``==`` mining shape);
    * ``is not`` is NOT mined: the witness model is equality-only (a witness asserts
      ``func(args) == expected``), and there is no must-NOT-equal witness channel, so
      inventing a negative witness would be unsound — we stay conservative and skip it;
    * an assert inside an ``xfail``/``skip`` test (its line in ``excluded``) pins no
      enforceable contract and is dropped, exactly as the ``==`` pass drops it.

    Deterministic, AST-based, stdlib-only: ``[]`` on a syntax error (the ``==`` regex
    pass already ran, so nothing a parse hiccup could have mined is lost)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[tuple[str, str]] = []
    for cmp_node in ast.walk(tree):
        if not isinstance(cmp_node, ast.Compare):
            continue
        if len(cmp_node.ops) != 1 or not isinstance(cmp_node.ops[0], ast.Is):
            continue
        if _line_in_ranges(cmp_node.lineno, excluded):
            continue  # xfail/skip assertion — not an enforceable contract
        pair = _singleton_compare_witness(cmp_node, stub)
        if pair is not None:
            out.append(pair)
    return out


def _singleton_compare_witness(cmp_node: ast.Compare,
                               stub: StubFunction) -> tuple[str, str] | None:
    """One ``(args_text, expected_text)`` witness from an ``is``-compare ``symbol(...)
    is <singleton>`` (either operand order), or ``None`` when it is not that shape.
    The call side must be a bare-``Name`` call to ``stub.name``; the other side must
    be one of the three singletons (``_SINGLETON_EXPECTED``). The args are rendered
    from the call's positional arguments verbatim, so they round-trip through the
    existing literal extraction the same way a ``==`` witness's args do."""
    left, right = cmp_node.left, cmp_node.comparators[0]
    call = singleton = None
    if _is_symbol_call(left, stub.name):
        call, singleton = left, right
    elif _is_symbol_call(right, stub.name):
        call, singleton = right, left
    if call is None:
        return None
    expected = _singleton_text(singleton)
    if expected is None:
        return None
    args_text = _render_call_args(call)
    if args_text is None:
        return None
    return args_text, expected


def _singleton_text(node: ast.expr) -> str | None:
    """``"None"``/``"True"``/``"False"`` when ``node`` is exactly that singleton
    constant, else ``None``. Matched by IDENTITY against the three interned singletons
    so a non-singleton ``is`` operand (``5``, ``'k'``, a ``Name``) is never mined —
    ``True``/``False`` are matched before ``1``/``0`` since ``True is 1`` is ``False``
    and ``bool`` is the distinguishing type. Deterministic, value-exact."""
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    return None


def _render_call_args(call: ast.Call) -> str | None:
    """The comma-joined source text of ``call``'s POSITIONAL arguments — the
    ``args_text`` of a witness, rendered exactly as the ``==`` regex would have
    captured the ``(...)`` group. ``None`` when the call carries a starred or keyword
    argument (the witness's arg tuple would be unrecoverable — never guessed)."""
    if call.keywords or any(isinstance(a, ast.Starred) for a in call.args):
        return None
    return ", ".join(ast.unparse(a) for a in call.args)


def _indirect_witnesses(text: str,
                        stub: StubFunction) -> tuple[list[tuple[str, str]], set[int]]:
    """The literal witnesses recovered from the three indirect forms (parametrize
    rows, one-level module-local helpers, and same-test local-literal bindings),
    plus the exact source LINES of the asserts that were resolved (so the direct
    regex pass skips only those lines). ``([], set())`` on a syntax error — the
    direct pass then still runs. Enforceable-only: an assert inside an xfail/skip
    test is not mined. Deterministic: source order."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [], set()
    excluded = _unenforced_line_ranges(text)
    witnesses: list[tuple[str, str]] = []
    resolved: set[int] = set()
    p_w, p_lines = _parametrize_witnesses(tree, text, stub, excluded)
    h_w, h_lines = _helper_witnesses(tree, text, stub, excluded)
    l_w, l_lines = _localvar_witnesses(tree, stub, excluded)
    witnesses.extend(p_w)
    witnesses.extend(h_w)
    witnesses.extend(l_w)
    resolved |= p_lines
    resolved |= h_lines
    resolved |= l_lines
    return witnesses, resolved


def _symbol_assert_pairs(body_node: ast.AST,
                         stub: StubFunction) -> list[tuple[ast.Call, ast.expr]]:
    """Every ``symbol(<args>) == <expected>`` assertion in ``body_node``'s subtree,
    as ``(call_node, expected_node)`` AST pairs. Both ``call == expected`` and
    ``expected == call`` orderings are accepted (the comparator that IS the call to
    ``stub.name`` becomes the call side). Only a simple two-operand ``==`` compare
    is mined — never a chained one. The call node carries its ``lineno`` so a
    resolved assert's exact source line can be suppressed in the direct pass."""
    out: list[tuple[ast.Call, ast.expr]] = []
    for cmp_node in ast.walk(body_node):
        if not isinstance(cmp_node, ast.Compare):
            continue
        if len(cmp_node.ops) != 1 or not isinstance(cmp_node.ops[0], ast.Eq):
            continue
        left, right = cmp_node.left, cmp_node.comparators[0]
        if _is_symbol_call(left, stub.name):
            out.append((left, right))
        elif _is_symbol_call(right, stub.name):
            out.append((right, left))
    return out


def _is_symbol_call(node: ast.expr, name: str) -> bool:
    """True when ``node`` is a direct call ``name(...)`` (a bare-``Name`` callee)."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == name)


def _bind_and_render(call_node: ast.Call, expected: ast.expr,
                     binding: dict[str, ast.expr]) -> tuple[str, str] | None:
    """Substitute ``binding`` (param name -> literal AST) into the call's positional
    arguments and the expected expression, then render both as source text — the
    ``(args_text, expected_text)`` of one recovered literal witness. ``None`` when,
    after substitution, any argument or the expected is not a pure literal (a
    non-literal reference survived), so we never guess. Positional args only; a
    starred/keyword arg makes the witness unrecoverable (``None``)."""
    if any(isinstance(a, ast.Starred) for a in call_node.args) or call_node.keywords:
        return None
    rendered_args: list[str] = []
    for arg in call_node.args:
        text = _render_substituted(arg, binding)
        if text is None:
            return None
        rendered_args.append(text)
    expected_text = _render_substituted(expected, binding)
    if expected_text is None:
        return None
    return ", ".join(rendered_args), expected_text


def _render_substituted(node: ast.expr, binding: dict[str, ast.expr]) -> str | None:
    """Render ``node`` to source after replacing every ``Name`` bound in
    ``binding`` with its literal AST, but ONLY when the result is a pure literal
    (``ast.literal_eval`` succeeds) — otherwise ``None`` (a non-literal survived).
    Pure and deterministic; the rendered text round-trips through the existing
    literal extractor."""
    substituted = _Substitute(binding).visit(ast.copy_location(_clone(node), node))
    try:
        ast.literal_eval(substituted)
    except (ValueError, SyntaxError, TypeError):
        return None
    return ast.unparse(substituted)


def _clone(node: ast.expr) -> ast.expr:
    """A deep, location-stripped copy of ``node`` safe to mutate during
    substitution (we never edit the original tree)."""
    return ast.parse(ast.unparse(node), mode="eval").body


class _Substitute(ast.NodeTransformer):
    """Replace each ``Name`` whose id is a key of ``binding`` with the bound literal
    AST node — the one-step param->value substitution that turns a parametrize/
    helper assert into a concrete literal witness."""

    def __init__(self, binding: dict[str, ast.expr]) -> None:
        self._binding = binding

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802 - ast API
        replacement = self._binding.get(node.id)
        return ast.copy_location(_clone(replacement), node) if replacement is not None else node


def _all_literal(nodes: list[ast.expr]) -> bool:
    """True when every node is a literal (``ast.literal_eval`` succeeds). Used to
    admit only fully-literal parametrize rows / helper-call arguments."""
    for n in nodes:
        try:
            ast.literal_eval(n)
        except (ValueError, SyntaxError, TypeError):
            return False
    return True


def _parametrize_witnesses(tree: ast.Module, text: str, stub: StubFunction,
                           excluded: list[tuple[int, int]]) -> tuple[list[tuple[str, str]], set[int]]:
    """Literal witnesses recovered from ``@pytest.mark.parametrize`` tests. For each
    top-level enforced ``test_*`` carrying a parametrize decorator, bind every
    literal row to the declared param names and substitute into each
    ``symbol(...) == ...`` assert in its body. Returns the witnesses and the exact
    LINES of the asserts resolved (so the direct pass skips only those lines).
    Deterministic: source order; non-literal rows / unresolved asserts are
    skipped."""
    witnesses: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for node in tree.body:
        if not _is_enforced_test(node, excluded):
            continue
        rows = _parametrize_rows(node)
        if rows is None:
            continue
        names, value_rows = rows
        pairs = _symbol_assert_pairs(node, stub)
        if not pairs:
            continue
        emitted, lines = _emit_param_rows(names, value_rows, pairs)
        witnesses.extend(emitted)
        resolved |= lines
    return witnesses, resolved


def _emit_param_rows(names: list[str], value_rows: list[list[ast.expr]],
                     pairs: list[tuple[ast.Call, ast.expr]]) -> tuple[list[tuple[str, str]], set[int]]:
    """For each literal parametrize row, bind it to ``names`` and render every
    ``symbol`` assert pair into a literal witness. Returns the witnesses and the
    source lines of the asserts that produced at least one. A row whose arity
    mismatches the names, or that holds a non-literal, is skipped (never guessed)."""
    out: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for row in value_rows:
        if len(row) != len(names) or not _all_literal(row):
            continue
        binding = {name: value for name, value in zip(names, row)}
        for call_node, expected in pairs:
            rendered = _bind_and_render(call_node, expected, binding)
            if rendered is not None:
                out.append(rendered)
                resolved.add(call_node.lineno)
    return out, resolved


def _parametrize_rows(node: ast.AST) -> tuple[list[str], list[list[ast.expr]]] | None:
    """The ``(param_names, value_rows)`` of a test's ``@pytest.mark.parametrize``
    decorator: the argnames (a ``"a,b"`` string or a list/tuple of name strings)
    and each argvalues row as a list of arg AST nodes (a single-param row is a bare
    value, wrapped to a one-element list). ``None`` when the node has no usable
    parametrize decorator. The FIRST parametrize decorator is used (stacked marks
    are an uncommon shape we conservatively skip beyond the first)."""
    for dec in getattr(node, "decorator_list", []):
        names_values = _parse_parametrize_call(dec)
        if names_values is not None:
            return names_values
    return None


def _parse_parametrize_call(dec: ast.expr) -> tuple[list[str], list[list[ast.expr]]] | None:
    """Parse one decorator AST into ``(names, value_rows)`` when it is a
    ``parametrize(argnames, argvalues, ...)`` call, else ``None``. ``argnames`` is a
    string literal (``"a,b"``) or a list/tuple of string literals; ``argvalues`` is
    a list/tuple of rows. A single-name parametrize wraps each scalar row into a
    one-element list so binding is uniform."""
    if not (isinstance(dec, ast.Call) and _is_parametrize(dec.func)):
        return None
    if len(dec.args) < 2:
        return None
    names = _parametrize_names(dec.args[0])
    if not names:
        return None
    rows_node = dec.args[1]
    if not isinstance(rows_node, (ast.List, ast.Tuple)):
        return None
    value_rows: list[list[ast.expr]] = []
    for row in rows_node.elts:
        if len(names) == 1:
            value_rows.append([row])
        elif isinstance(row, (ast.List, ast.Tuple)):
            value_rows.append(list(row.elts))
    return names, value_rows


def _is_parametrize(func: ast.expr) -> bool:
    """True for a ``parametrize`` decorator callee in any spelling
    (``pytest.mark.parametrize``, ``mark.parametrize``, a bare ``parametrize``
    alias) — matched on the trailing attribute/name token."""
    if isinstance(func, ast.Attribute):
        return func.attr == "parametrize"
    return isinstance(func, ast.Name) and func.id == "parametrize"


def _parametrize_names(node: ast.expr) -> list[str]:
    """The parameter names of a parametrize ``argnames`` node: a ``"a, b"`` string
    literal split on commas, or a list/tuple of string literals. ``[]`` when the
    node is not a recognizable name spec."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [n.strip() for n in node.value.split(",") if n.strip()]
    if isinstance(node, (ast.List, ast.Tuple)):
        names = [el.value for el in node.elts
                 if isinstance(el, ast.Constant) and isinstance(el.value, str)]
        return names if len(names) == len(node.elts) else []
    return []


def _helper_witnesses(tree: ast.Module, text: str, stub: StubFunction,
                      excluded: list[tuple[int, int]]) -> tuple[list[tuple[str, str]], set[int]]:
    """Literal witnesses recovered from one-level module-local helpers. For each
    top-level helper ``_h(params...)`` whose body asserts ``symbol(...) == ...``
    over its own params, find every enforced ``test_*`` that calls ``_h(lit, ...)``
    with all-literal args, bind them to the helper's params, and substitute into
    the assert. Returns the witnesses and the exact LINES of the helper asserts that
    were resolved (so the direct pass skips ONLY the helper's own non-literal assert
    when a test actually drove it to a literal). Deterministic: helpers then their
    call sites in source order; non-literal calls are skipped."""
    helpers = _resolvable_helpers(tree, stub)
    if not helpers:
        return [], set()
    witnesses: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for node in tree.body:
        if not _is_enforced_test(node, excluded):
            continue
        w, lines = _witnesses_from_helper_calls(node, helpers)
        witnesses.extend(w)
        resolved |= lines
    return witnesses, resolved


def _resolvable_helpers(tree: ast.Module, stub: StubFunction
                        ) -> dict[str, tuple[list[str], list[tuple[ast.Call, ast.expr]]]]:
    """The module-local helpers usable for one-level witness resolution: a top-level
    non-``test`` ``def`` with positional params whose body asserts ``symbol(...) ==
    ...`` referencing only those params. Maps helper name -> (param names, the
    ``(call, expected)`` assert pairs). Deterministic."""
    out: dict[str, tuple[list[str], list[tuple[ast.Call, ast.expr]]]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("test"):
            continue
        params = _plain_param_names(node)
        if not params:
            continue
        pairs = _symbol_assert_pairs(node, stub)
        if pairs:
            out[node.name] = (params, pairs)
    return out


def _plain_param_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The ordered plain positional parameter names of a helper ``def`` (no
    ``self``/``cls`` dropping — a helper is a free function). ``*args``/keyword-only
    params make the helper unresolvable, so ``[]`` is returned then."""
    args = node.args
    if args.vararg or args.kwarg or args.kwonlyargs:
        return []
    return [a.arg for a in (args.posonlyargs + args.args)]


def _witnesses_from_helper_calls(test_node: ast.AST,
                                 helpers: dict) -> tuple[list[tuple[str, str]], set[int]]:
    """Every literal witness from ``test_node``'s direct calls to a resolvable
    helper, plus the helper-assert lines resolved: for each ``_h(lit, lit, ...)``
    whose arity and literalness match, bind the literals to the helper's params and
    render each of the helper's ``symbol`` asserts. Deterministic: calls in source
    order; a non-literal/arity-mismatched call is skipped."""
    out: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for call in ast.walk(test_node):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            continue
        entry = helpers.get(call.func.id)
        if entry is not None:
            w, lines = _witnesses_from_one_call(call, entry)
            out.extend(w)
            resolved |= lines
    return out, resolved


def _witnesses_from_one_call(call: ast.Call,
                             entry: tuple[list[str], list[tuple[ast.Call, ast.expr]]]
                             ) -> tuple[list[tuple[str, str]], set[int]]:
    """The literal witnesses from ONE ``_h(lit, ...)`` helper call, plus the
    helper-assert lines they resolve: bind its literal args to the helper's params
    and render each of the helper's ``symbol`` asserts. ``([], set())`` when the
    call is not all-literal-positional or its arity mismatches the helper's params
    (never guessed)."""
    params, pairs = entry
    if call.keywords or any(isinstance(a, ast.Starred) for a in call.args):
        return [], set()
    if len(call.args) != len(params) or not _all_literal(call.args):
        return [], set()
    binding = {name: value for name, value in zip(params, call.args)}
    out: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for inner_call, expected in pairs:
        rendered = _bind_and_render(inner_call, expected, binding)
        if rendered is not None:
            out.append(rendered)
            resolved.add(inner_call.lineno)
    return out, resolved


def _localvar_witnesses(tree: ast.Module, stub: StubFunction,
                        excluded: list[tuple[int, int]]) -> tuple[list[tuple[str, str]], set[int]]:
    """Literal witnesses recovered from SAME-TEST local-literal bindings — the
    third indirect form (real-repo GAP #3). Within each enforced top-level
    ``test_*``, a straight-line constant environment is built from that function's
    OWN top-level ``Assign`` statements whose RHS is a literal, and every
    ``symbol(...) == ...`` assert whose call-args / expected REFERENCE such a name
    is resolved by substituting the bound literal (reusing :func:`_bind_and_render`,
    the same substitution parametrize/helper use). Returns the recovered witnesses
    and the exact source LINES of the asserts resolved (so the direct regex pass
    skips ONLY those lines — otherwise the non-literal raw text ``prefix + "3"``
    would poison the evaluable witness set).

    Per-test only (no cross-test / module-scope leakage); constants-only,
    straight-line, last-binding-wins; control-flow / augmented-assign / reassigned
    names refuse (:func:`_straightline_literal_env`). Deterministic: tests then
    their asserts in source order. A binding that does not turn the witness fully
    literal yields nothing (``_bind_and_render`` returns ``None``) — never guessed."""
    witnesses: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for node in tree.body:
        if not _is_enforced_test(node, excluded):
            continue
        env = _straightline_literal_env(node)
        if not env:
            continue
        w, lines = _witnesses_from_local_env(node, stub, env)
        witnesses.extend(w)
        resolved |= lines
    return witnesses, resolved


def _straightline_literal_env(test_node: ast.FunctionDef | ast.AsyncFunctionDef
                              ) -> dict[str, tuple[int, ast.expr]]:
    """The straight-line constant environment of ``test_node``: maps each name bound
    by a TOP-LEVEL ``Assign`` in the function body whose RHS is a pure literal
    (``ast.literal_eval`` succeeds — a ``Constant`` or a list/dict/set/tuple display
    of constants) to ``(lineno, literal_ast)``, last-binding-wins in source order.

    SOUNDNESS — refuse anything not provably a straight-line constant:

    * only direct children of the function body are considered (a binding inside an
      ``if`` / ``for`` / ``while`` / ``with`` / ``try`` is NOT straight-line, so it
      is never collected);
    * only a single-target ``Name`` assign (``x = <lit>``) qualifies — a tuple/list
      unpack target or attribute/subscript target is skipped;
    * an ``AugAssign`` (``x += 1``) and an ``AnnAssign`` are NOT collected;
    * a NAME that is the target of MORE THAN ONE qualifying straight-line assign, or
      that ALSO appears as a target inside nested control flow / aug-assign / unpack,
      is POISONED (removed) — we cannot pin its value at the assert, so we refuse it.

    The ``lineno`` lets the caller enforce assignment-BEFORE-use. Deterministic;
    nothing is executed."""
    bound: dict[str, tuple[int, ast.expr]] = {}
    poisoned: set[str] = set()
    for stmt in test_node.body:
        name, literal = _straightline_assignment(stmt)
        if name is not None:
            if name in bound:
                poisoned.add(name)  # reassigned at top level — last value unclear here
            bound[name] = (stmt.lineno, literal)
            continue
        poisoned |= _names_unsafely_bound(stmt)
    for name in poisoned:
        bound.pop(name, None)
    return bound


def _straightline_assignment(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    """``(name, literal_ast)`` when ``stmt`` is a single-target ``Name = <literal>``
    straight-line assign whose RHS is a pure literal, else ``(None, None)``. The
    literal is validated with ``ast.literal_eval`` (a ``Constant`` or a list/dict/
    set/tuple display of constants); a name/call/attribute/comprehension/arithmetic
    RHS fails and is refused. Never executes anything."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None, None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None, None
    try:
        ast.literal_eval(stmt.value)
    except (ValueError, SyntaxError, TypeError):
        return None, None
    return target.id, stmt.value


def _names_unsafely_bound(stmt: ast.stmt) -> set[str]:
    """The names ``stmt`` binds in a way that makes them NOT safely resolvable as a
    straight-line constant: a non-literal top-level ``Assign`` target, an
    ``AugAssign`` / ``AnnAssign`` target, a tuple/list unpack target, or ANY name
    assigned inside nested control flow (``if`` / ``for`` / ``while`` / ``with`` /
    ``try``). Such names are poisoned out of the constant environment so a witness
    referencing them is refused, never guessed. ``Name`` STORE contexts anywhere in
    the statement subtree are collected (covers nested + unpack uniformly)."""
    names: set[str] = set()
    for child in ast.walk(stmt):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.add(child.id)
    return names


def _witnesses_from_local_env(test_node: ast.AST, stub: StubFunction,
                              env: dict[str, tuple[int, ast.expr]]
                              ) -> tuple[list[tuple[str, str]], set[int]]:
    """Resolve every ``symbol(...) == ...`` assert in ``test_node`` against the
    straight-line constant ``env``: substitute each bound literal into the call-args
    and expected, rendering a fully-literal witness via :func:`_bind_and_render`.
    Only names bound BEFORE the assert's source line are substituted (assignment-
    before-use); an assert whose result is not fully literal after substitution is
    skipped (never guessed). Returns the witnesses and the asserts' source lines (so
    the direct pass skips them). Deterministic: asserts in source order."""
    out: list[tuple[str, str]] = []
    resolved: set[int] = set()
    for call_node, expected in _symbol_assert_pairs(test_node, stub):
        use_line = call_node.lineno
        binding = {name: literal for name, (lineno, literal) in env.items()
                   if lineno < use_line}
        if not binding:
            continue
        rendered = _bind_and_fold(call_node, expected, binding)
        if rendered is not None:
            out.append(rendered)
            resolved.add(call_node.lineno)
    return out, resolved


def _bind_and_fold(call_node: ast.Call, expected: ast.expr,
                   binding: dict[str, ast.expr]) -> tuple[str, str] | None:
    """Like :func:`_bind_and_render`, but for the same-test local-var case: after
    substituting the bound literals, CONSTANT-FOLD each call-arg and the expected to
    a single literal value and render its canonical ``repr`` — so an expression that
    merely COMBINES constants (``prefix + "3"`` -> ``'item-3'``, ``base + 2`` ->
    ``12``) becomes the fully-literal ``args_text`` / ``expected_text`` the rest of
    the pipeline consumes via ``ast.literal_eval``.

    ``None`` (witness dropped, never guessed) when, after substitution, any arg or
    the expected still references a non-constant (a surviving ``Name``/``Call``/
    ``Attribute``/comprehension) or uses an operator outside the safe constant-fold
    whitelist (:func:`_fold_constant`). Positional args only; a starred/keyword arg
    is unrecoverable (``None``). Sound: nothing from the test is executed — only a
    tree of literals and whitelisted operators is folded in an empty sandbox."""
    if any(isinstance(a, ast.Starred) for a in call_node.args) or call_node.keywords:
        return None
    rendered_args: list[str] = []
    for arg in call_node.args:
        text = _render_folded(arg, binding)
        if text is None:
            return None
        rendered_args.append(text)
    expected_text = _render_folded(expected, binding)
    if expected_text is None:
        return None
    return ", ".join(rendered_args), expected_text


def _render_folded(node: ast.expr, binding: dict[str, ast.expr]) -> str | None:
    """Substitute ``binding`` into ``node`` then constant-fold the whole tree to one
    literal, returning its ``repr`` source — or ``None`` when a non-constant survives
    or an unsafe operator is used. The ``repr`` round-trips through the existing
    ``ast.literal_eval``-based extractor exactly like a hand-written literal would.
    Pure and deterministic; nothing is executed beyond folding a constants-only
    expression in an empty namespace."""
    substituted = _Substitute(binding).visit(ast.copy_location(_clone(node), node))
    value = _fold_constant(substituted)
    if value is _NO_LITERAL:
        return None
    return repr(value)


# Operators/containers safe to constant-fold over already-substituted LITERALS only.
# Bitwise/shift ops are intentionally excluded as uncommon in witness expectations;
# adding them would only widen coverage, never weaken soundness (still constants-only).
_FOLD_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_FOLD_UNARYOPS = (ast.UAdd, ast.USub, ast.Not)


def _fold_constant(node: ast.expr) -> object:
    """The literal VALUE of ``node`` when it is built ENTIRELY from constants and a
    whitelisted set of operators / container displays — else the sentinel
    ``_NO_LITERAL``. This is a tiny total evaluator that NEVER touches a ``Name``,
    ``Call``, ``Attribute``, comprehension, or any non-whitelisted node, so a
    non-constant that survived substitution refuses the witness (never guessed).

    Handled: ``Constant``; list/tuple/set/dict displays of foldable elements;
    ``BinOp`` over :data:`_FOLD_BINOPS`; ``UnaryOp`` over :data:`_FOLD_UNARYOPS`. A
    ``ZeroDivisionError`` / ``TypeError`` from a nonsensical fold (``'a' - 'b'``)
    also refuses. Deterministic; pure-Python, no ``eval``/builtins."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return _fold_sequence(node)
    if isinstance(node, ast.Dict):
        return _fold_dict(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, _FOLD_BINOPS):
        return _fold_binop(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _FOLD_UNARYOPS):
        return _fold_unaryop(node)
    return _NO_LITERAL


def _fold_sequence(node: ast.List | ast.Tuple | ast.Set) -> object:
    """Fold a list/tuple/set display whose every element is foldable, into the
    matching container value; ``_NO_LITERAL`` when any element is non-constant or
    a set element is unhashable."""
    items = [_fold_constant(el) for el in node.elts]
    if any(it is _NO_LITERAL for it in items):
        return _NO_LITERAL
    if isinstance(node, ast.List):
        return items
    if isinstance(node, ast.Set):
        try:
            return set(items)
        except TypeError:
            return _NO_LITERAL
    return tuple(items)


def _fold_dict(node: ast.Dict) -> object:
    """Fold a dict display whose keys and values are all foldable constants, else
    ``_NO_LITERAL``. A ``**spread`` (a ``None`` key) refuses (non-constant shape)."""
    out: dict = {}
    for key_node, val_node in zip(node.keys, node.values):
        if key_node is None:
            return _NO_LITERAL  # ``{**other}`` spread — not a constant display
        key = _fold_constant(key_node)
        val = _fold_constant(val_node)
        if key is _NO_LITERAL or val is _NO_LITERAL:
            return _NO_LITERAL
        try:
            out[key] = val
        except TypeError:
            return _NO_LITERAL  # unhashable key
    return out


def _fold_binop(node: ast.BinOp) -> object:
    """Fold a whitelisted ``BinOp`` over two foldable constants; ``_NO_LITERAL`` when
    either side is non-constant or the operation is undefined for the values."""
    left = _fold_constant(node.left)
    right = _fold_constant(node.right)
    if left is _NO_LITERAL or right is _NO_LITERAL:
        return _NO_LITERAL
    ops = {
        ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b,
    }
    try:
        return ops[type(node.op)](left, right)
    except (TypeError, ValueError, ZeroDivisionError):
        return _NO_LITERAL


def _fold_unaryop(node: ast.UnaryOp) -> object:
    """Fold a whitelisted ``UnaryOp`` over a foldable constant operand;
    ``_NO_LITERAL`` when the operand is non-constant or the op is undefined for it."""
    operand = _fold_constant(node.operand)
    if operand is _NO_LITERAL:
        return _NO_LITERAL
    try:
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        return not operand
    except TypeError:
        return _NO_LITERAL


def _is_enforced_test(node: ast.AST, excluded: list[tuple[int, int]]) -> bool:
    """True when ``node`` is a top-level ``def test_*`` that is NOT inside an
    xfail/skip range (its assertions are enforced). Used to gate both indirect
    witness miners so an unenforced test pins no witness."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if not node.name.startswith("test"):
        return False
    return not _line_in_ranges(node.lineno, excluded)


def _unenforced_line_ranges(text: str) -> list[tuple[int, int]]:
    """The 1-based ``(start, end)`` line spans of every test function in ``text``
    decorated to NOT enforce its assertions: ``@pytest.mark.xfail`` (and bare
    ``@xfail``), ``@pytest.mark.skip`` / ``skipif``, and ``@unittest.skip*``. An
    assertion inside such a function pins no contract — its failure is allowed
    (xfail) or it never runs (skip). Deterministic; ``[]`` on a syntax error so a
    parse failure never silently drops a real contract."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_is_unenforced_decorator(d) for d in node.decorator_list):
            out.append((node.lineno, node.end_lineno or node.lineno))
    return out


def _is_unenforced_decorator(dec: ast.expr) -> bool:
    """True for a decorator that suspends a test's assertions: ``xfail`` / ``skip``
    / ``skipif`` in any form (``@pytest.mark.xfail``, ``@xfail``,
    ``pytest.mark.xfail(...)``, ``@unittest.skip(...)``, ``@skipUnless`` ...). We
    match on the trailing attribute/name token so import-alias spellings still
    count; ``skipUnless``/``skipIf`` (unittest) are included."""
    if isinstance(dec, ast.Call):
        dec = dec.func
    name = None
    if isinstance(dec, ast.Attribute):
        name = dec.attr
    elif isinstance(dec, ast.Name):
        name = dec.id
    if name is None:
        return False
    lowered = name.lower()
    return lowered in {"xfail", "skip", "skipif", "skipunless"}


def _line_in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    """True when 1-based ``line`` falls within any ``(start, end)`` span."""
    return any(start <= line <= end for start, end in ranges)


def _has_enforceable_contract(root: Path, test_files: list[str],
                              stub: StubFunction) -> bool:
    """True when at least one ENFORCED test references ``stub.name`` — a test
    function that is NOT decorated ``xfail`` / ``skip`` / ``skipif`` and so whose
    assertions the suite actually enforces.

    This is the never-fake-green floor for the pytest-gated path: when EVERY test
    touching the stub is xfail/skip, the pinned-test gate is meaningless (an
    xfail test stays "green" no matter what body we land, a skip never runs), so
    synthesising a body against it would stamp an unenforced contract "verified".
    We refuse instead. A non-stub reference inside an enforced test is enough — we
    err toward "enforceable" only when a real, running test names the function.
    Deterministic; on a parse failure we conservatively report ``True`` so a
    parse hiccup never suppresses a genuine contract (the run gate still
    decides)."""
    name_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stub.name)
                         + r"(?![A-Za-z0-9_])")
    saw_reference = False
    for rel in sorted(test_files):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            if name_re.search(text):
                return True  # can't analyse — assume the reference is enforced
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(text, node) or ""
            if not name_re.search(seg):
                continue
            saw_reference = True
            if not any(_is_unenforced_decorator(d) for d in node.decorator_list):
                return True  # an enforced test names the stub — real contract
    # If no test referenced the stub at all, leave the decision to the caller
    # (no-pinned-tests is handled separately as a no-op refusal). Only when EVERY
    # referencing test was unenforced do we positively report "no contract".
    return not saw_reference


# --- synthesis (the gated search) --------------------------------------------

def _expected_constant(root: Path, test_files: list[str], stub: StubFunction) -> str | None:
    """If every test asserting ``func(...) == <literal>`` pins the SAME literal
    AND that agreement is witnessed by at least TWO DISTINCT argument tuples,
    return the literal's source text (so a constant-return template can be tried
    as a last resort). Otherwise ``None``.

    The two-distinct-tuples floor is what stops a single example overfitting: one
    ``add(3, 4) == 7`` must NOT become ``return 7`` — a single tuple cannot tell
    "the answer is always 7" from "the answer happens to be 7 here", so a bare
    constant is refused until two distinct inputs agree on it (a no-arg MODULE
    function ``k()`` is exempt: its single empty tuple genuinely IS the whole
    input space). A METHOD with no positional params is NOT exempt: ``self`` is
    dropped from ``params`` so ``def width(self)`` reads ``params == ()`` even
    though its result depends on instance state, and the positional templates
    cannot read ``self``. One ``Record(1, "abcd").width() == 4`` must not pin
    ``return 4`` (a second instance ``Record(2, "hello").width()`` would expect a
    different value), so the floor still applies. Conservative: any disagreement
    or a non-literal RHS yields ``None``."""
    literals: set[str] = set()
    arg_tuples: set[str] = set()
    call_eq = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(stub.name)
        + r"\s*\(([^()]*)\)\s*==\s*([^\n#]+)")
    for rel in test_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        excluded = _unenforced_line_ranges(text)
        for m in call_eq.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            if _line_in_ranges(line, excluded):
                continue  # xfail/skip assertion pins no enforceable literal
            lit = _leading_literal(m.group(2))
            if lit is None:
                return None
            literals.add(lit)
            arg_tuples.add(m.group(1).strip())
    if len(literals) != 1:
        return None
    # A genuine no-arg MODULE function has one empty tuple that fully determines
    # its result, so a single witness legitimately pins the constant. Every other
    # function — including a METHOD whose dropped ``self`` makes ``params`` empty
    # while its output still depends on instance state — needs >=2 distinct
    # argument tuples agreeing before a bare constant is trustworthy (one example
    # is not enough to claim "always this", and the templates cannot read self).
    if (stub.params or stub.is_method) and len(arg_tuples) < 2:
        return None
    return next(iter(literals))


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
    # `-B`: never write a `.pyc`. We also purge the module's stale bytecode below.
    # Successive probes rewrite the SAME file within one mtime-second with equal
    # size (e.g. `a + b` -> `a * b`), so a cached `.pyc` would be wrongly reused
    # and the probe would test the PREVIOUS candidate — a determinism/correctness
    # hazard the batch planner exposes by probing many candidates back-to-back.
    cmd = [_python_for(root), "-B", "-m", "pytest", "-q", *test_files]
    try:
        target.write_text(candidate, encoding="utf-8")
        _purge_pyc(target)
        summary = runner.run(str(root), commands=[cmd])
        return bool(summary.ok)
    finally:
        target.write_text(original, encoding="utf-8")
        _purge_pyc(target)


def _purge_pyc(module_path: Path) -> None:
    """Delete any cached bytecode for ``module_path`` so the next import always
    recompiles the just-written source. Removes both the legacy sibling ``.pyc``
    and the ``__pycache__/<stem>.*.pyc`` forms. Best-effort and silent — a probe
    is correct even if a stale file can't be removed (it just recompiles)."""
    try:
        cache_dir = module_path.parent / "__pycache__"
        stem = module_path.stem
        if cache_dir.is_dir():
            for pyc in cache_dir.glob(stem + ".*.pyc"):
                pyc.unlink(missing_ok=True)
        sibling = module_path.with_suffix(".pyc")
        sibling.unlink(missing_ok=True)
    except OSError:
        pass


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

    The search is deterministic: :func:`candidate_bodies` (the parameter-shaped
    templates) in fixed order, then a constant-return candidate LAST (only when
    the tests agree on one literal across >=2 distinct argument tuples). The
    FIRST candidate whose pinned tests all pass wins, so a parameter template
    beats a bare constant. With no pinned tests there is no spec to satisfy —
    refuse immediately.

    Two never-fake-green floors precede the search:

    * **enforceable-contract floor** — if EVERY pinned test touching the stub is
      ``xfail`` / ``skip``, the gate is meaningless (an xfail test stays green for
      any body), so we refuse rather than stamp an unenforced contract verified;
    * **ambiguity floor** — if >=2 fixed templates of DIFFERENT shape both satisfy
      ALL the enforceable witnesses, the witnesses don't determine intent, so we
      refuse (mirror ``cross_file_rename``'s conservatism on an ambiguous spec)."""
    if not test_files:
        return None
    if not _has_enforceable_contract(root, test_files, stub):
        return None  # only xfail/skip tests pin this stub — no real contract
    if _is_ambiguous(root, test_files, stub):
        return None  # witnesses fit >=2 different-shape templates — under-specified
    runner = runner or RunTestsSkill()
    source = (root / module_rel).read_text(encoding="utf-8")
    # Gate against THIS stub's per-symbol node IDs, not the whole pinned file: a
    # shared file's unsynthesizable sibling (its own red node) must not veto this
    # stub when its OWN node passes. Falls back to whole-file paths per file when
    # no node is discoverable (so nothing that used to land stops landing).
    gate = pinned_test_nodes(root, module_rel, stub.name)

    for label, expr in _ordered_candidates(root, test_files, stub):
        candidate = _rewrite_with_body(source, stub, expr)
        if candidate is None:
            continue
        if _candidate_passes(root, module_rel, candidate, gate, runner):
            return candidate
    return None


def ordered_candidate_exprs(root: Path, test_files: list[str],
                            stub: StubFunction) -> list[tuple[str, str]]:
    """Public view of the fixed-order candidate list for ``stub`` — the
    parameter-shaped templates first, then the last-resort constant (when the
    tests pin one literal across >=2 distinct tuples). Used by the per-module
    batch planner to coordinate sibling stubs whose pinned tests share one file
    (where no single stub goes green until the others are filled too)."""
    return _ordered_candidates(root, test_files, stub)


def synthesize_expr_from_witnesses(root: Path, test_files: list[str],
                                   stub: StubFunction) -> str | None:
    """The FIRST fixed-order candidate expr that satisfies ``stub``'s OWN pinned
    witnesses, evaluated in-process — or ``None`` when none does. This is the
    INDEPENDENT per-stub synthesis the mutual-stub planner relies on: a stub's
    body is determined by its own ``func(args) == expected`` assertions alone,
    without running the shared test file (which stays red until every sibling is
    filled too). Deterministic, offline, stdlib-only.

    Evaluation is sandboxed: the candidate is a pure expression over the stub's
    positional parameters with no name access beyond a fixed safe builtin set, so
    a witness like ``double(3) == 6`` is checked by binding ``n = 3`` and
    comparing ``eval('n * 2')`` to ``6``. A candidate is accepted ONLY when it
    matches EVERY witness — never a guess. The composed module is still gated by
    the real suite afterwards (never-fake-green).

    Two never-fake-green floors precede acceptance, the same the pytest-gated
    path applies: an ``xfail``/``skip``-only contract is unenforceable (its
    witnesses are already dropped by :func:`_function_witnesses`, and an all-xfail
    test set is refused outright), and a contract that fits >=2 different-shape
    templates is ambiguous, so we refuse rather than land an arbitrary first."""
    if not _has_enforceable_contract(root, test_files, stub):
        return None  # only xfail/skip tests pin this stub — no real contract
    witnesses = _function_witnesses(root, test_files, stub)
    if not witnesses:
        return None
    evaluable = _evaluable_witnesses(witnesses, stub)
    if evaluable is None:
        return None
    if _is_ambiguous(root, test_files, stub):
        return None  # witnesses fit >=2 different-shape templates — under-specified
    for _label, expr in _ordered_candidates(root, test_files, stub):
        if _expr_matches_all(expr, stub, evaluable):
            return expr
    return None


def can_fill_stub_in_process(root: Path, test_files: list[str],
                             stub: StubFunction) -> bool:
    """A CHEAP, in-process estimate of whether ``stub`` is fillable — no pytest.

    This is the fitness/move-scan oracle: it must be FAST (the develop loop
    measures fitness and enumerates moves once per pass, and the pytest-gated
    ``plan_implement_stub`` is far too slow to run for that) yet it must NOT
    under-count any stub the real (pytest-gated) apply would land — a stub the
    estimate misses would silently stop being offered. So it accepts when EITHER:

    * a non-recursive fixed template matches every witness in-process
      (:func:`synthesize_expr_from_witnesses`), OR
    * a recursion template (factorial/fibonacci), which the pure-expression
      synth cannot evaluate (``__apex_self__`` is not bound), matches every
      witness when evaluated AS a real recursive function in-process
      (:func:`_recursion_matches`). This is the cheap structural recursion check
      that keeps recursion-only stubs (e.g. a factorial body) in the scan.

    The estimate may OVER-count (a stub it accepts that the real per-module gate
    later rejects simply no-ops at apply — already handled), but it never
    UNDER-counts a landable stub. Deterministic, offline, stdlib-only; runs the
    same never-fake-green floors (enforceable contract, ambiguity) as the apply
    path so it never offers a stub the apply would refuse on principle.

    When the witnesses are NOT literal enough to evaluate in-process (a non-literal
    argument or expected value), the in-process synth cannot decide either way —
    but the pytest-gated apply still might land a value-free template (e.g.
    ``s.lower()``). To stay safe (never under-count), such a stub is counted
    CONSERVATIVELY: the move is offered, and the real per-module pytest gate is the
    authority on whether it actually lands (a no-op if it doesn't)."""
    if not _has_enforceable_contract(root, test_files, stub):
        return False  # only xfail/skip tests pin this stub — apply would refuse too
    if synthesize_expr_from_witnesses(root, test_files, stub) is not None:
        return True
    if _recursion_matches(root, test_files, stub):
        return True
    # In-process synthesis couldn't decide. If the witnesses aren't evaluable
    # in-process (non-literal args/expected), the pytest gate might still land a
    # value-free template — count it conservatively rather than under-count. If
    # the witnesses ARE evaluable yet nothing matched, the apply path would refuse
    # too (same templates, same gate), so it is honestly NOT counted.
    return _has_pinned_but_non_evaluable_witnesses(root, test_files, stub)


def _has_pinned_but_non_evaluable_witnesses(root: Path, test_files: list[str],
                                            stub: StubFunction) -> bool:
    """True when ``stub`` has enforceable pinned witnesses that the in-process
    evaluator CANNOT turn into literal ``(args, expected)`` pairs (a non-literal
    call site). Such a contract is undecidable in-process, so the cheap scan
    counts it conservatively (the pytest apply gate decides for real) rather than
    risk under-counting a stub the pytest path could still fill. A stub with no
    enforceable witnesses at all is NOT counted (no contract to satisfy)."""
    witnesses = _function_witnesses(root, test_files, stub)
    if not witnesses:
        return False
    return _evaluable_witnesses(witnesses, stub) is None


def _recursion_matches(root: Path, test_files: list[str],
                       stub: StubFunction) -> bool:
    """True when a recursion template (the ``__apex_self__`` shapes) reproduces
    every enforceable witness for ``stub``, evaluated AS a real recursive function
    in-process (no pytest). The pure-expression synth skips recursion because
    ``__apex_self__`` has no binding; here we wrap each recursion body in an
    actual ``def`` over the stub's parameters so factorial/fibonacci can be
    checked cheaply. Runs the same enforceable-contract / ambiguity floors first,
    so it never offers a stub the apply path would refuse. Deterministic."""
    if not _has_enforceable_contract(root, test_files, stub):
        return False
    witnesses = _function_witnesses(root, test_files, stub)
    evaluable = _evaluable_witnesses(witnesses, stub) if witnesses else None
    if not evaluable:
        return False
    if _is_ambiguous(root, test_files, stub):
        return False
    # Evaluate the recursion only against SMALL-magnitude witnesses: the fibonacci
    # template is EXPONENTIAL, so ``fib(95)`` would never terminate in-process. A
    # recursion-shaped contract is pinned by small base/step cases anyway
    # (``fact(0)==1, fact(5)==120``), so bounding the evaluated witnesses keeps the
    # cheap check fast without missing a real recursion. A contract whose ONLY
    # witnesses are large (e.g. ``grade_letter(95)=='A'``) yields no small witness
    # to check, so recursion is honestly not claimed — and such a contract is not a
    # recursion shape anyway (its expected values are strings, not the recursion's
    # ints). The explicit pytest-gated apply remains the authority for any genuine
    # large-argument recursion that this cheap bound would skip.
    small = [(args, exp) for args, exp in evaluable
             if all(isinstance(a, int) and abs(a) <= _RECURSION_WITNESS_CAP
                    for a in args)]
    if len({args for args, _e in small}) < 2:
        return False  # too few small witnesses to determine a recursion cheaply
    for _label, expr in _ordered_candidates(root, test_files, stub):
        if "__apex_self__" in expr and _recursive_expr_matches_all(expr, stub, small):
            return True
    return False


# Largest |arg| the in-process recursion check evaluates. Factorial (linear) and
# fibonacci (exponential) both stay cheap within this bound; larger witnesses are
# left to the explicit pytest-gated apply path so the cheap scan never hangs.
_RECURSION_WITNESS_CAP = 25


def _recursive_expr_matches_all(expr: str, stub: StubFunction,
                                witnesses: list[tuple[tuple, object]]) -> bool:
    """True when the recursion body ``expr`` (with the ``__apex_self__`` marker)
    yields the expected value for EVERY witness, evaluated as a genuine recursive
    function bound to ``stub``'s parameters. The caller passes only small-magnitude
    witnesses, so factorial/fibonacci stay cheap and always terminate; a deep
    linear recursion is additionally guarded by a temporary recursion-limit.
    Sandboxed to the safe builtin set, like the pure-expression matcher."""
    body = expr.replace("__apex_self__", "__apex_rec__")
    params = ", ".join(stub.params)
    src = f"def __apex_rec__({params}):\n    return {body}\n"
    env: dict = {"__builtins__": _SAFE_BUILTINS}
    try:
        exec(compile(src, "<apex-recursion>", "exec"), env)  # noqa: S102 - fixed templates
        fn = env["__apex_rec__"]
    except Exception:
        return False
    import sys
    prev = sys.getrecursionlimit()
    sys.setrecursionlimit(min(prev, 1000))
    try:
        for args, expected in witnesses:
            try:
                value = fn(*args)
            except Exception:
                return False
            if type(value) is not type(expected) or value != expected:
                return False
        return True
    finally:
        sys.setrecursionlimit(prev)


def module_has_fillable_stub(root: Path, module_rel: str) -> bool:
    """A CHEAP, in-process estimate (no pytest) of whether ``module_rel`` holds at
    least one fillable stub — the oracle the implement-stub fitness/move scan uses
    instead of the slow pytest-gated ``plan_implement_stub``.

    A module qualifies when any of its stubs has pinned tests AND
    :func:`can_fill_stub_in_process` accepts it. Test/fixture files and unreadable
    modules never qualify. Deterministic: stubs are taken in fixed source order.

    HONESTY: this only changes the SCAN cost, never WHAT lands. The actual apply
    still runs the full pytest gate in ``plan_implement_stub`` — a stub this
    estimate counts but the gate later rejects simply no-ops at apply; a stub it
    accepts is exactly the set the apply path can land (it never under-counts a
    landable stub, recursion included)."""
    if _is_test_or_fixture(module_rel):
        return False
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return False
    for stub in find_stub_functions(source):
        tests = pinned_test_files(root, module_rel, stub.name)
        if tests and can_fill_stub_in_process(root, tests, stub):
            return True
    return False


def _evaluable_witnesses(witnesses: list[tuple[str, str]],
                         stub: StubFunction) -> list[tuple[tuple, object]] | None:
    """Parse the witnesses into ``(arg_values, expected_value)`` pairs of real
    Python objects, or ``None`` if any witness's args/expected are not literal
    (a non-literal call site cannot be checked in-process). Each arg tuple must
    have one value per positional parameter."""
    out: list[tuple[tuple, object]] = []
    for args_text, expected_text in witnesses:
        args = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if args is None or expected is _NO_LITERAL:
            return None
        if len(args) != len(stub.params):
            return None
        out.append((args, expected))
    return out or None


_NO_LITERAL = object()


def _literal_tuple(args_text: str) -> tuple | None:
    """Evaluate a comma-separated argument fragment to a tuple of literal values,
    or ``None`` when any argument is not a literal."""
    text = args_text.strip()
    if not text:
        return ()
    try:
        node = ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError):
        return None
    elements = node.elts if isinstance(node, ast.Tuple) else [node]
    out: list[object] = []
    for el in elements:
        try:
            out.append(ast.literal_eval(el))
        except (ValueError, SyntaxError, TypeError):
            return None
    return tuple(out)


def _literal_value(expected_text: str) -> object:
    """Evaluate an expected-value fragment (the RHS of ``==``) to a literal, or the
    sentinel ``_NO_LITERAL`` when it is not a literal."""
    text = expected_text.strip().split("#")[0].strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        return _NO_LITERAL


_SAFE_BUILTINS = {
    "len": len, "min": min, "max": max, "sorted": sorted, "sum": sum,
    "abs": abs, "round": round, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "tuple": tuple,
}


def _expr_matches_all(expr: str, stub: StubFunction,
                      witnesses: list[tuple[tuple, object]]) -> bool:
    """True when ``expr`` (over the stub's parameter names) yields the expected
    value for EVERY witness, evaluated in a sandbox with only safe builtins.
    Recursion templates (``__apex_self__``) cannot be evaluated in-process, so
    they never match here and are left to the real suite gate — keeping this
    helper a strict, no-guess check."""
    if "__apex_self__" in expr:
        return False
    env_globals = {"__builtins__": _SAFE_BUILTINS}
    for args, expected in witnesses:
        local = dict(zip(stub.params, args))
        try:
            value = eval(expr, env_globals, local)  # noqa: S307 - fixed templates only
        except Exception:
            return False
        if type(value) is not type(expected) or value != expected:
            return False
    return True


@dataclass(frozen=True)
class AmbiguityDiagnosis:
    """Why a stub's pinned witnesses are AMBIGUOUS — the data behind a refusal,
    captured so the buyer can be told WHAT to fix, never to change WHAT lands.

    ``exprs`` are the two representative competing body expressions (the first
    two distinct off-witness-diverging shapes, in fixed candidate order).
    ``params`` are the stub's positional parameter names. ``canary`` is the FIRST
    discriminating input tuple — the earliest in the fixed canary order where the
    two exprs' fingerprints differ — and ``values`` are each expr's rendered value
    on that input (``'<err>'`` when it raises). All deterministic: the same
    fixtures yield the same diagnosis, so the rendered reason is stable."""

    exprs: tuple[str, str]
    params: tuple[str, ...]
    canary: tuple
    values: tuple[str, str]


def _is_ambiguous(root: Path, test_files: list[str], stub: StubFunction) -> bool:
    """True when the stub's ENFORCEABLE witnesses are satisfied by >=2 templates
    that DISAGREE on some untested input — the witnesses don't determine intent,
    so any single pick would be an arbitrary guess stamped "verified".

    Two templates that both pass every witness but compute DIFFERENT functions
    (they differ on a canary input outside the witness set) are the harmful
    ambiguity: the thin contract ``is_big(5)==False``, ``is_big(200)==True`` is
    matched by BOTH ``n % 2 == 0`` (parity) and ``n >= 200`` (threshold), which
    disagree on ``is_big(50)`` — neither is trustworthy, so we land nothing
    (mirroring ``cross_file_rename``'s refusal on an ambiguous target). Templates
    that agree EVERYWHERE (``n * 2`` and ``n + n`` both double) are NOT ambiguous —
    they are the same intent spelled two ways, so they never trip the guard.

    The disagreement is detected by evaluating each witness-passing template on a
    fixed canary input set derived deterministically from the witnesses; if two
    of them ever produce different results, the contract is ambiguous. Recursion
    bodies (``__apex_self__``) can't be eval'd here, and the constant last resort
    is excluded — only the genuine competing intents are weighed. With no
    evaluable witnesses there is nothing to disambiguate, so it returns ``False``.

    A thin wrapper over :func:`_ambiguity_diagnosis`: the refuse DECISION is
    exactly "a diagnosis exists", so the same input lands the same nothing whether
    or not the diagnosis is ever rendered (the disclosure is purely additive)."""
    return _ambiguity_diagnosis(root, test_files, stub) is not None


def _ambiguity_diagnosis(root: Path, test_files: list[str],
                         stub: StubFunction) -> AmbiguityDiagnosis | None:
    """The structured ambiguity finding for ``stub`` — ``None`` when the contract
    is NOT ambiguous, else the two representative competing exprs, the first
    discriminating canary input, and each expr's value there.

    This is the single source of truth :func:`_is_ambiguous` wraps: it computes
    the SAME ``matching`` shapes (identity-family collapsed, constant/recursion
    excluded) the bool guard always did, then — instead of discarding everything
    but the verdict — keeps the FIRST pair whose fingerprints diverge and the
    EARLIEST canary at which they do. Deterministic throughout: candidates and
    canaries are in their fixed order, so the chosen pair and input are stable."""
    witnesses = _function_witnesses(root, test_files, stub)
    evaluable = _evaluable_witnesses(witnesses, stub) if witnesses else None
    if not evaluable:
        return None
    matching = _matching_shapes(root, test_files, stub, evaluable)
    if len(matching) < 2:
        return None
    canaries = _canary_inputs(evaluable)
    return _first_divergence(matching, stub, canaries)


def _matching_shapes(root: Path, test_files: list[str], stub: StubFunction,
                     evaluable: list[tuple[tuple, object]]) -> list[str]:
    """The witness-passing templates, ONE per distinct semantic shape, in fixed
    candidate order — the competing intents the ambiguity guard weighs.

    The algebraic-identity family (``a``, ``a + 0``, ``a - 0``, ``a * 1``,
    ``a // 1``, ``a / 1``) is collapsed to ONE shape: they are the same
    passthrough answer spelled different ways, so they must not count as DISTINCT
    competing intents against each other. Without this, a genuine passthrough
    (``identity(5)==5, identity(9)==9``) is matched by several identity-family
    templates and the >=2-shapes guard wrongly refuses ``return a``. A genuinely
    different shape (``a * 2``, ``a + k``, a comparison) is NOT in the family, so
    the guard still refuses it. Constant and recursion candidates are excluded —
    only the genuine competing intents are weighed."""
    matching: list[str] = []
    seen_shapes: set[str] = set()
    for label, expr in _ordered_candidates(root, test_files, stub):
        if label == "constant" or "__apex_self__" in expr:
            continue
        if not _expr_matches_all(expr, stub, evaluable):
            continue
        shape = _identity_canonical_shape(expr, stub)
        if shape in seen_shapes:
            continue  # an identity-family duplicate already represented
        seen_shapes.add(shape)
        matching.append(expr)
    return matching


def _first_divergence(matching: list[str], stub: StubFunction,
                      canaries: list[tuple]) -> AmbiguityDiagnosis | None:
    """The first pair of ``matching`` exprs whose fingerprints differ, with the
    EARLIEST canary at which they do — or ``None`` when every expr computes the
    same function on the probes (NOT ambiguous: same intent spelled many ways).

    Mirrors the bool guard's accumulation EXACTLY: it adds each expr's fingerprint
    in fixed order and stops at the first one that disagrees with an earlier expr,
    so the refuse decision is byte-for-byte unchanged. The earlier expr is the
    first already-seen one whose per-canary values differ, and the discriminating
    canary is the first index at which the two differ — both deterministic."""
    seen: list[tuple[str, tuple]] = []  # (expr, fingerprint) in fixed order
    for expr in matching:
        fp = _expr_fingerprint(expr, stub, canaries)
        for prev_expr, prev_fp in seen:
            idx = _first_diff_index(prev_fp, fp)
            if idx is not None:
                return _build_diagnosis(prev_expr, expr, stub, canaries, idx)
        seen.append((expr, fp))
    return None


def _first_diff_index(a: tuple, b: tuple) -> int | None:
    """The first index where fingerprints ``a`` and ``b`` differ, or ``None`` when
    they are identical (the two exprs compute the same function on every probe).
    Both fingerprints share the canary order, so the index selects a canary."""
    for i, (va, vb) in enumerate(zip(a, b)):
        if va != vb:
            return i
    return None


def _build_diagnosis(expr_a: str, expr_b: str, stub: StubFunction,
                     canaries: list[tuple], idx: int) -> AmbiguityDiagnosis:
    """Assemble the diagnosis for the diverging pair ``(expr_a, expr_b)`` at the
    discriminating canary ``canaries[idx]``: the human-facing value of each expr
    there (``repr`` of the result, or ``'<err>'`` when it raises). Deterministic —
    a pure re-evaluation of two fixed exprs on one fixed input."""
    canary = canaries[idx]
    return AmbiguityDiagnosis(
        exprs=(expr_a, expr_b),
        params=stub.params,
        canary=canary,
        values=(_canary_value(expr_a, stub, canary),
                _canary_value(expr_b, stub, canary)))


def _canary_value(expr: str, stub: StubFunction, canary: tuple) -> str:
    """The human-facing value ``expr`` yields on one canary input: ``repr`` of the
    result, or the stable ``'<err>'`` token when it raises — matching the
    fingerprint's per-canary rendering so the reason agrees with the divergence
    that was detected. Sandboxed to the fixed safe builtins, like every probe."""
    env_globals = {"__builtins__": _SAFE_BUILTINS}
    local = dict(zip(stub.params, canary))
    try:
        return repr(eval(expr, env_globals, local))  # noqa: S307 - fixed templates
    except Exception:
        return "<err>"


def ambiguity_reason(root: Path, test_files: list[str],
                     stub: StubFunction) -> str | None:
    """A one-line, human-readable explanation of WHY ``stub`` was refused for
    ambiguity and HOW to fix it — or ``None`` when the contract is NOT ambiguous.

    Public companion to the (unchanged) :func:`_is_ambiguous` decision: it renders
    the same structured finding the guard uses, naming the two competing body
    expressions, the first discriminating input, and each body's value there, then
    points the buyer at the missing discriminating witness, e.g.::

        ambiguous: `min(a)` and `a[-1]` both satisfy the tests but differ on
        a=[3, 9, 2] (2 vs -2)… add a discriminating test

    Deterministic: identical fixtures yield the identical string (no clock/random,
    offline). Used to disclose an honest refusal without changing what lands."""
    diagnosis = _ambiguity_diagnosis(root, test_files, stub)
    if diagnosis is None:
        return None
    return render_ambiguity_reason(diagnosis)


def render_ambiguity_reason(diagnosis: AmbiguityDiagnosis) -> str:
    """Render an :class:`AmbiguityDiagnosis` to its fixed one-line string. Pure and
    deterministic (no disk, no tests): the buyer-facing wording lives here so the
    in-process diagnosis and any caller render it identically."""
    a, b = diagnosis.exprs
    va, vb = diagnosis.values
    return (f"ambiguous: `{a}` and `{b}` both satisfy the tests but differ on "
            f"{_render_args(diagnosis.params, diagnosis.canary)} "
            f"({va} vs {vb})… add a discriminating test")


def _render_args(params: tuple[str, ...], canary: tuple) -> str:
    """Render the discriminating input as ``name=value`` pairs (``a=[3, 9, 2]``,
    or ``a=5, b=1`` for a multi-arg stub), in parameter order. Falls back to a bare
    ``repr`` of the tuple if the arities ever mismatch (defensive — they never do
    for a synthesized stub). Deterministic: a pure ``repr`` over fixed values."""
    if len(params) != len(canary):
        return repr(canary)
    return ", ".join(f"{name}={value!r}" for name, value in zip(params, canary))


# The algebraic-identity family: expressions over a single parameter ``a`` that
# all evaluate to ``a`` itself. Collapsed to one shape in the ambiguity guard so
# they never count as competing intents against EACH OTHER (a passthrough lands).
_IDENTITY_FAMILY: tuple[tuple[str, ...], ...] = (
    ("",),  # bare ``a``
    ("+", "0"), ("-", "0"), ("*", "1"), ("//", "1"), ("/", "1"),
)


def _identity_canonical_shape(expr: str, stub: StubFunction) -> str:
    """Canonical shape key for ``expr``: every algebraic-identity-family member
    over the stub's single parameter (``a``, ``a + 0``, ``a - 0``, ``a * 1``,
    ``a // 1``, ``a / 1``) collapses to one fixed ``"<identity>"`` token; any
    other expression keys to its own text. Used by the ambiguity guard so the
    identity family is treated as ONE semantic shape, not several competing ones.

    Deterministic and purely syntactic: only a one-parameter stub can have an
    identity family (the templates are built over ``params[0]``), so a
    multi-param expr always keys to itself."""
    if len(stub.params) != 1:
        return expr
    a = stub.params[0]
    text = expr.strip()
    if text == a:
        return "<identity>"
    for op, const in (p for p in _IDENTITY_FAMILY if len(p) == 2):
        if text == f"{a} {op} {const}":
            return "<identity>"
    return expr


def _int_canary_probes(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """Off-witness probe tuples for a single-int-argument contract: each
    witnessed value's neighbours (``v-1``/``v+1``) plus fixed anchors, so two
    bodies that agree on the witnesses but diverge nearby (parity vs threshold)
    are caught. A negative anchor is probed ONLY when a witness is itself
    negative — injecting one for an all-non-negative contract makes ``abs(a)`` /
    ``round(a)`` look like a different intent from a plain passthrough (they
    diverge only at the off-domain negative), wrongly tripping the guard against
    a genuine ``identity(5)==5, identity(9)==9``."""
    extra: set[int] = set()
    for args, _e in witnesses:
        v = args[0]
        extra.update({v - 1, v + 1})
    extra.update({0, 1, 2, 3, 50, 99, 100})
    if any(args[0] < 0 for args, _e in witnesses):
        extra.add(-1)
    return [(v,) for v in sorted(extra)]


def _str_canary_probes(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """Off-witness probe tuples for a single-str-argument contract: for each
    witnessed string emit perturbations that SPLIT the competing string-method
    shapes which coincide on the witnessed values themselves —

    * a surrounding-whitespace variant (``"  " + s + "  "``) distinguishes a
      trailing/leading ``.strip()`` (or ``.lower().strip()``) from a plain
      ``.lower()``/``.upper()``: they agree on a witness with no surrounding
      whitespace but diverge once it is added;
    * a case-flipped variant (``s.swapcase()``) distinguishes ``.upper()`` /
      ``.lower()`` / ``.title()`` from one another and from a passthrough — the
      witnessed casing alone cannot tell ``up("A")=="A"`` (passthrough) from
      ``s.upper()``;
    * a separator-injection variant — only when a separator character already
      appears in a witness — distinguishes ``.replace``/``.split`` family shapes;
    * fixed anchors ``""`` and ``" "`` exercise the empty / whitespace-only edge.

    Each probe is a valid ``str`` input, so two bodies that diverge on it
    genuinely differ in intent and the ambiguity guard honestly refuses an
    under-specified contract (``f("Hello")=="hello", f("World")=="world"`` is
    matched by BOTH ``s.lower()`` and ``s.lower().strip()`` — they diverge on the
    whitespace probe). A contract that pins exactly one shape
    (``up("a")=="A", up("bc")=="BC"`` → only ``s.upper()``) still lands: there is
    no second matching shape to disagree with. Deduped + repr-sorted for
    determinism."""
    extra: set[str] = set()
    seps = {" ", ",", "-", "_", "."}
    for args, _e in witnesses:
        s = args[0]
        extra.add("  " + s + "  ")
        extra.add(s.swapcase())
        if any(ch in s for ch in seps):
            for sep in sorted(seps):
                if sep in s:
                    extra.add(s.replace(sep, "X"))
    extra.update({"", " "})
    return [(v,) for v in sorted(extra)]


def _float_canary_probes(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """Off-witness probe tuples for a single-float-argument contract: for each
    witnessed value emit perturbations that SPLIT the competing numeric shapes —

    * ``-v`` distinguishes ``abs(x)`` from a plain passthrough (they agree on a
      positive witness, diverge on its negation);
    * ``v + 0.5`` and a value carrying an extra decimal place (``v + 0.125``)
      distinguish ``round(x, k)`` precisions and an ``int(x)``-style truncation
      from a passthrough (``f(2.5)==2.5, f(3.5)==3.5`` is matched by ``x``,
      ``abs(x)`` AND ``round(x, 1)`` — they diverge on these probes);
    * fixed anchors ``0.0`` and ``-1.5`` exercise the zero / negative edge.

    Each probe stays in the float domain, so a body that raises is folded to the
    stable ``'<err>'`` fingerprint token by the eval. A contract that pins one
    shape (``round(x, 2)`` with discriminating witnesses) still lands — no second
    matching shape to disagree with. Deduped + sorted for determinism."""
    extra: set[float] = set()
    for args, _e in witnesses:
        v = args[0]
        extra.update({-v, v + 0.5, v + 0.125})
    extra.update({0.0, -1.5})
    return [(v,) for v in sorted(extra)]


def _sequence_canary_probes(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """Off-witness probe tuples for a single-sequence-argument contract:
    reordered variants of each witnessed sequence (reversed, then sorted when its
    elements are mutually orderable). first/last/min/max/sorted/list all agree on
    an already-sorted-and-distinct sequence, so without a reordered probe the
    guard cannot tell ``xs[0]`` from ``min(xs)`` on ``head([1, 2, 3]) == 1``. A
    reordered variant is a valid input of the same type, so two bodies that
    diverge on it genuinely differ in intent. A non-orderable sequence simply
    skips the sorted variant.

    Two further probes discriminate the REDUCTION / JOIN family:

    * an EMPTY variant of each witnessed sequence (``type(seq)()``) splits the
      empty-safe ``max(a, default=k)`` / ``min(a, default=k)`` from a plain
      ``max(a)`` / ``min(a)`` (which raises on empty -> ``<err>``) and from each
      other when their defaults differ;
    * a MULTI-ELEMENT variant (the witnessed sequence with its first element
      duplicated ahead of it) splits the join separators: ``" ".join(a)`` and
      ``"".join(a)`` agree on a one-element list but diverge once two elements are
      joined. Built only for an all-string sequence (a join input), so a numeric
      reduction contract is unaffected."""
    out: list[tuple] = []
    for args, _e in witnesses:
        seq = args[0]
        out.append((type(seq)(reversed(seq)),))
        try:
            out.append((type(seq)(sorted(seq)),))
        except TypeError:
            pass  # heterogeneous/non-orderable — reversed alone still helps
        out.append((type(seq)(),))  # empty edge: splits default= from plain reduce
        if seq and all(isinstance(el, str) for el in seq):
            out.append((type(seq)([seq[0], *seq]),))  # >=2 elems: splits join seps
    return out


def _multi_arg_canary_probes(
    witnesses: list[tuple[tuple, object]],
) -> list[tuple]:
    """Off-witness probe tuples for a >=2-int-argument contract: for each
    witnessed tuple ``(a, b, ...)`` add the REORDERED tuples (every rotation/swap
    among the positions) plus per-position neighbour perturbations
    (``v-1``/``v+1`` on one position, others held fixed), staying inside the
    witnessed sign envelope.

    A thin 2-arg contract (``clamp_low(1, 5) == 1, clamp_low(2, 8) == 2``) is
    matched by BOTH ``a % b`` and ``a or b`` (and others) — they all AGREE on the
    witnessed tuples but DIVERGE on a swapped tuple (``(5, 1)``: ``5 % 1 == 0`` vs
    ``5 or 1 == 5``) or a perturbed one (``(7, 4)``), so this probe set exposes the
    ambiguity and Apex refuses rather than landing an arbitrary coincidental body.

    Sign envelope: a negative/zero perturbation is dropped unless a witness
    already holds a value of that sign at that position, mirroring
    :func:`_int_canary_probes` — never inject an off-domain value that makes a
    body raise (``a % b`` with ``b == 0``) look like a distinct intent against a
    genuine, single-shape contract (``add(2, 3) == 5, add(10, 1) == 11`` stays
    ``a + b``: only one shape passes the witnesses, so there is no ambiguity to
    trip regardless of the probes)."""
    has_neg = any(any(v < 0 for v in args) for args, _e in witnesses)
    has_zero = any(any(v == 0 for v in args) for args, _e in witnesses)
    out: list[tuple] = []
    for args, _e in witnesses:
        out.extend(_probes_for_tuple(tuple(args), has_neg, has_zero))
    return out


def _admit_probe(probe: tuple, has_neg: bool, has_zero: bool) -> bool:
    """True when every component of ``probe`` stays inside the witnessed sign
    envelope: a negative is allowed only when a witness already held a negative,
    a zero only when a witness held a zero. Keeps off-domain values (a zero
    divisor that makes ``a % b`` raise) from faking a distinct intent."""
    for v in probe:
        if v < 0 and not has_neg:
            return False
        if v == 0 and not has_zero:
            return False
    return True


def _probes_for_tuple(args: tuple, has_neg: bool, has_zero: bool) -> list[tuple]:
    """The reordered + per-position-perturbed off-witness probes derived from one
    witnessed argument tuple, each kept only when it stays inside the sign
    envelope (:func:`_admit_probe`). Deterministic ordering."""
    out: list[tuple] = []
    for perm in _ordered_perms(args):
        if perm != args and _admit_probe(perm, has_neg, has_zero):
            out.append(perm)
    for pos in range(len(args)):
        for delta in (-1, 1):
            probe = args[:pos] + (args[pos] + delta,) + args[pos + 1:]
            if _admit_probe(probe, has_neg, has_zero):
                out.append(probe)
    return out


def _ordered_perms(args: tuple) -> list[tuple]:
    """The deterministic, sorted-by-repr set of reorderings of ``args`` — swaps and
    rotations that surface order-sensitivity (``a % b`` vs ``a or b`` diverge on a
    swapped tuple). Bounded to small arities (the witnessed stubs are tiny), and
    deduplicated by repr so a tuple with repeated values yields no spurious dupes."""
    from itertools import permutations

    if len(args) > 4:
        return [args]
    seen: set[str] = set()
    ordered: list[tuple] = []
    for perm in sorted(permutations(args), key=repr):
        key = repr(perm)
        if key not in seen:
            seen.add(key)
            ordered.append(perm)
    return ordered


def _dedup_tuples(probes: list[tuple]) -> list[tuple]:
    """De-duplicate ``probes`` preserving first-seen (deterministic) order. An
    argument tuple may hold an UNHASHABLE value (a ``list``/``dict`` witness, e.g.
    ``head([1, 2, 3])``), so membership keys on each tuple's ``repr`` rather than
    the tuple itself — never crash on an unhashable arg, stay deterministic."""
    seen: set[str] = set()
    ordered: list[tuple] = []
    for p in probes:
        key = repr(p)
        if key not in seen:
            seen.add(key)
            ordered.append(p)
    return ordered


def _canary_inputs(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """A fixed, deterministic set of off-witness probe inputs for the ambiguity
    check, built from the witnessed argument tuples (always included). A single
    int argument adds neighbour/anchor probes (:func:`_int_canary_probes`); a
    single sequence argument adds reordered-sequence probes
    (:func:`_sequence_canary_probes`). A >=2-int-argument contract adds
    reordered/perturbed probes (:func:`_multi_arg_canary_probes`) so a thin
    contract matched by several order-sensitive bodies (``a % b`` vs ``a or b``) is
    detected as ambiguous. Other-typed / mixed args fall back to the witnessed
    tuples alone — two bodies that disagree there already disagree on a witness,
    which the gate catches anyway, so the guard stays conservative (never
    over-refuses)."""
    probes: list[tuple] = [args for args, _expected in witnesses]
    probes.extend(_off_witness_probes(witnesses))
    return _dedup_tuples(probes)


def _off_witness_probes(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """The type-appropriate off-witness probe family for ``witnesses`` (the
    witnessed tuples themselves are added by the caller): single-int neighbours,
    single-str perturbations (whitespace/case/separator —
    :func:`_str_canary_probes`), single-float perturbations
    (:func:`_float_canary_probes`), single-sequence reorderings, all-int
    multi-arg reorder/perturb, or — for a >=2-arg non-all-int contract —
    cross-witness recombination. ``[]`` when no family applies (the guard then
    weighs only the witnessed tuples, staying conservative). Deterministic
    dispatch on arity and component type."""
    arity = len(witnesses[0][0]) if witnesses else 0
    if arity == 1:
        return _single_arg_canary_probes(witnesses)
    if arity >= 2 and _all_int_tuples(witnesses):
        return _multi_arg_canary_probes(witnesses)
    if arity >= 2:
        return _recombination_canary_probes(witnesses)
    return []


def _single_arg_canary_probes(
    witnesses: list[tuple[tuple, object]],
) -> list[tuple]:
    """Off-witness probes for a SINGLE-argument contract, dispatched on the
    argument's homogeneous type: int neighbours (:func:`_int_canary_probes`), str
    perturbations (:func:`_str_canary_probes`), float perturbations
    (:func:`_float_canary_probes`), or sequence reorderings
    (:func:`_sequence_canary_probes`). ``[]`` for a mixed-typed / other-typed
    single arg — the guard then weighs only the witnessed tuples, staying
    conservative. Deterministic dispatch."""
    arg0s = [args[0] for args, _e in witnesses]
    if all(_is_plain_int(v) for v in arg0s):
        return _int_canary_probes(witnesses)
    if all(isinstance(v, str) for v in arg0s):
        return _str_canary_probes(witnesses)
    if all(isinstance(v, float) for v in arg0s):
        return _float_canary_probes(witnesses)
    if all(isinstance(v, (list, tuple)) for v in arg0s):
        return _sequence_canary_probes(witnesses)
    return []


def _recombination_canary_probes(
    witnesses: list[tuple[tuple, object]],
) -> list[tuple]:
    """Off-witness probe tuples for a >=2-argument NON-all-int contract (mixed /
    string / mapping args): for every position take that position's value from one
    witness and the OTHER positions' values from another witness (a cross-witness
    recombination), plus the position-swapped variants of each witnessed tuple.

    Each recombined / swapped tuple keeps each position's WITNESSED TYPE (it reuses
    real witnessed component values), so it is a VALID input the body would accept,
    just off-witness. This is what splits order-/value-sensitive shapes that the
    bare witnessed tuples cannot: ``f"{a}{b}"`` and ``f"{b}{a}"`` agree on a
    single ``("a","b")`` pair but a recombined/swapped pair makes them DIVERGE,
    exposing a genuine order-ambiguity; ``a.get(b)`` vs ``a[b]`` diverge on a
    recombined key that is absent from the recombined mapping. Deterministic:
    source-ordered, deduped by the caller. Bounded to small arities (witnessed
    stubs are tiny)."""
    rows = [tuple(args) for args, _e in witnesses]
    arity = len(rows[0]) if rows else 0
    out: list[tuple] = []
    # Position-swapped variants of each witnessed tuple (order-sensitivity).
    for row in rows:
        for perm in _ordered_perms(row):
            if perm != row:
                out.append(perm)
    # Cross-witness recombination: one position from row i, the rest from row j.
    for i, row_i in enumerate(rows):
        for j, row_j in enumerate(rows):
            if i == j:
                continue
            for pos in range(arity):
                out.append(row_j[:pos] + (row_i[pos],) + row_j[pos + 1:])
    return out


def _all_int_tuples(witnesses: list[tuple[tuple, object]]) -> bool:
    """True when EVERY component of EVERY witnessed argument tuple is a plain int
    (:func:`_is_plain_int`) — the precondition for the multi-arg canary branch.
    A mixed/other-typed tuple falls back to the witnessed tuples alone."""
    return all(_is_plain_int(v) for args, _e in witnesses for v in args)


def _is_plain_int(value: object) -> bool:
    """True for a genuine ``int`` (excluding ``bool``, which subclasses ``int``).
    The canary probes perturb/reorder integers; a ``bool`` is a degenerate
    two-value domain where ``+/-1`` neighbours leave the witnessed range, so it is
    not treated as a probe-able int."""
    return isinstance(value, int) and not isinstance(value, bool)


def _expr_fingerprint(expr: str, stub: StubFunction, canaries: list[tuple]) -> tuple:
    """The tuple of ``(repr(value) or '<err>')`` ``expr`` yields on each canary
    input — a deterministic signature of the FUNCTION the template computes.
    Two templates with equal fingerprints compute the same function on the probe
    set (same intent); differing fingerprints mean they disagree off-witness.
    Evaluation errors are folded into a stable ``'<err>'`` token so a body that
    raises on a canary still produces a comparable signature."""
    env_globals = {"__builtins__": _SAFE_BUILTINS}
    out: list[str] = []
    for args in canaries:
        local = dict(zip(stub.params, args))
        try:
            value = eval(expr, env_globals, local)  # noqa: S307 - fixed templates only
            out.append(f"{type(value).__name__}:{value!r}")
        except Exception:
            out.append("<err>")
    return tuple(out)


def fill_stub_body(source: str, stub: StubFunction, return_expr: str) -> str | None:
    """Public view of the body rewrite: replace ``stub``'s body with ``return
    <return_expr>`` (resolving the ``__apex_self__`` recursion marker) and return
    the new module source, or ``None`` if the edit would not parse. Deterministic
    and pure (no disk, no tests) — the batch planner uses it to compose a
    tentative all-stubs-filled source it then verifies once."""
    return _rewrite_with_body(source, stub, return_expr)


def _ordered_candidates(root: Path, test_files: list[str],
                        stub: StubFunction) -> list[tuple[str, str]]:
    """The full fixed-order candidate list: the parameter-shaped templates FIRST,
    then a constant-return as the LAST resort (and only when ``_expected_constant``
    is satisfied — at least two distinct argument tuples agree on one literal).

    Constant goes last so a parameter-shaped body that ALSO passes the pinned
    tests WINS over a bare literal: ``add(3, 4) == 7`` lands ``a + b`` (intent),
    not ``return 7`` (overfit). A constant only fires when no parameter template
    fits AND the literal is witnessed by >=2 distinct inputs (or the function
    takes no args).

    Value-dependent templates (``n * k``, ``s.replace(a, b)``) are seeded from the
    witnesses parsed from the pinned tests; they only PROPOSE bodies — every one
    is still gated against the tests before it lands."""
    witnesses = _function_witnesses(root, test_files, stub)
    out: list[tuple[str, str]] = list(candidate_bodies(stub, witnesses))
    const = _expected_constant(root, test_files, stub)
    if const is not None:
        out.append(("constant", const))
    return out
