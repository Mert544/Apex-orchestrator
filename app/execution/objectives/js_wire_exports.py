"""Self-registering objective: js-wire-exports — Apex's THIRD JS/TS concrete
landing, the JS/TS sibling of the Python :mod:`wire_exports` / wire-module-exports
objectives.

For an own non-test ``.js``/``.ts``/``.mjs``/``.cjs`` source that DEFINES a
top-level PUBLIC function or ``const``-arrow but never exports it, js-wire-exports
lands the ONE missing ESM ``export`` keyword (a byte-splice of ``export `` at the
statement start) so the helper becomes part of the module's public surface — the
boilerplate a student/team writes by hand when a private helper graduates to
public API. It is the soundest, smallest-blast-radius JS wiring: a pure
export-surface GROW that PUBLISHES an already-defined binding.

Why it is sound (and needs NO npm/jest/tsc): adding a name to the export surface
can never break an existing importer (the name did not exist before, so nothing
imported it), and the binding provably exists in the SAME AST that produced the
target (it is a defined top-level symbol in THIS file) — so "the export resolves
to a real binding" is a STRUCTURAL fact, not a runtime claim, unlike a cross-file
index re-export which would need a node loader. v0 is therefore ESM-NAMED-ONLY:
the driver REFUSES the whole file if any ``module.exports``/``exports.``/
``export default``/``export =`` is present (CJS + default-export are deferred —
their only honest "resolves" proof is a loader the pytest-only ``apply_rename``
gate cannot provide). One symbol per move (smallest blast radius); a file with
several unexported publics yields several moves, each independently oracle-gated.

The pipeline mirrors :mod:`document_export_jsdoc` — same JS spine, same
re-parse-oracle pattern, with ``==`` relaxed to a named SUPERSET (we INTEND to
grow the export set by exactly the added names):

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root; this is what
   makes the objective a clean NO-OP on a Python tree). Each own non-test source
   with at least one wireable target is a candidate. The walk / source-suffix gate
   / jest-test refusal are reused verbatim from
   :mod:`app.execution.lang.js_adapter` (the shared JS machinery).
2. **PLAN** — :func:`plan_js_wire_exports` reads the file, asks the driver
   (``ts_driver.js wire-targets``) for each defined-but-unexported public symbol's
   name + statement-start offset, splices ``export `` BOTTOM-UP (descending offset,
   so earlier inserts stay valid), and records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.js.js_tool.reparse_exports_superset`) and asserts the full
   exported-name set is exactly ``prior ∪ {the added names}`` — proving the splice
   added precisely the intended public names and corrupted nothing (refuse rather
   than land on any drift).
4. **LAND** — the ONE changed source is carried as a :class:`RenamePlan`
   (``originals`` for byte-for-byte rollback, ``new_contents`` for the wired
   source), applied by the shared gated/rollback writer like every objective.

Deterministic (pure AST → source order, byte-offset splice bottom-up, set-equality
oracle, no clock/random), offline (the project owns its ``node_modules``;
``typescript`` is global; Apex installs nothing), zero-token. Test/fixture files
are refused as WRITE targets — Apex never edits the suite. ``expensive=True``
(detection spawns node, so the fast plan/ascend board skips the scan);
``scope_verify=False`` (a pure export-surface grow has no red-baseline problem —
no full-suite veto to dodge — so it needs NO ``SCOPE_VERIFY_ALLOWLIST`` entry).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.js.js_tool import JsWireTarget, reparse_exports_superset, wire_targets
from app.execution.lang.js_adapter import (
    _read,
    _u16_to_codepoint,
    _walk_files,
    is_js_source,
)
from app.execution.lang.js_adapter import JS_SOURCE_SUFFIXES as _JS_SUFFIXES

__all__ = [
    "plan_js_wire_exports",
    "detect_wire_targets",
    "is_js_source",
    "wireable_targets",
]


def wireable_targets(root: Path, rel: str) -> list[JsWireTarget]:
    """The defined-but-unexported public function/const-arrow targets in
    ``root/rel`` the objective would actually export (empty on a non-source/test
    target or on refuse).

    Refuses a non-JS-source or test/fixture file outright (:func:`is_js_source`),
    then returns the driver-found targets (the driver already applied the public /
    not-already-exported / not-CJS-or-default / readable-binding gates), mirroring
    :func:`app.execution.objectives.document_export_jsdoc.documentable_targets`."""
    if not is_js_source(rel):
        return []
    return list(wire_targets(root, rel))


def _splice_export(source: str, targets: list[JsWireTarget]) -> str | None:
    """``source`` with ``"export "`` prepended at each target's ``insert_offset``,
    or ``None`` when any offset is out of range or splits a surrogate pair (a stale
    scan — refuse rather than corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not shift
    a later offset. The driver's ``insert_offset`` is a UTF-16 code-UNIT offset, so
    it is re-indexed to a code-POINT index via :func:`_u16_to_codepoint` against the
    CURRENT ``new_source`` before each insertion (they diverge by +1 per astral char
    upstream) — the surrounding formatting and every other character survive
    untouched; the only added bytes are the ``export `` keyword that publishes an
    already-defined binding."""
    new_source = source
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = _u16_to_codepoint(new_source, target.insert_offset)
        if off is None:
            return None
        new_source = new_source[:off] + "export " + new_source[off:]
    return new_source if new_source != source else None


def detect_wire_targets(project_root: str | Path) -> list[str]:
    """The own non-test JS/TS source files that have at least one wireable target,
    each pinned by the single-``package.json`` root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root, and what makes this a clean NO-OP on a Python (or any non-JS) tree.
    Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, _JS_SUFFIXES)
            if wireable_targets(root, rel)]


def plan_js_wire_exports(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the missing-export plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-JS-source / test / fixture write target outright
    (:func:`is_js_source`, via :func:`wireable_targets`). For each defined-but-
    unexported public target it splices a leading ``export `` keyword bottom-up,
    then proves the splice is a sound surface-grow with the driver's re-parse
    superset oracle (:func:`reparse_exports_superset` — re-parses AND carries
    exactly the prior export set ∪ the added names) before recording it. An empty
    plan means nothing was wireable or the oracle refused — nothing is touched
    (never-fake-green)."""
    plan = RenamePlan(old=rel, new="js-wire-exports")
    root = Path(project_root)
    targets = wireable_targets(root, rel)
    if not targets:
        return plan  # non-JS / test / nothing to wire — honest no-op
    target_file = root / rel
    original = _read(target_file)
    if not original and not target_file.exists():
        return plan  # unreadable / missing target — no-op
    wired = _splice_export(original, targets)
    if wired is None:
        return plan  # a stale offset / no-change splice — refuse
    added = frozenset(t.name for t in targets)
    if not reparse_exports_superset(root, rel, wired, added):
        return plan  # the splice did not re-parse as prior ∪ added — refuse, land nothing
    plan.originals[rel] = original
    plan.new_contents[rel] = wired
    plan.edits_by_file[rel] = len(targets)
    return plan


def _wireable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_js_wire_exports`` would actually change — i.e.
    the plan lands an export. A file whose every target the oracle refuses does NOT
    count, so it never shows as remaining debt (an honest measure, exactly like the
    Python ``wire-exports`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_wire_targets(root)
            if plan_js_wire_exports(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still define a public function/const-
    arrow that is never exported but this objective can wire. 0 means none remain."""
    return float(len(_wireable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``js_wire_exports`` move per wireable source file. The
    ``operator="js_wire_exports"`` literal lives HERE (in the objectives package)
    so the move-value drift scanner discovers it exactly as for every other
    self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_wire_exports",
        target=f"{rel}:js-wire-exports",
        description=f"export the unexported public symbols defined in {rel}",
        build_plan=lambda r=rel: plan_js_wire_exports(root, r),
    ) for rel in _wireable_files(root)]


# Detection spawns node (the driver parses each source), so flag it expensive: the
# fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-wire-exports`.
# scope_verify is FALSE (unlike js-tdd-implement): a pure export-surface GROW adds
# only an `export` keyword that publishes an already-defined binding — there is no
# red-baseline a full-suite gate could wrongly veto, so it needs NO
# SCOPE_VERIFY_ALLOWLIST entry. It must register DIRECTLY (not via
# register_module_objective, which iterates the Python-only own-modules) because
# this is a JS/TS objective — exactly as document-export-jsdoc / js-tdd-implement do.
register(ObjectiveSpec(name="js-wire-exports", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
