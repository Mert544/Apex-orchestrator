"""Self-registering objective: js-strengthen-tests — the JS/TS mirror of
strengthen-tests (the LITE, mined-witness variant).

Apex's JS/TS test-STRENGTHENING action: find a single-token MUTATION an ALREADY-
tested exported JS/TS function's EXISTING jest test (its mined witnesses) does NOT
catch, and LAND ONE new env-gated characterization assertion that DOES. The transform
lives in :mod:`app.execution.js.js_strengthen_tests`; this module selects the
candidate JS/TS sources and registers the objective.

HONESTY (do NOT over-claim): this strengthens against the function's PINNED/MINED
test witnesses, NOT against arbitrary full-suite blind spots (the un-buildable full
mirror — survivor detection would need the buyer's jest suite run per-mutant, a moat
hazard). Value-tier BELOW Python strengthen-tests (0.88) and js-cover-gaps (0.90).
Never implies full mutation coverage.

The pipeline mirrors the js-cover-gaps spine but STRENGTHENS instead of COVERS, and
reuses the shared JS machinery (:mod:`app.execution.lang.js_adapter`):

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate). Each own NON-test ``.js``/``.ts``/... source is a candidate.
2. **GENERATE** — :func:`app.execution.js.js_strengthen_tests.generate_js_strengthen_test`
   enumerates the source's exported, public, undecorated, non-async, non-generator,
   PURE functions; for each that HAS exactly one linked jest test (``_locate_test`` is
   not ``None``) AND mineable witnesses AND a GREEN baseline, it seeds a deterministic
   single-token mutant catalog, keeps the SURVIVORS (every mined witness still matches),
   synthesizes a fresh input, and pins ``expect(fn(<input>)).toEqual(<real output>)``
   ONLY when the real output DIVERGES from a survivor (it kills it) AND survives the
   env-reproducibility re-capture gate. The buyer's existing test is NEVER edited.
3. **LAND** — the ONE new Apex-owned test file
   (``<dir>/__tests__/<stem>.apex-mutants.cover.test.<ext>``) is carried as a
   :class:`RenamePlan` (``new_contents`` only; the apply layer deletes it on rollback),
   with ``derived_from`` seeded from the SOURCE module so the impact scope finds the
   right tests. The FORCED jest gate proves the new assertions EXECUTE + PASS, with
   byte-for-byte auto-rollback.

DISJOINT from js-cover-gaps by construction: js-cover-gaps fires ONLY when
``_locate_test(name) is None`` (an UNTESTED function); js-strengthen-tests fires ONLY
when ``_locate_test(name)`` finds an existing test (an ALREADY-tested function). The
two never act on the same function.

Deterministic (fixed input synthesis, a fixed mutant catalog, pure transpile/capture,
pinned re-capture variations — same module yields byte-identical test bytes), offline
(``typescript`` is global; Apex installs nothing), zero-token. Test/fixture files are
never subjects, and Apex never writes into the suite it is gated by NOR the buyer's
existing test.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.lang.js_adapter import (
    JS_SOURCE_SUFFIXES,
    _locate_test,
    _walk_files,
    is_js_source,
)

__all__ = ["plan_js_strengthen_tests", "detect_strengthen_targets", "is_js_source"]


def _strengthenable_sources(project_root: str | Path) -> list[str]:
    """The own NON-test JS/TS sources eligible for a strengthening assertion, pinned
    by the single-``package.json`` root gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is at
    the root — the single-project gate, the JS analogue of one Python project root,
    and what makes this a clean NO-OP on a Python (or any non-JS) tree. Deterministic:
    sources in sorted order. The per-source / per-target eligibility (a pure function
    with a linked test, mined witnesses, a green baseline, a surviving mutant killable
    with an env-gated oracle) is the generator's; this only enumerates the files."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, JS_SOURCE_SUFFIXES)
            if is_js_source(rel)]


def plan_js_strengthen_tests(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module jest-strengthening plan, or an empty no-op plan (an
    honest refusal).

    Refuses a non-JS-source / test / fixture subject outright (:func:`is_js_source`),
    then delegates to
    :func:`app.execution.js.js_strengthen_tests.generate_js_strengthen_test`, which
    enumerates the source's already-tested pure functions, seeds the mutant catalog,
    keeps the mined-witness survivors, and renders the killing assertions — returning
    ``None`` when nothing is strengthenable (no survivor / no green baseline / no
    env-gated kill), or Apex's own generated test path already exists (never clobber).
    On success the plan's ONLY write is the NEW Apex-owned test file in
    ``new_contents`` (no ``originals`` entry — the apply layer deletes a never-existed
    file on rollback), with ``derived_from`` seeded from the source module so the
    scope-verify impact scan finds the tests that exercise it. The buyer's existing
    test is NEVER edited. An empty plan means there is nothing to do — never-fake-green."""
    from app.execution.js.js_strengthen_tests import generate_js_strengthen_test

    plan = RenamePlan(old=module_rel, new="js-strengthen-tests")
    root = Path(project_root)
    if not is_js_source(module_rel):
        return plan  # non-JS / test / fixture subject — honest no-op

    def locate(name: str) -> str | None:
        return _locate_test(root, module_rel, name)

    strengthen = generate_js_strengthen_test(root, module_rel, locate)
    if strengthen is None:
        return plan  # nothing strengthenable / already generated — no-op

    # A NEW file: it lands in new_contents only. derived_from carries the SOURCE
    # module so the scope-verify impact scan finds the tests exercising it.
    plan.new_contents[strengthen.test_rel] = strengthen.content
    plan.edits_by_file[strengthen.test_rel] = 1
    plan.derived_from = [module_rel]
    return plan


def detect_strengthen_targets(project_root: str | Path) -> list[str]:
    """The own JS/TS sources ``plan_js_strengthen_tests`` would actually strengthen —
    i.e. the plan lands a NEW Apex-owned mutant-killing test.

    A source with no surviving mutant (every mutant the mined witnesses catch — the
    common well-tested no-op), none with a green baseline, or whose generated test
    exists does NOT count, so it never shows as remaining debt — an honest measure,
    exactly like the Python ``strengthen-tests`` self-validating count. Each plan
    build spawns node (parse + mutate + transpile/capture children), so this is
    heavyweight — the objective is flagged ``expensive``."""
    root = Path(project_root)
    return [rel for rel in _strengthenable_sources(root)
            if plan_js_strengthen_tests(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an already-tested exported
    function whose mined witnesses miss a mutant this objective can deterministically
    kill with an env-gated assertion. 0 means none remain."""
    return float(len(detect_strengthen_targets(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``js_strengthen_tests`` move per strengthenable source file. The
    ``operator="js_strengthen_tests"`` literal lives HERE (in the objectives package)
    so the move-value drift scanner discovers it exactly as for every other
    self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_strengthen_tests",
        target=f"{rel}:js-strengthen-tests",
        description=(f"land a jest assertion killing a mutant {rel}'s mined "
                     "test witnesses miss"),
        build_plan=lambda r=rel: plan_js_strengthen_tests(root, r),
    ) for rel in detect_strengthen_targets(root)]


# Detection spawns node (the driver parses each source, seeds the mutant catalog) AND,
# per survivor, transpile/capture child processes for the witness-survival decision,
# the real value oracle, the env-reproducibility re-capture gate, and the mutant
# divergence check — heavyweight — so flag it expensive: the fast plan/ascend board
# skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-strengthen-tests`.
# scope_verify=True for the same reason as js-cover-gaps and the Python strengthen-tests
# family: on a multi-module JS project several modules can each carry a legitimately-RED
# test (an unfilled stub elsewhere), so the FULL-suite gate would let an UNRELATED
# still-red module veto landing this module's brand-new, jest-proven mutant-killing
# assertion. The generated test is the independent correctness proof and the full suite
# stays the commit-time backstop.
register(ObjectiveSpec(name="js-strengthen-tests", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
