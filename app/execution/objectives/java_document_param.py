"""Self-registering objective: java-document-param — a Java doc-surface landing that
mirrors the Python :mod:`document_param` (an ``Args:`` section from declared parameter
annotations) and the JS ``js-document-param-types`` (a JSDoc ``@param {T} name`` from
declared param types). It is the param-contract sibling of
:mod:`app.execution.objectives.java_document_throws` (which mints a Javadoc ``@throws``
block from a method's DECLARED ``throws`` clause).

For an own non-test ``.java`` method that DECLARES at least one parameter but carries NO
Javadoc, java-document-param lands a FRESH Javadoc block with one ``@param <name>`` line
per DECLARED parameter (a byte-splice of a leading ``/** ... */`` comment just before
the method's modifiers). The documented names are the method's DECLARED parameters
(``MethodTree.getParameters()`` -> ``VariableTree.getName()``) — exact and verbatim, in
source order, with NO type (the standard bare ``@param name`` Javadoc form). A Javadoc is
a COMMENT, so the edit changes ZERO declared structure (types/fields/method-signatures):
it is the soundest, smallest-blast-radius Java edit, BEHAVIOUR-IDENTICAL by construction.

Why it is sound (and needs NO Maven/Gradle/JUnit/compile run): a Javadoc block is trivia
— it adds no declared type/field/method and alters no signature — so the spliced file
MUST re-parse with the IDENTICAL structural fact-set (the same oracle java-document-throws
/ java-finalize-field rely on, where a ``final`` modifier changes zero facts). The scope
is deliberately narrow for soundness:

* Target ONLY a method with at least one DECLARED parameter AND **no existing Javadoc**
  (insert a FRESH block). A method that ALREADY carries a Javadoc is REFUSED — editing /
  merging an existing Javadoc is out of scope (it risks dropping author prose and is not
  behaviour-trivial to keep identical), exactly as the Python ``document-param`` only
  documents the UNDOCUMENTED. This refusal is ALSO what keeps java-document-param disjoint
  from java-document-throws: both target a no-Javadoc method and both insert a leading
  Javadoc, so whichever LANDS first makes the method documented and the other then refuses
  it — no double block. (java-document-param emits ``@param``-ONLY blocks, no ``@throws``,
  so the two contracts stay orthogonal, exactly as the Python document-param vs
  document-raises are separate.)
* REFUSE a method with ZERO parameters — a ``@param``-less Javadoc block is content-free
  (nothing to document), exactly as java-document-throws refuses an empty ``throws`` clause.
* REFUSE a test/fixture ``.java`` file (``FooTest`` / ``FooTests`` / ``FooTestCase`` /
  ``FooIT`` / ``src/test/``) — reusing :func:`is_java_source` (Apex never edits the suite).
* The single-Java-project gate (a ``pom.xml`` / ``build.gradle`` marker at the root) —
  reused verbatim from java-document-throws, so the objective is a clean NO-OP on a
  Python / JS tree.

The pipeline mirrors :mod:`app.execution.objectives.java_document_throws` exactly — same
adapter spine, same reparse-oracle pattern, with the fact-set IDENTICAL (a Javadoc comment
changes zero declared structure):

1. **DETECT** — only when a single ``pom.xml`` / ``build.gradle`` is at the root. Each own
   non-test ``.java`` source with at least one undocumented method that declares >=1
   parameter is a candidate (the walk / source-suffix gate / test-file refusal are reused
   from :mod:`app.execution.lang.java_adapter`).
2. **PLAN** — :func:`plan_java_document_param` reads the file, asks the driver
   (``ApexJavaDriver.java param-targets``) for each undocumented method's name + declared
   parameter simple names + the method-start offset, splices the indented Javadoc block
   BOTTOM-UP (descending offset, so earlier inserts stay valid), and records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.java.java_tool.reparse_facts_identical`) and asserts the
   structural fact-set ({types} + {fields} + {methods}) is IDENTICAL — a Javadoc comment
   can never change it, so any drift means a corrupt splice (refuse rather than land).
4. **LAND** — the ONE changed source is carried as a :class:`RenamePlan` (``originals``
   for byte-for-byte rollback, ``new_contents`` for the documented source), applied by the
   shared gated/rollback writer like every objective.

Deterministic (pure parse -> source-order targets, byte-offset splice bottom-up,
fact-set-equality oracle, no clock/random), offline (the parser is the JDK's OWN Compiler
Tree API; Apex installs nothing), zero-token. Test/fixture files are refused as WRITE
targets. ``expensive=True`` (detection spawns ``java``); ``scope_verify=False`` (a
comment-only insert has no red-baseline to dodge). When the JDK is absent every driver
call returns ``None`` and this is a clean no-op. Idempotent: a second run sees the Javadoc
and refuses (the driver omits an already-documented method).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.java.java_tool import (
    JavaParamTarget,
    param_targets,
    reparse_facts_identical,
)
from app.execution.lang.java_adapter import JAVA_SOURCE_SUFFIXES as _JAVA_SUFFIXES
from app.execution.lang.java_adapter import _walk_files, is_java_source
from app.execution.objectives._java_doc_common import dominant_eol
from app.execution.objectives._java_doc_common import is_java_project as _is_java_project
from app.execution.objectives._java_doc_common import line_indent as _line_indent
from app.execution.objectives._java_doc_common import read_unnormalized as _read_unnormalized
from app.execution.objectives._java_doc_common import record_doc_plan as _record_doc_plan

# The single-project gate / raw-bytes read / EOL detection / column-indent scan / plan
# tail are IDENTICAL to java-document-throws, so they live ONCE in :mod:`_java_doc_common`
# (genuine reuse, not a clone) and are imported above. ``dominant_eol`` is re-exported in
# ``__all__`` for callers/tests that import it from this module.

__all__ = [
    "plan_java_document_param",
    "detect_param_targets",
    "is_java_source",
    "documentable_param_targets",
    "render_param_javadoc",
    "splice_param_javadoc",
    "dominant_eol",
]


def documentable_param_targets(root: Path, rel: str) -> list[JavaParamTarget]:
    """The undocumented >=1-parameter method targets in ``root/rel`` the objective would
    actually document (empty on a non-source/test target or on refuse).

    Refuses a non-Java-source or test/fixture file outright (:func:`is_java_source`),
    then returns the driver-found targets (the driver already applied the
    at-least-one-parameter / no-existing-Javadoc gates), mirroring
    :func:`app.execution.objectives.java_document_throws.documentable_targets`."""
    if not is_java_source(rel):
        return []
    return list(param_targets(root, rel))


def render_param_javadoc(name: str, params: tuple[str, ...], indent: str,
                         eol: str = "\n") -> str:
    """The Javadoc block (a fact-only summary + one ``@param <name>`` line per declared
    parameter) for a method at column ``indent``, joined with ``eol`` and ending with
    ``eol + indent`` so the method keeps its column AND the file's line ending.

    The block is ``/**`` / a ``<name>.`` summary line / a blank ``*`` separator / one
    ``* @param <name>`` line per declared parameter (IN SOURCE ORDER, verbatim, NO type —
    the standard bare ``@param name`` Javadoc form) / ``*/`` / the method's indentation.
    It splices at the method-START offset, where the method's own leading indentation is
    ALREADY in the source just before the offset — so the OPENING ``/**`` line carries NO
    indent (the existing indent precedes it); only the continuation ``*`` lines and the
    trailing method re-indent carry ``indent``. The ``eol`` is the file's dominant line
    ending (``"\\r\\n"`` on a CRLF file), so the block matches the surrounding source. NO
    invented prose: the summary is the method name and the only contract lines are the
    DECLARED parameter names. Deterministic: source-order names, fixed layout, no
    clock/random."""
    lines = ["/**", f"{indent} * {name}.", f"{indent} *"]
    lines += [f"{indent} * @param {p}" for p in params]
    lines.append(f"{indent} */")
    # Trailing EOL + indent re-indents the method declaration that follows the block.
    return eol.join(lines) + eol + indent


def splice_param_javadoc(source: str, targets: list[JavaParamTarget]) -> str | None:
    """``source`` with a fresh ``@param`` Javadoc block inserted at each target's
    ``insert_offset``, or ``None`` when any offset is out of range (a stale scan —
    refuse rather than corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not shift a
    later offset. Pure byte-offset insertion of a COMMENT — every other byte survives
    untouched; the only added bytes are the Javadoc block (rendered at the method's own
    indentation via :func:`render_param_javadoc`), which alters ZERO declared structure.
    A target with no declared parameters would render an empty contract, so such a
    (driver-impossible) target is skipped rather than emitting a bare block.

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
        if not target.params:
            continue  # nothing to document (the driver never emits this) — skip
        indent = _line_indent(new_source, off)
        block = render_param_javadoc(target.name, target.params, indent, eol)
        new_source = new_source[:off] + block + new_source[off:]
    return new_source if new_source != source else None


def detect_param_targets(project_root: str | Path) -> list[str]:
    """The own non-test Java source files that have at least one undocumented method
    declaring >=1 parameter, each pinned by the single-Java-project root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``pom.xml`` or
    ``build.gradle`` is at the root — the single-project gate, what makes this a clean
    NO-OP on a Python (or JS) tree. Deterministic: sources in sorted order (as
    :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not _is_java_project(root):
        return []
    return [rel for rel in _walk_files(root, _JAVA_SUFFIXES)
            if documentable_param_targets(root, rel)]


def plan_java_document_param(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the document-param plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-Java-source / test / fixture write target outright
    (:func:`is_java_source`, via :func:`documentable_param_targets`). For each
    undocumented >=1-parameter method it splices a fresh ``@param`` Javadoc block
    bottom-up, then proves the splice is behaviour-identical with the driver's re-parse
    oracle (:func:`reparse_facts_identical` — re-parses AND carries the IDENTICAL
    structural fact-set) before recording it. An empty plan means nothing was
    documentable or the oracle refused — nothing is touched (never-fake-green)."""
    plan = RenamePlan(old=rel, new="java-document-param")
    root = Path(project_root)
    targets = documentable_param_targets(root, rel)
    if not targets:
        return plan  # non-Java / test / nothing to document — honest no-op
    target_file = root / rel
    # Read WITHOUT newline normalization so the splice operates in the SAME byte-space as
    # the driver's CRLF-counting offsets (see _read_unnormalized) — never the shared
    # `_read`, which would normalize CRLF -> LF and shift the offset mid-signature.
    original = _read_unnormalized(target_file)
    if not original and not target_file.exists():
        return plan  # unreadable / missing target — no-op
    documented = splice_param_javadoc(original, targets)
    if documented is None:
        return plan  # a stale offset / no-change splice — refuse
    if not reparse_facts_identical(root, rel, documented):
        return plan  # the splice did not re-parse fact-identical — refuse, land nothing
    return _record_doc_plan(plan, rel, original, documented, len(targets))


def _documentable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_java_document_param`` would actually change — i.e.
    the plan lands a Javadoc. A file whose every target the oracle refuses does NOT
    count, so it never shows as remaining debt (an honest measure, exactly like
    java-document-throws' self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_param_targets(root)
            if plan_java_document_param(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own Java sources still declare a >=1-parameter method with no
    Javadoc this objective can document with ``@param`` lines. 0 means none remain."""
    return float(len(_documentable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``java_document_param`` move per documentable source file. The
    ``operator="java_document_param"`` literal lives HERE (in the objectives package) so
    the move-value drift scanner discovers it exactly as for every other self-registered
    objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="java_document_param",
        target=f"{rel}:java-document-param",
        description=f"document the declared parameters in {rel} with @param Javadoc",
        build_plan=lambda r=rel: plan_java_document_param(root, r),
    ) for rel in _documentable_files(root)]


# Detection spawns ``java`` (the driver parses each source), so flag it expensive: the
# fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective java-document-param`.
# scope_verify is FALSE: inserting a Javadoc COMMENT is behaviour-identical — there is no
# red-baseline a full-suite gate could wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST
# entry. It registers DIRECTLY (a Java objective), exactly as java-document-throws /
# java-finalize-field / js-wire-exports do.
register(ObjectiveSpec(name="java-document-param", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
