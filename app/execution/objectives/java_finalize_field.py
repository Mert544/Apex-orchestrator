"""Self-registering objective: java-finalize-field — Apex's FIRST Java concrete
landing and the proof-of-value gate of the Java beachhead, the Java sibling of the
Python :mod:`add_final` (which seals a never-subclassed class with ``@typing.final``).

For an own non-test ``.java`` source that declares a ``private`` instance field
PROVABLY never reassigned anywhere in the file, java-finalize-field lands the ONE
missing ``final`` modifier (a byte-splice of ` final` just after the existing
modifier keywords) so the field reads ``private final ...`` — documenting and
enforcing the immutability the code already obeys, the mechanical seal a
student/team would otherwise add by hand. It is the soundest, smallest-blast-radius
Java edit: ``final`` on an already-never-reassigned field changes ZERO runtime
behaviour.

Why it is sound (and needs NO Maven/Gradle/JUnit/compile run): for a unit that does
NOT touch reflection or serialization, a ``private`` field cannot be written from
outside its class, so the ENTIRE *syntactic* assignment surface lives in this one
file's parse tree — exactly the property js-wire-exports relies on ("the binding
provably exists in the SAME AST"). The driver scans every assignment target in the
file (plain ``=``, compound ``+=``, ``++``/``--``); a field written ONLY by its
declarator initializer (or never) can take ``final`` without changing behaviour.
**No symbol resolution, no other file, no classpath** — pure Tier A.

The one hole in "the whole assignment surface is syntactic" is a writer that sets a
field WITHOUT a ``=``: ``java.lang.reflect.Field`` (``f.setAccessible(true);
f.setInt(obj, v)``) and the deserializer of a ``Serializable`` class both write
private fields reflectively, and sealing such a field ``final`` makes that write
throw ``IllegalAccessException`` / no-op at RUNTIME — a real breakage the fact-set
re-parse oracle CANNOT catch (``final`` is not a declared type/field/method fact, so
the spliced file re-parses fact-identical and would wrongly pass). A single-file
parser cannot prove WHICH private field such a writer leaves alone, so the driver
REFUSES the WHOLE compilation unit (yields no final-targets) when it imports
``java.lang.reflect`` / invokes a ``Field`` setter, OR any class ``implements
Serializable`` — the conservative whole-file refusal, the same spirit as the
multi-declarator refusal and the false-``final`` (inner-class reassignment) trap.

The pipeline mirrors :mod:`document_export_jsdoc` / :mod:`js_wire_exports` — same
adapter spine, same reparse-oracle pattern, with the fact-set IDENTICAL (a ``final``
modifier changes zero declared type/field/method structure):

1. **DETECT** — only when a single ``pom.xml`` or ``build.gradle`` is at the project
   root (the single-project gate, the Java analogue of one Python project root /
   one ``package.json``; this is what makes the objective a clean NO-OP on a
   Python/JS tree). Each own non-test ``.java`` source with at least one finalisable
   field is a candidate. The walk / source-suffix gate / test-file refusal are
   reused verbatim from :mod:`app.execution.lang.java_adapter` (the shared Java
   machinery).
2. **PLAN** — :func:`plan_java_finalize_field` reads the file, asks the driver
   (``ApexJavaDriver.java final-targets``) for each never-reassigned private field's
   name + modifier-end offset, splices ` final` BOTTOM-UP (descending offset, so
   earlier inserts stay valid), and records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.java.java_tool.reparse_facts_identical`) and asserts the
   structural fact-set ({types} + {fields} + {methods}) is IDENTICAL — a ``final``
   modifier can never change it, so any drift means a corrupt splice (refuse rather
   than land).
4. **LAND** — the ONE changed source is carried as a :class:`RenamePlan`
   (``originals`` for byte-for-byte rollback, ``new_contents`` for the sealed
   source), applied by the shared gated/rollback writer like every objective.

Deterministic (pure parse -> source-order targets, byte-offset splice bottom-up,
fact-set-equality oracle, no clock/random), offline (the parser is the JDK's OWN
Compiler Tree API; Apex installs nothing — no Maven/Gradle/network), zero-token.
Test/fixture files are refused as WRITE targets — Apex never edits the suite.
``expensive=True`` (detection spawns ``java``, so the fast plan/ascend board skips
the scan); ``scope_verify=False`` (a runtime-noop modifier add has no red-baseline
problem — no full-suite veto to dodge — so it needs NO ``SCOPE_VERIFY_ALLOWLIST``
entry). When the JDK is absent every driver call returns ``None`` and this is a
clean no-op.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.java.java_tool import (
    JavaFinalTarget,
    final_targets,
    reparse_facts_identical,
)
from app.execution.lang.java_adapter import JAVA_SOURCE_SUFFIXES as _JAVA_SUFFIXES
from app.execution.lang.java_adapter import _read, _walk_files, is_java_source

__all__ = [
    "plan_java_finalize_field",
    "detect_finalize_targets",
    "is_java_source",
    "finalizable_targets",
    "splice_final",
]

# The single-Java-project markers, the analogue of a single ``package.json`` root.
# Either a Maven ``pom.xml`` or a Gradle ``build.gradle`` (the two standard Java
# project roots) at the project root gates the whole objective — its presence is
# what makes this a clean NO-OP on a Python (or JS) tree.
_JAVA_PROJECT_MARKERS = ("pom.xml", "build.gradle")


def _is_java_project(root: Path) -> bool:
    """True when ``root`` carries a single-Java-project marker (``pom.xml`` or
    ``build.gradle``) — the single-project gate."""
    return any((root / marker).exists() for marker in _JAVA_PROJECT_MARKERS)


def finalizable_targets(root: Path, rel: str) -> list[JavaFinalTarget]:
    """The never-reassigned private-field targets in ``root/rel`` the objective would
    actually finalise (empty on a non-source/test target or on refuse).

    Refuses a non-Java-source or test/fixture file outright (:func:`is_java_source`),
    then returns the driver-found targets (the driver already applied the
    private / non-static / non-final / never-reassigned / single-declarator gates),
    mirroring :func:`app.execution.objectives.js_wire_exports.wireable_targets`."""
    if not is_java_source(rel):
        return []
    return list(final_targets(root, rel))


def splice_final(source: str, targets: list[JavaFinalTarget]) -> str | None:
    """``source`` with ` final` inserted at each target's ``insert_offset``, or
    ``None`` when any offset is out of range (a stale scan — refuse rather than
    corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not shift a
    later offset. Pure byte-offset insertion — the surrounding formatting and every
    other byte survive untouched; the only added bytes are the ` final` keyword that
    seals an already-never-reassigned field. The leading space makes ``private`` +
    ` final` read ``private final`` (the offset sits just past ``private``)."""
    new_source = source
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = target.insert_offset
        if not 0 <= off <= len(new_source):
            return None
        new_source = new_source[:off] + " final" + new_source[off:]
    return new_source if new_source != source else None


def detect_finalize_targets(project_root: str | Path) -> list[str]:
    """The own non-test Java source files that have at least one finalisable field,
    each pinned by the single-Java-project root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``pom.xml`` or
    ``build.gradle`` is at the root — the single-project gate, the Java analogue of
    one Python project root, and what makes this a clean NO-OP on a Python (or JS)
    tree. Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not _is_java_project(root):
        return []
    return [rel for rel in _walk_files(root, _JAVA_SUFFIXES)
            if finalizable_targets(root, rel)]


def plan_java_finalize_field(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the finalize-field plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-Java-source / test / fixture write target outright
    (:func:`is_java_source`, via :func:`finalizable_targets`). For each
    never-reassigned private field it splices a leading ` final` keyword bottom-up,
    then proves the splice is a runtime-noop with the driver's re-parse oracle
    (:func:`reparse_facts_identical` — re-parses AND carries the IDENTICAL structural
    fact-set) before recording it. An empty plan means nothing was finalisable or the
    oracle refused — nothing is touched (never-fake-green)."""
    plan = RenamePlan(old=rel, new="java-finalize-field")
    root = Path(project_root)
    targets = finalizable_targets(root, rel)
    if not targets:
        return plan  # non-Java / test / nothing to finalise — honest no-op
    target_file = root / rel
    original = _read(target_file)
    if not original and not target_file.exists():
        return plan  # unreadable / missing target — no-op
    sealed = splice_final(original, targets)
    if sealed is None:
        return plan  # a stale offset / no-change splice — refuse
    if not reparse_facts_identical(root, rel, sealed):
        return plan  # the splice did not re-parse fact-identical — refuse, land nothing
    plan.originals[rel] = original
    plan.new_contents[rel] = sealed
    plan.edits_by_file[rel] = len(targets)
    return plan


def _finalizable_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_java_finalize_field`` would actually change — i.e.
    the plan lands a ``final``. A file whose every target the oracle refuses does NOT
    count, so it never shows as remaining debt (an honest measure, exactly like the
    Python ``add-final`` self-validating count)."""
    root = Path(project_root)
    return [rel for rel in detect_finalize_targets(root)
            if plan_java_finalize_field(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own Java sources still declare a never-reassigned private
    field this objective can seal with ``final``. 0 means none remain."""
    return float(len(_finalizable_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``java_finalize_field`` move per finalisable source file. The
    ``operator="java_finalize_field"`` literal lives HERE (in the objectives package)
    so the move-value drift scanner discovers it exactly as for every other
    self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="java_finalize_field",
        target=f"{rel}:java-finalize-field",
        description=f"seal the never-reassigned private fields in {rel} with final",
        build_plan=lambda r=rel: plan_java_finalize_field(root, r),
    ) for rel in _finalizable_files(root)]


# Detection spawns ``java`` (the driver parses each source), so flag it expensive:
# the fast plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective java-finalize-field`.
# scope_verify is FALSE (unlike js-tdd-implement): adding ` final` to an
# already-never-reassigned field is a runtime no-op — there is no red-baseline a
# full-suite gate could wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
# It must register DIRECTLY (not via register_module_objective, which iterates the
# Python-only own-modules) because this is a Java objective — exactly as
# js-wire-exports / document-export-jsdoc do.
register(ObjectiveSpec(name="java-finalize-field", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
