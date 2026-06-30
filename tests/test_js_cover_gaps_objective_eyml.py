"""js-cover-gaps develop objective — the JS/TS mirror of cover-gaps / test_shield.

Apex's deterministic JS/TS characterization-test generator: it CALLS an untested
exported JS/TS function with synthesized inputs at generation time and pins
``expect(fn(<args>)).toEqual(<captured>)`` — sound by construction within a
decidable input slice, env-reproducibility-gated, zero-token. The oracle is the
function's OWN executed output, never a guess.

Covers:
* the driver ``cover-targets`` subcommand (typed-primitive / zero-arg / literal-
  default targets; the AST ``pure`` flag refusing clock/random/free-id bodies;
  async/generator/decorated/private exclusions);
* the SOUND input slice (zero-arg / all-primitive-typed / all-literal-default) and
  the untyped-non-defaulted REFUSAL;
* the LAND path — a TS-typed-primitive-arg pure fn and a zero-arg pure fn each
  generate a jest test that PASSES the real (forced) jest gate;
* the REFUSE core (each its own test): Date.now()/Math.random() (AST scan); a
  clock-fragile value that SLIPS the AST scan (the env-reproducibility re-capture
  gate — the key regression); untyped non-defaulted param; async/generator/
  decorated; non-serialisable return; a module with an existing linked test (never
  clobber);
* determinism (same module -> byte-identical test bytes);
* JS tests RUN, not skip (asserted loudly — if node+jest aren't available the heavy
  tests skip with a reason, but a sentinel test FAILS so a silent skip is visible);
* parity (registration + facet + manifest + soundness 1:1) + count-pins (88/43) +
  the FACET reachability invariant + the new soundness-corpus fixture refusing.

The heavy node/jest tests skip cleanly when node + global ``typescript`` + an
installable jest+babel-TS toolchain aren't available; every pure/refusal/parity
test always runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.execution.js.js_cover_gaps import (
    _env_is_reproducible,
    _run_capture,
    _synth_args,
    generate_js_cover_test,
)
from app.execution.js.js_tool import (
    JsCoverParam,
    JsCoverTarget,
    cover_targets,
    global_node_modules,
)
from app.execution.objectives.js_cover_gaps import (
    detect_cover_targets,
    is_js_source,
    plan_js_cover_gaps,
)

_PHRASE = "the untested jest function to characterize"


# --- environment guards (the heavy node/jest path is opt-in by availability) ---

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (cover-targets) AND the transpile/capture
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

    The babel TS preset + commonjs plugin let jest transform a ``.ts`` source AND a
    ``.ts`` test (a buyer with TS would have an equivalent transform configured).
    Memoized so the suite installs at most once."""
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


def _jest_project(tmp_path: Path, rel: str, src: str) -> Path | None:
    """A throwaway jest project with ``rel`` containing ``src`` and a jest+babel-TS
    ``node_modules`` (so both ``.js`` and ``.ts`` run under the project's own jest).
    ``None`` when the toolchain can't be installed offline — the caller then skips.
    Reuses the session-cached ``node_modules`` so only the FIRST heavy test pays."""
    root = tmp_path / "demo"
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


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    """A throwaway project (single ``package.json`` root) with ``rel`` -> ``src``,
    NO ``node_modules`` — for the driver / generator / plan tests that need node to
    parse + capture but not a jest run."""
    root = tmp_path / "proj"
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")
    (root / "package.json").write_text(
        '{ "name": "p", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    return root


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")


# --- the JS-RUNS-NOT-SKIP sentinel (loud, always runs) ------------------------

def test_node_toolchain_is_available_or_warn_loudly():
    """JS tests must RUN, not silently skip. This sentinel makes the env state
    VISIBLE: it passes when node + global typescript are present (the heavy tests
    will run), and FAILS loudly otherwise so a silent skip never hides a broken
    JS lane (STOP+report if this fails in the integrator's env)."""
    assert _node_ok(), (
        "node + global typescript are NOT available — the js-cover-gaps heavy "
        "tests would SKIP. STOP and report: the JS lane cannot be proven here."
    )


# --- pure file-gate tests (always run) ----------------------------------------

def test_is_js_source_accepts_js_ts_rejects_tests_and_python():
    assert is_js_source("src/math.ts")
    assert is_js_source("src/util.js")
    assert is_js_source("lib/a.mjs")
    assert not is_js_source("a.test.ts")
    assert not is_js_source("a.spec.js")
    assert not is_js_source("__tests__/util.ts")
    assert not is_js_source("pkg/mod.py")


def test_synth_args_sound_slice():
    """The SOUND input slice: zero-arg, all-primitive-typed, all-literal-default;
    everything else refuses."""
    def target(params):
        return JsCoverTarget(name="f", params=tuple(params), pure=True,
                             export_kind="named")

    # zero-arg
    assert _synth_args(target([])) == []
    # all primitive-typed
    assert _synth_args(target([
        JsCoverParam("a", "number", None), JsCoverParam("b", "string", None),
        JsCoverParam("c", "boolean", None)])) == ["0", '""', "false"]
    # array type -> []
    assert _synth_args(target([JsCoverParam("xs", "number[]", None)])) == ["[]"]
    assert _synth_args(target([JsCoverParam("xs", "Array<string>", None)])) == ["[]"]
    # all literal-default
    assert _synth_args(target([
        JsCoverParam("a", None, "5"), JsCoverParam("b", None, '"x"')])) == ["5", '"x"']
    # MIXED (typed + defaulted) still all-sound
    assert _synth_args(target([
        JsCoverParam("a", "number", None), JsCoverParam("b", None, "true")])) == ["0", "true"]


def test_synth_args_refuses_untyped_non_defaulted():
    """An untyped, non-defaulted param has no LLM-free sound sample -> REFUSE the
    whole target (the honest reach ceiling)."""
    target = JsCoverTarget(
        name="f", params=(JsCoverParam("a", None, None),), pure=True,
        export_kind="named")
    assert _synth_args(target) is None
    # one bad param refuses even when a sibling is fine
    mixed = JsCoverTarget(
        name="g", params=(JsCoverParam("a", "number", None),
                          JsCoverParam("b", None, None)), pure=True,
        export_kind="named")
    assert _synth_args(mixed) is None


def test_synth_args_refuses_non_primitive_object_type():
    """A non-primitive, non-array object type with no default has no sound sample
    -> refuse (we never synthesize a structured value)."""
    target = JsCoverTarget(
        name="f", params=(JsCoverParam("o", "{x: number}", None),), pure=True,
        export_kind="named")
    assert _synth_args(target) is None


# --- driver cover-targets (need node) -----------------------------------------

@_needs_node
def test_driver_finds_typed_and_zero_arg_pure_targets(tmp_path: Path):
    src = ("export function add(a: number, b: number) { return a + b; }\n"
           "export function greet() { return \"hi\"; }\n")
    root = _project(tmp_path, "src/m.ts", src)
    targets = {t.name: t for t in cover_targets(root, "src/m.ts")}
    assert set(targets) == {"add", "greet"}
    assert targets["add"].pure and targets["greet"].pure
    assert [p.type for p in targets["add"].params] == ["number", "number"]


@_needs_node
def test_driver_pure_flag_refuses_clock_and_random(tmp_path: Path):
    src = ("export function stamp() { return Date.now(); }\n"
           "export function rnd() { return Math.random(); }\n"
           "export function envp() { return process.env.X; }\n")
    root = _project(tmp_path, "src/m.ts", src)
    targets = {t.name: t.pure for t in cover_targets(root, "src/m.ts")}
    assert targets == {"stamp": False, "rnd": False, "envp": False}


@_needs_node
def test_driver_pure_flag_refuses_free_identifier(tmp_path: Path):
    # OUTER is a module-level free identifier in the body -> impure (refuse-on-
    # uncertainty: a free reference could close over external mutable state).
    src = ("const OUTER = 10;\n"
           "export function f(a: number) { return a + OUTER; }\n")
    root = _project(tmp_path, "src/m.ts", src)
    t = {x.name: x.pure for x in cover_targets(root, "src/m.ts")}
    assert t.get("f") is False


@_needs_node
def test_driver_excludes_async_generator_private_unexported(tmp_path: Path):
    src = ("export async function af(a: number) { return a; }\n"
           "export function* gen() { yield 1; }\n"
           "export function _priv(a: number) { return a; }\n"
           "function notExported(a: number) { return a; }\n"
           "export function ok(a: number) { return a; }\n")
    root = _project(tmp_path, "src/m.ts", src)
    names = {t.name for t in cover_targets(root, "src/m.ts")}
    assert names == {"ok"}  # async / generator / private / unexported all excluded


@_needs_node
def test_driver_resolves_cjs_object_export(tmp_path: Path):
    src = ("function greet() { return \"hi\"; }\n"
           "function nums() { return [1, 2]; }\n"
           "module.exports = { greet, nums };\n")
    root = _project(tmp_path, "src/u.js", src)
    names = {t.name for t in cover_targets(root, "src/u.js")}
    assert names == {"greet", "nums"}


# --- LAND: a generated jest test that PASSES the real (forced) jest gate -------

@_needs_node
def test_lands_passing_jest_test_for_typed_primitive_fn(tmp_path: Path):
    src = ("export function add(a: number, b: number): number { return a + b; }\n"
           "export function clampPos(n: number): number { return n < 0 ? 0 : n; }\n")
    root = _jest_project(tmp_path, "src/math.ts", src)
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")
    cover = generate_js_cover_test(
        root, "src/math.ts", lambda name: None)
    assert cover is not None
    assert set(cover.functions) == {"add", "clampPos"}
    # the captured oracle is the REAL return on the synthesized zero inputs
    assert "expect(add(0, 0)).toEqual(0);" in cover.content
    assert "expect(clampPos(0)).toEqual(0);" in cover.content
    # land it and run the project's own jest gate — it must PASS
    p = root / cover.test_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cover.content, encoding="utf-8")
    summary = _run_jest(root)
    assert _jest_passed(summary) >= 2, summary


@_needs_node
def test_lands_passing_jest_test_for_zero_arg_fn(tmp_path: Path):
    src = ("export function greet() { return \"hello\"; }\n"
           "export function shape() { return { ok: true, items: [1, 2] }; }\n")
    root = _jest_project(tmp_path, "src/g.ts", src)
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")
    cover = generate_js_cover_test(root, "src/g.ts", lambda name: None)
    assert cover is not None
    assert set(cover.functions) == {"greet", "shape"}
    assert 'expect(greet()).toEqual("hello");' in cover.content
    # an object return uses toStrictEqual
    assert "toStrictEqual(" in cover.content
    p = root / cover.test_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cover.content, encoding="utf-8")
    assert _jest_passed(_run_jest(root)) >= 2


@_needs_node
def test_end_to_end_apply_rename_lands_and_jest_stays_green(tmp_path: Path):
    """The full landing: plan -> apply_rename(verify=True) writes the NEW test and
    the project's own jest stays green (the new test is the only impacted suite)."""
    src = ("export function clampPos(n: number): number { return n < 0 ? 0 : n; }\n")
    root = _jest_project(tmp_path, "src/clamp.ts", src)
    if root is None:
        pytest.skip("jest+babel-TS could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    plan = plan_js_cover_gaps(str(root), "src/clamp.ts")
    assert plan.new_contents  # a test was generated
    test_rel = next(iter(plan.new_contents))
    assert not (root / test_rel).exists()  # not yet written
    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True, result
    assert (root / test_rel).exists()
    # the landed test really passes the project's own jest
    assert _jest_passed(_run_jest(root)) >= 1


# --- REFUSE core (each its own test) ------------------------------------------

@_needs_node
def test_refuses_date_now_and_math_random_via_ast_scan(tmp_path: Path):
    src = ("export function stamp() { return Date.now(); }\n"
           "export function rnd() { return Math.random(); }\n")
    root = _project(tmp_path, "src/f.ts", src)
    cover = generate_js_cover_test(root, "src/f.ts", lambda name: None)
    assert cover is None  # the AST pure scan refused both -> nothing landable


@_needs_node
def test_env_reproducibility_gate_refuses_clock_value_that_slips_ast(tmp_path: Path):
    """THE key soundness regression: a value that the AST ``pure`` scan would pass
    (here we FORCE ``pure=True`` to bypass it) but that reads the clock / cwd / HOME
    is REFUSED by the ENV-REPRODUCIBILITY re-capture gate — proving the gate, not
    just the AST scan, closes the flaky-test hole. Without this gate the objective
    is UNSOUND."""
    src = ("export function stamp() { return Date.now(); }\n"
           "export function whereAmI() { return process.cwd(); }\n"
           "export function homeDir() { const os = require(\"os\"); "
           "return os.homedir(); }\n"
           "export function stable() { return 42; }\n")
    root = _project(tmp_path, "src/f.ts", src)
    src_abs = str((root / "src/f.ts").resolve())
    for name in ("stamp", "whereAmI", "homeDir"):
        baseline = _run_capture(root, src_abs, name, [], {}, None)
        assert baseline is not None, f"{name}: baseline capture should succeed"
        # the gate must REFUSE the env/clock-fragile value even though it captured
        assert _env_is_reproducible(root, src_abs, name, [], baseline) is False, (
            f"{name}: env-reproducibility gate FAILED to refuse a flaky value")
    # a genuinely stable value passes the SAME gate (the gate is not vacuous)
    stable_base = _run_capture(root, src_abs, "stable", [], {}, None)
    assert stable_base == "42"
    assert _env_is_reproducible(root, src_abs, "stable", [], stable_base) is True


@_needs_node
def test_refuses_untyped_non_defaulted_js_param(tmp_path: Path):
    # plain JS, untyped, non-defaulted param -> no sound input -> refuse.
    src = ("export function echo(a) { return a; }\n")
    root = _project(tmp_path, "src/e.js", src)
    cover = generate_js_cover_test(root, "src/e.js", lambda name: None)
    assert cover is None


@_needs_node
def test_refuses_async_generator_decorated(tmp_path: Path):
    src = ("export async function af(a: number) { return a; }\n"
           "export function* gen() { yield 1; }\n")
    root = _project(tmp_path, "src/ag.ts", src)
    assert generate_js_cover_test(root, "src/ag.ts", lambda name: None) is None


@_needs_node
def test_refuses_non_serializable_return(tmp_path: Path):
    # a class-instance return is not JSON-serialisable to a faithful oracle:
    # JSON.stringify drops methods, so the round-trip would not deep-equal the
    # instance -> the serializability gate declines.
    src = ("class Box { constructor() { this.v = 1; } get() { return this.v; } }\n"
           "export function make() { return new Box(); }\n"
           "export function undef() { return undefined; }\n"
           "export function nan() { return NaN; }\n")
    root = _project(tmp_path, "src/ns.ts", src)
    cover = generate_js_cover_test(root, "src/ns.ts", lambda name: None)
    # `make` returns a class instance with a method -> declined; `undef`/`nan` are
    # non-serialisable too. None is landable, so the whole module yields None.
    assert cover is None


@_needs_node
def test_never_clobbers_module_with_existing_linked_test(tmp_path: Path):
    # A locate_test that reports an EXISTING jest test for the target -> never
    # clobber / duplicate; the function is dropped, leaving nothing landable.
    src = ("export function add(a: number, b: number) { return a + b; }\n")
    root = _project(tmp_path, "src/math.ts", src)
    cover = generate_js_cover_test(
        root, "src/math.ts", lambda name: "__tests__/math.test.ts")
    assert cover is None  # already covered -> no-op (never clobber)


@_needs_node
def test_never_overwrites_existing_generated_test(tmp_path: Path):
    src = ("export function add(a: number, b: number) { return a + b; }\n")
    root = _project(tmp_path, "src/math.ts", src)
    # pre-create the destination generated test path
    dest = root / "src" / "__tests__" / "math.cover.test.ts"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("// existing\n", encoding="utf-8")
    cover = generate_js_cover_test(root, "src/math.ts", lambda name: None)
    assert cover is None  # never clobber a generated test path
    assert dest.read_text(encoding="utf-8") == "// existing\n"


def test_plan_refuses_non_js_and_test_targets(tmp_path: Path):
    root = _project(tmp_path, "src/m.ts", "export function f() { return 1; }\n")
    # a Python file / a test file are never subjects (no node needed — pure gate)
    assert not plan_js_cover_gaps(str(root), "pkg/mod.py").new_contents
    assert not plan_js_cover_gaps(str(root), "src/m.test.ts").new_contents


def test_no_package_json_is_a_clean_no_op(tmp_path: Path):
    # the single-package.json gate: no package.json at root -> no candidates.
    root = tmp_path / "nopkg"
    (root / "src").mkdir(parents=True)
    (root / "src" / "m.ts").write_text(
        "export function f() { return 1; }\n", encoding="utf-8")
    assert detect_cover_targets(str(root)) == []


# --- determinism (need node) --------------------------------------------------

@_needs_node
def test_deterministic_same_module_same_bytes(tmp_path: Path):
    src = ("export function add(a: number, b: number) { return a + b; }\n"
           "export function tag() { return { k: 1, v: [2, 3] }; }\n")
    root = _project(tmp_path, "src/m.ts", src)
    a = generate_js_cover_test(root, "src/m.ts", lambda name: None)
    b = generate_js_cover_test(root, "src/m.ts", lambda name: None)
    assert a is not None and b is not None
    assert a.content == b.content  # byte-identical across runs
    assert a.test_rel == b.test_rel == "src/__tests__/m.cover.test.ts"


# --- parity: registration / facet / manifest / soundness (always run) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-cover-gaps" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-cover-gaps"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # spawns node + transpile/capture children
    assert spec.scope_verify is True  # red-baseline objective, audited in allowlist


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-cover-gaps"


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


def test_facet_phrase_lives_in_a_test_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["property invariants"]
    assert _PHRASE in ladder
    assert ladder[0] == "idempotence"  # originals still lead


def test_move_value_is_tier1():
    from app.engine.move_value import OPERATOR_VALUE, move_value

    assert OPERATOR_VALUE["js_cover_gaps"] == 0.90
    assert move_value("js_cover_gaps") == 0.90


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "js-cover-gaps" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_scope_verify_allowed():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-cover-gaps" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-cover-gaps"]  # non-empty strategy string
    assert "js-cover-gaps" in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())  # fast path
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- count-pins (88 total / 43 CONCRETE after js-cover-gaps) ------------------

def test_objective_count_pins():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = available_objectives()
    assert len(set(names)) == 88  # 88 after js-cover-gaps (88th) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 43  # js-cover-gaps is CONCRETE


# --- the new soundness-corpus fixture refuses (the durable denetçi) -----------

def test_soundness_corpus_js_env_fragile_return_is_a_shape():
    from app.engine.soundness_audit import corpus_shapes, repo_root

    assert "js_env_fragile_return" in corpus_shapes(repo_root())


@_needs_node
def test_refuses_on_js_env_fragile_return_corpus_fixture():
    # The durable soundness guarantee: js-cover-gaps REFUSES the env-fragile JS
    # fixture (a Date.now()/Math.random() module) — the JS image of
    # env_fragile_return — proving the AST + env gates close the flaky-test hole.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("js-cover-gaps", {})
    assert cells, "js-cover-gaps should be swept in the heavy corpus path"
    assert cells.get("js_env_fragile_return") == "refused"
    # and it is a clean no-op on the WHOLE (Python-shaped + JS) corpus
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
