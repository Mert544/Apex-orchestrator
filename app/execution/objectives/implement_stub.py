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
    ordered_candidate_exprs,
    pinned_test_files,
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

    filled = _fill_all_stubs(root, module_rel, original)
    if filled is None or filled == original:
        return plan  # every stub refused — honest empty plan

    plan.originals[module_rel] = original
    plan.new_contents[module_rel] = filled
    plan.edits_by_file[module_rel] = 1
    return plan


def _fill_all_stubs(root: Path, module_rel: str, original: str) -> str | None:
    """Cumulatively synthesize a body for EVERY satisfiable stub in the module,
    returning the full module source with all of them filled (or the original
    text unchanged when none was satisfiable).

    Each stub is synthesized against the *current* (partially-filled) source on
    disk, so an already-filled sibling's body is in place while the next stub's
    pinned tests are probed — that is what lets a per-module batch pass together.
    Sibling stubs are pinned by SEPARATE test files in the simple case, but they
    may share one test file too (a single ``test_arith.py`` asserting both
    ``add`` and ``mul``); there, neither stub's pinned file goes green until the
    OTHER is also filled. So we iterate to a FIXPOINT: each pass fills whatever
    became satisfiable now (a freshly-filled sibling can unblock a shared test
    file on the next pass), stopping when a pass lands nothing more.

    When the cheap pass stalls with stubs still pending (the MUTUAL case: one
    test file asserts both ``add`` and ``mul``, so neither file goes green until
    BOTH are filled), a coordinate-descent fallback composes a tentative source
    with every pending stub filled and refines each one's body until the union of
    all pinned tests passes together.

    The on-disk file is always restored to ``original`` before returning, so the
    scan leaves the tree byte-for-byte unchanged (the verified-apply engine, not
    this planner, performs the real write). Deterministic: within each pass stubs
    are taken in the fixed source order :func:`find_stub_functions` returns,
    re-derived after each fill so shifted line spans stay correct."""
    target = root / module_rel
    runner = RunTestsSkill()
    current = original
    filled: set[str] = set()
    try:
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
        # Mutual deadlock: stubs whose shared test file can't go green until the
        # others are filled too. Resolve them together via coordinate descent.
        current = _resolve_mutual_stubs(root, module_rel, current, filled, runner)
    finally:
        target.write_text(original, encoding="utf-8")
    return current if filled else None


def _resolve_mutual_stubs(root: Path, module_rel: str, current: str,
                          filled: set[str], runner: RunTestsSkill) -> str:
    """Fill the stubs the cheap fixpoint left pending because their pinned tests
    share a file and so stay red until every sibling is filled too.

    Each pending stub is seeded with its first parameter-shaped candidate, then
    coordinate descent refines one stub at a time — picking the first candidate
    (fixed order) that makes the UNION of all pending pinned tests pass given the
    current sibling assignments — until a full pass changes nothing. A combined
    source is accepted ONLY when that union is green, so nothing unverified lands
    (never-fake-green); otherwise ``current`` is returned unchanged and those
    stubs are left as-is. ``filled`` is updated in place for the stubs that land."""
    candidates, union_tests = _resolvable_candidates(root, module_rel, current, filled)
    if not candidates or not union_tests:
        return current

    tests = sorted(union_tests)
    assignment = _descend(root, module_rel, current, candidates, tests, runner)
    composed = _compose(current, assignment)
    if composed is None:
        return current
    if not _union_passes(root, module_rel, composed, tests, runner):
        return current  # union not green — refuse, land nothing for these stubs
    filled.update(assignment)
    return composed


def _resolvable_candidates(root: Path, module_rel: str, current: str,
                           filled: set[str]) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
    """For each still-pending stub, its fixed-order candidate exprs and the union
    of pinned test files. A stub with no spec or no template is dropped (it can't
    be resolved); the rest are the coordinate-descent search space."""
    candidates: dict[str, list[tuple[str, str]]] = {}
    union_tests: set[str] = set()
    for stub in find_stub_functions(current):
        if stub.name in filled:
            continue
        tests = pinned_test_files(root, module_rel, stub.name)
        exprs = ordered_candidate_exprs(root, tests, stub) if tests else []
        if not tests or not exprs:
            continue  # no spec or no template — cannot resolve this one
        candidates[stub.name] = exprs
        union_tests.update(tests)
    return candidates, union_tests


def _descend(root: Path, module_rel: str, current: str,
             candidates: dict[str, list[tuple[str, str]]],
             union_tests: list[str], runner: RunTestsSkill) -> dict[str, str]:
    """Coordinate descent over the pending stubs: seed each with its first
    candidate, then repeatedly pick, for one stub at a time, the first candidate
    (fixed order) that makes the union of pinned tests pass with the others held
    fixed. Stops at a fixpoint (a full pass that changes nothing) or after a
    bounded number of passes. Returns the final ``name -> return_expr`` map."""
    assignment = {name: exprs[0][1] for name, exprs in candidates.items()}
    for _ in range(len(candidates) + 1):
        changed = False
        for name, exprs in candidates.items():
            best = _best_candidate(root, module_rel, current, assignment, name,
                                   exprs, union_tests, runner)
            if best is not None and best != assignment[name]:
                assignment[name] = best
                changed = True
        if not changed:
            break
    return assignment


def _best_candidate(root: Path, module_rel: str, current: str,
                    assignment: dict[str, str], target_name: str,
                    exprs: list[tuple[str, str]], union_tests: list[str],
                    runner: RunTestsSkill) -> str | None:
    """The first candidate expr (fixed order) for ``target_name`` that makes the
    union of pinned tests pass with all OTHER stubs held at their current
    assignment, or ``None`` when none does this round."""
    trial = dict(assignment)
    for _label, expr in exprs:
        trial[target_name] = expr
        composed = _compose(current, trial)
        if composed is None:
            continue
        if _union_passes(root, module_rel, composed, union_tests, runner):
            return expr
    return None


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
    from app.engine.objective_compiler import _own_modules

    return [rel for rel, _src in _own_modules(project_root)
            if plan_implement_stub(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still hold an implementable stub.

    Implementable = a stub whose pinned tests a fixed template can satisfy. A
    stub with no tests or an unsatisfiable contract does NOT count (we refuse to
    touch it), so it never appears as remaining debt — an honest measure."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="implement_stub",
        target=f"{rel}:implement-stub",
        description=f"implement a tested stub in {rel}",
        build_plan=lambda r=rel: plan_implement_stub(project_root, r),
    ) for rel in _modules(project_root)]


# Synthesis runs the project's tests once per candidate template, so the fitness
# scan is heavyweight — flag it expensive so the fast plan/ascend board skips it
# (it stays runnable explicitly via `apex develop --objective implement-stub`).
register(ObjectiveSpec(name="implement-stub", fitness=fitness, moves=moves,
                       expensive=True))
