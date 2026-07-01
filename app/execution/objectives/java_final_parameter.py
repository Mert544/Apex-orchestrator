"""Self-registering objective: java-final-parameter — the parameter-level sibling
of java-finalize-field (which seals a never-reassigned PRIVATE FIELD), and a
STRONGER soundness case: a runtime no-op modifier-add on a declared
method/constructor parameter PROVABLY never reassigned in that method's OWN body.

For an own non-test ``.java`` source, java-final-parameter lands the ONE missing
``final`` modifier on any declared parameter never reassigned anywhere in its
method (`void f(int x)` -> `void f(final int x)`) — a byte-splice of ``final ``
just before the parameter's type token. It is the mechanical seal a
student/team would otherwise add by hand, and it changes ZERO runtime behaviour.

Why it is sound (and needs NO whole-unit refusal — unlike java-finalize-field):
a Java method/constructor PARAMETER is a stack-local variable whose ENTIRE
lifetime and assignment surface is that one method's own body. No other method,
no reflection, no ``Serializable`` deserializer, no other file can ever write a
local — there is no escape hatch analogous to a private field's reflective
``Field.set``/deserialization writer. So a PER-METHOD scan (not the whole-FILE
scan java-finalize-field needs for a field) is both necessary AND sufficient:
scanning a single method's body for every assignment target (`=`, `+=`, `++`/
`--`) proves the WHOLE assignment surface for each of its own parameters. No
symbol resolution, no other file, no classpath, no whole-unit refusal — the
soundest, smallest-blast-radius Java edit in the objective family.

The pipeline mirrors java-finalize-field's Tier-A spine, minus the whole-unit
reflection/Serializable refusal (a parameter has none of that field's escape
hatches):

1. **DETECT** — only when a single ``pom.xml``/``build.gradle`` is at the
   project root (the shared single-Java-project gate, reused from
   :mod:`app.execution.objectives.java_finalize_field`). Each own non-test
   ``.java`` source with at least one finalisable parameter is a candidate.
2. **PLAN** — :func:`plan_java_final_parameter` reads the file, asks the driver
   (``ApexJavaDriver.java final-param-targets``) for each never-reassigned
   parameter's name + insert offset, splices ``final `` BOTTOM-UP (descending
   offset, so earlier inserts stay valid), and records it.
3. **VERIFY** — the driver RE-PARSES the spliced bytes
   (:func:`app.execution.java.java_tool.reparse_facts_identical` — reused
   verbatim; a ``final`` modifier on a parameter changes zero declared
   type/field/method facts, exactly as it does on a field) and asserts the
   structural fact-set is IDENTICAL — any drift means a corrupt splice (refuse
   rather than land).
4. **LAND** — the changed source(s) carry as a :class:`RenamePlan` (``originals``
   for byte-for-byte rollback, ``new_contents`` for the sealed source), applied
   by the shared gated/rollback writer like every objective.

Refused (never sealed): a parameter already ``final``; one reassigned anywhere
in ITS OWN method body (a plain ``=``, a compound ``+=``, or a ``++``/``--``);
every parameter of an ABSTRACT/INTERFACE method or a NATIVE method (no body to
scan — nothing to scan, so the driver skips the WHOLE method's parameters
rather than vacuously accepting them); a parse error. Scope: declared
method/constructor parameters only — a lambda parameter, an enhanced-``for``
loop variable, and a ``catch`` variable are OUT OF SCOPE for this first cut
(never touched, never reported).

Deterministic (pure parse -> per-method source-order targets, byte-offset
splice bottom-up, fact-set-equality oracle, no clock/random), offline (the JDK's
own Compiler Tree API; nothing installed), zero-token. Test/fixture files are
refused as WRITE targets. ``expensive=True`` (detection spawns ``java``, so the
fast plan/ascend board skips the scan); ``scope_verify=False`` (a runtime-noop
modifier add has no red-baseline problem — no full-suite veto to dodge — so it
needs no ``SCOPE_VERIFY_ALLOWLIST`` entry). When the JDK is absent every driver
call returns ``None`` and this is a clean no-op.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.java.java_tool import JavaFinalParamTarget, final_param_targets
from app.execution.lang.java_adapter import JAVA_SOURCE_SUFFIXES as _JAVA_SUFFIXES
from app.execution.lang.java_adapter import _walk_files, is_java_source
from app.execution.objectives.java_finalize_field import (
    _is_java_project,
    record_final_splice_plan,
)

__all__ = [
    "plan_java_final_parameter",
    "detect_final_parameter_targets",
    "is_java_source",
    "finalizable_param_targets",
    "splice_final_params",
]


def finalizable_param_targets(root: Path, rel: str) -> list[JavaFinalParamTarget]:
    """The never-reassigned declared-parameter targets in ``root/rel`` the
    objective would actually finalise (empty on a non-source/test target or on
    refuse).

    Refuses a non-Java-source or test/fixture file outright
    (:func:`is_java_source`), then returns the driver-found targets (the driver
    already applied the per-method never-reassigned / already-final / no-body
    gates), mirroring :func:`app.execution.objectives.java_finalize_field.finalizable_targets`."""
    if not is_java_source(rel):
        return []
    return list(final_param_targets(root, rel))


def splice_final_params(source: str, targets: list[JavaFinalParamTarget]) -> str | None:
    """``source`` with ``final `` inserted at each target's ``insert_offset``, or
    ``None`` when any offset is out of range (a stale scan — refuse rather than
    corrupt the file).

    Splices BOTTOM-UP (descending offset) so each earlier insertion does not
    shift a later offset — the exact discipline
    :func:`app.execution.objectives.java_finalize_field.splice_final` uses for
    fields. Pure byte-offset insertion — the surrounding formatting and every
    other byte survive untouched; the only added bytes are the ``final `` keyword
    that seals an already-never-reassigned parameter. The trailing space makes
    ``final`` + ``int x`` read ``final int x`` (the offset sits just before the
    parameter's own type token)."""
    new_source = source
    for target in sorted(targets, key=lambda t: t.insert_offset, reverse=True):
        off = target.insert_offset
        if not 0 <= off <= len(new_source):
            return None
        new_source = new_source[:off] + "final " + new_source[off:]
    return new_source if new_source != source else None


def detect_final_parameter_targets(project_root: str | Path) -> list[str]:
    """The own non-test Java source files that have at least one finalisable
    parameter, each pinned by the single-Java-project root-gate.

    REFUSES the whole project (returns ``[]``) unless a single ``pom.xml`` or
    ``build.gradle`` is at the root — the single-project gate reused from
    java-finalize-field, and what makes this a clean NO-OP on a Python (or JS)
    tree. Deterministic: sources in sorted order (as :func:`_walk_files` emits)."""
    root = Path(project_root)
    if not _is_java_project(root):
        return []
    return [rel for rel in _walk_files(root, _JAVA_SUFFIXES)
            if finalizable_param_targets(root, rel)]


def plan_java_final_parameter(project_root: str | Path, rel: str) -> RenamePlan:
    """Build the final-parameter plan for ONE source file, or an empty no-op plan
    (an honest refusal).

    Refuses a non-Java-source / test / fixture write target outright
    (:func:`is_java_source`, via :func:`finalizable_param_targets`). For each
    never-reassigned parameter it splices a leading ``final `` keyword bottom-up,
    then proves the splice is a runtime-noop with the driver's re-parse oracle
    (via the shared :func:`~app.execution.objectives.java_finalize_field.record_final_splice_plan`
    tail — reused verbatim from java-finalize-field; a ``final`` modifier changes
    zero declared type/field/method facts whether it seals a field or a
    parameter). An empty plan means nothing was finalisable or the oracle
    refused — nothing is touched (never-fake-green)."""
    root = Path(project_root)
    targets = finalizable_param_targets(root, rel)
    if not targets:
        return RenamePlan(old=rel, new="java-final-parameter")  # nothing to finalise
    return record_final_splice_plan(
        root, rel, "java-final-parameter", targets, splice_final_params)


def _finalizable_param_files(project_root: str | Path) -> list[str]:
    """The own source files ``plan_java_final_parameter`` would actually change
    — i.e. the plan lands a ``final`` on at least one parameter. A file whose
    every target the oracle refuses does NOT count, so it never shows as
    remaining debt (an honest measure, mirroring java-finalize-field's
    ``_finalizable_files``)."""
    root = Path(project_root)
    return [rel for rel in detect_final_parameter_targets(root)
            if plan_java_final_parameter(root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own Java sources still declare a never-reassigned
    method/constructor parameter this objective can seal with ``final``. 0 means
    none remain."""
    return float(len(_finalizable_param_files(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``java_final_parameter`` move per finalisable source file. The
    ``operator="java_final_parameter"`` literal lives HERE (in the objectives
    package) so the move-value drift scanner discovers it exactly as for every
    other self-registered objective."""
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="java_final_parameter",
        target=f"{rel}:java-final-parameter",
        description=f"seal the never-reassigned method parameters in {rel} with final",
        build_plan=lambda r=rel: plan_java_final_parameter(root, r),
    ) for rel in _finalizable_param_files(root)]


# Detection spawns ``java`` (the driver parses each source), so flag it
# expensive: the fast plan/ascend board skips the scan, but it stays runnable
# explicitly via `apex develop --objective java-final-parameter`.
# scope_verify is FALSE: adding ` final` to an already-never-reassigned
# parameter is a runtime no-op — there is no red-baseline a full-suite gate
# could wrongly veto, so it needs NO SCOPE_VERIFY_ALLOWLIST entry.
# It must register DIRECTLY (not via register_module_objective, which iterates
# the Python-only own-modules) because this is a Java objective — exactly as
# java-finalize-field does.
register(ObjectiveSpec(name="java-final-parameter", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=False))
