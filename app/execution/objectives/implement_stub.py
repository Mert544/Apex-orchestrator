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

import ast
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.stub_synthesis import (
    _native_mind_enabled,
    _purge_pyc,
    ambiguity_reason,
    fill_stub_body,
    filled_source_passes_doctests,
    has_enforceable_doctest_examples,
    find_stub_functions,
    module_has_fillable_stub,
    pinned_test_files,
    pinned_test_nodes,
    synthesize_doctest_body,
    synthesize_expr_from_witnesses,
    synthesize_stub_body,
    verify_body_via_doctest,
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
        _disclose_ambiguity(plan, root, module_rel, original)
        return plan  # every stub refused — honest empty plan (reason disclosed)

    plan.originals[module_rel] = original
    plan.new_contents[module_rel] = filled
    plan.edits_by_file[module_rel] = 1
    _scope_apply_gate(plan, root, module_rel, original, filled_names)
    # Attribute native-only landings ONLY when the lane is enabled: with it off,
    # no native body was ever offered, so nothing is native-only — skipping the
    # detector keeps the default (and every dry-run) path zero-overhead.
    if _native_mind_enabled():
        plan.native_shapes = _landed_native_shapes(root, module_rel, original, filled)
    return plan


def _returned_expr(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The unparsed single-return expression of ``fn`` (a leading docstring
    skipped), or ``None`` — the exact shape a native fill writes (``return
    <expr>``, a ternary included). Anything richer isn't a native single-expr
    body, so it is not attributed to the native lane."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant) and isinstance(
            body[0].value.value, str):
        body = body[1:]
    if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
        try:
            return ast.unparse(body[0].value)
        except Exception:
            return None
    return None


def _landed_native_shapes(root: Path, module_rel: str, original: str,
                          filled: str) -> list[str]:
    """The canonical idiom shapes this fill landed that ONLY the native
    intelligence supplied — a body present in the project-learned candidates but
    NOT in any fixed template for that stub. Pure/read-only and env-INDEPENDENT
    (it mines the native candidates directly), so a body a template produced is
    excluded: with the lane off, every landed body IS a template body and nothing
    is attributed. This is the experience signal the apply engine records only
    after the plan verifies and lands. Deterministic, sorted, de-duplicated."""
    from app.engine.native_synth import canonical_shape, mind_candidate_exprs
    from app.execution.stub_synthesis import (
        _function_witnesses,
        _native_mind_sources,
        candidate_bodies,
    )

    try:
        tree = ast.parse(filled)
    except (SyntaxError, ValueError):
        return []
    filled_fns = {n.name: n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    sources = list(_native_mind_sources(str(root)))
    shapes: set[str] = set()
    for stub in find_stub_functions(original):
        fn = filled_fns.get(stub.name)
        if fn is None:
            continue
        expr = _returned_expr(fn)
        if expr is None:
            continue
        tests = pinned_test_files(root, module_rel, stub.name)
        witnesses = _function_witnesses(root, tests, stub) if tests else []
        template_exprs = {e for _label, e in candidate_bodies(stub, witnesses)}
        native_exprs = {e for _label, e in mind_candidate_exprs(sources, stub.params)}
        if expr in native_exprs and expr not in template_exprs:
            shapes.add(canonical_shape(stub.params, expr))
    return sorted(shapes)


def _disclose_ambiguity(plan: RenamePlan, root: Path, module_rel: str,
                        original: str) -> None:
    """When this module's stubs were ALL refused, disclose WHY for each one that
    was refused specifically because its pinned witnesses are AMBIGUOUS — and HOW
    to fix it (add a discriminating test).

    A stub Apex correctly REFUSES on ambiguity (≥2 competing template bodies
    satisfy every witness but diverge off-witness) otherwise lands nothing with no
    explanation — the buyer gets silence. This rides the plan's EXISTING
    ``blockers`` channel, which ``objective_compiler`` records into
    ``CompileResult.blocked`` (rendered under "Blocked" and carried into the
    develop-session report), so the reason reaches the buyer through a path that
    already renders refusals — no new cross-cutting surface.

    Purely additive and never changes WHAT lands: it is called ONLY on the
    genuinely-empty refusal branch (``new_contents`` is empty here), where a
    blocker cannot suppress a landing — a module that lands any stub never reaches
    this branch, so its blockers stay untouched and its fill is unaffected. One
    line per ambiguous stub, in source order; non-ambiguous refusals (no pinned
    tests, unsatisfiable, xfail-only) add nothing. Deterministic: the reason is a
    pure function of the fixtures."""
    for stub in find_stub_functions(original):
        tests = pinned_test_files(root, module_rel, stub.name)
        if not tests:
            continue  # no spec — not an ambiguity refusal, nothing to disclose
        reason = ambiguity_reason(root, tests, stub)
        if reason is not None:
            plan.blockers.append(f"{stub.name}: {reason}")


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
        # Pass 0 (doctest): a stub whose contract lives in its docstring ``>>>``
        # examples has NO pinned test file, so the pytest-gated passes below can
        # never land it — yet the cheap scan (which mines those examples) counts it
        # fillable. This pass closes that gap HONESTLY: it synthesizes such a stub's
        # body from its doctest (and any test-file) witnesses and verifies it by
        # RUNNING the examples, so the apply lands exactly the set the scan offered.
        current = _fill_doctest_stubs(root, module_rel, current, filled)
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
                # A stub that ALSO carries doctest witnesses must satisfy its OWN
                # examples too: a pytest-passing body that VIOLATES the doctests is
                # a fake-green nobody re-ran, so re-run them on the filled source and
                # refuse the fill this pass if they don't hold (never-fake-green).
                # A stub with no doctest contract lands on the pytest gate alone, as
                # before — so a doctest+fixture stub the pytest pass can satisfy now
                # LANDS (closing the lost-landing regression of the upfront skip).
                # NOTE (honest under-claim): this gates the FIRST pytest-passing
                # candidate ``synthesize_stub_body`` returned; if THAT body violates
                # the stub's own doctests it is refused this run, rather than
                # searching for a later candidate that would satisfy BOTH gates. The
                # refusal is always SAFE (never a fake-green); it can only land
                # fewer, never a wrong body — so a doctest stub may be under-counted
                # vs the scan in this narrow case (acceptable; never over-claimed).
                if (has_enforceable_doctest_examples(current, stub)
                        and not filled_source_passes_doctests(new_source, stub)):
                    continue  # pytest-green but doctest-violating — skip this pass
                current = new_source
                filled.add(stub.name)
                progress = True
                break  # re-derive: this fill shifted later stubs' line spans
    finally:
        target.write_text(original, encoding="utf-8")
    return (current, filled) if filled else (None, filled)


def _fill_doctest_stubs(root: Path, module_rel: str, current: str,
                        filled: set[str]) -> str:
    """Fill every stub whose contract is (wholly or partly) pinned by its OWN
    docstring ``>>>`` examples, verifying each landed body by RUNNING those
    examples with the stdlib ``doctest`` — never by a pytest file (a doctest-only
    stub has none). ``filled`` is updated in place with each stub that lands.

    This is the apply-side twin of the scan's doctest acceptance: the body comes
    from :func:`synthesize_doctest_body` (the SAME synth + doctest-verify the
    scan's ``can_fill_stub_in_process`` uses), so the apply lands exactly the stubs
    the scan called fillable — the no-over/under-count invariant. The body it
    returns is already verified against ``current`` by re-running the examples, so
    a body that does not reproduce them is never composed (never-fake-green). A
    stub with NO minable doctest witness is left untouched here
    (``synthesize_doctest_body`` returns ``None``), so the pytest-gated passes own
    it and the existing test-file-only behavior is byte-identical.

    Iterates to a FIXPOINT: a doctest example may call a SIBLING function, whose
    body must already be in place for the example to pass, so a freshly-filled
    sibling can unblock another's examples on the next pass — and because each fill
    is verified against the partially-filled ``current``, a stub only lands once
    every function its examples exercise is real. Deterministic: stubs in source
    order, re-derived after each fill so shifted spans stay correct."""
    progress = True
    while progress:
        progress = False
        for stub in find_stub_functions(current):
            if stub.name in filled:
                continue
            tests = pinned_test_files(root, module_rel, stub.name)
            expr = synthesize_doctest_body(root, tests, stub, current)
            if expr is None:
                continue  # not doctest-pinnable now — pytest passes may own it
            composed = fill_stub_body(current, stub, expr)
            if composed is None or composed == current:
                continue
            current = composed
            filled.add(stub.name)
            progress = True
            break  # re-derive: this fill shifted later stubs' line spans
    return current


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
    independently of the others.

    A stub with enforceable DOCTEST witnesses must ALSO satisfy its own examples:
    a body the test-file witnesses determine could pass the pytest gate yet VIOLATE
    those examples (a fake-green nobody re-ran). So such a stub is NOT skipped here
    (skipping it locked out any stub whose pytest witnesses are non-literal — e.g.
    a fixture arg — even though the doctest pass declined it as non-evaluable,
    losing the landing); instead its candidate ``expr`` is DOCTEST-verified before
    it joins the assignment, so a body satisfying BOTH its pinned tests AND its
    doctests lands, while a doctest-violating one is refused. A stub the doctest
    pass already landed is in ``filled`` and skipped."""
    assignment: dict[str, str] = {}
    for stub in find_stub_functions(current):
        if stub.name in filled:
            continue
        tests = pinned_test_files(root, module_rel, stub.name)
        if not tests:
            continue  # no spec — leave as-is
        expr = synthesize_expr_from_witnesses(root, tests, stub)
        if expr is None:
            continue
        # Doctest-pinned: accept the test-witness-derived expr only when it also
        # reproduces the stub's own examples (never-fake-green); a non-doctest stub
        # is gated by its pinned tests alone, exactly as before.
        if (not has_enforceable_doctest_examples(current, stub)
                or verify_body_via_doctest(current, stub, expr)):
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
    gated by (a local copy on purpose: this objective stays self-contained).

    A ``.pyi`` type-stub file is refused too: every body in it is ``...`` by
    definition (a signature-only INTERFACE, never executed), so filling one would
    splice garbage into a declaration. This is the apply-side twin of the same
    ``.pyi`` guard the discovery scan applies — the planner sees the rel here, so
    this is where a ``.pyi`` is turned away before any stub is even looked for."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py" or name.endswith(".pyi")
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
