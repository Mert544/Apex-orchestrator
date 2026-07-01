"""js-document-returns-inferred develop objective — Apex's SEVENTH JS/TS concrete
landing, the PLAIN-JAVASCRIPT sibling of document-export-jsdoc.

For an EXPORTED ``.js``/``.ts`` function/const-arrow with NO leading JSDoc and NO
DECLARED TS return type, whose return type is PROVABLE from its OWN literal
``return`` statements, this lands a minimal JSDoc carrying exactly one
``@returns {T}`` line — the literal kind read VERBATIM off the AST
(``true``/``false`` → ``boolean``, string → ``string``, numeric → ``number``,
array → ``Array``, object → ``Object``, ``new <Ctor>()`` → the ctor). It is the
case the typed JSDoc family CANNOT serve: document-export-jsdoc emits ``@returns``
ONLY from a DECLARED TS return annotation.

Covers: the driver (``doc-targets`` now also emits ``returnsInferred``, the
literal-return type or null); each literal kind landing the right ``@returns`` +
reparse-identical; THE DISJOINTNESS CRUX (a declared-TS-return export → THIS
refuses; no node ever gets ``@returns`` from two planners on a shared fixture); the
REFUSE set (already-JSDoc'd / non-literal / heterogeneous / bare-return / no-return
/ non-exported / test-file); determinism + idempotence; UTF-16 emoji-offset safety;
plus objective registration / the FIVE parity registries the new objective must
appear in and the bumped count-pins (86→87 total, 41→42 CONCRETE). The heavy node
tests skip cleanly when node + global ``typescript`` aren't available; every pure /
refusal / parity test always runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_tool import (
    JsDocTarget,
    doc_targets,
    exported_names,
    global_node_modules,
    reparse_exports_identical,
)
from app.execution.objectives.js_document_returns_inferred import (
    _is_landable,
    _jsdoc_block,
    detect_returns_inferred_targets,
    is_js_source,
    plan_js_document_returns_inferred,
    returns_inferred_targets,
)

_PHRASE = "the inferred return type to document in jsdoc"

# A clean plain-JS module (the dominant case the typed doc family can't serve):
# six exported, JSDoc-less functions whose return type is PROVABLE from a single
# literal return — one per literal kind the inference maps verbatim.
_PLAIN_JS = (
    "export function isReady(x) { return true; }\n"
    "export function greet() { return \"hi\"; }\n"
    "export function count() { return 42; }\n"
    "export function items() { return [1, 2, 3]; }\n"
    "export function cfg() { return { a: 1 }; }\n"
    "export function when() { return new Date(); }\n"
)


# --- environment guards (the heavy node path is opt-in by availability) -------

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (doc-targets / doc-verify) to run."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _with_package_json(root: Path) -> Path:
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0" }\n', encoding="utf-8")
    return root


def _target(name: str, return_type: str | None, returns_inferred: str | None) -> JsDocTarget:
    """A bare JsDocTarget carrying just the return facts the gate / block template
    read — for the pure-Python unit tests (no node)."""
    return JsDocTarget(name=name, params=(), param_types=(), return_type=return_type,
                       returns_inferred=returns_inferred, throws_types=(),
                       insert_offset=0)


# --- the refusal rule for non-JS files (always runs — pure, no node) ----------

def test_refuses_non_js_python_file():
    assert not is_js_source("app/mod.py")
    assert not is_js_source("setup.py")


def test_refuses_non_source_file():
    assert not is_js_source("README.md")
    assert not is_js_source("data.json")


def test_accepts_js_and_ts_sources():
    assert is_js_source("src/api.js")
    assert is_js_source("src/api.ts")
    assert is_js_source("x.mjs")
    assert is_js_source("d.cjs")


def test_refuses_jest_test_and_fixture_write_targets():
    # A jest test file is never a WRITE target (Apex never edits the suite).
    assert not is_js_source("src/api.test.js")
    assert not is_js_source("a.spec.ts")
    assert not is_js_source("__tests__/api.ts")


def test_plan_refuses_non_js_file_outright(tmp_path: Path):
    # A .py path: the plan refuses it before touching anything — the load-bearing
    # no-op on the Python path.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_js_document_returns_inferred(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/api.js", _PLAIN_JS)
    assert detect_returns_inferred_targets(str(tmp_path)) == []


# --- the honesty + DISJOINTNESS gate (pure, no node) --------------------------

def test_landable_only_when_plain_js_literal_return():
    # The gate fires ONLY when no TS return is declared AND a literal-return type is
    # provable — the honesty + disjointness conjunction.
    assert _is_landable(_target("f", None, "boolean")) is True  # plain JS, provable


def test_not_landable_when_ts_return_declared():
    # THE DISJOINTNESS PREDICATE: a node that DECLARES a TS return type is
    # document-export-jsdoc's surface; THIS refuses even when the literal is also
    # inferable, so no node ever gets @returns from both.
    assert _is_landable(_target("f", "number", "number")) is False  # declared -> defer
    assert _is_landable(_target("f", "boolean", "boolean")) is False


def test_not_landable_when_no_inferred_type():
    # No provable literal-return type -> refuse (honest no-op, never a guess).
    assert _is_landable(_target("f", None, None)) is False


def test_jsdoc_block_is_exactly_one_returns_line_no_params():
    # The block is byte-for-byte the family's @returns formatting, with NO @param
    # lines (that is js-document-param-types' surface — stay disjoint).
    block = _jsdoc_block(_target("isReady", None, "boolean"))
    assert block == "/**\n * isReady.\n * @returns {boolean}\n */\n"
    assert "@param" not in block


# --- the driver: returnsInferred fact (needs node) ----------------------------

@_needs_node
def test_driver_infers_each_literal_kind(tmp_path: Path):
    root = _project(tmp_path, "src/api.js", _PLAIN_JS)
    by_name = {t.name: t for t in doc_targets(root, "src/api.js")}
    assert by_name["isReady"].returns_inferred == "boolean"
    assert by_name["greet"].returns_inferred == "string"
    assert by_name["count"].returns_inferred == "number"
    assert by_name["items"].returns_inferred == "Array"
    assert by_name["cfg"].returns_inferred == "Object"
    assert by_name["when"].returns_inferred == "Date"  # `new Date()` -> ctor name
    # all plain JS: no declared TS return type on any
    assert all(t.return_type is None for t in by_name.values())


@_needs_node
def test_driver_concise_arrow_body_is_an_implicit_return(tmp_path: Path):
    # A concise (expression-bodied) arrow has ONE implicit return — mapped exactly.
    src = "export const ok = (x) => true;\nexport const n = () => 99;\n"
    root = _project(tmp_path, "src/arrow.js", src)
    by_name = {t.name: t for t in doc_targets(root, "src/arrow.js")}
    assert by_name["ok"].returns_inferred == "boolean"
    assert by_name["n"].returns_inferred == "number"


@_needs_node
def test_driver_refuses_unprovable_and_heterogeneous_returns(tmp_path: Path):
    src = (
        "export function call() { return foo(); }\n"           # non-literal -> null
        "export function ident(x) { return x; }\n"             # identifier -> null
        "export function neg() { return -1; }\n"               # unary, not literal -> null
        "export function hetero(b) { if (b) return true; return \"x\"; }\n"  # mixed -> null
        "export function bare() { return; }\n"                 # void -> null
        "export function voidnull() { return null; }\n"        # null -> null
        "export function noret() { let y = 1; }\n"             # no return -> null
        "export function tmpl(x) { return `hi ${x}`; }\n"      # interpolated -> null
        "export function member() { return new ns.Foo(); }\n"  # member ctor -> null
    )
    root = _project(tmp_path, "src/u.js", src)
    for t in doc_targets(root, "src/u.js"):
        assert t.returns_inferred is None, f"{t.name} should be unprovable"


@_needs_node
def test_driver_own_scope_only_ignores_nested_returns(tmp_path: Path):
    # A return inside a nested function is THAT function's contract, not the
    # documented one — the own-scope walk does not descend into it.
    src = "export function outer() { const f = () => \"inner\"; return 7; }\n"
    root = _project(tmp_path, "src/nest.js", src)
    by_name = {t.name: t for t in doc_targets(root, "src/nest.js")}
    assert by_name["outer"].returns_inferred == "number"  # 7, not "inner"


# --- the DEFINITE-RETURN guard (the never-fake-green fix) ---------------------
# A body that returns a literal on SOME paths but can FALL THROUGH to the end
# returns `undefined` on the tail — so its type is `T|undefined`, NOT `T`, and an
# `@returns {T}` would be a FALSE fact. The guard requires the body's LAST
# statement to be an unconditional `return <literal>` or a `throw`; otherwise the
# type is REFUSED (refuse-on-ambiguity).

@_needs_node
def test_if_only_fall_through_is_refused(tmp_path: Path):
    # THE regression test for the soundness bug: `if(x) return true;` with NO
    # trailing return can implicitly return undefined -> boolean|undefined, NOT
    # boolean. The last statement is the `if`, not a return/throw -> REFUSE.
    root = _with_package_json(tmp_path)
    _project(root, "src/ft.js", "export function f(x) { if (x) return true; }\n")
    assert doc_targets(root, "src/ft.js")[0].returns_inferred is None
    assert returns_inferred_targets(root, "src/ft.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/ft.js").new_contents == {}


@_needs_node
def test_loop_fall_through_is_refused(tmp_path: Path):
    # A `for`/loop that returns a literal inside can COMPLETE without returning ->
    # the tail returns undefined. The last statement is the `for`, not a
    # return/throw -> REFUSE.
    root = _with_package_json(tmp_path)
    _project(root, "src/loop.js",
             "export function k(a) { for (const x of a) { if (x) return true; } }\n")
    assert doc_targets(root, "src/loop.js")[0].returns_inferred is None
    assert returns_inferred_targets(root, "src/loop.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/loop.js").new_contents == {}


@_needs_node
def test_trailing_return_is_accepted(tmp_path: Path):
    # `if(x) return true; return false;` — the trailing `return false` makes the
    # tail path provably return, and both returns are `boolean` and agree -> ACCEPT.
    root = _with_package_json(tmp_path)
    _project(root, "src/tr.js",
             "export function h(x) { if (x) return true; return false; }\n")
    assert doc_targets(root, "src/tr.js")[0].returns_inferred == "boolean"
    plan = plan_js_document_returns_inferred(str(root), "src/tr.js")
    landed = plan.new_contents["src/tr.js"]
    assert " * @returns {boolean}\n */\nexport function h" in landed
    assert reparse_exports_identical(root, "src/tr.js", landed)


@_needs_node
def test_concise_arrow_still_accepted_after_guard(tmp_path: Path):
    # The concise (expression-bodied) arrow always returns its body expression, so
    # it bypasses the block-tail guard and stays ACCEPTED (no regression).
    root = _with_package_json(tmp_path)
    _project(root, "src/ca.js", "export const ok = (x) => true;\n")
    assert doc_targets(root, "src/ca.js")[0].returns_inferred == "boolean"
    plan = plan_js_document_returns_inferred(str(root), "src/ca.js")
    assert " * @returns {boolean}\n */\nexport const ok" in plan.new_contents["src/ca.js"]


@_needs_node
def test_trailing_throw_is_accepted_when_a_literal_return_exists(tmp_path: Path):
    # A tail `throw` also hands off control off the end (no implicit-undefined
    # fall-through), so a body whose only return is a literal and whose tail throws
    # is ACCEPTED — the function returns the literal or throws, never undefined.
    root = _with_package_json(tmp_path)
    _project(root, "src/tt.js",
             "export function g(x) { if (x) return true; throw new Error('no'); }\n")
    assert doc_targets(root, "src/tt.js")[0].returns_inferred == "boolean"


@_needs_node
def test_exhaustive_if_else_without_trailing_return_is_conservatively_refused(tmp_path: Path):
    # DELIBERATELY conservative: an exhaustive `if/else` where BOTH arms return but
    # there is no trailing return is REFUSED (the simple tail rule does not prove
    # exhaustiveness). Refuse-on-ambiguity is the correct posture — refusing a valid
    # exhaustive case is fine; accepting ANY fall-through is not.
    root = _with_package_json(tmp_path)
    _project(root, "src/ie.js",
             "export function f(x) { if (x) { return true; } else { return false; } }\n")
    assert doc_targets(root, "src/ie.js")[0].returns_inferred is None
    assert plan_js_document_returns_inferred(str(root), "src/ie.js").new_contents == {}


# --- ASYNC wrapping + GENERATOR refusal (two more never-fake-green fixes) -----
# An async function's `return T` is a `Promise<T>` at runtime, so it MUST emit
# `@returns {Promise<T>}`, never a bare `{T}`. A generator's `return` is the
# iterator's return value (not a simple @returns type), so it is REFUSED.

@_needs_node
def test_async_function_returns_promise_wrapped_type(tmp_path: Path):
    # `async function af(x){ return true; }` is Promise<boolean>, NOT boolean.
    root = _with_package_json(tmp_path)
    _project(root, "src/af.js", "export async function af(x) { return true; }\n")
    assert doc_targets(root, "src/af.js")[0].returns_inferred == "Promise<boolean>"
    plan = plan_js_document_returns_inferred(str(root), "src/af.js")
    landed = plan.new_contents["src/af.js"]
    assert " * @returns {Promise<boolean>}\n */\nexport async function af" in landed
    assert reparse_exports_identical(root, "src/af.js", landed)


@_needs_node
def test_async_concise_arrow_returns_promise_wrapped_type(tmp_path: Path):
    # `async (x) => true` -> Promise<boolean> (same treatment as an async function;
    # NEVER a bare boolean).
    root = _with_package_json(tmp_path)
    _project(root, "src/aa.js", "export const aok = async (x) => true;\n")
    assert doc_targets(root, "src/aa.js")[0].returns_inferred == "Promise<boolean>"
    landed = plan_js_document_returns_inferred(str(root), "src/aa.js").new_contents["src/aa.js"]
    assert " * @returns {Promise<boolean>}\n */\nexport const aok" in landed


@_needs_node
def test_async_function_with_fall_through_is_refused(tmp_path: Path):
    # An async fn that can fall through is `Promise<T | undefined>` — the definite-
    # return guard runs on the bare inference FIRST, so it is refused before any
    # Promise-wrap (we never wrap a non-provable type).
    root = _with_package_json(tmp_path)
    _project(root, "src/aff.js", "export async function af(x) { if (x) return true; }\n")
    assert doc_targets(root, "src/aff.js")[0].returns_inferred is None
    assert plan_js_document_returns_inferred(str(root), "src/aff.js").new_contents == {}


@_needs_node
def test_generator_is_refused(tmp_path: Path):
    # `function* g(){ return true; }` produces a Generator object; a `return` inside
    # is the iterator's return value, not a simple @returns type -> REFUSE.
    root = _with_package_json(tmp_path)
    _project(root, "src/gen.js", "export function* g() { return true; }\n")
    assert doc_targets(root, "src/gen.js")[0].returns_inferred is None
    assert plan_js_document_returns_inferred(str(root), "src/gen.js").new_contents == {}


@_needs_node
def test_async_generator_is_refused(tmp_path: Path):
    # `async function* ag(){ return true; }` produces an AsyncGenerator -> REFUSE
    # (the asteriskToken makes it a generator regardless of the async modifier).
    root = _with_package_json(tmp_path)
    _project(root, "src/agen.js", "export async function* ag() { return true; }\n")
    assert doc_targets(root, "src/agen.js")[0].returns_inferred is None
    assert plan_js_document_returns_inferred(str(root), "src/agen.js").new_contents == {}


@_needs_node
def test_plain_sync_function_still_accepted(tmp_path: Path):
    # The core case is UNCHANGED by the async/generator layers: a plain (non-async,
    # non-generator) literal-return export still lands a bare `@returns {boolean}`.
    root = _with_package_json(tmp_path)
    _project(root, "src/s.js", "export function s(x) { return true; }\n")
    assert doc_targets(root, "src/s.js")[0].returns_inferred == "boolean"
    landed = plan_js_document_returns_inferred(str(root), "src/s.js").new_contents["src/s.js"]
    assert " * @returns {boolean}\n */\nexport function s" in landed


# --- T1: each literal kind lands the right @returns + reparse-identical --------

@_needs_node
def test_plan_lands_returns_for_every_literal_kind(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", _PLAIN_JS)
    plan = plan_js_document_returns_inferred(str(root), "src/api.js")
    assert plan.ok
    assert plan.originals["src/api.js"] == _PLAIN_JS  # original captured
    assert plan.edits_by_file["src/api.js"] == 6  # one JSDoc per exported function
    landed = plan.new_contents["src/api.js"]
    # each function gets exactly its inferred @returns as leading trivia
    assert " * @returns {boolean}\n */\nexport function isReady" in landed
    assert " * @returns {string}\n */\nexport function greet" in landed
    assert " * @returns {number}\n */\nexport function count" in landed
    assert " * @returns {Array}\n */\nexport function items" in landed
    assert " * @returns {Object}\n */\nexport function cfg" in landed
    assert " * @returns {Date}\n */\nexport function when" in landed
    # NO @param lines were emitted (stay off js-document-param-types' surface)
    assert "@param" not in landed
    # and the splice re-parses with the EXACT same exported-name set (behaviour-id)
    assert reparse_exports_identical(root, "src/api.js", landed)


@_needs_node
def test_end_to_end_lands_jsdoc(tmp_path: Path):
    # A JSDoc is leading trivia (zero runtime bytes), so it lands via the shared
    # gated writer with no suite; the documented file is on disk and re-parses with
    # the SAME exported set.
    from app.execution.cross_file_rename import apply_rename

    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", "export function isReady(x) { return true; }\n")
    before = exported_names(root, "src/api.js")
    plan = plan_js_document_returns_inferred(str(root), "src/api.js")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "api.js").read_text(encoding="utf-8")
    assert "/**\n * isReady.\n * @returns {boolean}\n */\nexport function isReady" in landed
    assert exported_names(root, "src/api.js") == before  # exported surface unchanged


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the
    # real source stays byte-identical — the change is landed only by the writer.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", _PLAIN_JS)
    before = (root / "src" / "api.js").read_text(encoding="utf-8")
    plan = plan_js_document_returns_inferred(str(root), "src/api.js")
    assert plan.new_contents  # a JSDoc WAS synthesised
    assert (root / "src" / "api.js").read_text(encoding="utf-8") == before


# --- T2: DISJOINTNESS (the crux) ----------------------------------------------

@_needs_node
def test_declared_ts_return_is_refused_by_this_objective(tmp_path: Path):
    # A DECLARED-TS-return export is document-export-jsdoc's surface; THIS objective
    # REFUSES it (return_type is not None), so the two never both emit @returns.
    root = _with_package_json(tmp_path)
    _project(root, "src/typed.ts", "export function f(): number { return 42; }\n")
    # the driver computes BOTH facts, but the disjointness gate filters it out
    targets = doc_targets(root, "src/typed.ts")
    assert targets and targets[0].return_type == "number"
    assert returns_inferred_targets(root, "src/typed.ts") == []  # filtered -> refuse
    assert plan_js_document_returns_inferred(str(root), "src/typed.ts").new_contents == {}


@_needs_node
def test_no_double_returns_on_a_shared_fixture(tmp_path: Path):
    # THE no-double-@returns proof: run BOTH planners on the SAME fixture and assert
    # no node ever gets an @returns from two objectives. The fixture mixes a
    # declared-TS-return export (document-export-jsdoc's) and a plain-JS literal
    # export (THIS objective's) — they partition the nodes by the typed/untyped split.
    from app.execution.objectives.document_export_jsdoc import (
        documentable_targets as export_targets,
    )
    from app.execution.objectives.document_export_jsdoc import (
        plan_document_export_jsdoc,
    )

    src = (
        "export function typed(a: number): number { return a; }\n"  # declared TS return
        "export function plain(x) { return true; }\n"               # plain JS literal
    )
    root = _with_package_json(tmp_path)
    _project(root, "src/mix.ts", src)

    # document-export-jsdoc handles ONLY the declared-TS-return node.
    exp_names = {t.name for t in export_targets(root, "src/mix.ts")}
    assert exp_names == {"typed"}
    # js-document-returns-inferred handles ONLY the plain-JS literal node.
    inf_names = {t.name for t in returns_inferred_targets(root, "src/mix.ts")}
    assert inf_names == {"plain"}
    # DISJOINT: no node is claimed by both planners.
    assert exp_names.isdisjoint(inf_names)

    # And concretely on the landed bytes: each node carries exactly ONE @returns.
    exp_landed = plan_document_export_jsdoc(str(root), "src/mix.ts").new_contents["src/mix.ts"]
    inf_landed = plan_js_document_returns_inferred(str(root), "src/mix.ts").new_contents["src/mix.ts"]
    # document-export-jsdoc documented `typed` (declared return), not `plain`.
    assert "@returns {number}" in exp_landed
    assert exp_landed.count("@returns") == 1
    # js-document-returns-inferred documented `plain` (inferred), not `typed`.
    assert "@returns {boolean}" in inf_landed
    assert inf_landed.count("@returns") == 1


# --- T3: the REFUSE set (need node for the driver scan) -----------------------

@_needs_node
def test_refuses_already_jsdocd_node(tmp_path: Path):
    # A node that ALREADY carries a leading JSDoc is skipped by the driver
    # (hasLeadingJSDoc) -> nothing to document (idempotence base case).
    src = "/** hand-written */\nexport function isReady(x) { return true; }\n"
    root = _with_package_json(tmp_path)
    _project(root, "src/doc.js", src)
    assert returns_inferred_targets(root, "src/doc.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/doc.js").new_contents == {}


@_needs_node
def test_refuses_non_literal_return(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/nl.js", "export function f() { return compute(); }\n")
    assert returns_inferred_targets(root, "src/nl.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/nl.js").new_contents == {}


@_needs_node
def test_refuses_heterogeneous_returns(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/h.js",
             "export function f(b) { if (b) return true; return \"x\"; }\n")
    assert returns_inferred_targets(root, "src/h.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/h.js").new_contents == {}


@_needs_node
def test_refuses_bare_return_and_no_return(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/v.js",
             "export function a() { return; }\nexport function b() { let x = 1; }\n")
    assert returns_inferred_targets(root, "src/v.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/v.js").new_contents == {}


@_needs_node
def test_refuses_non_exported_function(tmp_path: Path):
    # An un-exported function is not on the doc-export surface -> the driver never
    # emits it as a doc target.
    root = _with_package_json(tmp_path)
    _project(root, "src/p.js", "function helper() { return true; }\n")
    assert returns_inferred_targets(root, "src/p.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/p.js").new_contents == {}


@_needs_node
def test_refuses_test_file_write_target(tmp_path: Path):
    # A jest test/fixture file is never a WRITE target, even with a perfect literal
    # return — Apex never edits the suite.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.test.js", "export function isReady() { return true; }\n")
    assert returns_inferred_targets(root, "src/api.test.js") == []
    assert plan_js_document_returns_inferred(str(root), "src/api.test.js").new_contents == {}


# --- T4: determinism + idempotence --------------------------------------------

@_needs_node
def test_deterministic_same_source_same_plan(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", _PLAIN_JS)
    first = plan_js_document_returns_inferred(str(root), "src/api.js").new_contents["src/api.js"]
    second = plan_js_document_returns_inferred(str(root), "src/api.js").new_contents["src/api.js"]
    assert first == second  # pure AST -> fixed text -> byte-identical


@_needs_node
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", _PLAIN_JS)
    landed = plan_js_document_returns_inferred(str(root), "src/api.js").new_contents["src/api.js"]
    # re-running on the documented bytes finds every node already JSDoc'd ->
    # an empty, byte-identical no-op (idempotence).
    _project(root, "src/api2.js", landed)
    assert plan_js_document_returns_inferred(str(root), "src/api2.js").new_contents == {}


@_needs_node
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.js", _PLAIN_JS)
    # a module whose only export already has a declared TS return -> not ours
    _project(root, "src/typed.ts", "export function f(): number { return 1; }\n")
    found = detect_returns_inferred_targets(str(root))
    assert found == ["src/api.js"]  # typed.ts (declared return) is not documentable


# --- T6: UTF-16 safety (an emoji before the target shifts the offset) ---------

@_needs_node
def test_utf16_astral_offset_is_handled(tmp_path: Path):
    # A leading astral char (😀, U+1F600) makes the driver's UTF-16 code-UNIT
    # insertOffset diverge by +1 from the Python code-POINT index; the shared splice
    # re-indexes via _u16_to_codepoint so the JSDoc still lands at the right spot and
    # the emoji + every other char survive untouched.
    src = "// 😀 banner\nexport function isReady(x) { return true; }\n"
    root = _with_package_json(tmp_path)
    _project(root, "src/emoji.js", src)
    plan = plan_js_document_returns_inferred(str(root), "src/emoji.js")
    assert plan.ok
    landed = plan.new_contents["src/emoji.js"]
    # the emoji banner is intact and the JSDoc precedes the export exactly
    assert "// 😀 banner\n" in landed
    assert "/**\n * isReady.\n * @returns {boolean}\n */\nexport function isReady" in landed
    # behaviour-identical: re-parses with the SAME exported set
    assert reparse_exports_identical(root, "src/emoji.js", landed)


# --- T5: registration / 5-registry parity + count-pins (always runs) ----------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-document-returns-inferred" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-document-returns-inferred"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns node (the driver parse)
    assert spec.scope_verify is False  # leading-trivia insert; no red-baseline veto


def test_move_value_tier_matches_doc_cluster():
    from app.engine.move_value import move_value, objective_value

    # The doc-surface cluster tier, alongside the other JSDoc doc objectives.
    assert move_value("js_document_returns_inferred") == 0.68
    assert move_value("js_document_returns_inferred") == move_value("document_export_jsdoc")
    assert objective_value("js-document-returns-inferred") == 0.68


def test_move_value_table_has_no_phantom_and_covers_operator():
    from tests.test_move_value import _emitted_operators
    from app.engine.move_value import OPERATOR_VALUE

    ops = _emitted_operators()
    assert "js_document_returns_inferred" in ops
    assert sorted(op for op in ops if op not in OPERATOR_VALUE) == []
    assert sorted(op for op in OPERATOR_VALUE if op not in ops) == []


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "js-document-returns-inferred" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-document-returns-inferred" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-document-returns-inferred"]  # non-empty strategy
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "js-document-returns-inferred" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-document-returns-inferred"


def test_facet_reachability_parity_invariant_holds():
    # THE HARD INVARIANT: FACET_OBJECTIVE_MAP.values() == available_objectives().
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


def test_counts_bumped_to_eighty_seven_and_forty_two():
    # THE COUNT-PINS this new objective bumps: 86->87 total, 41->42 CONCRETE.
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 93
    assert len(classify_objectives(names)["CONCRETE"]) == 48


def test_north_star_and_soundness_audits_pass():
    # The two RAISE-on-drift audits both PASS with the new objective wired.
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_refuses_on_python_soundness_corpus():
    # The standing soundness corpus is Python-shaped (pkg/*.py, no package.json);
    # the objective must REFUSE on each — the no-op-on-Python guarantee, auto-
    # satisfied by the package.json root-gate.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    # ``only`` slices the heavy sweep to THIS objective's row (byte-identical to its row
    # in the full sweep — per-objective independent), so the test pays just this
    # objective's subprocess cost, not the whole ~2-minute sweep, staying under the
    # per-test timeout under a parallel-chunked gate.
    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"js-document-returns-inferred"})
    cells = corpus.get("js-document-returns-inferred", {})
    assert cells, "js-document-returns-inferred should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
