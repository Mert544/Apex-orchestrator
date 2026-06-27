"""Self-registering objective: java-document-throws — the SECOND Java concrete
landing (after java-finalize-field), deepening the Java lane with a doc-surface
contribution: the Java sibling of the Python :mod:`document_raises` (which mints a
``Raises:`` docstring section from a function's proven literal ``raise <Name>(...)``).

For an own non-test ``.java`` method that DECLARES a ``throws`` clause but carries NO
Javadoc, java-document-throws lands a fresh Javadoc block with one ``@throws <Type>``
line per declared checked-exception type (a byte-splice of a leading
``/** ... */`` comment just before the method's modifiers). The documented types are
the method's DECLARED throws clause (``MethodTree.getThrows()``) — exact and verbatim,
NEVER inferred from ``throw new X()`` statements — so the contract is the one the
method already publishes. A Javadoc is a COMMENT, so the edit changes ZERO declared
structure (types/fields/method-signatures): it is the soundest, smallest-blast-radius
Java edit, BEHAVIOUR-IDENTICAL by construction.

Why it is sound (and needs NO Maven/Gradle/JUnit/compile run): a Javadoc block is
trivia — it adds no declared type/field/method and alters no signature — so the
spliced file MUST re-parse with the IDENTICAL structural fact-set (the same oracle
java-finalize-field relies on, where a ``final`` modifier changes zero facts). The
scope is deliberately narrow for soundness:

* Target ONLY a method with a NON-EMPTY ``throws`` clause AND **no existing Javadoc**
  (insert a FRESH block). A method that ALREADY carries a Javadoc is REFUSED — editing
  / merging an existing Javadoc is out of scope (it risks dropping author prose and is
  not behaviour-trivial to keep identical), exactly as the Python ``document-signature``
  / ``document-raises`` only document the UNDOCUMENTED.
* REFUSE a test/fixture ``.java`` file (``FooTest`` / ``FooTests`` / ``FooTestCase`` /
  ``FooIT`` / ``src/test/``) — reusing :func:`is_java_source` (Apex never edits the
  suite).
* The single-Java-project gate (a ``pom.xml`` / ``build.gradle`` marker at the root) —
  reused verbatim from java-finalize-field, so the objective is a clean NO-OP on a
  Python / JS tree.

The pipeline mirrors :mod:`app.execution.objectives.java_finalize_field` exactly —
same adapter spine, same reparse-oracle pattern, with the fact-set IDENTICAL (a Javadoc
comment changes zero declared structure):

1. **DETECT** — only when a single ``pom.xml`` / ``build.gradle`` is at the root. Each
   own non-test ``.java`` source with at least one undocumented throwing method is a
   candidate (the walk / source-suffix gate / test-file refusal are reused from
   :mod:`app.execution.lang.java_adapter`).
2. **PLAN** — :func:`plan_java_document_throws` reads the file, asks the driver
   (``ApexJavaDriver.java doc-targets``) for each undocumented throwing method's name +
   declared throws-type simple names + the method-start offset, splices the indented
   Javadoc block BOTTOM-UP (descending offset, so earlier inserts stay valid), and
   records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.java.java_tool.reparse_facts_identical`) and asserts the
   structural fact-set ({types} + {fields} + {methods}) is IDENTICAL — a Javadoc comment
   can never change it, so any drift means a corrupt splice (refuse rather than land).
4. **LAND** — the ONE changed source is carried as a :class:`RenamePlan` (``originals``
   for byte-for-byte rollback, ``new_contents`` for the documented source), applied by
   the shared gated/rollback writer like every objective.

Deterministic (pure parse -> source-order targets, byte-offset splice bottom-up,
fact-set-equality oracle, no clock/random), offline (the parser is the JDK's OWN
Compiler Tree API; Apex installs nothing), zero-token. Test/fixture files are refused as
WRITE targets. ``expensive=True`` (detection spawns ``java``); ``scope_verify=False`` (a
comment-only insert has no red-baseline to dodge). When the JDK is absent every driver
call returns ``None`` and this is a clean no-op. Idempotent: a second run sees the
Javadoc and refuses (the driver omits an already-documented method).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.java.java_tool import (
    JavaDocTarget,
    doc_targets,
    reparse_facts_identical,
)
from app.execution.lang.java_adapter import JAVA_SOURCE_SUFFIXES as _JAVA_SUFFIXES
from app.execution.lang.java_adapter import _walk_files, is_java_source

__all__ = [
    "plan_java_document_throws",
    "detect_doc_targets",
    "is_java_source",
    "documentable_targets",
    "render_throws_javadoc",
    "splice_javadoc",
    "dominant_eol",
]

# The single-Java-project markers, reused verbatim from java-finalize-field: either a
# Maven ``pom.xml`` or a Gradle ``build.gradle`` at the project root gates the whole
# objective — its presence is what makes this a clean NO-OP on a Python (or JS) tree.
_JAVA_PROJECT_MARKERS = ("pom.xml", "build.gradle")


def _is_java_project(root: Path) -> bool:
    """True when ``root`` carries a single-Java-project marker (``pom.xml`` or
    ``build.gradle``) — the single-project gate."""
    return any((root / marker).exists() for marker in _JAVA_PROJECT_MARKERS)


def _read_unnormalized(path: Path) -> str:
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


def documentable_targets(root: Path, rel: str) -> list[JavaDocTarget]:
    """The undocumented throwing-method targets in ``root/rel`` the objective would
    actually document (empty on a non-source/test target or on refuse).

    Refuses a non-Java-source or test/fixture file outright (:func:`is_java_source`),
    then returns the driver-found targets (the driver already applied the
    non-empty-throws-clause / no-existing-Javadoc gates), mirroring
    :func:`app.execution.objectives.java_finalize_field.finalizable_targets`."""
    if not is_java_source(rel):
        return []
    return list(doc_targets(root, rel))


def _line_indent(source: str, offset: int) -> str:
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


def render_throws_javadoc(name: str, throws_types: tuple[str, ...], indent: str,
                          eol: str = "\n") -> str:
    """The Javadoc block (a fact-only summary + one ``@throws <Type>`` line per declared
    type) for a method at column ``indent``, joined with ``eol`` and ending with
    ``eol + indent`` so the method keeps its column AND the file's line ending.

    The block is ``/**`` / a ``<name>.`` summary line / a blank ``*`` separator / one
    ``* @throws <Type>`` line per declared throws-type (IN SOURCE ORDER, verbatim) /
    ``*/`` / the method's indentation. It splices at the method-START offset, where the
    method's own leading indentation is ALREADY in the source just before the offset —
    so the OPENING ``/**`` line carries NO indent (the existing indent precedes it); only
    the continuation ``*`` lines and the trailing method re-indent carry ``indent``. The
    ``eol`` is the file's dominant line ending (``"\\r\\n"`` on a CRLF file), so the block
    matches the surrounding source. NO invented prose: the summary is the method name and
    the only contract lines are the DECLARED throws types. Deterministic: source-order
    types, fixed layout, no clock/random."""
    lines = ["/**", f"{indent} * {name}.", f"{indent} *"]
    lines += [f"{indent} * @throws {t}" for t in throws_types]
    lines.append(f"{indent} */")
    # Trailing EOL + indent re-indents the method declaration that follows the block.
    return eol.join(lines) + eol + indent


def splice_javadoc(source: str, targets: list[JavaDocTarget]) -> str | None:
    """``source`` with a fresh ``@throws`` Javadoc block inserted at each target's
    ``insert_offset``, or ``None`` when any offset is out of range (a stale scan —
    refuse rather than corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not shift a
    later offset. Pure byte-offset insertion of a COMMENT — every other byte survives
    untouched; the only added bytes are the Javadoc block (rendered at the method's
    own indentation via :func:`render_throws_javadoc`), which alters ZERO declared
    structure. A target with no declared throws types would render an empty contract,
    so such a (driver-impossible) target is skipped rather than emitting a bare block.

    ``source`` MUST be the UN-normalized file text (see :func:`_read_unnormalized`): the
    ``insert_offset`` counts CRLF bytes exactly as the driver does, so a normalized
    (CRLF -> LF) ``source`` would splice at a shifted, mid-signature offset. The block is
    emitted with the file's :func:`dominant_eol` so a CRLF file stays CRLF and a second
    run is a byte no-op."""
    new_source = source
    eol = dominant_eol(source)
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = target.insert_offset
        if not 0 <= off <= len(new_source):
            return None
        if not target.throws_types:
            continue  # nothing to document (the driver never emits this) — skip
        indent = _line_indent(new_source, off)
        block = render_throws_javadoc(target.name, target.throws_types, indent, eol)
        new_source = new_source[:off] + block + new_source[off:]
    return new_source if new_source != source else None


def detect_doc_targets(project_root: str | Path) -> list[str]:
    """The own non-test Java source files that have at least one undocumented throwing
    method, each pinned by the single-Java-project root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``pom.xml`` or
    ``build.gradle`` is at the root — the single-project gate, what makes this a clean
    NO-OP on a Python (or JS) tree. Deterministic: sources in sorted order (as
    :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not _is_java_project(root):
        return []
    return [rel for rel in _walk_files(root, _JAVA_SUFFIXES)
            if documentable_targets(root, rel)]


def plan_java_document_throws(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the document-throws plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-Java-source / test / fixture write target outright
    (:func:`is_java_source`, via :func:`documentable_targets`). For each undocumented
    throwing method it splices a fresh ``@throws`` Javadoc block bottom-up, then proves
    the splice is behaviour-identical with the driver's re-parse oracle
    (:func:`reparse_facts_identical` — re-parses AND carries the IDENTICAL structural
    fact-set) before recording it. An empty plan means nothing was documentable or the
    oracle refused — nothing is touched (never-fake-green)."""
    plan = RenamePlan(old=rel, new="java-document-throws")
    root = Path(project_root)
    targets = documentable_targets(root, rel)
    if not targets:
        return plan  # non-Java / test / nothing to document — honest no-op
    target_file = root / rel
    # Read WITHOUT newline normalization so the splice operates in the SAME byte-space as
    # the driver's CRLF-counting offsets (see _read_unnormalized) — never the shared
    # `_read`, which would normalize CRLF -> LF and shift the offset mid-signature.
    original = _read_unnormalized(target_file)
    if not original and not target_file.exists():
        return plan  # unreadable / missing target — no-op
    documented = splice_javadoc(original, targets)
    if documented is None:
        return plan  # a stale offset / no-change splice — refuse
    if not reparse_facts_identical(root, rel, documented):
        return plan  # the splice did not re-parse fact-identical — refuse, land nothing
    plan.originals[rel] = original
    plan.new_contents[rel] = documented
    plan.edits_by_file[rel] = len(targets)
    return plan


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_java_document_throws`` would actually change — i.e.
    the plan lands a Javadoc. A file whose every target the oracle refuses does NOT
    count, so it never shows as remaining debt (an honest measure, exactly like
    java-finalize-field's self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_doc_targets(root)
            if plan_java_document_throws(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own Java sources still declare a throwing method with no
    Javadoc this objective can document with ``@throws`` lines. 0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``java_document_throws`` move per documentable source file. The
    ``operator="java_document_throws"`` literal lives HERE (in the objectives package)
    so the move-value drift scanner discovers it exactly as for every other
    self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="java_document_throws",
        target=f"{rel}:java-document-throws",
        description=f"document the declared throws clauses in {rel} with @throws Javadoc",
        build_plan=lambda r=rel: plan_java_document_throws(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns ``java`` (the driver parses each source), so flag it expensive: the
# fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective java-document-throws`.
# scope_verify is FALSE: inserting a Javadoc COMMENT is behaviour-identical — there is no
# red-baseline a full-suite gate could wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST
# entry. It registers DIRECTLY (a Java objective), exactly as java-finalize-field /
# js-wire-exports do.
register(ObjectiveSpec(name="java-document-throws", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
