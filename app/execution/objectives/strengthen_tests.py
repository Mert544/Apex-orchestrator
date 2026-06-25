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

Scaling on BIG real files (the bounded-gap-finding fix): mutation testing pays a
full-project copytree + pytest run PER MUTANT, so the unbounded per-module scan
over a whole source index times out on a large project and lands an honest no-op
— help least exactly where a real project needs it most. This module bounds that
fan-out deterministically:

* a per-scan WORK BUDGET (a mutant-RUN COUNT, never a clock — see
  :class:`app.execution._verify_budget._Budget`) consumed in deterministic module
  order, so a scan can't blow past the harness limit;
* a size-aware mutant cap inside the transform (a pure function of the source);
* a cheap PRE-FILTER that spends the budget on the highest-yield modules first —
  a pure-AST static rank (covering-test count, blindly-callable public funcs) and,
  when an opt-in trace evidence is supplied, the
  :func:`app.engine.runtime_trace.trace_pytest` untested-body-line signal — so the
  budget LANDS assertions on the files that matter instead of timing out in
  alphabetical order.

On a SMALL project the default budget is never exhausted, so every qualifying
module is still visited and the landed assertion set is byte-identical to the
pre-budget behaviour — the budget only bounds large scans.

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` runs the FULL suite and restores the file on any
regression). The double gate is the never-fake-green proof: an emitted assertion
is one Apex has PROVEN both holds on the real code and would have caught a real
fault. If no survivor can be killed honestly, the objective REFUSES (lands
nothing); a module whose tests already kill every mutant is a no-op. The MODULE
target is never a test/fixture file. Deterministic, stdlib-only, zero-token.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution._verify_budget import _Budget
from app.execution.strengthen_tests import plan_strengthen_tests

# Default per-scan work budget for the strengthen-tests objective, in mutant-RUN
# COUNT (the unit that actually costs a copytree+pytest run). ~13 modules at 31
# runs each — comfortably under the external harness limit, so a big project
# LANDS assertions on its highest-yield modules instead of timing out and landing
# nothing. A COUNT, not a clock, so the same project always spends it the same
# way regardless of how fast each test runs. None would restore the old unbounded
# scan; this default is what makes the objective safe on large real files.
_DEFAULT_VERIFY_BUDGET = 400


def _candidate_modules(project_root: str | Path) -> list[tuple[str, str]]:
    """The own modules eligible to even be a strengthen-tests target, as
    ``(rel, source)`` in the source index's order. A packaging module
    (``__init__``/``__main__``) is dropped here (the transform refuses it anyway)
    so it never consumes a prefilter slot or a budget run."""
    from app.engine.objective_compiler import _own_modules

    out: list[tuple[str, str]] = []
    for rel, src in _own_modules(project_root):
        if not Path(rel).stem.startswith("__"):
            out.append((rel, src))
    return out


def _yield_rank(root: Path, rel: str, source: str,
                evidence=None) -> tuple[int, int, int, str]:
    """A deterministic descending-yield sort key for one module — higher-yield
    modules sort FIRST so a bounded budget is spent where survivors concentrate.

    The key is a pure function of the project's static shape (and the optional
    trace evidence), never a clock:

    * ``-untested`` — count of the module's blindly-callable public-function body
      lines NOT executed by the traced suite (only when ``evidence`` is supplied;
      0 otherwise). Survivors concentrate on untested lines, so an under-covered
      module is the richest mutation target — it sorts first.
    * ``-covering`` — number of test files that import the module. No covering
      test → the strengthen-tests double-gate can never fire, so such a module
      sorts last (and is skipped outright by :func:`_can_yield`).
    * ``-callable`` — number of top-level, blindly-callable public functions; a
      module with none can never produce a double-gated assertion.
    * ``rel`` — the path, as a final stable tie-break so the order is total.
    """
    from app.engine.mutation_tester import covering_test_files
    from app.execution.test_shield import _safe_functions

    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return (0, 0, 0, rel)
    callable_funcs = _safe_functions(tree)
    covering = covering_test_files(root, rel)
    untested = _untested_body_lines(root, rel, tree, callable_funcs, evidence)
    return (-untested, -len(covering), -len(callable_funcs), rel)


def _can_yield(root: Path, rel: str, source: str) -> bool:
    """True only when this module COULD land a double-gated assertion: it has at
    least one top-level, blindly-callable public function.

    This is the cheapest HARD prefilter and the only one safe to drop on:
    :func:`app.execution.strengthen_tests._survivor_assertions` gates every
    survivor through ``_safe_call``, so a module with NO such function can never
    produce an assertion regardless of its mutation result — it is skipped without
    ever paying a copytree. (Covering-test presence is NOT a hard drop: the
    mutation engine falls back to the full suite when nothing imports the module,
    so a covering test is a RANKING signal in :func:`_yield_rank`, never a filter
    — keeping the examined SET byte-identical to the unbounded scan whenever the
    budget is not exhausted.)"""
    try:
        from app.execution.test_shield import _safe_functions

        return bool(_safe_functions(ast.parse(source)))
    except (SyntaxError, RecursionError, MemoryError):
        return False


def _untested_body_lines(root: Path, rel: str, tree: ast.Module,
                         callable_funcs, evidence) -> int:
    """How many body lines of the module's blindly-callable public functions were
    NOT executed by the traced suite — the trace-derived gap signal.

    Zero when ``evidence`` is ``None`` (the trace prefilter is opt-in: the cheap
    static rank stands alone by default). Deterministic: it reads a fixed line-set
    out of an immutable :class:`app.engine.runtime_trace.RuntimeEvidence` (which
    "depends solely on which lines those tests run"), so the same evidence always
    yields the same count — no clock enters the ranking."""
    if evidence is None:
        return 0
    names = {name for name, _ in callable_funcs}
    body = _public_body_lines(tree, names)
    if not body:
        return 0
    executed = evidence.executed_lines(str(root / rel))
    return len(body - executed)


def _public_body_lines(tree: ast.Module, names: set[str]) -> frozenset[int]:
    """The set of body line numbers (header excluded) of every top-level function
    in ``names`` — the lines that run only when the function is exercised, which
    is where a surviving mutant hides. Deterministic, pure-AST."""
    lines: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in names:
            continue
        for stmt in node.body:
            end = stmt.end_lineno or stmt.lineno
            lines.update(range(stmt.lineno, end + 1))
    return frozenset(lines)


def _ranked_modules(project_root: str | Path, evidence=None) -> list[tuple[str, str]]:
    """The yield-can't-be-zero candidate modules, sorted highest-yield first.

    Deterministic order (``sorted`` over a total key), so the SAME project always
    spends a bounded budget on the SAME modules in the SAME order — independent of
    how fast each test runs. ``evidence`` (optional) folds the trace untested-line
    signal into the rank; without it the cheap static rank stands."""
    root = Path(project_root)
    eligible = [(rel, src) for rel, src in _candidate_modules(project_root)
                if _can_yield(root, rel, src)]
    return sorted(eligible, key=lambda rs: _yield_rank(root, rs[0], rs[1], evidence))


def _modules(project_root: str | Path, budget: _Budget | None = None,
             evidence=None) -> list[str]:
    """Own modules that strengthen-tests would land an assertion on, in
    yield-priority order, bounded by ``budget``.

    The single chokepoint for the bounded scan: candidate modules are ranked
    highest-yield first (:func:`_ranked_modules`) and visited in that fixed order,
    each spending the shared mutant-run ``budget``. Once the budget is exhausted
    the remaining modules are simply NOT visited this scan — and because the order
    is deterministic and the budget is an integer count, the set of modules
    examined is byte-identical across machines. ``budget is None`` restores the
    unbounded scan (every qualifying module visited); the default caller passes a
    fresh :data:`_DEFAULT_VERIFY_BUDGET` budget so a big project stays under the
    harness limit while a small one (never exhausting it) is unchanged."""
    out: list[str] = []
    for rel, _src in _ranked_modules(project_root, evidence):
        if budget is not None and budget.exhausted:
            break  # work budget spent — remaining modules left unvisited this scan
        if plan_strengthen_tests(project_root, rel, budget=budget).new_contents:
            out.append(rel)
    return out


def _scan(project_root: str | Path) -> list[str]:
    """One budgeted scan with a FRESH default budget — the shared entry both
    ``fitness`` and ``moves`` use so they see the same bounded module set. A fresh
    budget per scan keeps the count deterministic (same project → same spend)."""
    return _modules(project_root, budget=_Budget(_DEFAULT_VERIFY_BUDGET))


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a surviving mutant we can kill,
    within the per-scan work budget.

    A module counts only when strengthen-tests would land at least one
    double-gated killing assertion for it — a module with no survivors, or whose
    survivors can't be killed with an honest oracle, does NOT count (we refuse to
    touch it), so it never appears as remaining debt. The bounded scan keeps the
    probe tractable on a big project (it no longer times out into an honest
    no-op); on a small project the budget is never exhausted, so the count is the
    same as the unbounded scan. An honest measure."""
    return float(len(_scan(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="strengthen_tests",
        target=f"{rel}:strengthen-tests",
        description=f"add mutant-killing assertions for {rel}",
        build_plan=lambda r=rel: plan_strengthen_tests(project_root, r),
    ) for rel in _scan(project_root)]


# Each fitness probe runs the mutation engine (the project's tests once per
# mutant in an isolated copy) over the budgeted set of own modules — heavyweight,
# exactly like implement-stub's per-candidate suite runs. Flag it expensive so the
# fast plan/ascend board skips it (it stays runnable via
# `apex develop --objective strengthen-tests`). The bounded budget keeps a single
# scan under the harness limit even on a large project.
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
