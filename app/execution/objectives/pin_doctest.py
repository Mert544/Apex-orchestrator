"""Self-registering objective: pin-doctest.

The honest gap this closes: a function carries ``>>>`` examples in its docstring
— a worked contract a reader trusts — yet NOTHING in the suite runs them. The
examples are documentation, not a test: they can silently rot to RED while the
suite stays green. Apex LANDS a real, suite-enforced test that EXECUTES those
examples, turning the documentation into a contract the project's own test run
keeps honest — for free, deterministically, no LLM.

The contribution is a NEW file ``tests/test_<stem>_doctest.py`` (additive — it
never edits the module or the existing suite), one test function per qualifying
function, each rebuilding the function's ENFORCEABLE examples from the live
``__doc__`` and asserting the stdlib :mod:`doctest` runner reports zero failures.
The examples are user-authored and already green, so the claim is near-zero
over-claim: the test only restates a contract the code already satisfies.

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
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _is_fixture_path
from app.execution.objectives._base import register_module_objective
from app.execution.stub_synthesis import (
    _module_dotted_paths,
    enforceable_examples_for_function,
    examples_pass,
    pinned_test_files,
)

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
# environment-dependent. argv: project root, dotted module, function name.
_ENV_DOCTEST_PROBE = r"""
import doctest, importlib, json, sys
root, dotted, fn_name = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
try:
    module = importlib.import_module(dotted)
    func = getattr(module, fn_name, None)
    if func is None:
        print(json.dumps({"ok": False}))
        sys.exit(0)
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


def _render_doctest_test(dotted: str, stem: str,
                         functions: list[tuple[str, int]]) -> str:
    """Render the ``tests/test_<stem>_doctest.py`` source: one test per qualifying
    function, each rebuilding the function's ENFORCEABLE examples from its live
    ``__doc__`` (``+SKIP`` excluded, the same set Apex verified) and asserting the
    stdlib :mod:`doctest` runner reports zero failures. The example text is NOT
    hardcoded — it is re-derived at runtime from the docstring, so the test pins
    whatever the (already-green) docstring declares. Deterministic: functions in
    the given (source) order; no clock/random."""
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
        "    test = doctest.DocTest(examples, _module.__dict__, func.__name__,",
        "                           None, 0, None)",
        "    runner = doctest.DocTestRunner(verbose=False)",
        "    return runner.run(test, out=lambda _s: None, clear_globs=False)",
        "",
    ]
    for name, _lineno in functions:
        lines += [
            "",
            f"def test_{name}_doctest():",
            f"    result = _run_enforceable(_module.{name})",
            "    assert result.failed == 0",
        ]
    return "\n".join(lines) + "\n"


def plan_pin_doctest(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the pin-doctest plan for one module, or an honest no-op.

    CREATES ``tests/test_<stem>_doctest.py`` with one test per function whose
    enforceable docstring examples PASS today but nothing enforces. Like
    :func:`~app.execution.objectives.generate_usage_doc.plan_generate_usage_doc`
    this is a NEW-FILE plan (not a source rewrite): the original (existing-or-``""``)
    goes in ``originals`` so the verified-apply engine can roll the create back. An
    EMPTY plan (a no-op refusal) results when the target is a test/fixture file, the
    module is unreadable, the project already enforces doctests project-wide
    (``--doctest-modules``), no function qualifies, or the generated test source
    would not parse. Idempotent: a second run sees the already-pinned test file
    (its functions are now enforced by it) and yields a byte-identical no-op."""
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
    # the generated test imports, so a function only qualifies when its examples are
    # green AND stay green under a varied environment.
    functions = _qualifying_functions(root, module_rel, source, dotted_paths[0])
    if not functions:
        return plan  # nothing unenforced-but-green to pin — honest under-claim

    stem = Path(module_rel).stem
    generated = _render_doctest_test(dotted_paths[0], stem, functions)
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
    plan.edits_by_file[doc_rel] = len(functions)
    return plan


register_module_objective(
    "pin-doctest", plan_pin_doctest, operator="pin_doctest",
    description="pin the unenforced doctest examples in {rel} with a gating test")
