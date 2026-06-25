"""Self-registering objective: js-tdd-implement — Apex's FIRST non-Python landing.

The JS/TS image of :mod:`app.execution.objectives.tdd_implement` — the everyday
TDD inner loop a budget-limited student or team otherwise pays an LLM for,
message by message: "I wrote the failing jest test, now write the code." Given a
top-level ``function foo(...) { throw new Error("Not implemented") }`` stub (or a
``const foo = (...) => { throw ... }`` arrow stub) that a jest test calls, this
objective DETERMINISTICALLY synthesises a real body from a FIXED template space
and lands it iff the previously-RED test flips GREEN — landing working code only
when the project's own ``npm test`` verifies it, with byte-for-byte auto-rollback
on any regression.

The pipeline mirrors the Python spine — **detect -> locate -> synthesise ->
gate** — but is JS-flavoured and touches ZERO Python objectives:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root). Each own
   ``.js``/``.ts`` source module is parsed by the bundled ``ts_driver.js`` (the
   TypeScript Compiler API); its top-level single-``throw`` stubs are the
   fillable candidates. Non-JS files are REFUSED outright (see
   :func:`is_js_source`), so this objective is a clean no-op on a Python tree.
2. **LOCATE** — find the ONE jest test that both imports the stub's module AND
   references the stub by name (the test that pins it). Ambiguity — zero or many
   such tests — is REFUSED, never guessed.
3. **SYNTHESISE** — delegate the body to
   :func:`app.execution.js.js_stub_synthesis.synthesize_js_body`, which tries the
   fixed template space in order against a THROWAWAY COPY's ``npm test`` and keeps
   the FIRST body that goes green (else refuses). Zero new synthesis logic here.
4. **GATE** — the plan lands the ONE changed source as a :class:`RenamePlan`
   (``originals`` for rollback, ``new_contents`` for the body), so the develop
   engine's gated/rollback writer runs the suite and restores it byte-for-byte if
   anything regresses.

Deterministic (fixed template order, byte-span splice, no clock/random — same
project, byte-identical body), offline (the project owns its ``node_modules``,
``typescript`` is global; Apex installs nothing), zero-token. Test/fixture files
are refused as WRITE targets — Apex never edits the suite it is gated by.

**Structure (round-22 extraction):** the JS-specific machinery — the
source-suffix gate, the jest test-file regex + ``node_modules`` walk, the
test-linkage LOCATE, the plan builder, the byte-span splice — now lives in
:mod:`app.execution.lang.js_adapter` as the canonical :class:`JavaScriptAdapter`
(the second instance of the :class:`~app.execution.lang.adapter.LanguageAdapter`
seam, so the Protocol is non-vacuous). This module is the thin objective wiring:
it obtains the adapter from the registry and FORWARDS the public surface
(``detect_js_stubs`` / ``plan_js_tdd_implement`` / ``fitness`` / ``moves`` /
``is_js_source`` / ``JsMissingBody``) to the adapter helpers so importers and the
507-line behaviour pin are unaffected, then registers the objective. Because each
forwarded name is the SAME predicate/slice it was before, ``detect_js_stubs`` /
``fitness`` / ``moves`` emit byte-identical output.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.lang.js_adapter import (
    JsMissingBody,
    detect_js_stubs,
    fitness,
    is_js_source,
    landable,
    plan_js_tdd_implement,
)

__all__ = ["plan_js_tdd_implement", "JsMissingBody", "detect_js_stubs", "is_js_source"]


def moves(project_root: str | Path) -> list:
    """The candidate ``js_tdd_implement`` moves — one per landable stub. A thin
    wrapper over :func:`app.execution.lang.js_adapter.landable`; the
    ``operator="js_tdd_implement"`` literal lives HERE (in the objectives package)
    so the move-value drift scanner discovers it exactly as before — byte-identical
    Moves, same operator, same target/description/plan."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_tdd_implement",
        target=f"{mb.file_rel}:{mb.stub.name}",
        description=(f"synthesize {mb.stub.name}() in {mb.file_rel} "
                     "to make its RED jest test green"),
        build_plan=lambda m=mb: plan_js_tdd_implement(root, m),
    ) for mb in landable(root)]


# Detection spawns node (parse) and, per candidate body, the project's jest suite
# against a throwaway copy — heavyweight — so flag it expensive: the fast
# plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-tdd-implement`.
# scope_verify=True for the same reason as the Python tdd-implement: on a
# multi-module JS project several modules can each have a RED test demanding a
# not-yet-written body, so the baseline suite is legitimately RED; making module
# A's test green must not be vetoed by an unrelated module B's still-red test.
register(ObjectiveSpec(name="js-tdd-implement", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
