"""Shared, behaviour-identical helpers for the Java Javadoc-doc-surface objectives
(:mod:`app.execution.objectives.java_document_throws` and
:mod:`app.execution.objectives.java_document_param`).

Both objectives splice a FRESH leading Javadoc block (one ``@throws <Type>`` line per
declared throws-type, resp. one bare ``@param <name>`` line per declared parameter) just
before an UNDOCUMENTED method, then prove the splice behaviour-identical with the driver's
re-parse oracle. The single-project gate, the raw-bytes read, the EOL detection, the
column-indent scan, and the plan-recording tail are IDENTICAL between them — so they live
here ONCE rather than being copy-pasted into each objective (genuine reuse, not a clone).

Pure / deterministic (no clock, no random, no symbol resolution): each function is a
string or filesystem-presence test. The only per-objective parts (the target dataclass,
the ``render_*_javadoc`` layout, the per-target ``splice_*_javadoc``) stay in each
objective module, since their bytes legitimately differ (``@throws`` vs ``@param``)."""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

__all__ = [
    "JAVA_PROJECT_MARKERS",
    "is_java_project",
    "read_unnormalized",
    "dominant_eol",
    "line_indent",
    "record_doc_plan",
]

# The single-Java-project markers: either a Maven ``pom.xml`` or a Gradle
# ``build.gradle`` at the project root gates the whole objective — its presence is what
# makes a Java doc objective a clean NO-OP on a Python (or JS) tree.
JAVA_PROJECT_MARKERS = ("pom.xml", "build.gradle")


def is_java_project(root: Path) -> bool:
    """True when ``root`` carries a single-Java-project marker (``pom.xml`` or
    ``build.gradle``) — the single-project gate."""
    return any((root / marker).exists() for marker in JAVA_PROJECT_MARKERS)


def read_unnormalized(path: Path) -> str:
    """The target's UTF-8 text with line endings PRESERVED (NOT universal-newline
    normalized), or ``""`` on an OS error.

    CRITICAL for the splice offset to be valid: the driver reads RAW bytes
    (``Files.readAllBytes``), so every ``insert_offset`` it reports from
    ``SourcePositions`` counts each ``\\r`` of a CRLF file. The shared
    :func:`app.execution.lang.java_adapter._read` normalizes CRLF -> LF (``read_text``
    uses universal newlines), which would shift every offset left by the number of
    ``\\r`` before the method and splice the Javadoc MID-SIGNATURE on a Windows-authored
    file — a fact-neutral corruption the re-parse oracle cannot catch (a comment still
    parses). Reading via ``read_bytes().decode`` keeps the splice in the SAME byte-space
    as the driver's offsets, so the block lands at the right place AND the file's
    original line endings survive byte-for-byte."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def dominant_eol(source: str) -> str:
    """The line ending the spliced Javadoc block should use: ``"\\r\\n"`` when ``source``
    contains any CRLF, else ``"\\n"``.

    Emitting the block with the file's own EOL keeps the documented file internally
    consistent (no mixed endings) AND makes a second run a byte-identical no-op — the
    driver re-parses the now-documented method, sees its Javadoc, and omits it, so the
    plan is idempotent on CRLF and LF alike. Deterministic: a pure substring test."""
    return "\r\n" if "\r\n" in source else "\n"


def line_indent(source: str, offset: int) -> str:
    """The leading whitespace of the line ``offset`` sits on (the run of spaces/tabs
    from the start of the line up to the first non-blank char), used to indent the
    spliced Javadoc block to the method's own column.

    The method-start ``offset`` the driver reports sits just past this indent (at the
    ``void``/modifier token), so the indent is the slice from the previous newline to
    the first non-whitespace char on that line. Pure string scan — no parse."""
    line_start = source.rfind("\n", 0, offset) + 1  # 0 when offset is on line 1
    indent_chars = []
    for ch in source[line_start:offset]:
        if ch in (" ", "\t"):
            indent_chars.append(ch)
        else:
            break
    return "".join(indent_chars)


def record_doc_plan(plan: RenamePlan, rel: str, original: str, documented: str,
                    edits: int) -> RenamePlan:
    """Record a VERIFIED documented source on ``plan`` (the original for byte-for-byte
    rollback, the documented bytes as the new content, and the per-file edit count) and
    return it.

    Called only AFTER the caller has proven the splice behaviour-identical with the
    driver's re-parse oracle, so this is the pure "stamp the plan" tail both Java doc
    objectives share. Mutates ``plan`` in place (its caller owns it) and returns it for a
    one-line ``return record_doc_plan(...)`` at the call site."""
    plan.originals[rel] = original
    plan.new_contents[rel] = documented
    plan.edits_by_file[rel] = edits
    return plan
