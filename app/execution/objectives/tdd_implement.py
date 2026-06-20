"""Self-registering objective: tdd-implement — write the function a RED test calls.

The everyday TDD inner loop a budget-limited student or team otherwise pays an
LLM for, message by message: "I wrote the test — now write the code." Given a
FAILING test that calls ``mod.foo(...)`` where ``foo`` does **not exist yet**
(or exists with the wrong arity), this objective synthesises a real
``def foo(...)`` in the correct module so the RED test goes GREEN — landing
working code only when the full suite verifies it.

This is DISTINCT from every neighbouring objective:

* ``implement-stub`` fills the body of a stub that ALREADY EXISTS
  (``NotImplementedError`` / ``...`` / ``# TODO``). Here the function is
  ENTIRELY ABSENT — the test fails with an import/attribute/name error, not an
  assertion — so there is no stub to fill until this objective creates one.
* ``cover-gaps`` / ``test_shield`` GENERATE tests for code. Here the test is the
  given (the human wrote it); we generate the *code*.
* ``dedup-*`` collapse duplication. Unrelated.

The pipeline is **detect → locate → infer → insert → synthesise → gate**:

1. **DETECT** — run the project's tests, collect failures, and keep ONLY the
   deterministically-attributable missing-symbol shapes: ``AttributeError:
   module 'x' has no attribute 'foo'``, ``NameError: name 'foo' is not
   defined``, ``ImportError: cannot import name 'foo'``, or a ``TypeError``
   arity mismatch on an existing ``foo``. Anything else — an assertion failure
   on existing code, an unattributable error — is REFUSED (out of scope, honest).
2. **LOCATE** — find the target module from the RED test's own import statement
   (the reverse of the test↔module pinning).
3. **INFER** — read the call sites in the RED test to recover the positional
   arity and any keyword names the new function must accept.
4. **INSERT** — splice a ``def foo(<inferred params>): raise
   NotImplementedError`` stub into the target module at a valid top-level
   position (the result is re-``ast.parse``-d), turning the absent-function case
   into the already-solved stub case.
5. **SYNTHESISE** — delegate the body to the EXISTING, overfit-guarded
   :func:`app.execution.stub_synthesis.synthesize_stub_body`, with the RED test
   as the spec — zero new synthesis logic, so the same fixed template order,
   the same two-distinct-tuples constant guard, the same determinism.
6. **GATE** — the develop engine applies the plan under the FULL suite with
   byte-for-byte auto-rollback. Success = the previously-RED test now passes AND
   no previously-green test regresses. If no template makes it green, NOTHING
   lands (honest refusal). The intentionally-RED baseline on the target test is
   exactly the point: we verify that specific test flips RED→GREEN.

Deterministic (fixed template order, AST-only, no clock/random — same project,
byte-identical function), offline, stdlib-only, zero-token. Idempotent: a test
already green leaves nothing to do. Test/fixture files are refused as WRITE
targets — we write into the MODULE under test, never the test.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.stub_synthesis import (
    _is_test_or_fixture,
    find_stub_functions,
    pinned_test_files,
    synthesize_stub_body,
)
from app.skills.execution.run_tests import RunTestsSkill

__all__ = ["plan_tdd_implement", "MissingSymbol", "detect_missing_symbols"]


# --- the missing-symbol shapes (deterministic attribution) -------------------

# Each pattern captures the bare symbol name the RED test referenced but that the
# target module does not define. Only these four shapes are in scope; anything
# else is an assertion failure or an unattributable error and is REFUSED.
_ATTR_RE = re.compile(
    r"AttributeError:\s*module\s*'(?P<mod>[^']+)'\s*has no attribute\s*'(?P<name>\w+)'")
_NAME_RE = re.compile(r"NameError:\s*name\s*'(?P<name>\w+)'\s*is not defined")
_IMPORT_RE = re.compile(r"ImportError:\s*cannot import name\s*'(?P<name>\w+)'")
# A TypeError arity mismatch on an EXISTING function: "foo() takes 1 positional
# argument but 2 were given" / "missing 1 required positional argument".
_ARITY_RE = re.compile(
    r"TypeError:\s*(?P<name>\w+)\(\)\s*(?:takes|missing)\b[^\n]*"
    r"(?:positional argument|argument)")


@dataclass(frozen=True)
class MissingSymbol:
    """One deterministically-attributable missing function a RED test demands.

    ``name`` is the absent (or wrong-arity) function; ``module_rel`` is the
    project module that should define it (located from the RED test's import);
    ``test_files`` are the pinned RED tests that form the spec; ``shape`` records
    which error attributed it (for the move description and audit)."""

    name: str
    module_rel: str
    test_files: tuple[str, ...]
    shape: str


# --- detection ---------------------------------------------------------------

def _run_suite_output(root: Path, runner: RunTestsSkill) -> str:
    """Run the project's full suite once and return the combined stdout+stderr.

    Empty string when there is no detectable suite (nothing to attribute), so the
    objective offers no moves rather than guessing."""
    summary = runner.run(str(root))
    if not summary.commands:
        return ""
    parts: list[str] = []
    for result in summary.results:
        parts.append(str(result.get("stdout", "")))
        parts.append(str(result.get("stderr", "")))
    return "\n".join(parts)


def _attributed_names(output: str) -> list[tuple[str, str]]:
    """Every ``(name, shape)`` the suite output attributes to a missing symbol,
    in first-seen order with duplicates dropped. Only the four in-scope shapes
    are recognised; an assertion failure contributes nothing (refused)."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for line in output.splitlines():
        for shape, rx in (("attribute", _ATTR_RE), ("import", _IMPORT_RE),
                          ("name", _NAME_RE), ("arity", _ARITY_RE)):
            m = rx.search(line)
            if m and m.group("name") not in seen:
                seen.add(m.group("name"))
                out.append((m.group("name"), shape))
    return out


def _test_imports_module(text: str, dotted: str) -> bool:
    """True when test source ``text`` imports the module ``dotted`` — either by
    dotted reference (``import x`` / ``x.foo``) or ``from pkg import stem``. This
    is the same import-linkage shape ``pinned_test_files`` uses, applied in
    reverse to LOCATE the target module a RED test is exercising."""
    parent, _, stem = dotted.rpartition(".")
    dotted_re = re.compile(re.escape(dotted) + r"(?![A-Za-z0-9_])")
    if dotted_re.search(text):
        return True
    if parent:
        from_re = re.compile(r"from\s+" + re.escape(parent) + r"\s+import\b[^\n()]*\b"
                             + re.escape(stem) + r"\b")
        if from_re.search(text):
            return True
    return False


def _candidate_modules(root: Path) -> list[str]:
    """The project's own non-fixture modules (rel paths), deterministically
    ordered. Used to locate which module a RED test's import resolves to."""
    from app.engine.objective_compiler import _own_modules

    return sorted(rel for rel, _src in _own_modules(root))


def _locate_module(root: Path, name: str) -> tuple[str, tuple[str, ...]] | None:
    """Find the single project module a RED test demands ``name`` from.

    For each own module, the RED tests that import that module AND reference
    ``name`` are its pinned spec (``pinned_test_files``). The target is the
    module whose pinned RED tests also IMPORT it — i.e. the test really exercises
    this module's surface. Returns ``(module_rel, test_files)`` or ``None`` when
    no module is unambiguously the target (refuse rather than guess)."""
    matches: list[tuple[str, tuple[str, ...]]] = []
    for module_rel in _candidate_modules(root):
        dotted = (module_rel[:-3].replace("/", ".")
                  if module_rel.endswith(".py") else module_rel)
        pinned = pinned_test_files(root, module_rel, name)
        importing = [
            rel for rel in pinned
            if _test_imports_module(
                _read(root / rel), dotted)
        ]
        if importing:
            matches.append((module_rel, tuple(importing)))
    # Exactly one module is the target. Ambiguity (two modules both plausibly the
    # home) is refused — a non-guessing objective never picks arbitrarily.
    if len(matches) == 1:
        return matches[0]
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_missing_symbols(root: str | Path,
                           runner: RunTestsSkill | None = None) -> list[MissingSymbol]:
    """Run the suite and return every deterministically-attributable missing
    function it demands, each located to its target module and pinned RED tests.

    A symbol is kept ONLY when (a) one of the four in-scope error shapes
    attributed it, (b) it locates to exactly one project module, and (c) that
    module does not already define it as a non-stub (idempotence — an
    already-implemented or already-green symbol yields nothing). Deterministic:
    suite output scanned in line order, modules in sorted order."""
    root = Path(root)
    runner = runner or RunTestsSkill()
    output = _run_suite_output(root, runner)
    if not output:
        return []
    out: list[MissingSymbol] = []
    for name, shape in _attributed_names(output):
        located = _locate_module(root, name)
        if located is None:
            continue
        module_rel, test_files = located
        if _already_defined(root / module_rel, name, shape):
            continue
        out.append(MissingSymbol(name=name, module_rel=module_rel,
                                 test_files=test_files, shape=shape))
    return out


def _already_defined(module_path: Path, name: str, shape: str) -> bool:
    """True when ``name`` is already a real (non-stub) top-level function in the
    module — so there is nothing to create (idempotence).

    For an arity-mismatch shape the function DOES exist (that is the whole
    point); we still let it through so its signature can be widened, so this
    returns False for that shape unless the symbol is genuinely absent."""
    source = _read(module_path)
    if not source:
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    defined = any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        for n in tree.body)
    if shape == "arity":
        # Existing-but-wrong-arity: out of the simple missing-symbol scope this
        # objective lands (re-shaping a real signature risks changing behaviour),
        # so treat an existing function as "already defined" → refuse.
        return defined
    return defined


# --- signature inference (from the RED test's call sites) --------------------

def _infer_signature(root: Path, name: str, test_files: tuple[str, ...]) -> str | None:
    """Infer the parameter list ``def name(...)`` needs from the call sites in
    the RED tests: the maximum positional arity seen, plus any keyword argument
    names. Returns the comma-joined parameter source (e.g. ``a, b`` or ``x,
    *, key``), or ``None`` when no call site is found.

    Deterministic and AST-only: parameters are named ``a0, a1, ...`` for the
    positionals (so the synthesiser's positional templates apply), and each
    keyword keeps its own name. Same tests → byte-identical signature."""
    max_pos = 0
    kwargs: list[str] = []
    found = False
    for rel in test_files:
        for call in _calls_to(_read(root / rel), name):
            found = True
            pos = sum(1 for a in call.args if not isinstance(a, ast.Starred))
            max_pos = max(max_pos, pos)
            for kw in call.keywords:
                if kw.arg and kw.arg not in kwargs:
                    kwargs.append(kw.arg)
    if not found:
        return None
    params = [f"a{i}" for i in range(max_pos)]
    if kwargs:
        params.append("*")
        params.extend(kwargs)
    return ", ".join(params)


def _calls_to(text: str, name: str) -> list[ast.Call]:
    """Every call node in ``text`` whose target names ``name`` — ``name(...)`` or
    ``mod.name(...)``. ``[]`` on a syntax error (a malformed test contributes no
    inference signal)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _call_targets(n.func, name)]


def _call_targets(func: ast.expr, name: str) -> bool:
    """True when a call's ``func`` names ``name`` — either ``name(...)`` (bare)
    or ``mod.name(...)`` (attribute access). Both are how a RED test reaches the
    not-yet-written function."""
    if isinstance(func, ast.Name):
        return func.id == name
    if isinstance(func, ast.Attribute):
        return func.attr == name
    return False


# --- stub insertion ----------------------------------------------------------

def _insert_stub(source: str, name: str, params: str) -> str | None:
    """Append a ``def name(params): raise NotImplementedError`` stub at the end
    of the module's top level and return the new source, or ``None`` if the
    result does not parse.

    Appending keeps every existing line span byte-for-byte unchanged (so the
    rest of the module is untouched) and is always a valid top-level position.
    The inserted stub then looks exactly like the case ``implement-stub``
    already handles, so the existing synthesiser takes over from here."""
    body = "\n\n\ndef " + name + "(" + params + "):\n    raise NotImplementedError\n"
    sep = "" if source.endswith("\n") or source == "" else "\n"
    candidate = source + sep + body
    try:
        ast.parse(candidate)
    except (SyntaxError, ValueError):
        return None
    return candidate


# --- the plan ----------------------------------------------------------------

def plan_tdd_implement(project_root: str | Path, missing: MissingSymbol,
                       runner: RunTestsSkill | None = None) -> RenamePlan:
    """Build the create-the-missing-function plan for ONE attributed RED test, or
    an empty no-op plan (an honest refusal).

    Insert a stub for ``missing.name`` into its target module, then delegate the
    body to :func:`synthesize_stub_body` against the RED tests as the spec. The
    plan lands the full new module source in ``new_contents`` (original in
    ``originals``), so the verified-apply engine runs the FULL suite and rolls it
    back byte-for-byte if any test regresses. An empty plan means no fixed
    template made the RED test green — nothing is landed (never-fake-green)."""
    plan = RenamePlan(old=missing.module_rel, new="tdd-implement")
    module_rel = missing.module_rel
    if _is_test_or_fixture(module_rel):
        return plan  # never write into a test/fixture file
    root = Path(project_root)
    target = root / module_rel
    original = _read(target)
    if not original and not target.exists():
        return plan  # unknown / unreadable target — no-op

    params = _infer_signature(root, missing.name, missing.test_files)
    if params is None:
        return plan  # no call site to infer from — refuse

    stubbed = _insert_stub(original, missing.name, params)
    if stubbed is None:
        return plan  # the insertion would not parse — refuse

    stub = _new_stub(stubbed, missing.name)
    if stub is None:
        return plan  # the inserted def isn't a recognised stub — refuse

    # Write the stubbed source so the synthesiser probes against it, then restore.
    runner = runner or RunTestsSkill()
    try:
        target.write_text(stubbed, encoding="utf-8")
        filled = synthesize_stub_body(root, module_rel, stub,
                                      list(missing.test_files), runner)
    finally:
        if original or target.exists():
            target.write_text(original, encoding="utf-8")
    landed = filled is not None and filled != original
    if landed:
        # no template satisfying the RED test → ``filled`` is None/unchanged and we
        # fall through with an empty plan (land nothing, never a fake-green).
        _record_landed(plan, module_rel, original, filled)
    return plan


def _record_landed(plan: RenamePlan, module_rel: str, original: str,
                   filled: str) -> None:
    """Stamp the verified-apply engine's inputs for ONE landed module onto
    ``plan``: the original (for rollback), the new full source, and the edit
    count. Mutates ``plan`` in place — the planner returns it once populated."""
    plan.originals[module_rel] = original
    plan.new_contents[module_rel] = filled
    plan.edits_by_file[module_rel] = 1


def _new_stub(stubbed_source: str, name: str):
    """The :class:`StubFunction` for the just-inserted ``name`` stub, or ``None``
    if it isn't present as a stub (shouldn't happen — the insertion writes a
    canonical ``raise NotImplementedError`` body)."""
    for stub in find_stub_functions(stubbed_source):
        if stub.name == name and not stub.is_method:
            return stub
    return None


# --- registry wiring ---------------------------------------------------------

def _missing(project_root: str | Path) -> list[MissingSymbol]:
    """The attributed missing symbols whose RED test a fixed template can satisfy
    — i.e. ``plan_tdd_implement`` would actually land a function. A symbol whose
    contract no template fits does NOT count (we refuse to touch it), so it never
    shows up as remaining debt — an honest measure."""
    root = Path(project_root)
    out: list[MissingSymbol] = []
    for ms in detect_missing_symbols(root):
        if plan_tdd_implement(root, ms).new_contents:
            out.append(ms)
    return out


def fitness(project_root: str | Path) -> float:
    """Fitness = how many RED tests still demand a function this objective can
    deterministically synthesise. 0 means no implementable missing-symbol failure
    remains."""
    return float(len(_missing(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="tdd_implement",
        target=f"{ms.module_rel}:{ms.name}",
        description=f"synthesize {ms.name}() in {ms.module_rel} to make its RED test green",
        build_plan=lambda m=ms: plan_tdd_implement(root, m),
    ) for ms in _missing(root)]


# Detection runs the project's full suite (to harvest failures) and then probes
# fixed templates per candidate — heavyweight — so flag it expensive: the fast
# plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective tdd-implement`.
# scope_verify=True: gate each synthesized function against the IMPACTED tests,
# not the full suite. On a multi-module project several modules can each have a
# RED test demanding a not-yet-written function, so the baseline suite is
# legitimately RED; making module A's RED test green must not be vetoed (rolled
# back) by an unrelated module B's still-RED test. Impact-scoping runs only A's
# real importing tests; the full suite stays the commit-time backstop.
register(ObjectiveSpec(name="tdd-implement", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
