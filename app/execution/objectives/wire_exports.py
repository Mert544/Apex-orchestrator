"""Self-registering objective: wire-exports.

The boilerplate every student and team writes by hand: a package whose
``__init__.py`` is empty re-exporting its modules' public symbols so
``from pkg import X`` works. ``wire-exports`` LANDS that ``__init__.py`` —
deterministically generated ``from .module import Name`` re-exports plus a
complete sorted ``__all__`` for every PUBLIC top-level symbol across the
package's modules.

The pure analysis lives in :mod:`app.execution.export_wiring`
(``plan_init_text``); this module names it as a develop objective, gates it with
an IMPORT ORACLE, and registers itself with the develop registry.

The import oracle is the distinctive safety here: BEFORE the change is allowed to
stand, the candidate ``__init__.py`` is written to a throwaway copy of the
package and imported in a clean subprocess, asserting that EVERY name in the new
``__all__`` resolves as an attribute of the package. If the import fails or any
export doesn't resolve, the objective REFUSES — landing nothing. That makes
wire-exports trustworthy even on a project with NO test suite (its safety does
not depend on a detectable suite); where a suite exists, ``apply_rename``'s
full-suite gate composes on top with byte-for-byte rollback. Deterministic
(sorted, no clock/random), stdlib-only, zero-token, idempotent (a fully-exported
package is a byte-identical no-op), and it refuses test/fixture packages.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.export_wiring import plan_init_text
from app.execution.import_oracle import exports_resolve


def plan_wire_exports(project_root: str | Path, init_rel: str) -> RenamePlan:
    """Build the wire-exports plan for one package ``__init__.py``, or a no-op.

    Computes the candidate ``__init__.py`` (sorted re-exports + ``__all__``), then
    gates it through the import oracle: the candidate must import cleanly and every
    name in its ``__all__`` must resolve as a package attribute. A package that is
    already fully wired, a refused test/fixture package, or a candidate that fails
    the oracle all yield an EMPTY plan — an honest no-op refusal, never a guess.
    The single write goes in ``new_contents`` with the original in ``originals`` so
    the verified-apply engine can roll it back if a project suite regresses."""
    plan = RenamePlan(old=init_rel, new="wire-exports")
    root = Path(project_root)
    candidate, wire = plan_init_text(root, init_rel)
    if candidate is None:
        return plan  # refused, or already fully exported (idempotent no-op)

    expected = sorted(wire.exports)
    if not expected:
        return plan  # nothing public to export
    if not exports_resolve(root, init_rel, candidate, expected):
        return plan  # the import oracle refused — land nothing

    try:
        original = (root / init_rel).read_text(encoding="utf-8")
    except OSError:
        original = ""
    plan.originals[init_rel] = original
    plan.new_contents[init_rel] = candidate
    plan.edits_by_file[init_rel] = len(expected)
    return plan


def _package_inits(project_root: str | Path) -> list[str]:
    """Every wireable ``__init__.py`` (one per package) whose plan would change
    something — the targets the objective offers. Sorted for determinism."""
    from app.engine.skip_dirs import is_skipped, is_test_or_fixture_path

    root = Path(project_root)
    out: list[str] = []
    for path in sorted(root.rglob("__init__.py")):
        rel = path.relative_to(root)
        if is_skipped(rel) or is_test_or_fixture_path(rel.parent):
            continue
        if plan_wire_exports(root, rel.as_posix()).new_contents:
            out.append(rel.as_posix())
    return out


def fitness(project_root: str | Path) -> float:
    """Fitness = how many packages still have an unwired public surface.

    A package counts only when its candidate ``__init__.py`` passes the import
    oracle (every export resolves) — a package we cannot safely wire never appears
    as remaining debt, an honest measure."""
    return float(len(_package_inits(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="wire_exports",
        target=f"{rel}:wire-exports",
        description=f"wire public re-exports + __all__ in {rel}",
        build_plan=lambda r=rel: plan_wire_exports(project_root, r),
    ) for rel in _package_inits(project_root)]


# The fitness scan imports each candidate package in a subprocess (the oracle),
# so it is heavyweight — flag it expensive so the fast plan/ascend board skips it
# (it stays runnable explicitly via `apex develop --objective wire-exports`).
register(ObjectiveSpec(name="wire-exports", fitness=fitness, moves=moves,
                       expensive=True))
