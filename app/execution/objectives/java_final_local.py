"""Self-registering objective: java-final-local — the local-variable sibling of
java-final-parameter (which seals a never-reassigned method/constructor PARAMETER),
one step deeper into the SAME never-reassigned proof and the third member of the
Java ``final``-modifier family (java-finalize-field, java-final-parameter,
java-final-local). It pays down Checkstyle ``FinalLocalVariable`` / SonarQube
``S3008``.

For an own non-test ``.java`` source, java-final-local lands the ONE missing
``final`` modifier on any LOCAL VARIABLE declared as a DIRECT STATEMENT of a
method/constructor body block that is never reassigned anywhere in that method
(``int x = 1;`` -> ``final int x = 1;``) — a byte-splice of ``final `` just
before the local's type token. It is the mechanical seal a student/team would
otherwise add by hand, and it changes ZERO runtime behaviour.

Why it is sound (and needs NO whole-unit refusal — exactly like
java-final-parameter): a Java local variable is a stack-local whose ENTIRE
lifetime and assignment surface is that one method's own body. No other method,
no reflection, no ``Serializable`` deserializer, no other file can ever write a
local — there is no escape hatch analogous to a private field's reflective
``Field.set``/deserialization writer. So a PER-METHOD scan (reused verbatim from
java-final-parameter's driver spine) is both necessary AND sufficient: scanning a
single method's body for every assignment target (`=`, `+=`, `++`/`--`) proves
the WHOLE assignment surface for each of its own locals.

SCOPE BOUNDARY (an EXPLICIT, TESTED decision — never an accidental byproduct):
the driver considers ONLY a plain ``VariableTree`` that is a DIRECT statement of a
``BlockTree`` AND carries an initializer. That deliberately EXCLUDES, by omission
of the block-statement scan:

* a ``for``-loop init variable (``ForLoopTree.getInitializer()``),
* an enhanced-``for`` variable (``EnhancedForLoopTree.getVariable()``),
* a try-with-resources resource (``TryTree.getResources()``),
* a variable captured by a lambda / anonymous inner class,

none of which is a bare top-level block statement. It also REFUSES a local with
NO initializer (``int x;`` split from its assignment) — sealing a definitely-
assigned-once split local would need definite-assignment analysis the parse-only
Tier-A oracle cannot do, the local analogue of java-finalize-field's blank-`final`
refusal. Each refusal shape has a dedicated test, so the boundary is proven, not
assumed. And this is NOT merely re-adding a modifier javac already treats as
effectively-final: the VALUE is the explicit ``final`` keyword that satisfies the
linter, and the reparse-fact-set-identity oracle confirms the edit is
comment/modifier-only and behaviour-preserving.

The pipeline mirrors java-final-parameter's Tier-A spine (itself java-finalize-
field's, minus the whole-unit reflection/Serializable refusal a local has none
of):

1. **DETECT** — only when a single ``pom.xml``/``build.gradle`` is at the
   project root (the shared single-Java-project gate, reused from
   :mod:`app.execution.objectives.java_finalize_field`). Each own non-test
   ``.java`` source with at least one finalisable local is a candidate.
2. **PLAN** — :func:`plan_java_final_local` reads the file, asks the driver
   (``ApexJavaDriver.java final-local-targets``) for each never-reassigned
   local's name + insert offset, splices ``final `` BOTTOM-UP (descending
   offset, so earlier inserts stay valid), and records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.java.java_tool.reparse_facts_identical` — reused
   verbatim; a ``final`` modifier on a local changes zero declared
   type/field/method facts, exactly as it does on a field/parameter) and asserts
   the structural fact-set is IDENTICAL — any drift means a corrupt splice (refuse
   rather than land).
4. **LAND** — the changed source(s) carry as a :class:`RenamePlan` (``originals``
   for byte-for-byte rollback, ``new_contents`` for the sealed source), applied
   by the shared gated/rollback writer like every objective.

Refused (never sealed): a local already ``final``; one with NO initializer; one
reassigned anywhere in ITS OWN method body (a plain ``=``, a compound ``+=``, or
a ``++``/``--``); every local of an ABSTRACT/INTERFACE method or a NATIVE method
(no body — nothing to scan); a parse error. Out of scope (never touched, never
reported): a ``for``-loop init var, an enhanced-``for`` var, a try-with-resources
resource, and a lambda/anonymous-inner-class captured var — none is a direct
block statement.

Deterministic (pure parse -> per-method source-order targets, byte-offset splice
bottom-up, fact-set-equality oracle, no clock/random), offline (the JDK's own
Compiler Tree API; nothing installed), zero-token. Test/fixture files are refused
as WRITE targets. ``expensive=True`` (detection spawns ``java``, so the fast
plan/ascend board skips the scan); ``scope_verify=False`` (a runtime-noop modifier
add has no red-baseline problem — no full-suite veto to dodge — so it needs no
``SCOPE_VERIFY_ALLOWLIST`` entry). When the JDK is absent every driver call returns
``None`` and this is a clean no-op.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.java.java_tool import JavaFinalLocalTarget, final_local_targets
from app.execution.lang.java_adapter import JAVA_SOURCE_SUFFIXES as _JAVA_SUFFIXES
from app.execution.lang.java_adapter import _walk_files, is_java_source
from app.execution.objectives.java_finalize_field import (
    _is_java_project,
    record_final_splice_plan,
)

__all__ = [
    "plan_java_final_local",
    "detect_final_local_targets",
    "is_java_source",
    "finalizable_local_targets",
    "splice_final_locals",
]


def finalizable_local_targets(root: Path, rel: str) -> list[JavaFinalLocalTarget]:
    """The never-reassigned local-variable targets in ``root/rel`` the objective
    would actually finalise (empty on a non-source/test target or on refuse).

    Refuses a non-Java-source or test/fixture file outright
    (:func:`is_java_source`), then returns the driver-found targets (the driver
    already applied the per-method never-reassigned / already-final / no-initializer
    / no-body gates and the direct-block-statement scope boundary), mirroring
    :func:`app.execution.objectives.java_final_parameter.finalizable_param_targets`."""
    if not is_java_source(rel):
        return []
    return list(final_local_targets(root, rel))


def splice_final_locals(source: str, targets: list[JavaFinalLocalTarget]) -> str | None:
    """``source`` with ``final `` inserted at each target's ``insert_offset``, or
    ``None`` when any offset is out of range (a stale scan — refuse rather than
    corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not
    shift a later offset — the exact discipline
    :func:`app.execution.objectives.java_final_parameter.splice_final_params` uses
    for parameters. Pure byte-offset insertion — the surrounding formatting and
    every other byte survive untouched; the only added bytes are the ``final ``
    keyword that seals an already-never-reassigned local. The trailing space makes
    ``final`` + ``int x = 1`` read ``final int x = 1`` (the offset sits just before
    the local's own type token)."""
    new_source = source
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = target.insert_offset
        if not 0 <= off <= len(new_source):
            return None
        new_source = new_source[:off] + "final " + new_source[off:]
    return new_source if new_source != source else None


def detect_final_local_targets(project_root: str | Path) -> list[str]:
    """The own non-test Java source files that have at least one finalisable
    local, each pinned by the single-Java-project root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``pom.xml`` or
    ``build.gradle`` is at the root — the single-project gate reused from
    java-finalize-field, and what makes this a clean NO-OP on a Python (or JS)
    tree. Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not _is_java_project(root):
        return []
    return [rel for rel in _walk_files(root, _JAVA_SUFFIXES)
            if finalizable_local_targets(root, rel)]


def plan_java_final_local(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the final-local plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-Java-source / test / fixture write target outright
    (:func:`is_java_source`, via :func:`finalizable_local_targets`). For each
    never-reassigned local it splices a leading ``final `` keyword bottom-up,
    then proves the splice is a runtime-noop with the driver's re-parse oracle
    (via the shared :func:`~app.execution.objectives.java_finalize_field.record_final_splice_plan`
    tail — reused verbatim from java-finalize-field; a ``final`` modifier changes
    zero declared type/field/method facts whether it seals a field, a parameter,
    or a local). An empty plan means nothing was finalisable or the oracle
    refused — nothing is touched (never-fake-green)."""
    root = Path(project_root)
    targets = finalizable_local_targets(root, rel)
    if not targets:
        return RenamePlan(old=rel, new="java-final-local")  # nothing to finalise
    return record_final_splice_plan(
        root, rel, "java-final-local", targets, splice_final_locals)


def _finalizable_local_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_java_final_local`` would actually change
    — i.e. the plan lands a ``final`` on at least one local. A file whose
    every target the oracle refuses does NOT count, so it never shows as
    remaining debt (an honest measure, mirroring java-final-parameter's
    ``_finalizable_param_files``)."""
    root = Path(project_root)
    return [rel for rel in detect_final_local_targets(root)
            if plan_java_final_local(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own Java sources still declare a never-reassigned local
    variable this objective can seal with ``final``. 0 means none remain."""
    return float(len(_finalizable_local_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``java_final_local`` move per finalisable source file. The
    ``operator="java_final_local"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="java_final_local",
        target=f"{rel}:java-final-local",
        description=f"seal the never-reassigned local variables in {rel} with final",
        build_plan=lambda r=rel: plan_java_final_local(root, r),
    ) for rel in _finalizable_local_files(root)]


# Detection spawns ``java`` (the driver parses each source), so flag it
# expensive: the fast plan/ascend board skips the scan, but it stays runnable
# explicitly via `apex develop --objective java-final-local`.
# scope_verify is FALSE: adding ` final` to an already-never-reassigned
# local is a runtime no-op — there is no red-baseline a full-suite gate
# could wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
# It must register DIRECTLY (not via register_module_objective, which iterates
# the Python-only own-modules) because this is a Java objective — exactly as
# java-finalize-field / java-final-parameter do.
register(ObjectiveSpec(name="java-final-local", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
