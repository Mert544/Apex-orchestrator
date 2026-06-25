"""Self-registering objective: add-slots.

Land ``__slots__`` on a project's own class whose instance-attribute set is PROVABLY
CLOSED — never extended dynamically anywhere in the project. The structural DUAL of
freeze-dataclass (and pre-anticipated at ``freeze_dataclass.py:43``): both prove, over
the WHOLE project, that no never-declared attribute is ever stored, then land a
storage/shape lock. ``__slots__`` changes ONLY the per-instance storage mechanism
(drops ``__dict__``), not any observable VALUE, FOR a closed-attribute class — so the
change is value-preserving by construction; the lone failure mode (an off-slot store
now raising ``AttributeError``) is closed STATICALLY by requiring the declared slot
tuple to be a SUPERSET of every attribute name stored on any instance of this class
across every module. Where a linter only FLAGS the opportunity, Apex WRITES it,
deterministically and for free.

The detection + minimal splice live in :mod:`app.execution.slots_synthesis`
(``add_slots``); this module only names it as a develop objective and registers
itself with the develop registry. UNLIKE the standard single-file objectives,
add-slots needs WHOLE-PROJECT context (the conservative closed-attribute
over-approximation spans EVERY module — tests and fixtures INCLUDED, via
``all_module_sources``, NOT the tests-excluding ``project_sources``), so — like
seal-final-method — its transform is a closure that gathers all the project's sources
as the mutation scan set before running the splice. Tests must be in scope because a
mock/fake that sets an off-slot attribute IS a real ``AttributeError`` under
``__slots__`` the pytest suite cannot fully cover — the same justification the @final
family documents for ``all_module_sources``. It still reuses the shared single-file
``plan_source_rewrite`` (refuse test/fixture + non-library files, read, run the
transform, record the one in-place rewrite with its original so the suite-gated apply
engine can roll it back). The transform ALSO REFUSES every class on the PUBLIC surface
— one listed in ``__all__``, or (with no ``__all__``) a top-level non-underscore class:
external (out-of-project) code may set a dynamic attribute on that published class the
project-own scan cannot see, which ``__slots__`` would turn into an ``AttributeError``
(a private / underscore-prefixed class, where the project scan is authoritative, is
still slotted). This is REFUSE-on-ambiguity (default-public): the plan layer already
filters true non-importable files, so any module reaching the transform is a real
importable one — including a PEP-420 NAMESPACE-package module with no ``__init__.py``.
The transform refuses (an honest no-op) a module with no slottable class: the class is
public-surface API, already declares ``__slots__``, has a non-``object`` base, is a
Protocol/ABC/Enum, has a class-attr/slot-name collision, stores an attribute outside
its proven field set anywhere, has a non-enumerable attribute set, has no instance
attributes, or the module does not parse.

``__slots__`` is ancient, so this lands on the 3.10 floor with NO version gate.
Deterministic, stdlib-only, zero-token, idempotent (a second run sees the
``__slots__`` it landed and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.freeze_dataclass import all_module_sources
from app.execution.objectives._base import register_module_objective
from app.execution.slots_synthesis import add_slots


def plan_add_slots(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the add-slots plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture, read,
    run the transform, record the one in-place rewrite with its original so the
    verified-apply engine can roll it back). The one twist over the standard
    single-file shape: its transform needs WHOLE-PROJECT context — the conservative
    closed-attribute over-approximation spans every module, tests and fixtures
    INCLUDED (via ``all_module_sources``), because an off-slot attribute set only in a
    test is a real ``AttributeError`` under ``__slots__`` the suite cannot cover — so
    the transform is a closure that, given the module's source, gathers all the
    project's sources and runs ``add_slots`` with that scan set. The public-surface
    refusal — every class on the PUBLIC surface (an ``__all__``-listed name, or, with
    no ``__all__``, a top-level non-underscore class) whose external dynamic-attribute
    setters the project-own scan cannot see — is enforced inside the transform from the
    module's own source. An empty plan means nothing to do here — no slottable class,
    or the module does not parse — a no-op, not a failure."""

    def _transform(source: str) -> str | None:
        sources = all_module_sources(project_root, module_rel, source)
        return add_slots(source, sources, refuse_public=True)

    return plan_source_rewrite(
        project_root, module_rel, "add_slots", _transform)


register_module_objective(
    "add-slots", plan_add_slots,
    operator="add_slots",
    description="add __slots__ to a closed-attribute class in {rel}",
)
