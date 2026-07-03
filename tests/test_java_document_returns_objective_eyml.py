"""java-document-returns develop objective — a Java doc-surface landing that mirrors the
Python ``document-returns`` (a ``:returns:``/``Returns:`` section from a DECLARED ``-> T``
annotation) and the JS ``js-document-returns-inferred`` (a JSDoc ``@returns {T}``), and is
the return-contract sibling of java-document-param / java-document-throws, completing the
Java Javadoc triad (@param + @throws + @return).

For an own non-test ``.java`` method that DECLARES a NON-void, NON-constructor return type
but carries NO Javadoc, java-document-returns lands a FRESH Javadoc block with one
``@return <type>`` line carrying the DECLARED return type read VERBATIM off the return-type
tree's SOURCE SPAN (the byte slice of the source — NOT ``Tree.toString()``, so the author's
generics/whitespace survive exactly; unlike the JS lane it is DECLARED, never inferred). A
Javadoc is a COMMENT, so the structural fact-set (declared types + fields + method
signatures) is unchanged BY CONSTRUCTION, verified by an in-driver re-parse — so NO
Maven/Gradle/JUnit/compile run is ever needed (Tier A).

Scope (kept narrow for soundness): ONLY a method with a DECLARED non-void return type AND
NO existing Javadoc is documented; an ALREADY-documented method is REFUSED (merging an
existing block is out of scope), a ``void``-returning method is REFUSED (a ``@return void``
is content-free AND wrong) and a CONSTRUCTOR is REFUSED (no return type), exactly as Python
document-returns refuses a ``None``/``NoReturn`` head / a generator / an already-documented
function.

DISJOINTNESS from java-document-param AND java-document-throws (the denetçi proof): all
three target a no-Javadoc method and all three insert a leading Javadoc, made safe by the
``getDocComment != null`` refusal — whichever LANDS first makes the method documented, so
the others then REFUSE it (no double block). java-document-returns emits ``@return``-ONLY
blocks (no ``@param``/``@throws``), staying orthogonal. This module proves it on a method
that carries a parameter, a ``throws`` clause AND a non-void return: running all three
planners on the one file lands a single Javadoc block with exactly one ``@return``.

NON-TAUTOLOGICAL void proof: the renderer is "dumb" — handed a (driver-impossible)
``void`` return-type target it WOULD emit a content-free ``@return void`` line; the ONLY
thing preventing that is the driver's ``void`` guard, which a dedicated test proves never
emits a void target. So removing the guard would land ``@return void`` — the test catches
it both ways.

Covers: the driver (``return-targets`` facts — VERBATIM source-span type text incl.
generics, the ``parse-verify`` re-parse oracle, the void/constructor/already-documented
refusals); the target-detection; the deterministic source-order indented splice +
idempotence; the plan (lands the Javadoc, captures the original, refuses non-Java / no
marker / test file / void / constructor / already-documented); the END-TO-END landing (the
documented file re-parses with the IDENTICAL fact-set, surrounding source untouched) and
that planning never touches the real tree; determinism across PYTHONHASHSEED; plus
objective registration / facet+manifest+soundness 1:1 parity (the SEVEN registries the new
objective must appear in) AND the behaviour-identical landing + must-refuse void trap on the
standing soundness corpus. The heavy ``java`` tests skip cleanly when a JDK is not on PATH;
every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    JavaReturnTarget,
    parse_facts,
    reparse_facts_identical,
    return_targets,
)
from app.execution.objectives.java_document_returns import (
    detect_return_targets,
    documentable_return_targets,
    dominant_eol,
    is_java_source,
    plan_java_document_returns,
    render_return_javadoc,
    splice_return_javadoc,
)

_PHRASE = "the undocumented java method return type to document"

# A class with a mix of methods: `add` DECLARES a non-void return (`int`) and is
# UNDOCUMENTED (-> a return target); `names` DECLARES a generic non-void return
# (`List<String>`, with a DOUBLE space to prove the SOURCE-SPAN read is byte-faithful, NOT
# Tree.toString() which would normalize it) and is UNDOCUMENTED (-> a return target);
# `doIt` returns `void` (-> SKIP, a @return void is content-free); the constructor `Calc()`
# has no return type (-> SKIP); `already` is non-void but ALREADY has a Javadoc (-> SKIP,
# merging is out of scope). Targets are emitted IN SOURCE ORDER.
_CALC_JAVA = (
    "package demo;\n"
    "\n"
    "import java.util.List;\n"
    "\n"
    "public class Calc {\n"
    "    int add(int a, int b) {\n"
    "        return a + b;\n"
    "    }\n"
    "\n"
    "    List<String>  names() {\n"
    "        return null;\n"
    "    }\n"
    "\n"
    "    void doIt() {\n"
    "        return;\n"
    "    }\n"
    "\n"
    "    public Calc() {\n"
    "    }\n"
    "\n"
    "    /** Already. */\n"
    "    String already() {\n"
    "        return \"x\";\n"
    "    }\n"
    "}\n"
)

# A method that carries a parameter, a `throws` clause AND a non-void return type and NO
# Javadoc — the DISJOINTNESS shape: java-document-returns, java-document-param and
# java-document-throws all find it, but once ONE lands a Javadoc the others refuse it (the
# getDocComment != null gate).
_BOTH_JAVA = (
    "package demo;\n"
    "\n"
    "import java.io.IOException;\n"
    "\n"
    "public class Both {\n"
    "    int load(String path) throws IOException {\n"
    "        throw new IOException(path);\n"
    "    }\n"
    "}\n"
)

# A CRLF (Windows-authored) source with a package+import HEADER before the non-void method
# — the shape that reproduces the offset mismatch: the driver counts each `\r`, so a
# normalized (LF) splice would land mid-signature. The fix reads raw bytes so the offset is
# valid and emits the block with CRLF.
_CRLF_HEADER_JAVA = (
    "package com.x;\r\n"
    "\r\n"
    "class Foo {\r\n"
    "    int add(int a, int b) {\r\n"
    "        return a + b;\r\n"
    "    }\r\n"
    "}\r\n"
)


# --- environment guards (the heavy java path is opt-in by availability) -------

def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (return-targets / parse-verify) to run."""
    return shutil.which("java") is not None


_needs_jdk = pytest.mark.skipif(not _jdk_ok(), reason="no JDK (java) on PATH")


def _javadoc_ok() -> bool:
    """True when ``javadoc`` is on PATH — the buyer's doc-build gate. The doclint proof
    is opt-in by availability (offline-friendly: skips cleanly when absent)."""
    return shutil.which("javadoc") is not None


_needs_javadoc = pytest.mark.skipif(
    not _javadoc_ok(), reason="no javadoc on PATH")


def _doclint_clean(files: list[Path]) -> tuple[bool, str]:
    """Run ``javadoc -Xdoclint:all -private`` over ``files`` and return
    ``(exit == 0, combined output)`` — the buyer's doc-build oracle. A doclint ERROR
    (an ``unknown tag`` from a leaked ``<...>`` / ``<init>``) makes ``javadoc`` exit
    non-zero; Apex's fact-only bare tags only ever raise WARNINGS (no description), so a
    doclint-clean output exits 0."""
    import tempfile

    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(
            ["javadoc", "-Xdoclint:all", "-private", "-d", out,
             *[str(f) for f in files]],
            capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _project_bytes(tmp_path: Path, rel: str, src: str) -> Path:
    """Write ``src`` as RAW bytes (no ``write_text`` newline translation), so a CRLF
    source lands on disk byte-for-byte — the state a Windows-authored file is in."""
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_bytes(src.encode("utf-8"))
    return tmp_path


def _with_gradle(root: Path) -> Path:
    (root / "build.gradle").write_text("// single-java-project marker\n", encoding="utf-8")
    return root


# --- the file gate (always runs — pure, no java) ------------------------------

def test_refuses_non_java_python_file():
    assert not is_java_source("app/mod.py")
    assert not is_java_source("setup.py")


def test_accepts_java_source():
    assert is_java_source("src/main/java/Main.java")
    assert is_java_source("Calc.java")


def test_refuses_junit_test_and_fixture_write_targets():
    # A JUnit/Maven test file is never a WRITE target (Apex never edits the suite).
    assert not is_java_source("CalcTest.java")
    assert not is_java_source("CalcTests.java")
    assert not is_java_source("CalcTestCase.java")
    assert not is_java_source("CalcIT.java")
    assert not is_java_source("src/test/java/Calc.java")


# --- the Javadoc render (always runs — pure string ops, no java) --------------

def test_render_return_javadoc_is_fact_only_summary_and_return_line():
    block = render_return_javadoc("add", "int", "    ")
    # opening /** carries NO indent (the source indent already precedes it); the
    # continuation lines + trailing method re-indent carry the method's indentation.
    assert block.startswith("/**\n")
    assert "    * add.\n" in block
    assert "    * @return int\n" in block
    assert block.endswith("    */\n    ")


def test_render_return_javadoc_has_no_invented_prose():
    # The ONLY contract line is the declared return TYPE — nothing invented.
    block = render_return_javadoc("f", "boolean", "")
    lines = [ln for ln in block.splitlines() if ln.strip()]
    # /**, * f., * (separator), * @return boolean, */
    assert lines == ["/**", " * f.", " *", " * @return boolean", " */"]


def test_render_return_javadoc_keeps_generics_verbatim():
    # The declared type text is rendered VERBATIM (generics + the author's whitespace),
    # never normalized — the byte-faithful source-span discipline. It sits INSIDE the
    # {@code ...} doclint wrap (the type carries `<`/`>`), so the double space still
    # survives byte-for-byte.
    block = render_return_javadoc("names", "Map<String,  Integer>", "  ")
    assert "  * @return {@code Map<String,  Integer>}\n" in block


# --- P1-a doclint fix: a generic/array return is {@code}-wrapped (pure, no java) ----

def test_render_return_javadoc_wraps_generic_type_in_code_span_P1A():
    # P1-a (field-found): a generic return type carries `<`/`>`, which `javadoc`/doclint
    # reads as an HTML tag (`* @return List<Point>` -> `unknown tag: Point`, exit 1). The
    # type is wrapped in {@code ...} so `<Point>` renders LITERALLY and doclint stays green.
    block = render_return_javadoc("pointsAbove", "List<Point>", "    ")
    assert "    * @return {@code List<Point>}\n" in block
    # NON-TAUTOLOGICAL: the RAW `<Point>` never appears OUTSIDE the {@code} wrap — i.e.
    # reverting the wrap (emitting `@return List<Point>`) would reintroduce the exact
    # doclint-breaking token this test forbids.
    assert "@return List<Point>" not in block  # never the bare, doclint-breaking form


def test_render_return_javadoc_wraps_map_generic_and_array_P1A():
    # A comma-generic (`Map<String,Integer>`) and an array (`int[]` carries no `<>` but is
    # fine bare) — the wrap fires on ANY `<`/`>`/`&` (generics, wildcards, intersections).
    block = render_return_javadoc("counts", "Map<String,Integer>", "  ")
    assert "  * @return {@code Map<String,Integer>}\n" in block
    # a wildcard bound uses `&`/`<`/`>` too -> wrapped.
    wild = render_return_javadoc("items", "List<? extends Number>", "")
    assert " * @return {@code List<? extends Number>}\n" in wild


def test_render_return_javadoc_keeps_simple_type_bare_P1A():
    # Minimal churn: a simple type with NO doclint-significant char stays BARE (no {@code}),
    # so `@return int` / `@return String` / `@return boolean[]` are unchanged (existing
    # simple-type expectations do not shift). `boolean[]` has `[`/`]`, not `<`/`>`/`&`.
    assert "    * @return int\n" in render_return_javadoc("f", "int", "    ")
    assert " * @return String\n" in render_return_javadoc("g", "String", "")
    assert " * @return boolean[]\n" in render_return_javadoc("h", "boolean[]", "")
    # none of these carry a `{@code}` wrap.
    for t in ("int", "String", "boolean[]"):
        assert "{@code" not in render_return_javadoc("f", t, "")


# --- the splice (always runs — pure byte ops, no java) ------------------------

def test_splice_return_javadoc_inserts_indented_block_at_offset():
    src = "    int f() { return 1; }\n"
    # offset 4 sits at `int` (just past the 4-space indent the source already carries).
    out = splice_return_javadoc(src, [JavaReturnTarget("f", "int", 4)])
    assert out is not None
    assert "    /**\n     * f.\n     *\n     * @return int\n     */\n    int f()" in out


def test_splice_return_javadoc_bottom_up_keeps_earlier_offsets_valid():
    # Two methods at ascending offsets: inserting bottom-up (descending offset) keeps the
    # earlier offset valid, so both blocks land at the right place.
    src = "int a() { return 1; }\nlong b() { return 2; }\n"
    off_b = src.index("long b(")
    targets = [JavaReturnTarget("a", "int", 0), JavaReturnTarget("b", "long", off_b)]
    out = splice_return_javadoc(src, targets)
    assert out is not None
    assert out.count("@return") == 2
    assert out.startswith("/**\n * a.\n")
    assert "@return long\n */\nlong b(" in out


def test_splice_return_javadoc_refuses_out_of_range_offset():
    assert splice_return_javadoc("int f() {}", [JavaReturnTarget("f", "int", 999)]) is None


def test_splice_return_javadoc_noop_returns_none():
    assert splice_return_javadoc("int f() {}", []) is None


def test_splice_return_javadoc_skips_target_with_empty_type():
    # A (driver-impossible) target with an empty return-type renders no contract, so it is
    # skipped rather than emitting a bare block -> a pure no-op -> None.
    assert splice_return_javadoc("int f() {}", [JavaReturnTarget("f", "", 0)]) is None


def test_render_void_would_emit_content_free_line_NON_TAUTOLOGICAL():
    # NON-TAUTOLOGICAL void guard proof (renderer side): the renderer is "dumb" — handed a
    # `void` return-type it WOULD emit a content-free `@return void` line. The ONLY thing
    # that prevents this is the DRIVER's void guard (proven below in
    # test_driver_return_targets_skips_void_and_constructor). So if the guard were removed
    # and a void target reached the renderer, `@return void` would land — this asserts the
    # exact content-free output the guard exists to prevent.
    block = render_return_javadoc("doIt", "void", "    ")
    assert "    * @return void\n" in block  # the WRONG line the driver must never produce
    out = splice_return_javadoc("    void doIt() {}\n",
                                [JavaReturnTarget("doIt", "void", 4)])
    assert out is not None and "@return void" in out


# --- CRLF EOL handling (pure — the P0 regression guard, no java) --------------

def test_dominant_eol_detects_crlf_vs_lf():
    assert dominant_eol("a\r\nb\r\n") == "\r\n"
    assert dominant_eol("a\nb\n") == "\n"
    assert dominant_eol("no newline at all") == "\n"  # default LF


def test_render_return_javadoc_uses_crlf_when_asked():
    block = render_return_javadoc("f", "int", "    ", "\r\n")
    # every line break in the block is CRLF (no bare LF), and it ends with EOL + indent.
    assert block == ("/**\r\n     * f.\r\n     *\r\n     * @return int\r\n"
                     "     */\r\n    ")
    assert "\n" not in block.replace("\r\n", "")  # no LF-only line break leaked


def test_splice_return_javadoc_on_crlf_source_lands_attached_with_crlf():
    # THE P0 REGRESSION: the offset counts each `\r` (as the driver does), so the block
    # must land ATTACHED before `int f` (NOT mid-signature) and use CRLF throughout.
    src = "class Foo {\r\n    int f() {\r\n    }\r\n}\r\n"
    off = src.index("int f(")
    out = splice_return_javadoc(src, [JavaReturnTarget("f", "int", off)])
    assert out is not None
    # the method signature is intact and the block is attached immediately before it.
    assert "    /**\r\n     * f.\r\n     *\r\n     * @return int\r\n     */\r\n    int f()" in out
    assert "int f()" in out  # signature NOT split by the comment
    assert "\n" not in out.replace("\r\n", "")  # the whole file stays pure CRLF


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    # A .py path: plan refuses it before touching anything — the no-op on Python.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_document_returns(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing, so the
    # objective is a clean no-op on a non-Java (e.g. pure-Python) tree.
    _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    assert detect_return_targets(str(tmp_path)) == []


# --- the driver: return-targets / parse-verify (need java) --------------------

@_needs_jdk
def test_driver_return_targets_finds_only_undocumented_non_void_methods(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = return_targets(root, "src/Calc.java")
    names = [t.name for t in targets]
    # ONLY the undocumented non-void methods; `doIt` is void, `Calc()` is a constructor,
    # `already` already has a Javadoc -> all SKIPPED. Source order: add before names.
    assert names == ["add", "names"]
    # the declared return-type text is carried VERBATIM off the SOURCE SPAN.
    assert targets[0].return_type == "int"
    # `List<String>  names()` has a DOUBLE space in the source — the span read preserves it
    # byte-for-byte; Tree.toString() would normalize to a single space. PROOF it is the span.
    assert targets[1].return_type == "List<String>"
    assert "  " not in targets[1].return_type  # the double space is AFTER the type, so the
    #                                            slice is exactly the type tree's span.
    # the insert offset sits at the method's start (`int add`).
    off = targets[0].insert_offset
    assert _CALC_JAVA[off:].startswith("int add(")


@_needs_jdk
def test_driver_return_targets_preserves_verbatim_generic_whitespace(tmp_path: Path):
    # The decisive SOURCE-SPAN (not toString) proof: a generic return type with an INTERNAL
    # double space is read byte-for-byte; Tree.toString() would collapse it to one space.
    src = (
        "import java.util.Map;\n"
        "public class G {\n"
        "    Map<String,  Integer> weird() { return null; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/G.java", src)
    targets = return_targets(root, "src/G.java")
    assert [t.name for t in targets] == ["weird"]
    assert targets[0].return_type == "Map<String,  Integer>"  # VERBATIM, not normalized


@_needs_jdk
def test_driver_return_targets_skips_void_and_constructor(tmp_path: Path):
    # NON-TAUTOLOGICAL void guard proof (driver side): a class with ONLY a void method and a
    # constructor yields NO target -> the driver NEVER emits a void/constructor target, so
    # the content-free `@return void` line the renderer would otherwise produce can never
    # land. (Pairs with test_render_void_would_emit_content_free_line_NON_TAUTOLOGICAL.)
    src = (
        "public class C {\n"
        "    public C() {}\n"
        "    void go() { return; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert return_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_return_targets_skips_already_documented_method(tmp_path: Path):
    # A single non-void method that ALREADY carries a Javadoc -> NOT a target (merging is
    # out of scope). The core refuse-already-documented proof.
    src = (
        "public class C {\n"
        "    /** Does the thing. */\n"
        "    int go() { return 1; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert return_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { int f( {")
    assert parse_facts(root, "src/Broken.java") is None  # parse error -> None
    assert return_targets(root, "src/Broken.java") == []  # conservative empty


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_documentable_return_targets_filters_to_undocumented_non_void(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    assert [t.name for t in documentable_return_targets(root, "src/Calc.java")] == [
        "add", "names"]


@_needs_jdk
def test_reparse_facts_identical_true_for_return_javadoc_splice(tmp_path: Path):
    # The behaviour-identical oracle: the Javadoc splice re-parses AND carries the SAME
    # structural fact-set (a comment changes zero declared structure).
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = return_targets(root, "src/Calc.java")
    documented = splice_return_javadoc(_CALC_JAVA, list(targets))
    assert documented is not None
    assert "     * @return int\n" in documented
    # P1-a: the generic `List<String>` return is {@code}-wrapped (doclint-clean), while the
    # {@code} sits inside the comment so the fact-set re-parse below is unchanged.
    assert "     * @return {@code List<String>}\n" in documented
    # `already` keeps its original Javadoc untouched; `doIt`/`Calc()` are untouched.
    assert "/** Already. */" in documented
    assert "@return void" not in documented  # the void method was NEVER documented
    assert reparse_facts_identical(root, "src/Calc.java", documented)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_splice(tmp_path: Path):
    # A corrupt splice fails to re-parse -> the driver exits 2 -> the oracle refuses.
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    corrupt = _CALC_JAVA.replace("int add(int a, int b)", "int add(int a @@@)")
    assert not reparse_facts_identical(root, "src/Calc.java", corrupt)


# --- the plan: an undocumented non-void method gets a Javadoc -----------------

@_needs_jdk
def test_plan_lands_javadoc_on_eligible_file(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_document_returns(str(root), "src/Calc.java")
    assert plan.ok
    assert plan.originals["src/Calc.java"] == _CALC_JAVA  # original captured
    assert plan.edits_by_file["src/Calc.java"] == 2  # add + names documented
    out = plan.new_contents["src/Calc.java"]
    # the fresh Javadoc lands immediately before `int add`, indented to its column.
    assert (
        "    /**\n"
        "     * add.\n"
        "     *\n"
        "     * @return int\n"
        "     */\n"
        "    int add(int a, int b) {"
    ) in out
    # and before `List<String>  names`, with the type read VERBATIM inside the {@code}
    # doclint wrap (P1-a: the generic carries `<`/`>`, so it is {@code}-wrapped).
    assert (
        "    /**\n"
        "     * names.\n"
        "     *\n"
        "     * @return {@code List<String>}\n"
        "     */\n"
        "    List<String>  names() {"
    ) in out
    # the void / constructor / already-documented methods are UNTOUCHED.
    assert "@return void" not in out
    assert "    void doIt() {" in out
    assert "    public Calc() {" in out
    assert "/** Already. */\n    String already(" in out
    # P1-a: the generic `List<String>` return is {@code}-wrapped, not the bare
    # doclint-breaking form — while the simple `int` stays bare (minimal churn).
    assert "* @return {@code List<String>}\n" in out
    assert "* @return int\n" in out


# --- P1-a doclint buyer-proof: a generic-return method (need java) ------------

@_needs_jdk
def test_plan_wraps_generic_return_in_code_span_P1A(tmp_path: Path):
    # P1-a end-to-end: a method that DECLARES a generic return (`List<Point>` /
    # `Map<String, Integer>`) is documented with a {@code}-wrapped @return, and the splice
    # still re-parses fact-identical (the {@code} lives inside the leading comment, so ZERO
    # declared structure changes).
    src = (
        "package demo;\n"
        "\n"
        "import java.util.List;\n"
        "import java.util.Map;\n"
        "\n"
        "public class Geo {\n"
        "    List<Point> pointsAbove(int y) {\n"
        "        return null;\n"
        "    }\n"
        "\n"
        "    Map<String, Integer> counts() {\n"
        "        return null;\n"
        "    }\n"
        "}\n"
        "class Point {}\n"
    )
    root = _with_gradle(tmp_path)
    _project(root, "src/Geo.java", src)
    plan = plan_java_document_returns(str(root), "src/Geo.java")
    assert plan.ok
    out = plan.new_contents["src/Geo.java"]
    # both generic returns are {@code}-wrapped (doclint-clean), NEVER the bare form.
    assert "* @return {@code List<Point>}\n" in out
    assert "* @return {@code Map<String, Integer>}\n" in out
    assert "@return List<Point>" not in out  # the bare, doclint-breaking form is gone
    # a comment-only change: the documented file re-parses with the IDENTICAL fact-set.
    assert reparse_facts_identical(root, "src/Geo.java", out)


@_needs_javadoc
def test_generic_return_javadoc_is_doclint_clean_RED_to_GREEN_P1A(tmp_path: Path):
    # THE BUYER PROOF (P1-a): the RAW bare `@return List<Point>` breaks `javadoc`
    # (`unknown tag: Point`, exit 1); the Apex-documented file ({@code}-wrapped) is
    # doclint-CLEAN (exit 0). Proves the fix RED->GREEN on the real doc-build tool.
    src = (
        "package demo;\n"
        "\n"
        "import java.util.List;\n"
        "\n"
        "public class Geo {\n"
        "    List<Point> pointsAbove(int y) {\n"
        "        return null;\n"
        "    }\n"
        "}\n"
        "class Point {}\n"
    )
    root = _with_gradle(tmp_path)
    _project(root, "src/Geo.java", src)

    # RED: the OLD (bare) form breaks doclint — build the exact block Apex used to emit.
    bare = src.replace(
        "    List<Point> pointsAbove(int y) {",
        "    /**\n     * pointsAbove.\n     *\n     * @return List<Point>\n     */\n"
        "    List<Point> pointsAbove(int y) {")
    (root / "src" / "Bare.java").write_text(
        bare.replace("class Geo", "class Bare").replace("public class Bare {",
                     "public class Bare {"), encoding="utf-8")
    red_ok, red_out = _doclint_clean([root / "src" / "Bare.java"])
    assert not red_ok, "the bare @return List<Point> should FAIL doclint"
    assert "unknown tag: Point" in red_out

    # GREEN: the Apex-documented ({@code}-wrapped) file is doclint-clean.
    out = plan_java_document_returns(str(root), "src/Geo.java").new_contents["src/Geo.java"]
    (root / "src" / "Geo.java").write_text(out, encoding="utf-8")
    green_ok, green_out = _doclint_clean([root / "src" / "Geo.java"])
    assert green_ok, f"the {{@code}}-wrapped @return should PASS doclint:\n{green_out}"
    assert "unknown tag" not in green_out


# --- CRLF (Windows-authored) end-to-end ---------------------------------------

@_needs_jdk
def test_plan_lands_on_crlf_header_file_attached_and_idempotent(tmp_path: Path):
    # A CRLF file with a package header. The driver's offset counts each `\r`; reading raw
    # bytes keeps the splice in that byte-space, so the Javadoc lands ATTACHED before
    # `int add` (NOT mid-signature), the file stays pure CRLF, the fact-set is identical,
    # and a 2nd run is a byte no-op.
    root = _with_gradle(tmp_path)
    _project_bytes(root, "src/Foo.java", _CRLF_HEADER_JAVA)
    before = parse_facts(root, "src/Foo.java")

    plan = plan_java_document_returns(str(root), "src/Foo.java")
    assert plan.ok
    out = plan.new_contents["src/Foo.java"]
    # the block lands attached, immediately before the (intact) method signature, in CRLF.
    assert (
        "    /**\r\n"
        "     * add.\r\n"
        "     *\r\n"
        "     * @return int\r\n"
        "     */\r\n"
        "    int add(int a, int b) {"
    ) in out
    assert "\n" not in out.replace("\r\n", "")  # the documented file stays pure CRLF
    # the captured original is the RAW (CRLF) bytes, so rollback restores byte-for-byte.
    assert plan.originals["src/Foo.java"] == _CRLF_HEADER_JAVA

    # land it + prove the fact-set is unchanged (a comment is behaviour-identical).
    (root / "src" / "Foo.java").write_bytes(out.encode("utf-8"))
    assert parse_facts(root, "src/Foo.java") == before
    # a SECOND run over the documented CRLF file is a byte-identical no-op (idempotent).
    assert not plan_java_document_returns(str(root), "src/Foo.java").new_contents


@_needs_jdk
def test_plan_refuses_when_no_eligible_method(tmp_path: Path):
    # A class whose only non-void method is already documented -> nothing to document,
    # file byte-unchanged (refuse).
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    /** done. */\n"
        "    int go() { return 1; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_document_returns(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_void_only_class(tmp_path: Path):
    # A class whose only method returns void + a constructor -> a @return void block is
    # content-free, so nothing is documented (refuse), file byte-unchanged.
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    public C() {}\n"
        "    void tick() { return; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_document_returns(str(root), "src/C.java")
    assert not plan.new_contents
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/CalcTest.java", _CALC_JAVA)
    assert not plan_java_document_returns(str(root), "src/CalcTest.java").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_gradle(tmp_path)
    plan = plan_java_document_returns(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


@_needs_jdk
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    _project(root, "src/Documented.java",
             "public class Documented {\n"
             "    /** already. */\n"
             "    int go() { return 1; }\n"
             "}\n")  # refused (its only non-void method is already documented)
    _project(root, "src/VoidOnly.java",
             "public class VoidOnly {\n"
             "    void go() { return; }\n"
             "}\n")  # refused (void-only)
    assert detect_return_targets(str(root)) == ["src/Calc.java"]


# --- DISJOINTNESS from java-document-param / java-document-throws (denetçi) ----

@_needs_jdk
def test_disjoint_after_returns_lands_param_and_throws_refuse(tmp_path: Path):
    # A method with a parameter, a `throws` clause AND a non-void return type, no Javadoc.
    # All three objectives find it. After java-document-returns lands its @return-only
    # block, the method now carries a Javadoc, so java-document-param AND java-document-throws
    # REFUSE it (getDocComment != null) — no double block, the contracts stay orthogonal.
    from app.execution.objectives.java_document_param import plan_java_document_param
    from app.execution.objectives.java_document_throws import plan_java_document_throws

    root = _with_gradle(tmp_path)
    _project(root, "src/Both.java", _BOTH_JAVA)
    # all three see the pristine method
    assert [t.name for t in return_targets(root, "src/Both.java")] == ["load"]

    plan = plan_java_document_returns(str(root), "src/Both.java")
    documented = plan.new_contents["src/Both.java"]
    # the landed block is @return-ONLY (no @param / @throws line) — orthogonal contracts.
    assert "@return int" in documented
    assert "@param" not in documented
    assert "@throws" not in documented

    # land it, then the other two must refuse the now-documented method.
    (root / "src" / "Both.java").write_text(documented, encoding="utf-8")
    assert not plan_java_document_param(str(root), "src/Both.java").new_contents
    assert not plan_java_document_throws(str(root), "src/Both.java").new_contents
    # and a second java-document-returns run is a byte-identical no-op.
    assert not plan_java_document_returns(str(root), "src/Both.java").new_contents


@_needs_jdk
def test_disjoint_all_three_planners_one_block_exactly_one_return(tmp_path: Path):
    # Run ALL THREE Javadoc planners over the SAME pristine file in sequence, landing each
    # in turn. Only the FIRST lands (java-document-returns here); the file ends with EXACTLY
    # ONE Javadoc block and EXACTLY ONE `@return` line — proving no double block, ever.
    from app.execution.objectives.java_document_param import plan_java_document_param
    from app.execution.objectives.java_document_throws import plan_java_document_throws

    root = _with_gradle(tmp_path)
    _project(root, "src/Both.java", _BOTH_JAVA)
    rel = "src/Both.java"

    for planner in (plan_java_document_returns, plan_java_document_throws,
                    plan_java_document_param):
        plan = planner(str(root), rel)
        if plan.new_contents:
            (root / rel).write_text(plan.new_contents[rel], encoding="utf-8")

    final = (root / rel).read_text(encoding="utf-8")
    assert final.count("/**") == 1  # exactly one Javadoc block
    assert final.count("@return") == 1  # exactly one @return line
    assert final.count("@param") == 0  # the others refused after the first landed
    assert final.count("@throws") == 0


@_needs_jdk
def test_disjoint_after_param_lands_returns_refuses(tmp_path: Path):
    # The reverse direction: after java-document-param lands its @param block, the method
    # carries a Javadoc, so java-document-returns REFUSES it (getDocComment != null).
    from app.execution.objectives.java_document_param import plan_java_document_param

    root = _with_gradle(tmp_path)
    _project(root, "src/Both.java", _BOTH_JAVA)

    documented = plan_java_document_param(str(root), "src/Both.java").new_contents["src/Both.java"]
    assert "@param path" in documented
    (root / "src" / "Both.java").write_text(documented, encoding="utf-8")
    # java-document-returns now refuses the documented method (no double block).
    assert not plan_java_document_returns(str(root), "src/Both.java").new_contents


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_document_returns(str(root), "src/Calc.java")
    documented = plan.new_contents["src/Calc.java"]
    # A SECOND run over the documented file is a byte-identical no-op (every non-void
    # method now carries a Javadoc, so the driver omits them all).
    _project(root, "src/Calc2.java", documented)
    assert not plan_java_document_returns(str(root), "src/Calc2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    a = plan_java_document_returns(str(root), "src/Calc.java").new_contents
    b = plan_java_document_returns(str(root), "src/Calc.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    # Emission is SOURCE-ORDER stable, never hash-ordered: the bytes must be identical
    # across two PYTHONHASHSEED values (the determinism moat).
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_document_returns import plan_java_document_returns\n"
        "plan = plan_java_document_returns(%r, 'src/Calc.java')\n"
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
    assert "* @return int" in first


# --- end-to-end: gated apply, real landing, fact-set identical ----------------

@_needs_jdk
def test_end_to_end_lands_javadoc_and_reparses_identical(tmp_path: Path):
    # A Javadoc comment is behaviour-identical by construction (proven by the in-plan
    # re-parse oracle), so it lands via the shared gated writer with no suite; the
    # documented file is on disk and the driver re-parses it with the SAME fact-set.
    from app.execution.cross_file_rename import apply_rename

    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before_facts = parse_facts(root, "src/Calc.java")

    plan = plan_java_document_returns(str(root), "src/Calc.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    assert "* @return int" in landed
    # P1-a: the generic return lands {@code}-wrapped (doclint-clean).
    assert "* @return {@code List<String>}" in landed
    # the structural fact-set is UNCHANGED — a Javadoc comment is a runtime no-op
    assert parse_facts(root, "src/Calc.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the real
    # source stays byte-identical — the change is landed only by the writer.
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    plan = plan_java_document_returns(str(root), "src/Calc.java")
    assert plan.new_contents  # a Javadoc WAS synthesised
    assert (root / "src" / "Calc.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-document-returns" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-document-returns"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # comment-only insert; no red-baseline veto


def test_objective_total_is_ninety_one():
    from app.engine.objective_compiler import available_objectives

    # 91 after java-document-returns (the Java mirror of document-returns), completing the
    # Java Javadoc triad (@param + @throws + @return).
    assert len(set(available_objectives())) == 97  # 96 -> 97: dedup-parameterized-total-return


# --- PARITY ROW 1: move_value tier (the doc-surface 0.66 tier) ----------------

def test_parity_move_value_is_doc_surface_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_document_returns") == 0.66
    assert objective_value("java-document-returns") == 0.66
    assert objective_value("java-document-returns") != DEFAULT_VALUE  # not the fallback


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-document-returns" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_forty_six():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 50  # finalize-module-constant (50th CONCRETE)


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
    assert "java-document-returns" in sc
    assert SOUNDNESS_STRATEGY["java-document-returns"]  # non-empty strategy string
    assert "java-document-returns" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-document-returns"
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


def test_parity_facet_phrase_lives_in_signatures_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    # the Java param sibling (java-document-param) stays directly before it (it was appended
    # after "the undocumented java method params to document", completing the Java triad).
    assert ladder[ladder.index(_PHRASE) - 1] == "the undocumented java method params to document"


# --- PARITY ROW 6: intent vocabulary ------------------------------------------

def test_parity_vocabulary_lists_java_document_returns():
    from app.intent.vocabulary import CONCEPT_VOCAB, _CONTEXT_KEY_PATTERNS, normalize

    # java-document-returns is wired into the "java" objective tuple (so the Java lane
    # carries it) ...
    java_row = dict(CONCEPT_VOCAB)["java"]
    assert "java-document-returns" in java_row
    # ... and the java CONTEXT pattern now covers `return`/`returns`, so a Java return
    # request reaches the java lane (the companion fires) rather than dropping to None.
    pat = _CONTEXT_KEY_PATTERNS["java"]
    assert pat.search(normalize("java return type"))
    assert pat.search(normalize("document java returns"))


# --- PARITY ROW 7: owner-report Java language attribution ---------------------

def test_parity_owner_report_attributes_java_language():
    from app.reporting.owner_report import _JAVA_NAME_PREFIXES, _languages_for

    # A java- slug contributes "Java" (NOT silently counted as Python), via the prefix.
    assert _JAVA_NAME_PREFIXES == ("java-",)
    assert _languages_for(["java-document-returns"]) == ["Java"]
    # The three-language order is stable (Python, Java, JS/TS).
    assert _languages_for(
        ["implement-stub", "java-document-returns", "js-wire-exports"]
    ) == ["Python", "Java", "JavaScript/TypeScript"]


def test_parity_owner_report_blurb_present():
    from app.reporting.owner_report import _ABILITY_PHRASES

    assert _ABILITY_PHRASES["java-document-returns"] == "documenting Java method return values"


# --- the two RAISE-on-drift audits both pass ----------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- behaviour-identical landing + must-refuse void trap on the corpus ---------

@_needs_jdk
def test_behavior_identical_on_java_undocumented_params_corpus_shape():
    # The standing soundness corpus carries a Java non-void undocumented method shape
    # (java_undocumented_params' `add` returns int). java-document-returns SHOULD document
    # it (NOT a must-refuse trap), and the insert is behaviour-identical (a comment-only
    # edit re-parses fact-identical). ``only`` slices the (process-memoized) sweep to THIS
    # objective's row, paying just this objective's JVM cost.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"java-document-returns"})
    cells = corpus.get("java-document-returns", {})
    assert cells, "java-document-returns should be swept in the heavy corpus path"
    assert cells.get("java_undocumented_params") == "behavior-identical"
    # and it NEVER lands a VIOLATION on any corpus shape.
    for shape, verdict in cells.items():
        assert not verdict.startswith("VIOLATION"), f"{shape}: {verdict}"
    # the void/constructor TRAP is cleanly REFUSED (no content-free @return void emitted).
    assert cells.get("java_void_return") == "refused"


def test_java_void_return_is_a_must_refuse_shape():
    # The new shape is a TRAP (a content-free return), so it MUST be in _SHAPE_MUST_REFUSE
    # mapped to exactly {java-document-returns} — the denetçi's standing proof it refuses
    # the void/constructor shape (removing the driver's void guard would land a content-free
    # @return void here, which the corpus sweep would then flag as a VIOLATION).
    from app.engine.soundness_audit import _SHAPE_MUST_REFUSE

    assert _SHAPE_MUST_REFUSE.get("java_void_return") == frozenset({"java-document-returns"})


def test_java_undocumented_params_is_not_a_must_refuse_shape():
    # The params LANDABLE is shared with java-document-param; it is NOT a trap for the
    # return objective either (a behaviour-identical landing is correct).
    from app.engine.soundness_audit import _SHAPE_MUST_REFUSE

    assert "java_undocumented_params" not in _SHAPE_MUST_REFUSE
