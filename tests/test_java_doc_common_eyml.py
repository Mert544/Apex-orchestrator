"""Unit tests for :mod:`app.execution.objectives._java_doc_common` — the shared,
behaviour-identical helpers the two Java Javadoc-doc-surface objectives
(java-document-throws and java-document-param) both ride.

These helpers are pure (a string scan or a filesystem-presence test) and carry NO JDK
dependency, so every test here ALWAYS runs (no skip). They are exercised end-to-end by
both objective suites too; this module pins them DIRECTLY so the shared hub is tested in
isolation (a regression in any one helper is caught here, not only through an objective).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution.objectives._java_doc_common import (
    JAVA_PROJECT_MARKERS,
    dominant_eol,
    is_java_project,
    line_indent,
    read_unnormalized,
    record_doc_plan,
)


# --- is_java_project: the single-project gate ---------------------------------

def test_is_java_project_true_for_pom(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    assert is_java_project(tmp_path)


def test_is_java_project_true_for_gradle(tmp_path: Path):
    (tmp_path / "build.gradle").write_text("// marker\n", encoding="utf-8")
    assert is_java_project(tmp_path)


def test_is_java_project_false_without_marker(tmp_path: Path):
    # A bare (e.g. Python) tree carries neither marker -> the Java objectives no-op.
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert not is_java_project(tmp_path)


def test_markers_are_pom_and_gradle():
    assert JAVA_PROJECT_MARKERS == ("pom.xml", "build.gradle")


# --- read_unnormalized: raw bytes, EOL preserved ------------------------------

def test_read_unnormalized_preserves_crlf(tmp_path: Path):
    # CRLF must survive byte-for-byte (NOT universal-newline normalized to LF), so the
    # splice offset stays in the driver's byte-space.
    p = tmp_path / "Foo.java"
    p.write_bytes(b"class Foo {\r\n}\r\n")
    assert read_unnormalized(p) == "class Foo {\r\n}\r\n"


def test_read_unnormalized_preserves_lf(tmp_path: Path):
    p = tmp_path / "Foo.java"
    p.write_bytes(b"class Foo {\n}\n")
    assert read_unnormalized(p) == "class Foo {\n}\n"


def test_read_unnormalized_missing_file_is_empty(tmp_path: Path):
    assert read_unnormalized(tmp_path / "Nope.java") == ""


# --- dominant_eol -------------------------------------------------------------

def test_dominant_eol_detects_crlf_vs_lf():
    assert dominant_eol("a\r\nb\r\n") == "\r\n"
    assert dominant_eol("a\nb\n") == "\n"
    assert dominant_eol("no newline at all") == "\n"  # default LF
    # a single CRLF anywhere flips the whole file to CRLF (mixed -> CRLF).
    assert dominant_eol("a\nb\r\nc\n") == "\r\n"


# --- line_indent: the method's column -----------------------------------------

def test_line_indent_reads_leading_whitespace():
    src = "class C {\n    void f() {}\n}\n"
    off = src.index("void f()")
    assert line_indent(src, off) == "    "


def test_line_indent_tabs_preserved():
    src = "class C {\n\t\tvoid f() {}\n}\n"
    off = src.index("void f()")
    assert line_indent(src, off) == "\t\t"


def test_line_indent_zero_on_column_zero():
    src = "void f() {}\n"
    assert line_indent(src, 0) == ""


def test_line_indent_stops_at_first_non_blank():
    # Only the run of leading whitespace up to the first non-blank char counts.
    src = "  x void f() {}\n"
    off = src.index("void")
    assert line_indent(src, off) == "  "  # not "  x "


# --- record_doc_plan: the shared verified-plan tail ---------------------------

def test_record_doc_plan_stamps_originals_new_contents_and_edits():
    plan = RenamePlan(old="src/C.java", new="java-doc")
    out = record_doc_plan(plan, "src/C.java", "ORIG", "DOCD", 3)
    assert out is plan  # mutates + returns the same plan
    assert plan.originals["src/C.java"] == "ORIG"
    assert plan.new_contents["src/C.java"] == "DOCD"
    assert plan.edits_by_file["src/C.java"] == 3
