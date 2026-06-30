"""Self-registering objective: js-cover-gaps — the JS/TS mirror of cover-gaps.

Apex's JS/TS characterization-test generator: turn an UNTESTED exported JS/TS
function into the ACTION of writing the FIRST jest test that pins its behaviour.
The transform lives in :mod:`app.execution.js.js_cover_gaps` (the JS image of
:mod:`app.execution.test_shield`); this module selects the candidate JS/TS sources
and registers the objective.

The pipeline mirrors the Python ``cover-gaps`` spine but is JS-flavoured and reuses
the shared JS machinery (:mod:`app.execution.lang.js_adapter`):

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root, and what makes
   this a clean NO-OP on a Python tree). Each own NON-test ``.js``/``.ts``/... source
   is a candidate.
2. **GENERATE** — :func:`app.execution.js.js_cover_gaps.generate_js_cover_test`
   enumerates the source's exported, public, undecorated, non-async, non-generator
   functions; for each whose inputs are in the SOUND slice (zero-arg / all-primitive-
   typed / all-literal-default) AND that is ``pure`` (the driver's forbidden-call/
   free-identifier AST scan), it CALLS the function with synthesized args at
   generation time and pins ``expect(fn(<args>)).toEqual(<captured>)`` — but ONLY
   when the captured value survives the ENV-REPRODUCIBILITY re-capture gate (varied
   cwd/HOME/TZ/TMPDIR + a wall-clock gap). A function a jest test ALREADY pins is
   never clobbered (the ``_locate_test`` linkage), and the generated test path is
   never overwritten.
3. **LAND** — the ONE new test file is carried as a :class:`RenamePlan`
   (``new_contents`` only; no ``originals`` entry — the file does not exist yet, so
   the apply layer deletes it on rollback), with ``derived_from`` seeded from the
   SOURCE module so the impact scope finds the right tests. The FORCED jest gate
   proves the generated test EXECUTES + PASSES, with byte-for-byte auto-rollback.

Deterministic (fixed input synthesis, pure transpile/capture, pinned re-capture
variations — same module yields byte-identical test bytes), offline (``typescript``
is global; Apex installs nothing), zero-token. Test/fixture files are never
subjects, and Apex never writes into the suite it is gated by.
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

__all__ = ["plan_js_cover_gaps", "detect_cover_targets", "is_js_source"]


def _coverable_sources(project_root: str | Path) -> list[str]:
    """The own NON-test JS/TS sources eligible for a characterization test, pinned by
    the single-``package.json`` root gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is at
    the root — the single-project gate, the JS analogue of one Python project root,
    and what makes this a clean NO-OP on a Python (or any non-JS) tree. Deterministic:
    sources in sorted order (as :func:`_walk_files` emits). The per-source / per-target
    eligibility (an exported pure function in the sound input slice, no existing linked
    test) is the generator's; this only enumerates the candidate files."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, JS_SOURCE_SUFFIXES)
            if is_js_source(rel)]


def plan_js_cover_gaps(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module jest-characterization-test plan, or an empty no-op
    plan (an honest refusal).

    Refuses a non-JS-source / test / fixture subject outright (:func:`is_js_source`),
    then delegates to
    :func:`app.execution.js.js_cover_gaps.generate_js_cover_test`, which enumerates
    the source's landable targets, captures each real return under the env-
    reproducibility gate, and renders the test — returning ``None`` when nothing is
    landable, a test path already exists, or a target is already covered by a linked
    jest test (never clobber). On success the plan's ONLY write is the NEW test file
    in ``new_contents`` (no ``originals`` entry — the apply layer deletes a
    never-existed file on rollback), with ``derived_from`` seeded from the source
    module so the impact scope finds the tests that exercise it. An empty plan means
    there is nothing to do — never-fake-green."""
    from app.execution.js.js_cover_gaps import generate_js_cover_test

    plan = RenamePlan(old=module_rel, new="js-cover-gaps")
    root = Path(project_root)
    if not is_js_source(module_rel):
        return plan  # non-JS / test / fixture subject — honest no-op

    def locate(name: str) -> str | None:
        return _locate_test(root, module_rel, name)

    cover = generate_js_cover_test(root, module_rel, locate)
    if cover is None:
        return plan  # nothing landable / already covered / test exists — no-op

    # A NEW file: it lands in new_contents only. derived_from carries the SOURCE
    # module so the scope-verify impact scan finds the tests exercising it.
    plan.new_contents[cover.test_rel] = cover.content
    plan.edits_by_file[cover.test_rel] = 1
    plan.derived_from = [module_rel]
    return plan


def detect_cover_targets(project_root: str | Path) -> list[str]:
    """The own JS/TS sources ``plan_js_cover_gaps`` would actually write a test for —
    i.e. the plan lands a NEW jest characterization test.

    A source with no landable target (no exported pure function in the sound input
    slice with a reproducible value oracle), one already covered, or whose generated
    test exists does NOT count, so it never shows as remaining debt — an honest
    measure, exactly like the Python ``cover-gaps`` self-validating count. Each plan
    build spawns node (parse + transpile/capture children), so this is heavyweight —
    the objective is flagged ``expensive``."""
    root = Path(project_root)
    return [rel for rel in _coverable_sources(root)
            if plan_js_cover_gaps(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an exported function this
    objective can deterministically characterize with a value oracle. 0 means none
    remain (every characterizable function is already pinned)."""
    return float(len(detect_cover_targets(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``js_cover_gaps`` move per coverable source file. The
    ``operator="js_cover_gaps"`` literal lives HERE (in the objectives package) so
    the move-value drift scanner discovers it exactly as for every other
    self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_cover_gaps",
        target=f"{rel}:js-cover-gaps",
        description=f"write a jest characterization test for {rel}",
        build_plan=lambda r=rel: plan_js_cover_gaps(root, r),
    ) for rel in detect_cover_targets(root)]


# Detection spawns node (the driver parses each source) AND, per landable target,
# transpile/capture child processes for the value oracle + the env-reproducibility
# re-capture gate — heavyweight — so flag it expensive: the fast plan/ascend board
# skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-cover-gaps`.
# scope_verify=True for the same reason as the Python cover-gaps' sibling
# tdd-implement family: on a multi-module JS project several modules can each carry a
# legitimately-RED test (an unfilled stub elsewhere), so the FULL-suite gate would
# let an UNRELATED still-red module veto landing this module's brand-new, jest-proven
# characterization test. The generated test is the independent correctness proof and
# the full suite stays the commit-time backstop.
register(ObjectiveSpec(name="js-cover-gaps", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
