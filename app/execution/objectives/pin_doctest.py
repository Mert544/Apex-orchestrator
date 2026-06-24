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


def _qualifying_functions(root: Path, module_rel: str,
                          source: str) -> list[tuple[str, int]]:
    """The (name, 1-based lineno) of every top-level function in ``source`` whose
    UNENFORCED doctest examples pin-doctest would pin: it has >=1 enforceable ``>>>``
    example, its examples PASS today, and NO ``test_*.py`` already pins it (so the
    new test adds enforcement rather than duplicating it). Source-ordered and
    deterministic; ``[]`` on a syntax error (``ast.parse`` raises nothing it then
    iterates)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not enforceable_examples_for_function(source, node.name, node.lineno):
            continue  # no enforceable example (or +SKIP-only) — nothing to pin
        if not examples_pass(source, node.name, node.lineno):
            continue  # RED today — never pin a failing contract (gate 1)
        if pinned_test_files(root, module_rel, node.name):
            continue  # a test already enforces this symbol — no duplicate gate
        out.append((node.name, node.lineno))
    return out


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

    functions = _qualifying_functions(root, module_rel, source)
    if not functions:
        return plan  # nothing unenforced-but-green to pin — honest under-claim

    dotted_paths = _module_dotted_paths(root, module_rel)
    if not dotted_paths:
        return plan  # no importable name — cannot generate a runnable test
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
