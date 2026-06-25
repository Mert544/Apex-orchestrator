"""Self-registering objective: pin-doctest.

The honest gap this closes: a function carries ``>>>`` examples in its docstring
— a worked contract a reader trusts — yet NOTHING in the suite runs them. The
examples are documentation, not a test: they can silently rot to RED while the
suite stays green. Apex LANDS a real, suite-enforced test that EXECUTES those
examples, turning the documentation into a contract the project's own test run
keeps honest — for free, deterministically, no LLM.

The contribution is a NEW file ``tests/test_<stem>_doctest.py`` (additive — it
never edits the module or the existing suite), one test function per qualifying
SYMBOL — a top-level function, a public class (its docstring), or a public method —
each rebuilding the symbol's ENFORCEABLE examples from the live ``__doc__`` and
asserting the stdlib :mod:`doctest` runner reports zero failures. The examples are
user-authored and already green, so the claim is near-zero over-claim: the test
only restates a contract the code already satisfies. Descent into public class
methods and class docstrings only generalizes NAME RESOLUTION (function ->
``Class`` / ``Class.method``); every symbol clears the SAME gates below.

Three gates keep it never-fake-green (mirrored on
:mod:`app.execution.objectives.generate_usage_doc`):

  1. the examples must PASS today (:func:`~app.execution.stub_synthesis.examples_pass`)
     — Apex never pins a RED contract;
  2. the generated test source must ``ast.parse`` clean — never ship un-runnable
     test code;
  3. ``apply_rename``'s full-suite gate + byte-for-byte rollback compose on top
     (the engine blesses a CREATED test file and deletes it on rollback).

It REFUSES (an honest under-claim, lands nothing) when: there is no enforceable
example (a ``+SKIP``-only docstring pins no contract); the target is a
test/fixture file; the function's examples are ALREADY ENFORCED — either a
``test_*.py`` already pins the symbol (:func:`pinned_test_files`) or, the biggest
false-negative risk, the project runs ``pytest --doctest-modules`` (configured in
``pyproject.toml`` / ``pytest.ini`` / ``setup.cfg`` / ``tox.ini``, or a doctest
option in a ``conftest.py``), in which case EVERY module docstring is already
executed suite-wide and a dedicated test would only duplicate it.

Deterministic (functions in source order, pure AST + docstring → content, no
clock/random), stdlib-only, zero-token, idempotent (a second run sees its own
generated test file and produces a byte-identical no-op).
"""

from __future__ import annotations

import ast
import doctest
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _is_fixture_path
from app.execution.objectives._base import register_module_objective
from app.execution.stub_synthesis import (
    _compiled_module_namespace,
    _module_dotted_paths,
    enforceable_examples_for_function,
    examples_pass,
    pinned_test_files,
)


@dataclass(frozen=True)
class _Symbol:
    """One doctest-bearing SYMBOL pin-doctest can land a gating test for: a
    top-level function, a public class (its docstring), or a public method.

    The fields carry everything the per-symbol gates and the test renderer need,
    so descending from functions into class docstrings and methods changes only
    name RESOLUTION (function -> ``Class`` / ``Class.method``), never the gates:

      * ``bare_name``/``lineno`` address the def/class node for the
        :func:`~app.execution.stub_synthesis.enforceable_examples_for_function`
        and :func:`examples_pass` extractors (which key on name AND 1-based
        lineno, so a same-named sibling is never confused for it);
      * ``dotted`` is the access path UNDER THE MODULE (``"f"`` | ``"Counter"`` |
        ``"Counter.value"``) the env-stability probe resolves by successive
        ``getattr``;
      * ``test_name``/``access_expr`` are the generated test's function name and
        the expression that fetches the live object whose ``__doc__`` is run.
    """

    bare_name: str
    lineno: int
    dotted: str
    test_name: str
    access_expr: str

# pytest doctest opt-ins to scan config files for. Any of these means the project
# already EXECUTES module docstrings suite-wide, so a per-function gating test
# would only duplicate that enforcement — pin-doctest refuses project-wide.
_DOCTEST_CONFIG_FILES = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


def _doctest_examples_already_enforced_project_wide(root: Path) -> bool:
    """True when the project is configured to run ``pytest --doctest-modules`` (or a
    ``conftest.py`` enables a doctest option) — so every module docstring's examples
    are ALREADY executed by the suite. The biggest false-negative risk: such a
    project enforces doctests with NO ``test_*.py`` reference, so the per-symbol
    linkage check would miss it and pin-doctest would land a DUPLICATE gate. Pure
    text scan (no parsing of foreign config dialects), guarded against unreadable
    files, deterministic."""
    for name in _DOCTEST_CONFIG_FILES:
        try:
            text = (root / name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "--doctest-modules" in text or "doctest_modules" in text:
            return True
    for conftest in sorted(root.rglob("conftest.py")):
        try:
            text = conftest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "doctest" in text:
            return True
    return False


def _want_is_unordered_repr(want: str) -> bool:
    """True when a doctest example's EXPECTED output ``want`` is a ``set``/``dict``
    repr — an output whose element/key order is ``PYTHONHASHSEED``-dependent (a set)
    or could be set-iteration-derived (a dict).

    The LANDED pin-doctest test re-runs the example via :mod:`doctest` at the USER's
    runtime seed, comparing the live ``repr`` against this literal text. A set repr
    like ``{'a', 'b'}`` re-renders in a DIFFERENT order under another seed, so the
    landed test would be RED elsewhere — a future-red fake-green. We REFUSE to pin
    such an example (conservative: a dict repr is refused too, since its key order
    can be set-derived, and the degenerate empty ``set()``/``{}`` — though stable — is
    refused as well, costing nothing). Pure: parses ``want`` with
    :func:`ast.literal_eval` (no execution; modern ``literal_eval`` resolves
    ``set()`` to an empty set); a non-literal ``want`` is not a set/dict repr."""
    text = want.strip()
    if not text:
        return False
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
        return False
    return isinstance(value, (set, dict))


def _function_has_unordered_want(source: str, name: str, lineno: int) -> bool:
    """True when ANY enforceable example of ``name`` has a set/dict-repr expected
    output — so pinning it would land a hash-seed-fragile test. Document order,
    deterministic; a function with no such example yields ``False``."""
    for ex in enforceable_examples_for_function(source, name, lineno):
        if _want_is_unordered_repr(ex.want):
            return True
    return False


# The env-stable probe: import the module under VARIED env and re-run a function's
# enforceable ``>>>`` examples by the stdlib doctest runner, reporting whether they
# all pass. Mirrors :mod:`app.execution.doctest_oracle`: a fresh interpreter, the
# project root on ``sys.path``, examples rebuilt from the live ``__doc__`` (``+SKIP``
# dropped) and run in the module's namespace. A green verdict under a DIFFERENT cwd
# / ``$HOME`` / ``$TZ`` / ``$TMPDIR`` / ``PYTHONHASHSEED`` proves the example is not
# environment-dependent. argv: project root, dotted module, symbol name — the last
# may be a single component (a function) or a DOTTED access path (``Class`` /
# ``Class.method``), resolved by successive ``getattr`` while the doctest globals
# stay ``module.__dict__`` (so a method example reading ``Counter().m()`` resolves
# the class). A single-component name resolves identically to the original
# ``getattr(module, fn_name)``, so the function path is byte-identical.
_ENV_DOCTEST_PROBE = r"""
import doctest, importlib, json, sys
root, dotted, fn_name = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
try:
    module = importlib.import_module(dotted)
    obj = module
    for _part in fn_name.split("."):
        obj = getattr(obj, _part, None)
        if obj is None:
            print(json.dumps({"ok": False}))
            sys.exit(0)
    func = obj
    examples = [
        ex for ex in doctest.DocTestParser().get_examples(func.__doc__ or "")
        if not ex.options.get(doctest.SKIP)
    ]
    if not examples:
        print(json.dumps({"ok": False}))
        sys.exit(0)
    test = doctest.DocTest(examples, module.__dict__, fn_name, None, 0, None)
    runner = doctest.DocTestRunner(verbose=False)
    result = runner.run(test, out=lambda _s: None, clear_globs=False)
    print(json.dumps({"ok": True, "green": result.failed == 0 and result.attempted > 0}))
except BaseException:  # noqa: BLE001 - any failure -> refuse (never a fake green)
    print(json.dumps({"ok": False}))
    sys.exit(0)
"""

# Two distinct environment variations: a value/example that reads cwd/HOME/TZ/
# TMPDIR or a hash-seed-derived order diverges (goes RED) under at least one. The
# dir-valued axes are filled with real temp dirs at call time. Pinned values keep
# the gate deterministic (same variations every run).
_ENV_DOCTEST_SEEDS = (
    {"TZ": "America/New_York", "PYTHONHASHSEED": "1"},
    {"TZ": "Asia/Tokyo", "PYTHONHASHSEED": "424242"},
)


def _examples_env_stable(root: Path, dotted: str, fn_name: str) -> bool:
    """True iff ``dotted.fn_name``'s enforceable examples stay GREEN under every
    environment variation — the env-reproducibility gate for pin-doctest.

    For each spec in :data:`_ENV_DOCTEST_SEEDS` a fresh temp cwd / ``$HOME`` /
    ``$TMPDIR`` is created and the function's examples are re-run there (with that
    spec's distinct ``$TZ``/``PYTHONHASHSEED``) by :data:`_ENV_DOCTEST_PROBE`. An
    example reading the environment (``>>> f()`` -> cwd / ``$HOME`` / a clock / a
    set-order repr) goes RED under at least one variation and is REFUSED. A child
    that fails to run/parse also yields ``False`` (refuse — never pin an unverified
    example). Conservative; deterministic (pinned variation values)."""
    for spec in _ENV_DOCTEST_SEEDS:
        with tempfile.TemporaryDirectory(prefix="apex_pindoc_") as base:
            var_cwd = os.path.join(base, "cwd")
            var_home = os.path.join(base, "home")
            var_tmp = os.path.join(base, "tmp")
            for d in (var_cwd, var_home, var_tmp):
                os.makedirs(d, exist_ok=True)
            env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
                "HOME": var_home, "TMPDIR": var_tmp, "TEMP": var_tmp, "TMP": var_tmp,
                "TZ": spec["TZ"], "PYTHONHASHSEED": spec["PYTHONHASHSEED"],
            }
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", _ENV_DOCTEST_PROBE,
                     str(root), dotted, fn_name],
                    cwd=var_cwd, capture_output=True, text=True, env=env, timeout=60,
                )
            except (OSError, subprocess.SubprocessError):
                return False
        if proc.returncode != 0:
            return False
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return False
        if not result.get("ok") or not result.get("green"):
            return False
    return True


def _qualifying_functions(root: Path, module_rel: str, source: str,
                          dotted: str | None = None) -> list[tuple[str, int]]:
    """The (name, 1-based lineno) of every top-level function in ``source`` whose
    UNENFORCED doctest examples pin-doctest would pin: it has >=1 enforceable ``>>>``
    example, its examples PASS today (under a pinned hash seed), NO ``test_*.py``
    already pins it, NONE of its examples has a ``set``/``dict``-repr expected output
    (hash-seed-fragile), and — when ``dotted`` is given — its examples stay GREEN
    under a VARIED environment (different cwd / ``$HOME`` / ``$TZ`` / ``$TMPDIR`` /
    ``PYTHONHASHSEED``). The last two gates keep the LANDED test from being green
    here but RED on another machine/run. Source-ordered and deterministic; ``[]`` on
    a syntax error."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _function_qualifies(root, module_rel, source, dotted, node):
            out.append((node.name, node.lineno))
    return out


def _function_qualifies(root: Path, module_rel: str, source: str,
                        dotted: str | None,
                        node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Does ``node``'s function pass EVERY pin-doctest gate? (the per-function check).

    All gates must hold: it has >=1 enforceable ``>>>`` example; its examples PASS
    today under a pinned hash seed (gate 1); NO ``test_*.py`` already pins it; NONE of
    its examples has a ``set``/``dict``-repr expected output (hash-seed-fragile); and
    — when ``dotted`` is given — its examples stay GREEN under a VARIED environment.
    Any failing gate yields ``False`` (the function is not pinned). Conservative and
    deterministic."""
    name, lineno = node.name, node.lineno
    if not enforceable_examples_for_function(source, name, lineno):
        return False  # no enforceable example (or +SKIP-only) — nothing to pin
    if not examples_pass(source, name, lineno):
        return False  # RED today — never pin a failing contract (gate 1)
    if pinned_test_files(root, module_rel, name):
        return False  # a test already enforces this symbol — no duplicate gate
    if _function_has_unordered_want(source, name, lineno):
        return False  # set/dict-repr expected output — hash-seed-fragile, refuse
    if dotted is not None and not _examples_env_stable(root, dotted, name):
        return False  # example varies with the environment — future-red, refuse
    return True


# === descent into PUBLIC classes: class docstrings + public methods ============
# The function path above pins ONLY top-level ``tree.body`` functions, so a worked
# example living in a class docstring or a method docstring is run by nothing. The
# helpers below collect those SYMBOLS and clear the SAME prove-or-refuse gates,
# generalizing name resolution from a module global to ``Class`` / ``Class.method``.


def _class_docstring_examples(source: str, classname: str) -> list[doctest.Example]:
    """The ENFORCEABLE ``>>>`` examples in the docstring of the top-level class
    ``classname`` in ``source`` (``# doctest: +SKIP`` dropped — those pin no
    contract). Extracted LOCALLY via :func:`ast.get_docstring` because the shared
    :func:`~app.execution.stub_synthesis.enforceable_examples_for_function` matches
    only ``FunctionDef``/``AsyncFunctionDef`` (it skips ``ClassDef``), so it returns
    ``[]`` for a class. Same ``+SKIP``-aware rule as everywhere else. Fully guarded:
    a malformed source or a missing/docstring-less class yields ``[]``."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == classname:
            text = ast.get_docstring(node) or ""
            return [ex for ex in doctest.DocTestParser().get_examples(text)
                    if not ex.options.get(doctest.SKIP)]
    return []


def _examples_green_in_namespace(source: str, name: str,
                                 examples: list[doctest.Example]) -> bool:
    """True iff ``examples`` all PASS when run against the WHOLE compiled module
    namespace of ``source`` — the in-process gate-1 verdict for a method or class
    docstring. Mirrors :func:`~app.execution.stub_synthesis._doctests_pass` EXACTLY
    except the example is resolved against the full module namespace (where the
    class lives, so a method example ``Counter().value()`` references it) instead of
    requiring ``name`` to itself be a module global. Conservative, never a
    fake-green: no example, an un-compilable source, or any runner error yields
    ``False``. Determinism note: the sole seed-sensitive shape (a ``set``/``dict``
    repr) is independently REFUSED by the unordered-want gate, so running this
    in-process under the parent seed is safe."""
    if not examples:
        return False
    ns = _compiled_module_namespace(source)
    if ns is None:
        return False
    test = doctest.DocTest(examples, ns, name, None, 0, None)
    runner = doctest.DocTestRunner(verbose=False)
    try:
        result = runner.run(test, out=lambda _s: None, clear_globs=False)
    except Exception:
        return False
    return result.failed == 0 and result.attempted > 0


def _symbol_examples_pass(source: str, bare_name: str, lineno: int) -> bool:
    """The method GATE-1 verdict: ``bare_name``'s enforceable examples all pass when
    resolved against the module namespace. (The shared :func:`examples_pass` cannot
    be reused for a method — it looks ``bare_name`` up as a module global, which a
    method name is not.) Tiny wrapper over :func:`_examples_green_in_namespace`."""
    return _examples_green_in_namespace(
        source, bare_name,
        enforceable_examples_for_function(source, bare_name, lineno))


def _class_doc_examples_pass(source: str, classname: str) -> bool:
    """The class-docstring GATE-1 verdict: the class's docstring examples all pass
    when resolved against the module namespace (the class name IS a global there).
    Tiny wrapper over :func:`_examples_green_in_namespace`."""
    return _examples_green_in_namespace(
        source, classname, _class_docstring_examples(source, classname))


def _class_doc_has_unordered_want(source: str, classname: str) -> bool:
    """True when ANY class-docstring example of ``classname`` has a ``set``/``dict``-
    repr expected output — the hash-seed-fragile shape pin-doctest refuses. The
    method/function path reuses :func:`_function_has_unordered_want`; a class
    docstring is not function-addressable, so it scans its own examples here."""
    return any(_want_is_unordered_repr(ex.want)
               for ex in _class_docstring_examples(source, classname))


def _iter_candidate_symbols(tree: ast.Module) -> list[_Symbol]:
    """Every doctest-bearing SYMBOL inside a top-level PUBLIC class, in deterministic
    order: for each public ``ClassDef`` (name not starting ``_``) in source order,
    the class-docstring symbol FIRST (when its docstring carries an enforceable
    example) then each public method (name not starting ``_``, plus ``__init__``) in
    source (lineno) order whose docstring carries an enforceable example. No
    pre-walk of foreign nodes, no clock/random — purely ``tree.body`` order. The
    per-symbol gates downstream decide; this only enumerates the candidates."""
    out: list[_Symbol] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        out.extend(_class_symbols(node))
    return out


def _class_symbols(node: ast.ClassDef) -> list[_Symbol]:
    """The candidate :class:`_Symbol` records for ONE public class ``node``: its
    docstring symbol (when example-bearing) first, then its example-bearing public
    methods in source order. Kept tiny so the iterator stays well under the
    complexity ceiling."""
    out: list[_Symbol] = []
    cls = node.name
    doc = ast.get_docstring(node) or ""
    if any(not ex.options.get(doctest.SKIP)
           for ex in doctest.DocTestParser().get_examples(doc)):
        out.append(_Symbol(cls, node.lineno, cls, f"test_{cls}",
                           f"_module.{cls}"))
    for child in node.body:
        if _is_pinnable_method(child):
            out.append(_method_symbol(cls, child))
    return out


def _is_pinnable_method(child: ast.stmt) -> bool:
    """True when ``child`` is a method pin-doctest may descend into: a
    ``def``/``async def`` that is public (name not starting ``_``) OR is exactly
    ``__init__``, and whose docstring carries at least one enforceable example."""
    if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if child.name.startswith("_") and child.name != "__init__":
        return False
    doc = ast.get_docstring(child) or ""
    return any(not ex.options.get(doctest.SKIP)
               for ex in doctest.DocTestParser().get_examples(doc))


def _method_symbol(cls: str, child: ast.FunctionDef | ast.AsyncFunctionDef) -> _Symbol:
    """The :class:`_Symbol` for one public method ``child`` of class ``cls``. The
    generated test fetches the live function via ``getattr(_module.Cls, "m")`` so
    its ``__doc__`` examples run in the module namespace (where the class lives)."""
    m = child.name
    return _Symbol(m, child.lineno, f"{cls}.{m}", f"test_{cls}_{m}",
                   f"getattr(_module.{cls}, {m!r})")


def _symbol_qualifies(root: Path, module_rel: str, source: str,
                      dotted: str | None, sym: _Symbol) -> bool:
    """Does the class/method ``sym`` pass EVERY pin-doctest gate? Parallel to
    :func:`_function_qualifies` but with name resolution generalized to a class /
    method. A class symbol's ``bare_name == dotted`` (the leaf class name); a method
    symbol's ``dotted`` is ``Class.method``, so ``sym.bare_name != sym.dotted``
    selects the gate-1 verdict and key set without branching on a type tag.

    All gates must hold: gate-1 green TODAY (the docstring examples pass in the
    module namespace — class via :func:`_class_doc_examples_pass`, method via
    :func:`_symbol_examples_pass`); NOT already pinned (DUAL KEY — refuse if a
    ``test_*.py`` importing the module references the leaf name OR, for a method,
    the class name); NO ``set``/``dict``-repr expected output (hash-seed-fragile);
    and — when ``dotted`` is given — the examples stay GREEN under a VARIED
    environment (the probe resolves ``sym.dotted``). Conservative, deterministic."""
    is_class = sym.bare_name == sym.dotted
    if is_class:
        gate1 = _class_doc_examples_pass(source, sym.bare_name)
        unordered = _class_doc_has_unordered_want(source, sym.bare_name)
    else:
        gate1 = _symbol_examples_pass(source, sym.bare_name, sym.lineno)
        unordered = _function_has_unordered_want(source, sym.bare_name, sym.lineno)
    if not gate1:
        return False  # RED today (in the module namespace) — never pin a failure
    if _symbol_already_pinned(root, module_rel, sym, is_class):
        return False  # a test already exercises the leaf (or its class) — no dup
    if unordered:
        return False  # set/dict-repr expected output — hash-seed-fragile, refuse
    if dotted is not None and not _examples_env_stable(root, dotted, sym.dotted):
        return False  # example varies with the environment — future-red, refuse
    return True


def _symbol_already_pinned(root: Path, module_rel: str, sym: _Symbol,
                           is_class: bool) -> bool:
    """The DUAL-KEY duplicate refusal: a method is already pinned if a ``test_*.py``
    importing the module references EITHER its leaf method name OR its class name (a
    test exercising the class likely covers the method's contract); a class symbol
    keys on its own name alone. Conservative — never a duplicate gate."""
    if pinned_test_files(root, module_rel, sym.bare_name):
        return True
    if is_class:
        return False
    classname = sym.dotted.split(".", 1)[0]
    return bool(pinned_test_files(root, module_rel, classname))


def _doctest_name_expr(has_objects: bool) -> str:
    """The DocTest ``name`` argument for the generated ``_run_enforceable`` helper.

    For a function-only module the helper keeps the EXACT current text
    ``func.__name__`` (so the generated file is byte-for-byte what it is today). The
    moment a class or method symbol is present the name is fetched safely with
    ``getattr(func, "__name__", "doctest")`` — a class object and a bound function
    both have ``__name__``, but the getattr-safe form makes the helper robust for
    any resolved object. This single conditional is the ONLY thing that changes the
    generated bytes, and only for modules that actually have qualifying
    methods/classes — off-by-default byte-identity is preserved."""
    return 'getattr(func, "__name__", "doctest")' if has_objects else "func.__name__"


def _render_doctest_test(dotted: str, stem: str, symbols: list[_Symbol],
                         has_objects: bool = False) -> str:
    """Render the ``tests/test_<stem>_doctest.py`` source: one test per qualifying
    SYMBOL (a top-level function, a public class docstring, or a public method),
    each rebuilding the symbol's ENFORCEABLE examples from the LIVE ``__doc__`` of
    the resolved object (``+SKIP`` excluded, the same set Apex verified) and
    asserting the stdlib :mod:`doctest` runner reports zero failures. The example
    text is NOT hardcoded — it is re-derived at runtime from the docstring, so the
    test pins whatever the (already-green) docstring declares.

    Byte-identity: for a function-only module (``has_objects`` is ``False``) the
    helper text and every test use the EXACT current shape (``func.__name__`` /
    ``def test_<fn>_doctest():`` / ``_run_enforceable(_module.<fn>)``), so the
    generated file is unchanged. Deterministic: symbols in the given (source)
    order; no clock/random."""
    lines = [
        '"""Auto-generated by Apex pin-doctest: execute the unenforced ``>>>``',
        f'examples of {dotted} as a suite-enforced contract.',
        "",
        "Apex generated this so the module's worked docstring examples — already",
        "green but run by nothing — are kept honest by the project's own test run.",
        "Each test rebuilds the function's enforceable examples (``# doctest: +SKIP``",
        "excluded) from the live ``__doc__`` and asserts the stdlib ``doctest``",
        'runner reports zero failures.',
        '"""',
        "",
        "import doctest",
        "import importlib",
        "",
        f"_module = importlib.import_module({dotted!r})",
        "",
        "",
        "def _run_enforceable(func):",
        '    """Run the function\'s enforceable ``>>>`` examples; return the runner',
        '    result. ``+SKIP`` examples are dropped — they pin no contract."""',
        "    examples = [",
        "        ex for ex in doctest.DocTestParser().get_examples(func.__doc__ or \"\")",
        "        if not ex.options.get(doctest.SKIP)",
        "    ]",
        "    assert examples, \"expected at least one enforceable doctest example\"",
        f"    test = doctest.DocTest(examples, _module.__dict__, {_doctest_name_expr(has_objects)},",
        "                           None, 0, None)",
        "    runner = doctest.DocTestRunner(verbose=False)",
        "    return runner.run(test, out=lambda _s: None, clear_globs=False)",
        "",
    ]
    for sym in symbols:
        lines += [
            "",
            f"def {sym.test_name}_doctest():",
            f"    result = _run_enforceable({sym.access_expr})",
            "    assert result.failed == 0",
        ]
    return "\n".join(lines) + "\n"


def _function_symbols(functions: list[tuple[str, int]]) -> list[_Symbol]:
    """Wrap the qualifying top-level ``(name, lineno)`` functions as :class:`_Symbol`
    records in their FUNCTION form — ``dotted == bare_name`` and the EXACT current
    accessor ``_module.<name>`` / test name ``test_<name>`` — so a function-only
    module renders byte-for-byte what it does today. Source order preserved."""
    return [_Symbol(name, lineno, name, f"test_{name}", f"_module.{name}")
            for name, lineno in functions]


def _dedup_test_names(symbols: list[_Symbol]) -> list[_Symbol]:
    """Make every symbol's ``test_name`` UNIQUE so the rendered file never emits
    two identically-named ``def test_..._doctest()`` (the second of which would
    shadow the first at collection, silently dropping one verified contract).

    The ``test_<Class>_<method>`` flattening uses underscores, so distinct symbols
    can collapse to one name — e.g. a top-level function ``C_value`` and class ``C``
    method ``value`` both render ``test_C_value``; likewise class ``A_b``.``c`` vs
    class ``A``.``b_c``. For ANY ``test_name`` shared by >1 symbol, this appends the
    symbol's 1-based source ``lineno`` (``test_C_value`` -> ``test_C_value_l5`` /
    ``test_C_value_l14``): two distinct symbols in one module have distinct linenos,
    so the suffixed names are unique AND stably tied to the source def. Names that
    are already unique are returned UNCHANGED — so a function-only module (no
    method/class symbols to collide with) is byte-for-byte what it is today, and a
    collision only perturbs the colliding pair. Deterministic: input order
    preserved; the suffix is an AST lineno, never a clock/random/hash value."""
    counts = Counter(sym.test_name for sym in symbols)
    return [sym if counts[sym.test_name] == 1
            else replace(sym, test_name=f"{sym.test_name}_l{sym.lineno}")
            for sym in symbols]


def _qualifying_class_symbols(root: Path, module_rel: str, source: str,
                              dotted: str | None) -> list[_Symbol]:
    """The class-docstring + public-method symbols (source order) that clear EVERY
    pin-doctest gate via :func:`_symbol_qualifies`. ``[]`` on a syntax error — the
    function path has already handled the module's top-level functions."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    return [sym for sym in _iter_candidate_symbols(tree)
            if _symbol_qualifies(root, module_rel, source, dotted, sym)]


def plan_pin_doctest(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the pin-doctest plan for one module, or an honest no-op.

    CREATES ``tests/test_<stem>_doctest.py`` with one test per SYMBOL whose
    enforceable docstring examples PASS today but nothing enforces — a top-level
    function, a public class (its docstring), or a public method. Like
    :func:`~app.execution.objectives.generate_usage_doc.plan_generate_usage_doc`
    this is a NEW-FILE plan (not a source rewrite): the original (existing-or-``""``)
    goes in ``originals`` so the verified-apply engine can roll the create back. An
    EMPTY plan (a no-op refusal) results when the target is a test/fixture file, the
    module is unreadable, the project already enforces doctests project-wide
    (``--doctest-modules``), no symbol qualifies, or the generated test source
    would not parse. Idempotent: a second run sees the already-pinned test file
    (its symbols are now enforced by it) and yields a byte-identical no-op.

    Determinism / ordering: top-level functions FIRST (in source order, exactly as
    before — so a function-only module is byte-identical), then class symbols in
    source order (each class's docstring symbol before its methods, methods in
    lineno order). Generated test-function names are made UNIQUE
    (:func:`_dedup_test_names`) so a name the underscore-flattening would otherwise
    collide (e.g. function ``C_value`` vs class ``C`` method ``value``) cannot
    silently shadow another symbol's contract; non-colliding names are unchanged."""
    root = Path(project_root)
    plan = RenamePlan(old=module_rel, new="pin-doctest")
    if _is_fixture_path(module_rel):
        return plan  # never pin a test/fixture file
    if _doctest_examples_already_enforced_project_wide(root):
        return plan  # `pytest --doctest-modules` already runs every docstring
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    dotted_paths = _module_dotted_paths(root, module_rel)
    if not dotted_paths:
        return plan  # no importable name — cannot generate a runnable test

    # The env-reproducibility gate re-runs the examples under the SAME dotted path
    # the generated test imports, so a symbol only qualifies when its examples are
    # green AND stay green under a varied environment.
    functions = _qualifying_functions(root, module_rel, source, dotted_paths[0])
    class_symbols = _qualifying_class_symbols(
        root, module_rel, source, dotted_paths[0])
    symbols = _dedup_test_names(_function_symbols(functions) + class_symbols)
    if not symbols:
        return plan  # nothing unenforced-but-green to pin — honest under-claim

    stem = Path(module_rel).stem
    generated = _render_doctest_test(dotted_paths[0], stem, symbols,
                                     has_objects=bool(class_symbols))
    try:
        ast.parse(generated)  # gate 2: never ship un-runnable test code
    except (SyntaxError, ValueError):
        return plan

    doc_rel = (Path("tests") / f"test_{stem}_doctest.py").as_posix()
    try:
        original = (root / doc_rel).read_text(encoding="utf-8")
    except OSError:
        original = ""
    if generated == original:
        return plan  # already pinned — byte-identical no-op (idempotent)

    plan.originals[doc_rel] = original
    plan.new_contents[doc_rel] = generated
    plan.edits_by_file[doc_rel] = len(symbols)
    return plan


register_module_objective(
    "pin-doctest", plan_pin_doctest, operator="pin_doctest",
    description="pin the unenforced doctest examples in {rel} with a gating test")
