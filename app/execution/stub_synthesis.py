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
from dataclasses import dataclass
from pathlib import Path

from app.skills.execution.run_tests import RunTestsSkill

__all__ = [
    "StubFunction",
    "find_stub_functions",
    "pinned_test_files",
    "candidate_bodies",
    "ordered_candidate_exprs",
    "synthesize_expr_from_witnesses",
    "fill_stub_body",
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
        out.extend(_two_arg_templates(params[0], params[1]))
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
    ARGUMENT text of the witnesses so common slug/clean shapes are reachable."""
    out: list[tuple[str, str]] = [
        ("lower", f"{a}.lower()"),
        ("upper", f"{a}.upper()"),
        ("strip", f"{a}.strip()"),
        ("title", f"{a}.title()"),
        ("lower.strip", f"{a}.lower().strip()"),
    ]
    strings = _string_constants(witnesses)
    for old, new in _ordered_string_pairs(strings):
        out.append((f"replace({old},{new})", f"{a}.replace({old}, {new})"))
        out.append((f"lower.replace({old},{new})",
                    f"{a}.lower().replace({old}, {new})"))
    for sep in strings:
        out.append((f"split({sep})", f"{a}.split({sep})"))
    return out


def _two_arg_templates(a: str, b: str) -> list[tuple[str, str]]:
    """Two-arg binary templates in a fixed order. Covers numeric arithmetic and,
    via ``+``, string/list concatenation; boolean ``and``/``or``; comparison;
    and ``a.join(b)`` for the ``sep.join(xs)`` shape."""
    ops = ["+", "-", "*", "//", "%", "/"]
    out = [(op, f"{a} {op} {b}") for op in ops]
    out.append(("and", f"{a} and {b}"))
    out.append(("or", f"{a} or {b}"))
    out.append(("<", f"{a} < {b}"))
    out.append(("<=", f"{a} <= {b}"))
    out.append(("==", f"{a} == {b}"))
    out.append(("join", f"{a}.join({b})"))
    return out


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
    in-process synthesis. Deterministic: source order within each sorted file."""
    call_eq = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(stub.name)
        + r"\s*\(([^()]*)\)\s*==\s*([^\n#]+)")
    out: list[tuple[str, str]] = []
    for rel in sorted(test_files):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        excluded = _unenforced_line_ranges(text)
        for m in call_eq.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            if _line_in_ranges(line, excluded):
                continue  # assertion lives in an xfail/skip test — not a contract
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


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

    for label, expr in _ordered_candidates(root, test_files, stub):
        candidate = _rewrite_with_body(source, stub, expr)
        if candidate is None:
            continue
        if _candidate_passes(root, module_rel, candidate, test_files, runner):
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
    evaluable witnesses there is nothing to disambiguate, so it returns
    ``False``."""
    witnesses = _function_witnesses(root, test_files, stub)
    evaluable = _evaluable_witnesses(witnesses, stub) if witnesses else None
    if not evaluable:
        return False
    matching: list[str] = []
    for label, expr in _ordered_candidates(root, test_files, stub):
        if label == "constant" or "__apex_self__" in expr:
            continue
        if _expr_matches_all(expr, stub, evaluable):
            matching.append(expr)
    if len(matching) < 2:
        return False
    canaries = _canary_inputs(evaluable)
    fingerprints: set[tuple] = set()
    for expr in matching:
        fingerprints.add(_expr_fingerprint(expr, stub, canaries))
        if len(fingerprints) >= 2:
            return True  # two passing templates disagree off-witness — ambiguous
    return False


def _canary_inputs(witnesses: list[tuple[tuple, object]]) -> list[tuple]:
    """A fixed, deterministic set of off-witness probe inputs for the ambiguity
    check, built from the witnessed argument tuples. For a single int argument we
    probe small neighbours of the witnessed values (``v-1``, ``v+1``, plus a few
    fixed anchors) so two bodies that agree on the witnesses but diverge nearby
    (parity vs threshold) are caught. The witnessed tuples themselves are always
    included. Multi-arg / non-int args fall back to the witnessed tuples alone —
    two bodies that disagree there already disagree on a witness, which the gate
    catches anyway, so the guard stays conservative (never over-refuses)."""
    probes: list[tuple] = [args for args, _expected in witnesses]
    arity = len(probes[0]) if probes else 0
    if arity == 1 and all(isinstance(args[0], int) and not isinstance(args[0], bool)
                          for args, _e in witnesses):
        extra: set[int] = set()
        for args, _e in witnesses:
            v = args[0]
            extra.update({v - 1, v + 1})
        extra.update({0, 1, 2, 3, 50, 99, 100, -1})
        for v in sorted(extra):
            probes.append((v,))
    # De-duplicate while preserving deterministic order.
    seen: set[tuple] = set()
    ordered: list[tuple] = []
    for p in probes:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


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
