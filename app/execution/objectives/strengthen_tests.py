"""Self-registering objective: strengthen-tests.

For a module that HAS tests but whose tests miss a branch, generate an
additional PASSING assertion that KILLS a specific surviving mutant — landing
real new test code that pins behaviour the current suite lets through.

The pipeline (run the mutation engine to find survivors, capture the real output
of the unmutated function on synthesized inputs, and keep only DOUBLE-GATED
assertions that pass on real code AND fail against the recorded mutant) lives in
:mod:`app.execution.strengthen_tests`; this module names it as a develop
objective, builds the one-module plan, and registers itself with the develop
registry.

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` runs the FULL suite and restores the file on any
regression). The double gate is the never-fake-green proof: an emitted assertion
is one Apex has PROVEN both holds on the real code and would have caught a real
fault. If no survivor can be killed honestly, the objective REFUSES (lands
nothing); a module whose tests already kill every mutant is a no-op. The MODULE
target is never a test/fixture file. Deterministic, stdlib-only, zero-token.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.strengthen_tests import plan_strengthen_tests


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules

    return [rel for rel, _src in _own_modules(project_root)
            if plan_strengthen_tests(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a surviving mutant we can kill.

    A module counts only when strengthen-tests would land at least one
    double-gated killing assertion for it — a module with no survivors, or whose
    survivors can't be killed with an honest oracle, does NOT count (we refuse to
    touch it), so it never appears as remaining debt. An honest measure."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="strengthen_tests",
        target=f"{rel}:strengthen-tests",
        description=f"add mutant-killing assertions for {rel}",
        build_plan=lambda r=rel: plan_strengthen_tests(project_root, r),
    ) for rel in _modules(project_root)]


# Each fitness probe runs the mutation engine (the project's tests once per
# mutant in an isolated copy) over every own module — heavyweight, exactly like
# implement-stub's per-candidate suite runs. Flag it expensive so the fast
# plan/ascend board skips it (it stays runnable via
# `apex develop --objective strengthen-tests`).
#
# scope_verify=True: strengthen-tests has the same multi-module red-baseline
# deadlock implement-stub / tdd-implement opt out of. On a project where several
# OTHER modules still hold unimplemented stubs, the FULL suite is RED at baseline.
# A correct strengthen-tests landing only APPENDS a double-gated mutant-killing
# assertion to ONE module's TEST file; gated by the whole suite, that correct
# change would be vetoed and rolled back by an unrelated still-red module. Because
# the change IS to a test file, ``impacted_test_files`` includes that changed test
# file directly, so impact-scoping runs exactly the appended assertion's own tests
# (which genuinely pass after the landing, keeping the "verified" stamp honest)
# and skips the unrelated red modules. The full suite stays the commit-time
# backstop (``scripts/verify.py``), so never-fake-green holds.
register(ObjectiveSpec(name="strengthen-tests", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
