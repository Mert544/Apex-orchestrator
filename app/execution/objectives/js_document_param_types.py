"""Self-registering objective: js-document-param-types — Apex's FIFTH JS/TS
concrete landing, the missing HALF of :mod:`document_export_jsdoc`.

For an EXPORTED ``.js``/``.ts`` function or ``const`` arrow whose parameters
carry DECLARED type annotations but that has NO leading JSDoc, land a MINIMAL
JSDoc block whose ``@param {T} name`` lines carry the DECLARED parameter types
read VERBATIM off the TS annotation (plus an ``@returns {T}`` when a return type
is declared). It is built from ONLY proven AST facts — a type is never inferred,
only copied from the author's own annotation, so the JSDoc cannot misstate it.

This is the complement of :mod:`document_export_jsdoc`: that objective lands a
JSDoc only when a DECLARED RETURN TYPE exists and emits bare ``@param name`` lines
(no type); this one surfaces the PARAMETER TYPES — a strictly richer, maintainer-
valued fact (``@param {string} host`` vs ``@param host``). It inherits document-
signature's HONESTY GATE (the honest-no-op-beats-noise rule): a name-only /
untyped ``@param`` is a pure RESTATEMENT of the signature and adds nothing, so it
lands ONLY when at least one parameter has a DECLARED type (a name-only/untyped
target — plain JS or untyped TS — is REFUSED, an honest no-op never a content-
free JSDoc).

The pipeline mirrors the JS spine, but its VERIFY is the CHEAPEST sound one —
a JSDoc is leading trivia, so it changes ZERO runtime bytes and is
behaviour-identical BY CONSTRUCTION; NO ``npm``/``jest``/``tsc`` is ever run:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root; this is what
   makes the objective a clean NO-OP on a Python tree). Each own non-test
   ``.js``/``.ts`` source with at least one landable target is a candidate. The
   walk / source-suffix gate / jest-test refusal are reused verbatim from
   :mod:`app.execution.lang.js_adapter` (the shared JS machinery).
2. **PLAN** — :func:`plan_js_document_param_types` reads the file, asks the driver
   (``ts_driver.js doc-targets``) for each exported, JSDoc-less node's name,
   declared param names, per-param declared types (or null), declared return-type
   text (or null), and the byte insertion offset, applies the honesty gate, builds
   the JSDoc text from facts, and splices it as leading trivia bottom-up
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
    "plan_js_document_param_types",
    "detect_param_type_targets",
    "is_js_source",
    "param_type_targets",
]


def _is_landable(target: JsDocTarget) -> bool:
    """The HONESTY GATE: ``True`` only when documenting ``target`` would carry a
    fact the bare signature does not already state.

    A JSDoc minted from only the name + parameter names is a pure restatement of
    the signature and adds nothing (the document-signature ``_adds_semantic_content
    => False`` rule). The fact THIS template surfaces beyond the signature is the
    DECLARED PARAMETER TYPES, so a target is landable iff AT LEAST ONE parameter
    has a declared type (a TS ``host: string`` → an ``@param {string} host``). A
    plain-JS / untyped-TS target (every ``param_types`` entry ``None``) is
    REFUSED — an honest no-op, never a content-free JSDoc."""
    return any(t is not None for t in target.param_types)


def param_type_targets(root: Path, rel: str) -> list[JsDocTarget]:
    """The exported, JSDoc-less targets in ``root/rel`` the honesty gate would
    actually document — i.e. at least one parameter carries a declared type (empty
    on a non-source/test target or on refuse).

    Refuses a non-JS-source or test/fixture file outright (:func:`is_js_source`),
    then keeps only the driver-found targets that pass :func:`_is_landable`."""
    if not is_js_source(rel):
        return []
    return [t for t in doc_targets(root, rel) if _is_landable(t)]


def _param_line(name: str, declared: str | None) -> str:
    """One ``@param`` line for ``name``: ``@param {T} name`` when the author
    DECLARED a type ``T`` (read verbatim), else a bare ``@param name`` (an untyped
    param of a function that has at least one typed param — its name is still a
    fact, but no type is invented). Pure function of (name, declared)."""
    return f" * @param {{{declared}}} {name}" if declared is not None \
        else f" * @param {name}"


def _jsdoc_block(target: JsDocTarget) -> str:
    """The minimal JSDoc block for ``target`` as a single string ending in a
    newline, built from FACTS only: a name summary, one ``@param`` line per declared
    parameter carrying its VERBATIM declared type when present (the honesty gate
    only lands targets where at least one does), and an ``@returns {T}`` when a
    return type was DECLARED. Nothing is invented; the text is a fixed function of
    (name, params, param_types, return_type)."""
    lines = ["/**", f" * {target.name}."]
    lines += [_param_line(name, declared)
              for name, declared in zip(target.params, target.param_types)]
    if target.return_type is not None:
        lines.append(f" * @returns {{{target.return_type}}}")
    lines.append(" */")
    return "\n".join(lines) + "\n"


def detect_param_type_targets(project_root: str | Path) -> list[str]:
    """The own non-test JS/TS source files that have at least one landable typed-
    param JSDoc target, each pinned by the single-``package.json`` root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root, and what makes this a clean NO-OP on a Python (or any non-JS) tree.
    Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, _JS_SUFFIXES)
            if param_type_targets(root, rel)]


def plan_js_document_param_types(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the minimal typed-param-JSDoc plan for ONE source file, or an empty
    no-op plan (an honest refusal).

    Refuses a non-JS-source / test / fixture write target outright
    (:func:`is_js_source`, via :func:`param_type_targets`). For each exported,
    JSDoc-less target with at least one declared parameter type it splices a
    facts-only JSDoc (``@param {T} name`` lines, verbatim types) as leading trivia,
    then proves the splice behaviour-identical with the driver's re-parse oracle
    (same exported-name set, still parses) before recording it. An empty plan means
    nothing was landable or the oracle refused — nothing is touched (never-fake-
    green). Delegates to the SHARED :func:`plan_jsdoc_insert` spine (the splice +
    oracle + record steps document-export-jsdoc and this objective share) with this
    objective's param-typed landability filter and ``@param {T} name`` block
    template — so the spine is reused, not cloned."""
    return plan_jsdoc_insert(project_root, rel, "js-document-param-types",
                             param_type_targets, _jsdoc_block)


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_js_document_param_types`` would actually change —
    i.e. the plan lands a JSDoc. A file whose every target the oracle/honesty gate
    refuses does NOT count, so it never shows as remaining debt (an honest measure,
    exactly like the Python ``document-signature`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_param_type_targets(root)
            if plan_js_document_param_types(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an undocumented exported
    signature whose parameters carry declared types this objective can document.
    0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``js_document_param_types`` move per documentable source file. The
    ``operator="js_document_param_types"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_document_param_types",
        target=f"{rel}:js-document-param-types",
        description=f"document the exported parameter types in {rel} with a JSDoc",
        build_plan=lambda r=rel: plan_js_document_param_types(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns node (the driver parses each source), so flag it expensive:
# the fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-document-param-types`.
# scope_verify is FALSE (unlike js-tdd-implement): a JSDoc is leading trivia that
# changes ZERO runtime bytes — there is no red-baseline a full-suite gate could
# wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
register(ObjectiveSpec(name="js-document-param-types", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
