"""Self-registering objective: document-export-jsdoc — Apex's SECOND JS/TS
concrete landing, the JS/TS sibling of :mod:`document_signature`.

For an EXPORTED ``.js``/``.ts`` function or ``const`` arrow that carries NO
leading JSDoc, land a MINIMAL JSDoc block built from ONLY proven AST facts:

  - one ``@param <name>`` line per DECLARED parameter name, read straight off the
    AST (names only — never an invented description), and
  - for TypeScript, an ``@returns {T}`` whose ``T`` is the function's DECLARED
    return-type annotation, read VERBATIM (an author fact).

It inherits document-signature's HONESTY GATE (the honest-no-op-beats-noise
rule). A JSDoc built from ONLY the name and the parameter names is a pure
RESTATEMENT of the signature and adds nothing a maintainer would value, so this
objective REFUSES it. Concretely it lands a JSDoc ONLY when the target carries a
DECLARED return type (a TS ``@returns {T}`` surfaces a fact the bare signature
reader would not) — so under this names+params+``@returns`` template it is, like
its Python sibling today, a deliberate near-total NO-OP that lands only when a
real fact (a declared return type) exists. On plain JS (no annotations) it lands
nothing.

The pipeline mirrors the JS spine, but its VERIFY is the CHEAPEST sound one —
a JSDoc is leading trivia, so it changes ZERO runtime bytes and is
behaviour-identical BY CONSTRUCTION; NO ``npm``/``jest``/``tsc`` is ever run:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root; this is what
   makes the objective a clean NO-OP on a Python tree). Each own non-test
   ``.js``/``.ts`` source with at least one landable target is a candidate. The
   walk / source-suffix gate / jest-test refusal are reused verbatim from
   :mod:`app.execution.lang.js_adapter` (the shared JS machinery).
2. **PLAN** — :func:`plan_document_export_jsdoc` reads the file, asks the driver
   (``ts_driver.js doc-targets``) for each exported, JSDoc-less node's name,
   declared param names, declared return-type text (or null), and the byte
   insertion offset, applies the honesty gate, builds the JSDoc text from facts,
   and splices it as leading trivia bottom-up (descending offset, so earlier
   offsets stay valid).
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.js.js_tool.reparse_exports_identical`) and asserts the
   exported-name set is unchanged (it can never differ for a comment insert, so
   a difference means a corrupt splice — refuse rather than land). This is the
   behaviour-identical proof that REPLACES the jest gate.
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

from collections.abc import Callable
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.js.js_tool import JsDocTarget, doc_targets, reparse_exports_identical
from app.execution.lang.js_adapter import (
    _read,
    _u16_to_codepoint,
    _walk_files,
    is_js_source,
)
from app.execution.lang.js_adapter import JS_SOURCE_SUFFIXES as _JS_SUFFIXES

__all__ = [
    "plan_document_export_jsdoc",
    "detect_jsdoc_targets",
    "is_js_source",
    "documentable_targets",
    "splice_jsdoc",
    "plan_jsdoc_insert",
]


def _is_landable(target: JsDocTarget) -> bool:
    """The HONESTY GATE: ``True`` only when documenting ``target`` would carry a
    fact the bare signature does not already state.

    A JSDoc minted from only the name + parameter names is a pure restatement of
    the signature and adds nothing (the document-signature ``_adds_semantic_content
    => False`` rule). The one fact this template can surface beyond the signature
    is a DECLARED return type, so a target is landable iff it has one (a TS
    ``: T`` → an ``@returns {T}``). A plain-JS target with no annotation is
    REFUSED — an honest no-op, never a content-free JSDoc."""
    return target.return_type is not None


def documentable_targets(root: Path, rel: str) -> list[JsDocTarget]:
    """The exported, JSDoc-less targets in ``root/rel`` the honesty gate would
    actually document (empty on a non-source/test target or on refuse).

    Refuses a non-JS-source or test/fixture file outright (:func:`is_js_source`),
    then keeps only the driver-found targets that pass :func:`_is_landable`."""
    if not is_js_source(rel):
        return []
    return [t for t in doc_targets(root, rel) if _is_landable(t)]


def _jsdoc_block(target: JsDocTarget) -> str:
    """The minimal JSDoc block for ``target`` as a single string ending in a
    newline, built from FACTS only: a name summary, one ``@param <name>`` line per
    declared parameter, and an ``@returns {T}`` carrying the DECLARED return type
    (always present — the honesty gate only lands targets that have one). Nothing
    is invented; the text is a fixed function of (name, params, return_type)."""
    lines = ["/**", f" * {target.name}."]
    lines += [f" * @param {name}" for name in target.params]
    lines.append(f" * @returns {{{target.return_type}}}")
    lines.append(" */")
    return "\n".join(lines) + "\n"


def splice_jsdoc(source: str, targets: list[JsDocTarget],
                 block_fn: Callable[[JsDocTarget], str]) -> str | None:
    """``source`` with a JSDoc block (minted by ``block_fn``) spliced in as leading
    trivia at each target's ``insert_offset``, or ``None`` when any offset is out of
    range or splits a surrogate pair (a stale scan — refuse rather than corrupt the
    file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not shift
    a later offset. The driver's ``insert_offset`` is a UTF-16 code-UNIT offset, so
    it is re-indexed to a code-POINT index via :func:`_u16_to_codepoint` against the
    CURRENT ``new_source`` before each insertion (they diverge by +1 per astral char
    upstream) — the surrounding formatting and every other character survive
    untouched (the JSDoc is leading trivia, so ZERO runtime bytes change).
    ``block_fn`` is the only varying part across the JSDoc-insert objectives (this
    module's ``@param name`` template vs js-document-param-types' ``@param {T}
    name``), so it is injected — the splice spine itself is shared, not cloned."""
    new_source = source
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = _u16_to_codepoint(new_source, target.insert_offset)
        if off is None:
            return None
        new_source = new_source[:off] + block_fn(target) + new_source[off:]
    return new_source if new_source != source else None


def plan_jsdoc_insert(project_root: str | Path, rel: str, new_name: str,
                      targets_fn: Callable[[Path, str], list[JsDocTarget]],
                      block_fn: Callable[[JsDocTarget], str]) -> RenamePlan:
    """The SHARED JSDoc-insert plan spine for ONE source file, or an empty no-op
    plan (an honest refusal).

    Both JSDoc-insert objectives — this module (``@param name`` + ``@returns {T}``,
    landable on a declared return type) and js-document-param-types (``@param {T}
    name``, landable on a declared param type) — differ ONLY in their
    landability-filtered ``targets_fn`` and their ``block_fn``; the splice + re-parse
    oracle + record steps are identical, so they live HERE once rather than being
    cloned. Splices a facts-only JSDoc as leading trivia, then proves the splice
    behaviour-identical with the driver's re-parse oracle
    (:func:`reparse_exports_identical` — same exported-name set, still parses)
    before recording it. An empty plan means nothing was landable or the oracle
    refused — nothing is touched (never-fake-green)."""
    plan = RenamePlan(old=rel, new=new_name)
    root = Path(project_root)
    targets = targets_fn(root, rel)
    if not targets:
        return plan  # non-JS / test / nothing landable — honest no-op
    target_file = root / rel
    original = _read(target_file)
    if not original and not target_file.exists():
        return plan  # unreadable / missing target — no-op
    documented = splice_jsdoc(original, targets, block_fn)
    if documented is None:
        return plan  # a stale offset / no-change splice — refuse
    if not reparse_exports_identical(root, rel, documented):
        return plan  # the splice did not re-parse identical — refuse, land nothing
    plan.originals[rel] = original
    plan.new_contents[rel] = documented
    plan.edits_by_file[rel] = len(targets)
    return plan


def detect_jsdoc_targets(project_root: str | Path) -> list[str]:
    """The own non-test JS/TS source files that have at least one landable JSDoc
    target, each pinned by the single-``package.json`` root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root, and what makes this a clean NO-OP on a Python (or any non-JS) tree.
    Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    return [rel for rel in _walk_files(root, _JS_SUFFIXES)
            if documentable_targets(root, rel)]


def plan_document_export_jsdoc(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the minimal-JSDoc plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-JS-source / test / fixture write target outright
    (:func:`is_js_source`, via :func:`documentable_targets`). For each exported,
    JSDoc-less, return-typed target it splices a facts-only JSDoc as leading
    trivia, then proves the splice behaviour-identical with the driver's re-parse
    oracle (:func:`reparse_exports_identical` — same exported-name set, still
    parses) before recording it. An empty plan means nothing was landable or the
    oracle refused — nothing is touched (never-fake-green). Delegates to the shared
    :func:`plan_jsdoc_insert` spine with this objective's return-typed
    landability filter and ``@param name``/``@returns {T}`` block template."""
    return plan_jsdoc_insert(project_root, rel, "document-export-jsdoc",
                             documentable_targets, _jsdoc_block)


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_document_export_jsdoc`` would actually change —
    i.e. the plan lands a JSDoc. A file whose every target the oracle/honesty gate
    refuses does NOT count, so it never shows as remaining debt (an honest measure,
    exactly like the Python ``document-signature`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_jsdoc_targets(root)
            if plan_document_export_jsdoc(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own JS/TS sources still have an undocumented exported,
    return-typed signature this objective can document. 0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``document_export_jsdoc`` move per documentable source file. The
    ``operator="document_export_jsdoc"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="document_export_jsdoc",
        target=f"{rel}:document-export-jsdoc",
        description=f"document the exported signatures in {rel} with a JSDoc",
        build_plan=lambda r=rel: plan_document_export_jsdoc(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns node (the driver parses each source), so flag it expensive:
# the fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective document-export-jsdoc`.
# scope_verify is FALSE (unlike js-tdd-implement): a JSDoc is leading trivia that
# changes ZERO runtime bytes — there is no red-baseline a full-suite gate could
# wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
register(ObjectiveSpec(name="document-export-jsdoc", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
