"""java-final-parameter develop objective — the parameter-level sibling of
java-finalize-field, and a STRONGER soundness case: a runtime no-op modifier-add
on a declared method/constructor parameter PROVABLY never reassigned in that
method's OWN body.

For an own non-test ``.java`` source, java-final-parameter lands the ONE missing
``final`` modifier on any declared parameter never reassigned anywhere in its
method (``void f(int x)`` -> ``void f(final int x)``) — a byte-splice of
``final `` just before the parameter's type token. Adding ``final`` to an
already-never-reassigned parameter is a RUNTIME no-op — the structural fact-set
(declared types + fields + method signatures) is unchanged BY CONSTRUCTION,
verified by an in-driver re-parse — so NO Maven/Gradle/JUnit/compile run is ever
needed (Tier A).

Why it needs NO whole-unit refusal (unlike java-finalize-field): a parameter is a
stack-local variable whose entire assignment surface is closed to its own
method's body — no reflection, no deserializer, no other file or method can ever
write it. So a PER-METHOD scan (not a whole-FILE scan) is both necessary and
sufficient, and is strictly SOUNDER than the field sibling.

Covers: the driver (``final-param-targets`` facts + the ``parse-verify`` re-parse
oracle, refusals); the target-detection (never-reassigned declared parameters,
SKIPPING reassigned / already-final / no-body methods); the deterministic
source-order splice + idempotence; the plan (lands ``final``, captures the
original, refuses non-Java / no marker / test file); the END-TO-END landing (the
sealed file re-parses with the IDENTICAL fact-set, surrounding source untouched)
and that planning never touches the real tree; determinism across
PYTHONHASHSEED; plus objective registration / facet+manifest+soundness 1:1
parity (the SIX registries the new objective must appear in) AND the
must-refuse-on-the-Java-corpus-fixture. The heavy ``java`` tests skip cleanly
when a JDK is not on PATH; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    final_param_targets,
    parse_facts,
    reparse_facts_identical,
)
from app.execution.objectives.java_final_parameter import (
    detect_final_parameter_targets,
    finalizable_param_targets,
    is_java_source,
    plan_java_final_parameter,
    splice_final_params,
)

_PHRASE = "the never-reassigned java method parameter to finalize"

# A class exercising every branch of the per-method scan: `add`'s params are never
# reassigned (-> LAND both); `bump`'s `x` is reassigned via `=` (-> SKIP); `tick`'s
# `n` is reassigned via `+=` (-> SKIP); `dec`'s `n` is reassigned via `--` (-> SKIP);
# `already`'s `w` is already final (-> SKIP, idempotency); the constructor's `seed`
# is never reassigned (-> LAND); `noBody` is abstract (no body -> SKIP its param
# entirely, never vacuously accepted).
_CALC_JAVA = (
    "package demo;\n"
    "\n"
    "public abstract class Calc {\n"
    "    private int total;\n"
    "\n"
    "    int add(int a, int b) {\n"
    "        return a + b;\n"
    "    }\n"
    "\n"
    "    void bump(int x) {\n"
    "        x = x + 1;\n"
    "        total = x;\n"
    "    }\n"
    "\n"
    "    void tick(int n) {\n"
    "        n += 1;\n"
    "        total = n;\n"
    "    }\n"
    "\n"
    "    void dec(int n) {\n"
    "        n--;\n"
    "        total = n;\n"
    "    }\n"
    "\n"
    "    void already(final int w) {\n"
    "        total = w;\n"
    "    }\n"
    "\n"
    "    Calc(int seed) {\n"
    "        this.total = seed;\n"
    "    }\n"
    "\n"
    "    abstract void noBody(int y);\n"
    "}\n"
)


# --- environment guards (the heavy java path is opt-in by availability) -------

def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (final-param-targets / parse-verify) to run."""
    return shutil.which("java") is not None


_needs_jdk = pytest.mark.skipif(not _jdk_ok(), reason="no JDK (java) on PATH")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _with_gradle(root: Path) -> Path:
    (root / "build.gradle").write_text(
        "// marker only\n", encoding="utf-8")
    return root


# --- the file gate (always runs — pure, no java; reused from java_finalize_field) --

def test_refuses_non_java_python_file():
    assert not is_java_source("app/mod.py")
    assert not is_java_source("setup.py")


def test_accepts_java_source():
    assert is_java_source("src/main/java/Main.java")
    assert is_java_source("Foo.java")


def test_refuses_junit_test_write_target():
    assert not is_java_source("FooTest.java")
    assert not is_java_source("src/test/java/Foo.java")


# --- the splice (always runs — pure byte ops, no java) ------------------------

def test_splice_final_params_inserts_at_offset_bottom_up():
    from app.execution.java.java_tool import JavaFinalParamTarget

    src = "void f(int a, int b) {}"
    # offsets 7 (start of `int a`) and 14 (start of `int b`)
    targets = [
        JavaFinalParamTarget("f", "a", 7),
        JavaFinalParamTarget("f", "b", 14),
    ]
    out = splice_final_params(src, targets)
    assert out == "void f(final int a, final int b) {}"


def test_splice_final_params_refuses_out_of_range_offset():
    from app.execution.java.java_tool import JavaFinalParamTarget

    assert splice_final_params(
        "void f(int a) {}", [JavaFinalParamTarget("f", "a", 999)]) is None


def test_splice_final_params_noop_returns_none():
    assert splice_final_params("void f(int a) {}", []) is None


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_final_parameter(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing.
    _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    assert detect_final_parameter_targets(str(tmp_path)) == []


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_gradle(tmp_path)
    plan = plan_java_final_parameter(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


# --- the driver: final-param-targets (needs java) ------------------------------

@_needs_jdk
def test_driver_finds_only_never_reassigned_declared_parameters(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_param_targets(root, "src/Calc.java")
    pairs = [(t.method, t.name) for t in targets]
    # ONLY add's a/b and the constructor's seed — every reassigned param
    # (bump/tick/dec) is skipped, already's w is already final, and noBody's y is
    # skipped WHOLESALE because the method has no body to scan.
    assert pairs == [("add", "a"), ("add", "b"), ("Calc", "seed")]


@_needs_jdk
def test_driver_skips_param_reassigned_by_plain_equals(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void bump(int x) { x = x + 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_param_reassigned_by_compound_assign(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void tick(int n) { n += 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_param_reassigned_by_decrement(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void dec(int n) { n--; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_abstract_method_with_no_body(tmp_path: Path):
    # Non-tautological: WITHOUT the no-body gate, an abstract method's parameter
    # would be vacuously "never reassigned" (there is no body to scan) and get
    # falsely sealed — the driver must skip the WHOLE method instead.
    src = (
        "public abstract class C {\n"
        "    abstract void noBody(int y);\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_native_method_with_no_body(tmp_path: Path):
    src = (
        "public class C {\n"
        "    native void nativeMethod(int z);\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_already_final_param(tmp_path: Path):
    # Non-tautological: an already-`final` parameter must be OMITTED (the
    # idempotency guard) — without the already-final check it would be listed
    # again (harmless syntactically, but a wasted/duplicate splice attempt).
    src = (
        "public class C {\n"
        "    void already(final int w) { System.out.println(w); }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_lands_offset_just_before_type_token(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_param_targets(root, "src/Calc.java")
    by_name = {(t.method, t.name): t.insert_offset for t in targets}
    off = by_name[("add", "a")]
    assert _CALC_JAVA[off:].startswith("int a")


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { void f(int x = ; }")
    assert parse_facts(root, "src/Broken.java") is None
    assert final_param_targets(root, "src/Broken.java") == []


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_finalizable_param_targets_filters_to_never_reassigned(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    pairs = [(t.method, t.name) for t in finalizable_param_targets(root, "src/Calc.java")]
    assert pairs == [("add", "a"), ("add", "b"), ("Calc", "seed")]


@_needs_jdk
def test_reparse_facts_identical_true_for_final_param_splice(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_param_targets(root, "src/Calc.java")
    sealed = splice_final_params(_CALC_JAVA, list(targets))
    assert sealed is not None
    assert "int add(final int a, final int b)" in sealed
    # the reassigned/already-final/no-body params are UNTOUCHED
    assert "void bump(int x)" in sealed
    assert "void already(final int w)" in sealed  # already final, unchanged
    assert reparse_facts_identical(root, "src/Calc.java", sealed)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_param_splice(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    corrupt = _CALC_JAVA.replace("int add(int a, int b)", "int add(int @@@ a, int b)")
    assert not reparse_facts_identical(root, "src/Calc.java", corrupt)


# --- the plan: never-reassigned parameters get `final` ------------------------

@_needs_jdk
def test_plan_lands_final_on_eligible_file(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_final_parameter(str(root), "src/Calc.java")
    assert plan.ok
    assert plan.originals["src/Calc.java"] == _CALC_JAVA
    assert plan.edits_by_file["src/Calc.java"] == 3  # a, b, seed
    sealed = plan.new_contents["src/Calc.java"]
    assert "int add(final int a, final int b)" in sealed
    assert "Calc(final int seed)" in sealed
    # reassigned params stay untouched
    assert "void bump(int x)" in sealed
    assert "void tick(int n)" in sealed
    assert "void dec(int n)" in sealed
    assert "void already(final int w)" in sealed
    assert "abstract void noBody(int y)" in sealed


@_needs_jdk
def test_plan_refuses_when_no_eligible_param(tmp_path: Path):
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    void bump(int x) { x = x + 1; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_final_parameter(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/CalcTest.java", _CALC_JAVA)
    assert not plan_java_final_parameter(str(root), "src/CalcTest.java").new_contents


@_needs_jdk
def test_detects_and_locates_finalizable_files(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    _project(root, "src/AllReassigned.java",
             "public class AllReassigned {\n"
             "    void bump(int x) { x = 1; }\n"
             "}\n")  # refused (its only param is reassigned)
    assert detect_final_parameter_targets(str(root)) == ["src/Calc.java"]


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_final_parameter(str(root), "src/Calc.java")
    sealed = plan.new_contents["src/Calc.java"]
    _project(root, "src/Calc2.java", sealed)
    assert not plan_java_final_parameter(str(root), "src/Calc2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    a = plan_java_final_parameter(str(root), "src/Calc.java").new_contents
    b = plan_java_final_parameter(str(root), "src/Calc.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_final_parameter import plan_java_final_parameter\n"
        "plan = plan_java_final_parameter(%r, 'src/Calc.java')\n"
        "sys.stdout.write(plan.new_contents.get('src/Calc.java', '<none>'))\n"
        % str(root)
    )

    def _run(seed: str) -> str:
        import os

        env = {"PYTHONHASHSEED": seed, "PATH": os.environ.get("PATH", "")}
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).resolve().parents[1]), check=True)
        return out.stdout

    first = _run("0")
    second = _run("12345")
    assert first == second
    assert "int add(final int a, final int b)" in first


# --- end-to-end: gated apply, real landing, fact-set identical ----------------

@_needs_jdk
def test_end_to_end_lands_final_and_reparses_identical(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename

    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before_facts = parse_facts(root, "src/Calc.java")

    plan = plan_java_final_parameter(str(root), "src/Calc.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    assert "int add(final int a, final int b)" in landed
    # the structural fact-set is UNCHANGED — a final modifier is a runtime no-op
    assert parse_facts(root, "src/Calc.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    plan = plan_java_final_parameter(str(root), "src/Calc.java")
    assert plan.new_contents
    assert (root / "src" / "Calc.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-final-parameter" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-final-parameter"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # runtime-noop modifier add; no red-baseline veto


def test_objective_total_is_ninety_two():
    from app.engine.objective_compiler import available_objectives

    # 92 after java-final-parameter (java-finalize-field's parameter-level sibling).
    assert len(set(available_objectives())) == 92


# --- PARITY ROW 1: move_value tier (matches java-finalize-field's runtime-noop tier) --

def test_parity_move_value_matches_java_finalize_field_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_final_parameter") == 0.34
    assert move_value("java_final_parameter") == move_value("java_finalize_field")
    assert objective_value("java-final-parameter") == 0.34
    assert objective_value("java-final-parameter") != DEFAULT_VALUE


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-final-parameter" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_forty_seven():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 47  # java-final-parameter (47th CONCRETE)


# --- PARITY ROW 3: soundness-strategy manifest --------------------------------

def test_parity_soundness_strategy_present_and_no_scope_verify_entry():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "java-final-parameter" in sc
    assert SOUNDNESS_STRATEGY["java-final-parameter"]  # non-empty strategy string
    assert "java-final-parameter" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-final-parameter"
    # the standing 1:1 invariant: the facet map reaches EXACTLY the registry.
    assert len(set(FACET_OBJECTIVE_MAP.values())) == len(set(available_objectives()))
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_parity_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_parity_facet_phrase_lives_in_extension_points_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["extension points"]
    assert _PHRASE in ladder
    # the java-finalize-field field sibling stays directly before it (appended
    # right after it).
    assert ladder[ladder.index(_PHRASE) - 1] == "the never-reassigned java field to finalize"


# --- PARITY ROW 6: owner-report Java language coverage ------------------------

def test_parity_owner_report_lists_java_for_the_new_slug():
    from app.reporting.owner_report import _JAVA_NAME_PREFIXES, _languages_for

    # A java- slug contributes "Java" automatically via the shared prefix rule —
    # no per-objective owner_report entry is required for language coverage.
    assert _languages_for(["java-final-parameter"]) == ["Java"]
    assert all("java-final-parameter".startswith(p) for p in _JAVA_NAME_PREFIXES)


# --- the two RAISE-on-drift audits both pass ----------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- must-refuse on the Java soundness-corpus fixture (the reassigned-param trap) --

def test_refuses_on_java_reassigned_param_corpus_shape():
    # The standing soundness corpus carries a Java reassigned-parameter trap shape: a
    # declared parameter reassigned by a plain `=` in its own method body (so `final`
    # would be a COMPILE ERROR). java-final-parameter MUST refuse it — the per-method
    # assignment scan catches the reassignment. Non-tautological: WITHOUT the
    # reassignment scan the parameter would wrongly be sealed `final`.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"java-final-parameter"})
    cells = corpus.get("java-final-parameter", {})
    assert cells, "java-final-parameter should be swept in the heavy corpus path"
    assert cells.get("java_reassigned_param") == "refused"
    # Unlike java-finalize-field (whose whole-FILE field scan finds no eligible field
    # on any OTHER corpus shape), java-final-parameter's per-method PARAMETER scan
    # legitimately LANDS a behaviour-identical `final` on the two Java doc-landable
    # fixtures (`java_undocumented_params` / `java_undocumented_throws`), which each
    # declare a plain, never-reassigned parameter alongside their undocumented
    # method — a real, sound seal, not a violation. Every OTHER shape (the
    # Python/JS shapes lack a Java project marker; the other Java shapes declare no
    # eligible parameter) must stay a clean refusal.
    _LANDABLE_ELSEWHERE = frozenset({"java_undocumented_params", "java_undocumented_throws"})
    for shape, verdict in cells.items():
        if shape in _LANDABLE_ELSEWHERE:
            assert verdict == "behavior-identical", f"{shape}: {verdict}"
        else:
            assert verdict == "refused", f"{shape}: {verdict}"
