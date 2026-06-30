"""java-document-param develop objective — a Java doc-surface landing that mirrors the
Python ``document-param`` (an ``Args:`` section) and the JS ``js-document-param-types``
(a JSDoc ``@param {T} name``), and is the param-contract sibling of java-document-throws.

For an own non-test ``.java`` method that DECLARES at least one parameter but carries NO
Javadoc, java-document-param lands a FRESH Javadoc block with one bare ``@param <name>``
line per DECLARED parameter (a byte-splice of a leading ``/** ... */`` comment just before
the method). The documented names are the method's DECLARED parameters
(``MethodTree.getParameters()`` -> ``VariableTree.getName()``) — exact and verbatim, in
source order, with NO type (the standard bare ``@param name`` Javadoc form). A Javadoc is
a COMMENT, so the structural fact-set (declared types + fields + method signatures) is
unchanged BY CONSTRUCTION, verified by an in-driver re-parse — so NO Maven/Gradle/JUnit/
compile run is ever needed (Tier A).

Scope (kept narrow for soundness): ONLY a method with at least one DECLARED parameter AND
NO existing Javadoc is documented; an ALREADY-documented method is REFUSED (merging an
existing block is out of scope) and a ZERO-parameter method is REFUSED (a ``@param``-less
block is content-free), exactly as Python document-param documents only the undocumented.

DISJOINTNESS from java-document-throws (the denetçi proof): both objectives target a
no-Javadoc method and both insert a leading Javadoc, made safe by the ``getDocComment !=
null`` refusal — whichever LANDS first makes the method documented, so the other then
REFUSES it (no double block). java-document-param emits ``@param``-ONLY blocks (no
``@throws``), staying orthogonal. This module proves it both directions on a method that
carries BOTH a parameter and a ``throws`` clause.

Covers: the driver (``param-targets`` facts + the ``parse-verify`` re-parse oracle,
refusals); the target-detection (undocumented >=1-param methods, SKIPPING already-
documented / zero-param); the deterministic source-order indented splice + idempotence;
the plan (lands the Javadoc, captures the original, refuses non-Java / no marker / test
file / already-documented / zero-param); the END-TO-END landing (the documented file
re-parses with the IDENTICAL fact-set, surrounding source untouched) and that planning
never touches the real tree; determinism across PYTHONHASHSEED; plus objective
registration / facet+manifest+soundness 1:1 parity (the SEVEN registries the new objective
must appear in) AND the behaviour-identical landing on the standing
``java_undocumented_params`` corpus fixture. The heavy ``java`` tests skip cleanly when a
JDK is not on PATH; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    JavaParamTarget,
    param_targets,
    parse_facts,
    reparse_facts_identical,
)
from app.execution.objectives.java_document_param import (
    detect_param_targets,
    documentable_param_targets,
    dominant_eol,
    is_java_source,
    plan_java_document_param,
    render_param_javadoc,
    splice_param_javadoc,
)

_PHRASE = "the undocumented java method params to document"

# A class with a mix of methods: `add` declares >=1 parameter and is UNDOCUMENTED (-> a
# param target); `sub` declares parameters but ALREADY has a Javadoc (-> SKIP, merging is
# out of scope); `tick` declares NO parameter (-> SKIP, a @param-less block is
# content-free). The two params of `add` are emitted IN SOURCE ORDER.
_CALC_JAVA = (
    "package demo;\n"
    "\n"
    "public class Calc {\n"
    "    int add(int a, int b) {\n"
    "        return a + b;\n"
    "    }\n"
    "\n"
    "    /** Subtracts. */\n"
    "    int sub(int x, int y) {\n"
    "        return x - y;\n"
    "    }\n"
    "\n"
    "    int tick() {\n"
    "        return 1;\n"
    "    }\n"
    "}\n"
)

# A method that carries BOTH a parameter AND a `throws` clause and NO Javadoc — the
# DISJOINTNESS shape: java-document-param and java-document-throws both find it, but once
# one lands a Javadoc the other refuses it (the getDocComment != null gate).
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

# A CRLF (Windows-authored) source with a package+import HEADER before the >=1-param
# method — the shape that reproduces the offset mismatch: the driver counts each `\r`, so
# a normalized (LF) splice would land mid-signature. The fix reads raw bytes so the offset
# is valid and emits the block with CRLF.
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
    (param-targets / parse-verify) to run."""
    return shutil.which("java") is not None


_needs_jdk = pytest.mark.skipif(not _jdk_ok(), reason="no JDK (java) on PATH")


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

def test_render_param_javadoc_is_fact_only_summary_and_param_lines():
    block = render_param_javadoc("add", ("a", "b"), "    ")
    # opening /** carries NO indent (the source indent already precedes it); the
    # continuation lines + trailing method re-indent carry the method's indentation.
    assert block.startswith("/**\n")
    assert "    * add.\n" in block
    assert "    * @param a\n" in block
    assert "    * @param b\n" in block
    assert block.endswith("    */\n    ")
    # the @param lines are IN SOURCE ORDER (a before b).
    assert block.index("@param a") < block.index("@param b")


def test_render_param_javadoc_has_no_invented_prose_and_no_types():
    # The ONLY contract lines are the declared param NAMES — no type, nothing invented.
    block = render_param_javadoc("f", ("x",), "")
    lines = [ln for ln in block.splitlines() if ln.strip()]
    # /**, * f., * (separator), * @param x, */
    assert lines == ["/**", " * f.", " *", " * @param x", " */"]
    # bare @param name, NEVER a typed `@param {T} name` / `@param x the ...`.
    assert "{" not in block and "}" not in block


# --- the splice (always runs — pure byte ops, no java) ------------------------

def test_splice_param_javadoc_inserts_indented_block_at_offset():
    src = "    int f(int a) { return a; }\n"
    # offset 4 sits at `int` (just past the 4-space indent the source already carries).
    out = splice_param_javadoc(src, [JavaParamTarget("f", ("a",), 4)])
    assert out is not None
    assert "    /**\n     * f.\n     *\n     * @param a\n     */\n    int f(int a)" in out


def test_splice_param_javadoc_bottom_up_keeps_earlier_offsets_valid():
    # Two methods at ascending offsets: inserting bottom-up (descending offset) keeps the
    # earlier offset valid, so both blocks land at the right place.
    src = "int a(int p) { return p; }\nint b(int q) { return q; }\n"
    off_b = src.index("int b(")
    targets = [JavaParamTarget("a", ("p",), 0), JavaParamTarget("b", ("q",), off_b)]
    out = splice_param_javadoc(src, targets)
    assert out is not None
    assert out.count("@param") == 2
    assert out.startswith("/**\n * a.\n")
    assert "@param q\n */\nint b(" in out


def test_splice_param_javadoc_refuses_out_of_range_offset():
    assert splice_param_javadoc("int f(int a) {}", [JavaParamTarget("f", ("a",), 999)]) is None


def test_splice_param_javadoc_noop_returns_none():
    assert splice_param_javadoc("int f(int a) {}", []) is None


def test_splice_param_javadoc_skips_target_with_no_params():
    # A (driver-impossible) target with an empty param list renders no contract, so it is
    # skipped rather than emitting a bare block -> a pure no-op -> None.
    assert splice_param_javadoc("int f() {}", [JavaParamTarget("f", (), 0)]) is None


# --- CRLF EOL handling (pure — the P0 regression guard, no java) --------------

def test_dominant_eol_detects_crlf_vs_lf():
    assert dominant_eol("a\r\nb\r\n") == "\r\n"
    assert dominant_eol("a\nb\n") == "\n"
    assert dominant_eol("no newline at all") == "\n"  # default LF


def test_render_param_javadoc_uses_crlf_when_asked():
    block = render_param_javadoc("f", ("a",), "    ", "\r\n")
    # every line break in the block is CRLF (no bare LF), and it ends with EOL + indent.
    assert block == ("/**\r\n     * f.\r\n     *\r\n     * @param a\r\n"
                     "     */\r\n    ")
    assert "\n" not in block.replace("\r\n", "")  # no LF-only line break leaked


def test_splice_param_javadoc_on_crlf_source_lands_attached_with_crlf():
    # THE P0 REGRESSION: the offset counts each `\r` (as the driver does), so the block
    # must land ATTACHED before `int f` (NOT mid-signature) and use CRLF throughout.
    src = "class Foo {\r\n    int f(int a) {\r\n    }\r\n}\r\n"
    off = src.index("int f(")
    out = splice_param_javadoc(src, [JavaParamTarget("f", ("a",), off)])
    assert out is not None
    # the method signature is intact and the block is attached immediately before it.
    assert "    /**\r\n     * f.\r\n     *\r\n     * @param a\r\n     */\r\n    int f(int a)" in out
    assert "int f(int a)" in out  # signature NOT split by the comment
    assert "\n" not in out.replace("\r\n", "")  # the whole file stays pure CRLF


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    # A .py path: plan refuses it before touching anything — the no-op on Python.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_document_param(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing, so the
    # objective is a clean no-op on a non-Java (e.g. pure-Python) tree.
    _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    assert detect_param_targets(str(tmp_path)) == []


# --- the driver: param-targets / parse-verify (need java) ---------------------

@_needs_jdk
def test_driver_param_targets_finds_only_undocumented_methods_with_params(tmp_path: Path):
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = param_targets(root, "src/Calc.java")
    names = [t.name for t in targets]
    # ONLY the undocumented >=1-param method; `sub` already has a Javadoc, `tick` has no
    # parameter -> both SKIPPED.
    assert names == ["add"]
    # the declared parameter names are carried IN SOURCE ORDER (a before b), no types.
    assert targets[0].params == ("a", "b")
    # the insert offset sits at the method's start (`int add`).
    off = targets[0].insert_offset
    assert _CALC_JAVA[off:].startswith("int add(")


@_needs_jdk
def test_driver_param_targets_skips_already_documented_method(tmp_path: Path):
    # A single >=1-param method that ALREADY carries a Javadoc -> NOT a target (merging is
    # out of scope). The core refuse-already-documented proof.
    src = (
        "public class C {\n"
        "    /** Does the thing. */\n"
        "    void go(int n) {}\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_param_targets_skips_method_without_params(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void go() { return; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert param_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { void f( {")
    assert parse_facts(root, "src/Broken.java") is None  # parse error -> None
    assert param_targets(root, "src/Broken.java") == []  # conservative empty


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_documentable_param_targets_filters_to_undocumented_with_params(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    assert [t.name for t in documentable_param_targets(root, "src/Calc.java")] == ["add"]


@_needs_jdk
def test_reparse_facts_identical_true_for_param_javadoc_splice(tmp_path: Path):
    # The behaviour-identical oracle: the Javadoc splice re-parses AND carries the SAME
    # structural fact-set (a comment changes zero declared structure).
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    targets = param_targets(root, "src/Calc.java")
    documented = splice_param_javadoc(_CALC_JAVA, list(targets))
    assert documented is not None
    assert "     * @param a\n     * @param b\n" in documented
    # `sub` keeps its original Javadoc untouched; `tick` is untouched.
    assert "/** Subtracts. */" in documented
    assert reparse_facts_identical(root, "src/Calc.java", documented)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_splice(tmp_path: Path):
    # A corrupt splice fails to re-parse -> the driver exits 2 -> the oracle refuses.
    root = _project(tmp_path, "src/Calc.java", _CALC_JAVA)
    corrupt = _CALC_JAVA.replace("int add(int a, int b)", "int add(int a @@@)")
    assert not reparse_facts_identical(root, "src/Calc.java", corrupt)


# --- the plan: an undocumented >=1-param method gets a Javadoc -----------------

@_needs_jdk
def test_plan_lands_javadoc_on_eligible_file(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_document_param(str(root), "src/Calc.java")
    assert plan.ok
    assert plan.originals["src/Calc.java"] == _CALC_JAVA  # original captured
    assert plan.edits_by_file["src/Calc.java"] == 1  # only `add` documented
    out = plan.new_contents["src/Calc.java"]
    # the fresh Javadoc lands immediately before `int add`, indented to its column.
    assert (
        "    /**\n"
        "     * add.\n"
        "     *\n"
        "     * @param a\n"
        "     * @param b\n"
        "     */\n"
        "    int add(int a, int b) {"
    ) in out
    # the already-documented / no-param methods are UNTOUCHED.
    assert "/** Subtracts. */\n    int sub(" in out
    assert "    int tick() {" in out


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

    plan = plan_java_document_param(str(root), "src/Foo.java")
    assert plan.ok
    out = plan.new_contents["src/Foo.java"]
    # the block lands attached, immediately before the (intact) method signature, in CRLF.
    assert (
        "    /**\r\n"
        "     * add.\r\n"
        "     *\r\n"
        "     * @param a\r\n"
        "     * @param b\r\n"
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
    assert not plan_java_document_param(str(root), "src/Foo.java").new_contents


@_needs_jdk
def test_plan_refuses_when_no_eligible_method(tmp_path: Path):
    # A class whose only >=1-param method is already documented -> nothing to document,
    # file byte-unchanged (refuse).
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    /** done. */\n"
        "    void go(int n) {}\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_document_param(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_zero_param_method(tmp_path: Path):
    # A class whose only method declares NO parameter -> a @param-less block is
    # content-free, so nothing is documented (refuse), file byte-unchanged.
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    int tick() { return 1; }\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_document_param(str(root), "src/C.java")
    assert not plan.new_contents
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/CalcTest.java", _CALC_JAVA)
    assert not plan_java_document_param(str(root), "src/CalcTest.java").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_gradle(tmp_path)
    plan = plan_java_document_param(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


@_needs_jdk
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    _project(root, "src/Documented.java",
             "public class Documented {\n"
             "    /** already. */\n"
             "    void go(int n) {}\n"
             "}\n")  # refused (its only >=1-param method is already documented)
    assert detect_param_targets(str(root)) == ["src/Calc.java"]


# --- DISJOINTNESS from java-document-throws (the denetçi proof) ----------------

@_needs_jdk
def test_disjoint_after_param_lands_throws_refuses(tmp_path: Path):
    # A method with BOTH a parameter AND a `throws` clause and NO Javadoc. Both objectives
    # find it. After java-document-param lands its @param-only block, the method now
    # carries a Javadoc, so java-document-throws REFUSES it (getDocComment != null) — no
    # double block, the two contracts stay orthogonal.
    from app.execution.objectives.java_document_throws import plan_java_document_throws

    root = _with_gradle(tmp_path)
    _project(root, "src/Both.java", _BOTH_JAVA)
    # both see the pristine method
    assert [t.name for t in param_targets(root, "src/Both.java")] == ["load"]

    plan = plan_java_document_param(str(root), "src/Both.java")
    documented = plan.new_contents["src/Both.java"]
    # the landed block is @param-ONLY (no @throws line) — orthogonal contracts.
    assert "@param path" in documented
    assert "@throws" not in documented

    # land it, then java-document-throws must refuse the now-documented method.
    (root / "src" / "Both.java").write_text(documented, encoding="utf-8")
    assert not plan_java_document_throws(str(root), "src/Both.java").new_contents
    # and a second java-document-param run is a byte-identical no-op.
    assert not plan_java_document_param(str(root), "src/Both.java").new_contents


@_needs_jdk
def test_disjoint_after_throws_lands_param_refuses(tmp_path: Path):
    # The reverse direction: after java-document-throws lands its @throws block, the
    # method carries a Javadoc, so java-document-param REFUSES it (getDocComment != null).
    from app.execution.objectives.java_document_throws import plan_java_document_throws

    root = _with_gradle(tmp_path)
    _project(root, "src/Both.java", _BOTH_JAVA)

    documented = plan_java_document_throws(str(root), "src/Both.java").new_contents["src/Both.java"]
    assert "@throws IOException" in documented
    (root / "src" / "Both.java").write_text(documented, encoding="utf-8")
    # java-document-param now refuses the documented method (no double block).
    assert not plan_java_document_param(str(root), "src/Both.java").new_contents


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    plan = plan_java_document_param(str(root), "src/Calc.java")
    documented = plan.new_contents["src/Calc.java"]
    # A SECOND run over the documented file is a byte-identical no-op (every >=1-param
    # method now carries a Javadoc, so the driver omits them all).
    _project(root, "src/Calc2.java", documented)
    assert not plan_java_document_param(str(root), "src/Calc2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    a = plan_java_document_param(str(root), "src/Calc.java").new_contents
    b = plan_java_document_param(str(root), "src/Calc.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    # Emission is SOURCE-ORDER stable, never hash-ordered: the bytes must be identical
    # across two PYTHONHASHSEED values (the determinism moat).
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_document_param import plan_java_document_param\n"
        "plan = plan_java_document_param(%r, 'src/Calc.java')\n"
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
    assert "* @param a" in first


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

    plan = plan_java_document_param(str(root), "src/Calc.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    assert "* @param a" in landed
    assert "* @param b" in landed
    # the structural fact-set is UNCHANGED — a Javadoc comment is a runtime no-op
    assert parse_facts(root, "src/Calc.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the real
    # source stays byte-identical — the change is landed only by the writer.
    root = _with_gradle(tmp_path)
    _project(root, "src/Calc.java", _CALC_JAVA)
    before = (root / "src" / "Calc.java").read_text(encoding="utf-8")
    plan = plan_java_document_param(str(root), "src/Calc.java")
    assert plan.new_contents  # a Javadoc WAS synthesised
    assert (root / "src" / "Calc.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-document-param" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-document-param"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # comment-only insert; no red-baseline veto


def test_objective_total_is_eighty_nine():
    from app.engine.objective_compiler import available_objectives

    # 89 after java-document-param (the Java mirror of document-param). (The concurrent
    # js-strengthen-tests wave also bumps to 89 in isolation; the integrator reconciles
    # the combined total to 90 at batch-integration.)
    assert len(set(available_objectives())) == 90


# --- PARITY ROW 1: move_value tier (the doc-surface 0.66 tier) ----------------

def test_parity_move_value_is_doc_surface_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_document_param") == 0.66
    assert objective_value("java-document-param") == 0.66
    assert objective_value("java-document-param") != DEFAULT_VALUE  # not the fallback


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-document-param" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_forty_four():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 45  # java-document-param (44th CONCRETE)


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
    assert "java-document-param" in sc
    assert SOUNDNESS_STRATEGY["java-document-param"]  # non-empty strategy string
    assert "java-document-param" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-document-param"
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
    # the Python sibling (document-param) stays directly before it (it was appended
    # after "the parameter types to document").
    assert ladder[ladder.index(_PHRASE) - 1] == "the parameter types to document"


# --- PARITY ROW 6: intent vocabulary ------------------------------------------

def test_parity_vocabulary_lists_java_document_param():
    from app.engine.objective_compiler import resolve_objective
    from app.intent.vocabulary import CONCEPT_VOCAB

    # java-document-param is wired into the "java" objective tuple (so the Java lane
    # carries it) ...
    java_row = dict(CONCEPT_VOCAB)["java"]
    assert "java-document-param" in java_row
    # ... and a Java-context "param" request routes there (the verify regex now covers
    # `param`/`parameters`, so the java context companion fires).
    assert resolve_objective("java parameters") == "java-document-param"
    assert resolve_objective("java param") == "java-document-param"


# --- PARITY ROW 7: owner-report Java language attribution ---------------------

def test_parity_owner_report_attributes_java_language():
    from app.reporting.owner_report import _JAVA_NAME_PREFIXES, _languages_for

    # A java- slug contributes "Java" (NOT silently counted as Python), via the prefix.
    assert _JAVA_NAME_PREFIXES == ("java-",)
    assert _languages_for(["java-document-param"]) == ["Java"]
    # The three-language order is stable (Python, Java, JS/TS).
    assert _languages_for(
        ["implement-stub", "java-document-param", "js-wire-exports"]
    ) == ["Python", "Java", "JavaScript/TypeScript"]


# --- the two RAISE-on-drift audits both pass ----------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- behaviour-identical landing on the java_undocumented_params corpus shape --

@_needs_jdk
def test_behavior_identical_on_java_undocumented_params_corpus_shape():
    # The standing soundness corpus carries a Java undocumented-params LANDABLE shape: a
    # method declaring >=1 parameter with no Javadoc. java-document-param SHOULD document
    # it (NOT a must-refuse trap), and the insert is behaviour-identical (a comment-only
    # edit re-parses fact-identical). This is the standing proof that the Javadoc landing
    # is sound on the sweep. (The heavy sweep is process-memoized in soundness_audit, so
    # the first corpus test pays for it and every later one reuses the result.)
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("java-document-param", {})
    assert cells, "java-document-param should be swept in the heavy corpus path"
    assert cells.get("java_undocumented_params") == "behavior-identical"
    # and it NEVER lands a VIOLATION on any corpus shape (the must-refuse traps —
    # java_false_final / java_blank_final / provenance_trap — have no undocumented method
    # with a parameter to splice, or are already documented, so it cleanly refuses them).
    for shape, verdict in cells.items():
        assert not verdict.startswith("VIOLATION"), f"{shape}: {verdict}"
    # the java must-refuse traps (no undocumented method-with-param) are cleanly refused.
    assert cells.get("java_false_final") == "refused"


def test_java_undocumented_params_is_not_a_must_refuse_shape():
    # The new shape is a LANDABLE, not a TRAP — it must NOT be in _SHAPE_MUST_REFUSE
    # (which would demand a refusal where a behaviour-identical landing is correct).
    from app.engine.soundness_audit import _SHAPE_MUST_REFUSE

    assert "java_undocumented_params" not in _SHAPE_MUST_REFUSE
