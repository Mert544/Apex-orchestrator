"""What did "tests passed" actually prove? — coverage-aware verification.

Full-suite verification is only as strong as the suite's interest in what
changed: on a module no test ever references, a green run proves nothing
about the change. This module statically grades that strength, so apply
results and proof-of-fix records can distinguish "verified by tests that
NAME the changed function" from "applied blind — the suite never looks at
this module".

Levels (weakest link across the changed files):
  - ``function``   — a referencing test names a changed function
  - ``module``     — tests import/reference the module, none name the change
  - ``none``       — no test references the module at all (applied blind)
  - ``test-change``— only test files changed (they ARE the suite)
  - ``baseline-red``— the suite was ALREADY failing before any fix, so a
                      green-after (or a still-red that didn't worsen) cannot be
                      attributed to THIS fix; the weakest tier of all (it proves
                      strictly less than ``none`` — even a blind apply at least
                      ran against a green suite). A fix recorded ``baseline-red``
                      is INCONCLUSIVE, never verified, and is withheld from
                      auto-commit. Set externally by the maintenance pass once it
                      records a non-green pre-flight; ``assess_strength`` itself
                      (a static, no-execution grader) never emits it.

Deterministic, stdlib-only, no execution — it inspects the test files' text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS as _SKIPPED_DIRS

# The weakest verification tier: the suite was red BEFORE the fix, so its result
# proves nothing about the fix. Ranked below ``none`` so any "weakest link"
# comparison treats it as the floor.
BASELINE_RED = "baseline-red"

_RANK = {BASELINE_RED: -1, "none": 0, "module": 1, "function": 2}
_MAX_TEST_FILE_BYTES = 400_000  # don't slurp generated monsters


def _is_test_path(rel: str) -> bool:
    p = rel.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or p.startswith(("tests/", "test/")) or "/tests/" in p or "/test/" in p)


def changed_functions(old: str, new: str) -> list[str]:
    """Names of functions whose source differs between ``old`` and ``new``
    (including functions present on only one side). Unparsable sides yield []
    rather than guessing."""
    def _functions(src: str) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            tree = ast.parse(src)
        except (SyntaxError, RecursionError, MemoryError):
            return out
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    out[node.name] = ast.get_source_segment(src, node) or node.name
                except Exception:
                    out[node.name] = node.name
        return out

    a, b = _functions(old), _functions(new)
    return sorted(name for name in {*a, *b} if a.get(name) != b.get(name))


def _test_files(root: Path) -> list[tuple[str, str]]:
    """All (relative_path, text) test files under ``root``, deterministic order."""
    out: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in _SKIPPED_DIRS for part in Path(rel).parts):
            continue
        if not _is_test_path(rel):
            continue
        try:
            if path.stat().st_size > _MAX_TEST_FILE_BYTES:
                continue
            out.append((rel, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return out


def _imported_modules(text: str) -> set[str] | None:
    """Dotted module paths actually IMPORTED by ``text`` (AST-exact).

    Walks ``Import`` / ``ImportFrom`` nodes only, so a module named in a comment
    or a string literal is NOT reported — those prove nothing about a change to
    it. Returns ``None`` when the text does not parse (caller falls back to a
    regex over import lines)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                mods.add(base)
            for alias in node.names:
                mods.add(f"{base}.{alias.name}" if base else alias.name)
    return mods


def _module_identity(rel_path: str) -> tuple[str, str] | None:
    """The (dotted_path, own_name) by which a test would IMPORT ``rel_path``,
    or ``None`` if it is not an importable module.

    Flat module: ``pkg/danger.py`` → (``"pkg.danger"``, ``"danger"``).
    Package init: ``inflection/__init__.py`` is imported as the PACKAGE, not as
    ``inflection.__init__`` — the importable name is the parent directory(ies),
    so ``inflection/__init__.py`` → (``"inflection"``, ``"inflection"``) and
    ``a/b/__init__.py`` → (``"a.b"``, ``"b"``). ``import inflection`` /
    ``from inflection import camelize`` then correctly reference the init file,
    where the old ``inflection.__init__`` form matched no real import. A bare
    top-level ``__init__.py`` (no parent package) is not importable → ``None``."""
    norm = rel_path.replace("\\", "/")
    if not norm.endswith(".py"):
        return None
    parts = norm[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]  # the package IS the parent dir(s), not ``__init__``
        if not parts:
            return None  # a root ``__init__.py`` has no importable package name
    return ".".join(parts), parts[-1]


def _references_module(text: str, rel_path: str) -> bool:
    """Does this test text actually IMPORT the module at ``rel_path``?

    AST-exact: a bare mention of the module in a comment or a string literal
    does NOT count as coverage — a green suite that only *names* the module in a
    comment proves nothing about a change to it (the over-counting a substring
    match used to allow). Falls back to an import-line regex only when the test
    text cannot be parsed.

    A ``<pkg>/__init__.py`` is keyed on its PACKAGE name (its parent dir), so
    ``import inflection`` references ``inflection/__init__.py`` — see
    :func:`_module_identity`."""
    identity = _module_identity(rel_path)
    if identity is None:
        return False
    dotted, name = identity
    mods = _imported_modules(text)
    if mods is not None:
        if dotted in mods:
            return True
        # The module's own name as a clean dotted component of a real import
        # (``from pkg import danger`` / ``import a.danger``) — covers layouts
        # whose project-root-relative dotted path differs from the test's root.
        return any(name == part for m in mods for part in m.split("."))
    # Unparsable test text: match the name only in an import position, not a
    # bare-word match (function names like ``run`` would otherwise flood).
    return bool(re.search(rf"(?:^|\n)\s*(?:from|import)\s+[\w.]*\b{re.escape(name)}\b", text))


def module_referenced_by_suite(project_root: str | Path, rel_path: str) -> bool:
    """Does ANY test file reference this module? (The cheap pre-check the
    test-first shield uses before touching an uncovered module.)"""
    if not rel_path.endswith(".py") or _is_test_path(rel_path):
        return True  # test files and non-Python targets never need a shield
    return any(_references_module(text, rel_path)
               for _rel, text in _test_files(Path(project_root)))


def _weaker(current: str, candidate: str) -> str:
    """The weaker (lower-ranked) of two strength levels."""
    return candidate if _RANK[candidate] < _RANK[current] else current


# Decorator attrs that mean a test never actually asserts against the change:
# ``@pytest.mark.skip``/``skipif`` never run; ``@pytest.mark.xfail`` runs but its
# failure (even an assertion of the WRONG value) is the EXPECTED outcome, so it
# keeps the suite green without verifying anything. A reference reachable ONLY
# from such a test proves nothing — it must not upgrade coverage to ``function``.
_INERT_DECORATORS = frozenset({"skip", "skipif", "xfail"})

# Statements after one of these (at the same block level) can never run.
_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _decorator_is_inert(node: ast.expr) -> bool:
    """Is this decorator a ``pytest.mark.skip``/``skipif``/``xfail`` (called or
    bare)? Matched on the decorator's final attribute/name, so any alias for
    ``pytest``/``mark`` is covered (``@mark.skip``, ``@pytest.mark.xfail()``)."""
    if isinstance(node, ast.Call):
        node = node.func
    attr = node.attr if isinstance(node, ast.Attribute) else (
        node.id if isinstance(node, ast.Name) else None)
    return attr in _INERT_DECORATORS


def _is_dead_branch(node: ast.stmt) -> bool:
    """An ``if False:`` / ``if 0:`` whose body is statically unreachable."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Constant):
        return not bool(test.value)
    return False


def _collect_own_identifiers(stmt: ast.stmt, out: set[str]) -> None:
    """Identifiers in ``stmt``'s OWN expression parts — i.e. excluding nested
    statement bodies, which :func:`_reachable_identifiers` walks separately with
    reachability rules. Walks every child that is not itself a statement."""
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, ast.stmt):
            continue  # a nested block — handled with its own reachability
        for sub in ast.walk(child):
            if isinstance(sub, ast.Name):
                out.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                out.add(sub.attr)


def _reachable_identifiers(body: list[ast.stmt], out: set[str]) -> None:
    """Collect ``Name`` ids / ``Attribute`` attrs from the statements in ``body``
    that can actually execute, recursing into reachable nested blocks.

    Drops (a) statements after a ``return``/``raise``/``continue``/``break`` at
    this block level, (b) the body of an ``if False:``/``if 0:`` (its ``else`` is
    still live), and (c) the whole body of a ``skip``/``skipif``/``xfail`` test.
    A statically-unreachable or never-asserting reference proves nothing about the
    change, so it must not be counted as coverage."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_decorator_is_inert(d) for d in stmt.decorator_list):
                continue  # a skip/xfail test never verifies — skip its whole body
            _collect_own_identifiers(stmt, out)  # decorators / default-arg exprs
            _reachable_identifiers(stmt.body, out)
        elif _is_dead_branch(stmt):
            _reachable_identifiers(stmt.orelse, out)  # body dead, else still runs
        else:
            _collect_own_identifiers(stmt, out)
            for nested in _child_bodies(stmt):
                _reachable_identifiers(nested, out)
        if isinstance(stmt, _TERMINATORS):
            break  # nothing after this statement at this level can run


def _child_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """The nested statement-list bodies of a compound statement (``if``/``for``/
    ``while``/``with``/``try``/class/handler bodies). Each is walked with its own
    reachability so an unreachable nested reference still doesn't count."""
    bodies: list[list[ast.stmt]] = []
    for field in ("body", "orelse", "finalbody"):
        block = getattr(stmt, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            bodies.append(block)
    for handler in getattr(stmt, "handlers", []) or []:
        bodies.append(handler.body)
    return bodies


def _code_identifiers(text: str) -> set[str] | None:
    """Identifiers in REACHABLE, asserting CODE positions of ``text`` — every
    ``Name`` id and ``Attribute`` attr — excluding names mentioned only in
    comments / string literals, names inside a ``skip``/``skipif``/``xfail`` test,
    and names in statically-unreachable positions (``if False:`` bodies, code
    after a ``return``/``raise``/``continue``/``break``). ``None`` when the text
    can't be parsed (caller falls back to a whole-word text match)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    names: set[str] = set()
    _reachable_identifiers(tree.body, names)
    return names


def _names_changed_function(text: str, funcs: list[str]) -> bool:
    """Does ``text`` REFERENCE — in code that can actually EXECUTE and assert —
    any of these changed function names?

    AST-exact — mirrors the rigor of :func:`_references_module`: a function name
    that appears only in a comment of an already-importing test must NOT upgrade
    coverage from ``module`` to ``function`` (it proves nothing about the change).
    Likewise a reference reachable only from a ``skip``/``skipif``/``xfail`` test
    or a statically-unreachable position (``if False:``, after a ``return``) is
    NOT coverage: no test runs that line against the change, so a green suite
    vouches for nothing. Falls back to a whole-word text match only when the test
    can't be parsed."""
    ids = _code_identifiers(text)
    if ids is not None:
        return any(name in ids for name in funcs)
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in funcs)


def _grade_file(
    rel: str,
    funcs: list[str],
    tests: list[tuple[str, str]],
) -> tuple[str, list[str], list[str]]:
    """Grade one changed code file against the suite. Pure.

    Returns ``(level, module_tests, function_tests)`` where ``level`` is the
    file's own strength ("function"/"module"/"none")."""
    referencing = [(t_rel, text) for t_rel, text in tests
                   if _references_module(text, rel)]
    module_tests = [t_rel for t_rel, _ in referencing]
    function_tests = [t_rel for t_rel, text in referencing
                      if _names_changed_function(text, funcs)]
    level = "function" if function_tests else ("module" if referencing else "none")
    return level, module_tests, function_tests


def assess_strength(
    project_root: str | Path,
    changed_files: list[str],
    old_by_path: dict[str, str | None],
    new_by_path: dict[str, str],
) -> dict:
    """Grade how strongly a passing suite vouches for these changes."""
    root = Path(project_root)
    code_files = [f for f in changed_files if f.endswith(".py") and not _is_test_path(f)]
    if not code_files:
        return {"level": "test-change", "changed_functions": [],
                "module_tests": [], "function_tests": []}

    tests = _test_files(root)
    worst = "function"
    all_changed: list[str] = []
    module_tests: list[str] = []
    function_tests: list[str] = []
    for rel in code_files:
        funcs = changed_functions(old_by_path.get(rel) or "", new_by_path.get(rel, ""))
        all_changed += [f"{rel}::{name}" for name in funcs]
        level, file_module_tests, file_function_tests = _grade_file(rel, funcs, tests)
        module_tests += file_module_tests
        function_tests += file_function_tests
        worst = _weaker(worst, level)
    return {
        "level": worst,
        "changed_functions": all_changed[:5],
        "module_tests": sorted(dict.fromkeys(module_tests))[:5],
        "function_tests": sorted(dict.fromkeys(function_tests))[:5],
    }
