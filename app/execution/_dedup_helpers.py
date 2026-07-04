"""Shared primitives for the dedup / near-dup extract transforms.

:mod:`app.execution.dedup_extract`, :mod:`app.execution.dedup_total_return`, and
:mod:`app.execution.near_dup_extract` each build a multi-module
:class:`~app.execution.cross_file_rename.RenamePlan` and finish by stamping the
SAME five fields onto it. That finalise tail was byte-identical across the three
transforms (the duplication detector flagged it as a shared 5-statement window),
so it lives here once and every transform calls it.

It also hosts the family's SOUNDNESS RAILS (:func:`family_rail_blocker`): the
adversarially-verified refusal checks the exact-dup landers (dedup_extract,
dedup_total_return, dedup_guarded_return) run after resolving every occurrence
— occurrence identity, overlapping same-file spans, cross-module free-global
rebinds, and the per-run lift hazards (multi-line string/bytes constants,
pre-run closures, invisible non-``Name`` bindings, ``async for``/``async
with``, frame/namespace reflection, ``global``/``nonlocal``-declared names the
run binds or reads). Strictly refuse-direction: a rail can only turn an
unsound accept into a blocker.

W99b-fix: a SEPARATE, earlier rail lives here too — :func:`_unbound_live_in_reason`
— closing a shipped family-wide gap: every live-in name a resolver hands to
``_data_flow`` must be DEFINITELY bound before its run even starts (a
parameter, or a direct top-level prelude assignment — :func:`_bound_before_run`
/ :func:`_definitely_assigned`), or the eager call-argument evaluation every
lane emits can raise ``UnboundLocalError`` on a path where the original never
touched the name at all. Every resolver (``dedup_extract._resolve_occurrence``,
``dedup_total_return._total_return_occurrence``,
``dedup_guarded_return._resolve_guarded_return``, and — by delegation — both
near-dup parameterized siblings) calls it right after computing ``live_in``.

This is a **library** (leading underscore in the filename) — it is never an
objective and exposes no ``plan_*`` entry point. It imports nothing from the
transforms (only the plan type it stamps), so it can never form an import cycle
with them. Deterministic and stdlib-only — no time, no randomness.
"""

from __future__ import annotations

import ast
import builtins

from app.execution.extract_method import (
    _NESTED_SCOPE_NODES,
    _enclosing_function,
    _function_param_names,
    _loads,
    _stores,
)

__all__ = ["stamp_multi_module_plan", "resolve_occurrence_prefix",
           "family_rail_blocker", "occurrence_rail_reason"]

# Everything the running Python resolves WITHOUT a module-level binding — the
# only names a run may read freely when its copies collapse into one module.
_BUILTIN_NAMES = frozenset(dir(builtins))

# Frame/namespace reflection: what these observe depends on WHICH scope is
# executing, so a verbatim lift silently changes their meaning. ``_getframe``
# is matched as an attribute (``sys._getframe``).
_REFLECTION_NAMES = frozenset({"globals", "locals", "vars", "eval", "exec"})
_REFLECTION_ATTRS = frozenset(_REFLECTION_NAMES | {"_getframe"})

# ``async for`` / ``async with`` carry NO ``ast.Await`` child, so the family's
# yield/await hazard walks miss them — yet lifted into a sync ``def`` they emit
# a module that PARSES but cannot compile or import ("'async for' outside async
# function" is a compile-stage error, not a parse error).
_ASYNC_HAZARDS = (ast.AsyncFor, ast.AsyncWith)


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


# ── The family soundness rails (refuse-direction only) ────────────────────

def _invisible_bound_names(nodes: list) -> set[str]:
    """Names ``nodes`` bind WITHOUT an ``ast.Name`` store node — ``import …
    as`` / ``from … import`` aliases, ``except … as`` targets, and match-case
    captures (``MatchAs``/``MatchStar``) — invisible to ``_stores`` and hence
    to the family's live-in computation."""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.alias):
                out.add((n.asname or n.name).split(".")[0])
            elif isinstance(n, ast.ExceptHandler) and n.name:
                out.add(n.name)
            elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
                out.add(n.name)
    return out


def _bound_names(nodes: list) -> set[str]:
    """Every name ``nodes`` binds by ANY mechanism: ``ast.Name`` stores (plain
    assignments, aug-assigns, ``for``/``with`` targets, walrus) plus the
    non-``Name`` bindings of :func:`_invisible_bound_names`."""
    out = _invisible_bound_names(nodes)
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                out.add(n.id)
    return out


def _definitely_assigned(run: list) -> set[str]:
    """Names DEFINITELY bound when control falls off the end of ``run``.

    Reaching the fall-through exit means every DIRECT (top-level) statement of
    the run executed to completion, so the Name targets of a direct
    ``Assign`` / ``AugAssign`` / valued ``AnnAssign`` are guaranteed bound. A
    name bound only inside an ``if``/loop body, a ``for`` target (zero
    iterations skip it), a ``with`` body, or a walrus in a short-circuit
    position may be SKIPPED on the fall-through path, so none of those count.
    Conservative by design — under-approximating definite assignment can only
    refuse a liftable block, never mis-lift one.

    W99b-fix: moved here (from ``dedup_guarded_return``, its original home)
    so the family-wide live-in rail below can share it without an import
    cycle; re-exported from ``dedup_guarded_return`` for its own pinned
    tests (``tests/test_dedup_guarded_return.py`` imports it directly)."""
    out: set[str] = set()
    for stmt in run:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AugAssign):
            targets = [stmt.target]
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        else:
            continue
        for target in targets:
            for n in ast.walk(target):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    out.add(n.id)
    return out


def _bound_before_run(fn, before: list) -> set[str]:
    """Names guaranteed bound by the time control REACHES ``run`` at all: the
    enclosing function's own parameters, plus any name :func:`_definitely_assigned`
    by a direct top-level statement of ``before`` (the prelude preceding the
    run). A name bound only CONDITIONALLY in the prelude (inside an
    ``if``/loop/``with``) is excluded — some execution path reaches the run
    without ever having bound it."""
    return _function_param_names(fn) | _definitely_assigned(before)


def _unbound_live_in_reason(live_in: list, bound_before: set[str]) -> str | None:
    """W99b-fix (family-wide, shipped-bug closure): every LIVE-IN name must be
    in ``bound_before`` (:func:`_bound_before_run`), or ``None`` when they all
    are.

    ``_data_flow``'s ``live_in`` is *reads(run) ∩ (params ∪ stores(before))* —
    it counts a name bound only CONDITIONALLY in the prelude (``if cond: acc =
    1``) as live-in the moment the run reads it anywhere, however deep inside
    an ``if``. Every dedup-family lane then emits live-in names as EAGER call
    arguments (``helper(acc, ...)``): Python evaluates every argument before
    the call, regardless of the callee's own control flow. So when the run
    itself contains a guard that the ORIGINAL code would take before ever
    reading the name (a guard-return before the read, or the read sitting
    behind its own conditional inside the run), the original never touches an
    unbound ``acc`` on that path — but the lifted call touches it
    unconditionally, raising ``UnboundLocalError`` where the original raised
    nothing. Probe-verified (machine-checked) live on the shipped exact
    guarded-return lane and, by the same shared ``_data_flow`` computation,
    on dedup_extract (plain and tail-return), dedup_total_return, and both
    near-dup parameterized siblings (they resolve occurrences via these same
    functions). Refuse-direction only: under-approximating "bound before" can
    only refuse a liftable block, never mis-lift one — a live-in name that
    happens to be read unconditionally at the very top of the run before any
    guard would never actually diverge, but this rail refuses it anyway
    rather than prove that finer distinction."""
    unbound = sorted(set(live_in) - bound_before)
    if unbound:
        return (f"{', '.join(unbound)} may be unbound before the range even "
                "runs (no parameter/direct top-level assignment binds it "
                "first) — evaluating it eagerly as a call argument could "
                "raise where the original never read it")
    return None


def _run_context(fn, run: list) -> tuple[list, list]:
    """``(before, after)`` — the enclosing function's direct body statements
    around ``run`` (whose statements are identity-members of ``fn.body``)."""
    lo = fn.body.index(run[0])
    hi = fn.body.index(run[-1]) + 1
    return fn.body[:lo], fn.body[hi:]


def _async_hazard_reason(run: list) -> str | None:
    """``async for``/``async with`` in the run: no ``Await`` child, so the
    yield/await walks miss it, and the broken sync emit still PARSES."""
    for stmt in run:
        for n in ast.walk(stmt):
            if isinstance(n, _ASYNC_HAZARDS):
                return (f"the range contains `{type(n).__name__.lower()}` — "
                        "moving it into a helper would change control flow")
    return None


def _classdef_reason(run: list) -> str | None:
    """A ``class`` statement anywhere in the run (top-level or nested inside
    another statement): its ``.name`` binding is an identifier FIELD, not an
    ``ast.Name`` Store node, so it is INVISIBLE to ``_stores``/``_bound_names``
    (W99a, probe-confirmed, family-wide). Two independent silent hazards
    follow: (a) a class defined in the run and READ AFTER it is lost —
    live-out never includes it, so the caller raises ``NameError`` once the
    run collapses into a helper; (b) in the near-dup lane, a differing class
    DOCSTRING (an ``Expr`` over a ``str`` Constant at ``ClassDef.body[0]``)
    passes every other value-position gate and splices to a bare parameter
    expression, silently nulling ``__doc__``. Refusing every ClassDef in the
    run closes both at once — cheap over-refusal, class-in-function runs are
    rare. Refuse-direction only."""
    for stmt in run:
        for n in ast.walk(stmt):
            if isinstance(n, ast.ClassDef):
                return ("the range defines a `class` — its name binding is "
                        "invisible to this data-flow analysis (a read after "
                        "the range would raise NameError), refusing")
    return None


def _multiline_string_reason(run: list) -> str | None:
    """A string/bytes constant (or f-string) spanning multiple physical lines:
    ``_reindent`` treats its continuation lines as CODE and rewrites the
    constant's contents (a ``b\"\"\"…\"\"\"`` literal corrupts exactly like a
    ``str`` one). Refuse-first — no delta-indent preservation. The blocker
    string is unchanged (pinned by existing tests)."""
    for stmt in run:
        for n in ast.walk(stmt):
            is_str = (isinstance(n, ast.JoinedStr)
                      or (isinstance(n, ast.Constant)
                          and isinstance(n.value, (str, bytes))))
            if (is_str and getattr(n, "end_lineno", None) is not None
                    and n.end_lineno > n.lineno):
                return ("the range contains a multi-line string constant — "
                        "re-indenting the lifted block would rewrite the "
                        "string's contents")
    return None


def _reflection_reason(run: list) -> str | None:
    """``globals``/``locals``/``vars``/``eval``/``exec``/``sys._getframe`` in
    the run: they observe the EXECUTING scope, which the lift changes."""
    for stmt in run:
        for n in ast.walk(stmt):
            token = None
            if isinstance(n, ast.Name) and n.id in _REFLECTION_NAMES:
                token = n.id
            elif isinstance(n, ast.Attribute) and n.attr in _REFLECTION_ATTRS:
                token = n.attr
            if token is not None:
                return (f"the range references `{token}` — frame/namespace "
                        "reflection would observe the helper's scope, not the "
                        "original function's")
    return None


def _outside_closure_reason(fn, run: list) -> str | None:
    """A nested def/lambda OUTSIDE the run (but inside the enclosing function)
    reads a name the run STORES: after the lift that closure keeps reading the
    enclosing function's (now never-assigned) local."""
    stored = _stores(run)
    if not stored:
        return None
    before, after = _run_context(fn, run)
    for stmt in before + after:
        for n in ast.walk(stmt):
            if not isinstance(n, _NESTED_SCOPE_NODES):
                continue
            hit = sorted(stored & _loads([n]))
            if hit:
                return (f"the range assigns `{hit[0]}`, which a nested "
                        "def/lambda outside the range reads — the closure "
                        "would keep reading the now-helper-internal name")
    return None


def _invisible_binding_reason(fn, run: list) -> str | None:
    """The run READS a name the enclosing function binds only via an
    ``import``/``except``/``match`` binding outside the run — no ``ast.Name``
    store exists, so live-in misses it and the helper would lose the binding."""
    before, after = _run_context(fn, run)
    invisible = _invisible_bound_names(before + after)
    if not invisible:
        return None
    visible = _function_param_names(fn) | _stores(before) | _bound_names(run)
    hit = sorted((_loads(run) & invisible) - visible)
    if hit:
        return (f"the range reads `{hit[0]}`, which the enclosing function "
                "binds only via an `import`/`except`/`match` binding outside "
                "the range — the lifted helper would lose that binding")
    return None


def _global_decl_reason(fn, run: list) -> str | None:
    """A ``global``/``nonlocal`` declaration anywhere in the enclosing function
    whose name the run BINDS or READS: the declaration does not travel with the
    lift, so inside the helper a store becomes a helper-LOCAL bind (and a read
    resolves through a different scope chain) — an in-run call that reads the
    module global then observes a stale value. The in-run ``global`` case is
    already blocked upstream; this catches declarations OUTSIDE the run."""
    declared: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            declared.update(n.names)
    if not declared:
        return None
    hit = sorted(declared & (_bound_names(run) | _loads(run)))
    if hit:
        return (f"the enclosing function declares `{hit[0]}` "
                "global/nonlocal and the range binds or reads it — the "
                "lifted helper would rebind it as a helper-local instead")
    return None


def occurrence_rail_reason(fn, run: list) -> str | None:
    """The first per-run soundness-rail reason ``run`` cannot lift verbatim out
    of ``fn`` (or ``None``): async blocks, multi-line strings, reflection,
    pre-run closures over run-stores, invisible non-``Name`` bindings,
    ``global``/``nonlocal``-declared names the run binds or reads, and a
    ``class`` statement anywhere in the run (W99a — its name binding is
    invisible to this analysis). Fixed order, deterministic."""
    return (_async_hazard_reason(run)
            or _multiline_string_reason(run)
            or _reflection_reason(run)
            or _outside_closure_reason(fn, run)
            or _invisible_binding_reason(fn, run)
            or _global_decl_reason(fn, run)
            or _classdef_reason(run))


def _identity_blocker(resolved: list) -> str | None:
    """Every resolved run must be structurally identical (normalized
    ``ast.dump``, position-free) to the first's — a stale/shifted detector
    line otherwise replaces DIFFERENT code with the first copy's logic."""
    first = resolved[0]
    want = [ast.dump(s) for s in first.stmts]
    for occ in resolved[1:]:
        if [ast.dump(s) for s in occ.stmts] != want:
            return (f"{occ.rel}:{occ.span_lo}: occurrence is not structurally "
                    f"identical to {first.rel}:{first.span_lo} — stale "
                    "detector lines would rewrite different code with the "
                    "first copy's logic")
    return None


def _overlap_blocker(resolved: list) -> str | None:
    """Two occurrences in the SAME module whose statement spans OVERLAP: the
    bottom-up call-site splice rewrites the lower copy first, so the upper
    copy's slice then consumes the fresh call line and neighbouring code —
    silent corruption that still parses. Overlap is detected on the resolved
    spans (``span_lo``/``span_hi``), the only layer that has them."""
    by_rel: dict[str, list] = {}
    for occ in resolved:
        by_rel.setdefault(occ.rel, []).append(occ)
    for rel in sorted(by_rel):
        ordered = sorted(by_rel[rel], key=lambda o: o.span_lo)
        for a, b in zip(ordered, ordered[1:]):
            if b.span_lo <= a.span_hi:
                return (f"{rel}: occurrences at lines {a.span_lo} and "
                        f"{b.span_lo} overlap — overlapping copies cannot be "
                        "rewritten independently, refusing")
    return None


def _cross_module_rebind_blocker(resolved: list) -> str | None:
    """When the copies span modules, any name a run LOADS that is neither
    live-in, nor bound within the run, nor a Python builtin resolves to a
    module global — and the lift would re-resolve it in the DEFINING module.
    Single-module blocks are untouched (the helper stays in the same module)."""
    if len({occ.rel for occ in resolved}) < 2:
        return None
    for occ in resolved:
        free = sorted(_loads(occ.stmts) - set(occ.live_in)
                      - _bound_names(occ.stmts) - _BUILTIN_NAMES)
        if free:
            return (f"{occ.rel}:{occ.span_lo}: the range reads `{free[0]}` — "
                    "a free module-global would rebind to the defining "
                    "module's value when the copies collapse into one module")
    return None


def family_rail_blocker(resolved: list) -> str | None:
    """The dedup family's post-resolution soundness rails, in fixed order:
    occurrence identity, overlapping same-file spans, cross-module free-global
    rebinds, then each occurrence's per-run rails
    (:func:`occurrence_rail_reason`). Returns the first blocker string, or
    ``None`` when the block is sound to lift. ``resolved`` entries only need
    ``rel``/``span_lo``/``span_hi``/``stmts``/``live_in``/``fn`` (the family's
    ``_Occurrence`` shape). Refuse-direction only: this can never widen what
    lands."""
    blocker = (_identity_blocker(resolved)
               or _overlap_blocker(resolved)
               or _cross_module_rebind_blocker(resolved))
    if blocker is not None:
        return blocker
    for occ in resolved:
        reason = occurrence_rail_reason(occ.fn, occ.stmts)
        if reason is not None:
            return f"{occ.rel}:{occ.span_lo}: {reason}"
    return None
