"""Dedup Guarded-Return — lift an exact-duplicate block with guard returns AND
a live fall-through, via sentinel projection.

The dedup family's control-flow ladder, completed. Each rung admits exactly the
shape its siblings refuse, so the three transforms never contend for a block:

- :mod:`app.execution.dedup_extract` — a run with NO ``return`` (plain block)
  or a single TAIL ``return``;
- :mod:`app.execution.dedup_total_return` — a run whose EVERY exit path
  ``return``s / ``raise``s (control can never fall off its end);
- THIS — a run with at least one ``return`` on SOME path and a REACHABLE
  fall-through (``_always_returns`` is False): the guard-prelude shape
  (`if bad: return ...` then keep computing) both siblings refuse. This is the
  single biggest slice of the "detect >> act" dedup gap the total-return
  diagnosis left open — Apex's own A+100 debt block (the param_add/param_drop
  definition-resolution seam) was exactly this shape and needed a human.

HOW: sentinel projection. The run lifts VERBATIM into a module-level helper
whose appended last line returns a fresh, unforgeable module-level sentinel
(``_X_MISS = object()``). Each copy becomes a guard on that sentinel:

    live_out == []:                      live_out == [a, b]:
        _res = _helper(<live_in>)            _res = _helper(<live_in>)
        if _res is not _X_MISS:              if not (type(_res) is tuple and
            return _res                              len(_res) == 2 and
                                                     _res[0] is _X_MISS):
                                                 return _res
                                             a, b = _res[1]

Behaviour-preserving by cases: a path that returned V (ANY value, including
None or a user tuple — V can never be the fresh sentinel, nor a 2-tuple whose
head IS the sentinel) now returns V from the helper and the caller returns V
exactly as before; the fall-through path reaches the appended sentinel line,
the caller's guard skips (rebinding the projected locals when there are any),
and control continues into the statements after the run — or falls off the
function end to the same implicit None. A ``raise`` propagates unchanged
through the call. A bare ``return`` maps to None → not the sentinel → the
caller returns None, as the original did.

RAILS (any miss records a blocker; correctness over coverage, absolutely):
- the run must contain a ``return`` but NOT always-return (the siblings' turf);
- no ``yield`` / ``await`` / ``global`` / ``nonlocal`` (relocation changes
  control flow), no nested ``def``/``lambda`` (unanalyzable scope), no
  ``break``/``continue`` escaping the run;
- no ``super`` / ``__class__`` reference — a module-level helper has no class
  cell, so zero-arg ``super()`` would break at runtime while still re-parsing;
- no ``del`` — it voids the definite-assignment argument below;
- every LIVE-IN name must ALSO be DEFINITELY bound BEFORE the run even starts
  (a parameter, or a direct top-level prelude assignment — W99b-fix): the
  call site evaluates every live-in name EAGERLY, so a name only
  conditionally bound in the prelude could raise ``UnboundLocalError`` on a
  guard path where the original never reached the read at all;
- every live-out name must be DEFINITELY assigned when the run falls through
  (bound by a direct, top-level assignment statement of the run) — otherwise
  the helper's projection line could raise ``UnboundLocalError`` on a path
  where the original never read the name; a LIVE-IN name that is definitely
  bound BEFORE the run (a parameter, or a direct top-level prelude
  assignment) also counts (W100): it enters the helper as an always-bound
  parameter, so even a conditional in-run rebind leaves the projection safe;
- identical live-in AND live-out signatures across all copies;
- the FAMILY rails (shared via :func:`~app.execution._dedup_helpers
  .family_rail_blocker`): every occurrence structurally identical to the
  first, no cross-module free-global rebinds, no multi-line strings, no
  pre-run closures over run-stores, no invisible ``import``/``except``/
  ``match`` bindings, no ``async for``/``async with``, no reflection;
- no shadow of ``object``/``type``/``tuple``/``len`` (module level or any
  enclosing function) — the emitted sentinel/guard must resolve to the real
  builtins; and the sentinel name must be unused in every enclosing function.

Consumes the same EXACT-duplicate :class:`~app.engine.dedup.DuplicateBlock`
input as its siblings, reusing dedup_extract's occurrence resolution, data-flow
and naming machinery and dedup_total_return's shared prelude — only the
control-flow admissibility rule and the sentinel emit are new. Deterministic,
stdlib-only; produces a suite-verified :class:`RenamePlan` (never-fake-green:
``apply_rename`` verifies and auto-rolls-back like every plan in the family).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from app.execution._dedup_helpers import (
    _bound_before_run,
    _bound_names,
    _definitely_assigned,
    _unbound_live_in_reason,
    resolve_occurrence_prefix,
    stamp_multi_module_plan,
)
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import (
    _all_top_level_bindings,
    _import_insert_index,
    _locate_run,
    _module_dotted,
    _Occurrence,
)
from app.execution.dedup_total_return import (
    _always_returns,
    _choose_helper_name,
    _FLOW_HAZARDS,
    _helper_insert_index,
    _load_and_resolve,
    _signature_gate,
)
from app.execution.extract_method import (
    _data_flow,
    _function_param_names,
    _has_unenclosed_jump,
    _NESTED_SCOPE_NODES,
    _reindent,
)
from app.execution.unused_imports import strip_unused_imports

__all__ = ["plan_dedup_guarded_return", "_definitely_assigned"]

# Names whose meaning depends on the enclosing CLASS cell: zero-arg ``super()``
# and ``__class__`` are compiled against the method's implicit ``__class__``
# closure, which a module-level helper does not have — the lifted code would
# re-parse fine and fail at runtime, exactly the silent breakage this refuses.
_CLASS_CELL_NAMES = frozenset({"super", "__class__"})


def _guarded_return_reason(run: list) -> str | None:
    """The reason ``run`` is NOT a safe guarded-return block to lift, or ``None``
    when it is. Mirrors the sibling hazard sets, then requires the exact
    COMPLEMENT of their admissibility shapes: at least one ``return``
    (otherwise it is dedup_extract's plain-block job) that does NOT
    always-return (otherwise it is dedup-total-return's job)."""
    has_return = False
    for stmt in run:
        for n in ast.walk(stmt):
            if isinstance(n, _NESTED_SCOPE_NODES):
                return ("the range defines a nested function/lambda — its scope "
                        "can't be analyzed; extract it separately first")
            if isinstance(n, _FLOW_HAZARDS):
                return (f"the range contains `{type(n).__name__.lower()}` — moving "
                        "it into a helper would change control flow")
            if isinstance(n, ast.Delete):
                return ("the range contains `del` — definite assignment of the "
                        "projected locals can't be guaranteed")
            if isinstance(n, ast.Name) and n.id in _CLASS_CELL_NAMES:
                return (f"the range references `{n.id}` — a module-level helper "
                        "has no class cell, so it would break at runtime")
            if isinstance(n, ast.Return):
                has_return = True
    if any(_has_unenclosed_jump(stmt) for stmt in run):
        return ("the range contains a `break`/`continue` whose loop is outside "
                "the selection — it can't be lifted out")
    if not has_return:
        return ("the range has no `return` — a plain block is dedup_extract's "
                "job, not a guarded-return lift")
    if _always_returns(run):
        return ("every exit path of the range returns — that is "
                "dedup-total-return's job, not a guarded-return lift")
    return None


def _resolve_guarded_return(rel: str, start_line: int, n_statements: int,
                            sources: dict, trees: dict,
                            plan: RenamePlan) -> _Occurrence | None:
    """Resolve one ``module:lineno`` occurrence into an :class:`_Occurrence` for
    a GUARDED-RETURN block, recording a blocker and returning ``None`` on any
    unsafe / ambiguous case. Same resolution shape as the siblings (shared
    prelude), differing in the control-flow admissibility check and in KEEPING
    the real ``live_out`` — the projection emits it back to the caller."""
    prefix = resolve_occurrence_prefix(plan, rel, start_line, n_statements,
                                       sources, trees, _locate_run)
    if prefix is None:
        return None
    source, fn, container, run = prefix

    reason = _guarded_return_reason(run)
    if reason:
        plan.blockers.append(f"{rel}:{start_line}: {reason}")
        return None

    before = fn.body[:fn.body.index(run[0])]
    after = fn.body[fn.body.index(run[-1]) + 1:]
    live_in, live_out = _data_flow(fn, before, run, after)
    bound_before = _bound_before_run(fn, before)

    # W99b-fix (family-wide, shipped-bug closure): EVERY live-in name must be
    # bound_before, full stop — the call site evaluates live_in EAGERLY
    # (`_call_lines`), so a name only CONDITIONALLY bound in the prelude could
    # raise `UnboundLocalError` even on a path where the guard return below
    # exits before the run ever reads it (`acc` is live-in-only, not
    # live-out: the pre-existing check below never saw it).
    reason = _unbound_live_in_reason(live_in, bound_before)
    if reason:
        plan.blockers.append(f"{rel}:{start_line}: {reason}")
        return None

    # W100 (over-refusal narrowing): a live-in name that is DEFINITELY bound
    # BEFORE the run — a parameter, or a direct top-level assignment in the
    # prelude — is always bound at the fall-through even when the run only
    # rebinds it conditionally: it enters the helper as a parameter, so the
    # projection line can never raise. Plain `live_in` membership is NOT
    # enough: _data_flow's live-in admits names bound only CONDITIONALLY
    # before the run, and evaluating such a name eagerly as a call argument
    # could raise `UnboundLocalError` on a guard path where the original
    # returned before ever reading it (closed for live-in-ONLY names by the
    # W99b-fix rail above; this rail stays for live-out names).
    definite = _definitely_assigned(run) | (set(live_in) & bound_before)
    unbound = [n for n in live_out if n not in definite]
    if unbound:
        plan.blockers.append(
            f"{rel}:{start_line}: {', '.join(unbound)} may be unbound when the "
            "range falls through (no direct top-level assignment) — projecting "
            "it out could raise where the original did not")
        return None

    span_lo = run[0].lineno
    span_hi = max(getattr(s, "end_lineno", s.lineno) for s in run)
    return _Occurrence(rel, source, source.splitlines(keepends=True), fn,
                       container, run, live_in, live_out, span_lo, span_hi,
                       False)  # tail_return=False: the call site GUARDS the sentinel


# The names the emitted caller-side code RESOLVES at runtime outside the
# lifted block: `object` builds the sentinel; `type`/`tuple`/`len` gate the
# live-out projection form. A shadow of ANY of them (a module-level
# ``object = lambda: None`` makes the sentinel forgeable; a parameter named
# ``type`` breaks the guard) silently changes the emit's meaning.
_EMIT_BUILTIN_NAMES = ("object", "type", "tuple", "len")


def _shadowed_emit_builtin(resolved: list, trees: dict, rels: list) -> str | None:
    """The blocker for the first emit-critical builtin that any involved
    module's top-level bindings, or any enclosing function's locals/params,
    shadow — the emitted sentinel/guard would resolve to the shadow, not the
    builtin — or ``None`` when all four are the real builtins everywhere."""
    bound = set(_all_top_level_bindings(trees, set(rels)))
    for occ in resolved:
        bound |= _function_param_names(occ.fn) | _bound_names([occ.fn])
    for name in _EMIT_BUILTIN_NAMES:
        if name in bound:
            return (f"`{name}` is shadowed by a module-level or enclosing-"
                    "function binding — the emitted sentinel/guard would "
                    "resolve to the shadow, not the builtin")
    return None


def _names_used_in_fns(resolved: list) -> set[str]:
    """Every Name/arg appearing in ANY enclosing function — the set a fresh
    caller-visible name (the result local, the sentinel the guard compares
    against) must dodge: a same-named local would hijack the emitted code."""
    used: set[str] = set()
    for occ in resolved:
        for n in ast.walk(occ.fn):
            if isinstance(n, ast.Name):
                used.add(n.id)
            elif isinstance(n, ast.arg):
                used.add(n.arg)
    return used


def _free_sentinel_name(helper_name: str, trees: dict, rels: set,
                        resolved: list,
                        also_avoid: frozenset = frozenset()) -> str | None:
    """A module-level sentinel name derived from the helper's own, free in
    every involved module (its def and cross-module imports must never
    collide) AND unused as any Name/arg in every enclosing function (a
    same-named local would hijack the guard's identity test — the same scan
    :func:`_free_result_name` performs) — ``_shared_1`` → ``_SHARED_1_MISS``.
    ``None`` when exhausted.

    ``also_avoid`` (default ``frozenset()`` — byte-preserves the exact lane):
    extra names the sentinel must dodge. The near-dup parameterized lanes pass
    the hole `p<n>` params here — the sentinel is referenced in the helper's
    tail where the params are in scope, so a same-named param would shadow it.
    Unreachable today (``p\\d+`` never collides with ``_UPPER_MISS``), but
    W99c's descriptive Name-hole names make it reachable — wired now."""
    bound = (_all_top_level_bindings(trees, rels) | _names_used_in_fns(resolved)
            | also_avoid)
    base = f"_{helper_name.strip('_').upper()}_MISS"
    if base not in bound:
        return base
    for n in range(2, 100):
        candidate = f"{base}_{n}"
        if candidate not in bound:
            return candidate
    return None


def _free_result_name(resolved: list) -> str | None:
    """A local name for the helper's result, free in EVERY enclosing function —
    it must not collide with any name the function reads, writes, or takes as a
    parameter (rebinding a read-later name would change behaviour)."""
    used = _names_used_in_fns(resolved)
    for candidate in ["_res"] + [f"_res_{i}" for i in range(2, 100)]:
        if candidate not in used:
            return candidate
    return None


def _names_tuple(names: list) -> str:
    """The inside of a tuple display for ``names`` — trailing comma when single,
    so ``(a,)`` stays a tuple."""
    return f"{names[0]}," if len(names) == 1 else ", ".join(names)


@dataclass(frozen=True)
class _Emit:
    """The plan-constant emit context: everything the per-file rewrite needs
    beyond the occurrences themselves (one place, so the rewrite helpers stay
    small and the values provably identical across files)."""
    helper_name: str
    helper_block: str
    rvar: str
    sentinel: str
    live_in: tuple
    live_out: tuple
    first_rel: str
    first_container: object
    first_dotted: str

    @property
    def call_line_count(self) -> int:
        """Lines each copy is replaced with — the sentinel guard is 3 lines,
        the live-out projection adds the rebind line."""
        return 3 if not self.live_out else 4


def _build_guarded_helper(first: _Occurrence, helper_name: str, live_in: list,
                          sentinel: str, live_out: list) -> str:
    """Build the sentinel + helper block from the FIRST occurrence's real
    source: the sentinel ``object()`` line, then the block VERBATIM under the
    def, then the appended fall-through marker line — ``return <sentinel>``
    bare, or ``return (<sentinel>, (<live_out>))`` when locals project out."""
    range_lines = first.lines[first.span_lo - 1:first.span_hi]
    base_indent = len(range_lines[0]) - len(range_lines[0].lstrip())
    body_lines = _reindent(range_lines, base_indent)
    if live_out:
        tail = f"    return ({sentinel}, ({_names_tuple(live_out)}))"
    else:
        tail = f"    return {sentinel}"
    src = [f"{sentinel} = object()", "", "",
           f"def {helper_name}({', '.join(live_in)}):"] + body_lines + [tail]
    return "\n".join(src) + "\n\n\n"


def _call_lines(indent: str, emit: _Emit,
                extra_args: tuple[str, ...] = ()) -> list[str]:
    """The caller-side replacement for one copy (newline-terminated lines):
    call the helper, return through anything that is NOT the fall-through
    marker, then rebind the projected locals when there are any.

    ``extra_args`` (default ``()`` — byte-preserves the exact lane): appended
    after ``emit.live_in`` in the call's argument list — the near-dup
    parameterized lane's OWN per-occurrence constant literals (never a
    live-in name, so eager evaluation is always safe)."""
    rvar, sentinel = emit.rvar, emit.sentinel
    args = list(emit.live_in) + list(extra_args)
    call = f"{indent}{rvar} = {emit.helper_name}({', '.join(args)})\n"
    if not emit.live_out:
        return [call,
                f"{indent}if {rvar} is not {sentinel}:\n",
                f"{indent}    return {rvar}\n"]
    names = list(emit.live_out)
    lhs = f"({names[0]},)" if len(names) == 1 else ", ".join(names)
    return [call,
            f"{indent}if not (type({rvar}) is tuple and len({rvar}) == 2 "
            f"and {rvar}[0] is {sentinel}):\n",
            f"{indent}    return {rvar}\n",
            f"{indent}{lhs} = {rvar}[1]\n"]


def _emit_file(rel: str, occs: list, sources: dict, trees: dict,
               emit: _Emit,
               const_args_of=lambda occ: ()) -> tuple[str | None, str]:
    """Rewrite ONE module: replace each copy with the sentinel-guard call block
    (bottom-up so earlier spans stay valid), then either splice the sentinel +
    helper in (the defining file) or import BOTH names (any other file).
    Returns ``(new_source, "")`` or ``(None, blocker)`` if the emitted module
    would not parse.

    ``const_args_of`` (default a no-op lambda — byte-preserves the exact
    lane): per-occurrence callback returning that copy's OWN extra call
    arguments (the near-dup lane's per-column constant literals)."""
    lines = list(sources[rel].splitlines(keepends=True))
    for occ in sorted(occs, key=lambda o: o.span_lo, reverse=True):
        head = occ.lines[occ.span_lo - 1]
        indent = " " * (len(head) - len(head.lstrip()))
        lines[occ.span_lo - 1:occ.span_hi] = _call_lines(
            indent, emit, const_args_of(occ))

    if rel == emit.first_rel:
        insert_at = _helper_insert_index(emit.first_container, occs,
                                         emit.call_line_count)
        lines[insert_at:insert_at] = [emit.helper_block]
    else:
        lines.insert(_import_insert_index(trees[rel]),
                     f"from {emit.first_dotted} import "
                     f"{emit.sentinel}, {emit.helper_name}\n")

    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        return None, f"{rel}: extraction would not parse ({e})"
    # Gate-clean, exactly like the siblings: lifting the block can strand the
    # imports it used; drop precisely those dead top-level imports.
    cleaned = strip_unused_imports(new_source)
    return (new_source if cleaned is None else cleaned), ""


def _emit_all_files(resolved: list, sources: dict, trees: dict, emit: _Emit,
                    plan: RenamePlan,
                    const_args_of=lambda occ: ()) -> tuple[dict, dict] | None:
    """Group occurrences by file and rewrite each (deterministic sorted order),
    accumulating ``(new_contents, edits_by_file)``. ``None`` (after recording a
    blocker) if any emitted module would not parse.

    ``const_args_of`` (default a no-op lambda — byte-preserves the exact
    lane): threaded straight through to :func:`_emit_file`."""
    by_file: dict[str, list] = {}
    for occ in resolved:
        by_file.setdefault(occ.rel, []).append(occ)

    new_contents: dict[str, str] = {}
    edits: dict[str, int] = {}
    for rel in sorted(by_file):
        occs = sorted(by_file[rel], key=lambda o: o.span_lo)
        new_source, emit_blocker = _emit_file(rel, occs, sources, trees, emit,
                                              const_args_of)
        if new_source is None:
            plan.blockers.append(emit_blocker)
            return None
        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != emit.first_rel else 0)
    return new_contents, edits


def _prepare(root: Path, block, plan: RenamePlan) -> dict | None:
    """The whole admissibility prelude — validate the block, parse and resolve
    every occurrence (the shared :func:`_load_and_resolve` prelude with the
    guarded-return rules), gate the shared signature, and pick the helper /
    sentinel / result names. Each step records its own blocker; the first
    failure returns ``None``."""
    loaded = _load_and_resolve(root, block, plan, _resolve_guarded_return)
    if loaded is None:
        return None
    sources, trees, resolved, rels = loaded

    sig0 = _signature_gate(resolved, plan)
    if sig0 is None:
        return None

    names = _pick_names(resolved, trees, rels, plan)
    if names is None:
        return None
    return {
        "sources": sources, "trees": trees, "resolved": resolved,
        "live_in": sig0[0], "live_out": sig0[1], "first": resolved[0],
        "helper_name": names[0], "sentinel": names[1], "rvar": names[2],
    }


def _pick_names(resolved: list, trees: dict, rels: list,
                plan: RenamePlan) -> tuple[str, str, str] | None:
    """The three fresh names a guarded-return lift needs — helper (shared
    scheme), sentinel (module level, everywhere), result local (every enclosing
    function) — behind the shadowed-emit-builtin rail (the emitted
    ``object()``/``type``/``tuple``/``len`` must be the real builtins).
    Records a blocker and returns ``None`` when any is unavailable."""
    shadow = _shadowed_emit_builtin(resolved, trees, rels)
    if shadow is not None:
        plan.blockers.append(shadow)
        return None
    helper_name = _choose_helper_name(resolved, trees, rels, plan)
    if helper_name is None:
        return None
    sentinel = _free_sentinel_name(helper_name, trees, set(rels), resolved)
    if sentinel is None:
        plan.blockers.append("could not find a free module-level sentinel name")
        return None
    rvar = _free_result_name(resolved)
    if rvar is None:
        plan.blockers.append(
            "could not find a free result name in the enclosing functions")
        return None
    return helper_name, sentinel, rvar


def plan_dedup_guarded_return(project_root: str | Path, block) -> RenamePlan:
    """Plan lifting a GUARDED-RETURN exact-duplicate block into one shared
    helper via sentinel projection.

    ``block`` is an exact-duplicate :class:`~app.engine.dedup.DuplicateBlock`
    (``occurrences`` are ``"module:lineno"`` of each copy's first statement) —
    the same input the sibling dedup transforms consume. This planner accepts
    ONLY the shape both siblings refuse: a run with a ``return`` on some path
    AND a reachable fall-through. The run lifts verbatim into a helper that
    marks fall-through with a fresh module-level sentinel; each copy becomes a
    call + sentinel guard (+ a live-out rebind when locals project out).

    Returns a :class:`RenamePlan` ready for ``apply_rename`` (suite-verified,
    auto-rollback). On any unsafe / ambiguous case the plan carries a blocker
    and empty ``new_contents`` — correctness and safety over coverage.
    """
    plan = RenamePlan(old=getattr(block, "fingerprint", "dedup"), new="_shared")

    ctx = _prepare(Path(project_root), block, plan)
    if ctx is None:
        return plan
    first = ctx["first"]
    live_in, live_out = ctx["live_in"], ctx["live_out"]

    emit = _Emit(
        helper_name=ctx["helper_name"],
        helper_block=_build_guarded_helper(first, ctx["helper_name"], live_in,
                                           ctx["sentinel"], live_out),
        rvar=ctx["rvar"], sentinel=ctx["sentinel"],
        live_in=tuple(live_in), live_out=tuple(live_out),
        first_rel=first.rel, first_container=first.container,
        first_dotted=_module_dotted(first.rel),
    )
    emitted = _emit_all_files(ctx["resolved"], ctx["sources"], ctx["trees"],
                              emit, plan)
    if emitted is None:
        return plan
    new_contents, edits = emitted

    stamp_multi_module_plan(plan, emit.helper_name, first.rel, ctx["sources"],
                            new_contents, edits)
    if not live_in and not live_out:
        plan.warnings.append(
            "the helper takes no parameters and projects nothing out "
            "(it returns via the block's own returns) — confirm it's self-contained")
    return plan
