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

Beyond pinning CURRENT behaviour, the generator also mines DOCUMENTED-correct
behaviour out of docstrings: it parses doctest-style ``>>> expr`` / expected
pairs with the stdlib :mod:`doctest` parser (deterministic, offline, zero-token)
and emits REAL assertions of the documented answer — ``assert repr(expr) ==
<want>`` for a value example, ``pytest.raises(<Type>)`` for a documented
exception. Honesty is preserved by RUNNING each mined example against the real
code at generation time: an example the current code already satisfies becomes a
normal passing assertion (a real correctness pin, not just a current-behaviour
pin); an example the code does NOT satisfy (a real bug or an unfinished stub)
becomes an honest ``@pytest.mark.xfail(strict=True)`` so the suite stays green
AND the discrepancy is surfaced — never hidden, never falsely green, never
silently dropped.

The generator only PROPOSES a :class:`ShieldTest`; the caller decides to write
it (``write_shield_test``). An existing ``tests/test_<stem>.py`` is never
clobbered (the generator returns ``None``). Deterministic, stdlib-only: stable
document order, no time/random.
"""

from __future__ import annotations

import ast
import doctest
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Reuse — never re-implement — the sibling seed-fragility predicate. A doctest
# ``want`` that is a ``set``/``dict`` repr re-renders in a DIFFERENT order under
# another ``PYTHONHASHSEED``; a landed ``assert repr(expr) == <want>`` over it is
# green here but RED on another run — a future-red fake-green. ``pin_doctest``
# already refuses this exact shape; we share its one predicate (no duplicate
# block) so the two doctest paths guard identically. Import is a leaf-level
# predicate with no cycle back into this module.
from app.execution.objectives.pin_doctest import _want_is_unordered_repr


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


def _canonical_set_repr(value: object) -> str:
    """A deterministic source literal for a ``set`` — order-stable, never seed-

    dependent. The empty set MUST render as ``set()`` (because ``{}`` is a dict),
    and non-empty sets render their elements sorted by their OWN canonical repr,
    a total string order that is robust to mixed / unorderable element types.
    """
    if not value:  # type: ignore[truthy-bool]
        return "set()"
    rendered = sorted(_canonical_repr(item) for item in value)  # type: ignore[union-attr]
    return "{" + ", ".join(rendered) + "}"


def _canonical_dict_repr(value: object) -> str:
    """A deterministic source literal for a ``dict`` — keys sorted by their OWN
    canonical repr, never seed-dependent.

    A dict whose KEY ORDER comes from set iteration (e.g. ``{k: f(k) for k in
    a_set}``) has a ``PYTHONHASHSEED``-dependent key order, so emitting that order
    verbatim into LANDED test code makes two CI runs land different git diffs.
    Dict EQUALITY ignores order, so sorting the rendered pairs by canonical key
    repr (a total string order, robust to mixed/unorderable key types — exactly
    how sets are already handled) makes the landed BYTES deterministic with NO
    change to the assertion's validity (``fn() == {...}`` still holds, dict eq is
    order-insensitive). The empty dict renders ``{}``.
    """
    pairs = sorted(
        (_canonical_repr(k), _canonical_repr(v))
        for k, v in value.items()  # type: ignore[union-attr]
    )
    return "{" + ", ".join(f"{k}: {v}" for k, v in pairs) + "}"


def _canonical_repr(value: object) -> str:
    """A DETERMINISTIC, order-stable source literal for ``value``.

    ``repr`` of a ``set`` of strings — or of a ``dict`` whose key order comes from
    set iteration — is ``PYTHONHASHSEED``-dependent (str hashing is randomized),
    so emitting it into LANDED test code makes two CI runs land different git diffs
    for the same project. This renders every order-INSENSITIVE container with a
    deterministic element order — sets AND dicts sorted by canonical element/key
    repr (dict equality ignores order, so sorting its rendered pairs changes only
    the bytes, never the value) — while ``list``/``tuple`` preserve their order
    (it is order-SENSITIVE: sorting it would change the value, so the value-capture
    site instead DECLINES a list/tuple whose order is not reproducible across hash
    seeds). Recurses so nested sets/dicts are canonicalized too. Scalars and
    anything we do not specially handle delegate to ``repr`` (already deterministic).
    """
    t = type(value)
    if t in _LITERAL_SCALARS:
        return repr(value)
    if t is list:
        return "[" + ", ".join(_canonical_repr(v) for v in value) + "]"  # type: ignore[union-attr]
    if t is tuple:
        items = list(value)  # type: ignore[arg-type]
        if len(items) == 1:
            return "(" + _canonical_repr(items[0]) + ",)"
        return "(" + ", ".join(_canonical_repr(v) for v in items) + ")"
    if t is dict:
        return _canonical_dict_repr(value)
    if t is set:
        return _canonical_set_repr(value)
    return repr(value)


def _is_fragile_float(value: float) -> bool:
    """``True`` when ``value`` is a float whose decimal repr betrays floating-point
    IMPRECISION — an arithmetic result like ``0.1 + 0.2`` (``0.30000000000000004``)
    or ``1 / 3`` (``0.3333333333333333``) — so pinning its full-precision literal is
    a portability/run hazard.

    A float is honest to PIN only when it has a SHORT exact decimal form: rounding it
    to 12 significant figures must not change its value. ``0.1 + 0.2`` rounds to
    ``0.3`` (a different double) -> fragile; a clean ``42.0`` / ``2.5`` / ``0.1``
    round-trips unchanged -> fine. ``NaN``/``inf`` (already rejected upstream by
    :func:`_is_simple_literal`) are treated as fragile defensively. Deterministic:
    pure arithmetic on the value, no environment read."""
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return True
    return float(f"{value:.12g}") != value


def _contains_fragile_float(value: object) -> bool:
    """``True`` when ``value`` IS, or (recursively) CONTAINS, a fragile float
    (:func:`_is_fragile_float`).

    Recurses through list/tuple/set/frozenset members and dict keys+values so a
    float hidden inside a container (``[0.1 + 0.2]``, ``{"x": 1 / 3}``) is caught
    too. ``bool`` is a subclass of ``int``, never ``float``, so it is unaffected.
    Pure and deterministic."""
    t = type(value)
    if t is float:
        return _is_fragile_float(value)  # type: ignore[arg-type]
    if t in (list, tuple, set, frozenset):
        return any(_contains_fragile_float(item) for item in value)  # type: ignore[union-attr]
    if t is dict:
        return any(
            _contains_fragile_float(k) or _contains_fragile_float(v)
            for k, v in value.items()  # type: ignore[union-attr]
        )
    return False


def _captured_oracle(repr_text: str, value: object) -> str | None:
    """A re-importable, DETERMINISTIC source literal of ``value``, or ``None``.

    Belt-and-suspenders: even for a value that passed :func:`_is_simple_literal`,
    we re-parse its ``repr`` with :func:`ast.literal_eval` and require the
    round-tripped value to compare equal — this rejects a ``frozenset`` (whose
    ``repr`` ``ast.literal_eval`` refuses) and any non-round-tripping ``repr``,
    preserving today's decline behaviour. We then EMIT :func:`_canonical_repr`,
    re-validated the same way, so the landed literal is byte-stable across hash
    seeds; if canonical rendering ever fails to round-trip equal we return
    ``None`` (smoke fallback) — never a wrong oracle.

    A value carrying a FRAGILE float (:func:`_contains_fragile_float` — e.g.
    ``0.1 + 0.2``'s ``0.30000000000000004``) is declined here too: its
    full-precision literal is a portability/run hazard, so the call falls back to the
    honest smoke assertion rather than pinning an imprecise float.
    """
    try:
        round_tripped = ast.literal_eval(repr_text)
    except (ValueError, SyntaxError, RecursionError, MemoryError):
        return None
    try:
        if round_tripped != value:
            return None
    except Exception:
        return None
    if _contains_fragile_float(value):
        return None  # imprecise float -> portability/run hazard, never pin it
    canon = _canonical_repr(value)
    try:
        if ast.literal_eval(canon) == value:
            return canon
    except (ValueError, SyntaxError, RecursionError, MemoryError):
        return None
    except Exception:
        return None
    return None


def _contains_list_or_tuple(value: object) -> bool:
    """``True`` when ``value`` IS, or (recursively) CONTAINS, a ``list``/``tuple``.

    Only these two containers have an ORDER that is both semantically meaningful
    (list/tuple equality is order-SENSITIVE) AND potentially set-iteration-derived
    at runtime — so only they need the cross-hash-seed re-capture check. A plain
    scalar, a ``set`` (rendered sorted), or a ``dict`` (rendered with sorted keys)
    is byte-stable already and needs NO subprocess round-trip. We recurse through
    set/dict members too: a ``set`` whose elements are tuples, or a ``dict`` whose
    values are lists, still hides an order-sensitive sub-value.
    """
    t = type(value)
    if t in (list, tuple):
        return True
    if t in (set, frozenset):
        return any(_contains_list_or_tuple(item) for item in value)  # type: ignore[union-attr]
    if t is dict:
        return any(
            _contains_list_or_tuple(k) or _contains_list_or_tuple(v)
            for k, v in value.items()  # type: ignore[union-attr]
        )
    return False


# Fixed hash seeds for the re-capture children. We re-capture under SEVERAL
# distinct, pinned seeds and demand the canonical literal match the parent's under
# EVERY one. Two reasons it must be a set, not a single seed: (1) the parent's own
# seed is arbitrary (often unset -> random), so a single child seed could COINCIDE
# with it and let a set-iteration-order value slip through on that one run; (2)
# different seeds reshuffle set iteration differently, so a genuinely order-stable
# value matches them ALL while a set-order list almost surely diverges on at least
# one. Pinning the seeds keeps the CHECK itself deterministic (same children every
# run); using more than one closes the parent-seed coincidence hole.
_RECAPTURE_HASHSEEDS = ("1", "2", "424242")

# The repo root that owns THIS module (three levels above app/execution/…) —
# passed to every probe child as argv so the child can import the shield helpers
# WITHOUT depending on the ambient environment (``PYTHONPATH``, a pip install).
# A soundness gate whose child could only import its own helpers when the shell
# happened to export the right path was silently environment-dependent — the
# exact opposite of the determinism it exists to prove.
_SHIELD_ROOT = Path(__file__).resolve().parents[2]

# Shared probe preamble: bind the shield helpers from ``shield_root`` FIRST, then
# hand the import system back to the TARGET project. The two roots may both own a
# top-level ``app`` package (``app`` is a very common real-world project package
# name — and the shield's own package IS ``app``), so the child must never let one
# shadow the other: the helpers are imported with ``shield_root`` at the front of
# ``sys.path``, their function objects keep their globals alive independently of
# the module cache, and then every cached ``app*`` module AND ``shield_root``
# itself are dropped so ``importlib.import_module(dotted)`` resolves the target's
# OWN packages afresh under ``root``. (When the target IS the shield's repo the
# purge just forces a clean re-import of the same files.) Without this, a target
# project named ``app`` made every probe fail its helper import — and every value
# oracle silently DECLINE — an honest but needless capability loss.
_PROBE_PREAMBLE = r"""
import ast, json, sys
root, dotted, name, call_args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
shield_root = sys.argv[5]
sys.path.insert(0, shield_root)
from app.execution.test_shield import _canonical_repr, _eval_call_args, _is_simple_literal
for _cached in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
    del sys.modules[_cached]
while shield_root in sys.path:
    sys.path.remove(shield_root)
sys.path.insert(0, root)
"""

# The probe: import the target under ``root`` on ``sys.path``, call the function
# with the SAME literal args, and print the CANONICAL literal of its return value
# (via the project's own ``_canonical_repr``, so the comparison is byte-for-byte
# the same rendering the parent emits). argv: root, dotted, name, call_args text,
# shield_root (the repo that owns the shield helpers — see ``_PROBE_PREAMBLE``).
_RECAPTURE_PROBE = _PROBE_PREAMBLE + r"""
try:
    import importlib
    mod = importlib.import_module(dotted)
    fn = getattr(mod, name, None)
    if not callable(fn):
        print(json.dumps({"ok": False}))
        sys.exit(0)
    args, kwargs = _eval_call_args(call_args)
    value = fn(*args, **kwargs)
    if not _is_simple_literal(value):
        print(json.dumps({"ok": False}))
        sys.exit(0)
    print(json.dumps({"ok": True, "canon": _canonical_repr(value)}))
except BaseException:  # noqa: BLE001 - any failure -> decline (no oracle)
    print(json.dumps({"ok": False}))
    sys.exit(0)
"""

# The TIME probe: capture the canonical literal TWICE in one fresh interpreter,
# separated by a real ``> 1s`` sleep, and report whether the two captures are
# byte-identical. A value that reads the wall clock (``int(time.time())``,
# ``time.time()``, ``datetime.now()`` ...) advances across the gap and the two
# captures DIFFER, so the caller declines it; a stable value is identical on both
# captures. The ``> 1s`` gap makes an ``int(time.time())`` floor advance by at
# least one DETERMINISTICALLY (the check always declines a clock value and always
# accepts a stable one), so the gate stays deterministic. argv as the main probe.
_TIME_PROBE = _PROBE_PREAMBLE + r"""
import time
try:
    import importlib
    mod = importlib.import_module(dotted)
    fn = getattr(mod, name, None)
    if not callable(fn):
        print(json.dumps({"ok": False}))
        sys.exit(0)
    args, kwargs = _eval_call_args(call_args)
    first = fn(*args, **kwargs)
    if not _is_simple_literal(first):
        print(json.dumps({"ok": False}))
        sys.exit(0)
    canon_first = _canonical_repr(first)
    time.sleep(1.1)
    second = fn(*args, **kwargs)
    if not _is_simple_literal(second):
        print(json.dumps({"ok": False}))
        sys.exit(0)
    stable = canon_first == _canonical_repr(second)
    print(json.dumps({"ok": True, "stable": stable, "canon": canon_first}))
except BaseException:  # noqa: BLE001 - any failure -> decline (no oracle)
    print(json.dumps({"ok": False}))
    sys.exit(0)
"""


def _run_recapture_probe(
    project_root: Path, dotted: str, name: str, call_args: str,
    env_overrides: dict[str, str], cwd: str | None,
) -> str | None:
    """Re-capture ``dotted.name(call_args)``'s canonical literal in a CLEAN
    subprocess under the given ``env_overrides`` (layered on the parent env) and
    working directory ``cwd``, or ``None`` on ANY failure.

    The single subprocess primitive shared by the hash-seed gate and the env-axis
    gate: a fresh interpreter (bytecode off, project root on ``sys.path`` and
    ``PYTHONPATH``) re-runs the exact same call and renders the result through the
    project's own :func:`_canonical_repr`. ``cwd``/``HOME``/``TZ``/``TMPDIR``/
    ``PYTHONHASHSEED`` are whatever the caller's overrides set, so a value that
    reads any of those (``os.getcwd()``, ``expanduser('~')``, a hash-seed-derived
    order, ...) re-renders DIFFERENT bytes here. Any subprocess error/crash/
    timeout, or a child that itself declines, yields ``None`` (the caller then
    declines too — never an unverified oracle)."""
    env = {
        **os.environ,
        **env_overrides,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(project_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RECAPTURE_PROBE,
             str(project_root), dotted, name, call_args, str(_SHIELD_ROOT)],
            cwd=cwd if cwd is not None else str(project_root),
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
    canon = result.get("canon")
    return canon if isinstance(canon, str) else None


def _recapture_canonical(
    project_root: Path, dotted: str, name: str, call_args: str, hashseed: str
) -> str | None:
    """The canonical literal of ``dotted.name(call_args)`` re-captured in a CLEAN
    subprocess under the fixed ``PYTHONHASHSEED`` ``hashseed``, or ``None`` on any
    failure.

    A fresh interpreter (bytecode off, project root on ``sys.path``, seed pinned to
    ``hashseed``) re-runs the exact same call and renders the result through the
    project's own :func:`_canonical_repr`. Under a hash seed that differs from the
    parent's, a list/tuple whose order came from set iteration renders DIFFERENT
    bytes here — which the caller uses to DECLINE the oracle. Any subprocess
    error/crash/timeout, or a child that itself declines, yields ``None`` (the
    caller then declines too — never an unverified oracle).
    """
    return _run_recapture_probe(
        project_root, dotted, name, call_args, {"PYTHONHASHSEED": hashseed}, None)


def _order_is_reproducible(
    project_root: Path, dotted: str, name: str, call_args: str,
    value: object, in_process_canon: str,
) -> bool:
    """Is ``value``'s order reproducible across hash seeds? (the honest gate).

    For a value with NO list/tuple anywhere the answer is trivially ``True`` (sets
    and dicts are rendered sorted, so the bytes are already seed-stable — no child
    needed). When the value DOES contain a list/tuple, we re-capture the producing
    call in subprocesses under SEVERAL distinct fixed ``PYTHONHASHSEED`` values
    (:data:`_RECAPTURE_HASHSEEDS`) and require the child's canonical literal to be
    BYTE-IDENTICAL to the parent's under EVERY one: a deterministically-ordered
    list (``[1, 2, 3]``, ``sorted(s)``, ``list(range(n))``) re-renders identically
    under all seeds and PASSES; a set-iteration-order list re-renders in a
    different order under at least one seed and FAILS, so the oracle is declined.
    Using several seeds (not one) closes the hole where the parent's own seed
    coincides with a single child seed. A subprocess that fails or declines makes
    this ``False`` — we never emit an unverified value oracle. Deterministic: the
    seeds are pinned, so the children render the same bytes every run.
    """
    if not _contains_list_or_tuple(value):
        return True  # no order-sensitive sub-value -> already byte-stable
    for hashseed in _RECAPTURE_HASHSEEDS:
        child_canon = _recapture_canonical(
            project_root, dotted, name, call_args, hashseed)
        if child_canon is None or child_canon != in_process_canon:
            return False
    return True


# Distinct, fixed values for each environment axis a captured value might read.
# Used to build TWO independent variation environments below: a value that reads
# ANY of these axes (cwd via ``os.getcwd()``; ``$HOME`` via ``expanduser('~')``;
# ``$TZ``; ``$TMPDIR``; ``PYTHONHASHSEED`` via a set/dict-derived order) renders
# different bytes under at least one variation. The values are pinned literals so
# the env-axis gate is itself DETERMINISTIC (same variations every run). The cwd
# and dir-valued axes are filled with REAL temp directories at call time (a
# non-existent cwd would make every child fail and spuriously decline).
_ENV_VARIATION_SEEDS = (
    {"name": "alpha", "TZ": "America/New_York", "PYTHONHASHSEED": "1"},
    {"name": "beta", "TZ": "Asia/Tokyo", "PYTHONHASHSEED": "424242"},
)


def _env_recapture_matches(
    project_root: Path, dotted: str, name: str, call_args: str,
    in_process_canon: str, stack,
) -> bool:
    """Re-capture under each environment variation; ``True`` iff EVERY variation
    re-renders byte-identically to ``in_process_canon``.

    For each spec in :data:`_ENV_VARIATION_SEEDS` a fresh temp cwd, ``$HOME`` and
    ``$TMPDIR`` are created (registered on the caller's ``ExitStack`` ``stack`` so
    they are cleaned up) and the producing call is re-run there with that spec's
    distinct ``$TZ``/``PYTHONHASHSEED``. A value that reads cwd/HOME/TMPDIR/TZ or a
    hash-seed-derived order diverges under at least one variation and yields
    ``False``; a child that fails/declines also yields ``False`` (refuse, never an
    unverified oracle)."""
    for spec in _ENV_VARIATION_SEEDS:
        base = stack.enter_context(tempfile.TemporaryDirectory(prefix="apex_env_"))
        var_cwd = os.path.join(base, "cwd")
        var_home = os.path.join(base, "home")
        var_tmp = os.path.join(base, "tmp")
        for d in (var_cwd, var_home, var_tmp):
            os.makedirs(d, exist_ok=True)
        overrides = {
            "HOME": var_home, "TMPDIR": var_tmp, "TEMP": var_tmp, "TMP": var_tmp,
            "TZ": spec["TZ"], "PYTHONHASHSEED": spec["PYTHONHASHSEED"],
        }
        child_canon = _run_recapture_probe(
            project_root, dotted, name, call_args, overrides, var_cwd)
        if child_canon is None or child_canon != in_process_canon:
            return False
    return True


def _time_recapture_is_stable(
    project_root: Path, dotted: str, name: str, call_args: str,
    in_process_canon: str,
) -> bool:
    """``True`` iff the value is stable across a wall-clock gap (the time axis).

    Runs :data:`_TIME_PROBE`: one child captures the canonical literal twice,
    separated by a ``> 1s`` sleep. A value that reads the clock (``int(time.time())``
    ...) advances and the two captures differ -> ``False``; we ALSO require the
    child's first capture to match ``in_process_canon`` so a value that already
    diverged from the parent is refused. A child that fails/declines -> ``False``."""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(project_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _TIME_PROBE,
             str(project_root), dotted, name, call_args, str(_SHIELD_ROOT)],
            cwd=str(project_root), capture_output=True, text=True,
            env=env, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    if not result.get("ok") or not result.get("stable"):
        return False
    return result.get("canon") == in_process_canon


def _env_is_reproducible(
    project_root: Path, dotted: str, name: str, call_args: str,
    in_process_canon: str,
) -> bool:
    """The multi-AXIS environment-reproducibility gate (the honest env gate).

    A captured value is honest to PIN only if re-running the producing call under a
    VARIED environment re-renders the SAME canonical literal. We re-capture in clean
    subprocesses under distinct cwd / ``$HOME`` / ``$TZ`` / ``$TMPDIR`` /
    ``PYTHONHASHSEED`` variations (:func:`_env_recapture_matches`) AND across a
    wall-clock gap (:func:`_time_recapture_is_stable`), accepting the value ONLY when
    it is byte-identical (``_canonical_repr``) across ALL of them. This applies to
    SCALARS too (no early-return for non-list/tuple): a function returning
    ``os.getcwd()``, ``tempfile.mkdtemp()``, ``int(time.time())``, ``expanduser('~')``
    or a float like ``0.1 + 0.2`` (whose env-stable repr is still re-checked) is
    REFUSED unless it survives every axis. Conservative by construction: any child
    that fails/declines makes this ``False`` — over-refusal is safe, a future-red
    pinned test is not. Deterministic: the variation values are pinned, so the same
    input yields the same decision every run."""
    import contextlib

    with contextlib.ExitStack() as stack:
        if not _env_recapture_matches(
                project_root, dotted, name, call_args, in_process_canon, stack):
            return False
    return _time_recapture_is_stable(
        project_root, dotted, name, call_args, in_process_canon)


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


def _capture_one_oracle(
    module: object, name: str, call_args: str,
    project_root: Path | None = None, dotted: str | None = None,
) -> str | None:
    """The literal ``repr`` oracle for ``module.name`` called with ``call_args``,
    or ``None`` when no honest value oracle is available.

    Pure given an already-imported ``module``: returns ``None`` for any decline
    (arg not a plain literal, attribute missing/not callable, the call raises,
    a non-literal return, or a ``repr`` that does not round-trip) so the caller
    falls back to the "callable & runs" smoke assertion.

    When ``project_root``/``dotted`` are supplied the producing call is re-captured
    in clean subprocesses under VARIED environments — distinct cwd / ``$HOME`` /
    ``$TZ`` / ``$TMPDIR`` / ``PYTHONHASHSEED`` and a wall-clock gap
    (:func:`_env_is_reproducible`) — and the oracle is DECLINED unless the
    re-rendered canonical literal is byte-identical under EVERY variation. This
    catches a value that reads the environment or clock (``os.getcwd()``,
    ``tempfile.mkdtemp()``, ``int(time.time())``, ``expanduser('~')`` ...) AND a
    list/tuple whose order came from set iteration — none of which is honest to PIN
    — while a genuinely stable value still lands its oracle. The list/tuple-specific
    multi-seed order gate (:func:`_order_is_reproducible`) is ALSO applied for the
    extra seed coverage it adds on order-sensitive values.
    """
    try:
        args, kwargs = _eval_call_args(call_args)
    except (ValueError, SyntaxError, RecursionError, MemoryError):
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
    oracle = _captured_oracle(repr(value), value)
    if oracle is None:
        return None
    if project_root is not None and dotted is not None:
        # ENV-axis gate (applies to SCALARS too): decline any value that varies
        # with cwd/HOME/TZ/TMPDIR/hash-seed/clock — it would be green here and RED
        # on another machine or run.
        if not _env_is_reproducible(
            project_root, dotted, name, call_args, oracle
        ):
            return None
        # ORDER-sensitivity gate: a list/tuple whose order is set-iteration-derived
        # is genuinely flaky (can't be sorted — that would change the value), so
        # decline unless several different-hash-seed subprocesses re-render
        # byte-identically (extra seed coverage on top of the env gate).
        if not _order_is_reproducible(
            project_root, dotted, name, call_args, value, oracle
        ):
            return None
    return oracle


def _restore_modules(saved_modules: dict[str, object]) -> None:
    """Restore ``sys.modules`` to ``saved_modules`` exactly: drop anything the
    import added, and put back anything that was evicted beforehand."""
    for mod_name in list(sys.modules):
        if mod_name not in saved_modules:
            del sys.modules[mod_name]
    sys.modules.update(saved_modules)


def _collect_oracles(
    module: object, specs: list[tuple[str, str]],
    project_root: Path | None = None, dotted: str | None = None,
) -> dict[str, str]:
    """Map ``function name -> literal repr`` for the ``specs`` whose real return is
    a simple, reproducible literal, against an already-imported ``module``.

    ``project_root``/``dotted`` (when supplied) enable the cross-hash-seed
    re-capture that DECLINES a value whose list/tuple order is not reproducible.
    """
    oracles: dict[str, str] = {}
    for name, call_args in specs:
        oracle = _capture_one_oracle(module, name, call_args, project_root, dotted)
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
    here consults time or randomness. A value whose order is set-iteration-derived
    (a ``list``/``tuple`` whose element order depends on ``PYTHONHASHSEED``) is
    DECLINED here too — its producing call is re-captured in a subprocess under a
    different fixed seed and the oracle is kept only if the canonical literal is
    byte-identical, so Apex never lands a hash-seed-flaky value oracle.
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
        return _collect_oracles(module, specs, project_root, dotted)
    finally:
        if added_to_path and sys.path and sys.path[0] == root_str:
            sys.path.pop(0)
        _restore_modules(saved_modules)


# --- doctest mining ---------------------------------------------------------
#
# Beyond the current-behaviour value oracles above, Apex also mines the
# DOCUMENTED-correct behaviour straight out of docstrings. A ``>>> expr`` /
# expected-output pair in a docstring is a contract the author wrote down; the
# stdlib ``doctest`` parser turns it into an example deterministically (no LLM,
# offline). For each mined example we emit a REAL assertion of the documented
# answer — but honestly: an example the CURRENT code already satisfies becomes a
# normal passing assertion (a real correctness pin), while an example the code
# does NOT satisfy (the docstring says one thing, the code does another -> a real
# bug or an unfinished stub) becomes an honest ``xfail(strict=True)`` so the
# suite stays green AND the discrepancy is surfaced, never hidden, never falsely
# green, never silently dropped.


@dataclass(frozen=True)
class DocExample:
    """A single mined doctest example and its honest disposition.

    ``source`` is the ``>>> `` expression (exactly one expression, newline
    stripped); ``want`` is the documented expected ``repr`` text (for a value
    example) and ``exc_type`` the documented exception type name (for a raises
    example) -- exactly one of the two is set. ``passes`` records whether the
    CURRENT code already satisfies the example (captured by actually running the
    example against the imported module at generation time): ``True`` -> emit a
    passing assertion, ``False`` -> emit an honest ``xfail``.
    """

    qualname: str
    source: str
    want: str
    exc_type: str
    passes: bool


def _example_is_simple_expr(source: str) -> bool:
    """``True`` when ``source`` is exactly one evaluatable expression.

    We only emit assertions for a single ``>>> expr`` (no assignment, no import,
    no multi-statement block) so the generated ``assert repr(expr) == want`` /
    ``pytest.raises(...)`` is valid Python and faithfully mirrors doctest's own
    comparison. Anything else is declined (no test emitted for that example).
    """
    text = source.strip()
    if not text or "\n" in text:
        return False
    try:
        parsed = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    return isinstance(parsed, ast.Expression)


def _exc_type_name(exc_msg: str) -> str | None:
    """The documented exception TYPE NAME from a doctest ``exc_msg``, or ``None``.

    doctest stores the traceback's final ``Type: message`` line as ``exc_msg``;
    the leading token up to the first ``:`` (or the whole line) is the type. We
    only accept a bare dotted identifier (``ValueError``, ``a.B``) so the emitted
    ``pytest.raises(<name>)`` references a real, importable-in-namespace name.
    """
    head = exc_msg.split(":", 1)[0].strip()
    if not head:
        return None
    if not all(part.isidentifier() for part in head.split(".")):
        return None
    return head


def _want_is_bare_exception(want: str) -> bool:
    """``True`` when ``want`` is a traceback whose final line is a BARE type.

    A doctest exception example with no detail message -- the traceback's last
    line is just ``TypeError`` (not ``TypeError: some message``). doctest's
    strict exception matcher will NOT match such a bare-type ``want`` against a
    real traceback (which always carries the runtime message), so a code path
    that raises EXACTLY the documented type would be mis-scored as failing. We
    detect this shape so it can be re-run under ``IGNORE_EXCEPTION_DETAIL``,
    where doctest matches on the exception TYPE alone (deterministic, offline).
    """
    lines = [ln for ln in want.splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    return ":" not in last and _exc_type_name(last) is not None


def _example_passes(source: str, want: str, ns: dict) -> bool:
    """Run ONE doctest example against namespace ``ns``; ``True`` iff it passes.

    ``want`` is the doctest expected block exactly as parsed (the expected
    ``repr`` for a value example, or the full ``Traceback ...`` block for an
    exception example). Uses the stdlib :class:`doctest.DocTestRunner` so the
    pass/fail decision is exactly doctest's own (deterministic, offline). Output
    is discarded. Any failure to even build/run the example counts as "does not
    pass" (-> honest xfail), never as a false green.

    A bare-type exception ``want`` (``TypeError`` with no ``: message``) is run
    under :data:`doctest.IGNORE_EXCEPTION_DETAIL`, so a code path that raises
    exactly the documented type is honestly scored as PASSING (doctest's strict
    matcher would otherwise reject the message-less form and fake a red).
    """
    optionflags = 0
    if _want_is_bare_exception(want):
        optionflags = doctest.IGNORE_EXCEPTION_DETAIL
    block = f">>> {source}\n{want}"
    try:
        test = doctest.DocTestParser().get_doctest(block, dict(ns), "<mined>", None, 0)
        runner = doctest.DocTestRunner(verbose=False, optionflags=optionflags)
        sink = io.StringIO()
        result = runner.run(test, out=sink.write, clear_globs=True)
    except Exception:
        return False
    return result.attempted >= 1 and result.failed == 0


def _mine_examples_from(qualname: str, docstring: str | None, ns: dict) -> list[DocExample]:
    """All mined :class:`DocExample`s for one ``docstring`` (document order).

    Parses with :class:`doctest.DocTestParser` (deterministic, offline). Keeps
    only single-expression value examples (``>>> expr`` then expected ``repr``)
    and single-expression exception examples (``>>> expr`` then a traceback whose
    final line is a bare exception type). Each kept example is run against ``ns``
    to record its honest disposition (passes on current code or not).
    """
    if not docstring:
        return []
    try:
        raw = doctest.DocTestParser().get_examples(docstring)
    except (ValueError, RecursionError, MemoryError):
        return []
    out: list[DocExample] = []
    for ex in raw:
        source = ex.source.strip()
        if not _example_is_simple_expr(source):
            continue
        if ex.exc_msg is not None:
            exc_type = _exc_type_name(ex.exc_msg)
            if exc_type is None:
                continue
            passes = _example_passes(source, ex.want, ns)
            out.append(DocExample(qualname, source, "", exc_type, passes))
            continue
        want = ex.want.strip()
        if not want or "\n" in want:
            continue  # only single-line value examples get a faithful oracle
        if _want_is_unordered_repr(want):
            continue  # a set/dict-repr want is PYTHONHASHSEED-fragile — never land it
        passes = _example_passes(source, ex.want, ns)
        out.append(DocExample(qualname, source, want, "", passes))
    return out


def _doc_targets(tree: ast.Module) -> list[tuple[str, str | None]]:
    """``(qualname, docstring)`` for the module and every public function/method.

    Document order, deterministic. Includes the module docstring (qualname
    ``"<module>"``), each top-level public function, each public class, and each
    public method of a public class (``Class.method``). Private names (leading
    ``_``, except ``__init__``) are skipped -- their examples are not part of the
    public contract.
    """
    targets: list[tuple[str, str | None]] = [("<module>", ast.get_docstring(tree))]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            targets.append((node.name, ast.get_docstring(node)))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            targets.append((node.name, ast.get_docstring(node)))
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name.startswith("_") and item.name != "__init__":
                    continue
                targets.append((f"{node.name}.{item.name}", ast.get_docstring(item)))
    return targets


def _collect_doc_examples(module: object, tree: ast.Module) -> list[DocExample]:
    """All mined doctest examples for ``tree``, run against the imported ``module``.

    Pure given an already-imported ``module``: the example expressions are
    evaluated in the module's own namespace (so ``factorial(5)`` resolves to the
    module's ``factorial``). Returns examples in document order; empty when the
    module has no minable examples.
    """
    ns = dict(getattr(module, "__dict__", {}))
    examples: list[DocExample] = []
    for qualname, docstring in _doc_targets(tree):
        examples.extend(_mine_examples_from(qualname, docstring, ns))
    return examples


def _capture_doc_examples(
    project_root: Path, dotted: str, tree: ast.Module
) -> list[DocExample]:
    """Mine + honestly disposition every docstring example for ``dotted``.

    Imports the target under a controlled ``sys.path``/``sys.modules`` snapshot
    (identical discipline to :func:`_capture_oracles`) so each mined example can
    be RUN against the real code to decide passing-assertion vs honest-xfail.
    Any failure to import yields no examples (the docstrings still parse, but we
    will not claim a disposition we could not verify). Deterministic.
    """
    root_str = str(project_root)
    saved_modules = dict(sys.modules)
    # Force the target's package chain to bind under THIS root for the duration
    # of the import (insert at position 0 so a stale same-named package cached
    # from another root cannot win), then restore sys.path/sys.modules exactly.
    sys.path.insert(0, root_str)
    try:
        for mod_name in _stale_module_names(dotted, list(sys.modules)):
            del sys.modules[mod_name]
        importlib.invalidate_caches()
        try:
            module = importlib.import_module(dotted)
        except Exception:
            return []
        return _collect_doc_examples(module, tree)
    finally:
        if sys.path and sys.path[0] == root_str:
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


def _doc_test_name(module_stem: str, index: int) -> str:
    """Deterministic, unique test name for the ``index``-th mined doc example."""
    return f"test_{module_stem}_docexample_{index}"


def _render_doc_examples(
    module_stem: str, dotted: str, examples: list[DocExample]
) -> list[str]:
    """Emitted test source lines for the mined docstring examples (document order).

    A passing example (current code already satisfies the documented contract)
    becomes a normal assertion -- a REAL correctness pin of the documented answer.
    An unsatisfied example becomes an ``@pytest.mark.xfail(strict=True)`` test:
    the suite stays green, but the documented-vs-actual discrepancy is surfaced
    honestly (a real bug / unfinished stub), never hidden, never a false green.
    A value example emits ``assert repr(<expr>) == <want>`` (mirroring doctest's
    own comparison); an exception example emits ``pytest.raises(<Type>)``. The
    docstring's own names (``factorial`` ...) are bound via ``from <dotted>
    import *`` so each mined expression resolves exactly as it did in the docstring.
    """
    if not examples:
        return []
    lines: list[str] = [
        "",
        "",
        "import pytest  # noqa: E402",
        f"from {dotted} import *  # noqa: E402,F401,F403",
    ]
    for index, ex in enumerate(examples):
        name = _doc_test_name(module_stem, index)
        if ex.exc_type:
            body = [
                f"    with pytest.raises({ex.exc_type}):",
                f"        {ex.source}",
            ]
            summary = f"{ex.source} raises {ex.exc_type}"
        else:
            body = [f"    assert repr({ex.source}) == {ex.want!r}"]
            summary = f"{ex.source} == {ex.want}"
        if ex.passes:
            lines += [
                "",
                "",
                f"def {name}():",
                f'    """Documented behaviour of {ex.qualname}: {summary} (from its docstring)."""',
                *body,
            ]
        else:
            reason = f"docstring example not yet satisfied: {ex.qualname}: {summary}"
            lines += [
                "",
                "",
                f"@pytest.mark.xfail(strict=True, reason={reason!r})",
                f"def {name}():",
                f'    """Documented-but-unmet behaviour of {ex.qualname}: {summary}.',
                "",
                "    The docstring documents this, but the current code does NOT satisfy",
                "    it (a real bug or an unfinished stub). Marked xfail(strict) so the",
                "    suite stays green AND the discrepancy is surfaced honestly, not hidden.",
                '    """',
                *body,
            ]
    return lines


def _render(
    module_stem: str,
    dotted: str,
    specs: list[tuple[str, str]],
    class_specs: list[tuple[str, str, list[tuple[str, str]]]],
    oracles: dict[str, str] | None = None,
    doc_examples: list[DocExample] | None = None,
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
    lines += _render_doc_examples(module_stem, dotted, doc_examples or [])
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
    except (OSError, SyntaxError, RecursionError, MemoryError):
        return None

    test_path = f"tests/test_{module_stem}.py"
    if (root / test_path).exists():  # never clobber an existing test
        return None

    dotted = _dotted_name(rel)
    specs = _safe_functions(tree)
    class_specs = _safe_classes(tree)
    oracles = _capture_oracles(root, dotted, specs)
    doc_examples = _capture_doc_examples(root, dotted, tree)
    content = _render(module_stem, dotted, specs, class_specs, oracles, doc_examples)

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
