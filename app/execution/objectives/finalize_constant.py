"""Self-registering objective: finalize-module-constant.

Land ``typing.Final`` on a project's own top-level module CONSTANT
(``NAME = <literal>``) that is PROVABLY never REBOUND anywhere in the project — the
immutability-contract intent a careful author annotates by hand, paying down a
``pylint`` invalid-name / const-reassignment finding. ``typing.Final`` is a PURE
runtime no-op (CPython does not enforce it — it is a type-checker-only marker), so
the change is behaviour-preserving BY CONSTRUCTION; the only honesty risk — a false
"final" on a name that IS rebound — is closed STRUCTURALLY by a whole-project
over-approximate rebind scan, not by the suite. This is the Python analogue of the
shipped ``add-final`` (class ``@final``) / ``java-final-local`` family; UNLIKE a
``let``->``const`` rewrite (which THROWS at runtime if wrong), a wrong ``Final`` is
still a runtime no-op, so it is sound with the AST/reparse oracle. Where a linter
only FLAGS the opportunity, Apex WRITES it, deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.final_constant`
(``add_final_constant``); this module only names it as a develop objective and
registers itself with the develop registry. UNLIKE the standard single-file
objectives, finalize-module-constant needs WHOLE-PROJECT context (the conservative
rebind over-approximation spans EVERY module — tests and fixtures INCLUDED, via
``all_module_sources``, NOT the tests-excluding ``project_sources``), so its
transform is a closure that gathers all the project's sources as the rebind scan set
before running the marker. Tests must be in scope because ``typing.Final`` is a pure
runtime no-op: a constant REBOUND only in a test (a monkeypatch-by-assignment, a
fixture reset) is a REAL reassignment a TYPE CHECKER rejects once the name is
``Final``, yet the pytest suite can NEVER catch that false "final" — so excluding
tests would silently mis-seal it. It still reuses the shared single-file
``plan_source_rewrite`` (refuse test/fixture, read, run the transform, record the one
in-place rewrite with its original so the suite-gated apply engine can roll it back).

The transform refuses (an honest no-op) a module with no finalizable constant: the
name is REBOUND anywhere in the project (a later ``NAME = ...``, an annotated
``NAME: T = ...``, an augmented ``NAME += ...``, a ``for`` / ``with as`` / walrus
target, a ``def`` / ``class`` / parameter of that name, an import binding, or a
``global NAME`` inside a function — tests INCLUDED); already ``Final`` /
``typing.Final``; not a top-level ``NAME = <literal>`` UPPER_SNAKE constant (inside a
function / class, a tuple-unpack / multi-target, an annotation-only ``NAME: T``, or a
non-literal value); or the name ``Final`` cannot be bound unambiguously to
``typing.Final``. A name whose value is MUTATED IN PLACE (``NAMES.append(...)`` /
``NAMES[k] = ...``) is FINE — ``Final`` forbids REBINDING, not mutation — so an
attribute / subscript store on the constant is never a refusal.

``typing.Final`` exists since Python 3.8, so this lands on the 3.10 floor with NO
version gate. Deterministic, stdlib-only, zero-token, idempotent (a second run sees
the ``Final`` it landed and is a byte-identical no-op, then moves to the next
candidate).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.final_constant import add_final_constant
from app.execution.freeze_dataclass import all_module_sources
from app.execution.objectives._base import register_module_objective


def plan_finalize_constant(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the finalize-module-constant plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run the transform, record the one in-place rewrite with its original so
    the verified-apply engine can roll it back). The one twist over the standard
    single-file shape: its transform needs WHOLE-PROJECT context — the conservative
    rebind over-approximation spans every module, tests and fixtures INCLUDED (via
    ``all_module_sources``), because a constant rebound only in a test is a real
    reassignment a type checker rejects once the name is ``Final`` — so the transform
    is a closure that, given the module's source, gathers all the project's sources
    and runs ``add_final_constant`` with that rebind scan set. An empty plan means
    nothing to do here — no finalizable constant, or the module does not parse — a
    no-op, not a failure."""

    def _transform(source: str) -> str | None:
        sources = all_module_sources(project_root, module_rel, source)
        return add_final_constant(source, sources)

    return plan_source_rewrite(
        project_root, module_rel, "finalize_module_constant", _transform)


register_module_objective(
    "finalize-module-constant", plan_finalize_constant,
    operator="finalize_module_constant",
    description="add typing.Final to a module constant in {rel}",
)
