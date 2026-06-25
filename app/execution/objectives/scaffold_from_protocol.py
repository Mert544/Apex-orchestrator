"""Self-registering objective: scaffold-from-protocol.

The honest gap this closes: a project declares a ``typing.Protocol`` — the shared
interface a function depends on — but NO concrete class satisfies it yet, so
``PImpl()`` is impossible and the interface is shelf-ware. ``scaffold-from-protocol``
LANDS the missing implementer: a NEW file ``<pkgdir>/<stem>_impl.py`` holding
``class <P>Impl(<P>):`` with one ``...``-bodied override per FILLABLE member
(abstract / unimplemented), decorators preserved (``@abstractmethod`` dropped) and
annotations stripped — the runnable skeleton a person then fills in, for free.

The pure AST detect + render + the instantiation oracle live in
:mod:`app.execution.protocol_scaffold`; this module names them as a develop
objective, gates the candidate, and registers itself. The contribution is a NEW
file (additive — it never edits the protocol module or the suite); the original
(existing-or-``""``) goes in ``originals`` so the verified-apply engine can roll the
create back.

Two gates keep it never-fake-green (mirrored on ``wire-exports``):

  1. an INSTANTIATION ORACLE — the candidate is written to a throwaway copy and
     ``<P>Impl()`` is constructed in a CLEAN subprocess; if a fillable member was
     missed, Python raises ``TypeError: Can't instantiate abstract class`` and the
     oracle refuses (a partial scaffold is never landed);
  2. ``apply_rename``'s full-suite gate + byte-for-byte rollback (the engine
     blesses a CREATED file and deletes it on rollback).

It REFUSES (an honest under-claim, lands nothing) when the class is not a
Protocol, is a marker protocol (zero fillable members), already has a concrete
implementer (an explicit ``class C(P)`` subclass anywhere, or ``<P>Impl`` present),
the Protocol base is alias-imported (a conservative miss), the target is a
test/fixture file, or the source is unreadable / the candidate fails the oracle.

The fitness scan instantiates each candidate in a subprocess (the oracle), so the
objective is flagged ``expensive`` — the fast plan/ascend board skips it; it stays
runnable explicitly via ``apex develop --objective scaffold-from-protocol``.
Deterministic (members in source order, pure AST → text), stdlib-only, zero-token,
idempotent (once ``<stem>_impl.py`` exists with the subclass, a second run is a
byte-identical no-op).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan, _is_fixture_path
from app.execution.protocol_scaffold import (
    protocol_scaffolds,
    render_protocol_impl,
    scaffold_instantiates,
)
from app.execution.stub_synthesis import _module_dotted_paths


def _impl_rel(module_rel: str, protocol: str) -> str:
    """The ``<pkgdir>/<stem>_impl.py`` path for ``module_rel`` (a sibling of the
    protocol module, in its own package directory)."""
    path = Path(module_rel)
    return (path.parent / f"{path.stem}_impl.py").as_posix()


def _dotted_pair(root: Path, module_rel: str) -> tuple[str, str] | None:
    """``(source_dotted, impl_dotted)`` for ``module_rel``: the protocol module's
    importable dotted path (for the scaffold's ``from <source> import <P>`` line)
    and the impl sibling's dotted path (``<source>_impl``, for the oracle to
    import). ``None`` when the module has no importable name (cannot generate a
    runnable scaffold). The first (sorted, deterministic) dotted path is used,
    matching the impl file's physical location under the same package."""
    dotted_paths = _module_dotted_paths(root, module_rel)
    if not dotted_paths:
        return None
    source_dotted = dotted_paths[0]
    return source_dotted, source_dotted + "_impl"


def plan_scaffold_from_protocol(project_root: str | Path,
                                module_rel: str) -> RenamePlan:
    """Build the scaffold-from-protocol plan for one module, or an honest no-op.

    CREATES ``<pkgdir>/<stem>_impl.py`` implementing the FIRST qualifying Protocol
    in ``module_rel`` (a Protocol subclass with >=1 fillable member and no existing
    concrete implementer). The candidate must pass the instantiation oracle —
    ``<P>Impl()`` constructs in a clean subprocess — before it is offered; a
    still-abstract scaffold (a missed member) is refused. An EMPTY plan (a no-op
    refusal) results for a test/fixture file, an unreadable module, no qualifying
    protocol, a module with no importable name, a candidate that will not
    ``ast.parse``, or a candidate the oracle rejects. Idempotent: once the impl
    file exists with the subclass, ``protocol_scaffolds`` sees the implementer and
    yields nothing."""
    root = Path(project_root)
    plan = RenamePlan(old=module_rel, new="scaffold-from-protocol")
    if _is_fixture_path(module_rel):
        return plan  # never scaffold from a test/fixture file
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    scaffolds = protocol_scaffolds(root, module_rel, source)
    if not scaffolds:
        return plan  # no unimplemented protocol here — honest under-claim
    pair = _dotted_pair(root, module_rel)
    if pair is None:
        return plan  # no importable name — cannot generate a runnable scaffold
    source_dotted, impl_dotted = pair

    protocol, members = scaffolds[0]
    candidate = render_protocol_impl(source_dotted, protocol, members)
    try:
        ast.parse(candidate)  # never ship un-parseable scaffold source
    except (SyntaxError, ValueError):
        return plan

    impl_rel = _impl_rel(module_rel, protocol)
    if not scaffold_instantiates(root, impl_rel, candidate, impl_dotted,
                                 f"{protocol}Impl"):
        return plan  # the instantiation oracle refused — land nothing

    try:
        original = (root / impl_rel).read_text(encoding="utf-8")
    except OSError:
        original = ""
    if candidate == original:
        return plan  # already scaffolded — byte-identical no-op (idempotent)

    plan.originals[impl_rel] = original
    plan.new_contents[impl_rel] = candidate
    plan.edits_by_file[impl_rel] = len(members)
    # The created impl is DERIVED FROM the protocol source module: it is
    # ``class <P>Impl(<P>)`` importing ``<P>`` from ``module_rel``. The impl file
    # itself has no importing test yet (it never existed), so the impact-scope
    # gate would degrade to the FULL suite — and on a multi-module RED baseline an
    # unrelated still-red module would veto this oracle-proven scaffold. Carrying
    # the protocol module as the derived-from source seeds the scope from the
    # tests that exercise the protocol — precisely the tests that exercise the
    # concrete implementer once it is wired in — so the scaffold is regression-
    # gated honestly instead of deadlocked. A fixed echo of ``module_rel`` (a
    # field SEPARATE from ``new_contents``), so the determinism harness — which
    # hashes only ``new_contents`` — stays byte-identical.
    plan.derived_from = [module_rel]
    return plan


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules

    return [rel for rel, _src in _own_modules(project_root)
            if plan_scaffold_from_protocol(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still declare an unimplemented Protocol the
    scaffold could safely land (each candidate proven to instantiate by the
    oracle), an honest measure of remaining interface debt."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="scaffold_from_protocol",
        target=f"{rel}:scaffold-from-protocol",
        description=f"scaffold a concrete implementer for the protocol in {rel}",
        build_plan=lambda r=rel: plan_scaffold_from_protocol(project_root, r),
    ) for rel in _modules(project_root)]


# The fitness scan instantiates each candidate scaffold in a subprocess (the
# oracle), so it is heavyweight — flag it expensive so the fast plan/ascend board
# skips it (it stays runnable via `apex develop --objective scaffold-from-protocol`).
# scope_verify=True: the created ``<stem>_impl.py`` has no importing test yet, but
# the plan carries the protocol module in ``derived_from`` (set above), so the
# impact-scope gate seeds the scope from the PROTOCOL module's real importing tests
# instead of degrading to the full suite. On a multi-module RED baseline an
# unrelated still-red module therefore can no longer veto this oracle-proven
# scaffold. The instantiation oracle (protocol_scaffold.scaffold_instantiates)
# remains the INDEPENDENT correctness proof run BEFORE apply; the impact-scoped
# suite is a pure-additive regression backstop, and the FULL suite stays the
# commit-time backstop (``scripts/verify.py``). Listed in the audited
# SCOPE_VERIFY_ALLOWLIST (app/engine/soundness_audit.py).
register(ObjectiveSpec(name="scaffold-from-protocol", fitness=fitness,
                       moves=moves, expensive=True, scope_verify=True))
