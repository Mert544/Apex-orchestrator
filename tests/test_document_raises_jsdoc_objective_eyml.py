"""document-raises-jsdoc develop objective — Apex's SIXTH JS/TS concrete
landing, the FAILURE-CONTRACT sibling of document-export-jsdoc (``@returns``) and
js-document-param-types (``@param {T}``).

For an EXPORTED ``.js``/``.ts`` function/const-arrow with NO leading JSDoc whose
body throws a PROVEN constructor set — every ``throw`` is a literal
``throw new <Identifier>(...)`` — document-raises-jsdoc lands a MINIMAL JSDoc
carrying one ``@throws {<Ctor>}`` line per DISTINCT thrown constructor, read
VERBATIM off the AST in source order. It inherits the same HONESTY GATE: it lands
ONLY when at least one PROVABLE thrown constructor exists (``throws_types`` is
non-None AND non-empty). A function that throws nothing, or whose body contains
ANY unprovable throw shape (a ``throw <variable>`` / ``throw fn()`` / a
member-expression ctor ``new ns.Err()`` / a bare re-throw), is REFUSED — never a
content-free ``@throws``. A JSDoc is leading trivia (ZERO runtime bytes), so it is
behaviour-identical BY CONSTRUCTION, verified by the SAME in-driver re-parse that
asserts the exported-name set is unchanged — NO npm/jest/tsc run.

Covers: the driver (``doc-targets`` now emits ``throwsTypes`` — single throw, two
distinct throws de-duped in source order, duplicate ctor collapsed, the FULL
refusal set: ``throw variable`` / ``throw fn()`` / ``new ns.Err()`` / zero-throw /
re-throw → null or empty; TS + JS; const-arrow; destructured-param skip;
already-JSDoc'd skip; non-exported skip); the honesty gate (a provable-throw
export lands, a zero/unprovable-throw refuses); the deterministic source-order
splice as leading trivia + idempotence; the plan (lands the ``@throws`` JSDoc,
captures the original, refuses non-JS / test / fixture / no-package.json / stale-
offset / reparse-drift); the END-TO-END landing (the documented file re-parses,
surrounding source untouched) and that planning never touches the real tree; plus
objective registration / facet+manifest+soundness 1:1 parity (the SIX registries
the new objective must appear in) and the COUNT pins (71 / 29). The heavy node
tests skip cleanly when node + global ``typescript`` aren't available; every
pure/refusal/parity test always runs.
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
from app.execution.objectives.document_raises_jsdoc import (
    _is_landable,
    _jsdoc_block,
    detect_raises_targets,
    is_js_source,
    plan_document_raises_jsdoc,
    raises_targets,
)

_PHRASE = "the thrown error types to document in jsdoc"

# A typed exported TS module (the proven beachhead shape): one exported function
# whose body throws TWO distinct PROVEN ctors (TypeError then RangeError, in source
# order), an already-documented one (skipped at the driver), and a plain export
# that throws NOTHING (the honesty gate refuses it — nothing to document).
_PORT_TS = (
    "export function parsePort(s: string): number {\n"
    "  const n = Number(s);\n"
    "  if (Number.isNaN(n)) throw new TypeError(\"nan\");\n"
    "  if (n < 0 || n > 65535) throw new RangeError(\"range\");\n"
    "  return n;\n"
    "}\n"
    "/** already */\n"
    "export function sub(a: number): number { throw new Error(\"x\"); }\n"
    "export const echo = (a: number): number => a;\n"
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


def _target(name: str, throws: tuple[str, ...] | None) -> JsDocTarget:
    """A bare JsDocTarget carrying just the throws set the honesty gate / block
    template read — for the pure-Python unit tests (no node)."""
    return JsDocTarget(name=name, params=(), param_types=(), return_type=None,
                       returns_inferred=None, throws_types=throws, insert_offset=0)


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
    assert is_js_source("d.tsx")


def test_refuses_jest_test_and_fixture_write_targets():
    # A jest test file is never a WRITE target (Apex never edits the suite).
    assert not is_js_source("src/api.test.js")
    assert not is_js_source("a.spec.ts")
    assert not is_js_source("__tests__/api.ts")


def test_plan_refuses_non_js_file_outright(tmp_path: Path):
    # A .py path: plan_document_raises_jsdoc refuses it before touching anything —
    # the load-bearing no-op on the Python path.
    _project(tmp_path, "app/mod.py", "def f():\n    raise ValueError\n")
    plan = plan_document_raises_jsdoc(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/api.ts", _PORT_TS)
    assert detect_raises_targets(str(tmp_path)) == []


# --- the honesty gate + block template (pure Python, no node) -----------------

def test_honesty_gate_lands_provable_throw_set():
    assert _is_landable(_target("f", ("TypeError",)))
    assert _is_landable(_target("g", ("TypeError", "RangeError")))


def test_honesty_gate_refuses_none_throws_unprovable_shape():
    # A driver `throwsTypes: null` (an unprovable throw shape) -> refuse.
    assert not _is_landable(_target("r", None))


def test_honesty_gate_refuses_empty_throws_zero_throw_fn():
    # A driver `throwsTypes: []` (the body throws nothing) -> refuse (never a
    # content-free @throws).
    assert not _is_landable(_target("z", ()))


def test_block_emits_one_throws_line_per_distinct_ctor_in_order():
    block = _jsdoc_block(_target("parsePort", ("TypeError", "RangeError")))
    assert block == (
        "/**\n"
        " * parsePort.\n"
        " * @throws {TypeError}\n"
        " * @throws {RangeError}\n"
        " */\n"
    )


def test_block_single_throws_line():
    assert _jsdoc_block(_target("f", ("RangeError",))) == (
        "/**\n * f.\n * @throws {RangeError}\n */\n")


# --- the driver: doc-targets now emits throwsTypes (need node) -----------------

@_needs_node
def test_driver_doc_targets_emits_throws_types_verbatim(tmp_path: Path):
    root = _project(tmp_path, "src/api.ts", _PORT_TS)
    targets = {t.name: t for t in doc_targets(root, "src/api.ts")}
    # parsePort + echo are exported & JSDoc-less; sub is SKIPPED (already /** */).
    assert set(targets) == {"parsePort", "echo"}
    # the two distinct ctors, read VERBATIM in SOURCE ORDER (TypeError before Range)
    assert targets["parsePort"].throws_types == ("TypeError", "RangeError")
    # echo throws nothing -> empty tuple (the honesty gate will refuse it)
    assert targets["echo"].throws_types == ()


@_needs_node
def test_driver_single_throw_one_throws_type(tmp_path: Path):
    root = _project(tmp_path, "src/s.ts",
                    "export function f(x) { if (x) throw new TypeError(\"bad\"); }\n")
    targets = doc_targets(root, "src/s.ts")
    assert len(targets) == 1
    assert targets[0].throws_types == ("TypeError",)


@_needs_node
def test_driver_duplicate_ctor_collapses_to_single_line(tmp_path: Path):
    # Two throws of the SAME ctor -> ONE @throws line (de-duplicated).
    src = ("export function f(x) {\n"
           "  if (x < 0) throw new RangeError(\"a\");\n"
           "  throw new RangeError(\"b\");\n"
           "}\n")
    root = _project(tmp_path, "src/d.ts", src)
    targets = doc_targets(root, "src/d.ts")
    assert targets[0].throws_types == ("RangeError",)


@_needs_node
def test_driver_refuses_throw_of_variable(tmp_path: Path):
    # `throw e` is not a literal `new Identifier(...)` -> throwsTypes null (refuse).
    root = _project(tmp_path, "src/v.js",
                    "export function rethrow(e) { throw e; }\n")
    targets = doc_targets(root, "src/v.js")
    assert len(targets) == 1
    assert targets[0].throws_types is None


@_needs_node
def test_driver_refuses_throw_of_call_result(tmp_path: Path):
    # `throw makeError()` -> the ctor is not a `new` expression -> null (refuse).
    root = _project(tmp_path, "src/c.js",
                    "export function f() { throw makeError(); }\n")
    assert doc_targets(root, "src/c.js")[0].throws_types is None


@_needs_node
def test_driver_refuses_member_expression_ctor(tmp_path: Path):
    # `new ns.Err(...)` -> the ctor is a property-access, not a bare identifier ->
    # null (refuse): we never read a ctor name off a member expression.
    root = _project(tmp_path, "src/m.js",
                    "export function f() { throw new ns.Err(\"x\"); }\n")
    assert doc_targets(root, "src/m.js")[0].throws_types is None


@_needs_node
def test_driver_refuses_mixed_provable_and_unprovable_throw(tmp_path: Path):
    # ONE provable + ONE unprovable throw -> the WHOLE target refuses (null): the
    # @throws set must be complete or not claimed at all.
    src = ("export function f(x, e) {\n"
           "  if (x) throw new TypeError(\"a\");\n"
           "  throw e;\n"
           "}\n")
    root = _project(tmp_path, "src/mix.js", src)
    assert doc_targets(root, "src/mix.js")[0].throws_types is None


@_needs_node
def test_driver_zero_throw_fn_is_empty_not_null(tmp_path: Path):
    # A body with NO throw is vacuously provable -> empty tuple (the honesty gate
    # refuses it, but it is NOT a "null/unprovable" cell).
    root = _project(tmp_path, "src/z.js",
                    "export function f(a) { return a; }\n")
    assert doc_targets(root, "src/z.js")[0].throws_types == ()


@_needs_node
def test_driver_const_arrow_throw_form(tmp_path: Path):
    # The `const f = (...) => { throw new X(...) }` form is documented too.
    root = _project(tmp_path, "src/a.ts",
                    "export const f = (x: number) => { throw new RangeError(\"r\"); };\n")
    targets = doc_targets(root, "src/a.ts")
    assert len(targets) == 1
    assert targets[0].name == "f"
    assert targets[0].throws_types == ("RangeError",)


# --- ESCAPE-ONLY attribution: nested-function boundary + try/catch refuse -------
# (the P2 over-attribution closure — a `@throws` is the DOCUMENTED function's OWN
# contract, so a nested callback / nested helper throw is NOT attributed, and any
# try-with-catch refuses the whole target since deciding what a catch swallows is
# fragile. A catch-less try/finally does NOT swallow, so it still attributes.)

@_needs_node
def test_driver_refuses_target_with_try_catch_present(tmp_path: Path):
    # The exact adversarial-audit shape: a throw inside a nested callback, a throw
    # inside a nested helper, and a try whose catch SWALLOWS it. NONE of these is
    # the documented function's own escaping contract; the present `catch` makes the
    # whole target unprovable -> throwsTypes null (REFUSE the target). Before the
    # fix the driver wrongly returned ["RangeError","TypeError"].
    src = (
        "export function outer(items: number[]): number {\n"
        "  items.forEach((x) => { if (x < 0) throw new RangeError(\"neg\"); });\n"
        "  function inner() { throw new TypeError(\"bad\"); }\n"
        "  try { inner(); } catch (e) { /* swallowed */ }\n"
        "  return items.length;\n"
        "}\n"
    )
    root = _project(tmp_path, "src/outer.ts", src)
    targets = doc_targets(root, "src/outer.ts")
    assert len(targets) == 1
    assert targets[0].name == "outer"
    assert targets[0].throws_types is None  # refused (catch present)


@_needs_node
def test_driver_nested_callback_throw_not_attributed(tmp_path: Path):
    # A throw inside a nested `.forEach` callback, NO try/catch anywhere: it is the
    # callback's OWN contract, never `loop`'s. The walk does not descend into the
    # nested function-like, so it is invisible -> throwsTypes [] (vacuously provable,
    # the honesty gate then refuses — but it is NOT attributed to `loop`).
    src = (
        "export function loop(items: number[]): number {\n"
        "  items.forEach((x) => { if (x < 0) throw new RangeError(\"neg\"); });\n"
        "  return items.length;\n"
        "}\n"
    )
    root = _project(tmp_path, "src/loop.ts", src)
    targets = doc_targets(root, "src/loop.ts")
    assert len(targets) == 1
    assert targets[0].throws_types == ()  # nested throw NOT counted, no try/catch


@_needs_node
def test_driver_nested_helper_throw_not_attributed(tmp_path: Path):
    # A throw inside a nested HELPER function declaration (not a callback) is that
    # helper's contract, not the outer function's — and with no try/catch the outer
    # function attributes nothing.
    src = (
        "export function host(x: number): number {\n"
        "  function helper() { throw new TypeError(\"bad\"); }\n"
        "  helper();\n"
        "  return x;\n"
        "}\n"
    )
    root = _project(tmp_path, "src/host.ts", src)
    assert doc_targets(root, "src/host.ts")[0].throws_types == ()


@_needs_node
def test_driver_direct_top_level_throw_still_attributed(tmp_path: Path):
    # The unchanged base case: a function whose ONLY throw is a DIRECT, un-caught
    # `throw new TypeError(...)` in its own top-level body is still attributed.
    root = _project(tmp_path, "src/direct.ts",
                    "export function f(x: number): number {\n"
                    "  if (x < 0) throw new TypeError(\"bad\");\n"
                    "  return x;\n"
                    "}\n")
    targets = doc_targets(root, "src/direct.ts")
    assert len(targets) == 1
    assert targets[0].throws_types == ("TypeError",)


@_needs_node
def test_driver_try_finally_without_catch_still_attributes(tmp_path: Path):
    # A `try`/`finally` with NO catch does NOT swallow — a direct top-level throw
    # still escapes, so it is STILL attributed (only a present `catch` refuses).
    root = _project(tmp_path, "src/tf.ts",
                    "export function g(x: number): number {\n"
                    "  if (x < 0) throw new TypeError(\"bad\");\n"
                    "  try { run(); } finally { cleanup(); }\n"
                    "  return x;\n"
                    "}\n")
    targets = doc_targets(root, "src/tf.ts")
    assert len(targets) == 1
    assert targets[0].throws_types == ("TypeError",)


@_needs_node
def test_driver_direct_throw_inside_try_with_catch_refuses(tmp_path: Path):
    # Even a DIRECT throw is refused when it sits inside a try whose catch may
    # swallow it — the present catch makes the escape set unprovable.
    root = _project(tmp_path, "src/tc.ts",
                    "export function h(x: number): number {\n"
                    "  try { if (x < 0) throw new TypeError(\"bad\"); }\n"
                    "  catch (e) { return 0; }\n"
                    "  return x;\n"
                    "}\n")
    assert doc_targets(root, "src/tc.ts")[0].throws_types is None


@_needs_node
def test_driver_skips_unexported_and_destructured(tmp_path: Path):
    src = (
        "function notExported() { throw new TypeError(\"x\"); }\n"   # not exported
        "export function destruct({a}) { throw new TypeError(\"y\"); }\n"  # bad param
    )
    root = _project(tmp_path, "src/x.ts", src)
    # notExported is not exported; destruct's param is not a bare identifier, so
    # paramNames refuses it (inherited gate) -> empty.
    assert doc_targets(root, "src/x.ts") == []


@_needs_node
def test_driver_skips_already_documented(tmp_path: Path):
    # An exported function that ALREADY has a leading JSDoc is skipped (idempotence
    # at the driver level).
    root = _project(tmp_path, "src/done.ts",
                    "/** done */\nexport function f() { throw new TypeError(\"x\"); }\n")
    assert doc_targets(root, "src/done.ts") == []


@_needs_node
def test_driver_doc_targets_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.ts", "export function ( {\n")
    assert doc_targets(root, "src/broken.ts") == []  # conservative empty


# --- the honesty gate + the splice (need node for the driver scan) ------------

@_needs_node
def test_raises_targets_lands_provable_refuses_zero_throw(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    _project(root, "src/plain.js", "export function f(a) { return a; }\n")
    # parsePort throws a provable set; echo throws nothing (refused by the gate).
    assert [t.name for t in raises_targets(root, "src/api.ts")] == ["parsePort"]
    assert raises_targets(root, "src/plain.js") == []


@_needs_node
def test_plan_splices_throws_jsdoc_as_leading_trivia_with_facts(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    plan = plan_document_raises_jsdoc(str(root), "src/api.ts")
    assert plan.ok
    assert plan.originals["src/api.ts"] == _PORT_TS  # original captured
    assert plan.edits_by_file["src/api.ts"] == 1  # only parsePort is landable
    landed = plan.new_contents["src/api.ts"]
    # the JSDoc lands as leading trivia BEFORE the export keyword, with the VERBATIM
    # thrown ctors in source order (the fact this objective surfaces)
    assert ("/**\n * parsePort.\n * @throws {TypeError}\n * @throws {RangeError}\n"
            " */\nexport function parsePort") in landed
    # the surrounding source — incl. the already-documented sub — is untouched
    assert "/** already */\nexport function sub" in landed
    # echo (zero-throw) is left undocumented
    assert "@throws" not in landed.split("export const echo")[1]


@_needs_node
def test_landed_jsdoc_reparses_with_same_exported_set(tmp_path: Path):
    # The behaviour-identical oracle: the spliced bytes re-parse AND carry the SAME
    # exported-name set (a JSDoc is leading trivia -> zero runtime bytes).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    plan = plan_document_raises_jsdoc(str(root), "src/api.ts")
    landed = plan.new_contents["src/api.ts"]
    assert reparse_exports_identical(root, "src/api.ts", landed)
    # and a SECOND run is a byte-identical no-op (the one landable export is now
    # documented; the rest were already refused).
    _project(root, "src/api2.ts", landed)
    assert not plan_document_raises_jsdoc(str(root), "src/api2.ts").new_contents


@_needs_node
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    _project(root, "src/plain.js", "export function f(a) { return a; }\n")  # refused
    found = detect_raises_targets(str(root))
    assert found == ["src/api.ts"]  # plain.js (zero-throw) is not documentable


@_needs_node
def test_refuses_when_only_unprovable_or_zero_throws(tmp_path: Path):
    # A module with only an already-documented export, an un-exported function, and
    # a re-throw export: nothing to document -> empty plan, file byte-unchanged.
    root = _with_package_json(tmp_path)
    src = ("/** done */\nexport function a() { throw new TypeError(\"x\"); }\n"
           "function helper() { throw new TypeError(\"y\"); }\n"
           "export function rethrow(e) { throw e; }\n")
    _project(root, "src/done.ts", src)
    before = (root / "src" / "done.ts").read_text(encoding="utf-8")
    plan = plan_document_raises_jsdoc(str(root), "src/done.ts")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "done.ts").read_text(encoding="utf-8") == before


@_needs_node
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.test.ts", _PORT_TS)
    assert not plan_document_raises_jsdoc(str(root), "src/api.test.ts").new_contents


@_needs_node
def test_plan_refuses_fixture_file_input(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "__tests__/api.ts", _PORT_TS)
    assert not plan_document_raises_jsdoc(str(root), "__tests__/api.ts").new_contents


@_needs_node
def test_plan_unreadable_path_is_noop(tmp_path: Path):
    root = _with_package_json(tmp_path)
    plan = plan_document_raises_jsdoc(str(root), "src/missing.ts")
    assert not plan.new_contents
    assert not plan.blockers


@_needs_node
def test_plan_refuses_reparse_drift_planted_corrupt(monkeypatch, tmp_path: Path):
    # If the splice oracle reports drift (a corrupt splice), the plan refuses and
    # lands nothing — never an unverified change. Planted by forcing the oracle
    # False (the real splice could never drift for a comment, so we simulate it).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    import app.execution.objectives.document_export_jsdoc as spine

    monkeypatch.setattr(spine, "reparse_exports_identical", lambda *a, **k: False)
    plan = plan_document_raises_jsdoc(str(root), "src/api.ts")
    assert not plan.new_contents  # oracle refused -> nothing landed


# --- the END-TO-END landing (need node) ---------------------------------------

@_needs_node
def test_end_to_end_lands_throws_jsdoc_and_reparses(tmp_path: Path):
    # A JSDoc is behaviour-identical by construction (proven by the in-plan re-parse
    # oracle), so it lands via the shared gated writer with no suite; the documented
    # file is on disk and the driver re-parses it (same exports).
    from app.execution.cross_file_rename import apply_rename

    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    plan = plan_document_raises_jsdoc(str(root), "src/api.ts")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "api.ts").read_text(encoding="utf-8")
    assert ("/**\n * parsePort.\n * @throws {TypeError}\n * @throws {RangeError}\n"
            " */\nexport function parsePort") in landed
    assert exported_names(root, "src/api.ts") == frozenset({"parsePort", "sub", "echo"})


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the
    # real source stays byte-identical — the change is landed only by the writer.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    before = (root / "src" / "api.ts").read_text(encoding="utf-8")
    plan = plan_document_raises_jsdoc(str(root), "src/api.ts")
    assert plan.new_contents  # a JSDoc WAS synthesised
    assert (root / "src" / "api.ts").read_text(encoding="utf-8") == before


@_needs_node
def test_two_runs_are_byte_identical(tmp_path: Path):
    # Determinism: planning the same source twice yields byte-identical JSDoc.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _PORT_TS)
    a = plan_document_raises_jsdoc(str(root), "src/api.ts").new_contents["src/api.ts"]
    b = plan_document_raises_jsdoc(str(root), "src/api.ts").new_contents["src/api.ts"]
    assert a == b


@_needs_node
def test_never_fake_green_unprovable_throw_lands_nothing(tmp_path: Path):
    # never-fake-green capstone: a function whose ONLY throw is a re-thrown variable
    # is an UNPROVABLE failure contract — the driver returns throwsTypes null, the
    # honesty gate refuses, and NOTHING is landed before apply (no fabricated
    # @throws). The file is byte-unchanged on disk.
    root = _with_package_json(tmp_path)
    src = "export function wrap(e) { throw e; }\n"
    _project(root, "src/w.js", src)
    plan = plan_document_raises_jsdoc(str(root), "src/w.js")
    assert not plan.new_contents  # REFUSED before apply — never a fabricated @throws
    assert (root / "src" / "w.js").read_text(encoding="utf-8") == src


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "document-raises-jsdoc" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["document-raises-jsdoc"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns node (the driver parse)
    assert spec.scope_verify is False  # leading-trivia insert; no red-baseline veto


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "document-raises-jsdoc"


def test_facet_reachability_parity_invariant_holds():
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


def test_facet_phrase_distinct_from_sibling_jsdoc_phrases():
    # The three JSDoc facets must be substring-distinct (the planner matches by
    # substring), so none shadows the others.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the exported signature to document in jsdoc") \
        == "document-export-jsdoc"
    assert facet_to_objective("the exported parameter types to document in jsdoc") \
        == "js-document-param-types"
    assert facet_to_objective(_PHRASE) == "document-raises-jsdoc"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-raises-jsdoc" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    # appended AFTER the two sibling JSDoc phrases (the originals lead)
    assert ladder.index(_PHRASE) > ladder.index(
        "the exported signature to document in jsdoc")
    assert ladder.index(_PHRASE) > ladder.index(
        "the exported parameter types to document in jsdoc")


def test_move_value_tier_matches_sibling_jsdoc_objectives():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    # Same Tier-1 value as the sibling JSDoc objectives, so Layers a/b agree.
    assert move_value("document_raises_jsdoc") == 0.68
    assert move_value("document_raises_jsdoc") == move_value("document_export_jsdoc")
    assert objective_value("document-raises-jsdoc") == 0.68
    assert objective_value("document-raises-jsdoc") != DEFAULT_VALUE  # not fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["document-raises-jsdoc"] == (
        "jsdoc-leading-trivia-insert+throws-types-from-literal-new-verbatim"
        "+reparse-identical-or-refuse(no-suite-needed)")
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "document-raises-jsdoc" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_north_star_and_soundness_audits_pass():
    # The two RAISE-on-drift audits both PASS with the new objective wired (parity 1:1).
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 90  # 89 after js-strengthen-tests (89th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # js-strengthen-tests (89th) is CONCRETE


def test_refuses_on_python_soundness_corpus():
    # The standing soundness corpus is Python-shaped (pkg/*.py, no package.json);
    # the objective must REFUSE on each — the K3 no-op-on-Python guarantee, auto-
    # satisfied by the package.json root-gate.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    # ``only`` slices the sweep to THIS objective's row (byte-identical to its row in the
    # full sweep — per-objective independent), so the test pays just this objective's cost,
    # not the whole ~2-minute heavy sweep, staying under the per-test timeout under a
    # parallel-chunked gate.
    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"document-raises-jsdoc"})
    cells = corpus.get("document-raises-jsdoc", {})
    assert cells, "document-raises-jsdoc should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
