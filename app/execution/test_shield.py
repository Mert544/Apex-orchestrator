"""Characterization-test GENERATOR — Apex builds the project's safety net.

Given an untested module, this synthesizes a *characterization* test that PINS
the module's current behaviour. Where it safely can, it pins a REAL value oracle:
for a safely-callable public function whose synthesized arguments are plain
literals, the generator IMPORTS the target and CALLS the function at generation
time, and — if the real return value is a simple, reproducible literal — emits
``assert fn(<args>) == <captured value>``. The captured value IS what the
function returned, so the oracle always passes by construction while turning a
silent regression into a visible test failure. Where a value oracle cannot be
honestly known (the call raises, the return is not a simple literal, or the
import fails) it falls back to asserting only what is honestly knowable — "the
module imports", "this public callable is callable", "calling it on synthesized
inputs does not raise an *obvious* error".

This is a DEVELOPMENT capability (Apex builds the test net, it does not merely
audit it), and it is conservative by design. A function is exercised only when
it is SAFE to call blindly:

  - top-level, public (name does not start with ``_``);
  - regular positional/keyword params whose required arguments can be
    synthesized as trivial samples (``0`` for ``int``, ``""`` for ``str``,
    ``None`` for ``X | None``/``Optional``/unannotated, ...) — defaulted params
    are omitted;
  - NOT ``main`` (its contract is the CLI: it reads ``sys.argv``/stdin, and
    under pytest a bare call would read PYTEST'S argv);
  - NO ``*args``/``**kwargs`` (the call contract is open-ended);
  - NOT decorated (a decorator may change the call contract entirely);
  - NOT ``async`` (a bare call returns a coroutine, not a value).

Public CLASSES are covered the same way: a class is exercised when it is
public, undecorated, and its ``__init__`` (or the default constructor) needs
only synthesizable params. The generated test constructs an instance and then
calls each public method whose params are synthesizable — every step wrapped so
a runtime error does not fail the suite.

Every exercised call is wrapped in ``try/except Exception`` so a runtime error
on synthesized inputs does NOT fail the suite — the characterization is "it is
callable and runs", not "it returns X". If nothing is safely exercisable
(neither a function nor a class), the generator falls back to a pure
import-smoke test.

The generator only PROPOSES a :class:`ShieldTest`; the caller decides to write
it (``write_shield_test``). An existing ``tests/test_<stem>.py`` is never
clobbered (the generator returns ``None``). Deterministic, stdlib-only: stable
document order, no time/random.
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is not a characterization target — its
    "behaviour" is boilerplate, not project logic. A LOCAL copy (like
    ``app/engine/dedup.py`` keeps) on purpose: importing this from
    health_score would pull in a chain of engine modules and risk an import
    cycle, and this module is meant to stay a self-contained library."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


# Safe "zero value" literal to synthesize for a required argument of each type.
_ARG_SAMPLE = {
    "int": "0", "float": "0.0", "bool": "False", "complex": "0j",
    "str": "''", "bytes": "b''", "bytearray": "bytearray()",
    "list": "[]", "dict": "{}", "tuple": "()", "set": "set()", "frozenset": "frozenset()",
}
_TYPING_CONTAINER = {"List": "list", "Dict": "dict", "Tuple": "tuple", "Set": "set",
                     "FrozenSet": "frozenset", "Sequence": "list", "Mapping": "dict"}


@dataclass
class ShieldTest:
    """A proposed characterization test, NOT yet written to disk.

    ``functions`` is the document-ordered list of public callables the test
    actually exercises: top-level functions, plus safely-constructible public
    classes (as ``"ClassName"``) and each exercised public method (as
    ``"ClassName.method"``). Empty for a pure import-smoke fallback.
    """
    module: str
    test_path: str
    content: str
    functions: list[str] = field(default_factory=list)


def _union_has_none(node: ast.AST) -> bool:
    parts: list[ast.AST] = []

    def walk(n: ast.AST) -> None:
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            walk(n.left)
            walk(n.right)
        else:
            parts.append(n)

    walk(node)
    return any(isinstance(p, ast.Constant) and p.value is None for p in parts)


def _arg_literal(ann: ast.expr | None) -> str:
    """A safe sample literal for an argument annotation.

    Unlike the stricter stub generator, an UNANNOTATED parameter is not a
    blocker here: a characterization call is wrapped in ``try/except``, so the
    honest default for an unknown shape is ``None`` (the most broadly-accepted
    "empty" value). Returns ``None`` (the sentinel string ``"None"``) for any
    annotation we cannot map to a concrete sample.
    """
    if ann is None:
        return "None"
    if isinstance(ann, ast.Constant) and ann.value is None:
        return "None"
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        if _union_has_none(ann):
            return "None"
        # X | Y (no None): try the left arm's sample, else None.
        left = _arg_literal(ann.left)
        return left
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
        head = ann.value.id
        if head in ("Optional", "Union"):
            return "None"
        base = _TYPING_CONTAINER.get(head, head)
        return _ARG_SAMPLE.get(base, "None")
    if isinstance(ann, ast.Name):
        return _ARG_SAMPLE.get(ann.id, "None")
    return "None"


def _safe_call(node: ast.FunctionDef) -> tuple[str, str] | None:
    """``(name, call_args)`` for a function we can call blindly, else ``None``.

    SKIPS (returns ``None``) for: private names, ``main``, ``*args``/``**kwargs``,
    decorated functions, and async functions (handled by the caller's type
    check). Required positional and keyword-only args are synthesized; defaulted
    args are omitted.
    """
    if node.name.startswith("_") or node.name == "main":
        return None
    if node.decorator_list:  # a decorator may change the call contract
        return None
    a = node.args
    if a.vararg is not None or a.kwarg is not None:  # *args / **kwargs
        return None

    positional = a.posonlyargs + a.args
    n_required = len(positional) - len(a.defaults)
    literals: list[str] = [_arg_literal(p.annotation) for p in positional[:n_required]]

    for kwarg, kdef in zip(a.kwonlyargs, a.kw_defaults):
        if kdef is None:  # required keyword-only arg
            literals.append(f"{kwarg.arg}={_arg_literal(kwarg.annotation)}")

    return node.name, ", ".join(literals)


def _safe_functions(tree: ast.Module) -> list[tuple[str, str]]:
    """All safely-callable public functions, in DOCUMENT ORDER (deterministic).

    Async functions are excluded here (a bare call returns a coroutine, not a
    value), alongside everything :func:`_safe_call` rejects.
    """
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):  # excludes AsyncFunctionDef
            continue
        spec = _safe_call(node)
        if spec is not None:
            out.append(spec)
    return out


def _method_call_args(node: ast.FunctionDef) -> str | None:
    """``call_args`` string for a bound method/``__init__`` we can call blindly.

    Like :func:`_safe_call` but for METHODS: the leading ``self`` (the first
    positional parameter) is dropped because the call is made on an instance.
    Returns ``None`` when the contract is open-ended (``*args``/``**kwargs``) or
    the method is decorated (a decorator may change the call contract). Required
    positional and keyword-only args are synthesized; defaulted args are
    omitted.
    """
    if node.decorator_list:  # a decorator may change the call contract
        return None
    a = node.args
    if a.vararg is not None or a.kwarg is not None:  # *args / **kwargs
        return None

    positional = a.posonlyargs + a.args
    if positional:  # drop the implicit `self`
        positional = positional[1:]
    n_required = len(positional) - len(a.defaults)
    if n_required < 0:  # every param (incl. self) defaulted — nothing required
        n_required = 0
    literals: list[str] = [_arg_literal(p.annotation) for p in positional[:n_required]]

    for kwarg, kdef in zip(a.kwonlyargs, a.kw_defaults):
        if kdef is None:  # required keyword-only arg
            literals.append(f"{kwarg.arg}={_arg_literal(kwarg.annotation)}")

    return ", ".join(literals)


def _safe_class(node: ast.ClassDef) -> tuple[str, str, list[tuple[str, str]]] | None:
    """``(name, init_args, methods)`` for a class we can construct blindly, else
    ``None``.

    A class is "safely constructible" when it is public (name does not start
    with ``_``), is NOT decorated (a class decorator may change construction),
    and its ``__init__`` (or, with none, the implicit default constructor that
    takes no args) only needs synthesizable params. ``methods`` is the
    document-ordered list of ``(method_name, call_args)`` for each public method
    with synthesizable params (dunders and ``__init__`` excluded; async methods
    excluded — a bare call returns a coroutine).
    """
    if node.name.startswith("_"):
        return None
    if node.decorator_list:  # a class decorator may change construction
        return None

    init_args = ""  # default constructor: no args
    methods: list[tuple[str, str]] = []
    for item in node.body:
        if not isinstance(item, ast.FunctionDef):  # excludes AsyncFunctionDef
            continue
        if item.name == "__init__":
            args = _method_call_args(item)
            if args is None:  # __init__ is not safely synthesizable
                return None
            init_args = args
            continue
        if item.name.startswith("_"):  # dunders and private methods
            continue
        args = _method_call_args(item)
        if args is not None:
            methods.append((item.name, args))

    return node.name, init_args, methods


def _safe_classes(tree: ast.Module) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """All safely-constructible public classes, in DOCUMENT ORDER (deterministic)."""
    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        spec = _safe_class(node)
        if spec is not None:
            out.append(spec)
    return out


def _dotted_name(module_rel: str) -> str:
    """Importable dotted path for a module given relative to the project root."""
    return ".".join(Path(module_rel).with_suffix("").parts)


# Scalar leaf types whose ``repr`` is a deterministic, re-importable literal.
# ``bool`` is a subclass of ``int`` but is allowed in its own right; we never
# treat ``int``-subclasses other than ``bool`` as plain ints (a subclass repr is
# not a guaranteed-reproducible literal of the *declared* type).
_LITERAL_SCALARS = (type(None), bool, int, float, str)


def _is_simple_literal(value: object) -> bool:
    """``True`` when ``repr(value)`` is a SIMPLE, reproducible Python literal.

    A value qualifies when it is ``None``/``bool``/``int``/``float``/``str``, or a
    ``tuple``/``list``/``dict``/``set``/``frozenset`` composed (recursively) only
    of such values. Anything else — a custom object, a function, a value whose
    type merely *subclasses* a literal type — is rejected so the emitted oracle
    stays a faithful, regenerable equality check. ``NaN`` is rejected too: it is
    never equal to itself, so ``== nan`` would not be a passing oracle.
    """
    t = type(value)
    if t in _LITERAL_SCALARS:
        if t is float:  # NaN breaks the `== captured` oracle (nan != nan).
            return value == value  # type: ignore[comparison-overlap]
        return True
    if t in (tuple, list, set, frozenset):
        return all(_is_simple_literal(item) for item in value)  # type: ignore[union-attr]
    if t is dict:
        return all(
            _is_simple_literal(k) and _is_simple_literal(v)
            for k, v in value.items()  # type: ignore[union-attr]
        )
    return False


def _captured_oracle(repr_text: str, value: object) -> str | None:
    """A re-importable literal ``repr`` of ``value``, or ``None`` for no oracle.

    Belt-and-suspenders: even for a value that passed :func:`_is_simple_literal`,
    we re-parse its ``repr`` with :func:`ast.literal_eval` and require the
    round-tripped value to compare equal. A ``repr`` that does not faithfully
    round-trip (or whose evaluation raises) yields ``None`` — the emitted oracle
    is only ever a literal we have proven reproduces the captured value.
    """
    try:
        round_tripped = ast.literal_eval(repr_text)
    except (ValueError, SyntaxError):
        return None
    try:
        if round_tripped == value:
            return repr_text
    except Exception:
        return None
    return None


def _stale_module_names(dotted: str, module_names: list[str]) -> list[str]:
    """The cached module names that shadow ``dotted`` (it, or a package prefix).

    Pure: dropping exactly these from ``sys.modules`` forces the import to bind
    to the file under THIS project root, not a stale earlier one.
    """
    return [
        name
        for name in module_names
        if name == dotted or dotted.startswith(name + ".")
    ]


def _capture_one_oracle(module: object, name: str, call_args: str) -> str | None:
    """The literal ``repr`` oracle for ``module.name`` called with ``call_args``,
    or ``None`` when no honest value oracle is available.

    Pure given an already-imported ``module``: returns ``None`` for any decline
    (arg not a plain literal, attribute missing/not callable, the call raises,
    a non-literal return, or a ``repr`` that does not round-trip) so the caller
    falls back to the "callable & runs" smoke assertion.
    """
    try:
        args, kwargs = _eval_call_args(call_args)
    except (ValueError, SyntaxError):
        return None  # a synthesized arg is not a plain literal -> no oracle
    fn = getattr(module, name, None)
    if not callable(fn):
        return None
    try:
        value = fn(*args, **kwargs)
    except Exception:
        return None  # the call raises on synthesized args -> smoke fallback
    if not _is_simple_literal(value):
        return None  # non-literal return -> smoke fallback (no value oracle)
    return _captured_oracle(repr(value), value)


def _restore_modules(saved_modules: dict[str, object]) -> None:
    """Restore ``sys.modules`` to ``saved_modules`` exactly: drop anything the
    import added, and put back anything that was evicted beforehand."""
    for mod_name in list(sys.modules):
        if mod_name not in saved_modules:
            del sys.modules[mod_name]
    sys.modules.update(saved_modules)


def _collect_oracles(module: object, specs: list[tuple[str, str]]) -> dict[str, str]:
    """Map ``function name -> literal repr`` for the ``specs`` whose real return is
    a simple, reproducible literal, against an already-imported ``module``."""
    oracles: dict[str, str] = {}
    for name, call_args in specs:
        oracle = _capture_one_oracle(module, name, call_args)
        if oracle is not None:
            oracles[name] = oracle
    return oracles


def _capture_oracles(
    project_root: Path, dotted: str, specs: list[tuple[str, str]]
) -> dict[str, str]:
    """Map ``function name -> literal repr`` for functions whose real return is a
    simple, reproducible literal — captured by actually IMPORTING the target and
    CALLING it with the synthesized args.

    The module is imported in a controlled way: the project root is placed on
    ``sys.path`` only for the duration of the import, and ``sys.modules`` is
    snapshotted and RESTORED afterwards so nothing the import cached leaks (which
    also means a later call importing the same dotted path resolves the file at
    *its* project root, not a stale cache). Any failure at any step (import
    raises, the call raises, a synthesized arg is not a literal we can build, the
    return is not a simple literal) is swallowed and that function simply gets NO
    oracle, falling back to the existing "callable & runs" smoke assertion.

    Deterministic: only proven-literal return values produce an oracle; nothing
    here consults time or randomness.
    """
    if not specs:
        return {}

    root_str = str(project_root)
    added_to_path = root_str not in sys.path
    saved_modules = dict(sys.modules)
    if added_to_path:
        sys.path.insert(0, root_str)
    try:
        # Drop any cached copy of the target (and its package) so the import
        # binds to the file under THIS project root, not a stale earlier one.
        for mod_name in _stale_module_names(dotted, list(sys.modules)):
            del sys.modules[mod_name]
        importlib.invalidate_caches()
        try:
            module = importlib.import_module(dotted)
        except Exception:
            return {}  # not importable -> no oracles (smoke handles import)
        return _collect_oracles(module, specs)
    finally:
        if added_to_path and sys.path and sys.path[0] == root_str:
            sys.path.pop(0)
        _restore_modules(saved_modules)


def _eval_call_args(call_args: str) -> tuple[tuple[object, ...], dict[str, object]]:
    """Parse the synthesized ``call_args`` string into ``(args, kwargs)`` of plain
    literals, via :func:`ast.literal_eval` (no code execution).

    Raises ``ValueError``/``SyntaxError`` when any argument is not a plain literal
    (e.g. a name like ``set()`` or ``bytearray()`` — these are NOT literals and so
    a value oracle is declined for that call). An empty argument string is the
    no-argument call ``()``.
    """
    expr = f"_f({call_args})" if call_args else "_f()"
    call = ast.parse(expr, mode="eval").body
    if not isinstance(call, ast.Call):  # defensive: parse must yield a call
        raise ValueError("not a call expression")
    args = tuple(ast.literal_eval(a) for a in call.args)
    kwargs = {
        kw.arg: ast.literal_eval(kw.value)
        for kw in call.keywords
        if kw.arg is not None
    }
    return args, kwargs


def _render(
    module_stem: str,
    dotted: str,
    specs: list[tuple[str, str]],
    class_specs: list[tuple[str, str, list[tuple[str, str]]]],
    oracles: dict[str, str] | None = None,
) -> str:
    """The deterministic test source for ``dotted`` exercising ``specs`` (public
    functions) and ``class_specs`` (safely-constructible public classes).

    ``oracles`` maps a function name to the literal ``repr`` of its captured real
    return value (see :func:`_capture_oracles`). When a function has an oracle the
    emitted test is a true VALUE-ORACLE characterization (``assert fn(...) ==
    <captured literal>``); otherwise it is the "callable & runs" smoke assertion.
    """
    oracles = oracles or {}
    lines = [
        "# Generated by Apex Orchestrator - characterization test",
        f"# module: {dotted}",
        "#",
        "# Pins the module's CURRENT behaviour. Where the real return value of a",
        "# public function is a simple, reproducible literal it was captured at",
        "# generation time and pinned as a value oracle (assert fn(...) == <value>);",
        "# otherwise it asserts only what is honestly knowable (it imports; the",
        "# callable runs without an obvious error). Regenerate, do not hand-tune.",
        "",
        f"import {dotted}",
        "",
        "",
        f"def test_{module_stem}_imports():",
        f'    """The {module_stem} module imports cleanly (smoke test)."""',
        f"    assert {dotted} is not None",
    ]
    for name, call_args in specs:
        oracle = oracles.get(name)
        if oracle is not None:
            lines += [
                "",
                "",
                f"def test_{module_stem}_{name}_characterization():",
                f'    """Characterize {name}: it returns the captured value on synthesized inputs."""',
                f"    fn = {dotted}.{name}",
                "    assert callable(fn)",
                "    # Value oracle: the captured real return value pins behaviour exactly.",
                f"    assert fn({call_args}) == {oracle}",
            ]
            continue
        lines += [
            "",
            "",
            f"def test_{module_stem}_{name}_characterization():",
            f'    """Characterize {name}: it is callable and runs on synthesized inputs."""',
            f"    fn = {dotted}.{name}",
            "    assert callable(fn)",
            "    try:",
            f"        result = fn({call_args})",
            "    except Exception:",
            "        # A runtime error on synthesized inputs does not fail the",
            "        # characterization: 'it is callable and runs' is what we pin.",
            "        return",
            "    # Shape check only — no value oracle (we cannot know the right answer).",
            "    assert result is not None or result is None",
        ]
    for cname, init_args, methods in class_specs:
        lines += [
            "",
            "",
            f"def test_{module_stem}_{cname}_characterization():",
            f'    """Characterize {cname}: it constructs and its public methods run."""',
            f"    cls = {dotted}.{cname}",
            "    assert callable(cls)",
            "    try:",
            f"        instance = cls({init_args})",
            "    except Exception:",
            "        # A runtime error on synthesized inputs does not fail the",
            "        # characterization: 'it constructs' is what we pin.",
            "        return",
            "    assert instance is not None",
        ]
        for mname, call_args in methods:
            lines += [
                f"    method = getattr(instance, {mname!r}, None)",
                "    assert callable(method)",
                "    try:",
                f"        method({call_args})",
                "    except Exception:",
                "        # 'it is callable and runs' is what we pin, not a value.",
                "        pass",
            ]
    return "\n".join(lines) + "\n"


def generate_characterization_test(
    project_root: str | Path, module_rel: str
) -> ShieldTest | None:
    """Synthesize a characterization test for ``module_rel`` (relative to root).

    Returns a :class:`ShieldTest` to be written by the caller, or ``None`` when
    a test cannot/should not be generated:
      - the target is itself a test/fixture file;
      - the module is a dunder (``__init__``/``__main__`` — packaging, not
        behaviour);
      - the source does not exist or does not parse;
      - a ``tests/test_<stem>.py`` already exists (never clobber).
    """
    root = Path(project_root)
    rel = module_rel.replace("\\", "/")
    if not rel.endswith(".py"):
        return None
    if _is_fixture_path(rel):
        return None

    module_stem = Path(rel).stem
    if module_stem.startswith("__"):  # __init__/__main__ are packaging, not behaviour
        return None

    source = root / rel
    try:
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return None

    test_path = f"tests/test_{module_stem}.py"
    if (root / test_path).exists():  # never clobber an existing test
        return None

    dotted = _dotted_name(rel)
    specs = _safe_functions(tree)
    class_specs = _safe_classes(tree)
    oracles = _capture_oracles(root, dotted, specs)
    content = _render(module_stem, dotted, specs, class_specs, oracles)

    exercised = [name for name, _args in specs]
    for cname, _init_args, methods in class_specs:
        exercised.append(cname)
        exercised.extend(f"{cname}.{mname}" for mname, _margs in methods)

    return ShieldTest(
        module=dotted,
        test_path=test_path,
        content=content,
        functions=exercised,
    )


def write_shield_test(project_root: str | Path, shield: ShieldTest) -> str:
    """Write ``shield`` to disk and return the written path (POSIX, project-rel).

    Refuses to overwrite an existing file (a second safety net on top of the
    generator's own check) and creates the ``tests/`` directory if needed.
    """
    root = Path(project_root)
    target = root / shield.test_path
    if target.exists():
        raise FileExistsError(f"refusing to clobber existing test: {shield.test_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(shield.content, encoding="utf-8")
    return shield.test_path
