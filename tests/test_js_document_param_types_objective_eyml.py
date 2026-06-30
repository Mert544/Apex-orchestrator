"""js-document-param-types develop objective — Apex's FIFTH JS/TS concrete
landing, the missing HALF of document-export-jsdoc.

For an EXPORTED ``.js``/``.ts`` function/const-arrow whose parameters carry
DECLARED type annotations but with NO leading JSDoc, js-document-param-types
lands a MINIMAL JSDoc whose ``@param {T} name`` lines carry the DECLARED
parameter types read VERBATIM off the TS annotation (plus an ``@returns {T}``
when a return type is declared). Where document-export-jsdoc lands only when a
RETURN type exists (and emits bare ``@param name`` lines, no type), this one
surfaces the PARAMETER TYPES — a strictly richer fact. It inherits the same
HONESTY GATE: it lands ONLY when at least one parameter has a declared type (a
name-only/untyped ``@param`` restates the signature → refuse). A JSDoc is leading
trivia (ZERO runtime bytes), so it is behaviour-identical BY CONSTRUCTION,
verified by the SAME in-driver re-parse that asserts the exported-name set is
unchanged — NO npm/jest/tsc run.

Covers: the driver (``doc-targets`` now emits verbatim ``paramTypes``, TS + JS,
refusals); the honesty gate (a typed TS export lands, plain JS / untyped TS
refuses); the deterministic source-order splice as leading trivia + idempotence;
the plan (lands the typed JSDoc, captures the original, refuses non-JS / untyped);
the END-TO-END landing (the documented file re-parses, surrounding source
untouched) and that planning never touches the real tree; plus objective
registration / facet+manifest+soundness 1:1 parity (the SIX registries the new
objective must appear in). The heavy node tests skip cleanly when node + global
``typescript`` aren't available; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_tool import (
    doc_targets,
    exported_names,
    global_node_modules,
    reparse_exports_identical,
)
from app.execution.objectives.js_document_param_types import (
    detect_param_type_targets,
    is_js_source,
    param_type_targets,
    plan_js_document_param_types,
)

_PHRASE = "the exported parameter types to document in jsdoc"

# A typed exported TS module (the proven beachhead shape): two exported, typed,
# JSDoc-less functions the objective documents, plus an already-documented one
# (skipped) and a plain-JS-shaped untyped function (no declared param type ->
# honesty gate refuses).
_MATH_TS = (
    "export function add(a: number, b: number): number {\n"
    "  return a + b;\n"
    "}\n"
    "/** already */\n"
    "export function sub(a: number, b: number): number { return a - b; }\n"
    "export const mul = (a: number, b: number): number => a * b;\n"
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
    # A .py path: plan_js_document_param_types refuses it before touching anything —
    # the load-bearing no-op on the Python path.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_js_document_param_types(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/api.ts", _MATH_TS)
    assert detect_param_type_targets(str(tmp_path)) == []


# --- the driver: doc-targets now emits paramTypes (need node) -----------------

@_needs_node
def test_driver_doc_targets_emits_param_types_verbatim(tmp_path: Path):
    root = _project(tmp_path, "src/api.ts", _MATH_TS)
    targets = {t.name: t for t in doc_targets(root, "src/api.ts")}
    # add + mul are exported, JSDoc-less, and carry declared param types; sub is
    # SKIPPED (already has a /** */ JSDoc -> idempotence at the driver level).
    assert set(targets) == {"add", "mul"}
    assert targets["add"].params == ("a", "b")
    # the types are read VERBATIM off the annotation, one entry per param
    assert targets["add"].param_types == ("number", "number")
    assert targets["mul"].param_types == ("number", "number")
    assert targets["add"].return_type == "number"


@_needs_node
def test_driver_doc_targets_param_types_null_for_untyped(tmp_path: Path):
    # A plain-JS export: every param type is null (no annotation) -> honesty gate
    # will refuse; the driver still reports the parallel null-per-param array.
    root = _project(tmp_path, "src/p.js", "export function f(a, b) { return a + b; }\n")
    targets = doc_targets(root, "src/p.js")
    assert len(targets) == 1
    assert targets[0].name == "f"
    assert targets[0].param_types == (None, None)
    assert targets[0].return_type is None


@_needs_node
def test_driver_doc_targets_mixed_typed_and_untyped_params(tmp_path: Path):
    # A TS export with ONE typed and ONE untyped param: paramTypes is verbatim for
    # the typed one and null for the untyped one (parallel to params).
    src = "export function g(a: string, b): void { return; }\n"
    root = _project(tmp_path, "src/g.ts", src)
    targets = doc_targets(root, "src/g.ts")
    assert len(targets) == 1
    assert targets[0].params == ("a", "b")
    assert targets[0].param_types == ("string", None)


@_needs_node
def test_driver_doc_targets_skips_unexported_and_destructured(tmp_path: Path):
    src = (
        "function notExported(a: number) { return a; }\n"     # not exported
        "export function destruct({a, b}: any) { return a; }\n"  # non-identifier param
    )
    root = _project(tmp_path, "src/x.ts", src)
    # notExported is not exported; destruct's param is not a bare identifier, so
    # paramNames refuses it (never invent a @param name we cannot read) -> empty.
    assert doc_targets(root, "src/x.ts") == []


@_needs_node
def test_driver_doc_targets_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.ts", "export function ( {\n")
    assert doc_targets(root, "src/broken.ts") == []  # conservative empty


# --- the honesty gate + the splice (need node for the driver scan) ------------

@_needs_node
def test_honesty_gate_lands_typed_ts_and_refuses_plain_js(tmp_path: Path):
    # A TS function with a declared param type yields a JSDoc carrying `@param {T}`;
    # a plain-JS function with no declared param type yields nothing (a name+param-
    # only JSDoc adds nothing -> refuse).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    _project(root, "src/plain.js",
             "export function f(a, b) { return a + b; }\n")
    assert [t.name for t in param_type_targets(root, "src/api.ts")] == ["add", "mul"]
    assert param_type_targets(root, "src/plain.js") == []


@_needs_node
def test_plan_splices_typed_jsdoc_as_leading_trivia_with_facts(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_document_param_types(str(root), "src/api.ts")
    assert plan.ok
    assert plan.originals["src/api.ts"] == _MATH_TS  # original captured
    assert plan.edits_by_file["src/api.ts"] == 2  # add + mul documented
    landed = plan.new_contents["src/api.ts"]
    # the JSDoc lands as leading trivia BEFORE the export keyword, with the
    # VERBATIM declared param types (the fact this objective surfaces)
    assert "/**\n * add.\n * @param {number} a\n * @param {number} b\n"\
        " * @returns {number}\n */\nexport function add" in landed
    assert " * @param {number} a\n * @param {number} b\n"\
        " * @returns {number}\n */\nexport const mul" in landed
    # the surrounding source — incl. the already-documented sub — is untouched
    assert "/** already */\nexport function sub" in landed
    assert "@param" not in landed.split("export function sub")[1].split("\n")[0]


@_needs_node
def test_plan_lands_typed_param_without_return_type(tmp_path: Path):
    # The honesty gate fires on a typed PARAM even with NO return type — the half
    # document-export-jsdoc would refuse. The JSDoc carries @param {T} and NO
    # @returns (no return type was declared, so none is invented).
    root = _with_package_json(tmp_path)
    _project(root, "src/h.ts", "export function host(name: string) { return name; }\n")
    plan = plan_js_document_param_types(str(root), "src/h.ts")
    assert plan.ok
    landed = plan.new_contents["src/h.ts"]
    assert "/**\n * host.\n * @param {string} name\n */\nexport function host" in landed
    assert "@returns" not in landed


@_needs_node
def test_landed_jsdoc_reparses_with_same_exported_set(tmp_path: Path):
    # The behaviour-identical oracle: the spliced bytes re-parse AND carry the
    # SAME exported-name set (a JSDoc is leading trivia -> zero runtime bytes).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_document_param_types(str(root), "src/api.ts")
    landed = plan.new_contents["src/api.ts"]
    assert reparse_exports_identical(root, "src/api.ts", landed)
    # and a SECOND run is a byte-identical no-op (every export now documented)
    _project(root, "src/api2.ts", landed)
    assert not plan_js_document_param_types(str(root), "src/api2.ts").new_contents


@_needs_node
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    _project(root, "src/plain.js", "export function f(a) { return a; }\n")  # refused
    found = detect_param_type_targets(str(root))
    assert found == ["src/api.ts"]  # plain.js (no param type) is not documentable


@_needs_node
def test_refuses_when_no_typed_param_signature(tmp_path: Path):
    # A module with only an already-documented export and an un-exported function:
    # nothing to document -> empty plan, file byte-unchanged (refuse).
    root = _with_package_json(tmp_path)
    src = ("/** done */\nexport function a(x: number): number { return x; }\n"
           "function helper(y: number): number { return y; }\n")
    _project(root, "src/done.ts", src)
    before = (root / "src" / "done.ts").read_text(encoding="utf-8")
    plan = plan_js_document_param_types(str(root), "src/done.ts")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "done.ts").read_text(encoding="utf-8") == before


@_needs_node
def test_refuses_untyped_ts_export_with_return_type(tmp_path: Path):
    # A TS export with a RETURN type but NO param types: document-export-jsdoc
    # would land here, but THIS objective refuses (no param carries a declared
    # type -> a name-only @param restates the signature).
    root = _with_package_json(tmp_path)
    _project(root, "src/r.ts", "export function f(a, b): number { return 1; }\n")
    plan = plan_js_document_param_types(str(root), "src/r.ts")
    assert not plan.new_contents
    assert param_type_targets(root, "src/r.ts") == []


# --- the END-TO-END landing (need node) ---------------------------------------

@_needs_node
def test_end_to_end_lands_typed_jsdoc_and_reparses(tmp_path: Path):
    # A JSDoc is behaviour-identical by construction (proven by the in-plan
    # re-parse oracle), so it lands via the shared gated writer with no suite;
    # the documented file is on disk and the driver re-parses it (same exports).
    from app.execution.cross_file_rename import apply_rename

    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_document_param_types(str(root), "src/api.ts")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "api.ts").read_text(encoding="utf-8")
    assert " * @param {number} a\n * @param {number} b\n"\
        " * @returns {number}\n */\nexport function add" in landed
    assert exported_names(root, "src/api.ts") == frozenset({"add", "sub", "mul"})


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the
    # real source stays byte-identical — the change is landed only by the writer.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    before = (root / "src" / "api.ts").read_text(encoding="utf-8")
    plan = plan_js_document_param_types(str(root), "src/api.ts")
    assert plan.new_contents  # a JSDoc WAS synthesised
    assert (root / "src" / "api.ts").read_text(encoding="utf-8") == before


@_needs_node
def test_two_runs_are_byte_identical(tmp_path: Path):
    # Determinism: planning the same source twice yields byte-identical JSDoc.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    a = plan_js_document_param_types(str(root), "src/api.ts").new_contents["src/api.ts"]
    b = plan_js_document_param_types(str(root), "src/api.ts").new_contents["src/api.ts"]
    assert a == b


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-document-param-types" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-document-param-types"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns node (the driver parse)
    assert spec.scope_verify is False  # leading-trivia insert; no red-baseline veto


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-document-param-types"


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


def test_facet_phrase_distinct_from_document_export_jsdoc_phrase():
    # The two JSDoc facets must be substring-distinct (the planner matches by
    # substring), so neither shadows the other.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the exported signature to document in jsdoc") \
        == "document-export-jsdoc"
    assert facet_to_objective(_PHRASE) == "js-document-param-types"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "js-document-param-types" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    # appended AFTER document-export-jsdoc's phrase (the originals lead)
    assert ladder.index(_PHRASE) > ladder.index(
        "the exported signature to document in jsdoc")


def test_move_value_tier_matches_document_export_jsdoc():
    from app.engine.move_value import move_value, objective_value

    # Same Tier-1 value as document_export_jsdoc, so Layers a/b agree.
    assert move_value("js_document_param_types") == 0.68
    assert move_value("js_document_param_types") == move_value("document_export_jsdoc")
    assert objective_value("js-document-param-types") == 0.68


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-document-param-types" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-document-param-types"]  # non-empty strategy string
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "js-document-param-types" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


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
    # the objective must REFUSE on each — the K3 no-op-on-Python guarantee, auto-
    # satisfied by the package.json root-gate.
    from app.engine.soundness_audit import (
        corpus_refusal_findings,
        repo_root,
    )

    # ``only`` slices the heavy sweep to THIS objective's row (byte-identical to its row
    # in the full sweep — per-objective independent), so the test pays just this
    # objective's subprocess cost, not the whole ~2-minute sweep, staying under the
    # per-test timeout under a parallel-chunked gate.
    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"js-document-param-types"})
    cells = corpus.get("js-document-param-types", {})
    assert cells, "js-document-param-types should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
