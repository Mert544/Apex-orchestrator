"""js-wire-exports develop objective — Apex's THIRD non-Python concrete landing,
the JS/TS sibling of wire-exports / wire-module-exports.

For an own non-test ``.js``/``.ts``/``.mjs``/``.cjs`` source that DEFINES a
top-level PUBLIC function/const-arrow but never exports it, js-wire-exports lands
the ONE missing ESM ``export`` keyword (a byte-splice of ``export `` at the
statement start) so the helper becomes public API. It is a pure export-surface
GROW — publishing an already-defined binding can never break an existing importer
(the name did not exist before) and the binding provably exists in the SAME AST —
so it needs NO npm/jest/tsc: the proof is an in-driver re-parse asserting the
exported-name set is exactly ``prior ∪ {the added name}`` (a strict named
superset). v0 is clean-ESM-named only: a ``module.exports``/``exports.``/
``export default``/``export =`` module is REFUSED whole (the deferred surface).

Covers: the driver (``wire-targets`` finds unexported publics + skips
exported/private; ``wire-verify`` emits the full exported set; refusals on CJS /
default-export / syntax error); the deterministic bottom-up ``export ``-keyword
splice + the superset oracle + idempotence; the plan (lands the export, captures
the original, refuses non-JS / collision); the END-TO-END landing (the wired file
re-parses with the grown export set, surrounding source untouched) and that
planning never touches the real tree; plus objective registration / the FIVE
registries the new objective must appear in (move-value tier, north-star manifest,
soundness strategy, facet map, idea-facets ladder), all 1:1. The heavy node tests
skip cleanly when node + global ``typescript`` aren't available; every pure /
refusal / parity test always runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_tool import (
    all_exported_names,
    global_node_modules,
    reparse_exports_superset,
    wire_targets,
)
from app.execution.objectives.js_wire_exports import (
    detect_wire_targets,
    is_js_source,
    plan_js_wire_exports,
    wireable_targets,
)

_PHRASE = "the unexported public function to export"

# A clean-ESM TS module (the proven beachhead shape): one already-exported public
# function (skipped — already on the surface), one DEFINED-but-unexported public
# function and one unexported public const-arrow (the two wire targets), and a
# private ``_helper`` (skipped — not public surface).
_MATH_TS = (
    "export function add(a: number, b: number): number {\n"
    "  return a + b;\n"
    "}\n"
    "function sub(a: number, b: number): number {\n"
    "  return a - b;\n"
    "}\n"
    "function _helper(x: number): number { return x; }\n"
    "const mul = (a: number, b: number): number => a * b;\n"
)


# --- environment guards (the heavy node path is opt-in by availability) -------

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (wire-targets / wire-verify) to run."""
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
    assert is_js_source("d.cjs")
    assert is_js_source("d.tsx")


def test_refuses_jest_test_and_fixture_write_targets():
    # A jest test file is never a WRITE target (Apex never edits the suite).
    assert not is_js_source("src/api.test.js")
    assert not is_js_source("a.spec.ts")
    assert not is_js_source("__tests__/api.ts")


def test_plan_refuses_non_js_file_outright(tmp_path: Path):
    # A .py path: plan_js_wire_exports refuses it before touching anything — the
    # load-bearing no-op on the Python path.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_js_wire_exports(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/api.ts", _MATH_TS)
    assert detect_wire_targets(str(tmp_path)) == []


# --- the driver: wire-targets / wire-verify (need node) -----------------------

@_needs_node
def test_driver_wire_targets_finds_unexported_public(tmp_path: Path):
    root = _project(tmp_path, "src/api.ts", _MATH_TS)
    targets = {t.name: t for t in wire_targets(root, "src/api.ts")}
    # sub + mul are DEFINED public but never exported; add is SKIPPED (already
    # exported) and _helper is SKIPPED (private — not public surface).
    assert set(targets) == {"sub", "mul"}
    assert targets["sub"].kind == "function"
    assert targets["mul"].kind == "const"
    # the insertion offset sits at the statement start (where `export ` prepends)
    assert _MATH_TS[targets["sub"].insert_offset:].startswith("function sub")
    assert _MATH_TS[targets["mul"].insert_offset:].startswith("const mul")


@_needs_node
def test_driver_wire_targets_skips_already_exported_and_private(tmp_path: Path):
    src = (
        "export function exported(a) { return a; }\n"  # already exported -> skip
        "function _private(b) { return b; }\n"         # private -> skip
    )
    root = _project(tmp_path, "src/x.ts", src)
    # exported is on the surface; _private is not public -> nothing to wire.
    assert wire_targets(root, "src/x.ts") == []


@_needs_node
def test_driver_wire_targets_refuses_cjs_and_default_export(tmp_path: Path):
    # A CJS module (module.exports) -> the deferred surface -> empty targets.
    cjs = "function f(a) { return a; }\nmodule.exports.f = f;\n"
    root = _project(tmp_path, "src/cjs.js", cjs)
    assert wire_targets(root, "src/cjs.js") == []
    # An ESM default-export module -> also the deferred surface -> empty targets.
    dfl = "function f(a) { return a; }\nexport default function g() { return 1; }\n"
    _project(root, "src/dfl.ts", dfl)
    assert wire_targets(root, "src/dfl.ts") == []
    # A TS `export =` module -> deferred surface -> empty targets.
    eq = "function f(a) { return a; }\nexport = f;\n"
    _project(root, "src/eq.ts", eq)
    assert wire_targets(root, "src/eq.ts") == []


@_needs_node
def test_driver_wire_verify_emits_all_exported_set(tmp_path: Path):
    # The full exported-name set: ESM `export` (add) plus a trailing `export {}`.
    src = "export function add(a) { return a; }\nfunction sub(b) { return b; }\nexport { sub };\n"
    root = _project(tmp_path, "src/api.ts", src)
    assert all_exported_names(root, "src/api.ts") == frozenset({"add", "sub"})


@_needs_node
def test_driver_wire_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.ts", "export function ( {\n")
    assert all_exported_names(root, "src/broken.ts") is None  # parse error -> None


# --- the splice + the superset oracle (need node for the driver scan) ---------

@_needs_node
def test_plan_splices_export_keyword_and_superset_oracle(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_wire_exports(str(root), "src/api.ts")
    assert plan.ok
    assert plan.originals["src/api.ts"] == _MATH_TS  # original captured
    assert plan.edits_by_file["src/api.ts"] == 2  # sub + mul wired
    landed = plan.new_contents["src/api.ts"]
    # the ONE added byte-run per target is a leading `export ` keyword
    assert "export function sub(a: number, b: number): number {" in landed
    assert "export const mul = (a: number, b: number): number => a * b;" in landed
    # the already-exported add and the private _helper are untouched
    assert "export function add(a: number, b: number): number {" in landed
    assert "function _helper(x: number): number { return x; }" in landed
    assert "export function _helper" not in landed
    # and the splice re-parses as exactly prior ∪ {sub, mul}
    assert reparse_exports_superset(root, "src/api.ts", landed, frozenset({"sub", "mul"}))


@_needs_node
def test_collision_refused(tmp_path: Path):
    # An un-exported `f` whose name is ALREADY exported via `export {}` is a
    # collision — wire-targets omits it (we never double-export / shadow).
    src = "function f(a) { return a; }\nexport function g(b) { return b; }\nexport { f };\n"
    root = _project(tmp_path, "src/c.ts", src)
    # f is named in `export {}` (so already on the surface); g is exported; nothing
    # left to wire -> empty.
    assert wire_targets(root, "src/c.ts") == []
    _with_package_json(root)
    assert not plan_js_wire_exports(str(root), "src/c.ts").new_contents


@_needs_node
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_wire_exports(str(root), "src/api.ts")
    landed = plan.new_contents["src/api.ts"]
    # re-running on the landed bytes finds every public defined symbol exported ->
    # an empty, byte-identical no-op (idempotence).
    _project(root, "src/api2.ts", landed)
    assert not plan_js_wire_exports(str(root), "src/api2.ts").new_contents


@_needs_node
def test_detects_and_locates_wireable_files(tmp_path: Path):
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    # a module whose only public symbol is already exported -> not wireable
    _project(root, "src/done.ts", "export function only(a: number) { return a; }\n")
    found = detect_wire_targets(str(root))
    assert found == ["src/api.ts"]  # done.ts (nothing unexported) is not wireable


@_needs_node
def test_wireable_targets_refuses_cjs_via_objective(tmp_path: Path):
    # The objective-level view of the deferred surface: a CJS module yields no
    # wireable targets and an empty plan (a clean no-op, never a guess).
    root = _with_package_json(tmp_path)
    _project(root, "src/cjs.js", "function f(a) { return a; }\nexports.f = f;\n")
    assert wireable_targets(root, "src/cjs.js") == []
    plan = plan_js_wire_exports(str(root), "src/cjs.js")
    assert not plan.new_contents
    assert not plan.blockers


# --- the END-TO-END landing (need node) ---------------------------------------

@_needs_node
def test_end_to_end_lands_export(tmp_path: Path):
    # A pure export-surface grow is sound by construction (proven by the in-plan
    # re-parse superset oracle), so it lands via the shared gated writer with no
    # suite; the wired file is on disk and re-parses with the grown export set.
    from app.execution.cross_file_rename import apply_rename

    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    plan = plan_js_wire_exports(str(root), "src/api.ts")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "api.ts").read_text(encoding="utf-8")
    assert "export function sub(a: number, b: number): number {" in landed
    assert "export const mul = (a: number, b: number): number => a * b;" in landed
    # the full exported set is exactly the prior {add} grown by {sub, mul}
    assert all_exported_names(root, "src/api.ts") == frozenset({"add", "sub", "mul"})


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the
    # real source stays byte-identical — the change is landed only by the writer.
    root = _with_package_json(tmp_path)
    _project(root, "src/api.ts", _MATH_TS)
    before = (root / "src" / "api.ts").read_text(encoding="utf-8")
    plan = plan_js_wire_exports(str(root), "src/api.ts")
    assert plan.new_contents  # an export WAS synthesised
    assert (root / "src" / "api.ts").read_text(encoding="utf-8") == before


# --- registration / 5-registry 1:1 parity (always runs) -----------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-wire-exports" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-wire-exports"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns node (the driver parse)
    assert spec.scope_verify is False  # pure surface-grow; no red-baseline veto


def test_move_value_tier_matches_wire_exports():
    from app.engine.move_value import move_value, objective_value

    # Same Tier-1 value as its Python sibling wire_exports, so Layers a/b agree.
    assert move_value("js_wire_exports") == 0.90
    assert move_value("js_wire_exports") == move_value("wire_exports")
    assert objective_value("js-wire-exports") == 0.90


def test_move_value_table_has_no_phantom_and_covers_operator():
    # Reuse the authoritative drift checks: the operator is tiered and the table
    # has no stale row (the dash->underscore convention needs no OBJECTIVE_OPERATOR).
    from tests.test_move_value import _emitted_operators
    from app.engine.move_value import OPERATOR_VALUE

    ops = _emitted_operators()
    assert "js_wire_exports" in ops
    assert sorted(op for op in ops if op not in OPERATOR_VALUE) == []
    assert sorted(op for op in OPERATOR_VALUE if op not in ops) == []


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "js-wire-exports" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-wire-exports" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-wire-exports"]  # non-empty strategy string
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "js-wire-exports" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-wire-exports"


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


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


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
    from app.engine.soundness_audit import (
        corpus_refusal_findings,
        repo_root,
    )

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("js-wire-exports", {})
    assert cells, "js-wire-exports should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
