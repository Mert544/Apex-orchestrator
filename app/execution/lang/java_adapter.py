"""``JavaAdapter`` — the Java realisation of the :class:`LanguageAdapter` seam, the
Java sibling of :mod:`app.execution.lang.js_adapter`.

This module owns the Java-specific machinery the ``java-finalize-field`` objective
rides: the source-suffix gate, the JUnit/Maven test-file regex, the skip-dirs walk,
the byte-span splice, and the Tier-A ``reparse_facts_identical`` oracle. They live
here so a SECOND non-Python adapter keeps the Protocol non-vacuous and a future
``<lang>`` objective reuses the seam instead of re-copying the walk/suffix/oracle.

:class:`JavaAdapter` is a THIN re-expression of those functions — ``owns`` IS
:func:`is_java_source`, ``parse`` carries the source forward (the driver parses
per-file by path), ``apply`` is a pure byte-offset insert, and ``reparses`` reuses
the driver's ``parse-verify`` exit-2-means-does-not-parse contract via
:func:`app.execution.java.java_tool.parse_facts`'s conservative-None path. Because
every method is the same predicate/slice the objective performs, dispatch through
the adapter is byte-identical.

Deterministic (fixed regexes, sorted walk, byte-offset splice — no clock/random),
offline (the parser is the JDK's own Compiler Tree API; Apex installs nothing),
zero-token, exactly as the JS adapter is.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS
from app.execution.java.java_tool import parse_facts, reparse_facts_identical
from app.execution.lang.adapter import (
    Edit,
    ParseTree,
    Target,
    TargetQuery,
)

__all__ = [
    "JavaAdapter",
    "is_java_source",
    "splice_at",
    "reparse_facts_identical",
    "JAVA_SOURCE_SUFFIXES",
]

# The only source extension the Java driver parses. ANY other path is REFUSED — this
# is exactly what makes the objective a clean no-op on a Python (or any non-Java)
# file, so it never disturbs the Python path nor the soundness corpus.
_JAVA_SOURCE_SUFFIXES = frozenset({".java"})

# Public alias of the suffix set, so the adapter can expose the gate it enforces
# without leaking a private name.
JAVA_SOURCE_SUFFIXES = _JAVA_SOURCE_SUFFIXES

# A JUnit/Maven TEST file (also a refused WRITE target): a ``*Test.java`` /
# ``*Tests.java`` / ``*TestCase.java`` basename, or any file under a ``src/test/``
# directory (the Maven/Gradle standard test layout). Mirrors the common Java test
# discovery so a test source is never edited (Apex never edits the suite).
_TEST_BASENAME_RE = re.compile(r"(Test|Tests|TestCase|IT)\.java$")


def is_java_source(rel: str) -> bool:
    """True when ``rel`` is a NON-TEST Java source file this objective may edit.

    A file whose suffix is not ``.java`` is rejected (the no-op on a ``.py`` / any
    non-Java file), and a JUnit/Maven test file is rejected as a WRITE target (Apex
    never edits the suite). Pure, no filesystem touch."""
    p = rel.replace("\\", "/")
    if Path(p).suffix.lower() not in _JAVA_SOURCE_SUFFIXES:
        return False
    if _is_java_test(p):
        return False
    return True


def _is_java_test(rel: str) -> bool:
    """True when ``rel`` is a JUnit/Maven test file (``*Test.java`` / ``*Tests.java``
    / ``*TestCase.java`` / ``*IT.java`` basename, or under a ``src/test/`` dir)."""
    p = rel.replace("\\", "/")
    if "/src/test/" in p or p.startswith("src/test/"):
        return True
    return bool(_TEST_BASENAME_RE.search(Path(p).name))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _walk_files(root: Path, suffixes: frozenset[str]) -> list[str]:
    """The project's own files with one of ``suffixes`` (rel paths, sorted, canonical
    skip-dirs — caches/vendored build output/etc. — excluded). Deterministic. The
    Java image of the JS walk; ``target``/``build`` are common Java build-output dirs,
    skipped here so generated/compiled sources are never scanned."""
    out: list[str] = []
    skip = set(SKIPPED_DIRS) | {"target", "build", ".gradle"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in skip for part in Path(rel).parts):
            continue
        out.append(rel)
    return out


def splice_at(source: str, offset: int, text: str) -> str | None:
    """``source`` with ``text`` inserted at byte ``offset``, or ``None`` when the
    offset is out of range (a stale scan — refuse rather than corrupt the file).

    Pure byte-offset insertion — the surrounding formatting and every other byte
    survive untouched; the only added bytes are ``text`` (the ` final` keyword that
    seals an already-never-reassigned field)."""
    if not 0 <= offset <= len(source):
        return None
    return source[:offset] + text + source[offset:]


class JavaAdapter:
    """The Java :class:`LanguageAdapter`: a thin re-expression of the helpers above
    so the four verbs dispatch through one structural seam.

    ``owns`` IS :func:`is_java_source`; ``parse`` carries the text forward (the
    driver parses per-file by path, see :meth:`apply`/:meth:`reparses`); ``locate``
    exposes the byte ``insert_offset`` the detector already found (carried in
    ``query.extra``); ``apply`` IS :func:`splice_at`; and ``reparses`` reuses the
    driver's conservative ``parse_facts`` path (a file the driver exits-2 on yields
    ``None``). Every method is the same predicate/slice the objective performs, so
    dispatch is byte-identical."""

    name = "java"

    def owns(self, rel: str) -> bool:
        """True when ``rel`` is a non-test Java source — the file gate."""
        return is_java_source(rel)

    def parse(self, source: str) -> ParseTree | None:
        """Wrap ``source`` as a parse tree — the Java driver parses per-file by path
        (see :meth:`reparses`), so this only carries the text forward and is never
        ``None`` here (a does-not-parse file simply yields no targets via the
        detector)."""
        return ParseTree(tree=source)

    def locate(self, tree: ParseTree, source: str,
               query: TargetQuery) -> Target | None:
        """The field named by ``query`` as a zero-width byte-span :class:`Target` at
        its ``insert_offset`` (sourced from ``query.extra['insert_offset']`` — the
        offset the detector already located), or ``None`` when absent. The Java
        driver locates fields by path, so the detector supplies the offset and this
        exposes it through the seam as a ``(offset, offset)`` insertion point."""
        off = query.extra.get("insert_offset")
        if not isinstance(off, int):
            return None
        return Target(name=query.name, span=(off, off))

    def apply(self, source: str, target: Target, edit: Edit) -> str | None:
        """``source`` with ``edit.body`` inserted at ``target``'s insertion point, or
        ``None`` when the offset is stale — the exact :func:`splice_at` insert. The
        span is zero-width (``start == end``), so ``edit.body`` (` final`) is inserted
        verbatim, not a replacement."""
        start, _end = target.span
        return splice_at(source, start, edit.body)

    def reparses(self, new_source: str) -> bool:
        """True when ``new_source`` is well-formed Java. Proven by writing it to a
        throwaway file and asking the driver to parse it: the driver exits 2 (read as
        no result -> ``parse_facts`` is ``None``) on a file that does not parse, so a
        parse that succeeds is the well-formedness proof — the Java image of the JS
        ``scan``-succeeds / Python re-``ast.parse`` guard."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / "Probe.java").write_text(new_source, encoding="utf-8")
            return parse_facts(tmp_root, "Probe.java") is not None
