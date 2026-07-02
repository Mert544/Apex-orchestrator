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
import doctest
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
    "synthesize_doctest_body",
    "verify_body_via_doctest",
    "enforceable_examples_for_function",
    "examples_pass",
    "AmbiguityDiagnosis",
    "ambiguity_reason",
    "render_ambiguity_reason",
    "stub_decline_reason",
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
    list is in (lineno, col) order. Returns ``[]`` on a syntax error.

    INTERFACE DECLARATIONS are NOT stubs and are never yielded — filling them
    would land type-incorrect garbage in code the runtime never executes as
    written (a body that can even pass a test-based gate WITHOUT running it: a
    false-green). Three shapes are refused, all conservatively read from the AST:

    * a method of a class that DIRECTLY subclasses ``Protocol`` (any base named
      ``Protocol``, incl. ``typing.Protocol``) — the ``...`` is the structural
      contract, not an unimplemented body;
    * a function/method decorated ``@abstractmethod`` / ``@abc.abstractmethod`` —
      the ``raise NotImplementedError`` IS the abstract declaration;
    * a function/method decorated ``@overload`` / ``@typing.overload`` — the
      ``...`` is an overload SIGNATURE; the real impl follows separately.

    Refusing is always safe (worst case: an under-fill); a genuine module-level or
    plain-class stub in a NON-Protocol, NON-abstract, NON-overload context is
    discovered exactly as before (byte-identical)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = source.splitlines()
    out: list[StubFunction] = []
    for node, is_method, enclosing in _iter_functions(tree):
        if _is_interface_declaration(node, enclosing):
            continue  # Protocol method / @abstractmethod / @overload — never fill
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
    """Yield ``(func_node, is_method, enclosing_class)`` for every function defined
    directly at module level or directly inside a class body. ``enclosing_class``
    is the owning :class:`ast.ClassDef` for a method, or ``None`` at module level —
    the caller needs it to tell a Protocol-interface method from a real stub.
    Nested functions are skipped — their contract is not independently testable
    from outside."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, False, None
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield child, True, node


def _is_interface_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef,
                              enclosing: ast.ClassDef | None) -> bool:
    """True when ``node`` is an INTERFACE DECLARATION rather than a fillable stub:
    a method of a ``Protocol`` class, or a function/method decorated
    ``@abstractmethod`` or ``@overload``. Such bodies (``...`` / ``raise
    NotImplementedError``) are contracts, not unimplemented code — filling them
    lands garbage the runtime never runs as written. Conservative: decided from the
    AST alone, no import/MRO resolution (a refusal is always the safe direction)."""
    if enclosing is not None and _is_protocol_class(enclosing):
        return True
    return _has_refusing_decorator(node)


def _is_protocol_class(cls: ast.ClassDef) -> bool:
    """True when ``cls`` DIRECTLY subclasses ``Protocol`` — any base whose name is
    ``Protocol``, matching both a bare ``Protocol`` (``ast.Name``) and a dotted
    ``typing.Protocol`` (``ast.Attribute``). Conservative by design: a direct
    Protocol base is enough; we do not resolve imports or a transitive MRO."""
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _has_refusing_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``node`` carries an ``@abstractmethod`` or ``@overload`` decorator
    (``abc.abstractmethod`` / ``typing.overload`` included). Matches the bare-name
    (``ast.Name``) and dotted (``ast.Attribute``) forms, and defensively unwraps a
    call form (``ast.Call`` -> ``.func``) though these decorators take no args."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            dec = dec.func
        if isinstance(dec, ast.Name) and dec.id in _REFUSING_DECORATORS:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr in _REFUSING_DECORATORS:
            return True
    return False


# Decorators whose presence means the ``...``/``raise NotImplementedError`` body is
# a DECLARATION, never an unimplemented stub: an abstract method or an overload
# signature. Filling either lands code the runtime never runs as written.
_REFUSING_DECORATORS = frozenset({"abstractmethod", "overload"})


# --- pinned-test discovery ---------------------------------------------------

def _is_test_or_fixture(rel: str) -> bool:
    """True for an example/test/fixture path — files Apex must never edit.

    A ``.pyi`` STUB file is refused here too: every body in a type stub is ``...``
    by definition (it is a signature-only INTERFACE, never executed), so each one
    would look like a fillable stub and get garbage spliced in. Refusing the whole
    file at this path gate is the soundest place — ``find_stub_functions`` sees only
    source text, not the path, so the ``.pyi`` decision must live where the rel IS
    known (this gate feeds the implement-stub scan oracle)."""
    p = rel.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py" or name.endswith(".pyi")
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
        out.extend(_multi_arg_arith_templates(params, witnesses or []))
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
        out.extend(_count_templates(a, witnesses))
    out.extend(_affine_string_templates(a, witnesses))
    out.extend(_constant_index_templates(a, witnesses))
    out.extend(_dict_index_templates(a, witnesses))
    out.extend(_slice_templates(a, witnesses))
    out.extend(_index_templates(a, witnesses))
    out.extend(_one_arg_builtin_templates(a, kind, witnesses))
    out.extend(_compose_index_arith_templates(a, witnesses, simpler=out))
    out.extend(_sorted_index_templates(a, witnesses, simpler=out))
    if kind in (None, "int", "float"):
        out.extend(_clamp_templates(a, witnesses))
    if kind in (None, "iterable"):
        out.extend(_elementwise_map_templates(a, witnesses))
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


def _clamp_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The CLAMP / PIECEWISE family (NEW): bounded shapes the old single-``return``
    engine could not express — a lower clamp ``max(lo, a)``, an upper clamp
    ``min(hi, a)``, the two-sided ``max(lo, min(hi, a))``, and the ``relu``-style
    ternaries ``a if a > k else k`` / ``k if a < k else a``. ``lo``/``hi``/``k`` are
    WITNESS-DERIVED — the flat-region output value where the function stops tracking
    its input (:func:`_clamp_constants`) — never invented.

    OVERFIT FLOOR (the soundness core): a boundary is offered ONLY when the
    witnesses both (a) PIN the flat region with at least TWO DISTINCT inputs that
    saturate to it and (b) PIN the pass-through region with at least one input the
    clamp leaves unchanged. One flat example (``clip(99) == 50``) could equally be a
    constant, a different cap, or a scaling — so a single flat witness never lands a
    clamp; the two-distinct-flat-inputs + one-passthrough requirement is what makes
    the derived boundary trustworthy. Every emitted body is still gate-verified
    in-process AND by the pinned suite, and two competing boundaries that survive
    the witnesses but diverge off-witness are refused by the ambiguity guard (the
    int/float canary probes already perturb each witnessed value's neighbours and
    fixed anchors, so a wrong boundary is exposed). Deterministic: boundaries are
    the sorted distinct flat-region constants; the ternary text is fixed."""
    los, his = _clamp_constants(witnesses)
    out: list[tuple[str, str]] = []
    for lo in los:
        out.append((f"clamp_lo({lo})", f"max({lo}, {a})"))
        out.append((f"relu({lo})", f"{a} if {a} > {lo} else {lo}"))
        out.append((f"floor({lo})", f"{lo} if {a} < {lo} else {a}"))
    for hi in his:
        out.append((f"clamp_hi({hi})", f"min({hi}, {a})"))
    for lo in los:
        for hi in his:
            out.append((f"clamp({lo},{hi})", f"max({lo}, min({hi}, {a}))"))
    return out


def _clamp_constants(witnesses: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """The witness-derived ``(lower_bounds, upper_bounds)`` for the clamp family —
    each a list of literal-constant SOURCE strings, sorted and de-duplicated, or
    EMPTY when the overfit floor is not met.

    A single-number witness ``(v, e)`` is classified by comparing the output to the
    input: ``e > v`` means the lower clamp fired (``e`` is a ``lo`` candidate), ``e
    < v`` means the upper clamp fired (``e`` is a ``hi`` candidate), ``e == v`` is a
    pass-through. A bound is returned ONLY when at least TWO DISTINCT inputs
    saturate to the SAME single bound value AND at least one witness passes through
    unchanged — so a lone flat example, a contract with no pass-through region (a
    bare constant in disguise), or two inconsistent flat values never yield a
    boundary. Non-numeric / multi-arg / non-literal witnesses are ignored (they
    cannot establish a numeric boundary). Deterministic."""
    passthrough = False
    lo_inputs: dict[object, set] = {}
    hi_inputs: dict[object, set] = {}
    for args_text, expected_text in witnesses:
        classified = _clamp_witness_kind(args_text, expected_text)
        if classified is None:
            return [], []  # a non-numeric / non-literal witness — no boundary
        kind, v, expected = classified
        if kind == "pass":
            passthrough = True
        elif kind == "lo":
            lo_inputs.setdefault(expected, set()).add(v)
        else:
            hi_inputs.setdefault(expected, set()).add(v)
    if not passthrough:
        return [], []  # no pass-through region — a flat-only contract is a constant
    los = sorted(repr(k) for k, ins in lo_inputs.items() if len(ins) >= 2)
    his = sorted(repr(k) for k, ins in hi_inputs.items() if len(ins) >= 2)
    return los, his


def _clamp_witness_kind(args_text: str,
                        expected_text: str) -> tuple[str, object, object] | None:
    """Classify ONE single-number clamp witness into ``("pass"|"lo"|"hi", input,
    output)`` — pass-through (``e == v``), lower-clamp saturation (``e > v``), or
    upper-clamp saturation (``e < v``) — or ``None`` when the witness is not a
    single numeric ``(input, output)`` literal pair (multi-arg, non-literal, or a
    ``bool``/non-number). Pure and deterministic; the boundary value is the output
    ``e``."""
    value = _literal_tuple(args_text)
    expected = _literal_value(expected_text)
    if value is None or len(value) != 1 or expected is _NO_LITERAL:
        return None
    v = value[0]
    if isinstance(v, bool) or isinstance(expected, bool):
        return None
    if not isinstance(v, (int, float)) or not isinstance(expected, (int, float)):
        return None
    if expected == v:
        return "pass", v, expected
    if expected > v:
        return "lo", v, expected
    return "hi", v, expected


def _elementwise_map_templates(a: str,
                               witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The ELEMENT-WISE MAP / REDUCTION family (NEW): list comprehensions and
    scalar reductions over an iterable arg — shapes the old engine, which emits a
    single non-comprehension ``return`` expr, could not produce. The per-element
    transform pool is FIXED and small (mirroring the string-method whitelist
    discipline): identity is skipped (a plain passthrough already covers it),
    leaving ``x * k`` / ``x + k`` (witness-derived ``k``), ``abs(x)``, ``-x``,
    ``str(x)``, ``x.strip()``, ``x.lower()``, and the reductions ``sum(x * x for x
    in a)`` / ``sum(abs(x) for x in a)``.

    HASHSEED SAFETY (load-bearing): every output here is a LIST or a SCALAR, never a
    ``set``/``frozenset`` and never a set-iteration-ordered value — the same
    order-reproducibility discipline that makes the file withhold ``set(a)``. A
    comprehension iterates its argument in the argument's own order, so the landed
    bytes are identical across ``PYTHONHASHSEED`` values.

    OVERFIT FLOOR: the witness-derived ``x * k`` / ``x + k`` shapes bake the
    witnessed ``k``, so they are offered only under the >=2-distinct-tuple floor
    (:func:`_string_floor_met`) — a single ``[1, 2] -> [2, 4]`` cannot pin ``x * 2``
    alone. The value-free transforms need no floor (a non-matching one is rejected
    by the gate; two that diverge off-witness are refused by the sequence canary
    probes). Every body is still gate-verified in-process (``_expr_matches_all``
    evaluates list outputs type-exactly) AND by the pinned suite. Deterministic: the
    transform pool is fixed, constants sorted."""
    out: list[tuple[str, str]] = []
    out.append(("map(abs)", f"[abs(x) for x in {a}]"))
    out.append(("map(-x)", f"[-x for x in {a}]"))
    out.append(("map(x*x)", f"[x * x for x in {a}]"))
    out.append(("map(str)", f"[str(x) for x in {a}]"))
    out.append(("map(strip)", f"[x.strip() for x in {a}]"))
    out.append(("map(lower)", f"[x.lower() for x in {a}]"))
    out.append(("map(upper)", f"[x.upper() for x in {a}]"))
    out.append(("sum(x*x)", f"sum(x * x for x in {a})"))
    out.append(("sum(abs)", f"sum(abs(x) for x in {a})"))
    if _string_floor_met(witnesses):
        for k in _numeric_constants(witnesses):
            out.append((f"map(x*{k})", f"[x * {k} for x in {a}]"))
            out.append((f"map(x+{k})", f"[x + {k} for x in {a}]"))
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
    mined = _replace_templates(a, witnesses)
    out.extend(mined)  # the grounded (old, new) wins — emitted FIRST, before the noise
    strings = _string_constants(witnesses)
    for old, new in _ordered_string_pairs(strings):
        if mined:
            continue  # a unique grounded pair fired — the literal cross-product DEFERS
        out.append((f"replace({old},{new})", f"{a}.replace({old}, {new})"))
        out.append((f"lower.replace({old},{new})",
                    f"{a}.lower().replace({old}, {new})"))
    for sep in strings:
        out.append((f"split({sep})", f"{a}.split({sep})"))
    out.extend(_str_predicate_templates(a, witnesses))
    out.extend(_str_classification_templates(a, witnesses))
    out.extend(_count_templates(a, witnesses))
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


# The standard nullary ``str`` classifier methods, in FIXED order so the search is
# deterministic. Each takes no argument and returns a real ``bool`` — the structure
# a string-classification predicate (``is_num``, ``is_alpha``…) actually has, not a
# memorized lookup. ``str.<name>()`` is the whole template space this family spans.
_STR_CLASSIFIER_METHODS: tuple[str, ...] = (
    "isdigit", "isalpha", "isalnum", "isupper", "islower", "isspace", "istitle",
)


def _str_classification_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg STRING-CLASSIFICATION family: ``return a.<method>()`` for the ONE
    nullary ``str`` classifier — ``isdigit`` / ``isalpha`` / ``isalnum`` / ``isupper``
    / ``islower`` / ``isspace`` / ``istitle`` — that reproduces EVERY witness's
    expected bool. ``is_num('123') == True, is_num('12a') == False, is_num('') ==
    False`` lands ``s.isdigit()`` — the actual ``str`` property the witnesses
    describe, found (never a memorized map) by testing each classifier against the
    pairs.

    Sibling of :func:`_str_predicate_templates`: same str-only family, same
    DISCRIMINATING contract (at least one ``True`` AND one ``False`` —
    :func:`_discriminating_str_predicate_witnesses`; an all-``True`` / all-``False``
    contract collapses to a constant another family owns, refused here), and the
    same >=2-distinct-witness overfit floor (:func:`_string_floor_met`). The body
    returns a real ``bool``, so there is no domain/raise issue.

    AMBIGUITY: a classifier is emitted ONLY when it is the UNIQUE method reproducing
    every witness. If TWO different classifiers both fit all witnesses (e.g.
    ``isdigit`` and ``isalnum`` on all-digit ``True`` strings), the witnesses cannot
    tell which property is meant, so this family emits NOTHING rather than guess —
    the never-fake-green refusal the prefix/suffix miner makes when no single ``k``
    fits. The chosen method is still gated against all pinned tests and the
    off-witness str canary (:func:`_str_canary_probes`) by the caller, so a
    classifier that merely coincides on the witnesses but diverges elsewhere is
    rejected, never landed. With NO witness list (the structural view) nothing is
    mined — there is no expected bool to verify against. Deterministic: the methods
    are tried in fixed order and at most one body is returned."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _discriminating_str_predicate_witnesses(witnesses)
    if pairs is None:
        return []
    matches = [m for m in _STR_CLASSIFIER_METHODS if _classifier_reproduces_all(m, pairs)]
    if len(matches) != 1:
        return []  # zero fits (no body) or >=2 fit (ambiguous) — refuse, never guess
    method = matches[0]
    return [(f"{method}()", f"{a}.{method}()")]


def _classifier_reproduces_all(method: str, pairs: list[tuple[str, bool]]) -> bool:
    """True when the nullary ``str`` classifier ``method`` yields each pair's expected
    bool for EVERY ``(str_arg, expected_bool)`` in ``pairs`` — the witness-true check
    that lets one method be chosen. Pure and total: ``getattr(s, method)()`` of a
    fixed classifier name on a ``str`` always returns a ``bool`` and never raises.
    Deterministic — a value-free property read per witness, no clock/random."""
    return all(getattr(s, method)() is expected for s, expected in pairs)


def _count_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg OCCURRENCE-COUNT family: ``return a.count(k)`` for the ONE constant
    sub-element / substring ``k`` whose ``.count`` reproduces EVERY witness's expected
    int. ``n_l('hello') == 2, n_l('world') == 1, n_l('xyz') == 0`` lands
    ``return s.count('l')`` — the element actually counted, MINED from the witness
    inputs (every substring / element present) and VERIFIED against every pair, never a
    memorized map. The arg may be a ``str`` (substring count) or a ``list`` / ``tuple``
    (element count); both ``.count`` returns a real ``int``.

    Sibling of :func:`_str_classification_templates`: the witness-DERIVED ``k`` is baked
    into the body, so it carries the same >=2-distinct-witness overfit floor
    (:func:`_string_floor_met`). The expected ints must VARY — an all-equal contract
    (``f('a') == 1, f('b') == 1``) collapses to a constant the constant-last fallback
    owns, so it is refused here rather than baking a coincidental ``k``.

    AMBIGUITY: ``k`` is emitted ONLY when it is the UNIQUE survivor reproducing every
    witness. If TWO distinct ``k`` both reproduce all witnesses, the witnesses cannot
    tell which is meant, so this family emits NOTHING rather than guess — the
    never-fake-green refusal the prefix/classifier miners make. The chosen ``k`` is
    still gated against all pinned tests and the off-witness str / sequence canary
    probes by the caller, so a ``k`` that merely coincides on the witnesses but diverges
    elsewhere is rejected, never landed. With NO witness list (the structural view)
    nothing is mined. Deterministic: candidates are mined in fixed (sorted) order and at
    most one body is returned, type-exact (``str.count`` / ``list.count`` give ``int``)."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _count_witness_pairs(witnesses)
    if pairs is None:
        return []
    survivors = [k for k in _count_candidates(pairs)
                 if all(arg.count(k) == expected for arg, expected in pairs)]
    if len(survivors) != 1:
        return []  # zero fits (no body) or >=2 fit (ambiguous) — refuse, never guess
    return [(f"count({survivors[0]!r})", f"{a}.count({survivors[0]!r})")]


def _count_witness_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[object, int]] | None:
    """The ``(arg, expected_int)`` pairs for the count miner, or ``None`` when the
    family cannot be mined. Every witness must be ONE LITERAL ``str`` / ``list`` /
    ``tuple`` argument with a LITERAL ``int`` expected value (a ``bool`` is
    type-distinct — a ``.count`` result is a plain ``int``), and the expected ints must
    VARY (not all equal, else the contract is a constant another family owns). A
    non-literal, multi-arg, wrong-typed, or all-equal shape yields ``None`` — never
    guessed. Deterministic: source order."""
    out: list[tuple[object, int]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or not isinstance(value[0], (str, list, tuple)):
            return None
        if type(expected) is not int:
            return None
        out.append((value[0], expected))
    if len({expected for _arg, expected in out}) < 2:
        return None  # all-equal expected -> a constant, not a count
    return out


def _count_candidates(pairs: list[tuple[object, int]]) -> list[object]:
    """The candidate ``k`` values for ``a.count(k)``, mined from the witness inputs in a
    fixed (sorted) order: every NON-EMPTY contiguous substring of each witnessed string,
    or every distinct element of each witnessed list / tuple. The empty substring is
    excluded — ``s.count('') == len(s) + 1`` is degenerate, never a real occurrence.
    De-duplicated; strings are sorted, sequence elements sorted when mutually orderable
    (else left in first-seen order). Deterministic, total — a pure scan of the
    witnessed values, no clock/random."""
    if pairs and isinstance(pairs[0][0], str):
        subs: set[str] = set()
        for arg, _expected in pairs:
            for i in range(len(arg)):
                for j in range(i + 1, len(arg) + 1):
                    subs.add(arg[i:j])
        return sorted(subs)
    elements: list[object] = []
    for arg, _expected in pairs:
        for el in arg:
            if el not in elements:
                elements.append(el)
    try:
        return sorted(elements)
    except TypeError:
        return elements  # heterogeneous / non-orderable — first-seen order


def _replace_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg witness-DERIVED ``return a.replace(old, new)`` family: the ONE
    constant ``(old, new)`` pair MINED from the input->output transformation that,
    applied to EVERY witnessed input, reproduces EVERY expected output. ``slug('a b')
    == 'a-b', slug('c d e') == 'c-d-e'`` lands ``s.replace(' ', '-')`` — the single
    substitution the witnesses actually describe, derived (never the combinatorial
    cross-product guess :func:`_ordered_string_pairs` makes) by reading the changed
    span of a seed witness and INTERSECTING it across the rest.

    Sibling of :func:`_count_templates`: the witness-DERIVED pair is baked into the
    body, so it carries the same >=2-distinct-witness overfit floor
    (:func:`_string_floor_met`, applied by the caller) and the same UNIQUE-survivor
    discipline. The outputs must actually DIFFER from the inputs for at least one
    witness (an ``out == in`` contract is the identity / another family — refused via
    :func:`_replace_witness_pairs`), and the degenerate empty ``old`` (``replace('',
    x)`` inserts everywhere) is excluded from the candidate pool.

    AMBIGUITY: a pair is emitted ONLY when it is the UNIQUE survivor reproducing every
    witness (:func:`_replace_pair_constant`). If TWO distinct ``(old, new)`` both
    reproduce all witnesses (``f('cab') == 'ccb', f('dab') == 'dcb'`` admits both
    ``'a'->'c'`` and ``'ab'->'cb'``), the witnesses cannot tell which span is meant, so
    this family emits NOTHING rather than guess — the never-fake-green refusal the
    count / classifier miners make. The chosen pair is still gated against all pinned
    tests and the off-witness str canary (:func:`_str_canary_probes`) by the caller, so
    a pair that merely coincides on the witnessed values but diverges elsewhere is
    rejected, never landed. With NO witness list (the structural view) nothing is
    mined. Deterministic: candidate olds mined in fixed (sorted) order, type-exact
    (``str.replace`` gives ``str``); at most one body returned."""
    pairs = _replace_witness_pairs(witnesses)
    if pairs is None:
        return []
    found = _replace_pair_constant(pairs)
    if found is None:
        return []
    old, new = found
    return [(f"replace({old!r},{new!r})", f"{a}.replace({old!r}, {new!r})")]


def _replace_witness_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[str, str]] | None:
    """The ``(input_str, output_str)`` pairs for the replace miner, or ``None`` when
    the family cannot be mined. Every witness must be ONE LITERAL ``str`` argument with
    a LITERAL ``str`` expected value, and at least one output must DIFFER from its input
    (an all-``out == in`` contract is the identity / a value-free chain another family
    owns, refused here rather than mining a no-op ``replace``). A non-literal, multi-arg,
    or non-``str`` shape yields ``None`` — never guessed. Deterministic: source order."""
    out: list[tuple[str, str]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or not isinstance(value[0], str):
            return None
        if type(expected) is not str:
            return None
        out.append((value[0], expected))
    if not any(inp != exp for inp, exp in out):
        return None  # out == in for every witness -> identity, not a substitution
    return out


def _replace_pair_constant(pairs: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The single constant ``(old, new)`` for ``a.replace(old, new)``, or ``None`` when
    no UNIQUE pair reproduces every witness. Candidates are mined from the seed (first)
    witness's changed span (:func:`_replace_pair_candidates`) and each is VERIFIED to
    satisfy ``inp.replace(old, new) == out`` for EVERY witness; only the survivors that
    DISTINCTLY differ are weighed. Returns the lone survivor, or ``None`` when zero fit
    (no real substitution explains the contract) OR >=2 distinct pairs fit (ambiguous —
    the witnesses cannot tell which span is meant, so refuse rather than guess).
    Deterministic, total — a pure scan in sorted candidate order, no clock/random."""
    survivors = [
        (old, new) for old, new in _replace_pair_candidates(pairs)
        if all(inp.replace(old, new) == out for inp, out in pairs)
    ]
    distinct = sorted(set(survivors))
    if len(distinct) != 1:
        return None  # zero fits (no body) or >=2 fit (ambiguous) — refuse, never guess
    return distinct[0]


def _replace_pair_candidates(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The candidate ``(old, new)`` pairs for ``a.replace(old, new)``, mined from the
    SEED (first) witness in a fixed (sorted) order: every NON-EMPTY contiguous substring
    ``old`` of the seed input is paired with the ``new`` that segment-joining implies
    (:func:`_replace_new_for_old`). The empty ``old`` is excluded — ``replace('', x)``
    inserts ``x`` between every character, a degenerate non-substitution — and a no-op
    ``new == old`` is dropped (it changes nothing). De-duplicated and sorted, so the
    miner is deterministic. The candidates are only PROPOSED here; the caller verifies
    each against EVERY witness before any survives."""
    if not pairs:
        return []
    seed_in, seed_out = pairs[0]
    olds = {seed_in[i:j] for i in range(len(seed_in))
            for j in range(i + 1, len(seed_in) + 1)}
    out: list[tuple[str, str]] = []
    for old in sorted(olds):
        if not old:
            continue  # empty old -> degenerate insert-everywhere, excluded
        new = _replace_new_for_old(seed_in, seed_out, old)
        if new is not None and new != old:
            out.append((old, new))
    return out


def _replace_new_for_old(inp: str, out: str, old: str) -> str | None:
    """The unique ``new`` such that ``inp.replace(old, new) == out``, or ``None`` when no
    single ``new`` reproduces ``out`` for this ``old``. ``inp.replace(old, new)`` is
    ``new.join(inp.split(old))``: the fixed segments ``inp.split(old)`` must tile ``out``
    in order, separated by a CONSTANT ``new`` whose length is fixed by the length budget
    (``len(out) - sum(segment lengths)`` spread over the separators). When the segments
    do not tile ``out``, the separators disagree, or the budget is negative / not evenly
    divisible, no such ``new`` exists. Deterministic, total — a pure character walk, no
    clock/random."""
    if not old:
        return None  # empty old -> degenerate insert-everywhere, never a substitution
    segs = inp.split(old)
    n_sep = len(segs) - 1
    if n_sep < 1:
        return None  # old absent from inp -> not a candidate here
    budget = len(out) - sum(len(s) for s in segs)
    if budget < 0 or budget % n_sep != 0:
        return None
    width = budget // n_sep
    pos = 0
    new: str | None = None
    for i, seg in enumerate(segs):
        if out[pos:pos + len(seg)] != seg:
            return None  # a fixed segment does not appear where it must
        pos += len(seg)
        if i < n_sep:
            gap = out[pos:pos + width]
            if new is None:
                new = gap
            elif gap != new:
                return None  # the separators between segments disagree
            pos += width
    return new if pos == len(out) else None


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


def _dict_index_templates(a: str, witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The 1-arg DICT-KEY family: ``return a[k]`` for a fixed mapping KEY ``k`` mined
    from the witnesses — the value stored under a CONSTANT key in EVERY witnessed
    ``dict``. ``port({'host': 'a', 'port': 80}) == 80, port({'host': 'b', 'port': 443})
    == 443`` lands ``return d['port']`` — a value no sequence index, slice, or
    reduction template can spell (the argument is a mapping, not a sequence). It is the
    mapping counterpart of the sequence :func:`_constant_index_templates`, and the two
    are MUTUALLY EXCLUSIVE: the sequence miner rejects a ``dict`` argument (its type gate
    is ``list`` / ``tuple`` / ``str``) and this miner rejects a non-``dict`` argument, so
    a given witness set feeds at most one of them.

    Keys come from :func:`_dict_index_constants` — the TYPE-EXACT intersection of the
    keys whose value reproduces that witness's expected value, restricted to ``str`` /
    ``int`` keys (a ``bool`` is excluded — type-distinct from ``int``). The mined key
    reproduces every witness by construction (the caller still gates it against all
    pinned tests, never-fake-green).

    HASHSEED-SAFE: ``d[k]`` reads ONE key by hash lookup and NEVER iterates the mapping,
    so its value is independent of ``PYTHONHASHSEED`` — UNLIKE the forbidden ``set(a)`` /
    ``list(set(a))`` shapes (whose iteration order is hash-seed-dependent and therefore
    non-deterministic). Landing ``d[k]`` is sound under the determinism invariant.

    OVERFIT FLOOR + two never-fake-green guards live in :func:`_dict_index_constants`:
    the >=2-distinct-witness floor (:func:`_string_floor_met`), a VARY-VALUES guard (the
    mined key's value must DIFFER across witnesses, else the contract is a constant the
    constant-last fallback owns — and a ``dict`` arg has an EMPTY canary set, so this
    ambiguity is invisible to the off-witness guard and MUST be refused at mine time),
    and a UNIQUE-survivor guard (>1 surviving key -> refuse: the witnesses cannot tell
    which key is meant). Deterministic: at most one key, ``repr``-sorted."""
    out: list[tuple[str, str]] = []
    for k in _dict_index_constants(witnesses):
        out.append((f"dict_index[{k!r}]", f"{a}[{k!r}]"))
    return out


def _dict_index_survivor(common: "set[_Hashed] | None") -> list[object]:
    """The single surviving mined dict key as a one-element list, or ``[]``.

    GUARD 2 — UNIQUE survivor: more than one key surviving the type-exact
    intersection means the witnesses cannot tell which key is meant, so NOTHING
    is mined (parity with the unique-survivor discipline; never a guess).
    Deterministic: ``repr``-sorted."""
    survivors = sorted((h.value for h in (common or set())), key=repr)
    return survivors if len(survivors) == 1 else []


def _dict_index_constants(witnesses: list[tuple[str, str]]) -> list[object]:
    """The fixed mapping keys ``k`` to try in ``a[k]``, mined as the TYPE-EXACT
    INTERSECTION over the witnesses of the ``str`` / ``int`` keys whose value equals that
    witness's expected value. ``port({'host': 'a', 'port': 80}) == 80`` contributes the
    key ``'port'`` (the only key whose value type-exactly equals ``80``); intersecting
    with ``port({'host': 'b', 'port': 443}) == 443``'s ``{'port'}`` yields ``['port']``
    -> ``d['port']``.

    Each witness must be a single ``dict`` argument (the type gate FLIPS relative to the
    sequence :func:`_constant_index_constants`, making the two mutually exclusive) with a
    LITERAL expected value; any witness that is not (a non-literal, multi-arg, or
    non-``dict`` shape) yields NO key — the family cannot be mined then, never guessed. A
    key counts only when it is a ``str`` or ``int`` (a ``bool`` key is excluded — it is
    type-distinct from ``int``) AND its value's TYPE matches the expected value's type
    exactly (``1`` does not match ``True``), mirroring the accept-gate's type-exact
    comparison so a mined key can never imply a value the gate would reject. ``_Hashed``
    wraps each key so a type-exact set intersection is sound (``1`` never collides with
    ``True``, and an unhashable-looking key stays in its own type bucket).

    GUARD 1 — VARY-VALUES: the expected values must VARY across the witnesses (mirroring
    :func:`_count_witness_pairs` / :func:`_compose_witness_pairs`). An all-equal-value
    contract is a CONSTANT the constant-last fallback owns; landing ``a[k]`` over it would
    be fake-green — and crucially a ``dict`` argument has an EMPTY off-witness canary set
    (:func:`_single_arg_canary_probes`), so this ambiguity is INVISIBLE to the ambiguity
    guard and MUST be refused here, at mine time.

    GUARD 2 — UNIQUE survivor: if MORE THAN ONE key survives the intersection, the
    witnesses cannot tell which key is meant (parity with the unique-survivor discipline
    in :func:`_count_templates`), so NOTHING is mined — never a guess.

    Gated behind the >=2-distinct-witness overfit floor (:func:`_string_floor_met`).
    Deterministic: ``repr``-sorted; an empty / single / non-``dict`` witness set, an
    all-equal-value contract, or a >1-key intersection all yield ``[]``."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _dict_index_pairs(witnesses)
    if pairs is None:
        return []  # un-mineable shape, or GUARD 1 (all-equal value) fired in the helper
    common: set[_Hashed] | None = None
    for mapping, expected in pairs:
        keys = {
            _Hashed(key) for key, val in mapping.items()
            if _dict_key_kind_ok(key)
            and type(val) is type(expected) and val == expected
        }
        common = keys if common is None else (common & keys)
        if not common:
            return []
    return _dict_index_survivor(common)  # GUARD 2: unique survivor or []


def _dict_index_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[dict, object]] | None:
    """The ``(mapping, expected)`` pairs for the dict-key miner, or ``None`` when the
    family cannot be mined. Every witness must be ONE LITERAL ``dict`` argument (the
    type gate FLIPS relative to the sequence miner) with a LITERAL expected value; a
    non-literal, multi-arg, or non-``dict`` shape yields ``None`` — never guessed.

    GUARD 1 (VARY-VALUES) lives here: the expected values must VARY across the witnesses
    (mirroring :func:`_count_witness_pairs`). An all-equal-value contract is a CONSTANT
    the constant-last fallback owns; since a ``dict`` argument has an EMPTY off-witness
    canary set, that ambiguity is invisible to the guard and MUST be refused at mine time
    (``None``), else the dict-index body would be stamped fake-green over a real constant.
    Deterministic: source order."""
    out: list[tuple[dict, object]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or expected is _NO_LITERAL:
            return None
        if not isinstance(value[0], dict):
            return None
        out.append((value[0], expected))
    if len({_Hashed(e) for _m, e in out}) < 2:
        return None  # GUARD 1: all-equal value -> a constant, not a dict-key read
    return out


def _dict_key_kind_ok(key: object) -> bool:
    """True when ``key`` is a mineable dict key for ``a[k]``: a ``str`` or a non-``bool``
    ``int``. A ``bool`` is excluded — it is type-distinct from ``int`` (mirroring the
    type-exact accept gate), and any other key type (``float`` / ``tuple`` / ``None``) is
    out of scope for this family. Deterministic, total."""
    if isinstance(key, bool):
        return False
    return isinstance(key, (str, int))


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


def _compose_index_arith_templates(
    a: str, witnesses: list[tuple[str, str]],
    simpler: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """The 1-arg BOUNDED 1-LEVEL COMPOSITIONAL family: ``return a[k] <op> c`` (a
    constant index followed by a scalar arithmetic op) or ``return len(a) <op> c``
    (a length followed by the same), for the ONE composition that reproduces EVERY
    witness's expected int. ``double_first([5, 9]) == 10, double_first([0, 1]) == 0,
    double_first([7]) == 14`` lands ``return xs[0] * 2`` — a body neither the
    constant-index atom (:func:`_constant_index_templates`) nor the scalar-arith atom
    (:func:`_scalar_arith_templates`) can spell alone, because it is their COMPOSITION.

    Composes the EXISTING sound atoms — the constant index ``a[k]`` over a BOUNDED
    index set (:func:`_compose_index_set`: only indices valid for the shortest
    witnessed sequence, plus ``0``/``1``/``-1``) and ``len(a)`` — with the scalar-arith
    ``(op, c)`` derivation (:func:`_arith_survivors`), ``op`` restricted to ``+``/``-``
    (collapsed into one additive family by sign) and ``*`` (NO ``/``, NO ``**`` — those
    refusals stay locked). ``c`` is derived from the ATOM value the same way
    :func:`_derived_constants` derives a scalar constant, bounded to the same window,
    and the identity ``+ 0`` / ``* 1`` are never offered (they are the bare atom another
    family owns, so a composition never shadows a simpler atom that already fit).

    SOUNDNESS comes from witness-verification, not from trusting the composition: EVERY
    candidate body is evaluated end-to-end against ALL witnesses before emit, type-exact
    (``int`` only). Carries the same discipline as the count / index siblings — the
    >=2-distinct-witness overfit floor (:func:`_string_floor_met`); the expected ints
    must VARY (an all-equal contract collapses to a constant another family owns,
    refused via :func:`_compose_witness_pairs`); a 1-arg ``str`` / ``list`` / ``tuple``
    contract only (an int arg has no ``[k]`` / ``len``); an index out of range for some
    witness is simply not a candidate (never an exception). AMBIGUITY: a body is emitted
    ONLY when exactly one composition (distinct expr) survives — if two genuinely
    different ``(k, op, c)`` both reproduce every witness, the family REFUSES rather than
    guess. The chosen body is still gated against all pinned tests and the off-witness
    sequence / str canary by the caller, never-fake-green. With NO witness list (the
    structural view) nothing is mined. Deterministic: bounded indices and constants in
    sorted order, at most one body.

    NO-SHADOW: a composition is a LAST RESORT — it DEFERS to any simpler template
    (``simpler``, the atoms already offered) that ALSO reproduces every witness. A
    composition that merely COINCIDES with a simpler atom on a thin contract
    (``total([1, 2, 3]) == 6, total([4]) == 4`` is ``sum(xs)``, but ``len(xs) + 3``
    coincidentally fits the two points) would otherwise inject a rival shape that makes
    the gate refuse the genuine atom — so when a simpler body already fits
    (:func:`_simpler_template_fits`), this family abstains entirely and never
    shadows/destabilizes it. The composition fires ONLY for a contract no atom solves
    (the genuine ``double_first`` gap)."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _compose_witness_pairs(witnesses)
    if pairs is None:
        return []
    survivors = _compose_arith_survivors(a, pairs)
    distinct = {expr for _sig, expr in survivors}
    if len(distinct) != 1:
        return []  # zero fits (no body) or >=2 genuinely-different fit (ambiguous)
    if _simpler_template_fits(a, simpler or [], witnesses):
        return []  # a simpler atom already fits — never shadow/destabilize it
    return [("compose", survivors[0][1])]


def _sorted_index_templates(
    a: str, witnesses: list[tuple[str, str]],
    simpler: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """The 1-arg ORDER-STATISTIC family: ``return sorted(a)[k]`` for the ONE constant
    index ``k`` whose ``sorted(a)[k]`` reproduces EVERY witness — the k-th SMALLEST
    element (``k == 0`` min, ``k == -1`` max, ``k == 1`` second-smallest, etc.).
    ``second_smallest([3, 1, 2]) == 2, second_smallest([5, 9, 1]) == 5,
    second_smallest([8, 4, 6, 2]) == 4`` lands ``return sorted(xs)[1]`` — a value
    neither the constant index ``a[k]`` (the element AT a position) nor ``min`` / ``max``
    (the endpoints only) can spell: an INTERIOR order statistic over the SORTED sequence.

    Mines ``k`` over a BOUNDED index set (:func:`_sorted_index_set`: indices valid for
    the SHORTEST witnessed sequence, unioned with the anchors ``0`` / ``1`` / ``-1`` /
    ``-2``, kept only when in range for EVERY witness — an out-of-range ``k`` is simply
    not a candidate, never an exception). SOUNDNESS is by witness-verification, not by
    trusting the shape: every ``k`` is VERIFIED with ``sorted(seq)[k] == expected``
    type-exact across all witnesses before emit, so a coincidental ``k`` is dropped.

    GUARDS — the same discipline as the count / index / compositional siblings: every
    witnessed sequence must be ORDERABLE (``sorted`` must not raise; a mixed-type sequence
    refuses the whole family via :func:`_sorted_index_pairs`); the expected values must
    VARY (an all-equal contract collapses to a constant the constant-last fallback owns);
    the >=2-distinct-witness overfit floor (:func:`_string_floor_met`). AMBIGUITY: a body
    is emitted ONLY when exactly one ``k`` survives — if two distinct indices both
    reproduce every witness (a thin contract cannot tell min from second-smallest), the
    family REFUSES rather than guess. NO-SHADOW: a sorted-index body is a LAST RESORT — it
    DEFERS to any simpler offered template (``simpler``) that ALSO fits, so ``min(a)`` /
    ``a[0]`` win over ``sorted(a)[0]`` on a contract they already solve (they coincide
    when ``a`` is pre-sorted), and the genuine new value (an interior ``k`` no atom
    spells) is the only case that fires. The chosen body is still gated against all pinned
    tests and the off-witness sequence canary by the caller, never-fake-green. With NO
    witness list (the structural view) nothing is mined. Deterministic: bounded indices in
    sorted order, at most one body."""
    if not _string_floor_met(witnesses):
        return []
    pairs = _sorted_index_pairs(witnesses)
    if pairs is None:
        return []
    survivors = [k for k in _sorted_index_set(pairs)
                 if _sorted_index_holds(k, pairs)]
    if len(survivors) != 1:
        return []  # zero fits (no body) or >=2 fit (ambiguous) — refuse, never guess
    if _simpler_template_fits(a, simpler or [], witnesses):
        return []  # a simpler atom (min/max/a[k]) already fits — never shadow it
    return [(f"sorted[{survivors[0]}]", f"sorted({a})[{survivors[0]}]")]


def _sorted_index_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[object, object]] | None:
    """The ``(seq, expected)`` pairs for the sorted-index miner, or ``None`` when the
    family cannot be mined. Every witness must be ONE LITERAL ``list`` / ``tuple`` /
    ``str`` argument that is ORDERABLE (``sorted`` must not raise — a mixed-type sequence
    such as ``[1, 'a']`` refuses the whole family) with a LITERAL expected value, and the
    expected values must VARY (an all-equal contract is a constant another family owns).
    A non-literal, multi-arg, non-sequence, unorderable, or all-equal shape yields
    ``None`` — never guessed. Deterministic: source order."""
    out: list[tuple[object, object]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 \
                or not isinstance(value[0], (list, tuple, str)):
            return None
        if expected is _NO_LITERAL:
            return None
        try:
            sorted(value[0])
        except TypeError:
            return None  # an unorderable / mixed-type sequence — refuse the family
        out.append((value[0], expected))
    if len({repr(expected) for _seq, expected in out}) < 2:
        return None  # all-equal expected -> a constant, not an order statistic
    return out


def _sorted_index_set(pairs: list[tuple[object, object]]) -> list[int]:
    """The BOUNDED set of constant indices ``k`` to try in ``sorted(a)[k]``: the indices
    valid for the SHORTEST witnessed sequence (so no blowup with long inputs), unioned
    with the anchors ``0`` / ``1`` / ``-1`` / ``-2`` (min, second-smallest, max,
    second-largest), then KEPT only when ``k`` is in range for EVERY witness (an
    out-of-range index is simply not a candidate, never an exception). Deterministic:
    sorted, de-duplicated. An empty witness set yields ``[]``."""
    if not pairs:
        return []
    shortest = min(len(seq) for seq, _e in pairs)  # type: ignore[arg-type]
    candidates = set(range(shortest)) | {0, 1, -1, -2}
    return [k for k in sorted(candidates)
            if all(-len(seq) <= k < len(seq) for seq, _e in pairs)]  # type: ignore[arg-type]


def _sorted_index_holds(k: int, pairs: list[tuple[object, object]]) -> bool:
    """True when ``sorted(seq)[k]`` equals the expected value TYPE-EXACTLY for EVERY
    witness — the verification that makes a mined index sound (``sorted(seq)[k]`` cannot
    raise here: ``k`` came from :func:`_sorted_index_set`, in range for every witness,
    and the sequences are orderable, checked by :func:`_sorted_index_pairs`). Type-exact
    mirrors the accept-gate so a mined index can never imply a value the gate rejects."""
    for seq, expected in pairs:
        element = sorted(seq)[k]  # type: ignore[index]
        if type(element) is not type(expected) or element != expected:
            return False
    return True


def _simpler_template_fits(
    a: str, simpler: list[tuple[str, str]], witnesses: list[tuple[str, str]],
) -> bool:
    """True when ANY already-offered (simpler) template reproduces EVERY witness in
    process — the signal that the compositional family should DEFER (a composition must
    never shadow a simpler atom that already fit, nor inject a rival shape that makes the
    gate refuse the genuine atom). Each candidate expr is evaluated over the lone
    parameter ``a`` bound to the witness's literal argument, type-exact, in the same
    sandbox the accept-gate uses; a recursion marker (which cannot be eval'd here) or a
    non-literal witness simply does not count as a fit. Deterministic, pure."""
    evaluable: list[tuple[object, object]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 or expected is _NO_LITERAL:
            return False  # cannot judge fit -> stay conservative, do not abstain
        evaluable.append((value[0], expected))
    env_globals = {"__builtins__": _SAFE_BUILTINS}
    for _label, expr in simpler:
        if "__apex_self__" in expr:
            continue
        if all(_expr_yields(expr, a, arg, expected, env_globals)
               for arg, expected in evaluable):
            return True
    return False


def _expr_yields(
    expr: str, a: str, arg: object, expected: object, env_globals: dict,
) -> bool:
    """True when ``expr`` over the lone parameter ``a`` bound to ``arg`` evaluates to
    ``expected`` type-exactly in the sandbox (a raise / type-or-value mismatch is
    False)."""
    try:
        value = eval(expr, env_globals, {a: arg})  # nosec B307 - fixed templates only
    except Exception:
        return False
    return type(value) is type(expected) and value == expected


def _compose_witness_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[object, int]] | None:
    """The ``(seq_arg, expected_int)`` pairs for the compositional miner, or ``None``
    when the family cannot be mined. Every witness must be ONE LITERAL ``str`` /
    ``list`` / ``tuple`` argument (it must support ``[k]`` and ``len``) with a LITERAL
    ``int`` expected value (a ``bool`` is type-distinct — a scalar-arith result is a
    plain ``int``), and the expected ints must VARY (not all equal, else the contract is
    a constant another family owns). A non-literal, multi-arg, wrong-typed, or all-equal
    shape yields ``None`` — never guessed. Deterministic: source order."""
    out: list[tuple[object, int]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 \
                or not isinstance(value[0], (str, list, tuple)):
            return None
        if type(expected) is not int:
            return None
        out.append((value[0], expected))
    if len({expected for _arg, expected in out}) < 2:
        return None  # all-equal expected -> a constant, not a composition
    return out


def _compose_index_set(pairs: list[tuple[object, int]]) -> list[int]:
    """The BOUNDED set of constant indices ``k`` to try in ``a[k] <op> c``: the indices
    valid for the SHORTEST witnessed sequence (so no blowup with long inputs), unioned
    with the anchors ``0`` / ``1`` / ``-1``, then KEPT only when ``k`` is in range for
    EVERY witness (an out-of-range index is simply not a candidate, never an exception).
    Deterministic: sorted, de-duplicated. An empty witness set yields ``[]``."""
    if not pairs:
        return []
    shortest = min(len(arg) for arg, _e in pairs)  # type: ignore[arg-type]
    candidates = set(range(shortest)) | {0, 1, -1}
    return [k for k in sorted(candidates)
            if all(-len(arg) <= k < len(arg) for arg, _e in pairs)]  # type: ignore[arg-type]


def _compose_arith_survivors(
    a: str, pairs: list[tuple[object, int]],
) -> list[tuple[tuple, str]]:
    """All ``(signature, expr)`` compositional survivors over the bounded index set
    (:func:`_compose_index_set`) plus ``len(a)``, each VERIFIED against every witness.
    ``signature`` is the output tuple over the witness atoms, so two spellings of one
    function (``x + 1`` and ``x - -1``) collapse to one shape; genuinely different
    shapes stay distinct and trip the ambiguity refusal upstream."""
    out: list[tuple[tuple, str]] = []
    for k in _compose_index_set(pairs):
        out.extend(_arith_survivors(f"{a}[{k}]", _index_atom_values(k, pairs)))
    out.extend(_arith_survivors(f"len({a})", _len_atom_values(pairs)))
    return out


def _index_atom_values(
    k: int, pairs: list[tuple[object, int]],
) -> list[tuple[int, int]] | None:
    """The ``(a[k], expected)`` pairs, or ``None`` when any indexed element is not a
    plain ``int`` (a non-int element has no sound ``<op> c`` over ``int`` — e.g. a
    ``str`` element of a ``str`` arg, which ``len`` handles instead)."""
    values: list[tuple[int, int]] = []
    for arg, expected in pairs:
        element = arg[k]  # type: ignore[index]
        if type(element) is not int:
            return None
        values.append((element, expected))
    return values


def _len_atom_values(pairs: list[tuple[object, int]]) -> list[tuple[int, int]]:
    """The ``(len(a), expected)`` pairs — ``len`` is always a plain ``int``."""
    return [(len(arg), expected) for arg, expected in pairs]  # type: ignore[arg-type]


def _arith_survivors(
    prefix: str, values: list[tuple[int, int]] | None,
) -> list[tuple[tuple, str]]:
    """``(signature, expr)`` survivors for ``<prefix> <op> c`` over the atom ``values``:
    the additive shape (``+``/``-`` collapsed by sign, :func:`_compose_add_offset`) then
    the multiplicative shape (``*``, :func:`_compose_mul_factor`), each represented once
    and VERIFIED against every pair (type-exact ``int``). ``None`` values (a non-int
    atom) yield no survivor. The identity ``+ 0`` / ``* 1`` are excluded by the miners,
    so a composition never duplicates the bare atom."""
    if values is None:
        return []
    out: list[tuple[tuple, str]] = []
    d = _compose_add_offset(values)
    if d is not None and all(x + d == e for x, e in values):
        out.append((("add", tuple(x + d for x, _e in values)),
                    f"{prefix} {_render_add(d)}"))
    c = _compose_mul_factor(values)
    if c is not None and all(type(x * c) is int and x * c == e for x, e in values):
        out.append((("mul", tuple(x * c for x, _e in values)), f"{prefix} * {c}"))
    return out


def _render_add(d: int) -> str:
    """Render the additive constant ``d`` as ``+ d`` (or ``- |d|`` for a negative
    offset) so ``x - 2`` reads naturally and ``+``/``-`` are one additive family."""
    return f"+ {d}" if d >= 0 else f"- {-d}"


def _compose_add_offset(values: list[tuple[int, int]]) -> int | None:
    """The single consistent NON-ZERO additive offset ``d`` (``x + d == e`` for every
    pair), bounded to the scalar-arith window, or ``None``. The identity ``+ 0`` is the
    bare atom another family owns, so it is never returned; an inconsistent or
    out-of-bound offset refuses (mirrors :func:`_derived_constants`)."""
    offsets = {e - x for x, e in values}
    if len(offsets) != 1:
        return None
    d = next(iter(offsets))
    return d if d != 0 and -64 <= d <= 64 else None


def _compose_mul_factor(values: list[tuple[int, int]]) -> int | None:
    """The single consistent NON-UNIT multiplier ``c`` (``x * c == e``), derived from
    the DETERMINATE pairs where ``x != 0`` (a degenerate ``0 * c == 0`` pins no ``c`` and
    is left to the verify step), bounded to the scalar-arith window, or ``None``. The
    identity ``* 1`` is the bare atom, so it is never returned."""
    factors: set[int] = set()
    for x, e in values:
        if x != 0:
            if e % x != 0:
                return None  # this witness cannot be a clean multiple — no factor
            factors.add(e // x)
    if len(factors) != 1:
        return None  # no determinate pair, or inconsistent multipliers -> refuse
    c = next(iter(factors))
    return c if c != 1 and -64 <= c <= 64 else None


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
    * ``hex({a})`` / ``oct({a})`` / ``bin({a})`` / ``chr({a})`` — value-free, TOTAL
      int->str maps (int args only): the three radix formatters and the
      codepoint->char map. No floor (pure totals like ``neg``); the int canaries
      already split the radices and ``chr`` from one another and from ``str(n)``, so
      an under-specified ``hex`` vs ``str`` contract is refused. ``chr`` on an
      out-of-range codepoint RAISES -> gate rejects;
    * ``ord({a})`` — the value-free length-1-str->codepoint map (str args only), the
      inverse of ``chr``; a non-length-1 str RAISES -> gate rejects;
    * ``{a}[0]`` / ``{a}[-1]`` (first/last), ``{a}[::-1]`` (reverse),
      ``list({a})`` / ``tuple({a})``, ``bytes({a})`` / ``bytearray({a})`` — sequence
      projections (iterable / str args, where indexing and materialization are
      meaningful); ``tuple`` differs from ``list`` only in RESULT TYPE, which the
      type-exact accept-gate distinguishes, so the right one lands on its witnesses.
      ``{a}[::-1]`` reverses the whole sequence, VALUE-FREE and TYPE-PRESERVING
      (``str[::-1]`` -> ``str``, ``list[::-1]`` -> ``list``), so like ``first`` /
      ``last`` it carries no witness literal and no overfit floor; the off-witness
      canaries split it from passthrough / ``sorted`` (a list/tuple via the reversed
      sequence-canary probe, a ``str`` via the whitespace-padded ``str`` canaries —
      a palindrome / already-sorted-descending witness where the reverse coincides
      with passthrough / ``sorted`` is honestly REFUSED).
      ``list({a})`` / ``tuple({a})`` / ``bytes({a})`` / ``bytearray({a})`` are
      WITHHELD when a witnessed argument is a ``set``/``frozenset``: materializing an
      unordered collection yields a PYTHONHASHSEED-dependent order, the same
      non-deterministic value oracle that already excludes ``set({a})`` — landing
      such a body would break the determinism invariant. ``frozenset({a})`` is
      deliberately NOT offered as a body at all: it is the SAME hash-iteration-order
      determinism class as the forbidden ``set({a})`` (sound only as an INFERRED type
      name, never as a value-returning stub);
    * ``str({a})``, ``not {a}``, ``bool({a})`` — type-agnostic, offered for every
      kind (any value can be stringified or truth-tested). ``set({a})`` is
      deliberately NOT offered: a ``set`` return is hash-iteration-order-sensitive,
      so its value oracle is non-deterministic and the determinism invariant forbids
      landing it; an emptiness check ``len({a}) == 0`` is likewise omitted because the
      already-present ``not {a}`` is provably equivalent on every length-bearing arg.

    ``abs`` / ``len`` / ``sorted`` / ``sum`` already appear earlier in
    :func:`_one_arg_templates`, so they are not repeated here. Order is fixed and
    value-independent, preserving determinism. The witness-DERIVED distinct-count
    shape ``len(set(a))`` is appended last among the sequence projections, only when
    :func:`_distinct_count_applicable` clears it (a hashable sequence whose distinct
    count VARIES and genuinely differs from a plain ``len`` — never a shadow)."""
    out: list[tuple[str, str]] = []
    if kind in (None, "int", "float"):
        out.append(("neg", f"-{a}"))
    # ``int(a)`` parses a numeric string as well as truncating a float, so it is
    # offered for str args too (a common ``parse`` intent); only an iterable arg,
    # which ``int`` cannot coerce, prunes it.
    if kind in (None, "int", "float", "str"):
        out.append(("int", f"int({a})"))
    if kind in (None, "int"):
        # Value-free int-to-str radix formatters + the codepoint->char map. Each is
        # a pure TOTAL function on the int domain (``hex``/``oct``/``bin`` accept any
        # int; ``chr`` accepts ``0..0x10FFFF``), so no overfit floor is needed — just
        # like ``neg``. They are pruned to a pure-int arg (a ``float`` cannot radix-
        # format and ``chr`` rejects it), and the int-canary probes already split
        # ``hex``/``oct``/``bin``/``chr`` from one another and from ``str(n)`` (the
        # radices diverge on the anchor probes), so an under-specified ``hex`` vs
        # ``str`` contract is honestly refused by the ambiguity guard. ``chr`` on an
        # out-of-range / negative codepoint RAISES, which the accept-gate rejects.
        out.append(("hex", f"hex({a})"))
        out.append(("oct", f"oct({a})"))
        out.append(("bin", f"bin({a})"))
        out.append(("chr", f"chr({a})"))
    if kind in (None, "str"):
        # ``ord(s)`` maps a length-1 ``str`` to its int codepoint — value-free, pure,
        # the inverse of ``chr``. Offered for a str arg (a non-length-1 str RAISES,
        # which the gate rejects); the str canaries split it from the other str shapes.
        out.append(("ord", f"ord({a})"))
    if kind in (None, "str", "iterable"):
        out.append(("first", f"{a}[0]"))
        out.append(("last", f"{a}[-1]"))
        out.append(("reverse", f"{a}[::-1]"))
        if not _has_set_arg(witnesses):
            out.append(("list", f"list({a})"))
            out.append(("tuple", f"tuple({a})"))
            # ``bytes(a)``/``bytearray(a)`` materialize an iterable of ints (or encode
            # a str) into a bytes container — VALUE-FREE and order-PRESERVING for a
            # list/tuple/str arg, so they are HASHSEED-SAFE and need no floor (the
            # gate's type-exact accept keeps the right one — ``bytes`` vs ``bytearray``
            # differ only in result type). They share the ``_has_set_arg`` gate with
            # ``list``/``tuple``: a ``set`` arg would order its elements by hash, making
            # the bytes value PYTHONHASHSEED-dependent (the same non-determinism that
            # withholds ``set(a)``/``list(a)`` for a set witness). ``frozenset(a)`` is
            # deliberately NOT offered as a body — it is the same hash-iteration-order
            # determinism class as the forbidden ``set(a)``.
            out.append(("bytes", f"bytes({a})"))
            out.append(("bytearray", f"bytearray({a})"))
        if _distinct_count_applicable(witnesses):
            out.append(("distinct_count", f"len(set({a}))"))
    out.append(("str", f"str({a})"))
    out.append(("not", f"not {a}"))
    out.append(("bool", f"bool({a})"))
    return out


def _distinct_count_applicable(witnesses: list[tuple[str, str]] | None) -> bool:
    """True when the witness-DERIVED ``len(set(a))`` DISTINCT-count shape may be
    OFFERED for a single-sequence contract. ``n_unique([1, 2, 2]) == 2,
    n_unique([5, 5, 5, 6]) == 2, n_unique([7, 8, 9]) == 3`` clears it — the body
    returns the number of DISTINCT elements, a value no other 1-arg shape spells
    (``len`` counts WITH duplicates; ``set(a)`` itself is forbidden — its iteration
    order is hash-seed-dependent — but its CARDINALITY is a deterministic ``int``,
    PYTHONHASHSEED-safe, so ``len(set(a))`` is sound to land).

    Every witness must be ONE LITERAL ``list`` / ``tuple`` / ``str`` of HASHABLE
    elements (so ``set`` cannot raise; a witness with an unhashable element refuses
    the whole family) with a LITERAL ``int`` expected value (a ``bool`` is
    type-distinct — a count is a plain ``int``). The expected ints must VARY (an
    all-equal contract collapses to a constant the constant-last fallback owns), and
    every witness must satisfy ``len(set(seq)) == expected`` (the shape is mined and
    VERIFIED, never guessed; the caller still gates it against the pinned tests).

    NO-SHADOW: withheld when a plain ``len(a)`` ALREADY reproduces every witness —
    i.e. every witnessed sequence is duplicate-free, so ``len(set(a)) == len(a)`` and
    the earlier, simpler ``len`` body would win. At least one witness must carry a
    DUPLICATE (``len(set(seq)) < len(seq)``) for the distinct count to be genuinely
    new value, so it never shadows ``len``. Carries the >=2-distinct-witness overfit
    floor (:func:`_string_floor_met`). With NO witness list (the structural view) it
    is withheld — there is no literal to verify against. Deterministic, pure."""
    if not _string_floor_met(witnesses):
        return False
    pairs = _distinct_count_pairs(witnesses or [])
    if pairs is None:
        return False
    if not all(len(set(seq)) == expected for seq, expected in pairs):
        return False  # not a distinct-count contract — do not offer
    # NO-SHADOW: if every witnessed sequence is duplicate-free, plain ``len`` fits
    # and would win; the distinct count is only NEW value when a duplicate exists.
    return any(len(set(seq)) != len(seq) for seq, expected in pairs)


def _distinct_count_pairs(
    witnesses: list[tuple[str, str]],
) -> list[tuple[object, int]] | None:
    """The ``(seq, expected_int)`` pairs for the distinct-count miner, or ``None``
    when the family cannot be mined. Every witness must be ONE LITERAL ``list`` /
    ``tuple`` / ``str`` argument of HASHABLE elements (an unhashable element refuses —
    ``set`` would raise) with a LITERAL ``int`` expected value (a ``bool`` is
    type-distinct), and the expected ints must VARY (an all-equal contract is a
    constant another family owns). A non-literal, multi-arg, wrong-typed, unhashable,
    or all-equal shape yields ``None`` — never guessed. Deterministic: source order."""
    out: list[tuple[object, int]] = []
    for args_text, expected_text in witnesses:
        value = _literal_tuple(args_text)
        expected = _literal_value(expected_text)
        if value is None or len(value) != 1 \
                or not isinstance(value[0], (list, tuple, str)):
            return None
        if type(expected) is not int:
            return None
        try:
            set(value[0])
        except TypeError:
            return None  # an unhashable element — ``set`` cannot be formed soundly
        out.append((value[0], expected))
    if len({expected for _seq, expected in out}) < 2:
        return None  # all-equal expected -> a constant, not a distinct count
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


def _multi_arg_arith_templates(params: tuple[str, ...],
                               witnesses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The MULTI-ARG ARITHMETIC family (NEW): a FIXED, small set of combined
    numeric shapes over the FIRST TWO params (a mean / scaled binary) and — only
    when the stub has EXACTLY three params — the three-operand combinations that
    today's :func:`_two_arg_templates` never reaches (it forms one binary op on
    ``a``/``b`` and ignores ``c`` entirely, so a 3-arg arithmetic stub gets
    NOTHING). Offered AFTER every existing binary shape, so a plain ``a + b`` still
    wins when it fits; this family only lands where the old engine produced nothing.

    Two-param additions: ``(a + b) / 2`` and ``(a + b) // 2`` (the float / integer
    mean — a 2-arg shape the single-binary space cannot express), then the
    witness-DERIVED ``a * b + k`` / ``a - b * k`` for each small constant ``k``
    inferred from the witnesses. Three-param set (arity == 3 only): the fixed
    combinations ``a*b+c``, ``(a+b)*c``, ``(a-b)*c``, ``a*b//c``, ``(a+b)/c`` — a
    SHORT fixed list, never a search over all ASTs, so the space stays bounded and
    reproducible.

    Soundness: every shape here is still gate-verified (in-process type-exact
    ``eval`` against the literal witnesses AND the pinned pytest/doctest nodes), so
    a non-matching combination is rejected, never landed. The witness-DERIVED
    ``k``-baking shapes carry the same >=2-distinct-tuple overfit floor the derived
    scalar constants use (:func:`_string_floor_met` / :func:`_numeric_constants`),
    so one example cannot pin an arbitrary ``k``. The value-free mean / 3-op shapes
    need no floor — a coincidental one is caught by the gate, and two that survive
    the gate but diverge off-witness are refused by the ambiguity guard (the
    existing :func:`_multi_arg_canary_probes`, which already reorders/perturbs up to
    arity 4). Deterministic: the op list is fixed, constants are sorted."""
    out: list[tuple[str, str]] = []
    a, b = params[0], params[1]
    out.append(("mean2", f"({a} + {b}) / 2"))
    out.append(("floormean2", f"({a} + {b}) // 2"))
    if _string_floor_met(witnesses):
        for k in _numeric_constants(witnesses):
            out.append((f"a*b+{k}", f"{a} * {b} + {k}"))
            out.append((f"a-b*{k}", f"{a} - {b} * {k}"))
    if len(params) == 3:
        c = params[2]
        out.append(("a*b+c", f"{a} * {b} + {c}"))
        out.append(("(a+b)*c", f"({a} + {b}) * {c}"))
        out.append(("(a-b)*c", f"({a} - {b}) * {c}"))
        out.append(("a*b//c", f"{a} * {b} // {c}"))
        out.append(("(a+b)/c", f"({a} + {b}) / {c}"))
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
                        stub: StubFunction,
                        module_source: str | None = None) -> list[tuple[str, str]]:
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
    unchanged, the ambiguity guard still applies, never-fake-green holds.

    When ``module_source`` (the source of the module under fill) is supplied, the
    stub's OWN docstring ``>>>`` examples are mined too (:func:`_doctest_witnesses`)
    and APPENDED after the test-file witnesses, so a stub whose contract lives in
    its docstring is fillable through the SAME machinery. A doctest ``>>> f(2)\\n6``
    is the same kind of witness as ``assert f(2) == 6`` — it flows through the
    identical accept-gate, canary, >=2-distinct floor and ambiguity guard. The
    doctest pass is purely ADDITIVE: with ``module_source=None`` (every existing
    caller) the output is byte-for-byte what it was. Deterministic: test files in
    sorted order first, then the docstring examples in source order."""
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
    if module_source is not None:
        out.extend(_doctest_witnesses(module_source, stub))
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
    # A self-referential RHS (`f(x) == f(...)`) is a TAUTOLOGY — any body is equal to
    # itself, so it pins NO value. Mining it as a witness fake-greens the search (a
    # guessed body passes the self-equal gate); skip any assert whose expected side
    # calls the stub itself.
    self_call = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stub.name) + r"\s*\(")
    for m in call_eq.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if _line_in_ranges(line, excluded):
            continue  # assertion lives in an xfail/skip test — not a contract
        if line in resolved_lines:
            continue  # this exact assert already mined as a literal indirectly
        expected = m.group(2).strip()
        if self_call.search(expected):
            continue  # `f(x) == f(...)` tautology — pins no value, never a witness
        out.append((m.group(1).strip(), expected))
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


def _enforceable_doctest_examples(source: str,
                                  stub: StubFunction) -> list[doctest.Example]:
    """The ``>>>`` examples in ``stub``'s OWN docstring that the suite would
    actually ENFORCE — every example EXCEPT one carrying a ``# doctest: +SKIP``
    directive. A ``+SKIP`` example is never executed by ``doctest`` (the analogue
    of an ``xfail``/``skip`` test assert), so it pins NO contract: mining it for a
    witness or counting it toward verification would stamp an unenforced example
    "verified", breaking never-fake-green. It is dropped here, the SINGLE place the
    "which examples count" decision is made — so the witness miner and the
    apply-path doctest verifier weigh exactly the same examples.

    Fully guarded on a malformed source: a docstring that cannot be parsed yields
    ``[]`` (never raises). Deterministic: examples in source order."""
    docstring = _stub_docstring(source, stub)
    if not docstring:
        return []
    try:
        examples = doctest.DocTestParser().get_examples(docstring)
    except (ValueError, RecursionError, MemoryError):
        return []
    return [ex for ex in examples if not ex.options.get(doctest.SKIP)]


def has_enforceable_doctest_examples(source: str, stub: StubFunction) -> bool:
    """True when ``stub`` has at least one ENFORCEABLE ``>>>`` example (``+SKIP``
    excluded) — i.e. an example the apply-path doctest verifier would actually run.

    This is the correct TRIGGER for doctest gating: it is keyed to the SAME set
    (:func:`_enforceable_doctest_examples`) the verifier weighs, so the gate fires
    for EVERY enforceable example, not only a mined literal-call witness. Using the
    narrower ``_has_doctest_witnesses`` as the trigger let a comparison-style
    example (``>>> f(2) == 4``) — enforceable but not a mined witness — escape
    verification, so a doctest-violating body could land (a never-fake-green hole).
    Gating on this predicate closes that gap. Never raises (delegates to the
    fully-guarded example extractor)."""
    return bool(_enforceable_doctest_examples(source, stub))


def _doctest_witnesses(source: str, stub: StubFunction) -> list[tuple[str, str]]:
    """The ``(args_text, expected_text)`` witnesses mined from ``stub``'s OWN
    docstring ``>>>`` examples — a SECOND witness source besides the test files, so
    a stub whose contract lives only in its doctests (``>>> double(3)\\n6``) is
    fillable through the very same template machinery a ``assert double(3) == 6``
    would feed. The mined pairs have the IDENTICAL shape the test-file extractor
    yields, so they merge with (and are gated exactly like) the test witnesses —
    the accept-gate, canary, >=2-distinct floor and never-fake-green are unchanged;
    only a new witness SOURCE is added, no new template logic.

    Conservative by construction, the SAME strictness as the test-file extractor:

    * each example must be a single EXPRESSION that is a direct ``stub.name(...)``
      call with a bare-``Name`` callee (``mode='eval'`` rejects assignments,
      multi-statement examples and ``raise``; :func:`_is_symbol_call` rejects a
      method call or any other expression);
    * the args must be literal (re-using :func:`_literal_tuple`) and the expected
      ``want`` must be a literal — a non-literal example (``>>> double(x)``), prose,
      or an exception ``want`` (a Traceback) is simply IGNORED, never guessed;
    * a ``# doctest: +SKIP`` example is dropped (:func:`_enforceable_doctest_examples`)
      — an unenforced example is no contract;
    * no keyword/starred argument (:func:`_render_call_args` returns ``None``).

    Deterministic: examples are mined in docstring source order. A malformed /
    un-parseable source or docstring raises NOTHING — it yields ``[]`` (the
    >=2-distinct floor downstream still rejects a lone example on its own)."""
    out: list[tuple[str, str]] = []
    for ex in _enforceable_doctest_examples(source, stub):
        pair = _doctest_example_witness(ex.source, ex.want, stub)
        if pair is not None:
            out.append(pair)
    return out


def _stub_docstring(source: str, stub: StubFunction) -> str | None:
    """The docstring of the function ``stub`` denotes in ``source`` (matched by name
    AND its 1-based ``lineno``, so an overload elsewhere is never confused for it),
    or ``None`` when the source does not parse, the function is not found, or it
    carries no docstring. Guarded: a malformed source raises nothing."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == stub.name and node.lineno == stub.lineno):
            return ast.get_docstring(node)
    return None


def _doctest_example_witness(example_src: str, want: str,
                             stub: StubFunction) -> tuple[str, str] | None:
    """One ``(args_text, expected_text)`` witness from a single doctest example —
    its ``>>>`` source line(s) ``example_src`` and the expected output ``want`` — or
    ``None`` when the example is not a literal call to ``stub.name``.

    The expected text is ``want`` stripped and validated by :func:`_doctest_literal`
    (NOT the test-file :func:`_literal_value`): a doctest's expected OUTPUT may
    legitimately contain ``#`` inside a string repr (``>>> tag('x')`` -> ``'#x'``),
    which the test-file path's trailing-comment stripping would wrongly truncate.
    Only an example that survives every guard becomes a witness."""
    try:
        node = ast.parse(example_src.strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return None  # a statement / multi-line / non-expression example — ignore
    if not _is_symbol_call(node, stub.name):
        return None  # not a direct call to the stub's own function
    args_text = _render_call_args(node)
    if args_text is None:
        return None  # keyword / starred argument — unrecoverable, never guessed
    if _literal_tuple(args_text) is None:
        return None  # a non-literal argument (``double(x)``) — ignore, never guess
    expected_text = want.strip()
    if _doctest_literal(expected_text) is _NO_LITERAL:
        return None  # prose / exception / non-literal expected output — ignore
    return args_text, expected_text


def _doctest_literal(want_text: str) -> object:
    """Evaluate a doctest ``want`` (the expected printed output) to a literal, or
    the sentinel ``_NO_LITERAL`` when it is not one. Unlike the test-file
    :func:`_literal_value` this does NOT split on ``#`` before parsing: a doctest's
    expected output is the WHOLE printed repr, so a ``#`` belongs to the value
    (``'#tag'``), never a trailing comment — stripping it would corrupt the
    literal. ``ast.literal_eval`` still ignores a genuine trailing ``# comment`` on
    its own (the tokenizer drops it), so nothing legitimate is lost."""
    try:
        return ast.literal_eval(want_text.strip())
    except (ValueError, SyntaxError, TypeError):
        return _NO_LITERAL


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
    """The 1-based ``(start, end)`` line spans of every function in ``text`` whose
    assertions do NOT enforce a contract: decorated ``@pytest.mark.xfail`` (and bare
    ``@xfail``), ``@pytest.mark.skip`` / ``skipif``, ``@unittest.skip*``; OR whose body
    OPENS with an unconditional runtime skip/xfail (``pytest.skip(...)`` /
    ``pytest.xfail(...)`` / ``pytest.importorskip(...)`` / ``self.skipTest(...)`` /
    ``raise unittest.SkipTest``, alias-renamed forms included); OR poisoned from afar by
    a module ``pytestmark`` skip or its ``unittest.TestCase``'s ``setUp``
    unconditionally skipping. An assertion inside such a function pins no contract — its
    failure is allowed (xfail) or it never runs (skip). Deterministic; ``[]`` on a
    syntax error so a parse failure never silently drops a real contract."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    ctx = _build_skip_context(tree)
    out: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _test_function_is_enforced(node, ctx):
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


_RUNTIME_SKIP_CALLS = {"skip", "xfail", "importorskip"}
# The canonical pytest/unittest skip surfaces a ``from``-import alias can rename
# to a LOCAL token (``from pytest import skip as s`` binds ``s`` → canonical ``skip``).
_SKIP_CANONICALS = {"skip", "xfail", "importorskip", "SkipTest"}
# Modules whose ``skip``/``xfail``/``importorskip``/``SkipTest`` exports we trust as
# the genuine skip surface (so a ``from somethingelse import skip`` of an UNRELATED
# module is not mistaken for a test skip).
_SKIP_IMPORT_MODULES = {"pytest", "unittest", "_pytest.outcomes"}


def _skip_call_name(stmt: ast.stmt,
                    aliases: dict[str, str] | None = None) -> str | None:
    """The CANONICAL skip token of a bare or assigned call statement (``f(...)`` or
    ``x = f(...)``), else ``None`` — lets the caller spot a runtime ``skip`` /
    ``xfail`` / ``importorskip`` / ``skipTest`` call. The trailing attribute token is
    returned verbatim (so ``pytest.skip`` / ``import pytest as pt; pt.skip`` and a
    bound ``self.skipTest`` all read through); a BARE ``ast.Name`` callee is mapped
    through ``aliases`` so a ``from pytest import skip as s`` rename (local ``s`` ∉ the
    canonical set) still resolves to its canonical ``skip``."""
    call = None
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
    elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
        call = stmt.value
    if call is None:
        return None
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return (aliases or {}).get(f.id, f.id)
    return None


def _is_skip_raise(stmt: ast.stmt,
                   aliases: dict[str, str] | None = None) -> bool:
    """True for ``raise unittest.SkipTest`` (bare or called) / ``raise
    pytest.skip.Exception``. The attribute form matches on the trailing token; a BARE
    ``ast.Name`` exception is mapped through ``aliases`` so a ``from unittest import
    SkipTest as Foo`` rename (``raise Foo``) resolves to its canonical ``SkipTest``."""
    if not (isinstance(stmt, ast.Raise) and stmt.exc is not None):
        return False
    exc = stmt.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Attribute) and exc.attr == "Exception" \
            and isinstance(exc.value, ast.Attribute) and exc.value.attr == "skip":
        return True  # raise pytest.skip.Exception
    if isinstance(exc, ast.Attribute):
        return exc.attr == "SkipTest"
    if isinstance(exc, ast.Name):
        return (aliases or {}).get(exc.id, exc.id) == "SkipTest"
    return False


def _is_runtime_skip_stmt(stmt: ast.stmt,
                          aliases: dict[str, str] | None = None) -> bool:
    """True for a DIRECT body statement that UNCONDITIONALLY skips/xfails the test
    at runtime: a bare or assigned ``pytest.skip(...)`` / ``pytest.xfail(...)`` /
    ``pytest.importorskip(...)`` / ``self.skipTest(...)`` call, or ``raise
    unittest.SkipTest`` / ``raise pytest.skip.Exception``. Matched on the trailing
    attribute token (so ``pt.skip`` / ``self.skipTest`` count) and, for a bare-``Name``
    callee, through ``aliases`` (so a ``from pytest import skip as s`` rename counts —
    pass the per-file alias map from :func:`_build_skip_context`).

    Only DIRECT body statements are inspected, so a skip guarded by an ``if`` / ``for``
    / ``try`` (a conditional, genuinely-enforced test that runs for some inputs) does
    NOT trip this gate — that asymmetry is deliberate and load-bearing."""
    name = _skip_call_name(stmt, aliases)
    return name in _RUNTIME_SKIP_CALLS or name == "skipTest" \
        or _is_skip_raise(stmt, aliases)


def _line_in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    """True when 1-based ``line`` falls within any ``(start, end)`` span."""
    return any(start <= line <= end for start, end in ranges)


def _test_function_is_enforced(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    ctx: _FileSkipContext | None = None,
) -> bool:
    """True when a test function's assertions actually run — NOT suspended by an
    xfail/skip/skipif decorator, NOR by an unconditional runtime skip/xfail opening
    its OWN body, NOR (when ``ctx`` is given) by a file-level skip surface that poisons
    it from afar: a module ``pytestmark`` skip, or an unconditional skip in the
    ``setUp``/``setUpClass`` of the ``unittest.TestCase`` it belongs to. The two
    body-local skip surfaces AND the three file-context surfaces are the holes the
    never-fake-green floor must all close; ``ctx`` also carries the import-alias map so
    a ``from pytest import skip as s`` rename is recognised."""
    aliases = ctx.aliases if ctx else None
    if ctx and (ctx.pytestmark_skips or id(node) in ctx.poisoned_ids):
        return False
    return not any(_is_unenforced_decorator(d) for d in node.decorator_list) \
        and not any(_is_runtime_skip_stmt(s, aliases) for s in node.body)


@dataclass(frozen=True)
class _FileSkipContext:
    """The per-FILE skip surface the context-free body predicates can't see on a lone
    statement: the module-level import-alias map (local token → canonical ``skip`` /
    ``xfail`` / ``importorskip`` / ``SkipTest``), whether a module ``pytestmark`` skips
    every test, and the ``id()``s of ``test_*`` methods POISONED by an unconditional
    skip in their ``unittest.TestCase``'s ``setUp``/``setUpClass``. Built once per file
    by :func:`_build_skip_context` and threaded into the body/enforced predicates."""
    aliases: dict[str, str]
    pytestmark_skips: bool
    poisoned_ids: frozenset[int]


def _collect_skip_aliases(tree: ast.Module) -> dict[str, str]:
    """Resolve MODULE-level imports of the pytest/unittest skip surface into a
    ``{local_name -> canonical}`` map. Walks top-level ``from pytest/unittest import
    skip as s`` (``ast.ImportFrom`` from a trusted module → ``{"s": "skip"}``) and
    ``import pytest.skip as x`` style ``ast.Import`` whose dotted tail is a canonical
    (mirrors the import-walking in ``type_annotations._module_bound_names``). The
    attribute form ``pytest.skip`` needs no entry — its trailing token already reads."""
    out: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            if stmt.module not in _SKIP_IMPORT_MODULES:
                continue
            for alias in stmt.names:
                if alias.name in _SKIP_CANONICALS:
                    out[alias.asname or alias.name] = alias.name
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                tail = alias.name.rsplit(".", 1)[-1]
                if alias.asname and tail in _SKIP_CANONICALS:
                    out[alias.asname] = tail
    return out


def _module_pytestmark_skips(tree: ast.Module) -> bool:
    """True when a MODULE-level ``pytestmark = pytest.mark.skip`` (or a list/tuple any
    of whose elements is a ``*.mark.skip``) unconditionally skips every test in the
    file. A ``skipif`` mark is CONDITIONAL — not matched (mirrors the decorator path,
    which conservatively refuses ``skipif`` separately); only a bare ``.mark.skip``
    (trailing attr ``skip``, with or without a message arg) poisons the whole file."""
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark"
                for t in stmt.targets)):
            continue
        value = stmt.value
        elts = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        if any(_is_mark_skip(e) for e in elts):
            return True
    return False


def _is_mark_skip(node: ast.expr) -> bool:
    """True for a ``*.mark.skip`` expression (``pytest.mark.skip`` bare or called) — the
    unconditional module-level skip mark. Matched on the trailing ``skip`` attr whose
    parent attr is ``mark``; a ``skipif`` tail is deliberately NOT matched."""
    if isinstance(node, ast.Call):
        node = node.func
    return isinstance(node, ast.Attribute) and node.attr == "skip" \
        and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"


_TESTCASE_SETUP_HOOKS = {"setUp", "setUpClass", "setUpModule"}


def _class_is_testcase(node: ast.ClassDef) -> bool:
    """True when ``node`` subclasses a ``unittest.TestCase``-ish base — a base whose
    trailing name token is ``TestCase`` or ends with ``TestCase`` (covers
    ``unittest.TestCase``, a bare ``TestCase`` alias, and ``IsolatedAsyncioTestCase``-
    style names). Conservative name-only check (no import resolution)."""
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else (
            base.id if isinstance(base, ast.Name) else None)
        if name and name.endswith("TestCase"):
            return True
    return False


def _setup_unconditionally_skips(cls: ast.ClassDef,
                                 aliases: dict[str, str]) -> bool:
    """True when a ``setUp``/``setUpClass``/``setUpModule`` method of ``cls`` opens with
    an UNCONDITIONAL runtime skip (``self.skipTest(...)`` / ``pytest.skip(...)`` /
    ``raise SkipTest``) as a DIRECT body statement — which vacuously greens every
    ``test_*`` method of the class. The same conditional asymmetry holds: a skip nested
    under ``if``/``for``/``try`` in setUp does NOT poison (the suite still runs for the
    unskipped branch)."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and stmt.name in _TESTCASE_SETUP_HOOKS \
                and any(_is_runtime_skip_stmt(s, aliases) for s in stmt.body):
            return True
    return False


def _collect_poisoned_test_ids(tree: ast.Module,
                               aliases: dict[str, str]) -> frozenset[int]:
    """The ``id()``s of every ``test_*`` method whose enclosing ``unittest.TestCase``
    has a ``setUp``/``setUpClass`` that unconditionally skips — so the method is
    vacuously green even though its OWN body carries no skip. Only DIRECT methods of a
    poisoned TestCase body are collected (a nested function is not a test method)."""
    poisoned: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and _class_is_testcase(node)):
            continue
        if not _setup_unconditionally_skips(node, aliases):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and member.name.startswith("test"):
                poisoned.add(id(member))
    return frozenset(poisoned)


def _build_skip_context(tree: ast.Module) -> _FileSkipContext:
    """Compute the per-file skip surface (alias map, module ``pytestmark`` skip,
    setUp-poisoned test-method ids) ONCE for a parsed test file, so the cheap body
    predicates can resolve renamed-alias skips and file-level (pytestmark / class
    setUp) skips that no single statement reveals. Deterministic; pure AST."""
    aliases = _collect_skip_aliases(tree)
    return _FileSkipContext(
        aliases=aliases,
        pytestmark_skips=_module_pytestmark_skips(tree),
        poisoned_ids=_collect_poisoned_test_ids(tree, aliases),
    )


def _has_enforceable_contract(root: Path, test_files: list[str],
                              stub: StubFunction) -> bool:
    """True when at least one ENFORCED test references ``stub.name`` — a test
    function that is NOT decorated ``xfail`` / ``skip`` / ``skipif``, whose body does
    not open with an unconditional runtime skip/xfail (``pytest.skip(...)`` /
    ``pytest.xfail(...)`` / ``pytest.importorskip(...)`` / ``self.skipTest(...)`` /
    ``raise unittest.SkipTest``), AND which is not poisoned from afar by a module
    ``pytestmark`` skip or its ``unittest.TestCase``'s ``setUp`` unconditionally
    skipping — so the suite actually enforces its assertions.

    This is the never-fake-green floor for the pytest-gated path: when EVERY test
    touching the stub is xfail/skip (via a decorator, a body runtime skip, a renamed
    ``from``-import alias, a module ``pytestmark`` skip, or a class-``setUp`` skip),
    the pinned-test gate is meaningless (an xfail test stays "green" no matter what
    body we land, a skip never runs), so synthesising a body against it would stamp an
    unenforced contract "verified". We refuse instead. A non-stub reference inside an
    enforced test is enough — we err toward "enforceable" only when a real, running
    test names the function. Deterministic; on a parse failure we conservatively report
    ``True`` so a parse hiccup never suppresses a genuine contract (the run gate still
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
        ctx = _build_skip_context(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(text, node) or ""
            if not name_re.search(seg):
                continue
            saw_reference = True
            if _test_function_is_enforced(node, ctx):
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
    for node, _is_method, _enclosing in _iter_functions(tree):
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


def _doctests_pass(examples: list[doctest.Example], filled_source: str,
                   stub: StubFunction) -> bool:
    """Run already-picked enforceable ``examples`` against ``filled_source`` — the
    source compiled into a FRESH namespace — accepting ONLY when every example
    passes. The single place the compile-and-run verdict lives, shared by
    :func:`verify_body_via_doctest` (which rewrites a bare return-expr into the
    source first) and :func:`filled_source_passes_doctests` (whose source is already
    filled). Conservative, never a fake-green: a source that fails to compile, or a
    stub that is not a callable module global (e.g. a method whose ``self`` is not a
    global), yields ``False``. Deterministic: fixed namespace, examples in source
    order."""
    namespace = _compiled_module_namespace(filled_source)
    if namespace is None or stub.name not in namespace:
        return False  # didn't compile, or stub isn't a callable module global
    test = doctest.DocTest(examples, namespace, stub.name, None, 0, None)
    runner = doctest.DocTestRunner(verbose=False)
    try:
        # ``out=`` discards the failure report: a mismatched candidate is expected
        # during the search and must not spam stdout (it would corrupt a quiet
        # develop-loop log). The verdict is ``result.failed``, not the text.
        result = runner.run(test, out=lambda _s: None, clear_globs=False)
    except Exception:
        return False
    return result.failed == 0


def verify_body_via_doctest(module_source: str, stub: StubFunction,
                            return_expr: str) -> bool:
    """True when ``stub`` filled with ``return <return_expr>`` makes ALL of its OWN
    enforceable docstring ``>>>`` examples pass, run by the stdlib :mod:`doctest`.

    This is the never-fake-green gate for a stub whose contract lives (wholly or
    partly) in its docstring rather than a ``test_*.py`` file: such a stub has no
    pinned pytest file to gate it, so the apply path would otherwise have to either
    refuse it (under-count vs the scan) or land it UNVERIFIED. Instead the body is
    verified the way the contract is written — by re-running the function's own
    examples. The scan oracle and the apply path BOTH consult this, so a doctest-
    only stub the scan calls fillable is exactly one the apply can land and verify.

    Mechanism (in-process, no pytest, no temp files): the stub's enforceable
    examples (:func:`_enforceable_doctest_examples`, ``+SKIP`` excluded) are mined,
    the body is filled with ``return <return_expr>``, and both are handed to the
    shared verifier :func:`_doctests_pass` — which compiles the filled source into a
    fresh namespace and runs the examples by a :class:`doctest.DocTestRunner`,
    accepting ONLY when every example passed. A method stub (``self`` not a module
    global), a body that fails to compile, or NO enforceable example all yield
    ``False`` — conservative, never a fake-green. Deterministic: examples in source
    order, fixed namespace."""
    examples = _enforceable_doctest_examples(module_source, stub)
    if not examples:
        return False  # nothing enforceable to verify — never claim verified
    filled = _rewrite_with_body(module_source, stub, return_expr)
    if filled is None:
        return False
    return _doctests_pass(examples, filled, stub)


def filled_source_passes_doctests(filled_source: str, stub: StubFunction) -> bool:
    """True when ``stub``'s OWN enforceable docstring ``>>>`` examples all pass
    against an ALREADY-FILLED module source, run by the stdlib :mod:`doctest`.

    This is the never-fake-green gate the pytest-gated fixpoint pass needs for a
    stub that ALSO carries doctest witnesses. The pytest pass works with a fully
    composed ``new_source`` (a body chosen because it passes the pinned pytest
    nodes), not a bare return-expr, so it cannot reuse
    :func:`verify_body_via_doctest` (which re-derives the fill from an expr).
    Instead both share the compile-and-run verdict in :func:`_doctests_pass`: this
    function picks the contract examples with :func:`_enforceable_doctest_examples`
    and hands them — with the ALREADY-FILLED source — straight to that shared
    verifier, skipping the ``_rewrite_with_body`` step its twin needs first.

    Conservative, never a fake-green: a stub with NO enforceable example, a source
    that fails to compile, or a stub that is not a callable module global (e.g. a
    method whose ``self`` is not a global) all yield ``False``. Deterministic:
    examples in source order, fixed namespace."""
    examples = _enforceable_doctest_examples(filled_source, stub)
    if not examples:
        return False  # nothing enforceable to verify — never claim verified
    return _doctests_pass(examples, filled_source, stub)


def _named_stub(fn_name: str, fn_lineno: int) -> StubFunction:
    """A minimal :class:`StubFunction` carrying only the (name, 1-based lineno)
    identity the doctest layer keys on. ``_stub_docstring`` matches a function by
    ``name`` AND ``lineno`` (so a same-named overload is never confused for it) and
    ``_doctests_pass`` looks the function up in the compiled namespace by ``name``;
    neither reads ``params``/``end_lineno``/``indent``/``is_method``. This lets the
    pin-doctest objective reuse the verified doctest extractor and verdict for a
    FINISHED function (which has no ``StubFunction`` of its own) addressed by its
    name+lineno alone."""
    return StubFunction(name=fn_name, params=(), lineno=fn_lineno,
                        end_lineno=fn_lineno, indent="", is_method=False)


def enforceable_examples_for_function(source: str, fn_name: str,
                                      fn_lineno: int) -> list[doctest.Example]:
    """The ENFORCEABLE ``>>>`` examples in the docstring of the function ``fn_name``
    at 1-based ``fn_lineno`` in ``source`` — every example EXCEPT a ``# doctest:
    +SKIP`` one (which ``doctest`` never runs, so it pins no contract).

    A by-(name, lineno) sibling of :func:`_enforceable_doctest_examples` (which
    takes a :class:`StubFunction`): pin-doctest addresses an ALREADY-IMPLEMENTED
    function — which has no stub record — so it identifies the function the same way
    ``_stub_docstring`` does, by name AND lineno, and reuses the SAME "which examples
    count" decision the witness miner and apply-path verifier use. Fully guarded: a
    malformed source, a missing function, or a function with no docstring yields
    ``[]`` (never raises). Deterministic: examples in source order."""
    return _enforceable_doctest_examples(source, _named_stub(fn_name, fn_lineno))


# The pin-doctest gate-1 probe: re-run a function's enforceable doctest examples
# under a PINNED ``PYTHONHASHSEED`` in a clean subprocess and report the verdict.
# Mirrors :mod:`app.execution.doctest_oracle`'s discipline: a function whose
# example's expected output is a ``set``/``dict`` repr is otherwise scored
# green-or-red by the PARENT's RANDOMIZED seed, so the pinned-seed child makes the
# gate-1 verdict deterministic (the LANDED test's own runtime safety is handled
# separately by pin-doctest refusing set/dict-repr + env-dependent examples).
# argv: source path, fn_name, fn_lineno.
_EXAMPLES_PASS_PROBE = r"""
import json, sys
src_path, fn_name, fn_lineno = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    from app.execution.stub_synthesis import (
        _doctests_pass, _enforceable_doctest_examples, _named_stub)
    source = open(src_path, encoding="utf-8").read()
    stub = _named_stub(fn_name, fn_lineno)
    examples = _enforceable_doctest_examples(source, stub)
    ok = bool(examples) and _doctests_pass(examples, source, stub)
    print(json.dumps({"ok": True, "passed": ok}))
except BaseException:  # noqa: BLE001 - any failure -> refuse (never a fake green)
    print(json.dumps({"ok": False}))
    sys.exit(0)
"""


def examples_pass(source: str, fn_name: str, fn_lineno: int) -> bool:
    """True when EVERY enforceable ``>>>`` example of the function ``fn_name`` at
    1-based ``fn_lineno`` PASSES against ``source`` itself (the function's REAL,
    already-implemented body), run by the stdlib :mod:`doctest` UNDER A PINNED
    ``PYTHONHASHSEED``.

    This is the pin-doctest gate-1 oracle: the objective never pins a RED contract,
    so it only lands a gating test when the examples are GREEN today. It mines the
    enforceable examples (:func:`enforceable_examples_for_function`) and hands them —
    with the unmodified ``source`` — to the shared compile-and-run verdict
    :func:`_doctests_pass`, accepting ONLY when every example passes.

    The verdict is taken in a CLEAN subprocess with ``PYTHONHASHSEED`` pinned to
    ``0`` (mirroring :mod:`app.execution.doctest_oracle`): an example whose expected
    output is a ``set``/``dict`` repr would otherwise pass-or-fail by the parent's
    RANDOMIZED hash seed, making this gate flip run-to-run. The pinned seed keeps the
    generation-time decision deterministic. If the subprocess cannot be run (an
    OSError spawning it) the in-process verdict is used as a fallback — conservative
    and never a fake-green either way. Conservative: NO enforceable example, a source
    that fails to compile, or a function that is not a callable module global all
    yield ``False``. Deterministic: examples in source order, fixed namespace,
    pinned seed."""
    stub = _named_stub(fn_name, fn_lineno)
    examples = _enforceable_doctest_examples(source, stub)
    if not examples:
        return False  # nothing enforceable to check — never claim it passes
    verdict = _examples_pass_seeded(source, fn_name, fn_lineno)
    if verdict is not None:
        return verdict
    return _doctests_pass(examples, source, stub)  # subprocess unavailable -> in-proc


def _examples_pass_seeded(source: str, fn_name: str, fn_lineno: int) -> bool | None:
    """Run :func:`examples_pass`'s verdict in a clean ``PYTHONHASHSEED=0`` subprocess.

    Returns ``True``/``False`` for the pinned-seed verdict, or ``None`` when the
    subprocess could not be run/parsed (so the caller falls back to the in-process
    verdict). Writes ``source`` to a temp file the child reads — the child re-mines
    the same enforceable examples and applies the same shared verdict, but under the
    fixed seed. Deterministic: same source -> same child decision."""
    import json
    import os
    from app.execution.target_env import inherited_pythonpath
    import subprocess
    import sys
    import tempfile

    root = _repo_root_on_path()
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": root + os.pathsep + inherited_pythonpath(),
    }
    with tempfile.TemporaryDirectory(prefix="apex_examples_pass_") as tmp:
        src_path = os.path.join(tmp, "src.py")
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(source)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _EXAMPLES_PASS_PROBE,
                 src_path, fn_name, str(fn_lineno)],
                capture_output=True, text=True, env=env, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    if proc.returncode != 0:
        return None
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    if not result.get("ok"):
        return None
    return bool(result.get("passed"))


def _repo_root_on_path() -> str:
    """The directory that makes ``import app`` resolve for a child subprocess — the
    parent of this module's own ``app`` package. Pure: derived from ``__file__``."""
    import os

    # .../app/execution/stub_synthesis.py -> three parents up is the repo root.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compiled_module_namespace(source: str) -> dict | None:
    """Execute ``source`` in a FRESH module namespace and return it, or ``None`` if
    it raises (a body whose import/definition side-effects fail is unverifiable, so
    the caller refuses). Sandboxed only to the extent ``exec`` of the synthesized
    module is — the body is a fixed template over the stub's own parameters, never
    arbitrary user text, and it is the SAME source the verified-apply engine would
    write to disk, so running it here mirrors the real outcome."""
    namespace: dict = {}
    try:
        exec(compile(source, "<apex-doctest>", "exec"), namespace)  # nosec B102 - fixed doctest source
    except Exception:
        return None
    return namespace


def _has_doctest_witnesses(module_source: str | None,
                           stub: StubFunction) -> bool:
    """True when ``stub`` has at least one enforceable docstring ``>>>`` witness in
    ``module_source`` — i.e. (part of) its contract is pinned by doctests, so any
    body landed for it must be doctest-VERIFIED, not pytest-verified. ``False`` when
    ``module_source`` is ``None`` (the doctest pass is opt-in) or no example mines."""
    if module_source is None:
        return False
    return bool(_doctest_witnesses(module_source, stub))


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


def _call_targets(func: ast.expr, name: str) -> bool:
    """Whether ``func`` invokes the bare name ``name`` or an attribute ending in it
    (``name(...)`` or ``mod.name(...)``)."""
    if isinstance(func, ast.Name):
        return func.id == name
    return isinstance(func, ast.Attribute) and func.attr == name


def _is_singleton(node: ast.expr) -> bool:
    """A ``None`` / ``True`` / ``False`` literal — the only RHS that makes
    ``f(x) is <v>`` a value pin (identity-equality idiom). Uses ``is`` comparisons,
    not ``in (...)``, so a falsy literal like ``0`` (``0 == False``) is never
    mistaken for a singleton."""
    return isinstance(node, ast.Constant) and (
        node.value is None or node.value is True or node.value is False)


def _is_stub_result(operand: ast.expr, name: str, bound: set[str]) -> bool:
    """Whether ``operand`` IS the stub's call result — a direct call of ``name`` or a
    local previously bound to one."""
    if isinstance(operand, ast.Call) and _call_targets(operand.func, name):
        return True
    return isinstance(operand, ast.Name) and operand.id in bound


def _compares_call_result(fn: ast.AST, name: str) -> bool:
    """Whether ``fn`` pins the stub's return by an EQUALITY/IDENTITY comparison to a
    VALUE — ``name(args) == v`` / ``name(args) is None`` inline, or via a local
    binding ``r = name(args); ... r == v``. Robust to parenthesised arguments
    (tuples, nested calls) the literal witness regex cannot parse.

    The discriminator is deliberately narrow, because a loose "any comparison
    touching the call" rule RE-OPENS the vacuous-oracle fake-green:

    * ONLY ``==`` (against any non-stub operand) and ``is`` (against a
      None/True/False singleton) pin a value the equality-witness synthesis can
      honestly satisfy. ``!=`` / ``is not`` / ``<`` / ``<=`` / ``>`` / ``>=`` /
      ``in`` / ``not in`` constrain a half-space or a non-equality, NOT a value — a
      guessed body would still fake-green through them, so they are refused.
    * a SELF-comparison (``f(x) == f(x)`` or ``r == r``) pins nothing — any body
      equals itself — so a comparison whose BOTH sides reduce to the stub result is
      refused. The value-side must be something OTHER than the stub's own result.

    A type-only check (``isinstance(name(x), str)``), a discarded call (``name(x)``
    alone), and a name-only reference (``callable(name)`` — never CALLED) have no
    qualifying comparison, so they correctly read as NOT value-pinning."""
    bound: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and _call_targets(node.value.func, name)):
            bound.update(t.id for t in node.targets if isinstance(t, ast.Name))
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for i, op in enumerate(node.ops):
            lhs_stub = _is_stub_result(operands[i], name, bound)
            rhs_stub = _is_stub_result(operands[i + 1], name, bound)
            if lhs_stub == rhs_stub:
                continue  # both sides the stub (self-comparison) or neither — no value
            other = operands[i + 1] if lhs_stub else operands[i]
            if isinstance(op, ast.Eq) or (isinstance(op, ast.Is) and _is_singleton(other)):
                return True
    return False


def _stub_call_result_compared(root: Path, test_files: list[str],
                               stub: StubFunction) -> bool:
    """True when an ENFORCED test COMPARES the stub's call result to a value — an
    AST value-pinning signal robust to parenthesised arguments the witness regex
    cannot see.

    ``_function_witnesses`` mines witnesses with a regex whose argument capture
    (``[^()]*``) cannot match a parenthesised argument, so a tuple / nested-call
    witness like ``f((3, 1)) == [3, 1]`` yields NO witness even though the test
    clearly pins a value. This AST check closes that gap by looking for a comparison
    (``==`` / ``is`` / ``<`` …) whose operand is a call of the stub (or a local bound
    to one). The genuinely vacuous shapes still read as NOT value-pinning:
    ``callable(f)`` never CALLS the stub, ``isinstance(f(x), str)`` checks only the
    type (the call is an argument, never a comparison operand), and a bare ``f(x)``
    statement compares nothing — so the vacuous-oracle refusal still holds.
    Deterministic; a parse failure is skipped (the witness/constant checks still
    decide and the run gate is final)."""
    for rel in sorted(test_files):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_is_unenforced_decorator(d) for d in fn.decorator_list):
                continue
            if _compares_call_result(fn, stub.name):
                return True
    return False


def _pins_a_value(root: Path, test_files: list[str], stub: StubFunction) -> bool:
    """True when at least one enforceable witness CONSTRAINS the stub's return — a
    ``func(<args>) == <expected>`` / ``is None/True/False`` assertion, a doctest
    example, the >=2-distinct-tuples constant ``_expected_constant`` clears, or an
    AST-visible call whose result is COMPARED (:func:`_stub_call_result_compared`).

    This is the never-fake-green floor the candidate search was missing: a test may
    REFERENCE the symbol by name (``assert callable(fn)``) — satisfying
    :func:`_has_enforceable_contract` — yet assert NOTHING about the value the stub
    returns. With no value-pinning witness, the value-free ``passthrough`` template
    (``return x``) passes such a vacuous oracle for ANY body, so a guessed body
    would be stamped "verified" while the suite stays green. We refuse instead,
    mirroring the in-process synth's ``if not witnesses: return None`` and the
    doctest path's behavior (and agreeing with the cheap scan, which already
    reports such a stub NOT fillable).

    Three independent signals say "a value is pinned"; ANY one suffices:
    ``_function_witnesses`` (the regex/parametrize/helper/doctest miner),
    ``_stub_call_result_compared`` (the AST fallback that catches a COMPARED call the
    regex can't parse — e.g. a parenthesised tuple argument), and
    ``_expected_constant`` (the >=2-distinct-tuple constant last-resort). The AST
    fallback is what keeps a legitimate ``f((3, 1)) == [3, 1]`` from being wrongly
    refused while still refusing the genuinely vacuous ``callable(fn)`` (no call),
    the type-only ``isinstance(f(x), str)``, and a discarded smoke call.
    Deterministic, offline, stdlib-only — same project, same verdict."""
    if _function_witnesses(root, test_files, stub):
        return True
    if _stub_call_result_compared(root, test_files, stub):
        return True
    return _expected_constant(root, test_files, stub) is not None


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

    Three never-fake-green floors precede the search:

    * **enforceable-contract floor** — if EVERY pinned test touching the stub is
      ``xfail`` / ``skip``, the gate is meaningless (an xfail test stays green for
      any body), so we refuse rather than stamp an unenforced contract verified;
    * **value-pinning floor** (:func:`_pins_a_value`) — a test may merely REFERENCE
      the symbol (``assert callable(fn)``) without asserting anything about its
      return; the value-free ``passthrough`` template then passes for ANY body, so
      a guessed body would be stamped "verified". When NO witness constrains the
      return we refuse, mirroring the in-process synth's ``if not witnesses:
      return None`` (this is the apply path agreeing with the scan, which already
      reports such a stub NOT fillable);
    * **ambiguity floor** — if >=2 fixed templates of DIFFERENT shape both satisfy
      ALL the enforceable witnesses, the witnesses don't determine intent, so we
      refuse (mirror ``cross_file_rename``'s conservatism on an ambiguous spec)."""
    if not test_files:
        return None
    if not _has_enforceable_contract(root, test_files, stub):
        return None  # only xfail/skip tests pin this stub — no real contract
    if not _pins_a_value(root, test_files, stub):
        return None  # no witness constrains the return — any body fake-greens
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
                            stub: StubFunction,
                            module_source: str | None = None) -> list[tuple[str, str]]:
    """Public view of the fixed-order candidate list for ``stub`` — the
    parameter-shaped templates first, then the last-resort constant (when the
    tests pin one literal across >=2 distinct tuples). Used by the per-module
    batch planner to coordinate sibling stubs whose pinned tests share one file
    (where no single stub goes green until the others are filled too).

    ``module_source`` adds the stub's docstring ``>>>`` examples to the seeding
    witness set, so a value-derived template can be proposed from a doctest-only
    contract too. With it ``None`` (the default) the list is byte-for-byte as
    before."""
    return _ordered_candidates(root, test_files, stub, module_source)


def synthesize_expr_from_witnesses(root: Path, test_files: list[str],
                                   stub: StubFunction,
                                   module_source: str | None = None) -> str | None:
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
    templates is ambiguous, so we refuse rather than land an arbitrary first.

    ``module_source`` (the module under fill) is threaded through so the stub's OWN
    docstring ``>>>`` examples join the witness set — a doctest-only contract is
    synthesizable through the same gate. When the chosen expr was determined with
    doctest witnesses in play, it is additionally re-verified by RUNNING those
    examples (:func:`verify_body_via_doctest`) so the scan never accepts a body the
    doctest-verified apply could not land. With ``module_source`` ``None`` (the
    default) the search is byte-for-byte the prior test-file-only behavior."""
    if not _has_enforceable_contract(root, test_files, stub):
        return None  # only xfail/skip tests pin this stub — no real contract
    witnesses = _function_witnesses(root, test_files, stub, module_source)
    if not witnesses:
        return None
    evaluable = _evaluable_witnesses(witnesses, stub)
    if evaluable is None:
        return None
    if _is_ambiguous(root, test_files, stub, module_source):
        return None  # witnesses fit >=2 different-shape templates — under-specified
    uses_doctest = _has_doctest_witnesses(module_source, stub)
    for _label, expr in _ordered_candidates(root, test_files, stub, module_source):
        if not _expr_matches_all(expr, stub, evaluable):
            continue
        if uses_doctest and not verify_body_via_doctest(module_source, stub, expr):
            continue  # doctest-pinned: the apply gate runs the examples — agree
        return expr
    return None


def can_fill_stub_in_process(root: Path, test_files: list[str],
                             stub: StubFunction,
                             module_source: str | None = None) -> bool:
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
    authority on whether it actually lands (a no-op if it doesn't).

    ``module_source`` threads the stub's docstring ``>>>`` examples into the witness
    set, so a doctest-only stub is correctly counted as fillable — but ONLY through
    the in-process synth above, which doctest-VERIFIES the body it accepts (so the
    scan agrees with the doctest-gated apply). The non-evaluable conservative branch
    is justified solely by a real pytest gate, so it is SKIPPED when there are no
    pinned ``test_*.py`` files (a doctest-only stub has no pytest path to fall back
    on): it would otherwise over-count a doctest stub the apply could never land.
    With ``module_source`` ``None`` (the default) the estimate is byte-for-byte the
    prior test-file-only behavior."""
    if not _has_enforceable_contract(root, test_files, stub):
        return False  # only xfail/skip tests pin this stub — apply would refuse too
    if synthesize_expr_from_witnesses(root, test_files, stub, module_source) is not None:
        return True
    if _recursion_matches(root, test_files, stub, module_source):
        return True
    # In-process synthesis couldn't decide. The conservative count below leans on
    # the pytest apply gate to decide for real, so it only applies when a pinned
    # test file actually exists; a doctest-ONLY stub has no such gate (its sole
    # authority is the doctest verification the synth already ran), so counting it
    # here would over-count. If the witnesses aren't evaluable in-process the pytest
    # gate might still land a value-free template — count it conservatively rather
    # than under-count. If the witnesses ARE evaluable yet nothing matched, the
    # apply path would refuse too (same templates, same gate), so it is honestly NOT
    # counted.
    if not test_files:
        return False
    return _has_pinned_but_non_evaluable_witnesses(root, test_files, stub, module_source)


def _has_pinned_but_non_evaluable_witnesses(root: Path, test_files: list[str],
                                            stub: StubFunction,
                                            module_source: str | None = None) -> bool:
    """True when ``stub`` has enforceable pinned witnesses that the in-process
    evaluator CANNOT turn into literal ``(args, expected)`` pairs (a non-literal
    call site). Such a contract is undecidable in-process, so the cheap scan
    counts it conservatively (the pytest apply gate decides for real) rather than
    risk under-counting a stub the pytest path could still fill. A stub with no
    enforceable witnesses at all is NOT counted (no contract to satisfy).
    ``module_source`` adds the stub's docstring witnesses to the considered set."""
    witnesses = _function_witnesses(root, test_files, stub, module_source)
    if not witnesses:
        return False
    return _evaluable_witnesses(witnesses, stub) is None


def _recursion_matches(root: Path, test_files: list[str],
                       stub: StubFunction,
                       module_source: str | None = None) -> bool:
    """True when a recursion template (the ``__apex_self__`` shapes) reproduces
    every enforceable witness for ``stub``, evaluated AS a real recursive function
    in-process (no pytest). The pure-expression synth skips recursion because
    ``__apex_self__`` has no binding; here we wrap each recursion body in an
    actual ``def`` over the stub's parameters so factorial/fibonacci can be
    checked cheaply. Runs the same enforceable-contract / ambiguity floors first,
    so it never offers a stub the apply path would refuse. Deterministic.

    ``module_source`` threads the stub's docstring witnesses into the checked set;
    when those doctests are part of the contract the matched recursion body is
    additionally re-run against the examples (:func:`verify_body_via_doctest`) so
    the scan agrees with the doctest-gated apply."""
    return _recursion_body(root, test_files, stub, module_source) is not None


def _recursion_body(root: Path, test_files: list[str], stub: StubFunction,
                    module_source: str | None = None) -> str | None:
    """The recursion BODY expr (with the ``__apex_self__`` marker) that reproduces
    every enforceable small-magnitude witness for ``stub`` evaluated as a real
    recursive function in-process, or ``None`` when none does. The single source of
    truth :func:`_recursion_matches` (the scan bool) wraps and the doctest-gated
    apply lands, so the cheap recursion estimate and the doctest apply agree by
    construction. Runs the same enforceable-contract / ambiguity floors first.

    Evaluation is bounded to SMALL-magnitude witnesses: the fibonacci template is
    EXPONENTIAL, so ``fib(95)`` would never terminate in-process. A recursion-shaped
    contract is pinned by small base/step cases anyway (``fact(0)==1, fact(5)==120``),
    so the bound keeps the check fast without missing a real recursion. A contract
    whose ONLY witnesses are large yields no small witness, so recursion is honestly
    not claimed. When the contract is doctest-pinned the matched body is also re-run
    against the examples (:func:`verify_body_via_doctest`)."""
    if not _has_enforceable_contract(root, test_files, stub):
        return None
    witnesses = _function_witnesses(root, test_files, stub, module_source)
    evaluable = _evaluable_witnesses(witnesses, stub) if witnesses else None
    if not evaluable:
        return None
    if _is_ambiguous(root, test_files, stub, module_source):
        return None
    small = [(args, exp) for args, exp in evaluable
             if all(isinstance(a, int) and abs(a) <= _RECURSION_WITNESS_CAP
                    for a in args)]
    if len({args for args, _e in small}) < 2:
        return None  # too few small witnesses to determine a recursion cheaply
    candidates = _ordered_candidates(root, test_files, stub, module_source)
    return _first_matching_recursion(candidates, stub, small, module_source)


def _first_matching_recursion(candidates: list[tuple[str, str]], stub: StubFunction,
                              small: list[tuple[tuple, object]],
                              module_source: str | None) -> str | None:
    """The first recursion-shaped (``__apex_self__``) ``candidates`` expr that
    reproduces every ``small`` witness as a real recursive function, or ``None``.
    When ``module_source`` carries doctest witnesses the match is additionally
    re-run against the examples so the scan agrees with the doctest apply."""
    uses_doctest = _has_doctest_witnesses(module_source, stub)
    for _label, expr in candidates:
        if "__apex_self__" not in expr:
            continue
        if not _recursive_expr_matches_all(expr, stub, small):
            continue
        if uses_doctest and not verify_body_via_doctest(module_source, stub, expr):
            continue  # doctest-pinned: the apply runs the examples — agree
        return expr
    return None


def synthesize_doctest_body(root: Path, test_files: list[str], stub: StubFunction,
                            module_source: str | None) -> str | None:
    """The body expr the DOCTEST-gated apply should land for a doctest-pinned
    ``stub``, or ``None`` when it is not doctest-pinnable. This mirrors EXACTLY the
    doctest acceptance of :func:`can_fill_stub_in_process` — the pure-expression
    synth first (which doctest-verifies the expr it returns), then a doctest-verified
    recursion body — so the scan and the apply land the identical set (the no-over/
    under-count invariant). A stub WITHOUT a minable doctest witness yields ``None``
    here: it is not this path's responsibility (the pytest-gated passes own it), so
    the existing test-file-only behavior is untouched. Deterministic."""
    if not _has_doctest_witnesses(module_source, stub):
        return None  # not doctest-pinned — leave it to the pytest-gated passes
    expr = synthesize_expr_from_witnesses(root, test_files, stub, module_source)
    if expr is not None:
        return expr  # already doctest-verified inside synthesize_expr_from_witnesses
    return _recursion_body(root, test_files, stub, module_source)


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
        exec(compile(src, "<apex-recursion>", "exec"), env)  # nosec B102 - fixed templates
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
    landable stub, recursion included).

    The module ``source`` is forwarded to :func:`can_fill_stub_in_process` so a
    stub whose contract lives in its docstring ``>>>`` examples (and so has NO
    pinned ``test_*.py`` file) is also weighed — its doctest witnesses are mined and
    the body the scan accepts is doctest-VERIFIED, so the doctest-gated apply lands
    exactly the same set (no over-count). A stub with neither a pinned test nor a
    minable doctest witness contributes nothing, as before."""
    if _is_test_or_fixture(module_rel):
        return False
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return False
    for stub in find_stub_functions(source):
        tests = pinned_test_files(root, module_rel, stub.name)
        if can_fill_stub_in_process(root, tests, stub, source):
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
    sentinel ``_NO_LITERAL`` when it is not a literal.

    The whole fragment is parsed FIRST: ``ast.literal_eval`` already ignores a
    genuine trailing ``# comment`` (the tokenizer drops it), so a value that itself
    contains ``#`` inside a string repr (``'#tag'`` — a merged doctest want) is no
    longer truncated by the comment-strip below. Only if the whole-fragment parse
    fails do we fall back to splitting on the first ``#`` and re-parsing — keeping
    every previously-parseable input byte-for-byte identical (the fallback fires
    only for inputs that did not literal-eval as written before either)."""
    text = expected_text.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        pass
    try:
        return ast.literal_eval(text.split("#")[0].strip())
    except (ValueError, SyntaxError, TypeError):
        return _NO_LITERAL


_SAFE_BUILTINS = {
    "len": len, "min": min, "max": max, "sorted": sorted, "sum": sum,
    "abs": abs, "round": round, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "tuple": tuple,
    # Value-free int->str maps (the radix formatters + ``chr``) and the
    # str->codepoint ``ord``, present so the in-process matcher / fingerprint can
    # evaluate the ``hex``/``oct``/``bin``/``chr`` int templates and the ``ord`` str
    # template; without them the sandbox eval raises NameError and
    # ``can_fill_stub_in_process`` under-counts (the develop-loop move-scan would
    # never offer a body the pytest-gated apply lands). Each is a pure total function
    # on its domain (PYTHONHASHSEED-independent), so adding them lands no unsound body.
    "hex": hex, "oct": oct, "bin": bin, "chr": chr, "ord": ord,
    # ``bytes``/``bytearray`` materialize an iterable-of-ints / str into a bytes
    # container — value-free and order-preserving for a list/tuple/str arg
    # (hashseed-safe); a ``set`` arg is gated out upstream (``_has_set_arg``) exactly
    # as ``list``/``tuple`` are, and ``frozenset`` is never offered as a body.
    "bytes": bytes, "bytearray": bytearray,
    # ``set`` is present ONLY so the in-process matcher can evaluate the
    # DETERMINISTIC count ``len(set(a))`` (the distinct-count family). Without it
    # the sandbox eval raises NameError, ``can_fill_stub_in_process`` under-counts,
    # and the develop-loop move-scan never offers a distinct-count stub the
    # pytest-gated apply would actually land (breaking the documented no-under-count
    # invariant). A bare value-returning ``set(a)`` body stays forbidden upstream
    # (hash-seed-dependent order), so adding ``set`` here introduces no unsound body.
    "set": set,
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
            value = eval(expr, env_globals, local)  # nosec B307 - fixed templates only
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


def _is_ambiguous(root: Path, test_files: list[str], stub: StubFunction,
                  module_source: str | None = None) -> bool:
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
    or not the diagnosis is ever rendered (the disclosure is purely additive).

    ``module_source`` threads the docstring witnesses into the weighed set, so a
    doctest-only contract is checked for ambiguity exactly like a test-file one."""
    return _ambiguity_diagnosis(root, test_files, stub, module_source) is not None


def _ambiguity_diagnosis(root: Path, test_files: list[str],
                         stub: StubFunction,
                         module_source: str | None = None) -> AmbiguityDiagnosis | None:
    """The structured ambiguity finding for ``stub`` — ``None`` when the contract
    is NOT ambiguous, else the two representative competing exprs, the first
    discriminating canary input, and each expr's value there.

    This is the single source of truth :func:`_is_ambiguous` wraps: it computes
    the SAME ``matching`` shapes (identity-family collapsed, constant/recursion
    excluded) the bool guard always did, then — instead of discarding everything
    but the verdict — keeps the FIRST pair whose fingerprints diverge and the
    EARLIEST canary at which they do. Deterministic throughout: candidates and
    canaries are in their fixed order, so the chosen pair and input are stable.
    ``module_source`` threads the stub's docstring witnesses into the weighed set."""
    witnesses = _function_witnesses(root, test_files, stub, module_source)
    evaluable = _evaluable_witnesses(witnesses, stub) if witnesses else None
    if not evaluable:
        return None
    matching = _matching_shapes(root, test_files, stub, evaluable, module_source)
    if len(matching) < 2:
        return None
    canaries = _canary_inputs(evaluable)
    return _first_divergence(matching, stub, canaries)


def _matching_shapes(root: Path, test_files: list[str], stub: StubFunction,
                     evaluable: list[tuple[tuple, object]],
                     module_source: str | None = None) -> list[str]:
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
    for label, expr in _ordered_candidates(root, test_files, stub, module_source):
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
        return repr(eval(expr, env_globals, local))  # nosec B307 - fixed templates
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


def stub_decline_reason(module_source: str, stub: StubFunction,
                        has_pinned_test: bool = False) -> str | None:
    """A deterministic, human-readable DECLINE message (NEW) for a stub that
    DOCUMENTS a return — a docstring ``Returns:`` / ``:returns:`` / ``:return:``
    section or a non-``None`` return annotation — yet pins NO synthesizable example:
    no enforceable docstring ``>>>`` witness and no pinned test. ``None`` when the
    stub is synthesizable (has an example/test) or documents no return at all.

    This is DISCLOSURE, not a body: with a documented return type but no executable
    example, every candidate would be a GUESS, so Apex synthesizes nothing (the
    never-guess discipline) and instead names exactly what is missing, e.g.::

        declined: `parse` documents a return but pins no example/test — add one
        `>>>` line or a test so Apex can synthesize a verified body

    It NEVER changes what lands (it returns a string for a stub the engine already
    refuses) — purely additive, mirroring :func:`ambiguity_reason`. Pure and
    deterministic: a fixed reading of the docstring/annotation, no disk, no clock.
    ``has_pinned_test`` lets a caller that already resolved the stub's pinned test
    files suppress the decline when a test exists (the stub is then synthesizable
    through the pytest gate, so there is nothing to decline)."""
    if has_pinned_test:
        return None
    if _doctest_witnesses(module_source, stub):
        return None  # a doctest example pins it — synthesizable, not declined
    if not _documents_return(module_source, stub):
        return None  # documents no return — not this disclosure's concern
    return (f"declined: `{stub.name}` documents a return but pins no example/test "
            f"— add one `>>>` line or a test so Apex can synthesize a verified body")


def _documents_return(module_source: str, stub: StubFunction) -> bool:
    """True when ``stub`` DOCUMENTS a return value — either a non-``None`` return
    ANNOTATION on the ``def`` or a docstring section that names a returned value
    (``Returns:`` / ``Return:`` Google/NumPy heading, or a ``:returns:`` /
    ``:return:`` reST field). Used only to decide whether a SYNTHESIS-less stub
    deserves an honest decline; it never feeds the template engine. Conservative
    and fully guarded: an unparseable source yields ``False`` (never raises).
    Deterministic: a fixed scan of the AST and docstring text."""
    if _return_annotation_text(module_source, stub) not in (None, "None"):
        return True
    docstring = _stub_docstring(module_source, stub)
    if not docstring:
        return False
    for line in docstring.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith((":returns:", ":return:")):
            return True
        if stripped.rstrip(":") in ("returns", "return") and stripped.endswith(":"):
            return True
    return False


def _return_annotation_text(module_source: str, stub: StubFunction) -> str | None:
    """The SOURCE text of ``stub``'s return annotation (``-> T``), or ``None`` when
    it has none or the source does not parse. The function is matched by name AND
    1-based ``lineno`` (never confusing an overload). Fully guarded — a malformed
    source raises nothing. Deterministic."""
    try:
        tree = ast.parse(module_source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == stub.name and node.lineno == stub.lineno):
            if node.returns is None:
                return None
            return ast.unparse(node.returns)
    return None


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
    a genuine ``identity(5)==5, identity(9)==9``.

    Each witnessed FLAT-REGION boundary (an expected value that differs from its
    input — a saturated clamp/relu output) also contributes its just-inside /
    just-outside neighbours (``b-1``/``b``/``b+1``), so two clamps with DIFFERENT
    boundaries (``max(0, min(50, a))`` vs ``max(0, min(99, a))``) are split right at
    the boundary even when the bare witnessed neighbours miss it. These are valid
    int inputs (the contract's own output values), so they never fabricate a
    divergence for a single-shape contract — they only sharpen the clamp family."""
    extra: set[int] = set()
    for args, _e in witnesses:
        v = args[0]
        extra.update({v - 1, v + 1})
    extra.update({0, 1, 2, 3, 50, 99, 100})
    if any(args[0] < 0 for args, _e in witnesses):
        extra.add(-1)
    extra.update(_boundary_neighbors(witnesses, int))
    return [(v,) for v in sorted(extra)]


def _boundary_neighbors(witnesses: list[tuple[tuple, object]],
                        kind: type) -> set:
    """The just-inside / just-outside neighbours (``b-1``, ``b``, ``b+1``) of every
    witnessed FLAT-REGION boundary — an expected output that differs from its
    single ``kind`` (``int``/``float``) input, i.e. a saturated clamp/relu value.
    These probes split two clamp bodies whose boundaries differ; an unsaturated
    (pass-through) witness contributes nothing. ``set()`` for a non-matching
    contract. Pure and deterministic — derived only from witnessed literals."""
    out: set = set()
    for args, expected in witnesses:
        if len(args) != 1:
            continue
        v = args[0]
        if isinstance(v, bool) or isinstance(expected, bool):
            continue
        if not isinstance(v, kind) or not isinstance(expected, kind):
            continue
        if expected != v:
            out.update({expected - 1, expected, expected + 1})
    return out


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
    matching shape to disagree with. Deduped + sorted for determinism.

    Each witnessed FLOAT FLAT-REGION boundary (an expected value differing from its
    input — a saturated clamp) also contributes its neighbours so two float clamps
    with different boundaries diverge right at the boundary, exactly as the int
    path does."""
    extra: set[float] = set()
    for args, _e in witnesses:
        v = args[0]
        extra.update({-v, v + 0.5, v + 0.125})
    extra.update({0.0, -1.5})
    extra.update(_boundary_neighbors(witnesses, float))
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
      reduction contract is unaffected.

    For an ALL-NUMERIC sequence two further PER-ELEMENT-PERTURBED probes split the
    element-wise MAP family: each witnessed element incremented by one, plus the
    fixed canonical ``[1, 2, 3]`` (or its tuple form) whose distinct non-zero
    elements separate ``[x * 2 …]`` from ``[x * 3 …]``, ``[x + 1 …]`` from a plain
    map, and a reduction from a comprehension. Without these, an all-zero witness
    (``f([0, 0]) == [0, 0]``) leaves every linear transform AGREEING and a wrong map
    body could land; the canonical probe makes the divergence observable, so the
    ambiguity guard honestly refuses an under-specified map contract. The probes
    stay the witnessed sequence's own type (``list``/``tuple``), valid inputs of the
    same shape, so they never fabricate a divergence for a single-shape contract."""
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
        if seq and all(_is_plain_number(el) for el in seq):
            out.append((type(seq)(el + 1 for el in seq),))  # per-element perturb
            out.append((type(seq)([1, 2, 3]),))  # distinct non-zero: splits maps
    return out


def _is_plain_number(value: object) -> bool:
    """True for a genuine ``int``/``float`` element (``bool`` excluded). Gates the
    per-element MAP-family perturbation probes so only a numeric sequence (where
    ``el + 1`` and the ``[1, 2, 3]`` anchor are valid, divergence-revealing inputs)
    contributes them; a string/other element sequence is unaffected."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
            value = eval(expr, env_globals, local)  # nosec B307 - fixed templates only
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
                        stub: StubFunction,
                        module_source: str | None = None) -> list[tuple[str, str]]:
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
    is still gated against the tests before it lands. ``module_source`` adds the
    stub's docstring ``>>>`` examples to the seeding witness set, so a value-derived
    template (``n * 2``) can be proposed from a doctest-only contract too; the
    constant last-resort still reads only the pinned test files (a doctest-only
    constant-return is an honest under-claim, never landed unverified)."""
    witnesses = _function_witnesses(root, test_files, stub, module_source)
    out: list[tuple[str, str]] = list(candidate_bodies(stub, witnesses))
    const = _expected_constant(root, test_files, stub)
    if const is not None:
        out.append(("constant", const))
    return out
