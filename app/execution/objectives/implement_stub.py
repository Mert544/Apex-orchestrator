"""Self-registering objective: implement-stub.

The single highest-value concrete contribution for a budget-limited student:
take a function that is a STUB (``raise NotImplementedError``, a bare
``...``/``pass`` body, or empty-with-``# TODO: implement``) whose contract is
ALREADY pinned by the project's tests, and DETERMINISTICALLY synthesise a body
that makes ALL of that function's tests pass — landing real, working code.

This is the gap every other objective leaves open: they make EXISTING code
cleaner; this makes UNFINISHED code finished. The synthesis logic (stub
detection, pinned-test discovery, the fixed template space, and the inner
per-function gate) lives in :mod:`app.execution.stub_synthesis`; this module
names it as a develop objective, builds the one-module plan, and registers
itself with the develop registry.

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` runs the FULL suite and restores the file on any
regression). The tests are the spec: a body is emitted ONLY after it already
passes the function's pinned tests; if no fixed template passes, the objective
REFUSES (lands nothing) — never a guess, never a fake-green. Test/fixture files
are refused outright. Deterministic, stdlib-only, zero-token, idempotent (a
non-stub is untouched).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.stub_synthesis import (
    find_stub_functions,
    pinned_test_files,
    synthesize_stub_body,
)


def plan_implement_stub(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the implement-a-stub plan for one module, or an empty no-op plan.

    Finds the first stub in ``module_rel`` (source order) whose pinned tests a
    fixed template can satisfy, and emits that synthesized module text. An empty
    plan means nothing was implementable here — a no-op refusal, not a failure.
    Test/fixture files are refused outright. The single write goes in
    ``new_contents`` with the original in ``originals`` so the verified-apply
    engine can roll it back if the full suite regresses."""
    plan = RenamePlan(old=module_rel, new="implement-stub")
    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    root = Path(project_root)
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    stubs = find_stub_functions(source)
    if not stubs:
        return plan  # nothing unfinished here — no-op (idempotent)

    for stub in stubs:
        tests = pinned_test_files(root, module_rel, stub.name)
        if not tests:
            continue  # no spec to satisfy — refuse this stub
        new_source = synthesize_stub_body(root, module_rel, stub, tests)
        if new_source is None or new_source == source:
            continue  # no fixed template passed — refuse this stub
        plan.originals[module_rel] = source
        plan.new_contents[module_rel] = new_source
        plan.edits_by_file[module_rel] = 1
        return plan  # one implementable stub per plan — the engine re-derives

    return plan  # every stub refused — honest empty plan


def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (a local copy on purpose: this objective stays self-contained)."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules

    return [rel for rel, _src in _own_modules(project_root)
            if plan_implement_stub(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still hold an implementable stub.

    Implementable = a stub whose pinned tests a fixed template can satisfy. A
    stub with no tests or an unsatisfiable contract does NOT count (we refuse to
    touch it), so it never appears as remaining debt — an honest measure."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="implement_stub",
        target=f"{rel}:implement-stub",
        description=f"implement a tested stub in {rel}",
        build_plan=lambda r=rel: plan_implement_stub(project_root, r),
    ) for rel in _modules(project_root)]


# Synthesis runs the project's tests once per candidate template, so the fitness
# scan is heavyweight — flag it expensive so the fast plan/ascend board skips it
# (it stays runnable explicitly via `apex develop --objective implement-stub`).
register(ObjectiveSpec(name="implement-stub", fitness=fitness, moves=moves,
                       expensive=True))
