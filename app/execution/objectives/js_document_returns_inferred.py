"""Self-registering objective: js-document-returns-inferred — Apex's SEVENTH
JS/TS concrete landing, the PLAIN-JAVASCRIPT sibling of
:mod:`document_export_jsdoc` (``@returns`` from a DECLARED TS annotation).

For an EXPORTED ``.js``/``.ts`` function/const-arrow with NO leading JSDoc whose
return type is PROVABLE from its own literal ``return`` statements, land a MINIMAL
JSDoc carrying exactly one ``@returns {T}`` line — where ``T`` is read VERBATIM
off the AST literal kind (``true``/``false`` → ``boolean``, a string literal →
``string``, a numeric literal → ``number``, an array literal → ``Array``, an
object literal → ``Object``, ``new <Ctor>(...)`` → that constructor's name). A
type is NEVER inferred from a value flow / call result — only copied off a literal
return node — so the JSDoc cannot misstate it.

This serves the DOMINANT real-project case the existing JSDoc family CANNOT:
:mod:`document_export_jsdoc` (and :mod:`js_document_param_types`) emit an
``@returns {T}`` ONLY from a DECLARED TS return annotation, so a PLAIN-JS export
(``export function isReady(x) { return true; }``) gets no ``@returns`` at all. This
objective fires EXACTLY there — when ``return_type is None`` (no declared TS
annotation) AND a literal-return type is provable.

THE DISJOINTNESS CRUX (denetçi-critical). There is a third ``@returns`` emitter in
the JS doc family now, so it MUST be provably mutually exclusive with the others.
The predicate is the typed-vs-untyped split: ``document_export_jsdoc`` fires ONLY
when a TS return type is DECLARED (``return_type is not None``); THIS objective
fires ONLY when ``return_type is None``. On a given node they can never both emit —
a node either has a declared TS return (document-export-jsdoc's surface, THIS
refuses) or it does not (THIS may fire, document-export-jsdoc refuses). So no node
ever receives an ``@returns`` from two planners. (The queued PRE-EXISTING
double-``@returns`` concern between ``document_export_jsdoc`` and
``js_document_param_types`` — both emit ``@returns`` when a return type is DECLARED
— is a SEPARATE, out-of-scope finding; THIS objective is disjoint from BOTH by the
``return_type is None`` gate, so it does not touch or compound that.)

The pipeline mirrors the JS spine, but its VERIFY is the CHEAPEST sound one —
a JSDoc is leading trivia, so it changes ZERO runtime bytes and is
behaviour-identical BY CONSTRUCTION; NO ``npm``/``jest``/``tsc`` is ever run:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root; this is what
   makes the objective a clean NO-OP on a Python tree). Each own non-test
   ``.js``/``.ts`` source with at least one landable target is a candidate. The
   walk / source-suffix gate / jest-test refusal are reused verbatim from
   :mod:`app.execution.lang.js_adapter` (the shared JS machinery).
2. **PLAN** — :func:`plan_js_document_returns_inferred` reads the file, asks the
   driver (``ts_driver.js doc-targets``) for each exported, JSDoc-less node's name,
   declared return type (or null), the LITERAL-return-inferred type (or null), and
   the byte insertion offset, applies the honesty + disjointness gate, builds the
   ``@returns {T}`` JSDoc from facts, and splices it as leading trivia bottom-up
   (descending offset, so earlier offsets stay valid).
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
    "plan_js_document_returns_inferred",
    "detect_returns_inferred_targets",
    "is_js_source",
    "returns_inferred_targets",
]


def _is_landable(target: JsDocTarget) -> bool:
    """The HONESTY + DISJOINTNESS GATE: ``True`` only when documenting ``target``
    would carry a PROVEN-from-literal return type AND no DECLARED TS return exists.

    Two conjuncts:

    * **Honesty** — the fact THIS template surfaces is the type PROVEN from the
      body's own literal ``return`` statements (the driver returns
      ``returns_inferred is None`` when ANY return is non-literal / void / ``null`` /
      heterogeneous, or there is no return at all). A target is landable only when
      ``returns_inferred`` is non-``None`` (a provable literal return → one
      ``@returns {T}`` line). An unprovable return is REFUSED — an honest no-op,
      never a guessed ``@returns``.
    * **Disjointness** — THE mutual-exclusion predicate with
      :mod:`document_export_jsdoc`: this fires ONLY when ``return_type is None`` (no
      DECLARED TS return annotation). A node that DECLARES a TS return is
      document-export-jsdoc's surface (it emits the declared ``@returns {T}`` from
      ``return_type``), so THIS objective REFUSES it — guaranteeing no node ever
      gets an ``@returns`` from two planners (the typed-vs-untyped split)."""
    return target.return_type is None and target.returns_inferred is not None


def returns_inferred_targets(root: Path, rel: str) -> list[JsDocTarget]:
    """The exported, JSDoc-less targets in ``root/rel`` the honesty + disjointness
    gate would actually document — i.e. an UNDECLARED return type that is PROVABLE
    from literal returns (empty on a non-source/test target or on refuse).

    Refuses a non-JS-source or test/fixture file outright (:func:`is_js_source`),
    then keeps only the driver-found targets that pass :func:`_is_landable`."""
    if not is_js_source(rel):
        return []
    return [t for t in doc_targets(root, rel) if _is_landable(t)]


def _jsdoc_block(target: JsDocTarget) -> str:
    """The minimal JSDoc block for ``target`` as a single string ending in a
    newline, built from FACTS only: a name summary, then exactly one
    ``@returns {T}`` line carrying the type PROVEN from the body's literal returns
    (the honesty gate only lands targets where one exists). NO ``@param`` lines —
    that is js-document-param-types' surface, kept disjoint. Nothing is invented;
    the text is a fixed function of (name, returns_inferred), byte-for-byte matching
    the other JSDoc-family emitters' ``@returns {T}`` formatting."""
    return (f"/**\n * {target.name}.\n"
            f" * @returns {{{target.returns_inferred}}}\n */\n")


def detect_returns_inferred_targets(project_root: str | Path) -> list[str]:
    """The own non-test JS/TS source files that have at least one landable
    inferred-``@returns`` target, each pinned by the single-``package.json`` root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root, and what makes this a clean NO-OP on a Python (or any non-JS) tree.
    Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, _JS_SUFFIXES)
            if returns_inferred_targets(root, rel)]


def plan_js_document_returns_inferred(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the minimal inferred-``@returns``-JSDoc plan for ONE source file, or an
    empty no-op plan (an honest refusal).

    Refuses a non-JS-source / test / fixture write target outright
    (:func:`is_js_source`, via :func:`returns_inferred_targets`). For each exported,
    JSDoc-less target with NO declared TS return but a PROVABLE literal-return type it
    splices a facts-only JSDoc (one ``@returns {T}`` line) as leading trivia, then
    proves the splice behaviour-identical with the driver's re-parse oracle (same
    exported-name set, still parses) before recording it. An empty plan means nothing
    was landable or the oracle refused — nothing is touched (never-fake-green).
    Delegates to the SHARED :func:`plan_jsdoc_insert` spine (the splice + oracle +
    record steps document-export-jsdoc and the other JSDoc objectives share) with
    this objective's undeclared-but-inferable landability filter and ``@returns {T}``
    block template — so the spine is reused, not cloned."""
    return plan_jsdoc_insert(project_root, rel, "js-document-returns-inferred",
                             returns_inferred_targets, _jsdoc_block)


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_js_document_returns_inferred`` would actually
    change — i.e. the plan lands a JSDoc. A file whose every target the oracle/honesty
    gate refuses does NOT count, so it never shows as remaining debt (an honest
    measure, exactly like the Python ``document-signature`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_returns_inferred_targets(root)
            if plan_js_document_returns_inferred(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an undocumented exported
    function whose return type this objective can PROVE from literal returns and
    document. 0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``js_document_returns_inferred`` move per documentable source file. The
    ``operator="js_document_returns_inferred"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_document_returns_inferred",
        target=f"{rel}:js-document-returns-inferred",
        description=f"document the inferred return type in {rel} with a JSDoc",
        build_plan=lambda r=rel: plan_js_document_returns_inferred(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns node (the driver parses each source), so flag it expensive:
# the fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-document-returns-inferred`.
# scope_verify is FALSE (unlike js-tdd-implement): a JSDoc is leading trivia that
# changes ZERO runtime bytes — there is no red-baseline a full-suite gate could
# wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
register(ObjectiveSpec(name="js-document-returns-inferred", fitness=fitness,
                       moves=moves, expensive=True, scope_verify=False))
