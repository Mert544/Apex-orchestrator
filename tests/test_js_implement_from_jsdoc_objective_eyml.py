"""js-implement-from-jsdoc develop objective — the JS/TS image of
implement-from-doctest, the DISJOINT sibling of js-tdd-implement.

A developer wrote a ``throw``-stub whose contract lives ONLY in its own JSDoc
``@example`` block and that NO jest test references; js-implement-from-jsdoc
deterministically mines witnesses from the ``@example`` lines (no LLM),
synthesises a body from the SAME FIXED template space js-tdd-implement uses
(passthrough -> binary -> reduction -> constant-with->=2-witnesses) via the
bundled TypeScript Compiler API driver, and keeps the FIRST template whose
GENERATED jest spec (built from the ``@example`` lines, run in a THROWAWAY copy)
goes green, else REFUSES. Byte-for-byte rollback on failure; the generated spec
is NEVER written to the real tree.

Covers: the new ``mine-jsdoc`` driver subcommand (=== and expect().toBe() shapes,
arrow stubs, array args, prose-line skip, refusals); the generated-spec text; the
INVERSE trigger (a stub a jest test pins is js-tdd-implement's, never
double-counted); the plan (lands the body, captures the original, refuses non-JS /
contradiction / no-template); the END-TO-END landing (``apply_rename`` verify=True
lands the body and the real jest suite stays green) and the byte-for-byte ROLLBACK;
idempotence; the never-write-a-test-into-the-real-tree guarantee; plus objective
registration / facet+manifest+soundness 1:1 parity. The heavy npm/jest tests skip
cleanly when node + global ``typescript`` + an installable jest aren't available;
every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.execution.js.js_jsdoc_synthesis import generated_spec_source
from app.execution.js.js_tool import (
    JsStub,
    JsWitness,
    global_node_modules,
    mine_jsdoc_witnesses,
    scan_stubs,
)
from app.execution.objectives.js_implement_from_jsdoc import (
    detect_js_jsdoc_stubs,
    is_js_source,
    plan_js_implement_from_jsdoc,
)

_PHRASE = "the jsdoc example whose function to write"

# A stubbed CJS module whose contract is its OWN JSDoc @example (the === shape) and
# NO jest test — the js-implement-from-jsdoc beachhead shape.
_MATH_JS = (
    "/**\n"
    " * Add two numbers.\n"
    " * @param {number} a\n"
    " * @param {number} b\n"
    " * @example\n"
    " * add(2, 3) === 5\n"
    " * add(10, 20) === 30\n"
    " */\n"
    "function add(a, b) {\n"
    '  throw new Error("Not implemented");\n'
    "}\n"
    "module.exports = { add };\n"
)


# --- environment guards (the heavy npm/jest path is opt-in by availability) ---

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (scan/mine-jsdoc/fill) to run."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_JEST_CACHE: dict[str, Path | None] = {}


def _ensure_jest_node_modules() -> Path | None:
    """A directory holding an installed jest ``node_modules``, built once per
    session (shared with the js-tdd-implement suite's cache dir so jest installs at
    most once for both), or ``None`` when the install fails."""
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


def _jest_demo(tmp_path: Path) -> Path | None:
    """A throwaway jest project with a JSDoc-only stub (``src/math.js`` — its
    contract is its ``@example`` block, and NO jest test links it) PLUS one
    UNRELATED passing jest test, with jest installed into its own ``node_modules``.
    ``None`` when jest can't be installed offline — the caller then skips.

    The unrelated test is what makes this REALISTIC: a real project has a jest
    suite (so the full-suite gate is non-empty and green), it just has no test for
    THIS particular JSDoc-stubbed function — exactly the white space this objective
    fills. It does NOT reference ``add`` (referencing it would flip the trigger to
    js-tdd-implement's), so ``add`` stays a jsdoc-only candidate while the suite
    stays green for the ``apply_rename`` backstop to verify against."""
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "__tests__").mkdir()
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "src" / "math.js").write_text(_MATH_JS, encoding="utf-8")
    # An UNRELATED green test (never names ``add``) so the suite is non-empty.
    (root / "__tests__" / "sanity.test.js").write_text(
        'test("sanity", () => { expect(1 + 1).toBe(2); });\n', encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        return None
    shutil.copytree(cached, root / "node_modules")
    return root


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


def test_refuses_jest_test_and_fixture_write_targets():
    # A jest test file is never a WRITE target (Apex never edits the suite, and
    # never the SPEC it generates either).
    assert not is_js_source("src/math.test.js")
    assert not is_js_source("a.spec.ts")
    assert not is_js_source("__tests__/math.js")


def test_plan_refuses_non_js_file_outright(tmp_path: Path):
    # A JsJsdocStub pointing at a .py path: plan_js_implement_from_jsdoc refuses it
    # before touching anything — the load-bearing no-op on the Python path.
    from app.execution.objectives.js_implement_from_jsdoc import JsJsdocStub

    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=1)
    mb = JsJsdocStub(stub=stub, file_rel="app/mod.py")
    plan = plan_js_implement_from_jsdoc(str(tmp_path), mb)
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_package_json(tmp_path: Path):
    # The single-project gate: no package.json at root -> detect nothing, so the
    # objective is a clean no-op on a non-JS (e.g. pure-Python) tree.
    _project(tmp_path, "src/math.js", _MATH_JS)
    assert detect_js_jsdoc_stubs(str(tmp_path)) == []


# --- the GENERATED jest spec text (pure, no node) -----------------------------

def test_generated_spec_imports_and_asserts_each_witness():
    spec = generated_spec_source(
        "src/math.js", "add",
        [JsWitness(("2", "3"), "5"), JsWitness(("10", "20"), "30")])
    assert 'const { add } = require("./math");' in spec
    assert "expect(add(2, 3)).toEqual(5);" in spec
    assert "expect(add(10, 20)).toEqual(30);" in spec
    # It is a real jest test block.
    assert "test(" in spec and "});" in spec


def test_generated_spec_is_deterministic():
    w = [JsWitness(("1",), "1")]
    assert generated_spec_source("a/b.ts", "f", w) == generated_spec_source("a/b.ts", "f", w)


def test_generated_spec_never_lands_in_the_real_tree_name():
    # The spec basename is unmistakably a throwaway .test.js so jest discovers it in
    # the COPY — and is_js_source refuses it as a write target in the real tree.
    assert not is_js_source("src/math.apexjsdoc.test.js")


# --- the new mine-jsdoc driver subcommand (need node) -------------------------

@_needs_node
def test_driver_mines_jsdoc_strict_equality_examples(tmp_path: Path):
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    witnesses = mine_jsdoc_witnesses(root, "src/math.js", "add")
    assert witnesses == [JsWitness(("2", "3"), "5"), JsWitness(("10", "20"), "30")]


@_needs_node
def test_driver_mines_jsdoc_expect_tobe_and_arrow_and_array_args(tmp_path: Path):
    src = (
        "/**\n"
        " * @example\n"
        " * expect(head([1, 2, 3])).toBe(1)\n"
        ' * expect(head(["a", "b"])).toBe("a")\n'
        " */\n"
        "const head = (xs) => { throw new Error('nope'); };\n"
        "module.exports = { head };\n"
    )
    root = _project(tmp_path, "src/h.js", src)
    witnesses = mine_jsdoc_witnesses(root, "src/h.js", "head")
    # array args (with nested commas) survive verbatim; expect().toBe() is mined.
    assert witnesses == [JsWitness(("[1, 2, 3]",), "1"), JsWitness(('["a", "b"]',), '"a"')]


@_needs_node
def test_driver_mine_jsdoc_skips_prose_lines(tmp_path: Path):
    src = (
        "/**\n"
        " * @example\n"
        " * The length of a list:\n"
        " * size([1, 2, 3]) === 3\n"
        " * size([]) === 0\n"
        " */\n"
        "function size(xs) { throw new Error('x'); }\n"
        "module.exports = { size };\n"
    )
    root = _project(tmp_path, "src/s.js", src)
    assert mine_jsdoc_witnesses(root, "src/s.js", "size") == [
        JsWitness(("[1, 2, 3]",), "3"), JsWitness(("[]",), "0")]


@_needs_node
def test_driver_mine_jsdoc_refuses_stub_without_example(tmp_path: Path):
    src = ("/**\n * Just a description, no example.\n * @param {number} a\n */\n"
           "function noop(a) { throw new Error('x'); }\n"
           "module.exports = { noop };\n")
    root = _project(tmp_path, "src/n.js", src)
    assert mine_jsdoc_witnesses(root, "src/n.js", "noop") == []


@_needs_node
def test_driver_mine_jsdoc_refuses_stub_without_jsdoc(tmp_path: Path):
    # A stub with NO leading JSDoc at all -> empty (this objective never claims it).
    root = _project(tmp_path, "src/b.js",
                    "function bare(a) { throw new Error('x'); }\n"
                    "module.exports = { bare };\n")
    assert mine_jsdoc_witnesses(root, "src/b.js", "bare") == []


@_needs_node
def test_driver_mine_jsdoc_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/broken.js", "function ( {\n")
    assert mine_jsdoc_witnesses(root, "src/broken.js", "x") == []  # conservative empty


# --- DETECT: the INVERSE trigger (need node for scan) -------------------------

@_needs_node
def test_detects_jsdoc_stub_with_no_linking_test(tmp_path: Path):
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    found = detect_js_jsdoc_stubs(str(root))
    assert len(found) == 1
    assert found[0].stub.name == "add"
    assert found[0].file_rel == "src/math.js"


@_needs_node
def test_refuses_when_a_jest_test_links_the_stub_no_double_count(tmp_path: Path):
    # The DISJOINT mirror of js-tdd-implement: a stub a jest test pins is
    # js-tdd-implement's territory -> this objective refuses (never double-counts).
    root = _project(tmp_path, "src/math.js", _MATH_JS)
    _project(tmp_path, "__tests__/math.test.js",
             'const { add } = require("../src/math");\n'
             'test("add", () => { expect(add(2, 3)).toBe(5); });\n')
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    # js-implement-from-jsdoc REFUSES it...
    assert detect_js_jsdoc_stubs(str(root)) == []
    # ...and js-tdd-implement CLAIMS it (the partition is exact).
    from app.execution.objectives.js_tdd_implement import detect_js_stubs

    tdd = detect_js_stubs(str(root))
    assert [m.stub.name for m in tdd] == ["add"]


# --- the END-TO-END landing + byte-for-byte rollback (need node + jest) -------

@_needs_node
def test_end_to_end_lands_body_from_jsdoc_and_keeps_jest_green(tmp_path: Path):
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    found = detect_js_jsdoc_stubs(str(root))
    assert len(found) == 1
    plan = plan_js_implement_from_jsdoc(str(root), found[0])
    assert plan.ok
    assert plan.originals["src/math.js"] == _MATH_JS  # original captured

    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (root / "src" / "math.js").read_text(encoding="utf-8")
    assert "return a + b;" in landed  # binary template won (passthrough rejected)
    assert "module.exports = { add };" in landed  # surrounding source untouched
    assert " * @example" in landed  # the JSDoc contract survives the splice


@_needs_node
def test_planning_never_writes_a_test_or_touches_the_real_tree(tmp_path: Path):
    # The synthesiser probes a THROWAWAY COPY (writing the generated spec ONLY
    # there), so building the plan leaves the real source byte-identical AND writes
    # NO ``.apexjsdoc.test.js`` anywhere in the real tree.
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    before = (root / "src" / "math.js").read_text(encoding="utf-8")
    mb = detect_js_jsdoc_stubs(str(root))[0]
    plan = plan_js_implement_from_jsdoc(str(root), mb)
    assert plan.new_contents  # a body WAS synthesised
    assert (root / "src" / "math.js").read_text(encoding="utf-8") == before
    assert list(root.glob("**/*.apexjsdoc.test.js")) == []  # no spec in the real tree


@_needs_node
def test_refuses_contradictory_example_no_template_satisfies(tmp_path: Path):
    # A stub whose @example is self-contradictory (no fixed template reproduces
    # both): the generated spec stays RED for every candidate -> REFUSE, file
    # byte-unchanged.
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    (root / "src" / "bad.js").write_text(
        "/**\n * @example\n * weird(1, 2) === 99\n * weird(3, 4) === 7\n */\n"
        'function weird(a, b) {\n  throw new Error("Not implemented");\n}\n'
        "module.exports = { weird };\n", encoding="utf-8")
    before = (root / "src" / "bad.js").read_text(encoding="utf-8")
    located = [mb for mb in detect_js_jsdoc_stubs(str(root)) if mb.stub.name == "weird"]
    assert len(located) == 1  # it IS a jsdoc candidate (has an @example, no test)
    plan = plan_js_implement_from_jsdoc(str(root), located[0])
    assert not plan.new_contents  # refuse: no fixed template satisfies the contract
    assert not plan.blockers
    assert (root / "src" / "bad.js").read_text(encoding="utf-8") == before


@_needs_node
def test_refuses_when_no_template_passes_file_unchanged(tmp_path: Path):
    # ``shout(s) === "HI"`` needs .toUpperCase(), outside the v0 template space, so
    # every candidate leaves the generated spec RED -> REFUSE, real file byte-unchanged.
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    (root / "src" / "str.js").write_text(
        '/**\n * @example\n * shout("hi") === "HI"\n */\n'
        'function shout(s) {\n  throw new Error("Not implemented");\n}\n'
        "module.exports = { shout };\n", encoding="utf-8")
    before = (root / "src" / "str.js").read_text(encoding="utf-8")
    located = [mb for mb in detect_js_jsdoc_stubs(str(root)) if mb.stub.name == "shout"]
    assert len(located) == 1
    plan = plan_js_implement_from_jsdoc(str(root), located[0])
    assert not plan.new_contents
    assert (root / "src" / "str.js").read_text(encoding="utf-8") == before


@_needs_node
def test_idempotent_after_fill_no_stub_no_op(tmp_path: Path):
    # After the body lands, the stub is gone -> the second scan sees no throw-stub
    # -> nothing detected (idempotent no-op).
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    mb = detect_js_jsdoc_stubs(str(root))[0]
    plan = plan_js_implement_from_jsdoc(str(root), mb)
    apply_rename(str(root), plan, verify=True, impact_scope=False)
    # a real body now lives where the stub was -> scan finds no stub -> no candidate
    assert scan_stubs(root, "src/math.js") == []
    assert detect_js_jsdoc_stubs(str(root)) == []


@_needs_node
def test_byte_for_byte_rollback_on_full_suite_regression(tmp_path: Path):
    # A separate jest test in the SAME suite pins add(1,1)==3 (false), so the body
    # that satisfies the @example still leaves the FULL suite RED. apply_rename
    # verifies, finds red, and restores src/math.js byte-for-byte (never-fake-green).
    root = _jest_demo(tmp_path)
    if root is None:
        pytest.skip("jest could not be installed offline")
    from app.execution.cross_file_rename import apply_rename

    mb = detect_js_jsdoc_stubs(str(root))[0]
    plan = plan_js_implement_from_jsdoc(str(root), mb)
    assert plan.ok  # a body was synthesised against the @example contract alone
    original = (root / "src" / "math.js").read_text(encoding="utf-8")
    # NOW poison the suite: a pinning test the full-suite gate will run.
    (root / "__tests__").mkdir(exist_ok=True)
    (root / "__tests__" / "regress.test.js").write_text(
        'const { add } = require("../src/math");\n'
        'test("contradictory", () => { expect(add(1, 1)).toBe(3); });\n',
        encoding="utf-8")
    result = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    assert (root / "src" / "math.js").read_text(encoding="utf-8") == original


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "js-implement-from-jsdoc" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["js-implement-from-jsdoc"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # spawns node + jest per candidate
    assert spec.scope_verify is True  # red-baseline objective, like implement-from-doctest


def test_parity_move_value_tier_one():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("js_implement_from_jsdoc") == 1.00  # the proven landing tier
    assert objective_value("js-implement-from-jsdoc") == 1.00
    assert objective_value("js-implement-from-jsdoc") != DEFAULT_VALUE


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "js-implement-from-jsdoc"


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
    assert "js-implement-from-jsdoc" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_missing_operation_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["the missing operation on the contract"]
    assert _PHRASE in ladder
    assert ladder[0] == "the operation signature"  # originals still lead
    # appended right after the Python worked-example phrase (the landing cluster).
    assert ladder.index(_PHRASE) == ladder.index("the worked example to satisfy") + 1


def test_soundness_strategy_declared_and_scope_verify_allowed():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "js-implement-from-jsdoc" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["js-implement-from-jsdoc"]  # non-empty strategy string
    assert "js-implement-from-jsdoc" in SCOPE_VERIFY_ALLOWLIST  # scope_verify is audited
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 86  # 86 after modernize-typing (86th, TIDY) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 41  # promote-staticmethod (85th) is TIDY, not CONCRETE


def test_north_star_and_soundness_audits_pass():
    # The two RAISE-on-drift audits both PASS with the new objective wired (parity 1:1).
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_refuses_on_python_soundness_corpus():
    # The standing soundness corpus is Python-shaped (pkg/*.py, no package.json);
    # the objective must REFUSE on each — the no-op-on-Python guarantee that keeps
    # every existing Python corpus shape byte-identical.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("js-implement-from-jsdoc", {})
    assert cells, "js-implement-from-jsdoc should be swept in the heavy corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
