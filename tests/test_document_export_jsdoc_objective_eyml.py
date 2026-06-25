"""document-export-jsdoc develop objective — Apex's SECOND non-Python concrete
landing, the JS/TS sibling of document-signature.

For an EXPORTED ``.js``/``.ts`` function/const-arrow with NO leading JSDoc,
document-export-jsdoc lands a MINIMAL JSDoc built from ONLY proven AST facts —
one ``@param <name>`` per declared parameter plus (TS only) an ``@returns {T}``
read VERBATIM off the declared return-type annotation — and inherits
document-signature's HONESTY GATE: a name+param-only JSDoc restates the
signature, so it REFUSES unless a declared return type surfaces a fact the bare
signature does not. A JSDoc is leading trivia (ZERO runtime bytes), so it is
behaviour-identical BY CONSTRUCTION, verified by an in-driver re-parse that
asserts the exported-name set is unchanged — NO npm/jest/tsc run.

Covers: the driver (``doc-targets`` facts + the ``doc-verify`` re-parse oracle,
TS + JS, refusals); the honesty gate (TS ``@returns {T}`` lands, plain JS
refuses); the deterministic source-order splice as leading trivia + idempotence;
the plan (lands the JSDoc, captures the original, refuses non-JS / no return
type); the END-TO-END landing (the documented file re-parses, surrounding source
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
from app.execution.objectives.document_export_jsdoc import (
    detect_jsdoc_targets,
    documentable_targets,
    is_js_source,
    plan_document_export_jsdoc,
)

_PHRASE = "the exported signature to document in jsdoc"

# A stubbed-but-typed exported TS module (the proven beachhead shape): two
# exported, return-typed, JSDoc-less functions the objective documents, plus an
# already-documented one (skipped) and a plain-JS function (no return type ->
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
    # A .py path: plan_document_export_jsdoc refuses it before touching anything —
    # the load-bearing no-op on the Python path.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_document_export_jsdoc(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/api.ts", _MATH_TS)
    assert detect_jsdoc_targets(str(tmp_path)) == []


# --- the driver: doc-targets / doc-verify (need node) -------------------------

@_needs_node
def test_driver_doc_targets_finds_exported_typed_jsdocless(tmp_path: Path):
    root = _project(tmp_path, "src/api.ts", _MATH_TS)
    targets = {t.name: t for t in doc_targets(root, "src/api.ts")}
    # add + mul are exported, JSDoc-less, and carry a declared return type; sub is
    # SKIPPED (already has a /** */ JSDoc -> idempotence at the driver level).
    assert set(targets) == {"add", "mul"}
    assert targets["add"].params == ("a", "b")
    assert targets["add"].return_type == "number"
    assert targets["mul"].return_type == "number"
    # the insertion offset sits at the statement start (before `export`)
    assert _MATH_TS[targets["add"].insert_offset:].startswith("export function add")


@_needs_node
def test_driver_doc_targets_skips_unexported_and_destructured(tmp_path: Path):
    src = (
        "function notExported(a) { return a; }\n"            # not exported
        "export function destruct({a, b}) { return a; }\n"  # non-identifier param
    )
    root = _project(tmp_path, "src/x.ts", src)
    # notExported is not exported; destruct's param is not a bare identifier, so
    # paramNames refuses it (never invent a @param name we cannot read) -> empty.
    assert doc_targets(root, "src/x.ts") == []


@_needs_node
def test_driver_doc_targets_plain_js_has_no_return_type(tmp_path: Path):
    root = _project(tmp_path, "src/p.js", "export function f(a, b) { return a + b; }\n")
    targets = doc_targets(root, "src/p.js")
    assert len(targets) == 1
    assert targets[0].name == "f"
    assert targets[0].return_type is None  # plain JS -> the honesty gate refuses


@_needs_node
def test_driver_doc_targets_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.ts", "export function ( {\n")
    assert doc_targets(root, "src/broken.ts") == []  # conservative empty


@_needs_node
def test_driver_doc_verify_emits_exported_name_set(tmp_path: Path):
    root = _project(tmp_path, "src/api.ts", _MATH_TS)
    assert exported_names(root, "src/api.ts") == frozenset({"add", "sub", "mul"})


@_needs_node
def test_driver_doc_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.ts", "export function ( {\n")
    assert exported_names(root, "src/broken.ts") is None  # parse error -> None


# --- the honesty gate + the splice (need node for the driver scan) ------------

@_needs_node
def test_honesty_gate_lands_ts_returns_and_refuses_plain_js(tmp_path: Path):
    # A TS function with a declared `: number` yields a JSDoc carrying `@returns
    # {number}`; a plain-JS function with no declared return type yields nothing
    # (a name+param-only JSDoc adds nothing -> refuse).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    _project(root, "src/plain.js",
             "export function f(a, b) { return a + b; }\n")
    assert [t.name for t in documentable_targets(root, "src/api.ts")] == ["add", "mul"]
    assert documentable_targets(root, "src/plain.js") == []


@_needs_node
def test_plan_splices_jsdoc_as_leading_trivia_with_facts(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_document_export_jsdoc(str(root), "src/api.ts")
    assert plan.ok
    assert plan.originals["src/api.ts"] == _MATH_TS  # original captured
    assert plan.edits_by_file["src/api.ts"] == 2  # add + mul documented
    landed = plan.new_contents["src/api.ts"]
    # the JSDoc lands as leading trivia BEFORE the export keyword, facts only
    assert "/**\n * add.\n * @param a\n * @param b\n * @returns {number}\n */\n"\
        "export function add" in landed
    assert " * @returns {number}\n */\nexport const mul" in landed
    # the surrounding source — incl. the already-documented sub — is untouched
    assert "/** already */\nexport function sub" in landed
    assert "@param" not in landed.split("export function sub")[1].split("\n")[0]


@_needs_node
def test_landed_jsdoc_reparses_with_same_exported_set(tmp_path: Path):
    # The behaviour-identical oracle: the spliced bytes re-parse AND carry the
    # SAME exported-name set (a JSDoc is leading trivia -> zero runtime bytes).
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_document_export_jsdoc(str(root), "src/api.ts")
    landed = plan.new_contents["src/api.ts"]
    assert reparse_exports_identical(root, "src/api.ts", landed)
    # and a SECOND run is a byte-identical no-op (every export now documented)
    _project(root, "src/api2.ts", landed)
    assert not plan_document_export_jsdoc(str(root), "src/api2.ts").new_contents


@_needs_node
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    _project(root, "src/plain.js", "export function f(a) { return a; }\n")  # refused
    found = detect_jsdoc_targets(str(root))
    assert found == ["src/api.ts"]  # plain.js (no return type) is not documentable


@_needs_node
def test_refuses_when_no_exported_typed_signature(tmp_path: Path):
    # A module with only an already-documented export and an un-exported function:
    # nothing to document -> empty plan, file byte-unchanged (refuse).
    root = _with_package_json(tmp_path)
    src = ("/** done */\nexport function a(x: number): number { return x; }\n"
           "function helper(y: number): number { return y; }\n")
    _project(root, "src/done.ts", src)
    before = (root / "src" / "done.ts").read_text(encoding="utf-8")
    plan = plan_document_export_jsdoc(str(root), "src/done.ts")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "done.ts").read_text(encoding="utf-8") == before


# --- the END-TO-END landing (need node) ---------------------------------------

@_needs_node
def test_end_to_end_lands_jsdoc_and_reparses(tmp_path: Path):
    # A JSDoc is behaviour-identical by construction (proven by the in-plan
    # re-parse oracle), so it lands via the shared gated writer with no suite;
    # the documented file is on disk and the driver re-parses it (same exports).
    from app.execution.cross_file_rename import apply_rename

    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_document_export_jsdoc(str(root), "src/api.ts")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "api.ts").read_text(encoding="utf-8")
    assert " * @returns {number}\n */\nexport function add" in landed
    assert exported_names(root, "src/api.ts") == frozenset({"add", "sub", "mul"})


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the
    # real source stays byte-identical — the change is landed only by the writer.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    before = (root / "src" / "api.ts").read_text(encoding="utf-8")
    plan = plan_document_export_jsdoc(str(root), "src/api.ts")
    assert plan.new_contents  # a JSDoc WAS synthesised
    assert (root / "src" / "api.ts").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "document-export-jsdoc" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["document-export-jsdoc"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns node (the driver parse)
    assert spec.scope_verify is False  # leading-trivia insert; no red-baseline veto


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "document-export-jsdoc"


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


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-export-jsdoc" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


def test_move_value_tier_matches_document_signature():
    from app.engine.move_value import move_value, objective_value

    # Same Tier-1 value as its Python sibling document_signature, so Layers a/b agree.
    assert move_value("document_export_jsdoc") == 0.68
    assert move_value("document_export_jsdoc") == move_value("document_signature")
    assert objective_value("document-export-jsdoc") == 0.68


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "document-export-jsdoc" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["document-export-jsdoc"]  # non-empty strategy string
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "document-export-jsdoc" not in SCOPE_VERIFY_ALLOWLIST
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

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("document-export-jsdoc", {})
    assert cells, "document-export-jsdoc should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
