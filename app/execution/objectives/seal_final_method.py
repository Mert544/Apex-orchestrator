"""Self-registering objective: seal-final-method.

Land ``@typing.final`` on a project's own METHOD that is PROVABLY never overridden
anywhere in the project — the method-level sibling of add-final's class-level seal.
``@typing.final`` on a method is a PURE runtime no-op (it only records intent and is
consulted by type checkers), so the change is behaviour-preserving BY CONSTRUCTION;
the only honesty risk — a false "final" on a method that IS overridden — is closed
STRUCTURALLY by a whole-project over-approximate, transitive subclass scan, not by
the suite. Where a linter only FLAGS the opportunity, Apex WRITES it,
deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.final_method`
(``add_final_method_decorator``); this module only names it as a develop objective
and registers itself with the develop registry. UNLIKE the standard single-file
objectives, seal-final-method needs WHOLE-PROJECT context (the conservative
subclass over-approximation spans EVERY module — tests and fixtures INCLUDED, via
``all_module_sources``, NOT the tests-excluding ``project_sources``), so — like
add-final — its transform is a closure that gathers all the project's sources as
the subclass scan set before running the marker. Tests must be in scope because
``@typing.final`` is a pure runtime no-op: a method overridden ONLY in a test (a
mock / fake) is a REAL override a TYPE CHECKER rejects once the method is sealed,
yet the pytest suite can NEVER catch that false "final" — so excluding tests would
silently mis-seal it. It still reuses the shared single-file ``plan_source_rewrite``
(refuse test/fixture, read, run the transform, record the one in-place rewrite with
its original so the suite-gated apply engine can roll it back). The transform ALSO
REFUSES every method of a PUBLIC-surface CLASS — one listed in ``__all__``, or (with
no ``__all__``) a top-level non-underscore class: external (out-of-project) code may
subclass that published class and override the method, which ``@final`` would make a
type checker reject, and the project-own scan cannot see such a subclass (a method of
a private / underscore-prefixed class, where the project scan is authoritative, is
still sealed). This is REFUSE-on-ambiguity (default-public): the plan layer already
filters true non-importable files, so any module reaching the transform is a real
importable one — including a PEP-420 NAMESPACE-package module with no ``__init__.py``.
The transform refuses (an honest no-op) a module with no sealable method: the
method's class is public-surface API, the method is overridden in a potential
subclass (incl. via a dotted/subscripted base, transitively), already ``@final``, a
dunder, a property/staticmethod/classmethod/overload/abstractmethod, a method of a
Protocol/ABC class, the name ``final`` cannot be bound unambiguously to
``typing.final``, or the module does not parse.

``typing.final`` exists since Python 3.8, so this lands on the 3.10 floor with NO
version gate. Deterministic, stdlib-only, zero-token, idempotent (a second run sees
the ``@final`` it landed and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.final_method import add_final_method_decorator
from app.execution.freeze_dataclass import all_module_sources
from app.execution.objectives._base import register_module_objective


def plan_seal_final_method(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the seal-final-method plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run the transform, record the one in-place rewrite with its original so
    the verified-apply engine can roll it back). The one twist over the standard
    single-file shape: its transform needs WHOLE-PROJECT context — the conservative
    subclass over-approximation spans every module, tests and fixtures INCLUDED (via
    ``all_module_sources``), because a method overridden only in a test is a real
    override a type checker rejects once it is sealed — so the transform is a
    closure that, given the module's source, gathers all the project's sources and
    runs ``add_final_method_decorator`` with that scan set. The public-surface
    refusal — every method of a PUBLIC class (an ``__all__``-listed name, or, with no
    ``__all__``, a top-level non-underscore class) whose external subclassers the
    project-own scan cannot see — is enforced inside the transform from the module's
    own source. An empty plan means nothing to do here — no sealable method, or the
    module does not parse — a no-op, not a failure."""

    def _transform(source: str) -> str | None:
        sources = all_module_sources(project_root, module_rel, source)
        return add_final_method_decorator(source, sources, refuse_public=True)

    return plan_source_rewrite(
        project_root, module_rel, "seal_final_method", _transform)


register_module_objective(
    "seal-final-method", plan_seal_final_method,
    operator="seal_final_method",
    description="seal @final on a never-overridden method in {rel}",
)
