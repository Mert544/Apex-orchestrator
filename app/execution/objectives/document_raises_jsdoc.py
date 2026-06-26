"""Self-registering objective: document-raises-jsdoc — Apex's SIXTH JS/TS
concrete landing, the FAILURE-CONTRACT sibling of :mod:`document_export_jsdoc`
(``@returns``) and :mod:`js_document_param_types` (``@param {T}``).

For an EXPORTED ``.js``/``.ts`` function/const-arrow with NO leading JSDoc whose
body contains one or more literal ``throw new <ErrorCtor>(...)`` statements with a
SIMPLE constructor identifier (``TypeError``, ``RangeError``, a project error
class), land a MINIMAL JSDoc carrying one ``@throws {<ErrorCtor>}`` line per
DISTINCT thrown constructor — read VERBATIM off the AST, in source order. It is
built from ONLY proven AST facts: a constructor name is never inferred, only
copied off a real ``throw new Identifier(...)`` node, so the JSDoc cannot misstate
the contract.

This is the JSDoc-family sibling that surfaces the FAILURE CONTRACT — the single
most commonly-omitted JSDoc fact. It inherits document-signature's HONESTY GATE
(the honest-no-op-beats-noise rule): a function that throws nothing, or throws an
UNPROVABLE shape (a ``throw <variable>`` / ``throw fn()`` / a member-expression
ctor ``new ns.Err()`` / a bare re-throw), is REFUSED — the driver returns
``throws_types is None`` for an unprovable shape and ``()`` for zero throws, and
either way this objective lands nothing rather than an empty/content-free
``@throws``. It lands ONLY when ``throws_types`` is non-None AND non-empty (at
least one PROVEN thrown constructor).

The pipeline mirrors the JS spine, but its VERIFY is the CHEAPEST sound one —
a JSDoc is leading trivia, so it changes ZERO runtime bytes and is
behaviour-identical BY CONSTRUCTION; NO ``npm``/``jest``/``tsc`` is ever run:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root; this is what
   makes the objective a clean NO-OP on a Python tree). Each own non-test
   ``.js``/``.ts`` source with at least one landable target is a candidate. The
   walk / source-suffix gate / jest-test refusal are reused verbatim from
   :mod:`app.execution.lang.js_adapter` (the shared JS machinery).
2. **PLAN** — :func:`plan_document_raises_jsdoc` reads the file, asks the driver
   (``ts_driver.js doc-targets``) for each exported, JSDoc-less node's name, the
   DISTINCT thrown-constructor set (or null when an unprovable throw is present),
   and the byte insertion offset, applies the honesty gate, builds the JSDoc text
   from facts, and splices it as leading trivia bottom-up (descending offset, so
   earlier offsets stay valid).
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.js.js_tool.reparse_exports_identical`) and asserts the
   exported-name set is unchanged (it can never differ for a comment insert, so
   a difference means a corrupt splice — refuse rather than land). This is the
   behaviour-identical proof that REPLACES the jest gate, reused UNCHANGED.
4. **LAND** — the ONE changed source is carried as a :class:`RenamePlan`
   (``originals`` for byte-for-byte rollback, ``new_contents`` for the documented
   source), applied by the shared gated/rollback writer like every objective.

Deterministic (pure AST → fixed JSDoc text, source order, byte-offset splice, no
clock/random), offline (the project owns its ``node_modules``; ``typescript`` is
global; Apex installs nothing), zero-token. Test/fixture files are refused as
WRITE targets — Apex never edits the suite. ``expensive=True`` (detection spawns
node, so the fast plan/ascend board skips the scan); ``scope_verify=False`` (a
docstring insert has no red-baseline problem — no full-suite veto to dodge — so
it needs NO ``SCOPE_VERIFY_ALLOWLIST`` entry).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.js.js_tool import JsDocTarget, doc_targets
from app.execution.lang.js_adapter import _walk_files, is_js_source
from app.execution.lang.js_adapter import JS_SOURCE_SUFFIXES as _JS_SUFFIXES
from app.execution.objectives.document_export_jsdoc import plan_jsdoc_insert

__all__ = [
    "plan_document_raises_jsdoc",
    "detect_raises_targets",
    "is_js_source",
    "raises_targets",
]


def _is_landable(target: JsDocTarget) -> bool:
    """The HONESTY GATE: ``True`` only when documenting ``target`` would carry a
    PROVEN failure-contract fact.

    The fact THIS template surfaces is the DISTINCT set of thrown constructors. The
    driver returns ``throws_types is None`` when ANY throw in the body is an
    unprovable shape (a variable / call / member-ctor / re-throw — we cannot read
    the ctor verbatim) and an EMPTY tuple when the body throws nothing. A target is
    landable iff ``throws_types`` is non-None AND non-empty (at least one provable
    thrown ctor → at least one ``@throws {Ctor}`` line). A function that throws
    nothing, or throws an unprovable shape, is REFUSED — an honest no-op, never a
    content-free ``@throws``."""
    return bool(target.throws_types)


def raises_targets(root: Path, rel: str) -> list[JsDocTarget]:
    """The exported, JSDoc-less targets in ``root/rel`` the honesty gate would
    actually document — i.e. at least one PROVEN thrown constructor (empty on a
    non-source/test target or on refuse).

    Refuses a non-JS-source or test/fixture file outright (:func:`is_js_source`),
    then keeps only the driver-found targets that pass :func:`_is_landable`."""
    if not is_js_source(rel):
        return []
    return [t for t in doc_targets(root, rel) if _is_landable(t)]


def _jsdoc_block(target: JsDocTarget) -> str:
    """The minimal JSDoc block for ``target`` as a single string ending in a
    newline, built from FACTS only: a name summary, then one ``@throws {Ctor}`` line
    per DISTINCT thrown constructor in source order (the honesty gate only lands
    targets where at least one exists). Nothing is invented; the ctor names are read
    VERBATIM off the AST, so the text is a fixed function of (name, throws_types)."""
    lines = ["/**", f" * {target.name}."]
    lines += [f" * @throws {{{t}}}" for t in target.throws_types or ()]
    lines.append(" */")
    return "\n".join(lines) + "\n"


def detect_raises_targets(project_root: str | Path) -> list[str]:
    """The own non-test JS/TS source files that have at least one landable
    ``@throws`` target, each pinned by the single-``package.json`` root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root, and what makes this a clean NO-OP on a Python (or any non-JS) tree.
    Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, _JS_SUFFIXES)
            if raises_targets(root, rel)]


def plan_document_raises_jsdoc(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the minimal ``@throws``-JSDoc plan for ONE source file, or an empty
    no-op plan (an honest refusal).

    Refuses a non-JS-source / test / fixture write target outright
    (:func:`is_js_source`, via :func:`raises_targets`). For each exported,
    JSDoc-less target with at least one PROVEN thrown constructor it splices a
    facts-only JSDoc (``@throws {Ctor}`` lines, verbatim ctor names) as leading
    trivia, then proves the splice behaviour-identical with the driver's re-parse
    oracle (same exported-name set, still parses) before recording it. An empty plan
    means nothing was landable or the oracle refused — nothing is touched (never-
    fake-green). Delegates to the SHARED :func:`plan_jsdoc_insert` spine (the splice
    + oracle + record steps document-export-jsdoc and the other JSDoc objectives
    share) with this objective's throws-set landability filter and ``@throws {Ctor}``
    block template — so the spine is reused, not cloned."""
    return plan_jsdoc_insert(project_root, rel, "document-raises-jsdoc",
                             raises_targets, _jsdoc_block)


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_document_raises_jsdoc`` would actually change —
    i.e. the plan lands a JSDoc. A file whose every target the oracle/honesty gate
    refuses does NOT count, so it never shows as remaining debt (an honest measure,
    exactly like the Python ``document-signature`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_raises_targets(root)
            if plan_document_raises_jsdoc(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an undocumented exported
    function whose body throws a PROVEN constructor set this objective can document.
    0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``document_raises_jsdoc`` move per documentable source file. The
    ``operator="document_raises_jsdoc"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="document_raises_jsdoc",
        target=f"{rel}:document-raises-jsdoc",
        description=f"document the thrown error types in {rel} with a JSDoc",
        build_plan=lambda r=rel: plan_document_raises_jsdoc(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns node (the driver parses each source), so flag it expensive:
# the fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective document-raises-jsdoc`.
# scope_verify is FALSE (unlike js-tdd-implement): a JSDoc is leading trivia that
# changes ZERO runtime bytes — there is no red-baseline a full-suite gate could
# wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
register(ObjectiveSpec(name="document-raises-jsdoc", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
