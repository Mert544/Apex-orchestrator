"""Shared primitives for the dedup / near-dup extract transforms.

:mod:`app.execution.dedup_extract`, :mod:`app.execution.dedup_total_return`, and
:mod:`app.execution.near_dup_extract` each build a multi-module
:class:`~app.execution.cross_file_rename.RenamePlan` and finish by stamping the
SAME five fields onto it. That finalise tail was byte-identical across the three
transforms (the duplication detector flagged it as a shared 5-statement window),
so it lives here once and every transform calls it.

This is a **library** (leading underscore in the filename) — it is never an
objective and exposes no ``plan_*`` entry point. It imports nothing from the
transforms (only the plan type it stamps), so it can never form an import cycle
with them. Deterministic and stdlib-only — no time, no randomness.
"""

from __future__ import annotations

from app.execution.extract_method import _enclosing_function

__all__ = ["stamp_multi_module_plan", "resolve_occurrence_prefix"]


def stamp_multi_module_plan(
    plan: object,
    helper_name: str,
    defined_in: str,
    sources: dict,
    new_contents: dict,
    edits: dict,
) -> object:
    """Stamp a completed multi-module helper-extraction onto ``plan`` and return it.

    The byte-identical finalise tail the dedup / near-dup extract transforms each
    carried verbatim: record the new helper's name (``plan.new``) and defining
    module (``plan.defined_in``), snapshot the original source of every changed
    module (``plan.originals = {rel: sources[rel] for rel in new_contents}``), and
    store the rewritten contents and per-file edit counts. ``defined_in`` is taken
    as an argument because that is the only token that varied between call sites,
    so the body stays identical to every inlined copy. ``plan`` only needs those
    mapping / scalar attributes, keeping this decoupled from any concrete plan
    type; returning ``plan`` lets a caller continue with its own follow-up (e.g. a
    warning)."""
    plan.new = helper_name
    plan.defined_in = defined_in
    plan.originals = {rel: sources[rel] for rel in new_contents}
    plan.new_contents = new_contents
    plan.edits_by_file = edits
    return plan


def resolve_occurrence_prefix(plan, rel, start_line, n_statements, sources,
                              trees, locate_run):
    """The byte-identical occurrence-resolution PREFIX shared by the dedup-extract
    and dedup-total-return resolve helpers, lifted here once.

    Given a ``module:lineno`` occurrence, this performs the three admissibility
    steps both transforms do verbatim BEFORE their control-flow checks diverge:
      1. require the module to be a readable project module (``rel in trees``);
      2. locate the single enclosing top-level function/method body;
      3. snap the block to a contiguous run of ``n_statements`` complete
         statements (via the caller-supplied ``locate_run``).

    On success returns ``(source, fn, container, run)`` — the common intermediate
    values each caller's divergent tail continues with. On any unsafe / ambiguous
    case it appends the SAME blocker string the inlined copies emitted and returns
    ``None``. ``locate_run`` is passed in (rather than imported) so this library
    never imports a transform module — no import cycle. Deterministic, stdlib-only.
    """
    if rel not in trees:
        plan.blockers.append(f"{rel}: not a readable project module")
        return None
    tree = trees[rel]
    source = sources[rel]

    fn, container = _enclosing_function(tree, start_line, start_line)
    if fn is None:
        plan.blockers.append(
            f"{rel}:{start_line}: occurrence isn't inside one top-level "
            "function/method body (closures aren't supported)")
        return None

    run = locate_run(fn, start_line, n_statements)
    if not run:
        plan.blockers.append(
            f"{rel}:{start_line}: couldn't snap the block to a contiguous run "
            f"of {n_statements} complete statements")
        return None

    return source, fn, container, run
