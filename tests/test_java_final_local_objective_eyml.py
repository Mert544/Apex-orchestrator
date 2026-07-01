"""java-final-local develop objective — the local-variable sibling of
java-final-parameter, one step deeper into the SAME never-reassigned proof and the
third member of the Java ``final``-modifier family (java-finalize-field,
java-final-parameter, java-final-local). It pays down Checkstyle
``FinalLocalVariable`` / SonarQube ``S3008``.

For an own non-test ``.java`` source, java-final-local lands the ONE missing
``final`` modifier on any LOCAL VARIABLE declared as a DIRECT STATEMENT of a
method/constructor body block that is never reassigned anywhere in its method
(``int x = 1;`` -> ``final int x = 1;``) — a byte-splice of ``final `` just before
the local's type token. Adding ``final`` to an already-never-reassigned local is a
RUNTIME no-op — the structural fact-set (declared types + fields + method
signatures) is unchanged BY CONSTRUCTION, verified by an in-driver re-parse — so
NO Maven/Gradle/JUnit/compile run is ever needed (Tier A).

Why it needs NO whole-unit refusal (exactly like java-final-parameter): a local is
a stack-local variable whose entire assignment surface is closed to its own
method's body — no reflection, no deserializer, no other file or method can ever
write it. So a PER-METHOD scan (not a whole-FILE scan) is both necessary and
sufficient.

SCOPE BOUNDARY (an EXPLICIT, TESTED decision — never accidental): the driver
considers ONLY a plain ``VariableTree`` that is a DIRECT statement of a
``BlockTree`` AND carries an initializer. A ``for``-loop init variable, an
enhanced-``for`` variable, and a try-with-resources resource are EXCLUDED by
omission (none is a block statement); a lambda / anonymous-inner-class captured
local is refused EXPLICITLY (a per-body capture scan); a no-initializer split
local is refused (its definite-assignment cannot be proven by the parse-only
oracle). Each refusal shape has a dedicated test below, so the boundary is proven,
not assumed.

Covers: the driver (``final-local-targets`` facts + the ``parse-verify`` re-parse
oracle, refusals per unsound shape); the target-detection (never-reassigned
direct-block-statement locals, SKIPPING reassigned / already-final / no-initializer
/ for / enhanced-for / try-resources / captured / no-body); the deterministic
source-order splice + idempotence; the plan (lands ``final``, captures the
original, refuses non-Java / no marker / test file); the END-TO-END landing (the
sealed file re-parses with the IDENTICAL fact-set, surrounding source untouched)
and that planning never touches the real tree; determinism across PYTHONHASHSEED;
plus objective registration / facet+manifest+soundness 1:1 parity (the SIX
registries the new objective must appear in) AND the
must-refuse-on-the-Java-corpus-fixture. The heavy ``java`` tests skip cleanly when
a JDK is not on PATH; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    final_local_targets,
    parse_facts,
    reparse_facts_identical,
)
from app.execution.objectives.java_final_local import (
    detect_final_local_targets,
    finalizable_local_targets,
    is_java_source,
    plan_java_final_local,
    splice_final_locals,
)

_PHRASE = "the never-reassigned java local variable to finalize"

# A class exercising every branch of the per-method direct-block-statement local
# scan: `add`'s `a`/`b` are never reassigned, initialised block statements (-> LAND
# both); `bump`'s `x` is reassigned via `=` (-> SKIP); `tick`'s `n` is reassigned via
# `+=` (-> SKIP); `dec`'s `n` is reassigned via `--` (-> SKIP); `already`'s `w` is
# already final (-> SKIP, idempotency); the constructor's `base` is a never-reassigned
# initialised local (-> LAND, rendered `Calc`); `loop`'s `i` is a for-INIT var (NOT a
# block statement -> EXCLUDED by omission) and its `sum` is reassigned (-> SKIP);
# `each`'s `e` is an enhanced-for var (EXCLUDED by omission) and its `acc` is
# reassigned (-> SKIP); `split`'s `y` has NO initializer (-> SKIP); `noBody` is
# abstract (no body -> SKIP wholesale).
_CALC_JAVA = (
    "package demo;\n"
    "\n"
    "import java.util.List;\n"
    "\n"
    "public abstract class Calc {\n"
    "    private int total;\n"
    "\n"
    "    int add() {\n"
    "        int a = 1;\n"
    "        int b = 2;\n"
    "        return a + b;\n"
    "    }\n"
    "\n"
    "    void bump() {\n"
    "        int x = 0;\n"
    "        x = x + 1;\n"
    "        total = x;\n"
    "    }\n"
    "\n"
    "    void tick() {\n"
    "        int n = 0;\n"
    "        n += 1;\n"
    "        total = n;\n"
    "    }\n"
    "\n"
    "    void dec() {\n"
    "        int n = 0;\n"
    "        n--;\n"
    "        total = n;\n"
    "    }\n"
    "\n"
    "    void already() {\n"
    "        final int w = 5;\n"
    "        total = w;\n"
    "    }\n"
    "\n"
    "    Calc(int seed) {\n"
    "        int base = seed;\n"
    "        this.total = base;\n"
    "    }\n"
    "\n"
    "    int loop() {\n"
    "        int sum = 0;\n"
    "        for (int i = 0; i < 3; i++) { sum = sum + i; }\n"
    "        return sum;\n"
    "    }\n"
    "\n"
    "    int each(List<Integer> xs) {\n"
    "        int acc = 0;\n"
    "        for (Integer e : xs) { acc = acc + e; }\n"
    "        return acc;\n"
    "    }\n"
    "\n"
    "    void split() {\n"
    "        int y;\n"
    "        y = 7;\n"
    "        total = y;\n"
    "    }\n"
    "\n"
    "    abstract void noBody();\n"
    "}\n"
)


# --- environment guards (the heavy java path is opt-in by availability) -------

def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (final-local-targets / parse-verify) to run."""
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

def test_splice_final_locals_inserts_at_offset_bottom_up():
    from app.execution.java.java_tool import JavaFinalLocalTarget

    src = "void f() { int a = 1; int b = 2; }"
    # offsets 11 (start of `int a`) and 22 (start of `int b`)
    targets = [
        JavaFinalLocalTarget("f", "a", 11),
        JavaFinalLocalTarget("f", "b", 22),
    ]
    out = splice_final_locals(src, targets)
    assert out == "void f() { final int a = 1; final int b = 2; }"


def test_splice_final_locals_refuses_out_of_range_offset():
    from app.execution.java.java_tool import JavaFinalLocalTarget

    assert splice_final_locals(
        "void f() { int a = 1; }", [JavaFinalLocalTarget("f", "a", 999)]) is None


def test_splice_final_locals_noop_returns_none():
    assert splice_final_locals("void f() { int a = 1; }", []) is None


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_final_local(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing.
    _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    assert detect_final_local_targets(str(tmp_path)) == []


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_gradle(tmp_path)
    plan = plan_java_final_local(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


# --- the driver: final-local-targets (needs java) ------------------------------

@_needs_jdk
def test_driver_finds_only_never_reassigned_direct_block_locals(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_local_targets(root, "src/Calc.java")
    pairs = [(t.method, t.name) for t in targets]
    # ONLY add's a/b and the constructor's base — every reassigned local
    # (bump/tick/dec/loop/each) is skipped, already's w is already final, split's y
    # has no initializer, loop's `i` (for-init) and each's `e` (enhanced-for) are
    # excluded because they are NOT direct block statements, and noBody is body-less.
    assert pairs == [("add", "a"), ("add", "b"), ("Calc", "base")]


@_needs_jdk
def test_driver_skips_local_reassigned_by_plain_equals(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void bump() { int x = 0; x = x + 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_local_reassigned_by_compound_assign(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void tick() { int n = 0; n += 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_local_reassigned_by_decrement(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void dec() { int n = 0; n--; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_no_initializer_split_local(tmp_path: Path):
    # Non-tautological: a bare `int y;` split from its assignment would need
    # definite-assignment analysis the parse-only oracle cannot do (and here it is
    # also reassigned), so it must be REFUSED — only an initializer-bearing local is
    # ever sealed. Without the getInitializer() guard a split local could be
    # mis-sealed.
    src = (
        "public class C {\n"
        "    void split() { int y; y = 7; System.out.println(y); }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_excludes_for_loop_init_variable(tmp_path: Path):
    # SCOPE BOUNDARY (by omission): a `for`-loop init variable is NOT a direct block
    # statement, so scanning BlockTree.getStatements() never sees `i`. Even though `i`
    # here is reassigned by the loop's own `i++`, the point is the SHAPE is out of
    # scope entirely — a `for (final int i = ...; ...)` is a different edit family.
    src = (
        "public class C {\n"
        "    int loop() { int s = 0; for (int i = 0; i < 3; i++) { s = s + i; } return s; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    # `i` (for-init) is out of scope; `s` is reassigned -> nothing landable.
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_excludes_enhanced_for_variable(tmp_path: Path):
    # SCOPE BOUNDARY (by omission): an enhanced-`for` variable is NOT a direct block
    # statement, so `e` is never a target even though it is never reassigned.
    src = (
        "import java.util.List;\n"
        "public class C {\n"
        "    int each(List<Integer> xs) { int t = 0; for (Integer e : xs) { t = t + e; } return t; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    # `e` (enhanced-for var) is out of scope; `t` is reassigned -> nothing landable.
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_excludes_try_with_resources_resource(tmp_path: Path):
    # SCOPE BOUNDARY (by omission): a try-with-resources resource is NOT a direct
    # block statement, so `res` is never a target even though it is never reassigned.
    src = (
        "import java.io.Closeable;\n"
        "public class C {\n"
        "    Closeable open() { return null; }\n"
        "    void use() { try (Closeable res = open()) { res.toString(); } catch (Exception e) {} }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_refuses_lambda_captured_local(tmp_path: Path):
    # EXPLICIT refusal (a captured local IS a block statement, so it is refused by the
    # per-body capture scan, NOT by omission). `captured` is referenced inside a lambda
    # body -> refused; `plain` is never captured/reassigned -> LANDED. Non-tautological:
    # without the capture scan `captured` would be sealed too.
    src = (
        "public class C {\n"
        "    Runnable make() { int captured = 7; int plain = 9;\n"
        "        return () -> System.out.println(captured); }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    pairs = [(t.method, t.name) for t in final_local_targets(root, "src/C.java")]
    assert pairs == [("make", "plain")]


@_needs_jdk
def test_driver_refuses_anonymous_class_captured_local(tmp_path: Path):
    # EXPLICIT refusal: `captured` is referenced inside an anonymous inner class body
    # -> refused; `plain` is never captured -> LANDED.
    src = (
        "public class C {\n"
        "    Runnable make() { int captured = 7; int plain = 9;\n"
        "        return new Runnable() { public void run() { System.out.println(captured); } }; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    pairs = [(t.method, t.name) for t in final_local_targets(root, "src/C.java")]
    assert pairs == [("make", "plain")]


@_needs_jdk
def test_driver_skips_abstract_method_with_no_body(tmp_path: Path):
    src = (
        "public abstract class C {\n"
        "    abstract void noBody();\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_skips_already_final_local(tmp_path: Path):
    # Non-tautological: an already-`final` local must be OMITTED (the idempotency
    # guard) — without the already-final check it would be listed again.
    src = (
        "public class C {\n"
        "    void already() { final int w = 5; System.out.println(w); }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert final_local_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_lands_offset_just_before_type_token(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_local_targets(root, "src/Calc.java")
    by_name = {(t.method, t.name): t.insert_offset for t in targets}
    off = by_name[("add", "a")]
    assert _CALC_JAVA[off:].startswith("int a")


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { void f() { int x = ; } }")
    assert parse_facts(root, "src/Broken.java") is None
    assert final_local_targets(root, "src/Broken.java") == []


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_finalizable_local_targets_filters_to_never_reassigned(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    pairs = [(t.method, t.name) for t in finalizable_local_targets(root, "src/Calc.java")]
    assert pairs == [("add", "a"), ("add", "b"), ("Calc", "base")]


@_needs_jdk
def test_reparse_facts_identical_true_for_final_local_splice(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = final_local_targets(root, "src/Calc.java")
    sealed = splice_final_locals(_CALC_JAVA, list(targets))
    assert sealed is not None
    assert "final int a = 1;" in sealed
    assert "final int b = 2;" in sealed
    assert "final int base = seed;" in sealed
    # the reassigned/already-final/no-init/out-of-scope locals are UNTOUCHED
    assert "int x = 0;" in sealed
    assert "final int w = 5;" in sealed  # already final, unchanged (not double-sealed)
    assert "int sum = 0;" in sealed
    assert "int y;" in sealed
    assert reparse_facts_identical(root, "src/Calc.java", sealed)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_local_splice(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    corrupt = _CALC_JAVA.replace("int a = 1;", "int @@@ a = 1;")
    assert not reparse_facts_identical(root, "src/Calc.java", corrupt)


# --- the plan: never-reassigned locals get `final` ----------------------------

@_needs_jdk
def test_plan_lands_final_on_eligible_file(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_final_local(str(root), "src/Calc.java")
    assert plan.ok
    assert plan.originals["src/Calc.java"] == _CALC_JAVA
    assert plan.edits_by_file["src/Calc.java"] == 3  # a, b, base
    sealed = plan.new_contents["src/Calc.java"]
    assert "final int a = 1;" in sealed
    assert "final int b = 2;" in sealed
    assert "final int base = seed;" in sealed
    # reassigned / already-final / out-of-scope locals stay untouched
    assert "int x = 0;" in sealed
    assert "int n = 0;" in sealed
    assert "final int w = 5;" in sealed
    assert "int sum = 0;" in sealed
    assert "int acc = 0;" in sealed
    assert "int y;" in sealed


@_needs_jdk
def test_plan_refuses_when_no_eligible_local(tmp_path: Path):
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    void bump() { int x = 0; x = x + 1; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_final_local(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/CalcTest.java", _CALC_JAVA)
    assert not plan_java_final_local(str(root), "src/CalcTest.java").new_contents


@_needs_jdk
def test_detects_and_locates_finalizable_files(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    _project(root, "src/AllReassigned.java",
             "public class AllReassigned {\n"
             "    void bump() { int x = 0; x = 1; }\n"
             "}\n")  # refused (its only local is reassigned)
    assert detect_final_local_targets(str(root)) == ["src/Calc.java"]


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_final_local(str(root), "src/Calc.java")
    sealed = plan.new_contents["src/Calc.java"]
    _project(root, "src/Calc2.java", sealed)
    assert not plan_java_final_local(str(root), "src/Calc2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    a = plan_java_final_local(str(root), "src/Calc.java").new_contents
    b = plan_java_final_local(str(root), "src/Calc.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_final_local import plan_java_final_local\n"
        "plan = plan_java_final_local(%r, 'src/Calc.java')\n"
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
    assert "final int a = 1;" in first


# --- end-to-end: gated apply, real landing, fact-set identical ----------------

@_needs_jdk
def test_end_to_end_lands_final_and_reparses_identical(tmp_path: Path):
    from app.execution.cross_file_rename import apply_rename

    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before_facts = parse_facts(root, "src/Calc.java")

    plan = plan_java_final_local(str(root), "src/Calc.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    assert "final int a = 1;" in landed
    # the structural fact-set is UNCHANGED — a final modifier is a runtime no-op
    assert parse_facts(root, "src/Calc.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    plan = plan_java_final_local(str(root), "src/Calc.java")
    assert plan.new_contents
    assert (root / "src" / "Calc.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-final-local" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-final-local"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # runtime-noop modifier add; no red-baseline veto


def test_objective_total_is_ninety_four():
    from app.engine.objective_compiler import available_objectives

    # 94 after java-final-local (java-final-parameter's local-variable sibling and the
    # third member of the Java final-modifier family).
    assert len(set(available_objectives())) == 94


# --- PARITY ROW 1: move_value tier (matches java-final-parameter's runtime-noop tier) --

def test_parity_move_value_matches_java_final_parameter_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_final_local") == 0.34
    assert move_value("java_final_local") == move_value("java_final_parameter")
    assert move_value("java_final_local") == move_value("java_finalize_field")
    assert objective_value("java-final-local") == 0.34
    assert objective_value("java-final-local") != DEFAULT_VALUE


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-final-local" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_forty_nine():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 49  # java-final-local (49th CONCRETE)


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
    assert "java-final-local" in sc
    assert SOUNDNESS_STRATEGY["java-final-local"]  # non-empty strategy string
    assert "java-final-local" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-final-local"
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
    # the java-final-parameter sibling stays directly before it (appended right after).
    assert ladder[ladder.index(_PHRASE) - 1] == (
        "the never-reassigned java method parameter to finalize")


# --- PARITY ROW 6: owner-report Java language coverage ------------------------

def test_parity_owner_report_lists_java_for_the_new_slug():
    from app.reporting.owner_report import _JAVA_NAME_PREFIXES, _languages_for

    # A java- slug contributes "Java" automatically via the shared prefix rule —
    # no per-objective owner_report entry is required for language coverage.
    assert _languages_for(["java-final-local"]) == ["Java"]
    assert all("java-final-local".startswith(p) for p in _JAVA_NAME_PREFIXES)


# --- the two RAISE-on-drift audits both pass ----------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- must-refuse on the Java soundness-corpus fixture (the reassigned-local trap) --

def test_refuses_on_java_reassigned_local_corpus_shape():
    # The standing soundness corpus carries a Java reassigned-local trap shape: a local
    # variable declared as a direct block statement WITH an initializer that LOOKS
    # never-reassigned from its declaration alone but is REASSIGNED by a plain `=`
    # later in its own method body (so `final` would be a COMPILE ERROR).
    # java-final-local MUST refuse it — the per-method assignment scan catches the
    # reassignment. Non-tautological: WITHOUT the reassignment scan the local would
    # wrongly be sealed `final`.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"java-final-local"})
    cells = corpus.get("java-final-local", {})
    assert cells, "java-final-local should be swept in the heavy corpus path"
    assert cells.get("java_reassigned_local") == "refused"
    # java-final-local legitimately LANDS a behaviour-identical `final` on the reflective
    # trap fixture: its local `Field f = ...;` is never reassigned/captured, so sealing
    # it is SOUND (the reflective-write concern is about the FIELD `secret`, which this
    # objective never touches — a local, unlike a field, has no reflective/deserializer
    # write surface). Every OTHER shape must stay a clean refusal (the Python/JS shapes
    # lack a Java project marker; the other Java shapes declare no eligible local, or
    # their only locals are reassigned / out-of-scope / captured).
    _LANDABLE_ELSEWHERE = frozenset({"java_reflective_field"})
    for shape, verdict in cells.items():
        if shape in _LANDABLE_ELSEWHERE:
            assert verdict == "behavior-identical", f"{shape}: {verdict}"
        else:
            assert verdict == "refused", f"{shape}: {verdict}"
