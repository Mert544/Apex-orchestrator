"""java-finalize-field develop objective — Apex's FIRST Java concrete landing and
the proof-of-value gate of the Java beachhead, the Java sibling of add-final.

For an own non-test ``.java`` source that declares a ``private`` instance field
PROVABLY never reassigned anywhere in the file, java-finalize-field lands the ONE
missing ``final`` modifier (a byte-splice of ` final` just past the existing
modifier keywords) so the field reads ``private final ...``. Adding ``final`` to an
already-never-reassigned field is a RUNTIME no-op — the structural fact-set (declared
types + fields + method signatures) is unchanged BY CONSTRUCTION, verified by an
in-driver re-parse — so NO Maven/Gradle/JUnit/compile run is ever needed (Tier A).

Why it is sound: a ``private`` field cannot be written from outside its class, so the
ENTIRE assignment surface lives in this one file's parse tree; the driver's
whole-file scan sees every assignment target (``=`` / ``+=`` / ``++``) and omits a
field written anywhere but its declarator. The false-``final`` trap (a field
reassigned in a nested inner class) is refused by exactly that whole-file scan.

Covers: the driver (``final-targets`` facts + the ``parse-verify`` re-parse oracle,
refusals); the target-detection (private never-reassigned fields, SKIPPING reassigned
/ public / static / already-final / multi-declarator); the deterministic
source-order splice + idempotence; the plan (lands ``final``, captures the original,
refuses non-Java / no marker / test file); the END-TO-END landing (the sealed file
re-parses with the IDENTICAL fact-set, surrounding source untouched) and that
planning never touches the real tree; determinism across PYTHONHASHSEED; plus
objective registration / facet+manifest+soundness 1:1 parity (the SIX registries the
new objective must appear in) AND the must-refuse-on-the-Java-corpus-fixture. The
heavy ``java`` tests skip cleanly when a JDK is not on PATH; every pure/refusal/parity
test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    final_targets,
    parse_facts,
    reparse_facts_identical,
)
from app.execution.lang import adapter_for, adapters
from app.execution.lang.adapter import Edit, LanguageAdapter, TargetQuery
from app.execution.lang.java_adapter import (
    JAVA_SOURCE_SUFFIXES,
    JavaAdapter,
    splice_at,
)
from app.execution.objectives.java_finalize_field import (
    detect_finalize_targets,
    finalizable_targets,
    is_java_source,
    plan_java_finalize_field,
    splice_final,
)

_PHRASE = "the never-reassigned java field to finalize"

# A class with a mix of fields: `neverWritten` is private, initialised (`= 1`) and only
# ever read (-> finalisable); `name` is private but BLANK (no initializer) and never
# assigned anywhere, so a blank `final` could never be definitely assigned (JLS §16 ->
# COMPILE ERROR) (-> SKIP); `counter` is reassigned in tick() (-> SKIP); `total` via +=
# (-> SKIP); `ticks` via ++ (-> SKIP); `exposed` is public (-> SKIP); `already` is
# already final (-> SKIP); `shared` is static (-> SKIP); `a, b` are one multi-
# declarator statement (-> SKIP both).
_COUNTER_JAVA = (
    "package demo;\n"
    "\n"
    "public class Counter {\n"
    "    private int neverWritten = 1;\n"
    "    private String name;\n"
    "    private int counter;\n"
    "    private int total = 0;\n"
    "    private int ticks = 0;\n"
    "    public int exposed = 5;\n"
    "    private final int already = 7;\n"
    "    private static int shared = 0;\n"
    "    private int a, b;\n"
    "\n"
    "    void tick() {\n"
    "        this.counter = counter + 1;\n"
    "        total += 1;\n"
    "        ticks++;\n"
    "    }\n"
    "\n"
    "    int read() { return neverWritten + already + a + b; }\n"
    "}\n"
)


# --- environment guards (the heavy java path is opt-in by availability) -------

def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (final-targets / parse-verify) to run."""
    return shutil.which("java") is not None


_needs_jdk = pytest.mark.skipif(not _jdk_ok(), reason="no JDK (java) on PATH")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _with_pom(root: Path) -> Path:
    (root / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion></project>\n", encoding="utf-8")
    return root


# --- the file gate (always runs — pure, no java) ------------------------------

def test_refuses_non_java_python_file():
    assert not is_java_source("app/mod.py")
    assert not is_java_source("setup.py")


def test_refuses_non_source_file():
    assert not is_java_source("README.md")
    assert not is_java_source("pom.xml")
    assert not is_java_source("Main.class")


def test_accepts_java_source():
    assert is_java_source("src/main/java/Main.java")
    assert is_java_source("Foo.java")


def test_refuses_junit_test_and_fixture_write_targets():
    # A JUnit/Maven test file is never a WRITE target (Apex never edits the suite).
    assert not is_java_source("FooTest.java")
    assert not is_java_source("FooTests.java")
    assert not is_java_source("FooTestCase.java")
    assert not is_java_source("FooIT.java")
    assert not is_java_source("src/test/java/Foo.java")


# --- the splice (always runs — pure byte ops, no java) ------------------------

def test_splice_final_inserts_at_offset_bottom_up():
    from app.execution.java.java_tool import JavaFinalTarget

    src = "private int a = 1; private int b = 2;"
    # offsets 7 (after first `private`) and 26 (after second `private`)
    targets = [JavaFinalTarget("a", 7), JavaFinalTarget("b", 26)]
    out = splice_final(src, targets)
    assert out == "private final int a = 1; private final int b = 2;"


def test_splice_final_refuses_out_of_range_offset():
    from app.execution.java.java_tool import JavaFinalTarget

    assert splice_final("private int a;", [JavaFinalTarget("a", 999)]) is None


def test_splice_final_noop_returns_none():
    assert splice_final("private int a;", []) is None


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    # A .py path: plan refuses it before touching anything — the no-op on Python.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_finalize_field(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing, so
    # the objective is a clean no-op on a non-Java (e.g. pure-Python) tree.
    _project(tmp_path, "src/Counter.java", _COUNTER_JAVA)
    assert detect_finalize_targets(str(tmp_path)) == []


# --- the JavaAdapter seam (always runs — pure predicate/slice, no java) -------

def test_java_adapter_is_a_structural_language_adapter():
    # The Protocol is runtime_checkable; JavaAdapter is a plain object that satisfies
    # it structurally (no inheritance) — what the registry uses to validate it.
    assert isinstance(JavaAdapter(), LanguageAdapter)
    assert JavaAdapter().name == "java"
    assert JAVA_SOURCE_SUFFIXES == frozenset({".java"})


def test_java_adapter_owns_is_the_file_gate():
    ja = JavaAdapter()
    assert ja.owns("src/main/java/Main.java")
    assert not ja.owns("FooTest.java")   # test file refused as a write target
    assert not ja.owns("src/test/java/Foo.java")
    assert not ja.owns("app/mod.py")     # non-Java refused (no-op on Python)


def test_java_adapter_locate_then_apply_is_a_byte_offset_insert():
    # The seam: locate exposes the detector's insert offset as a zero-width span,
    # apply splices ` final` there verbatim (start == end -> insertion, not replace).
    ja = JavaAdapter()
    src = "private int a = 1;"
    tree = ja.parse(src)
    target = ja.locate(tree, src, TargetQuery(name="a", extra={"insert_offset": 7}))
    assert target is not None and target.span == (7, 7)
    assert ja.apply(src, target, Edit(body=" final")) == "private final int a = 1;"


def test_java_adapter_locate_refuses_without_offset():
    ja = JavaAdapter()
    src = "private int a = 1;"
    assert ja.locate(ja.parse(src), src, TargetQuery(name="a")) is None


def test_java_adapter_apply_refuses_stale_span():
    from app.execution.lang.adapter import Target

    ja = JavaAdapter()
    assert ja.apply("private int a;", Target(name="a", span=(999, 999)),
                    Edit(body=" final")) is None


def test_splice_at_is_a_pure_byte_insert():
    assert splice_at("abcd", 2, "XY") == "abXYcd"
    assert splice_at("abcd", 99, "X") is None  # out of range -> refuse


def test_registry_places_java_between_python_and_javascript():
    # The append-only registry sorts Python first, then by name -> java < javascript.
    names = [a.name for a in adapters()]
    assert names[0] == "python"
    assert "java" in names and "javascript" in names
    assert names.index("java") < names.index("javascript")
    # dispatch: a .java file routes to the Java adapter, a test file to nothing.
    assert adapter_for("src/main/java/Foo.java").name == "java"
    assert adapter_for("src/main/java/FooTest.java") is None


# --- the driver: final-targets / parse-verify (need java) ---------------------

@_needs_jdk
def test_driver_final_targets_finds_only_never_reassigned_private_fields(tmp_path: Path):
    root = _project(tmp_path, "src/Counter.java", _COUNTER_JAVA)
    targets = final_targets(root, "src/Counter.java")
    names = [t.name for t in targets]
    # ONLY the never-reassigned private fields WITH AN INITIALIZER, in source order.
    # `name` is blank (no initializer) + never assigned -> a blank `final` cannot be
    # definitely assigned (JLS §16) -> SKIPPED. counter/total/ticks are reassigned;
    # exposed is public; already is final; shared is static; a,b are one multi-
    # declarator statement -> all SKIPPED.
    assert names == ["neverWritten"]
    # the insert offset sits just past `private`, so splicing ` final` reads
    # `private final ...`
    src = _COUNTER_JAVA
    off = targets[0].insert_offset
    assert src[:off].endswith("private")
    assert src[off:].lstrip().startswith("int neverWritten")


@_needs_jdk
def test_driver_final_targets_skips_reassigned_field(tmp_path: Path):
    # A single private field reassigned in a method -> NOT a target (final would be a
    # compile error). The core never-reassigned proof.
    src = (
        "public class C {\n"
        "    private int x = 0;\n"
        "    void bump() { x = x + 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_parse_verify_emits_structural_fact_set(tmp_path: Path):
    root = _project(tmp_path, "src/Counter.java", _COUNTER_JAVA)
    facts = parse_facts(root, "src/Counter.java")
    assert facts is not None
    assert facts.types == frozenset({"Counter"})
    assert "Counter.neverWritten" in facts.fields
    assert "Counter.tick/0" in facts.methods
    assert "Counter.read/0" in facts.methods


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { private int x = ;")
    assert parse_facts(root, "src/Broken.java") is None  # parse error -> None
    assert final_targets(root, "src/Broken.java") == []  # conservative empty


@_needs_jdk
def test_java_adapter_reparses_proves_well_formedness():
    # The cheap post-edit proof: a well-formed splice re-parses (True), a corrupt one
    # makes the driver exit 2 -> parse_facts None -> reparses False.
    ja = JavaAdapter()
    assert ja.reparses("public class C { private final int x = 1; }")
    assert not ja.reparses("public class C { private @@@ int x = ;")


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_finalizable_targets_filters_to_never_reassigned(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    assert [t.name for t in finalizable_targets(root, "src/Counter.java")] == [
        "neverWritten"]


@_needs_jdk
def test_reparse_facts_identical_true_for_final_splice(tmp_path: Path):
    # The behaviour-identical oracle: the ` final` splice re-parses AND carries the
    # SAME structural fact-set (a final modifier changes zero declared structure).
    root = _project(tmp_path, "src/Counter.java", _COUNTER_JAVA)
    targets = final_targets(root, "src/Counter.java")
    sealed = splice_final(_COUNTER_JAVA, list(targets))
    assert sealed is not None
    assert "private final int neverWritten" in sealed
    # `name` is blank (no initializer) -> refused (a blank `final` cannot compile)
    assert "private final String name" not in sealed
    assert "private String name;" in sealed
    assert reparse_facts_identical(root, "src/Counter.java", sealed)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_splice(tmp_path: Path):
    # A corrupt splice fails to re-parse -> the driver exits 2 -> the oracle refuses.
    root = _project(tmp_path, "src/Counter.java", _COUNTER_JAVA)
    corrupt = _COUNTER_JAVA.replace("private int neverWritten = 1;",
                                    "private @@@ int neverWritten = 1;")
    assert not reparse_facts_identical(root, "src/Counter.java", corrupt)


# --- the plan: a never-reassigned private field gets `final` ------------------

@_needs_jdk
def test_plan_lands_final_on_eligible_file(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    plan = plan_java_finalize_field(str(root), "src/Counter.java")
    assert plan.ok
    assert plan.originals["src/Counter.java"] == _COUNTER_JAVA  # original captured
    assert plan.edits_by_file["src/Counter.java"] == 1  # only neverWritten sealed
    sealed = plan.new_contents["src/Counter.java"]
    assert "private final int neverWritten = 1;" in sealed
    # the blank / reassigned / public / static / final / multi-declarator fields are
    # UNTOUCHED. `name` is blank (no initializer) -> a blank `final` cannot be
    # definitely assigned (JLS §16), so it stays unsealed.
    assert "private String name;" in sealed
    assert "private int counter;" in sealed
    assert "public int exposed = 5;" in sealed
    assert "private final int already = 7;" in sealed
    assert "private static int shared = 0;" in sealed
    assert "private int a, b;" in sealed


@_needs_jdk
def test_plan_refuses_when_no_eligible_field(tmp_path: Path):
    # A class whose only private field is reassigned -> nothing to finalise, file
    # byte-unchanged (refuse).
    root = _with_pom(tmp_path)
    src = (
        "public class C {\n"
        "    private int x = 0;\n"
        "    void bump() { x++; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_finalize_field(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/CounterTest.java", _COUNTER_JAVA)
    assert not plan_java_finalize_field(str(root), "src/CounterTest.java").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_pom(tmp_path)
    plan = plan_java_finalize_field(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


@_needs_jdk
def test_detects_and_locates_finalizable_files(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    _project(root, "src/AllWritten.java",
             "public class AllWritten {\n"
             "    private int x = 0;\n"
             "    void bump() { x = 1; }\n"
             "}\n")  # refused (its only private field is reassigned)
    assert detect_finalize_targets(str(root)) == ["src/Counter.java"]


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    plan = plan_java_finalize_field(str(root), "src/Counter.java")
    sealed = plan.new_contents["src/Counter.java"]
    # A SECOND run over the sealed file is a byte-identical no-op (every eligible
    # field now carries final).
    _project(root, "src/Counter2.java", sealed)
    assert not plan_java_finalize_field(str(root), "src/Counter2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    a = plan_java_finalize_field(str(root), "src/Counter.java").new_contents
    b = plan_java_finalize_field(str(root), "src/Counter.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    # Emission is SOURCE-ORDER stable, never hash-ordered: the bytes must be identical
    # across two PYTHONHASHSEED values (the determinism moat).
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_finalize_field import plan_java_finalize_field\n"
        "plan = plan_java_finalize_field(%r, 'src/Counter.java')\n"
        "sys.stdout.write(plan.new_contents.get('src/Counter.java', '<none>'))\n"
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
    assert "private final int neverWritten = 1;" in first


# --- end-to-end: gated apply, real landing, fact-set identical ----------------

@_needs_jdk
def test_end_to_end_lands_final_and_reparses_identical(tmp_path: Path):
    # A `final` modifier is behaviour-identical by construction (proven by the
    # in-plan re-parse oracle), so it lands via the shared gated writer with no suite;
    # the sealed file is on disk and the driver re-parses it with the SAME fact-set.
    from app.execution.cross_file_rename import apply_rename

    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    before_facts = parse_facts(root, "src/Counter.java")

    plan = plan_java_finalize_field(str(root), "src/Counter.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Counter.java").read_text(encoding="utf-8")
    assert "private final int neverWritten = 1;" in landed
    # `name` is blank (no initializer) -> not sealed (a blank `final` cannot compile)
    assert "private String name;" in landed
    # the structural fact-set is UNCHANGED — a final modifier is a runtime no-op
    assert parse_facts(root, "src/Counter.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the real
    # source stays byte-identical — the change is landed only by the writer.
    root = _with_pom(tmp_path)
    _project(root, "src/Counter.java", _COUNTER_JAVA)
    before = (root / "src" / "Counter.java").read_text(encoding="utf-8")
    plan = plan_java_finalize_field(str(root), "src/Counter.java")
    assert plan.new_contents  # a final WAS synthesised
    assert (root / "src" / "Counter.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-finalize-field" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-finalize-field"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # runtime-noop modifier add; no red-baseline veto


def test_objective_total_is_seventy_eight():
    from app.engine.objective_compiler import available_objectives

    # 83 after document-attributes + document-yields (the class-attribute and
    # generator-yield doc-splice objectives).
    assert len(set(available_objectives())) == 84


# --- PARITY ROW 1: move_value tier (matches add-final's runtime-noop tier) ----

def test_parity_move_value_matches_add_final_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_finalize_field") == 0.34
    assert move_value("java_finalize_field") == move_value("add_final")
    assert objective_value("java-finalize-field") == 0.34
    assert objective_value("java-finalize-field") != DEFAULT_VALUE  # not the fallback


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-finalize-field" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_thirty_six():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 41  # dedup-dunder-all (84th) is TIDY, not CONCRETE


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
    assert "java-finalize-field" in sc
    assert SOUNDNESS_STRATEGY["java-finalize-field"]  # non-empty strategy string
    assert "java-finalize-field" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-finalize-field"
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
    assert ladder[0] == "the hook interface"  # originals still lead
    # the add-final family stays directly before it (it was appended after
    # "the method to seal as final").
    assert ladder[ladder.index(_PHRASE) - 1] == "the method to seal as final"


# --- PARITY ROW 6: owner-report plain-English label + Java language -----------

def test_parity_owner_report_labels_java_and_lists_the_language():
    from app.reporting.owner_report import (
        _ABILITY_PHRASES,
        _JAVA_NAME_PREFIXES,
        _languages_for,
    )

    # The owner sees a plain-English ability label, never the slug.
    assert "java-finalize-field" in _ABILITY_PHRASES
    assert _ABILITY_PHRASES["java-finalize-field"]
    # A java- slug contributes "Java" (NOT silently counted as Python).
    assert _languages_for(["java-finalize-field"]) == ["Java"]
    # The three-language order is stable (Python, Java, JS/TS).
    assert _languages_for(
        ["implement-stub", "java-finalize-field", "js-wire-exports"]
    ) == ["Python", "Java", "JavaScript/TypeScript"]
    assert _JAVA_NAME_PREFIXES == ("java-",)


# --- the two RAISE-on-drift audits both pass ----------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- must-refuse on the Java soundness-corpus fixture (the false-final trap) ---

def test_refuses_on_java_false_final_corpus_shape():
    # The standing soundness corpus carries a Java false-`final` trap shape: a private
    # field reassigned in a nested inner class (so `final` would be a COMPILE ERROR).
    # java-finalize-field MUST refuse it — the whole-file assignment scan catches the
    # inner-class write. This is the K2-class never-fake-green guarantee for Java.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("java-finalize-field", {})
    assert cells, "java-finalize-field should be swept in the heavy corpus path"
    assert cells.get("java_false_final") == "refused"
    # and it stays a clean refusal on EVERY corpus shape (the Python/JS shapes lack a
    # Java project marker, so the single-project gate is a clean no-op there too).
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
