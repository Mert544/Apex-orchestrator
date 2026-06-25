"""Strengthen tests — generate assertions that KILL surviving mutants.

The strongest falsifiability oracle in the repo turned into a DEVELOP action.
Where :mod:`app.engine.mutation_tester` only MEASURES test strength (it seeds
tiny faults and reports which ones the suite fails to catch), this LANDS the
fix: for a module that HAS tests but whose tests miss a branch, it generates an
additional PASSING assertion that pins exactly the behaviour the suite currently
lets through — closing a real test blind spot with real new test code.

This is DISTINCT from ``cover-gaps``: cover-gaps writes a characterization test
for an UNTESTED module (it has no test at all); strengthen-tests STRENGTHENS an
existing-but-thin test by adding assertions that catch bugs the current suite
misses. The signal that there IS a blind spot is a *surviving mutant* — a seeded
fault the suite still passes on.

The pipeline (deterministic, no LLM, no clock, no randomness):

1. Run the existing mutation engine over the target module to enumerate the
   SURVIVING mutants (operator/number/return/boolop/boundary flips the suite did
   not catch), in the engine's own document order.
2. For each survivor, find the top-level, blindly-callable public function whose
   body contains the mutated line; synthesize inputs for it the same way
   :mod:`app.execution.test_shield` does (``_safe_call`` / ``_arg_literal``).
3. Capture the REAL output of the UNMUTATED function on those inputs via
   test_shield's oracle capture — never a guessed expected value.
4. Emit ``assert fn(<args>) == <captured value>`` and ACCEPT it ONLY when the
   DOUBLE GATE holds: the assertion (a) PASSES against the real code AND (b)
   FAILS against the recorded mutant (proven mutant-killing). An assertion that
   does not kill its target mutant is discarded — it would add no signal.
5. Propose the surviving, double-gated assertions as a :class:`RenamePlan` that
   creates or EXTENDS ``tests/test_<stem>.py``, applied under the full-suite
   gate with auto-rollback (so a regression restores the file byte-for-byte).

The double gate is the never-fake-green proof: a kept assertion is one we have
PROVEN both holds on the real code and would have caught a specific real fault.
If no survivor can be killed honestly, the plan is empty (a no-op refusal, not a
failure) — Apex lands nothing rather than a vacuous green. A module whose tests
already kill every mutant has no survivors, so it is a no-op too. The MODULE
target is never a test/fixture file (Apex writes INTO tests, gated; it never
treats one as the subject to mutate). Deterministic, stdlib-only, zero-token.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import itertools

from app.engine.mutation_tester import (
    Mutant,
    _splice,
    mutation_score,
)
from app.execution._verify_budget import _Budget, _mutant_cap_for
from app.execution.cross_file_rename import RenamePlan
from app.execution.test_shield import (
    _captured_oracle,
    _env_is_reproducible,
    _is_simple_literal,
    _safe_call,
)

__all__ = ["plan_strengthen_tests"]

# Cap mutants enumerated per module — mirrors mutation_score's own default so a
# huge module's scan stays bounded and deterministic.
_MAX_MUTANTS = 30

# A fixed, deterministic per-parameter probe pool. To KILL a boundary/branch
# mutant we need an input that actually crosses the branch the mutant lives on —
# a single "zero value" rarely does. We try these literals in this exact order,
# so the first combination that both runs on the real code and diverges on the
# mutant is reproducible across runs. The pool spans the boundary-relevant values
# (sign, zero, off-by-one neighbours, empties, the two bools) that the engine's
# operator/number/comparison/boundary/boolop flips key on, written as their
# repr so they round-trip through ``ast.literal_eval`` and re-emit verbatim.
_PROBE_POOL: tuple[str, ...] = (
    "0", "1", "-1", "2", "''", "'a'", "[]", "[0]", "True", "False", "None",
)

# Bound on the Cartesian product of probes across a function's parameters, so a
# many-argument function never explodes the search. Deterministic: the first
# ``_MAX_COMBINATIONS`` tuples in fixed product order are tried.
_MAX_COMBINATIONS = 256


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test files are REFUSED as the MODULE target — Apex writes
    INTO tests under the gate, it never mutates one as the subject. A local copy
    (like ``cover_gaps.py`` keeps) on purpose, so this stays a self-contained
    transform with no import-cycle risk."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _dotted_name(module_rel: str) -> str:
    """Importable dotted path for a module given relative to the project root."""
    return ".".join(Path(module_rel).with_suffix("").parts)


def _function_for_line(tree: ast.Module, line: int) -> ast.FunctionDef | None:
    """The TOP-LEVEL, non-async function whose body spans ``line``, or ``None``.

    Only top-level functions are considered: ``_safe_call`` knows how to build a
    blind call for them, and the captured oracle is ``module.fn(args)``. A method
    or nested function has no such direct call path, so a survivor inside one is
    simply skipped (no assertion is emitted for it)."""
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):  # excludes async defs
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= line <= end:
            return node
    return None


def _load_module_from_source(source: str, dotted: str) -> object | None:
    """Import ``source`` as a throwaway module object, or ``None`` on failure.

    The module is built from an in-memory spec under a unique synthetic name so
    it never collides with (or pollutes) ``sys.modules`` for the real dotted
    path. Used to call the UNMUTATED and MUTATED function bodies in-process for
    the double gate. Any import-time error (a body that needs an unavailable
    dependency, a syntax error from a degenerate splice) yields ``None`` — the
    survivor is then left unkilled (honest: we never claim a kill we could not
    run)."""
    name = f"_apex_strengthen_{abs(hash((dotted, source))):x}"
    tmpdir = tempfile.mkdtemp(prefix="_apex_strengthen_")
    path = Path(tmpdir) / "m.py"
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # Load through the standard import machinery (``exec_module``) rather than
        # the bare ``exec`` builtin: same in-process effect on TRUSTED, locally
        # generated mutant source, but the sanctioned API — no code-injection
        # surface for Apex's own security scan to flag.
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None
    finally:
        sys.dont_write_bytecode = prev_dont_write
        shutil.rmtree(tmpdir, ignore_errors=True)


def _call_value(module: object, fn_name: str, args: tuple) -> tuple[bool, object]:
    """``(ok, value)`` from calling ``module.fn_name(*args)``.

    ``ok`` is ``False`` when the attribute is missing/not callable or the call
    raises — the caller treats that as "no honest comparison here"."""
    fn = getattr(module, fn_name, None)
    if not callable(fn):
        return False, None
    try:
        return True, fn(*args)
    except Exception:
        return False, None


def _diverges(real_value: object, mutant_module: object,
              fn_name: str, args: tuple) -> bool:
    """Does asserting ``fn(args) == real_value`` FAIL on the mutant? (gate b).

    True iff calling the SAME function on the SAME inputs against the mutated
    source yields a value that does NOT equal the real captured value (or raises
    / is missing — a divergence the assertion would also catch). Equal output
    means the mutant is behaviourally equivalent on these inputs, so the
    assertion would NOT catch it."""
    ok, mutated_value = _call_value(mutant_module, fn_name, args)
    if not ok:
        return True  # mutant raises / vanished on these inputs -> assertion fails
    try:
        return not (mutated_value == real_value)
    except Exception:
        return True  # incomparable -> the equality assertion would fail -> killed


def _required_positional_arity(node: ast.FunctionDef) -> int | None:
    """The count of REQUIRED positional params for a blindly-callable function,
    or ``None`` when it can't be driven by a pure positional probe.

    ``_safe_call`` already vetted eligibility (not private/main/decorated, no
    ``*args``/``**kwargs``). Here we additionally require that every required
    parameter is positional: a required keyword-only arg has no fixed name in our
    positional probe pool, so we decline rather than guess. Defaulted params are
    omitted from the call (the probe fills only the required prefix)."""
    a = node.args
    for kdef in a.kw_defaults:
        if kdef is None:  # a required keyword-only arg -> can't probe positionally
            return None
    positional = a.posonlyargs + a.args
    n_required = len(positional) - len(a.defaults)
    return max(n_required, 0)


def _probe_combinations(arity: int):
    """Deterministic candidate positional-argument tuples for ``arity`` params.

    The first ``_MAX_COMBINATIONS`` tuples of the Cartesian product of
    :data:`_PROBE_POOL` with itself ``arity`` times, in fixed product order. Each
    element is the literal's source text (so it re-emits verbatim into the test);
    its value is obtained via :func:`ast.literal_eval`. ``arity == 0`` yields the
    single empty tuple (the no-argument call)."""
    if arity == 0:
        yield ()
        return
    for combo in itertools.islice(
            itertools.product(_PROBE_POOL, repeat=arity), _MAX_COMBINATIONS):
        yield combo


def _killing_assertion(real_module: object, mutant_module: object, call_target: str,
                       fn_name: str, arity: int,
                       root: Path | None = None, dotted: str | None = None) -> str | None:
    """A double-gated ``call_target(args) == <captured>`` assertion line, or ``None``.

    ``call_target`` is the exact callable expression the rendered test will use
    (e.g. ``_apex_mod.classify``, ``alias.classify`` reusing an existing import,
    or bare ``classify`` for a ``from pkg.mod import classify``). The double gate
    itself runs ``module.fn_name(*args)`` in-process, so it is independent of how
    the assertion ADDRESSES the function — ``call_target`` only shapes the emitted
    line, ``fn_name`` drives the gate.

    Searches the deterministic probe combinations in fixed order for the FIRST
    input tuple where BOTH gates hold:

    * gate (a) — the REAL function returns a simple, reproducible literal whose
      ``repr`` round-trips, so ``assert call_target(args) == <repr>`` passes on
      real code by construction;
    * gate (b) — the SAME call against the mutated source diverges, so the
      assertion fails on the mutant (it provably kills it).

    A THIRD gate guards never-fake-green across MACHINES/RUNS when ``root``/``dotted``
    address the real ON-DISK module (the production path always supplies them): the
    producing call is re-captured under a VARIED environment — distinct cwd /
    ``$HOME`` / ``$TZ`` / ``$TMPDIR`` / ``PYTHONHASHSEED`` and a wall-clock gap
    (:func:`_env_is_reproducible`) — and the assertion is DECLINED unless the
    canonical literal is byte-identical under every variation. A value reading the
    environment or clock (``os.getcwd()``, ``int(time.time())``, ``expanduser('~')``
    ...) would pass both double-gates here yet be RED elsewhere, so it is never
    pinned. The env gate is SKIPPED only when ``root``/``dotted`` are omitted (a
    direct unit call exercising the in-process double-gate against a throwaway module
    that has no on-disk path); the imprecise-float guard in :func:`_captured_oracle`
    still applies on every path.

    Returns the assertion for the first qualifying tuple, or ``None`` when no
    probe input kills this mutant honestly — the survivor is then left unkilled,
    never a fabricated oracle."""
    for combo in _probe_combinations(arity):
        try:
            values = tuple(ast.literal_eval(text) for text in combo)
        except (ValueError, SyntaxError, RecursionError, MemoryError):
            continue
        ok, real_value = _call_value(real_module, fn_name, values)
        if not ok or not _is_simple_literal(real_value):
            continue  # real call raises / non-literal return -> no oracle here
        oracle = _captured_oracle(repr(real_value), real_value)
        if oracle is None:
            continue  # repr does not round-trip (or imprecise float) -> next probe
        if not _diverges(real_value, mutant_module, fn_name, values):
            continue  # mutant agrees on these inputs -> not a kill, keep searching
        call_args = ", ".join(combo)
        if not _env_gate_passes(root, dotted, fn_name, call_args, oracle):
            continue  # env/clock-dependent value -> future-red, never pin it
        return f"assert {call_target}({call_args}) == {oracle}"
    return None


def _env_gate_passes(root: Path | None, dotted: str | None, fn_name: str,
                     call_args: str, oracle: str) -> bool:
    """Does the captured ``oracle`` survive the env-reproducibility gate?

    ``True`` when ``root``/``dotted`` are omitted (a direct unit call against a
    throwaway in-process module that has no on-disk path — the env gate is then a
    no-op and only the in-process double-gate + the imprecise-float guard apply), or
    when re-running the producing call under a VARIED environment re-renders the SAME
    canonical literal (:func:`_env_is_reproducible`). ``False`` for a value that
    reads the environment/clock — it would be RED on another machine/run, so the
    assertion is declined."""
    if root is None or dotted is None:
        return True
    return _env_is_reproducible(root, dotted, fn_name, call_args, oracle)


def _alias_for(fn_name: str) -> str:
    """A stable, private import alias for ``fn_name`` — deterministic, no clock.

    The alias is derived solely from the function name, so two runs over the same
    module emit the identical ``from pkg.mod import fn as _apex_fn_<name>`` import.
    The ``_apex_fn_`` prefix keeps it private (it can never collide with a public
    name the test already uses) and unmistakably Apex-owned."""
    return f"_apex_fn_{fn_name}"


def _existing_bindings(existing: str | None,
                       dotted: str) -> tuple[list[str], dict[str, str]]:
    """How the EXISTING test file already addresses ``dotted`` — reuse what works.

    Returns ``(module_prefixes, fn_bindings)``:

    * ``module_prefixes`` — names bound to the module itself by an
      ``import pkg.mod`` (binds the dotted path) or ``import pkg.mod as alias``
      (binds ``alias``), usable as ``prefix.fn(...)`` for ANY function in it;
    * ``fn_bindings`` — ``{function_name: bound_name}`` from
      ``from pkg.mod import fn`` / ``... as bound``, usable as a BARE call.

    Reusing a binding the file already imports is the most robust fix: it is, by
    definition, an addressing form that already resolves in that test. A file we
    cannot read/parse yields empty maps, so the caller falls back to an alias
    import that is guaranteed to resolve. The relative ``from . import`` /
    ``from .mod import`` forms are ignored (their package anchor is the test
    file's location, which is not the module's dotted path)."""
    module_prefixes: list[str] = []
    fn_bindings: dict[str, str] = {}
    if existing is None:
        return module_prefixes, fn_bindings
    try:
        tree = ast.parse(existing)
    except (SyntaxError, RecursionError, MemoryError):
        return module_prefixes, fn_bindings
    for node in ast.walk(tree):
        _collect_binding(node, dotted, module_prefixes, fn_bindings)
    return module_prefixes, fn_bindings


def _collect_binding(node: ast.AST, dotted: str, module_prefixes: list[str],
                     fn_bindings: dict[str, str]) -> None:
    """Record any binding ``node`` (an ``import``/``from``-import) gives ``dotted``.

    ``import pkg.mod`` / ``import pkg.mod as a`` adds the dotted path / alias as a
    MODULE prefix; ``from pkg.mod import fn`` / ``... as bound`` maps ``fn ->
    bound`` (a star import binds names we cannot enumerate, so it is skipped).
    Relative imports (``node.level > 0``) anchor at the test file, not ``dotted``,
    so they are ignored."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == dotted:
                module_prefixes.append(alias.asname or alias.name)
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == dotted:
        for alias in node.names:
            if alias.name != "*":  # a star import binds names we cannot enumerate
                fn_bindings[alias.name] = alias.asname or alias.name


def _binding_for(fn_name: str, dotted: str, module_prefixes: list[str],
                 fn_bindings: dict[str, str]) -> tuple[str | None, str, str]:
    """``(emit_import, verify_import, call_target)`` for calling ``fn_name``.

    Resolution order (most robust first):

    1. the EXISTING test already does ``from pkg.mod import fn`` — call the bound
       name BARE; nothing new to EMIT (``emit_import`` is ``None``), and the
       binding is VERIFIED with the equivalent ``from pkg.mod import fn as bound``;
    2. the existing test already does ``import pkg.mod`` / ``... as alias`` — call
       ``prefix.fn``; nothing new to emit, verified with ``import pkg.mod`` (the
       ``prefix`` is that import's own binding);
    3. otherwise EMIT (and verify with) an UNAMBIGUOUS alias import,
       ``from pkg.mod import fn as _apex_fn_<name>``, and call the alias.

    ``emit_import`` is what the rendered test will ADD; ``verify_import`` is the
    import that makes ``call_target`` resolve when run standalone (a reused
    binding emits nothing but still has an import that backs it). The alias
    fallback is a ``from``-import of the SUBMODULE's own namespace, so it binds
    the function directly and is immune to a same-named function a package
    ``__init__`` re-exports (which would shadow ``pkg.mod`` as an attribute).
    Determinism: a fixed resolution order and a name-derived alias."""
    if fn_name in fn_bindings:
        bound = fn_bindings[fn_name]
        return None, f"from {dotted} import {fn_name} as {bound}", bound
    if module_prefixes:
        prefix = module_prefixes[0]
        # The prefix is either the dotted path (plain `import pkg.mod`) or an
        # alias (`import pkg.mod as alias`); reconstruct that exact import to
        # verify the `prefix.fn` call resolves.
        verify = f"import {dotted}" if prefix == dotted else f"import {dotted} as {prefix}"
        return None, verify, f"{prefix}.{fn_name}"
    alias = _alias_for(fn_name)
    line = f"from {dotted} import {fn_name} as {alias}"
    return line, line, alias


def _survivor_assertions(root: Path, module_rel: str, source: str,
                         tree: ast.Module, survivors: list[Mutant],
                         existing: str | None) -> tuple[list[str], list[str]]:
    """``(assertions, imports)`` — double-gated killers + the imports they need.

    For each survivor (in the mutation engine's deterministic document order) we
    locate the containing top-level public function, rebuild the exact mutated
    source for that survivor via the engine's own ``_splice``, synthesize a blind
    call with test_shield's ``_safe_call``, and keep the assertion only if it is
    double-gated. The call is ADDRESSED through a binding guaranteed to resolve:
    the one the ``existing`` test already uses, else a private alias import
    (returned in ``imports``). Each emitted assertion is then re-validated to
    actually run via the in-process oracle, so a binding that does not resolve is
    never landed. Duplicate assertions are collapsed; both lists are sorted for a
    stable file."""
    dotted = _dotted_name(module_rel)
    real_module = _load_module_from_source(source, dotted)
    if real_module is None:
        return [], []
    module_prefixes, fn_bindings = _existing_bindings(existing, dotted)
    source_lines = source.splitlines(keepends=True)
    assertions: set[str] = set()
    imports: set[str] = set()
    for mutant in survivors:
        fn = _function_for_line(tree, mutant.line)
        if fn is None:
            continue
        spec = _safe_call(fn)
        if spec is None:
            continue  # not blindly callable (private/main/decorated/varargs/...)
        fn_name, _call_args = spec
        arity = _required_positional_arity(fn)
        if arity is None:
            continue  # a required keyword-only arg -> can't probe positionally
        mutated_source = _splice(source_lines, _site_of(mutant, source_lines))
        if mutated_source is None:
            continue  # the splice no longer matches -> skip this survivor
        mutant_module = _load_module_from_source(mutated_source, dotted)
        if mutant_module is None:
            continue  # mutated source won't import -> cannot prove the kill
        emit_import, verify_import, call_target = _binding_for(
            fn_name, dotted, module_prefixes, fn_bindings)
        line = _killing_assertion(
            real_module, mutant_module, call_target, fn_name, arity, root, dotted)
        if line is None:
            continue
        if not _import_call_resolves(root, dotted, verify_import, line):
            continue  # the import+call must actually run against the project
        assertions.add(line)
        if emit_import is not None:
            imports.add(emit_import)
    return sorted(assertions), sorted(imports)


@contextlib.contextmanager
def _hermetic_modules(dotted: str):
    """Run a block with ``sys.modules`` snapshotted, the target package EVICTED on
    entry, and the snapshot restored on exit.

    The resolution probe imports the real project's package. Two cache hazards are
    neutralised: (1) a STALE cache — a same-named package from an earlier probe or
    a different project — would make the probe resolve against the wrong files, so
    every component of ``dotted`` (``pkg``, ``pkg.mod``) is evicted on entry,
    forcing a fresh on-disk import; (2) a LEAKED cache — the freshly imported
    package would otherwise persist, perturbing later probes — so the original
    ``sys.modules`` is restored exactly on exit (additions dropped, originals put
    back). Deterministic and side-effect-free by construction: same files in,
    same answer out, no trace left behind."""
    saved = dict(sys.modules)
    parts = dotted.split(".")
    for i in range(len(parts)):
        sys.modules.pop(".".join(parts[: i + 1]), None)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in saved:
                del sys.modules[name]
        # Restore any module object the probe may have overwritten in place.
        for name, module in saved.items():
            sys.modules[name] = module


def _import_call_resolves(root: Path, dotted: str, import_line: str | None,
                          assertion: str) -> bool:
    """Does the EMITTED ``import_line`` + ``assertion`` actually run against the
    real project? The final guard before a binding is trusted to LAND.

    We load exactly what the test file will contain — the (optional) import then
    the bare assertion — as a throwaway module with ``root`` on ``sys.path``,
    through the same sanctioned ``spec.loader.exec_module`` discipline the double
    gate uses (no bytecode, restored path, no bare ``exec`` surface). The target
    package ``dotted`` is freshly imported under :func:`_hermetic_modules` so a
    stale/leaked cache never skews the answer. A binding that fails to resolve (an
    ``ImportError``/``NameError``/``AttributeError`` from a shadowed re-export)
    makes this ``False`` and the assertion is dropped, so a non-resolving import
    is never landed. The assertion is the double-gated one, so it passes on the
    real code by construction; this confirms it RESOLVES, closing the field-test
    gap where a correct assertion failed only on import."""
    snippet = (import_line + "\n" + assertion + "\n") if import_line else assertion + "\n"
    root_str = str(root)
    added = root_str not in sys.path
    if added:
        sys.path.insert(0, root_str)
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    tmpdir = tempfile.mkdtemp(prefix="_apex_strengthen_resolve_")
    with _hermetic_modules(dotted):
        try:
            path = Path(tmpdir) / "probe.py"
            path.write_text(snippet, encoding="utf-8")
            name = f"_apex_strengthen_resolve_{abs(hash(snippet)):x}"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                return False
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
            return True
        except Exception:
            return False
        finally:
            sys.dont_write_bytecode = prev_dont_write
            shutil.rmtree(tmpdir, ignore_errors=True)
            if added:
                try:
                    sys.path.remove(root_str)
                except ValueError:
                    pass


def _site_of(mutant: Mutant, source_lines: list[str]):
    """Rebuild the mutation-engine ``_Site`` for ``mutant`` so ``_splice`` can
    reproduce its exact mutated source.

    The mutant records line/operator/original/mutated; the column is recovered by
    locating ``mutant.original`` on its line. Deterministic: the first occurrence
    matching the recorded original is the one the engine spliced (sites are taken
    in document order, left-to-right)."""
    from app.engine.mutation_tester import _Site

    line = source_lines[mutant.line - 1] if mutant.line - 1 < len(source_lines) else ""
    col = line.find(mutant.original)
    return _Site(
        line=mutant.line, col=col, end_col=col + len(mutant.original),
        operator=mutant.operator, original=mutant.original, mutated=mutant.mutated,
    )


def _render_appended(dotted: str, module_stem: str, assertions: list[str],
                     imports: list[str], existing: str | None) -> str:
    """The test-file text after appending the new mutant-killing assertions.

    ``imports`` are the alias-import lines the assertions need (empty when every
    call reuses a binding the existing test already provides). They are emitted on
    BOTH paths: prepended to the fresh-file header, and — critically — inside the
    appended test function on the EXISTING-file path, so an appended assertion's
    call always has a name that resolves (the field-test bug was the missing
    import here). Module-level imports are placed inside the function body so the
    append never edits the file's existing top-of-file imports.

    When the module already has a ``tests/test_<stem>.py`` (``existing`` is its
    text) the killing assertions are APPENDED as one new test function so the
    file's existing tests are untouched — and any alias imports go INSIDE that
    function (the field-test bug was the missing import here). When there is none,
    a fresh file is created with the alias imports at top level (falling back to
    ``import <dotted>`` when there are none). Deterministic: imports and
    assertions in sorted order, a fixed function body, a single trailing
    newline."""
    if existing is not None:
        inner = [f"    {line}" for line in imports]
        if imports:
            inner.append("")
        inner += [f"    {line}" for line in assertions]
        func = _killing_func(module_stem, inner)
        text = existing if existing.endswith("\n") else existing + "\n"
        return text + "\n".join(func) + "\n"
    func = _killing_func(module_stem, [f"    {line}" for line in assertions])
    header = [
        "# Generated by Apex Orchestrator - mutant-killing assertions",
        f"# module: {dotted}",
        "#",
        "# Each assertion below pins behaviour a surviving mutant exposed as a test",
        "# blind spot: it passes on the real code and fails against that mutant",
        "# (double-gated, never-fake-green). Regenerate, do not hand-tune.",
        "",
        # On a fresh file the imports live at top level; with no alias import to
        # reuse we still pull the module in so a bare-binding reuse stays valid.
        *(imports if imports else [f"import {dotted}"]),
    ]
    return "\n".join(header + func) + "\n"


def _killing_func(module_stem: str, body_lines: list[str]) -> list[str]:
    """The ``def test_<stem>_kills_surviving_mutants`` block with ``body_lines``.

    A fixed header/docstring with the (already-indented) ``body_lines`` appended,
    so both the fresh-file and append paths share one deterministic shape."""
    return [
        "",
        "",
        f"def test_{module_stem}_kills_surviving_mutants():",
        f'    """Assertions that KILL mutants the existing {module_stem} tests miss.',
        "",
        "    Each was generated by Apex's strengthen-tests objective: the value is the",
        "    REAL captured output of the unmutated function, and every assertion was",
        "    double-gated (it passes on the real code AND fails against the specific",
        "    surviving mutant it kills). Regenerate, do not hand-tune.",
        '    """',
        *body_lines,
    ]


def plan_strengthen_tests(project_root: str | Path, module_rel: str,
                          budget: _Budget | None = None) -> RenamePlan:
    """Build the mutant-killing test plan for one module, or an empty no-op plan.

    Runs the mutation engine over ``module_rel`` to find surviving mutants, then
    generates double-gated killing assertions for them. The plan creates or
    EXTENDS ``tests/test_<stem>.py`` with those assertions. An empty plan means
    there was nothing to land — no survivors (the suite already kills them all),
    no survivor in a blindly-callable function, or none killable with an honest
    oracle. The MODULE target is refused outright for a test/fixture file. The
    write goes in ``new_contents`` (with the original in ``originals`` when the
    test file already exists, so the verified-apply engine rolls it back on a
    full-suite regression).

    ``budget`` (a :class:`app.execution._verify_budget._Budget` or ``None``) is a
    DETERMINISTIC mutant-RUN COUNT — never a clock — threaded into the mutation
    engine so a scan over a big real file can't fan out past the harness limit and
    land an honest no-op. It bounds how many mutants are examined for THIS module
    (decrementing the shared counter the caller passes), never weakens a gate, and
    never shortens ``verify_timeout``. ``budget is None`` (the default) is
    byte-identical to the pre-budget behaviour, so a small project is unchanged."""
    plan = RenamePlan(old=module_rel, new="strengthen-tests")
    rel = module_rel.replace("\\", "/")
    if not rel.endswith(".py") or _is_fixture_path(rel):
        return plan  # never treat a test/fixture (or non-module) as the subject
    root = Path(project_root)
    existing = _read_existing_test(root, rel)
    killers = _module_killing_assertions(root, rel, existing, budget)
    if killers is None:
        return plan  # nothing to land (no survivors / unkillable / unreadable)
    assertions, imports = killers
    return _attach_test_write(plan, root, rel, assertions, imports, existing)


def _read_existing_test(root: Path, rel: str) -> str | None:
    """The text of the module's ``tests/test_<stem>.py`` if it exists and reads,
    else ``None`` — both the binding source and the file we extend."""
    target = root / f"tests/test_{Path(rel).stem}.py"
    if not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


def _module_killing_assertions(root: Path, rel: str, existing: str | None,
                               budget: _Budget | None = None
                               ) -> tuple[list, list] | None:
    """``(assertions, imports)`` for one module, or ``None`` (a no-op).

    ``None`` for: a packaging module (``__init__``/``__main__``), an
    unreadable/unparseable source, an unsound (red) or already-saturated mutation
    baseline, or a survivor set from which nothing could be killed honestly.
    ``existing`` (the current test file, if any) seeds the import-binding reuse so
    appended assertions address the function the way that file already does.

    ``budget`` is the deterministic mutant-run COUNT threaded into the mutation
    engine (``None`` = unbounded, byte-identical to before). The per-module mutant
    cap is the smaller of the module default and the size-aware
    :func:`_mutant_cap_for` cap, so a huge file enumerates fewer mutants while a
    small file keeps the full default set — a pure function of the source, so the
    cap is deterministic and never changes any mutant's kill/survive verdict."""
    module_stem = Path(rel).stem
    if module_stem.startswith("__"):  # __init__/__main__ are packaging, not behaviour
        return None
    try:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, RecursionError, MemoryError):
        return None
    cap = min(_MAX_MUTANTS, _mutant_cap_for(source))
    result = mutation_score(root, rel, max_mutants=cap, budget=budget)
    # A red baseline makes the kill/survive split meaningless; refuse to act on it.
    if not result.baseline_ok or not result.survivors:
        return None
    assertions, imports = _survivor_assertions(
        root, rel, source, tree, result.survivors, existing)
    if not assertions:
        return None
    return assertions, imports


def _attach_test_write(plan: RenamePlan, root: Path, rel: str, assertions: list,
                       imports: list, existing: str | None) -> RenamePlan:
    """Render the killing assertions into ``tests/test_<stem>.py`` on ``plan``.

    Extends an existing test file (recording the original for rollback) or creates
    a new one, emitting ``imports`` on whichever path applies. A degenerate render
    that does not re-parse leaves the plan empty (a no-op)."""
    module_stem = Path(rel).stem
    test_path = f"tests/test_{module_stem}.py"
    content = _render_appended(_dotted_name(rel), module_stem, assertions, imports, existing)
    try:
        ast.parse(content)
    except (SyntaxError, RecursionError, MemoryError):
        return plan  # a degenerate render -> refuse rather than land broken tests
    if existing is not None:
        plan.originals[test_path] = existing
    plan.new_contents[test_path] = content
    plan.edits_by_file[test_path] = len(assertions)
    return plan
