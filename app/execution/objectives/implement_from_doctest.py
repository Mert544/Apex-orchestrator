"""Self-registering objective: implement-from-doctest.

Fill a STUB's body FROM ITS OWN docstring ``>>>`` examples — the single biggest
white-space win on a HALF-FINISHED project. The author has already written the
contract as a worked example (``>>> double(3)`` -> ``6``) but no test file yet,
so :mod:`implement-stub <app.execution.objectives.implement_stub>` — which needs
*pinned pytest tests* — cannot serve it. This objective PROMOTES the docstring to
the PRIMARY spec: it synthesises a body, keeps it IFF every example PASSES (run as
a stdlib ``doctest`` oracle), and otherwise REFUSES. Never a guess, never a
fake-green, byte-for-byte rollback on failure.

ALL the heavy lifting is REUSED read-only from
:mod:`app.execution.stub_synthesis` — the stub detector (``find_stub_functions``),
the fixed template space + doctest-witness synthesis (``synthesize_doctest_body``,
the SAME synth ``implement-stub``'s doctest pass uses), the per-function doctest
verifier (``filled_source_passes_doctests``), and the ambiguity diagnosis
(``_ambiguity_diagnosis`` / ``render_ambiguity_reason``). This module adds NO new
template/verify logic; it names the docstring-PRIMARY path as a first-class develop
objective, builds the one-module plan, and registers itself.

The TRIGGER that keeps it DISTINCT from ``implement-stub``: a stub with at least
one enforceable ``>>>`` example AND **no pinned ``test_*.py`` file** — its
contract lives *only* in the docstring, the exact case ``implement-stub`` leaves
open. (A stub that already has a pinned test stays ``implement-stub``'s; this
objective never claims it, so the two never double-count the same fill.)

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` writes, verifies, and restores the file on any regression).
The doctest examples are the spec: a body is emitted ONLY after it already
reproduces every example; if no fixed template does, the objective REFUSES (lands
nothing) and — when the refusal is an AMBIGUITY (two templates pass the examples
but diverge off-example) — discloses WHY and HOW to fix it ("add a discriminating
example") through the plan's ``blockers`` channel. Test/fixture files are refused
outright. Deterministic, stdlib-only, zero-token, idempotent (a non-stub, or a
stub already filled, is untouched).

``expensive=True`` / ``scope_verify=True`` mirror ``implement-stub``: the apply
runs the project's tests per fill, and the baseline suite is legitimately RED while
the stub is unimplemented, so each fill is gated against its IMPACTED tests rather
than vetoed by an unrelated still-red module (the full suite stays the commit-time
backstop).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.stub_synthesis import (
    _ambiguity_diagnosis,
    fill_stub_body,
    filled_source_passes_doctests,
    find_stub_functions,
    has_enforceable_doctest_examples,
    pinned_test_files,
    pinned_test_nodes,
    render_ambiguity_reason,
    synthesize_doctest_body,
)


def plan_implement_from_doctest(project_root: str | Path,
                                module_rel: str) -> RenamePlan:
    """Build the implement-from-doctest plan for one module, or an empty no-op plan.

    Fills EVERY doctest-primary stub in ``module_rel`` — each stub whose contract
    is (only) its own ``>>>`` examples and whose body a fixed template can make
    reproduce them — in ONE atomic write, so a module of doctest-stubbed functions
    goes from all-stub to all-implemented together (and an example that calls a
    SIBLING resolves once the sibling is filled). A stub with no satisfiable
    template, no enforceable example, or an already-present pinned test file is left
    as-is; the others still land.

    An empty plan means nothing was implementable here — a no-op refusal, not a
    failure. Test/fixture files are refused outright. The single combined write goes
    in ``new_contents`` with the original in ``originals`` so the verified-apply
    engine can roll it back if the impacted tests regress. When the module's
    doctest-stubs were ALL refused, an AMBIGUOUS one discloses why through
    ``blockers``."""
    plan = RenamePlan(old=module_rel, new="implement-from-doctest")
    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    root = Path(project_root)
    try:
        original = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    if not _doctest_primary_stubs(original, root, module_rel):
        return plan  # nothing doctest-fillable here — no-op (idempotent)

    filled, filled_names = _fill_doctest_primary_stubs(root, module_rel, original)
    if filled is None or filled == original or not filled_names:
        _disclose_ambiguity(plan, root, module_rel, original)
        return plan  # every doctest-stub refused — honest empty plan (reason disclosed)

    _attach_fill(plan, root, module_rel, original, filled, filled_names)
    return plan


def _attach_fill(plan: RenamePlan, root: Path, module_rel: str, original: str,
                 filled: str, filled_names: set[str]) -> None:
    """Record the combined doctest-fill on ``plan`` — the original (for rollback),
    the filled source, the single-write edit count — and scope the apply gate to the
    impacted nodes. The one place the landing is attached, so the plan-population
    idiom lives in a single helper rather than inline at the call site."""
    plan.originals[module_rel] = original
    plan.new_contents[module_rel] = filled
    plan.edits_by_file[module_rel] = 1
    _scope_apply_gate(plan, root, module_rel, original, filled_names)


def _doctest_primary_stubs(source: str, root: Path,
                           module_rel: str) -> list:
    """The stubs in ``source`` whose contract is PRIMARILY their own docstring
    ``>>>`` examples — at least one enforceable example AND no pinned ``test_*.py``
    file. This is the trigger that keeps the objective DISTINCT from
    ``implement-stub`` (which owns a stub that already carries a pinned test): the
    docstring is the only spec, the exact white space this objective targets.

    Deterministic: stubs in :func:`find_stub_functions` source order. ``[]`` when no
    stub qualifies (a clean no-op signal for the planner and the scan)."""
    out = []
    for stub in find_stub_functions(source):
        if not has_enforceable_doctest_examples(source, stub):
            continue  # no example to derive a body from — not ours
        if pinned_test_files(root, module_rel, stub.name):
            continue  # a pinned test already pins it — implement-stub owns it
        out.append(stub)
    return out


def _fill_doctest_primary_stubs(root: Path, module_rel: str,
                                original: str) -> tuple[str | None, set[str]]:
    """Cumulatively synthesise a body for EVERY doctest-primary stub whose examples
    a fixed template reproduces, returning ``(filled_source, filled_names)`` — the
    full module source with all such stubs filled and the set that landed (or
    ``(None, set())`` when none was satisfiable). The names let the planner scope
    the apply gate.

    Each stub's body comes from :func:`synthesize_doctest_body` (the SAME synth +
    doctest-verify ``implement-stub``'s doctest pass uses), so the body is already
    verified against ``current`` by re-running the examples; it is then composed and
    DOUBLE-CHECKED with :func:`filled_source_passes_doctests` on the composed source
    (never-fake-green: a body that does not reproduce every example is never kept).

    Iterates to a FIXPOINT: a doctest example may call a SIBLING function, whose body
    must already be in place for the example to pass, so a freshly-filled sibling can
    unblock another's examples on the next pass — and because each fill is verified
    against the partially-filled ``current``, a stub only lands once every function
    its examples exercise is real. Nothing is written to disk — this is a pure
    in-memory derivation; the verified-apply engine performs the real write.
    Deterministic: stubs in source order, re-derived after each fill so shifted line
    spans stay correct."""
    current = original
    filled: set[str] = set()
    progress = True
    while progress:
        progress = False
        for stub in _doctest_primary_stubs(current, root, module_rel):
            if stub.name in filled:
                continue
            expr = synthesize_doctest_body(root, [], stub, current)
            if expr is None:
                continue  # no fixed template reproduces its examples — refuse it
            composed = fill_stub_body(current, stub, expr)
            if composed is None or composed == current:
                continue
            # Double-check on the COMPOSED source: the filled stub's own examples
            # must still all pass (a sibling fill could only help, never hurt, but
            # we re-run to keep the never-fake-green guarantee explicit and local).
            landed = _stub_named(composed, stub.name)
            if landed is None or not filled_source_passes_doctests(composed, landed):
                continue  # composed body does not reproduce the examples — skip
            current = composed
            filled.add(stub.name)
            progress = True
            break  # re-derive: this fill shifted later stubs' line spans
    return (current, filled) if filled else (None, filled)


def _stub_named(source: str, name: str):
    """The just-FILLED function ``name`` in ``source`` as a ``StubFunction`` carrying
    its current (name, lineno) identity, so its doctest examples can be re-run on the
    composed source. ``find_stub_functions`` only returns UNfilled stubs, so after a
    fill the function is no longer there — we rebuild the identity from the parsed
    tree instead. ``None`` when the source does not parse or the function is absent.

    Deterministic; reuses the same name+lineno identity the doctest layer keys on
    (matching :func:`stub_synthesis._stub_docstring`'s lookup)."""
    import ast

    from app.execution.stub_synthesis import _named_stub

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name):
            return _named_stub(name, node.lineno)
    return None


def _disclose_ambiguity(plan: RenamePlan, root: Path, module_rel: str,
                        original: str) -> None:
    """When this module's doctest-stubs were ALL refused, disclose WHY for each one
    refused specifically because its examples are AMBIGUOUS — and HOW to fix it (add
    a discriminating example).

    A stub Apex correctly REFUSES on ambiguity (>=2 competing template bodies satisfy
    every example but diverge off-example) otherwise lands nothing with no
    explanation. This rides the plan's EXISTING ``blockers`` channel — the same path
    ``implement-stub`` uses — which ``objective_compiler`` records into
    ``CompileResult.blocked`` (rendered under "Blocked"), so the reason reaches the
    buyer without a new cross-cutting surface.

    Purely additive and never changes WHAT lands: it is called ONLY on the
    genuinely-empty refusal branch (``new_contents`` is empty here), so a blocker
    cannot suppress a landing. ``_ambiguity_diagnosis`` is threaded with the module
    source so a DOCTEST contract's ambiguity is diagnosed exactly like a test-file
    one. One line per ambiguous stub, in source order; non-ambiguous refusals (no
    minable witness, unsatisfiable) add nothing. Deterministic: the reason is a pure
    function of the module bytes."""
    for stub in _doctest_primary_stubs(original, root, module_rel):
        diagnosis = _ambiguity_diagnosis(root, [], stub, original)
        if diagnosis is not None:
            plan.blockers.append(f"{stub.name}: {render_ambiguity_reason(diagnosis)}")


def _scope_apply_gate(plan: RenamePlan, root: Path, module_rel: str,
                      original: str, filled_names: set[str]) -> None:
    """Tell the apply gate which pinned nodes this fill makes green, and which
    pre-existing-red sibling nodes to deselect.

    A doctest-primary stub has NO pinned ``test_*.py`` node by definition (that is
    its trigger), so ``scoped_test_nodes`` is empty for the doctest stubs THEMSELVES
    — their contract is verified IN the plan derivation (the examples were re-run),
    not by a pytest node. We still scope the gate honestly: any stub that was PRESENT
    but NOT filled (a doctest stub no template satisfied, or a NON-doctest stub the
    module also holds) contributes its pinned nodes — if any — to
    ``scoped_excluded_nodes`` so a pre-existing-red sibling does not roll the landable
    doctest fill back. A node that survives is one a still-unfilled stub's red test
    owns; deselecting exactly those keeps every still-green impacted test running (a
    genuine regression is still caught). Deterministic: sorted. Both empty when
    nothing is discoverable, leaving the gate on its unchanged impacted scope."""
    unfilled = {s.name for s in find_stub_functions(original)} - filled_names
    excluded: set[str] = set()
    for name in unfilled:
        excluded.update(pinned_test_nodes(root, module_rel, name))
    # Only a TRUE node ID (``file::test``) can be deselected function-wise; a
    # whole-file fallback (no ``::``) is left in scope.
    deselectable = {n for n in excluded if "::" in n}
    plan.scoped_test_nodes = []
    plan.scoped_excluded_nodes = sorted(deselectable)


def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (a local copy on purpose: this objective stays self-contained). A
    ``.pyi`` stub file is refused too: every body is an interface ``...``, never an
    implementable doctest target (mirrors the implement-stub twin's guard)."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py" or name.endswith(".pyi")
    )


def _modules(project_root: str | Path) -> list[str]:
    """Own modules that hold at least one doctest-primary fillable stub — the
    implement-from-doctest fitness/move scan, made CHEAP.

    Mirrors ``implement-stub``'s scan discipline: an IN-PROCESS estimate (no pytest)
    that counts a module when any of its stubs has at least one enforceable ``>>>``
    example, NO pinned test file, and a fixed template whose body reproduces every
    example (``synthesize_doctest_body`` is non-None — the SAME synth + doctest-verify
    the apply path uses). This never under-counts a landable doctest stub (the apply
    lands exactly the set the scan offered); a stub the verify-on-apply later rejects
    simply no-ops at apply.

    Deterministic; fixed source-order traversal. Test/fixture modules are skipped by
    ``_own_modules``'s own filtering and the per-stub ``_is_fixture_path`` guard."""
    from app.engine.objective_compiler import _own_modules

    root = Path(project_root)
    out: list[str] = []
    for rel, src in _own_modules(project_root):
        if _is_fixture_path(rel):
            continue
        for stub in _doctest_primary_stubs(src, root, rel):
            if synthesize_doctest_body(root, [], stub, src) is not None:
                out.append(rel)
                break
    return out


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still hold a doctest-fillable stub.

    Fillable = a doctest-primary stub whose ``>>>`` examples a fixed template
    reproduces. A stub with no example, an already-pinned test, or an unsatisfiable
    contract does NOT count (we refuse to touch it), so it never appears as remaining
    debt — an honest measure. Counted by the CHEAP in-process estimate
    (:func:`_modules`); the verify-on-apply still governs what actually lands."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="implement_from_doctest",
        target=f"{rel}:implement-from-doctest",
        description=f"implement a doctest-specified stub in {rel}",
        build_plan=lambda r=rel: plan_implement_from_doctest(project_root, r),
    ) for rel in _modules(project_root)]


# The fitness/move SCAN is cheap (an in-process estimate, no pytest — see
# `_modules`), but the APPLY runs the project's tests per fill to LAND it under the
# impact-scoped gate, so the objective is flagged `expensive`: the fast plan/ascend
# board skips it and it runs explicitly via
# `apex develop --objective implement-from-doctest`. scope_verify=True: gate each
# fill against the IMPACTED tests, not the full suite — on a multi-module project an
# unfilled stub elsewhere leaves the baseline suite legitimately RED, and a
# full-suite gate would roll a correct per-module fill back. The doctest examples
# are the per-fill contract (verified in the plan derivation); the full suite stays
# the commit-time backstop.
register(ObjectiveSpec(name="implement-from-doctest", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
