"""js-tdd-implement develop objective — Apex's FIRST non-Python concrete landing.

A developer wrote a FAILING jest test that calls a function whose body is a
``throw new Error("Not implemented")`` stub; js-tdd-implement deterministically
mines witnesses from the test (no LLM), synthesises a body from a FIXED template
space (passthrough -> binary -> reduction -> constant-with->=2-witnesses) via the
bundled TypeScript Compiler API driver, keeps the FIRST template that flips the
project's own ``npm test`` (jest) RED->GREEN, else REFUSES. Byte-for-byte
rollback on failure.

Covers: the driver (scan / mine / fill byte-span splice, TS + JS, refusals); the
template space + its >=2-witness constant floor; the deterministic test-linkage
LOCATE; the plan (lands the body, captures the original, refuses non-JS / no
template); the END-TO-END landing (``apply_rename`` verify=True lands the body and
the real jest suite stays green) and the byte-for-byte ROLLBACK (a full-suite
regression restores the file); plus objective registration / facet+manifest+
soundness 1:1 parity (the four registries the new objective must appear in). The
heavy npm/jest tests skip cleanly when node + global ``typescript`` + an
installable jest aren't available; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.execution.js.js_stub_synthesis import candidate_bodies
from app.execution.js.js_tool import (
    JsStub,
    JsWitness,
    fill_body,
    global_node_modules,
    mine_witnesses,
    scan_stubs,
)
from app.execution.objectives.js_tdd_implement import (
    detect_js_stubs,
    is_js_source,
    plan_js_tdd_implement,
)

_PHRASE = "the failing jest test whose function to write"

# A stubbed CJS module + a RED jest test calling it (the proven beachhead shape).
_MATH_JS = (
    "function add(a, b) {\n"
    '  throw new Error("Not implemented");\n'
    "}\n"
    "module.exports = { add };\n"
)
_MATH_TEST = (
    'const { add } = require("../src/math");\n'
    'test("add sums two numbers", () => {\n'
    "  expect(add(2, 3)).toBe(5);\n"
    "});\n"
)


# --- environment guards (the heavy npm/jest path is opt-in by availability) ---

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (scan/mine/fill) to run."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


def _jest_demo(tmp_path: Path) -> Path | None:
    """A throwaway jest project (``src/math.js`` stub + RED test) with jest
    installed into its own ``node_modules`` (the project owns its deps, exactly as
    a Python target owns its ``.venv``). ``None`` when jest can't be installed
    offline — the caller then skips. Reuses a session-cached ``node_modules`` so
    only the FIRST heavy test pays the install."""
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "__tests__").mkdir()
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "src" / "math.js").write_text(_MATH_JS, encoding="utf-8")
    (root / "__tests__" / "math.test.js").write_text(_MATH_TEST, encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        return None
    shutil.copytree(cached, root / "node_modules")
    return root


_JEST_CACHE: dict[str, Path | None] = {}


def _ensure_jest_node_modules() -> Path | None:
    """A directory holding an installed jest ``node_modules``, built once per
    session (``npm install --prefer-offline jest@30`` in a tmp project served from
    the warm cache), or ``None`` when the install fails. Memoized so the suite
    installs jest at most once."""
    if "dir" in _JEST_CACHE:
        return _JEST_CACHE["dir"]
    base = Path(os.environ.get("TMPDIR", "/tmp")) / "apex_jest_cache_eyml"
    nm = base / "node_modules"
    if nm.is_dir():
        _JEST_CACHE["dir"] = nm
        return nm
    base.mkdir(parents=True, exist_ok=True)
    (base / "package.json").write_text('{ "name": "c", "version": "1.0.0" }\n',
                                       encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund",
             "jest@30"],
            cwd=str(base), capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        _JEST_CACHE["dir"] = None
        return None
    result = nm if (proc.returncode == 0 and nm.is_dir()) else None
    _JEST_CACHE["dir"] = result
    return result


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


# --- the refusal rule for non-JS files (always runs — pure, no node) ----------

def test_refuses_non_js_python_file():
    assert not is_js_source("app/mod.py")
    assert not is_js_source("setup.py")


def test_refuses_non_source_file():
    assert not is_js_source("README.md")
    assert not is_js_source("data.json")


def test_accepts_js_and_ts_sources():
    assert is_js_source("src/math.js")
    assert is_js_source("src/util.ts")
    assert is_js_source("x.mjs")
    assert is_js_source("y.cjs")
    assert is_js_source("c.jsx")
    assert is_js_source("d.tsx")


def test_refuses_jest_test_and_fixture_write_targets():
    # A jest test file is never a WRITE target (Apex never edits the suite).
    assert not is_js_source("src/math.test.js")
    assert not is_js_source("a.spec.ts")
    assert not is_js_source("__tests__/math.js")
    assert not is_js_source("pkg/__tests__/util.ts")


def test_plan_refuses_non_js_file_outright(tmp_path: Path):
    # A JsMissingBody pointing at a .py path: plan_js_tdd_implement refuses it
    # before touching anything — the load-bearing no-op on the Python path.
    from app.execution.objectives.js_tdd_implement import JsMissingBody

    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    mb = JsMissingBody(stub=stub, file_rel="app/mod.py", test_rel="t.test.js")
    plan = plan_js_tdd_implement(str(tmp_path), mb)
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/math.js", _MATH_JS)
    assert detect_js_stubs(str(tmp_path)) == []


# --- the template space + the >=2-witness constant floor (pure, no node) ------

def test_passthrough_offered_for_one_param():
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    labels = [lbl for lbl, _ in candidate_bodies(stub, [])]
    assert labels[0] == "passthrough"


def test_binary_templates_fixed_order_for_two_params():
    stub = JsStub(name="h", params=("a", "b"), body_start=0, body_end=1)
    labels = [lbl for lbl, _ in candidate_bodies(stub, [])]
    assert labels == ["a+b", "a-b", "a*b", "a%b", "a/b", "a&&b", "a||b"]


def test_no_param_stub_has_empty_template_space():
    stub = JsStub(name="g", params=(), body_start=0, body_end=1)
    assert candidate_bodies(stub, []) == []


def test_constant_withheld_on_single_witness():
    # The anti-overfit floor: one example must NOT land ``return <literal>;``.
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    labels = [lbl for lbl, _ in candidate_bodies(stub, [JsWitness(("3",), "6")])]
    assert "constant" not in labels


def test_constant_offered_last_on_two_distinct_witnesses():
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    cands = candidate_bodies(
        stub, [JsWitness(("1",), "7"), JsWitness(("2",), "7")])
    labels = [lbl for lbl, _ in cands]
    assert labels[-1] == "constant"
    assert cands[-1][1] == "return 7;"


def test_constant_withheld_when_witnesses_disagree():
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    labels = [lbl for lbl, _ in candidate_bodies(
        stub, [JsWitness(("1",), "7"), JsWitness(("2",), "8")])]
    assert "constant" not in labels


def test_candidate_bodies_deterministic():
    stub = JsStub(name="h", params=("a", "b"), body_start=0, body_end=1)
    assert candidate_bodies(stub, []) == candidate_bodies(stub, [])


# --- the driver: scan / mine / fill (need node) -------------------------------

@_needs_node
def test_driver_scan_finds_throw_stub_with_byte_span(tmp_path: Path):
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    stubs = scan_stubs(root, "src/math.js")
    assert len(stubs) == 1
    assert stubs[0].name == "add"
    assert stubs[0].params == ("a", "b")
    # the body block span splices exactly { ... } and nothing else
    assert _MATH_JS[stubs[0].body_start] == "{"
    assert _MATH_JS[stubs[0].body_end - 1] == "}"


@_needs_node
def test_driver_scan_ignores_non_stub_real_body(tmp_path: Path):
    root = _project(tmp_path, "src/ok.js", "function ok(a) { return a + 1; }\n")
    assert scan_stubs(root, "src/ok.js") == []


@_needs_node
def test_driver_scan_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.js", "function ( {\n")
    assert scan_stubs(root, "src/broken.js") == []  # conservative empty


@_needs_node
def test_driver_scan_parses_typescript(tmp_path: Path):
    src = ("export function add(a: number, b: number): number {\n"
           '  throw new Error("nope");\n}\n')
    root = _project(tmp_path, "src/math.ts", src)
    stubs = scan_stubs(root, "src/math.ts")
    assert len(stubs) == 1 and stubs[0].name == "add"


@_needs_node
def test_driver_mines_jest_witnesses(tmp_path: Path):
    root = _project(tmp_path, "__tests__/math.test.js", _MATH_TEST)
    witnesses = mine_witnesses(root, "__tests__/math.test.js", "add")
    assert witnesses == [JsWitness(args=("2", "3"), expected="5")]


@_needs_node
def test_driver_fill_splices_only_the_body(tmp_path: Path):
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    assert fill_body(root, "src/math.js", "add", "return a + b;")
    landed = (root / "src" / "math.js").read_text(encoding="utf-8")
    assert landed == "function add(a, b) { return a + b; }\nmodule.exports = { add };\n"


@_needs_node
def test_driver_fill_refuses_ambiguous_duplicate(tmp_path: Path):
    src = ("function foo(a) { throw new Error('x'); }\n"
           "function foo(b) { throw new Error('y'); }\n")
    root = _project(tmp_path, "src/dup.js", src)
    before = (root / "src" / "dup.js").read_text(encoding="utf-8")
    assert not fill_body(root, "src/dup.js", "foo", "return a;")
    assert (root / "src" / "dup.js").read_text(encoding="utf-8") == before


# --- LOCATE: the deterministic test linkage (need node for scan) --------------

@_needs_node
def test_detects_and_locates_stub_to_its_pinning_test(tmp_path: Path):
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    _project(tmp_path, "__tests__/math.test.js", _MATH_TEST)
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    found = detect_js_stubs(str(root))
    assert len(found) == 1
    assert found[0].stub.name == "add"
    assert found[0].file_rel == "src/math.js"
    assert found[0].test_rel == "__tests__/math.test.js"


@_needs_node
def test_refuses_when_no_test_pins_the_stub(tmp_path: Path):
    # A stub no test references -> not located -> nothing detected (refuse).
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    _project(tmp_path, "__tests__/other.test.js",
             'test("unrelated", () => { expect(1).toBe(1); });\n')
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    assert detect_js_stubs(str(root)) == []


# --- the END-TO-END landing + byte-for-byte rollback (need node + jest) -------

@_needs_node
def test_end_to_end_lands_body_and_keeps_jest_green(tmp_path: Path):
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    mb_list = detect_js_stubs(str(root))
    assert len(mb_list) == 1
    plan = plan_js_tdd_implement(str(root), mb_list[0])
    assert plan.ok
    assert plan.originals["src/math.js"] == _MATH_JS  # original captured

    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (root / "src" / "math.js").read_text(encoding="utf-8")
    assert "return a + b;" in landed  # binary template won; passthrough (return a;
    # -> 2 != 5) was tried and rejected by the jest gate first
    assert "module.exports = { add };" in landed  # surrounding source untouched


@_needs_node
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # The synthesiser probes a THROWAWAY COPY, so building the plan leaves the real
    # source byte-identical — the change is landed only by the gated/rollback writer.
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    before = (root / "src" / "math.js").read_text(encoding="utf-8")
    mb = detect_js_stubs(str(root))[0]
    plan = plan_js_tdd_implement(str(root), mb)
    assert plan.new_contents  # a body WAS synthesised
    assert (root / "src" / "math.js").read_text(encoding="utf-8") == before


@_needs_node
def test_refuses_when_no_template_passes_file_unchanged(tmp_path: Path):
    # ``shout(s) -> "HI"`` needs .toUpperCase(), outside the v0 template space, so
    # every candidate leaves the jest copy RED -> REFUSE, real file byte-unchanged.
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    (root / "src" / "str.js").write_text(
        'function shout(s) {\n  throw new Error("Not implemented");\n}\n'
        "module.exports = { shout };\n", encoding="utf-8")
    (root / "__tests__" / "str.test.js").write_text(
        'const { shout } = require("../src/str");\n'
        'test("upcases", () => { expect(shout("hi")).toBe("HI"); });\n',
        encoding="utf-8")
    before = (root / "src" / "str.js").read_text(encoding="utf-8")
    located = [mb for mb in detect_js_stubs(str(root)) if mb.stub.name == "shout"]
    assert len(located) == 1
    plan = plan_js_tdd_implement(str(root), located[0])
    assert not plan.new_contents  # refuse: no fixed template flips it green
    assert not plan.blockers
    assert (root / "src" / "str.js").read_text(encoding="utf-8") == before


@_needs_node
def test_byte_for_byte_rollback_on_full_suite_regression(tmp_path: Path):
    # A second test in the SAME suite pins add(1,1)==3 (false), so the body that
    # makes the FIRST test green still leaves the suite RED. apply_rename verifies,
    # finds red, and restores src/math.js byte-for-byte (never-fake-green).
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    mb = detect_js_stubs(str(root))[0]
    plan = plan_js_tdd_implement(str(root), mb)
    assert plan.ok  # a body was synthesised against math.test.js alone
    original = (root / "src" / "math.js").read_text(encoding="utf-8")
    # NOW poison the suite: a second test file the full-suite gate will run.
    (root / "__tests__" / "regress.test.js").write_text(
        'const { add } = require("../src/math");\n'
        'test("contradictory", () => { expect(add(1, 1)).toBe(3); });\n',
        encoding="utf-8")
    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # the file is restored to the exact original stub bytes
    assert (root / "src" / "math.js").read_text(encoding="utf-8") == original


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-tdd-implement" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-tdd-implement"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # spawns node + jest per candidate
    assert spec.scope_verify is True  # red-baseline objective, like tdd-implement


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-tdd-implement"


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
    assert "js-tdd-implement" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_missing_operation_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["the missing operation on the contract"]
    assert _PHRASE in ladder
    assert ladder[0] == "the operation signature"  # originals still lead


def test_soundness_strategy_declared_and_scope_verify_allowed():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-tdd-implement" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-tdd-implement"]  # non-empty strategy string
    assert "js-tdd-implement" in SCOPE_VERIFY_ALLOWLIST  # scope_verify is audited
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


def test_refuses_on_python_soundness_corpus(tmp_path: Path):
    # The standing soundness corpus is Python-shaped (pkg/*.py, no package.json);
    # the objective must REFUSE on each — the K3 no-op-on-Python guarantee.
    from app.engine.soundness_audit import (
        corpus_refusal_findings,
        repo_root,
    )

    # ``only`` slices the heavy sweep to THIS objective's row (byte-identical to its row
    # in the full sweep — per-objective independent), so the test pays just this
    # objective's subprocess cost, not the whole ~2-minute sweep, staying under the
    # per-test timeout under a parallel-chunked gate.
    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"js-tdd-implement"})
    cells = corpus.get("js-tdd-implement", {})
    assert cells, "js-tdd-implement should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
