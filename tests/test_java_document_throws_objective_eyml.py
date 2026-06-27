"""java-document-throws develop objective — the SECOND Java concrete landing (after
java-finalize-field), the Java sibling of document-raises / document-raises-jsdoc.

For an own non-test ``.java`` method that DECLARES a ``throws`` clause but carries NO
Javadoc, java-document-throws lands a FRESH Javadoc block with one ``@throws <Type>``
line per DECLARED checked-exception type (a byte-splice of a leading ``/** ... */``
comment just before the method). The documented types are the method's DECLARED throws
clause (``MethodTree.getThrows()``) — exact and verbatim, NEVER inferred from
``throw new X()`` statements. A Javadoc is a COMMENT, so the structural fact-set
(declared types + fields + method signatures) is unchanged BY CONSTRUCTION, verified by
an in-driver re-parse — so NO Maven/Gradle/JUnit/compile run is ever needed (Tier A).

Scope (kept narrow for soundness): ONLY a method with a NON-EMPTY ``throws`` clause AND
NO existing Javadoc is documented; an ALREADY-documented method is REFUSED (merging an
existing block is out of scope), exactly as Python document-signature / document-raises
document only the undocumented.

Covers: the driver (``doc-targets`` facts + the ``parse-verify`` re-parse oracle,
refusals); the target-detection (undocumented throwing methods, SKIPPING already-
documented / no-throws-clause); the deterministic source-order indented splice +
idempotence; the plan (lands the Javadoc, captures the original, refuses non-Java / no
marker / test file / already-documented); the END-TO-END landing (the documented file
re-parses with the IDENTICAL fact-set, surrounding source untouched) and that planning
never touches the real tree; determinism across PYTHONHASHSEED; plus objective
registration / facet+manifest+soundness 1:1 parity (the SIX registries the new objective
must appear in) AND the behaviour-identical landing on the standing
``java_undocumented_throws`` corpus fixture. The heavy ``java`` tests skip cleanly when a
JDK is not on PATH; every pure/refusal/parity test always runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.java.java_tool import (
    JavaDocTarget,
    doc_targets,
    parse_facts,
    reparse_facts_identical,
)
from app.execution.objectives.java_document_throws import (
    detect_doc_targets,
    documentable_targets,
    dominant_eol,
    is_java_source,
    plan_java_document_throws,
    render_throws_javadoc,
    splice_javadoc,
)

_PHRASE = "the undocumented java throws clause to document"

# A class with a mix of methods: `load` declares a `throws` clause and is UNDOCUMENTED
# (-> a doc target); `cached` declares `throws` but ALREADY has a Javadoc (-> SKIP,
# merging is out of scope); `pure` declares NO `throws` clause (-> SKIP, nothing to
# document). The two throws types of `load` are emitted IN SOURCE ORDER.
_LOADER_JAVA = (
    "package demo;\n"
    "\n"
    "import java.io.IOException;\n"
    "import java.sql.SQLException;\n"
    "\n"
    "public class Loader {\n"
    "    int load(String p) throws IOException, SQLException {\n"
    "        throw new IOException(p);\n"
    "    }\n"
    "\n"
    "    /** Reads the cache. */\n"
    "    int cached() throws IOException {\n"
    "        return 0;\n"
    "    }\n"
    "\n"
    "    int pure() {\n"
    "        return 1;\n"
    "    }\n"
    "}\n"
)

# A CRLF (Windows-authored) source with a package+import HEADER before the throwing
# method — the shape that reproduces the offset mismatch: the driver counts each `\r`,
# so a normalized (LF) splice would land mid-signature (`void /**...*/ f()`). The fix
# reads raw bytes so the offset is valid and emits the block with CRLF.
_CRLF_HEADER_JAVA = (
    "package com.x;\r\n"
    "\r\n"
    "import java.io.IOException;\r\n"
    "\r\n"
    "class Foo {\r\n"
    "    int load(String p) throws IOException {\r\n"
    "        throw new IOException(p);\r\n"
    "    }\r\n"
    "}\r\n"
)

# The WORST case the audit hit: a CRLF source whose header is a MULTI-LINE license/
# copyright block comment (many `\r` before the method), maximising the offset drift.
_CRLF_LICENSE_JAVA = (
    "/*\r\n"
    " * Copyright 2026 Example Corp.\r\n"
    " * Licensed under the Apache License, Version 2.0.\r\n"
    " */\r\n"
    "package com.x;\r\n"
    "\r\n"
    "import java.io.IOException;\r\n"
    "\r\n"
    "class Svc {\r\n"
    "    int load(String p) throws IOException {\r\n"
    "        throw new IOException(p);\r\n"
    "    }\r\n"
    "}\r\n"
)


# --- environment guards (the heavy java path is opt-in by availability) -------

def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (doc-targets / parse-verify) to run."""
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
    assert is_java_source("Loader.java")


def test_refuses_junit_test_and_fixture_write_targets():
    # A JUnit/Maven test file is never a WRITE target (Apex never edits the suite).
    assert not is_java_source("LoaderTest.java")
    assert not is_java_source("LoaderTests.java")
    assert not is_java_source("LoaderTestCase.java")
    assert not is_java_source("LoaderIT.java")
    assert not is_java_source("src/test/java/Loader.java")


# --- the Javadoc render (always runs — pure string ops, no java) --------------

def test_render_throws_javadoc_is_fact_only_summary_and_throws_lines():
    block = render_throws_javadoc("load", ("IOException", "SQLException"), "    ")
    # opening /** carries NO indent (the source indent already precedes it); the
    # continuation lines + trailing method re-indent carry the method's indentation.
    assert block.startswith("/**\n")
    assert "    * load.\n" in block
    assert "    * @throws IOException\n" in block
    assert "    * @throws SQLException\n" in block
    assert block.endswith("    */\n    ")
    # the @throws lines are IN SOURCE ORDER (IOException before SQLException).
    assert block.index("@throws IOException") < block.index("@throws SQLException")


def test_render_throws_javadoc_has_no_invented_prose():
    # The ONLY contract lines are the declared types; nothing is invented.
    block = render_throws_javadoc("f", ("IOException",), "")
    lines = [ln for ln in block.splitlines() if ln.strip()]
    # /**, * f., * (separator), * @throws IOException, */
    assert lines == ["/**", " * f.", " *", " * @throws IOException", " */"]


# --- the splice (always runs — pure byte ops, no java) ------------------------

def test_splice_javadoc_inserts_indented_block_at_offset():
    src = "    void f() throws IOException {}\n"
    # offset 4 sits at `void` (just past the 4-space indent the source already carries).
    out = splice_javadoc(src, [JavaDocTarget("f", ("IOException",), 4)])
    assert out is not None
    assert "    /**\n     * f.\n     *\n     * @throws IOException\n     */\n    void f()" in out


def test_splice_javadoc_bottom_up_keeps_earlier_offsets_valid():
    # Two methods at ascending offsets: inserting bottom-up (descending offset) keeps
    # the earlier offset valid, so both blocks land at the right place.
    src = "void a() throws E {}\nvoid b() throws E {}\n"
    off_b = src.index("void b()")
    targets = [JavaDocTarget("a", ("E",), 0), JavaDocTarget("b", ("E",), off_b)]
    out = splice_javadoc(src, targets)
    assert out is not None
    assert out.count("@throws E") == 2
    assert out.startswith("/**\n * a.\n")
    assert "@throws E\n */\nvoid b()" in out


def test_splice_javadoc_refuses_out_of_range_offset():
    assert splice_javadoc("void f() {}", [JavaDocTarget("f", ("E",), 999)]) is None


def test_splice_javadoc_noop_returns_none():
    assert splice_javadoc("void f() {}", []) is None


def test_splice_javadoc_skips_target_with_no_throws_types():
    # A (driver-impossible) target with an empty throws list renders no contract, so it
    # is skipped rather than emitting a bare block -> a pure no-op -> None.
    assert splice_javadoc("void f() {}", [JavaDocTarget("f", (), 0)]) is None


# --- CRLF EOL handling (pure — the P0 regression guard, no java) --------------

def test_dominant_eol_detects_crlf_vs_lf():
    assert dominant_eol("a\r\nb\r\n") == "\r\n"
    assert dominant_eol("a\nb\n") == "\n"
    assert dominant_eol("no newline at all") == "\n"  # default LF


def test_render_throws_javadoc_uses_crlf_when_asked():
    block = render_throws_javadoc("f", ("IOException",), "    ", "\r\n")
    # every line break in the block is CRLF (no bare LF), and it ends with EOL + indent.
    assert block == ("/**\r\n     * f.\r\n     *\r\n     * @throws IOException\r\n"
                     "     */\r\n    ")
    assert "\n" not in block.replace("\r\n", "")  # no LF-only line break leaked


def test_splice_javadoc_on_crlf_source_lands_attached_with_crlf():
    # THE P0 REGRESSION: the offset counts each `\r` (as the driver does), so the block
    # must land ATTACHED before `void f` (NOT mid-signature) and use CRLF throughout.
    # On the pre-fix code (which mixed a CRLF-space offset with an LF block) this lands
    # `void /**...*/ f()` — mid-signature corruption.
    src = "class Foo {\r\n    void f() throws E {\r\n    }\r\n}\r\n"
    off = src.index("void f()")
    out = splice_javadoc(src, [JavaDocTarget("f", ("E",), off)])
    assert out is not None
    # the method signature is intact and the block is attached immediately before it.
    assert "    /**\r\n     * f.\r\n     *\r\n     * @throws E\r\n     */\r\n    void f() throws E" in out
    assert "void f() throws E" in out  # signature NOT split by the comment
    assert "\n" not in out.replace("\r\n", "")  # the whole file stays pure CRLF


def test_plan_refuses_non_java_file_outright(tmp_path: Path):
    # A .py path: plan refuses it before touching anything — the no-op on Python.
    _project(tmp_path, "app/mod.py", "def f():\n    return 1\n")
    plan = plan_java_document_throws(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers  # honest no-op, not an error


def test_detect_refuses_project_without_java_marker(tmp_path: Path):
    # The single-project gate: no pom.xml/build.gradle at root -> detect nothing, so the
    # objective is a clean no-op on a non-Java (e.g. pure-Python) tree.
    _project(tmp_path, "src/Loader.java", _LOADER_JAVA)
    assert detect_doc_targets(str(tmp_path)) == []


# --- the driver: doc-targets / parse-verify (need java) -----------------------

@_needs_jdk
def test_driver_doc_targets_finds_only_undocumented_throwing_methods(tmp_path: Path):
    root = _project(tmp_path, "src/Loader.java", _LOADER_JAVA)
    targets = doc_targets(root, "src/Loader.java")
    names = [t.name for t in targets]
    # ONLY the undocumented throwing method; `cached` already has a Javadoc, `pure` has
    # no throws clause -> both SKIPPED.
    assert names == ["load"]
    # the declared throws types are carried IN SOURCE ORDER.
    assert targets[0].throws_types == ("IOException", "SQLException")
    # the insert offset sits at the method's start (`int load`).
    off = targets[0].insert_offset
    assert _LOADER_JAVA[off:].startswith("int load(")


@_needs_jdk
def test_driver_doc_targets_skips_already_documented_method(tmp_path: Path):
    # A single throwing method that ALREADY carries a Javadoc -> NOT a target (merging is
    # out of scope). The core refuse-already-documented proof.
    src = (
        "public class C {\n"
        "    /** Does the thing. */\n"
        "    void go() throws java.io.IOException {}\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert doc_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_doc_targets_skips_method_without_throws_clause(tmp_path: Path):
    src = (
        "public class C {\n"
        "    void go() { return; }\n"
        "}\n"
    )
    root = _project(tmp_path, "src/C.java", src)
    assert doc_targets(root, "src/C.java") == []


@_needs_jdk
def test_driver_parse_verify_refuses_syntax_error(tmp_path: Path):
    root = _project(tmp_path, "src/Broken.java", "public class Broken { void f( {")
    assert parse_facts(root, "src/Broken.java") is None  # parse error -> None
    assert doc_targets(root, "src/Broken.java") == []  # conservative empty


# --- the splice + reparse oracle (need java) ----------------------------------

@_needs_jdk
def test_documentable_targets_filters_to_undocumented_throwing(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    assert [t.name for t in documentable_targets(root, "src/Loader.java")] == ["load"]


@_needs_jdk
def test_reparse_facts_identical_true_for_javadoc_splice(tmp_path: Path):
    # The behaviour-identical oracle: the Javadoc splice re-parses AND carries the SAME
    # structural fact-set (a comment changes zero declared structure).
    root = _project(tmp_path, "src/Loader.java", _LOADER_JAVA)
    targets = doc_targets(root, "src/Loader.java")
    documented = splice_javadoc(_LOADER_JAVA, list(targets))
    assert documented is not None
    assert "     * @throws IOException\n     * @throws SQLException\n" in documented
    # `cached` keeps its original Javadoc untouched; `pure` is untouched.
    assert "/** Reads the cache. */" in documented
    assert reparse_facts_identical(root, "src/Loader.java", documented)


@_needs_jdk
def test_reparse_facts_identical_false_for_corrupt_splice(tmp_path: Path):
    # A corrupt splice fails to re-parse -> the driver exits 2 -> the oracle refuses.
    root = _project(tmp_path, "src/Loader.java", _LOADER_JAVA)
    corrupt = _LOADER_JAVA.replace("int load(String p)", "int load(String p @@@)")
    assert not reparse_facts_identical(root, "src/Loader.java", corrupt)


# --- the plan: an undocumented throwing method gets a Javadoc ------------------

@_needs_jdk
def test_plan_lands_javadoc_on_eligible_file(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    plan = plan_java_document_throws(str(root), "src/Loader.java")
    assert plan.ok
    assert plan.originals["src/Loader.java"] == _LOADER_JAVA  # original captured
    assert plan.edits_by_file["src/Loader.java"] == 1  # only `load` documented
    out = plan.new_contents["src/Loader.java"]
    # the fresh Javadoc lands immediately before `int load`, indented to its column.
    assert (
        "    /**\n"
        "     * load.\n"
        "     *\n"
        "     * @throws IOException\n"
        "     * @throws SQLException\n"
        "     */\n"
        "    int load(String p) throws IOException, SQLException {"
    ) in out
    # the already-documented / no-throws methods are UNTOUCHED.
    assert "/** Reads the cache. */\n    int cached()" in out
    assert "    int pure() {" in out


# --- CRLF (Windows-authored) end-to-end: the P0 the audit found ---------------

@_needs_jdk
def test_plan_lands_on_crlf_header_file_attached_and_idempotent(tmp_path: Path):
    # THE P0: a CRLF file with a package+import header. The driver's offset counts each
    # `\r`; reading raw bytes keeps the splice in that byte-space, so the Javadoc lands
    # ATTACHED before `int load` (NOT mid-signature), the file stays pure CRLF, the
    # fact-set is identical, and a 2nd run is a byte no-op. On the pre-fix code (which
    # normalized CRLF -> LF before splicing) the block landed `int /**...*/ load(...)`.
    from app.execution.java.java_tool import parse_facts

    root = _with_gradle(tmp_path)
    _project_bytes(root, "src/Foo.java", _CRLF_HEADER_JAVA)
    before = parse_facts(root, "src/Foo.java")

    plan = plan_java_document_throws(str(root), "src/Foo.java")
    assert plan.ok
    out = plan.new_contents["src/Foo.java"]
    # the block lands attached, immediately before the (intact) method signature, in CRLF.
    assert (
        "    /**\r\n"
        "     * load.\r\n"
        "     *\r\n"
        "     * @throws IOException\r\n"
        "     */\r\n"
        "    int load(String p) throws IOException {"
    ) in out
    assert "\n" not in out.replace("\r\n", "")  # the documented file stays pure CRLF
    # the captured original is the RAW (CRLF) bytes, so rollback restores byte-for-byte.
    assert plan.originals["src/Foo.java"] == _CRLF_HEADER_JAVA

    # land it + prove the fact-set is unchanged (a comment is behaviour-identical).
    (root / "src" / "Foo.java").write_bytes(out.encode("utf-8"))
    assert parse_facts(root, "src/Foo.java") == before
    # a SECOND run over the documented CRLF file is a byte-identical no-op (idempotent).
    assert not plan_java_document_throws(str(root), "src/Foo.java").new_contents


@_needs_jdk
def test_plan_lands_on_crlf_multiline_license_header(tmp_path: Path):
    # The worst case the audit hit: a CRLF file whose header is a MULTI-LINE license
    # block comment (many `\r` before the method, maximising the drift). The block still
    # lands attached, the license header survives, and the fact-set is identical.
    from app.execution.java.java_tool import parse_facts

    root = _with_gradle(tmp_path)
    _project_bytes(root, "src/Svc.java", _CRLF_LICENSE_JAVA)
    before = parse_facts(root, "src/Svc.java")

    out = plan_java_document_throws(str(root), "src/Svc.java").new_contents["src/Svc.java"]
    # the multi-line license header is preserved verbatim at the top.
    assert out.startswith("/*\r\n * Copyright 2026 Example Corp.\r\n")
    # the Javadoc lands attached to the (intact) method, not inside its signature.
    assert "     */\r\n    int load(String p) throws IOException {" in out
    assert "\n" not in out.replace("\r\n", "")  # stays pure CRLF

    (root / "src" / "Svc.java").write_bytes(out.encode("utf-8"))
    assert parse_facts(root, "src/Svc.java") == before
    assert not plan_java_document_throws(str(root), "src/Svc.java").new_contents


@_needs_jdk
def test_plan_refuses_when_no_eligible_method(tmp_path: Path):
    # A class whose only throwing method is already documented -> nothing to document,
    # file byte-unchanged (refuse).
    root = _with_gradle(tmp_path)
    src = (
        "public class C {\n"
        "    /** done. */\n"
        "    void go() throws java.io.IOException {}\n"
        "}\n"
    )
    _project(root, "src/C.java", src)
    before = (root / "src" / "C.java").read_text(encoding="utf-8")
    plan = plan_java_document_throws(str(root), "src/C.java")
    assert not plan.new_contents
    assert not plan.blockers
    assert (root / "src" / "C.java").read_text(encoding="utf-8") == before


@_needs_jdk
def test_plan_refuses_test_file_input(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/LoaderTest.java", _LOADER_JAVA)
    assert not plan_java_document_throws(str(root), "src/LoaderTest.java").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    _with_gradle(tmp_path)
    plan = plan_java_document_throws(str(tmp_path), "src/Missing.java")
    assert not plan.new_contents
    assert not plan.blockers


@_needs_jdk
def test_detects_and_locates_documentable_files(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    _project(root, "src/Documented.java",
             "public class Documented {\n"
             "    /** already. */\n"
             "    void go() throws java.io.IOException {}\n"
             "}\n")  # refused (its only throwing method is already documented)
    assert detect_doc_targets(str(root)) == ["src/Loader.java"]


# --- idempotency / determinism (need java) ------------------------------------

@_needs_jdk
def test_idempotent_second_run_is_noop(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    plan = plan_java_document_throws(str(root), "src/Loader.java")
    documented = plan.new_contents["src/Loader.java"]
    # A SECOND run over the documented file is a byte-identical no-op (every throwing
    # method now carries a Javadoc, so the driver omits them all).
    _project(root, "src/Loader2.java", documented)
    assert not plan_java_document_throws(str(root), "src/Loader2.java").new_contents


@_needs_jdk
def test_deterministic_across_two_runs(tmp_path: Path):
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    a = plan_java_document_throws(str(root), "src/Loader.java").new_contents
    b = plan_java_document_throws(str(root), "src/Loader.java").new_contents
    assert a and a == b


@_needs_jdk
def test_deterministic_across_hashseed(tmp_path: Path):
    # Emission is SOURCE-ORDER stable, never hash-ordered: the bytes must be identical
    # across two PYTHONHASHSEED values (the determinism moat).
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    snippet = (
        "import sys\n"
        "from app.execution.objectives.java_document_throws import plan_java_document_throws\n"
        "plan = plan_java_document_throws(%r, 'src/Loader.java')\n"
        "sys.stdout.write(plan.new_contents.get('src/Loader.java', '<none>'))\n"
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
    assert "* @throws IOException" in first


# --- end-to-end: gated apply, real landing, fact-set identical ----------------

@_needs_jdk
def test_end_to_end_lands_javadoc_and_reparses_identical(tmp_path: Path):
    # A Javadoc comment is behaviour-identical by construction (proven by the in-plan
    # re-parse oracle), so it lands via the shared gated writer with no suite; the
    # documented file is on disk and the driver re-parses it with the SAME fact-set.
    from app.execution.cross_file_rename import apply_rename

    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    before_facts = parse_facts(root, "src/Loader.java")

    plan = plan_java_document_throws(str(root), "src/Loader.java")
    assert plan.ok

    result = apply_rename(str(root), plan, verify=False)
    assert result.get("applied") is True

    landed = (root / "src" / "Loader.java").read_text(encoding="utf-8")
    assert "* @throws IOException" in landed
    assert "* @throws SQLException" in landed
    # the structural fact-set is UNCHANGED — a Javadoc comment is a runtime no-op
    assert parse_facts(root, "src/Loader.java") == before_facts


@_needs_jdk
def test_planning_never_touches_the_real_tree(tmp_path: Path):
    # Building the plan splices in Python + verifies via a THROWAWAY copy, so the real
    # source stays byte-identical — the change is landed only by the writer.
    root = _with_gradle(tmp_path)
    _project(root, "src/Loader.java", _LOADER_JAVA)
    before = (root / "src" / "Loader.java").read_text(encoding="utf-8")
    plan = plan_java_document_throws(str(root), "src/Loader.java")
    assert plan.new_contents  # a Javadoc WAS synthesised
    assert (root / "src" / "Loader.java").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "java-document-throws" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["java-document-throws"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True  # detection spawns java (the driver parse)
    assert spec.scope_verify is False  # comment-only insert; no red-baseline veto


def test_objective_total_is_seventy_nine():
    from app.engine.objective_compiler import available_objectives

    # 79 after java-document-throws (the Java @throws Javadoc develop objective).
    assert len(set(available_objectives())) == 79


# --- PARITY ROW 1: move_value tier (the doc-surface 0.66 tier) ----------------

def test_parity_move_value_is_doc_surface_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("java_document_throws") == 0.66
    assert objective_value("java-document-throws") == 0.66
    assert objective_value("java-document-throws") != DEFAULT_VALUE  # not the fallback


# --- PARITY ROW 2: north-star manifest ----------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "java-document-throws" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_thirty_seven():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 37  # rose from 36 with java-document-throws


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
    assert "java-document-throws" in sc
    assert SOUNDNESS_STRATEGY["java-document-throws"]  # non-empty strategy string
    assert "java-document-throws" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder -----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "java-document-throws"
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


def test_parity_facet_phrase_lives_in_raised_exceptions_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["raised exceptions"]
    assert _PHRASE in ladder
    # the Python sibling (document-raises) stays directly before it (it was appended
    # after "the raised exceptions to document").
    assert ladder[ladder.index(_PHRASE) - 1] == "the raised exceptions to document"


# --- PARITY ROW 6: owner-report Java language attribution ---------------------

def test_parity_owner_report_attributes_java_language():
    from app.reporting.owner_report import _JAVA_NAME_PREFIXES, _languages_for

    # A java- slug contributes "Java" (NOT silently counted as Python), via the prefix.
    assert _JAVA_NAME_PREFIXES == ("java-",)
    assert _languages_for(["java-document-throws"]) == ["Java"]
    # The three-language order is stable (Python, Java, JS/TS).
    assert _languages_for(
        ["implement-stub", "java-document-throws", "js-wire-exports"]
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


# --- behaviour-identical landing on the java_undocumented_throws corpus shape --

@_needs_jdk
def test_behavior_identical_on_java_undocumented_throws_corpus_shape():
    # The standing soundness corpus carries a Java undocumented-throws LANDABLE shape:
    # a method declaring a `throws` clause with no Javadoc. java-document-throws SHOULD
    # document it (NOT a must-refuse trap), and the insert is behaviour-identical (a
    # comment-only edit re-parses fact-identical). This is the standing proof that the
    # Javadoc landing is sound on the sweep.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=True)
    cells = corpus.get("java-document-throws", {})
    assert cells, "java-document-throws should be swept in the heavy corpus path"
    assert cells.get("java_undocumented_throws") == "behavior-identical"
    # and it NEVER lands a VIOLATION on any corpus shape (the must-refuse traps —
    # java_false_final / java_blank_final / provenance_trap — have no `throws` clause,
    # so the objective cleanly refuses them).
    for shape, verdict in cells.items():
        assert not verdict.startswith("VIOLATION"), f"{shape}: {verdict}"


def test_java_undocumented_throws_is_not_a_must_refuse_shape():
    # The new shape is a LANDABLE, not a TRAP — it must NOT be in _SHAPE_MUST_REFUSE
    # (which would demand a refusal where a behaviour-identical landing is correct).
    from app.engine.soundness_audit import _SHAPE_MUST_REFUSE

    assert "java_undocumented_throws" not in _SHAPE_MUST_REFUSE
