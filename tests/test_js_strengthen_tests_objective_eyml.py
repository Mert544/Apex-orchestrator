"""js-strengthen-tests develop objective — the JS/TS mirror of strengthen-tests
(the LITE, mined-witness variant).

Apex's deterministic JS/TS test-STRENGTHENING: it finds a single-token MUTATION an
ALREADY-tested exported JS/TS function's EXISTING jest test (its mined witnesses)
does NOT catch, and lands ONE env-gated characterization assertion that DOES — in an
Apex-OWNED test file, never editing the buyer's test. HONEST framing: it strengthens
against the function's MINED witnesses, NOT arbitrary full-suite blind spots (the
un-buildable full mirror); value-tier 0.80 (below cover-gaps 0.90 / strengthen 0.88).

Covers:
* the driver ``mutate`` subcommand (the single-token mutant catalog: comparison /
  boundary / arithmetic / boolean flips, bool-const, n->n+1, return X->undefined);
* the LAND path — a tested pure fn whose mined witnesses MISS a mutant (the witness
  ``add(2,0)===2`` is blind to ``+``->``-``; the synthesized ``add(2,2)`` diverges)
  lands a killing assertion in the Apex-owned file that PASSES the real (forced) jest
  gate;
* DISJOINTNESS from js-cover-gaps (untested fn -> strengthen refuses, cover-gaps
  offers; tested fn -> strengthen offers, cover-gaps refuses; disjoint target sets on
  a shared fixture; strengthen never writes the buyer's test);
* the REFUSE core (each its own test): no surviving mutant (well-tested); non-pure /
  clock fn; RED existing test (witnesses not green); no witnesses; async/generator;
  non-serialisable; the mutant is NEVER persisted to the real source;
* determinism (same module -> byte-identical assertions);
* JS tests RUN, not skip (a loud sentinel — STOP+report if it fails);
* parity (registration + facet + manifest + soundness 1:1) + count-pins (89/44) +
  the FACET reachability invariant + the new soundness-corpus fixture refusing.

The heavy node/jest tests skip cleanly when node + global ``typescript`` + an
installable jest+babel-TS toolchain aren't available; every pure/refusal/parity test
always runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.execution.js.js_strengthen_tests import (
    JsMutant,
    _apply_mutant,
    _driver_mutants,
    _is_survivor,
    _probe_inputs,
    generate_js_strengthen_test,
)
from app.execution.js.js_tool import (
    JsCoverParam,
    JsCoverTarget,
    global_node_modules,
    mine_witnesses,
)
from app.execution.lang.js_adapter import _locate_test
from app.execution.objectives.js_strengthen_tests import (
    detect_strengthen_targets,
    is_js_source,
    plan_js_strengthen_tests,
)

_PHRASE = "the jest mutant the mined witnesses miss"


# --- environment guards (the heavy node/jest path is opt-in by availability) ---

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (mutate/cover-targets) AND the transpile/capture
    children to run."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_JEST_TS_CACHE: dict[str, Path | None] = {}


def _ensure_jest_ts_node_modules() -> Path | None:
    """A directory holding an installed jest + babel-TS ``node_modules`` (jest@30,
    ``@babel/preset-typescript``, ``@babel/plugin-transform-modules-commonjs``,
    ``babel-jest``), built once per session, or ``None`` when the install fails.

    Shares the SAME on-disk cache directory as the js-cover-gaps suite so at most one
    install happens across the whole JS test corpus."""
    if "dir" in _JEST_TS_CACHE:
        return _JEST_TS_CACHE["dir"]
    base = Path(os.environ.get("TMPDIR", "/tmp")) / "apex_jest_ts_cache_eyml"
    nm = base / "node_modules"
    if nm.is_dir():
        _JEST_TS_CACHE["dir"] = nm
        return nm
    base.mkdir(parents=True, exist_ok=True)
    (base / "package.json").write_text('{ "name": "c", "version": "1.0.0" }\n',
                                       encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund",
             "jest@30", "@babel/preset-typescript@7",
             "@babel/plugin-transform-modules-commonjs@7", "babel-jest@30"],
            cwd=str(base), capture_output=True, text=True, timeout=400)
    except (OSError, subprocess.SubprocessError):
        _JEST_TS_CACHE["dir"] = None
        return None
    result = nm if (proc.returncode == 0 and nm.is_dir()) else None
    _JEST_TS_CACHE["dir"] = result
    return result


_BABEL_CONFIG = (
    "module.exports = { presets: [\"@babel/preset-typescript\"], "
    "plugins: [\"@babel/plugin-transform-modules-commonjs\"] };\n"
)


def _jest_project(tmp_path: Path, files: dict[str, str]) -> Path | None:
    """A throwaway jest project with each ``rel -> src`` in ``files`` and a
    jest+babel-TS ``node_modules`` (so both ``.js`` and ``.ts`` run under the
    project's own jest). ``None`` when the toolchain can't be installed offline — the
    caller then skips. Reuses the session-cached ``node_modules``."""
    root = tmp_path / "demo"
    for rel, src in files.items():
        (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "babel.config.js").write_text(_BABEL_CONFIG, encoding="utf-8")
    cached = _ensure_jest_ts_node_modules()
    if cached is None:
        return None
    shutil.copytree(cached, root / "node_modules")
    return root


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    """A throwaway project (single ``package.json`` root) with each ``rel -> src``,
    NO ``node_modules`` — for the driver / generator / plan tests that need node to
    parse + capture but not a jest run."""
    root = tmp_path / "proj"
    for rel, src in files.items():
        (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    (root / "package.json").write_text(
        '{ "name": "p", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    return root


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")

# A tested ``add`` whose ONLY witness (``add(2, 0) === 2``) is BLIND to the ``+``->``-``
# mutant (2 - 0 == 2), so that mutant SURVIVES; a synthesized input (``add(2, 2)``)
# diverges (4 vs 0), so strengthen can land a killing assertion. The recurring LAND
# fixture across the suite.
_ADD_SRC = "export function add(a: number, b: number): number { return a + b; }\n"
_ADD_TEST = ('import { add } from "../math";\n'
             'test("add", () => { expect(add(2, 0)).toBe(2); });\n')


# --- the JS-RUNS-NOT-SKIP sentinel (loud, always runs) ------------------------

def test_node_toolchain_is_available_or_warn_loudly():
    """JS tests must RUN, not silently skip. This sentinel makes the env state
    VISIBLE: it passes when node + global typescript are present (the heavy tests
    will run), and FAILS loudly otherwise so a silent skip never hides a broken JS
    lane (STOP+report if this fails in the integrator's env)."""
    assert _node_ok(), (
        "node + global typescript are NOT available — the js-strengthen-tests heavy "
        "tests would SKIP. STOP and report: the JS lane cannot be proven here."
    )


# --- pure file-gate tests (always run) ----------------------------------------

def test_is_js_source_accepts_js_ts_rejects_tests_and_python():
    assert is_js_source("src/math.ts")
    assert is_js_source("src/util.js")
    assert not is_js_source("a.test.ts")
    assert not is_js_source("a.spec.js")
    assert not is_js_source("__tests__/util.ts")
    assert not is_js_source("pkg/mod.py")


def test_probe_inputs_sound_slice_and_refusal():
    """The probe pool: zero-arg yields the empty tuple; primitive-typed params yield
    their boundary-relevant pools; an untyped non-defaulted param refuses (yields
    nothing)."""
    def target(params):
        return JsCoverTarget(name="f", params=tuple(params), pure=True,
                             export_kind="named")

    # zero-arg -> a single empty input
    assert list(_probe_inputs(target([]))) == [[]]
    # number param -> the first probe is the leading pool value, and 2/1/0 appear
    rows = list(_probe_inputs(target([JsCoverParam("a", "number", None)])))
    assert rows[0] == ["2"]
    assert ["0"] in rows and ["-1"] in rows
    # a literal-default param -> the author's value is the single candidate
    assert list(_probe_inputs(target([JsCoverParam("a", None, "5")]))) == [["5"]]
    # an untyped, non-defaulted param -> refuse (no probe tuples at all)
    assert list(_probe_inputs(target([JsCoverParam("a", None, None)]))) == []
    # one bad param refuses the whole target even when a sibling is fine
    mixed = target([JsCoverParam("a", "number", None), JsCoverParam("b", None, None)])
    assert list(_probe_inputs(mixed)) == []


def test_probe_inputs_is_bounded():
    """A many-argument function's product is capped (deterministic, never explodes)."""
    from app.execution.js.js_strengthen_tests import _MAX_COMBINATIONS

    params = [JsCoverParam(f"p{i}", "number", None) for i in range(8)]
    rows = list(_probe_inputs(JsCoverTarget(
        name="f", params=tuple(params), pure=True, export_kind="named")))
    assert len(rows) == _MAX_COMBINATIONS


# --- driver mutate subcommand (need node) -------------------------------------

@_needs_node
def test_driver_mutate_emits_deterministic_catalog(tmp_path: Path):
    root = _project(tmp_path, {"src/m.ts": _ADD_SRC})
    a = _driver_mutants(root, "src/m.ts", "add")
    b = _driver_mutants(root, "src/m.ts", "add")
    assert a == b  # deterministic
    ops = {m.operator for m in a}
    # add's body `return a + b` seeds an arithmetic flip and a return->undefined.
    assert "arith:+" in ops
    assert "return:undefined" in ops
    plus = next(m for m in a if m.operator == "arith:+")
    assert plus.original == "+" and plus.mutated == "-"


@_needs_node
def test_driver_mutate_comparison_boundary_boolconst_number(tmp_path: Path):
    src = ("export function cmp(x: number): boolean { if (x < 0) { return true; } "
           "return false; }\n")
    root = _project(tmp_path, {"src/c.ts": src})
    ops = {m.operator: m for m in _driver_mutants(root, "src/c.ts", "cmp")}
    # `<` seeds BOTH a comparison flip (->>=) and a boundary flip (-><=).
    assert ops["comparison:<"].mutated == ">="
    assert ops["boundary:<"].mutated == "<="
    # `0` -> `1`; `true`/`false` flip.
    assert ops["number:0"].mutated == "1"
    assert ops["boolconst:true"].mutated == "false"
    assert ops["boolconst:false"].mutated == "true"


@_needs_node
def test_driver_mutate_boolean_connective(tmp_path: Path):
    src = "export function band(p: boolean, q: boolean): boolean { return p && q; }\n"
    root = _project(tmp_path, {"src/b.ts": src})
    ops = {m.operator: m for m in _driver_mutants(root, "src/b.ts", "band")}
    assert ops["boolop:&&"].mutated == "||"


@_needs_node
def test_driver_mutate_refuses_unknown_or_unexported_name(tmp_path: Path):
    src = ("export function add(a: number, b: number) { return a + b; }\n"
           "function helper(a: number) { return a; }\n")
    root = _project(tmp_path, {"src/m.ts": src})
    assert _driver_mutants(root, "src/m.ts", "nope") == []   # not defined
    assert _driver_mutants(root, "src/m.ts", "helper") == []  # not exported


@_needs_node
def test_apply_mutant_is_an_in_memory_span_splice(tmp_path: Path):
    root = _project(tmp_path, {"src/m.ts": _ADD_SRC})
    plus = next(m for m in _driver_mutants(root, "src/m.ts", "add")
                if m.operator == "arith:+")
    mutated = _apply_mutant(_ADD_SRC, plus)
    assert mutated is not None
    assert "return a - b" in mutated  # the `+` span replaced by `-`
    # a stale span out of range -> None (refuse rather than corrupt)
    assert _apply_mutant(_ADD_SRC, JsMutant("x", "+", "-", 9999, 10000)) is None


# --- LAND: a generated jest test that PASSES the real (forced) jest gate -------

@_needs_node
def test_lands_killing_assertion_in_apex_owned_file(tmp_path: Path):
    """The headline LAND: a tested ``add`` whose mined witness (``add(2,0)===2``) is
    blind to ``+``->``-`` gets a killing assertion in the Apex-owned test file, and
    the project's own forced jest gate PASSES it."""
    root = _jest_project(tmp_path, {
        "src/math.ts": _ADD_SRC,
        "src/__tests__/math.test.ts": _ADD_TEST,
    })
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    strengthen = generate_js_strengthen_test(root, "src/math.ts", locate)
    assert strengthen is not None
    assert strengthen.functions == ["add"]
    assert strengthen.test_rel == "src/__tests__/math.apex-mutants.cover.test.ts"
    # the asserted value is the REAL output on a synthesized DIVERGING input
    assert "expect(add(2, 2)).toEqual(4);" in strengthen.content
    # the Apex-owned file imports the SOURCE, never the buyer's test
    assert 'require("../math")' in strengthen.content
    # land it + run the project's own jest gate — BOTH the buyer's test and the new
    # Apex-owned test must pass (>=2 tests).
    p = root / strengthen.test_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(strengthen.content, encoding="utf-8")
    assert _jest_passed(_run_jest(root)) >= 2


@_needs_node
def test_end_to_end_apply_rename_lands_and_jest_stays_green(tmp_path: Path):
    """The full landing: plan -> apply_rename(verify=True) writes the NEW Apex-owned
    test and the project's own jest stays green."""
    root = _jest_project(tmp_path, {
        "src/math.ts": _ADD_SRC,
        "src/__tests__/math.test.ts": _ADD_TEST,
    })
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    plan = plan_js_strengthen_tests(str(root), "src/math.ts")
    assert plan.new_contents  # an assertion was generated
    test_rel = next(iter(plan.new_contents))
    assert test_rel == "src/__tests__/math.apex-mutants.cover.test.ts"
    assert not (root / test_rel).exists()  # not yet written
    # the buyer's existing test must be untouched by the plan
    assert "src/__tests__/math.test.ts" not in plan.new_contents
    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True, result
    assert (root / test_rel).exists()
    assert _jest_passed(_run_jest(root)) >= 2


@_needs_node
def test_lands_boundary_killer_for_comparison_fn(tmp_path: Path):
    """A boundary blind spot: ``atLeast`` tested only with ``atLeast(5)===true`` is
    blind to the ``>=``->``>`` boundary mutant (5 > 5 is false, but 5 >= 5 is true —
    the witness at 5 catches it, so use a witness AWAY from the boundary). With the
    witness ``atLeast(9)===true`` the boundary mutant survives, and a synthesized
    input at the boundary (``atLeast(5)``) diverges."""
    src = ("export function atLeast(n: number): boolean { return n >= 5; }\n")
    test = ('import { atLeast } from "../cmp";\n'
            'test("atLeast", () => { expect(atLeast(9)).toBe(true); });\n')
    root = _jest_project(tmp_path, {
        "src/cmp.ts": src, "src/__tests__/cmp.test.ts": test})
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/cmp.ts", name)

    strengthen = generate_js_strengthen_test(root, "src/cmp.ts", locate)
    assert strengthen is not None
    assert strengthen.functions == ["atLeast"]
    p = root / strengthen.test_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(strengthen.content, encoding="utf-8")
    assert _jest_passed(_run_jest(root)) >= 2


# --- DISJOINTNESS from js-cover-gaps (denetçi-critical) -----------------------

@_needs_node
def test_disjoint_untested_fn_strengthen_refuses_cover_gaps_offers(tmp_path: Path):
    """An UNTESTED pure fn: js-cover-gaps OFFERS (writes the first test), but
    js-strengthen-tests REFUSES (there is no existing test to strengthen)."""
    from app.execution.objectives.js_cover_gaps import plan_js_cover_gaps

    root = _project(tmp_path, {"src/math.ts": _ADD_SRC})  # no linked test
    assert not plan_js_strengthen_tests(str(root), "src/math.ts").new_contents
    assert plan_js_cover_gaps(str(root), "src/math.ts").new_contents


@_needs_node
def test_disjoint_tested_fn_strengthen_offers_cover_gaps_refuses(tmp_path: Path):
    """An ALREADY-tested pure fn whose witness misses a mutant: js-strengthen-tests
    OFFERS (lands a killing assertion), but js-cover-gaps REFUSES (never clobbers a
    function an existing jest test already pins)."""
    from app.execution.objectives.js_cover_gaps import plan_js_cover_gaps

    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": _ADD_TEST})
    assert plan_js_strengthen_tests(str(root), "src/math.ts").new_contents
    assert not plan_js_cover_gaps(str(root), "src/math.ts").new_contents


@_needs_node
def test_disjoint_target_sets_on_a_shared_fixture(tmp_path: Path):
    """On a shared fixture with BOTH an untested and a tested fn, the two objectives'
    landing target sets are DISJOINT (no module is offered by both)."""
    from app.execution.objectives.js_cover_gaps import detect_cover_targets

    root = _project(tmp_path, {
        # tested -> strengthen's lane
        "src/math.ts": _ADD_SRC,
        "src/__tests__/math.test.ts": _ADD_TEST,
        # untested -> cover-gaps' lane
        "src/util.ts": "export function dbl(n: number): number { return n * 2; }\n",
    })
    strengthen_set = set(detect_strengthen_targets(str(root)))
    cover_set = set(detect_cover_targets(str(root)))
    assert "src/math.ts" in strengthen_set
    assert "src/util.ts" in cover_set
    assert strengthen_set.isdisjoint(cover_set)  # mutually exclusive by construction


@_needs_node
def test_strengthen_never_writes_the_buyer_test_file(tmp_path: Path):
    """strengthen lands ONLY its Apex-owned file; the buyer's existing test bytes are
    never in the plan (and stay byte-identical on disk)."""
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": _ADD_TEST})
    before = (root / "src/__tests__/math.test.ts").read_text(encoding="utf-8")
    plan = plan_js_strengthen_tests(str(root), "src/math.ts")
    assert plan.new_contents
    for rel in plan.new_contents:
        assert "apex-mutants.cover.test" in rel  # only the Apex-owned file
        assert rel != "src/__tests__/math.test.ts"
    assert (root / "src/__tests__/math.test.ts").read_text(encoding="utf-8") == before


# --- REFUSE core (each its own test) ------------------------------------------

@_needs_node
def test_refuses_well_tested_fn_no_surviving_mutant(tmp_path: Path):
    """The common no-op: a witness (``add(2,3)===5``) that CATCHES every seeded mutant
    leaves no survivor -> refuse (never a vacuous assertion)."""
    test = ('import { add } from "../math";\n'
            'test("add", () => { expect(add(2, 3)).toBe(5); });\n')
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    assert generate_js_strengthen_test(root, "src/math.ts", locate) is None


@_needs_node
def test_refuses_impure_clock_fn(tmp_path: Path):
    """A non-pure (clock-reading) fn is refused by the AST pure scan even with a
    linked test -> no oracle is ever captured."""
    src = "export function stamp(): number { return Date.now(); }\n"
    test = ('import { stamp } from "../t";\n'
            'test("stamp", () => { expect(typeof stamp()).toBe("number"); });\n')
    root = _project(tmp_path, {"src/t.ts": src, "src/__tests__/t.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/t.ts", name)

    assert generate_js_strengthen_test(root, "src/t.ts", locate) is None


@_needs_node
def test_refuses_red_existing_test_witness_not_green(tmp_path: Path):
    """A RED/stale existing test (its mined witness does NOT match the real fn) cannot
    be trusted as the survival oracle -> refuse (the baseline-OK gate)."""
    # the witness claims add(2,2)===99, which is FALSE on the real add -> red baseline
    test = ('import { add } from "../math";\n'
            'test("add", () => { expect(add(2, 2)).toBe(99); });\n')
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    assert generate_js_strengthen_test(root, "src/math.ts", locate) is None


@_needs_node
def test_refuses_no_mineable_witness(tmp_path: Path):
    """A linked test that pins NO direct ``expect(fn(args)).matcher(expected)`` witness
    (only an indirect assertion) -> nothing to strengthen against -> refuse."""
    # `typeof add(...)` is not a direct call witness the miner reads.
    test = ('import { add } from "../math";\n'
            'test("add", () => { expect(typeof add(1, 2)).toBe("number"); });\n')
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    assert mine_witnesses(root, "src/__tests__/math.test.ts", "add") == []
    assert generate_js_strengthen_test(root, "src/math.ts", locate) is None


@_needs_node
def test_refuses_async_and_generator(tmp_path: Path):
    """async / generator functions are not cover targets (no bare synchronous call /
    a generator returns an iterator) -> refuse even with a linked test."""
    src = ("export async function af(a: number) { return a; }\n"
           "export function* gen() { yield 1; }\n")
    test = ('import { af, gen } from "../ag";\n'
            'test("af", () => { expect(af(1)).toBeDefined(); });\n'
            'test("gen", () => { expect(gen()).toBeDefined(); });\n')
    root = _project(tmp_path, {"src/ag.ts": src, "src/__tests__/ag.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/ag.ts", name)

    assert generate_js_strengthen_test(root, "src/ag.ts", locate) is None


@_needs_node
def test_refuses_non_serializable_return(tmp_path: Path):
    """A class-instance return is not a faithful JSON oracle -> the serializability
    gate declines, so no killing assertion is pinned."""
    src = ("class Box { constructor(public v: number) {} }\n"
           "export function make(n: number): Box { return new Box(n); }\n")
    test = ('import { make } from "../ns";\n'
            'test("make", () => { expect(make(1)).toBeDefined(); });\n')
    root = _project(tmp_path, {"src/ns.ts": src, "src/__tests__/ns.test.ts": test})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/ns.ts", name)

    assert generate_js_strengthen_test(root, "src/ns.ts", locate) is None


@_needs_node
def test_never_overwrites_existing_generated_test(tmp_path: Path):
    """Apex's own generated test path is never clobbered (idempotent re-run)."""
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": _ADD_TEST})
    dest = root / "src" / "__tests__" / "math.apex-mutants.cover.test.ts"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("// existing\n", encoding="utf-8")

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    assert generate_js_strengthen_test(root, "src/math.ts", locate) is None
    assert dest.read_text(encoding="utf-8") == "// existing\n"


@_needs_node
def test_mutant_is_never_persisted_to_the_real_source(tmp_path: Path):
    """The mutant is a gap-FINDER only — generating a plan NEVER writes a mutated
    source to the real tree (the source bytes stay byte-identical)."""
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": _ADD_TEST})
    before = (root / "src/math.ts").read_text(encoding="utf-8")
    plan = plan_js_strengthen_tests(str(root), "src/math.ts")
    assert plan.new_contents  # a strengthening assertion was generated
    # the real source is untouched, and no stray transpile/mutant temp file remains
    assert (root / "src/math.ts").read_text(encoding="utf-8") == before
    stray = [p.name for p in (root / "src").iterdir()
             if p.name.startswith((".apex_mutant", ".apex_real", ".apex_cover"))]
    assert stray == [], stray


def test_plan_refuses_non_js_and_test_targets(tmp_path: Path):
    root = _project(tmp_path, {"src/m.ts": _ADD_SRC})
    assert not plan_js_strengthen_tests(str(root), "pkg/mod.py").new_contents
    assert not plan_js_strengthen_tests(str(root), "src/m.test.ts").new_contents


def test_no_package_json_is_a_clean_no_op(tmp_path: Path):
    root = tmp_path / "nopkg"
    (root / "src").mkdir(parents=True)
    (root / "src" / "m.ts").write_text(_ADD_SRC, encoding="utf-8")
    assert detect_strengthen_targets(str(root)) == []


# --- determinism (need node) --------------------------------------------------

@_needs_node
def test_deterministic_same_module_same_bytes(tmp_path: Path):
    root = _project(tmp_path, {
        "src/math.ts": _ADD_SRC, "src/__tests__/math.test.ts": _ADD_TEST})

    def locate(name: str) -> str | None:
        return _locate_test(root, "src/math.ts", name)

    a = generate_js_strengthen_test(root, "src/math.ts", locate)
    b = generate_js_strengthen_test(root, "src/math.ts", locate)
    assert a is not None and b is not None
    assert a.content == b.content  # byte-identical across runs
    assert a.test_rel == b.test_rel == "src/__tests__/math.apex-mutants.cover.test.ts"


@_needs_node
def test_is_survivor_decides_against_mined_witnesses(tmp_path: Path):
    """The LITE survival contract: the ``+``->``-`` mutant SURVIVES the witness
    ``add(2,0)===2`` (2-0==2, the witness is blind) but is CAUGHT by ``add(2,3)===5``
    (2-3!=5, the witness changes) — decided against the MINED witnesses, no suite run."""
    root = _project(tmp_path, {"src/math.ts": _ADD_SRC})
    src = (root / "src/math.ts").read_text(encoding="utf-8")
    src_file = str((root / "src/math.ts").resolve())
    plus = next(m for m in _driver_mutants(root, "src/math.ts", "add")
                if m.operator == "arith:+")
    blind = mine_witnesses(_project(tmp_path, {  # a fresh project carrying the blind test
        "src/math.ts": _ADD_SRC,
        "src/__tests__/math.test.ts": _ADD_TEST}), "src/__tests__/math.test.ts", "add")
    catching = mine_witnesses(_project(tmp_path, {
        "src/math.ts": _ADD_SRC,
        "src/__tests__/c.test.ts": (
            'import { add } from "../math";\n'
            'test("a", () => { expect(add(2, 3)).toBe(5); });\n'),
    }), "src/__tests__/c.test.ts", "add")
    assert _is_survivor(root, src_file, "add", src, plus, blind) is True
    assert _is_survivor(root, src_file, "add", src, plus, catching) is False


# --- parity: registration / facet / manifest / soundness (always run) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-strengthen-tests" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-strengthen-tests"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # spawns node + mutate + transpile/capture children
    assert spec.scope_verify is True  # red-baseline objective, audited in allowlist


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-strengthen-tests"


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


def test_facet_phrase_lives_in_the_property_invariants_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["property invariants"]
    assert _PHRASE in ladder
    assert ladder[0] == "idempotence"  # originals still lead


def test_move_value_is_below_cover_gaps_and_strengthen():
    from app.engine.move_value import OPERATOR_VALUE, move_value

    assert OPERATOR_VALUE["js_strengthen_tests"] == 0.80
    assert move_value("js_strengthen_tests") == 0.80
    # honest tier: BELOW js-cover-gaps (0.90) and the Python strengthen-tests (0.88)
    assert OPERATOR_VALUE["js_strengthen_tests"] < OPERATOR_VALUE["js_cover_gaps"]
    assert OPERATOR_VALUE["js_strengthen_tests"] < OPERATOR_VALUE["strengthen_tests"]


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "js-strengthen-tests" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_scope_verify_allowed():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-strengthen-tests" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-strengthen-tests"]  # non-empty strategy string
    assert "js-strengthen-tests" in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())  # fast path
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- count-pins (89 total / 44 CONCRETE after js-strengthen-tests) ------------

def test_objective_count_pins():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = available_objectives()
    assert len(set(names)) == 90  # 89 after js-strengthen-tests (89th) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # it is CONCRETE


# --- the new soundness-corpus fixture refuses (the durable denetçi) -----------

def test_soundness_corpus_js_strengthen_env_fragile_is_a_shape():
    from app.engine.soundness_audit import corpus_shapes, repo_root

    assert "js_strengthen_env_fragile" in corpus_shapes(repo_root())


@_needs_node
def test_refuses_on_js_strengthen_env_fragile_corpus_fixture():
    """The durable soundness guarantee: js-strengthen-tests REFUSES the env-fragile JS
    fixture (a clock/random module WITH a linked, witness-mining test) — proving the
    AST + env gates close the flaky-test hole even when the target reaches the value
    gates. And it is a clean no-op on the WHOLE (Python-shaped + JS) corpus."""
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("js-strengthen-tests", {})
    assert cells, "js-strengthen-tests should be swept in the heavy corpus path"
    assert cells.get("js_strengthen_env_fragile") == "refused"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"


# --- jest run helpers ---------------------------------------------------------

def _run_jest(root: Path):
    """Run the project's own forced jest gate and return the run summary."""
    from app.execution.js.js_gate import JEST_COMMAND
    from app.skills.execution.run_tests import RunTestsSkill

    return RunTestsSkill().run(str(root), commands=[JEST_COMMAND])


def _jest_passed(summary) -> int:
    """The number of jest tests that passed in ``summary`` (0 on a vacuous/failed
    run) — via the gate's own positive-execution parser."""
    from app.execution.js.js_gate import _passed_count, jest_ran_and_passed

    return _passed_count(summary) if jest_ran_and_passed(summary) else 0
