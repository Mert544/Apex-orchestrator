"""Self-registering objective: implement-stub.

The single highest-value concrete contribution for a budget-limited student:
take a function that is a STUB (``raise NotImplementedError``, a bare
``...``/``pass`` body, or empty-with-``# TODO: implement``) whose contract is
ALREADY pinned by the project's tests, and DETERMINISTICALLY synthesise a body
that makes ALL of that function's tests pass — landing real, working code.

This is the gap every other objective leaves open: they make EXISTING code
cleaner; this makes UNFINISHED code finished. The synthesis logic (stub
detection, pinned-test discovery, the fixed template space, and the inner
per-function gate) lives in :mod:`app.execution.stub_synthesis`; this module
names it as a develop objective, builds the one-module plan, and registers
itself with the develop registry.

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` runs the FULL suite and restores the file on any
regression). The tests are the spec: a body is emitted ONLY after it already
passes the function's pinned tests; if no fixed template passes, the objective
REFUSES (lands nothing) — never a guess, never a fake-green. Test/fixture files
are refused outright. Deterministic, stdlib-only, zero-token, idempotent (a
non-stub is untouched).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.stub_synthesis import (
    _purge_pyc,
    fill_stub_body,
    find_stub_functions,
    module_has_fillable_stub,
    pinned_test_files,
    pinned_test_nodes,
    synthesize_expr_from_witnesses,
    synthesize_stub_body,
)
from app.skills.execution.run_tests import RunTestsSkill


def plan_implement_stub(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the implement-the-stubs plan for one module, or an empty no-op plan.

    Implements EVERY convertible stub in ``module_rel`` in ONE atomic write: each
    stub whose own pinned tests a fixed template can satisfy is filled, so the
    file goes from all-stub to all-implemented together. This is what breaks the
    same-module sibling deadlock — when two stubs share a module, implementing
    just one is rolled back because the other's test is still red under the
    impact-scoped gate; filling them together lets every module stub test pass at
    once. A stub with no satisfiable template (or no pinned tests) is left as-is;
    the others still land.

    An empty plan means nothing was implementable here — a no-op refusal, not a
    failure. Test/fixture files are refused outright. The single combined write
    goes in ``new_contents`` with the original in ``originals`` so the
    verified-apply engine can roll it back if the full suite regresses."""
    plan = RenamePlan(old=module_rel, new="implement-stub")
    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    root = Path(project_root)
    try:
        original = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    if not find_stub_functions(original):
        return plan  # nothing unfinished here — no-op (idempotent)

    filled, filled_names = _fill_all_stubs(root, module_rel, original)
    if filled is None or filled == original:
        return plan  # every stub refused — honest empty plan

    plan.originals[module_rel] = original
    plan.new_contents[module_rel] = filled
    plan.edits_by_file[module_rel] = 1
    _scope_apply_gate(plan, root, module_rel, original, filled_names)
    return plan


def _scope_apply_gate(plan: RenamePlan, root: Path, module_rel: str,
                      original: str, filled_names: set[str]) -> None:
    """Tell the apply gate which pinned nodes this fill makes green, and which
    pre-existing-red sibling nodes to deselect.

    ``scoped_test_nodes``: the sorted union of pinned-test NODE IDs
    (``file::test_x``) for ONLY the stubs this plan actually filled — the tests
    that genuinely pass after the fill (transparency + never-fake-green: each
    landed stub is grounded in its OWN real tests).

    ``scoped_excluded_nodes``: the pinned nodes of every stub that was PRESENT in
    the module but NOT filled (unsynthesizable, or no spec) — i.e. nodes that were
    red BEFORE the change and the fill doesn't worsen. The gate deselects exactly
    these from the whole impacted files, so an unsynthesizable sibling no longer
    rolls the landable fill back end-to-end, while every still-green impacted test
    keeps running (a genuine regression is still caught). A node naming BOTH a
    filled and an unfilled stub is kept (never deselect a node a landed stub must
    pass). Deterministic: sorted. Both empty when nothing is discoverable, leaving
    the gate on its unchanged whole-file impacted-scope."""
    included: set[str] = set()
    for name in filled_names:
        included.update(pinned_test_nodes(root, module_rel, name))
    unfilled = {s.name for s in find_stub_functions(original)} - filled_names
    excluded: set[str] = set()
    for name in unfilled:
        excluded.update(pinned_test_nodes(root, module_rel, name))
    # Only deselect TRUE node IDs (``file::test``) of an unfilled sibling, and
    # never one a filled stub depends on (``excluded - included``). pytest can
    # deselect a single function from a shared file while its sibling functions
    # still run, which is exactly the same-file deadlock fix. A whole-file
    # fallback (no ``::``) is left in scope — it can't be deselected node-wise.
    deselectable = {n for n in (excluded - included) if "::" in n}
    plan.scoped_test_nodes = sorted(included)
    plan.scoped_excluded_nodes = sorted(deselectable)


def _fill_all_stubs(root: Path, module_rel: str,
                    original: str) -> tuple[str | None, set[str]]:
    """Cumulatively synthesize a body for EVERY satisfiable stub in the module,
    returning ``(filled_source, filled_names)`` — the full module source with all
    satisfiable stubs filled and the set of stub names that landed (or
    ``(None, set())`` when none was satisfiable). The names let the planner scope
    the apply gate to exactly those stubs' pinned tests.

    Each stub is synthesized against the *current* (partially-filled) source on
    disk, so an already-filled sibling's body is in place while the next stub's
    pinned tests are probed — that is what lets a per-module batch pass together.
    Sibling stubs are pinned by SEPARATE test files in the simple case, but they
    may share one test file too (a single ``test_arith.py`` asserting both
    ``add`` and ``mul``); there, neither stub's pinned file goes green until the
    OTHER is also filled. So we iterate to a FIXPOINT: each pass fills whatever
    became satisfiable now (a freshly-filled sibling can unblock a shared test
    file on the next pass), stopping when a pass lands nothing more.

    Two passes, fast first:

    1. **Independent in-process synthesis** determines each stub's body from ITS
       OWN ``func(args) == expected`` witnesses, evaluated in-process with no
       pytest, composes them all, and verifies the UNION of pinned tests passes
       ONCE. This resolves the MUTUAL case (one test file asserts both ``add`` and
       ``mul``, so neither file greens until BOTH are filled) with a single suite
       run instead of a per-candidate probe storm — and never coordinate-descends
       from a passthrough seed, which deadlocked when two stubs needed different
       bodies. Only stubs whose own witnesses a template matches in-process land
       here; the union is the honesty gate (never-fake-green).

    2. **pytest-gated fixpoint** for whatever the in-process pass could not
       determine (recursion bodies that can't be eval'd in-process, or witnesses
       that aren't simple literals): each remaining stub is synthesized against
       the *current* (partially-filled) source, iterating to a fixpoint so a
       freshly-filled sibling can unblock a shared file on the next pass.

    The on-disk file is always restored to ``original`` before returning, so the
    scan leaves the tree byte-for-byte unchanged (the verified-apply engine, not
    this planner, performs the real write). Deterministic: stubs are taken in the
    fixed source order :func:`find_stub_functions` returns, re-derived after each
    fill so shifted line spans stay correct."""
    target = root / module_rel
    runner = RunTestsSkill()
    current = original
    filled: set[str] = set()
    try:
        # Pass 1 (fast): independent per-witness synthesis + one union verify.
        current = _resolve_mutual_stubs(root, module_rel, current, filled, runner)
        # Pass 2: pytest-gated fixpoint for stubs in-process eval can't determine.
        progress = True
        while progress:
            progress = False
            for stub in find_stub_functions(current):
                if stub.name in filled:
                    continue
                tests = pinned_test_files(root, module_rel, stub.name)
                if not tests:
                    continue  # no spec to satisfy — leave this stub as-is
                # Probe against the current (partially-filled) source: write it so
                # an already-filled sibling is present while this stub is gated.
                target.write_text(current, encoding="utf-8")
                new_source = synthesize_stub_body(root, module_rel, stub, tests)
                if new_source is None or new_source == current:
                    continue  # no template passes YET — retry next fixpoint pass
                current = new_source
                filled.add(stub.name)
                progress = True
                break  # re-derive: this fill shifted later stubs' line spans
    finally:
        target.write_text(original, encoding="utf-8")
    return (current, filled) if filled else (None, filled)


def _resolve_mutual_stubs(root: Path, module_rel: str, current: str,
                          filled: set[str], runner: RunTestsSkill) -> str:
    """Fill the stubs the cheap fixpoint left pending because their pinned tests
    share a file and so stay red until every sibling is filled too.

    Each pending stub's body is synthesized INDEPENDENTLY from its OWN pinned
    witnesses — ``func(args) == expected`` assertions evaluated in-process, with
    no coordination from a passthrough seed. (Coordinate descent deadlocked here:
    when two stubs need DIFFERENT bodies, no single move greens the shared file,
    so it never left the seed.) The independently-determined bodies are composed
    and the UNION of all pinned tests is verified ONCE: only when that union is
    green do they land (never-fake-green). A stub whose own witnesses no template
    satisfies is dropped — the others still land. ``filled`` is updated in place."""
    assignment = _independent_assignment(root, module_rel, current, filled)
    if not assignment:
        return current

    composed = _compose(current, assignment)
    if composed is None:
        return current
    tests = _union_node_ids(root, module_rel, assignment)
    if not tests:
        return current
    if not _union_passes(root, module_rel, composed, tests, runner):
        return current  # union not green — refuse, land nothing for these stubs
    filled.update(assignment)
    return composed


def _independent_assignment(root: Path, module_rel: str, current: str,
                            filled: set[str]) -> dict[str, str]:
    """For each still-pending stub, the body its OWN witnesses determine (the
    first fixed-order candidate that matches every ``func(args) == expected``
    assertion in-process), or nothing when no template fits. Deterministic: the
    stubs are taken in source order, each synthesized from its own assertions
    independently of the others."""
    assignment: dict[str, str] = {}
    for stub in find_stub_functions(current):
        if stub.name in filled:
            continue
        tests = pinned_test_files(root, module_rel, stub.name)
        if not tests:
            continue  # no spec — leave as-is
        expr = synthesize_expr_from_witnesses(root, tests, stub)
        if expr is not None:
            assignment[stub.name] = expr
    return assignment


def _union_node_ids(root: Path, module_rel: str,
                    assignment: dict[str, str]) -> list[str]:
    """The sorted union of per-symbol pinned-test NODE IDs across the stubs being
    landed — the spec the composed source is verified against once before it
    lands.

    This is the Blocker-2 fix for the mutual-stub union gate: gating against the
    landed stubs' OWN node IDs (``test_mathutils.py::test_add``,
    ``::test_scale``) — not the whole shared file — keeps an unsynthesizable
    sibling's red node (``::test_running_total``, NOT in ``assignment``) out of
    the gate, so ``add``/``scale`` land together while ``running_total`` stays a
    stub. Each landed stub is still gated against its OWN real tests
    (never-fake-green). Falls back to whole-file paths per file where a symbol's
    node IDs aren't discoverable (so nothing that used to land stops landing).
    Deterministic: sorted."""
    union: set[str] = set()
    for name in assignment:
        union.update(pinned_test_nodes(root, module_rel, name))
    return sorted(union)


def _compose(current: str, assignment: dict[str, str]) -> str | None:
    """Apply every ``name -> return_expr`` in ``assignment`` to ``current``,
    re-deriving stub spans after each fill (a fill shifts later line numbers).
    ``None`` if any rewrite fails to parse."""
    out = current
    remaining = dict(assignment)
    while remaining:
        applied = None
        for stub in find_stub_functions(out):
            if stub.name in remaining:
                filled_src = fill_stub_body(out, stub, remaining[stub.name])
                if filled_src is None:
                    return None
                out = filled_src
                applied = stub.name
                break
        if applied is None:
            break  # remaining names are not stubs in `out` — nothing more to do
        remaining.pop(applied, None)
    return out


def _union_passes(root: Path, module_rel: str, candidate: str,
                  test_files: list[str], runner: RunTestsSkill) -> bool:
    """Write ``candidate`` to the module, run the union of pinned tests, restore
    the prior on-disk text. True iff every test passes. Leaves the file as it
    found it, so the search never mutates the tree it reports on."""
    target = root / module_rel
    original = target.read_text(encoding="utf-8")
    import sys
    py = sys.executable
    for cand in (root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python"):
        if cand.exists():
            py = str(cand)
            break
    # `-B` + a bytecode purge: successive probes rewrite the same file within one
    # mtime-second at equal size, so a cached `.pyc` would test a stale candidate.
    cmd = [py, "-B", "-m", "pytest", "-q", *test_files]
    try:
        target.write_text(candidate, encoding="utf-8")
        _purge_pyc(target)
        summary = runner.run(str(root), commands=[cmd])
        return bool(summary.ok)
    finally:
        target.write_text(original, encoding="utf-8")
        _purge_pyc(target)


def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (a local copy on purpose: this objective stays self-contained)."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _modules(project_root: str | Path) -> list[str]:
    """Own modules that hold at least one fillable stub — the implement-stub
    fitness/move scan, made CHEAP.

    This is the DEFECT-1 fix: the scan formerly ran the FULL pytest-gated
    ``plan_implement_stub`` for EVERY module just to COUNT/enumerate work, and
    ``compile_objective`` calls the fitness/candidate scan once PER PASS — so the
    whole per-candidate pytest synthesis ran many times merely to MEASURE. The
    scan now uses :func:`module_has_fillable_stub`, an IN-PROCESS estimate (no
    pytest): a module counts when any stub with pinned tests is fillable via the
    in-process witness synthesis (non-recursive shapes) OR a recursion template
    evaluated as a real recursive function in-process. This never under-counts a
    landable stub (recursion included), so the SAME modules are offered.

    The actual apply is UNCHANGED: when a move is selected, ``plan_implement_stub``
    builds the real plan under the FULL pytest gate that ``apply_rename`` enforces
    — the never-fake-green moat governs what LANDS, exactly as before. A stub this
    cheap estimate counts but the gate later rejects simply no-ops at apply.
    Deterministic; fixed source-order traversal preserved."""
    from app.engine.objective_compiler import _own_modules

    root = Path(project_root)
    return [rel for rel, _src in _own_modules(project_root)
            if module_has_fillable_stub(root, rel)]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still hold an implementable stub.

    Implementable = a stub whose pinned tests a fixed template can satisfy. A
    stub with no tests or an unsatisfiable contract does NOT count (we refuse to
    touch it), so it never appears as remaining debt — an honest measure. Counted
    by the CHEAP in-process estimate (:func:`_modules`), never the slow pytest
    gate; the gate still governs what actually lands at apply."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="implement_stub",
        target=f"{rel}:implement-stub",
        description=f"implement a tested stub in {rel}",
        build_plan=lambda r=rel: plan_implement_stub(project_root, r),
    ) for rel in _modules(project_root)]


# The fitness/move SCAN is now cheap (an in-process estimate, no pytest — see
# `_modules`), but the APPLY still runs the project's tests per candidate template
# to actually LAND a fill, so the objective stays flagged `expensive`: the fast
# plan/ascend board skips it and it runs explicitly via
# `apex develop --objective implement-stub` (or the opt-in `develop session`).
# scope_verify=True: gate each fill against the IMPACTED tests, not the full
# suite. On a multi-module project where several modules each hold an
# unimplemented stub, the baseline suite is legitimately RED (every stub fails its
# own tests). Filling module A's stub correctly makes A's importing tests pass,
# but a full-suite gate would still see module B's pre-existing redness and roll
# A's correct change back — every module vetoed by every other. Impact-scoping
# runs only A's real importing tests (honestly verifying the fill); the full suite
# stays the commit-time backstop.
register(ObjectiveSpec(name="implement-stub", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
