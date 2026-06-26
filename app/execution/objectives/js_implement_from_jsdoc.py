"""Self-registering objective: js-implement-from-jsdoc — Apex's FOURTH JS/TS
concrete landing, the JS/TS image of :mod:`implement-from-doctest
<app.execution.objectives.implement_from_doctest>` and the DISJOINT sibling of
:mod:`js-tdd-implement <app.execution.objectives.js_tdd_implement>`.

Fills a top-level ``function foo(...) { throw ... }`` stub (or a ``const foo =
(...) => { throw ... }`` arrow stub) whose contract lives ONLY in its own JSDoc
``@example`` block and that NO jest test references — the exact white space the
two existing JS objectives leave open: ``js-tdd-implement`` needs a LINKING jest
test, ``document-export-jsdoc`` only documents. The author has already written the
contract as a worked example (``@example`` -> ``foo(2, 3) === 5``) but no test
file, so this objective PROMOTES the docstring to the PRIMARY spec: it
DETERMINISTICALLY synthesises a body from the SAME fixed template space the JS
spine uses and lands it IFF a jest spec Apex GENERATES from the ``@example`` lines
goes green — landing working code only when the project's own ``npm test``
verifies it, with byte-for-byte auto-rollback on any regression.

The TRIGGER is the INVERSE of ``js-tdd-implement``: a stub with >=1 JSDoc
``@example`` AND **no jest test that links it** (``_locate_test`` returns None),
so the two NEVER double-count the same stub. The generated spec lives ONLY in a
THROWAWAY copy of the project and dies with it — Apex NEVER writes a test into the
real tree (parity with "never edit the suite I'm gated by").

The pipeline clones the ``js-tdd-implement`` spine read-only — **detect -> locate
-> synthesise -> oracle+gate** — JS-flavoured and touching ZERO Python objectives:

1. **DETECT** — only when a single ``package.json`` is at the project root. Each
   own ``.js``/``.ts`` source's top-level single-``throw`` stubs whose leading
   JSDoc mines >=1 ``@example`` witness AND that no jest test links are the
   candidates (:func:`app.execution.lang.js_adapter.detect_js_jsdoc_stubs`).
   Non-JS files are REFUSED outright (a clean no-op on a Python tree).
2. **SYNTHESISE + ORACLE** — delegate the body to
   :func:`app.execution.js.js_jsdoc_synthesis.synthesize_js_jsdoc_body`, which
   generates a throwaway jest spec from the ``@example`` witnesses, tries the fixed
   template space IN ORDER against a THROWAWAY COPY's ``npm test``, and keeps the
   FIRST body that goes green (else refuses). Zero new synthesis logic.
3. **GATE** — the plan lands the ONE changed source as a :class:`RenamePlan`
   (``originals`` for rollback, ``new_contents`` for the body), so the develop
   engine's gated/rollback writer runs the FULL real suite and restores it
   byte-for-byte if anything regresses.

Deterministic (fixed template order, byte-span splice, fixed generated-spec text,
no clock/random — same project + same ``@example`` -> byte-identical body),
offline (the project owns its ``node_modules``; ``typescript`` is global; Apex
installs nothing), zero-token. Test/fixture files are refused as WRITE targets.

This module is the thin objective wiring: it FORWARDS the public surface
(``detect_js_jsdoc_stubs`` / ``plan_js_implement_from_jsdoc`` / ``is_js_source`` /
``JsJsdocStub``) to the canonical :class:`~app.execution.lang.js_adapter.JavaScriptAdapter`
helpers (where the JS-specific machinery lives), then registers the objective. The
``operator="js_implement_from_jsdoc"`` literal lives HERE so the move-value drift
scanner discovers it exactly as for every other self-registered objective.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.lang.js_adapter import (
    JsJsdocStub,
    detect_js_jsdoc_stubs,
    is_js_source,
    jsdoc_fitness,
    jsdoc_landable,
    plan_js_implement_from_jsdoc,
)

__all__ = [
    "plan_js_implement_from_jsdoc",
    "JsJsdocStub",
    "detect_js_jsdoc_stubs",
    "is_js_source",
]

# The objective's fitness is the JSDoc-contract landable count, forwarded from the
# adapter so the registered spec and the helper agree on the same measure.
fitness = jsdoc_fitness


def moves(project_root: str | Path) -> list:
    """The candidate ``js_implement_from_jsdoc`` moves — one per landable
    JSDoc-contract stub. A thin wrapper over
    :func:`app.execution.lang.js_adapter.jsdoc_landable`; the
    ``operator="js_implement_from_jsdoc"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it — byte-identical Moves,
    same operator, same target/description/plan."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_implement_from_jsdoc",
        target=f"{mb.file_rel}:{mb.stub.name}",
        description=(f"synthesize {mb.stub.name}() in {mb.file_rel} "
                     "from its jsdoc @example and verify a generated jest spec"),
        build_plan=lambda m=mb: plan_js_implement_from_jsdoc(root, m),
    ) for mb in jsdoc_landable(root)]


# Detection spawns node (parse + JSDoc mine) and, per candidate body, the
# project's jest suite against a throwaway copy carrying a GENERATED spec —
# heavyweight — so flag it expensive: the fast plan/ascend board skips the scan,
# but it stays runnable explicitly via
# `apex develop --objective js-implement-from-jsdoc`.
# scope_verify=True for the same reason as js-tdd-implement / implement-from-doctest:
# on a multi-module JS project several modules can each have a not-yet-filled stub,
# so the baseline suite is legitimately RED; filling module A's stub must not be
# vetoed by an unrelated module B's still-red stub. The generated @example spec is
# the per-fill contract (verified in the throwaway copy); the full suite stays the
# commit-time backstop.
register(ObjectiveSpec(name="js-implement-from-jsdoc", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
