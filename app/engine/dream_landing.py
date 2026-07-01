"""The DREAM analysis→LANDING seam: `develop --from-dream` lands from the
DEFAULT dream.

The default dream only *proposes* (it never writes `.apex/dream-promotions.json`),
so a naive ``dream_confluence_modules`` would return ``[]`` and
``compile_from_dream`` would land nothing on a project that had never been
``--curate``-d. Two fixes close the loop, both deterministic and offline:

  - **drives** — when the promotion store is absent/empty,
    ``dream_confluence_modules`` derives promotable confluences LIVE from a fully
    READ-ONLY dream (``persist=False``) under the EXISTING ``PROMOTE_STREAK`` /
    ``PROMOTE_CONFIDENCE`` gate (no lowered bar, no new threshold). The read-only
    dream READS the journal to compute the streak but NEVER advances it, so the
    derivation is deterministic, idempotent, and writes nothing — the streak is
    earned by the user's own prior ``apex dream`` runs;
  - **lands** — ``compile_from_dream(..., sweep=True)`` runs the
    ``rank_objectives``-ranked board of fitness-applicable objectives scoped to
    the flagged module, so the landing is no longer pinned to dead-params.

A non-empty stored store still wins byte-for-byte (a curated project is
unchanged), and a below-gate confluence still graduates nothing (no
over-promise).

Note: a curated store built with ``apex dream --curate --learn-gates``
(``dream_gate_learn``'s tighten-only promote-gate feedback) may promote a
STRICTER SUBSET of the confluences an un-learned curate run would have — the
gate only ever tightens, never loosens. This seam's refusal-safe invariant
(empty/absent store ⇒ ``{}`` boost, zero behaviour change) is untouched either
way: a smaller promoted set still reads as a smaller-or-equal boost map, never
a fabricated one.

Imports flow ONE-WAY: this module imports ``objective_compiler`` (compile_objective,
CompileResult), ``ascend`` (rank_objectives), and ``dream`` (PROMOTE_*, dream).
Nothing in those modules imports ``dream_landing`` — only the CLI and the tests
do — so the seam adds no import cycle.

Deterministic, stdlib-only; reuses the verified-with-rollback compile engine.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.objective_compiler import CompileResult, compile_objective


def _confluence_key_module(key: str, project_root: str | Path) -> str:
    """The existing module a ``confluence:<module>`` promotion key names, or "".

    Returns the path only when the key is a confluence and the file still
    exists under the project — so a stale or non-confluence key is dropped."""
    if not key.startswith("confluence:"):
        return ""
    module = key.split(":", 1)[1].strip()
    if module and (Path(project_root) / module).exists():
        return module
    return ""


def _live_confluence_modules(project_root: str | Path) -> list[str]:
    """Derive promotable confluence modules LIVE, without a stored promotion.

    The default dream never writes the promotion store (it only PROPOSES), so a
    project that has never been ``--curate``-d would land nothing. Here we run a
    fully read-only dream (``persist=False`` — the journal/ledger are never
    advanced, so repeated calls return the same modules and write nothing) and
    apply the SAME graduation predicate the curating dream uses —
    :func:`app.engine.dream._promotable_discoveries`, the single source of truth
    for what a curate run would promote. That predicate is streak-gated over BOTH
    promote paths: the design-level ``PROMOTE_CONFIDENCE`` path AND the
    value-aware second path (a confluence BELOW the confidence bar that carries a
    PROVEN verified-landable move, :func:`_is_value_landable_confluence`). The
    live path formerly re-derived only the design-level half inline, so it
    silently DROPPED exactly the most actionable confluences — the ones the dream
    can prove it can land — leaving ``develop --from-dream`` / ``dream --land``
    scope narrower than a curated store on the same project. Reusing the curate
    predicate closes that gap: the live path now graduates EXACTLY what a curated
    store would (no lowered bar — the value-aware path still requires a proven
    landing, and every landed move still passes the covered-only verify +
    auto-rollback gate downstream, so never-fake-green is untouched). Sorted,
    deduplicated; empty when the dream surfaces no promotable confluence (or
    cannot run). ``gate_factors`` is left at its default (the static gate), so a
    non-``--learn-gates`` live derivation is byte-identical to the curate default."""
    try:
        from app.engine.dream import _promotable_discoveries, dream

        report = dream(project_root, write_digest=False, curate=False,
                       persist=False)
    except Exception:
        return []  # a dream that cannot run names no confluence — never invents one
    streaks: dict[str, int] = getattr(report, "_streaks", {}) or {}
    root = Path(project_root)
    out: list[str] = []
    for d in _promotable_discoveries(root, report, streaks):
        # confluence keys only — a non-confluence promote (association/triple)
        # yields "" here, so the live confluence contract is preserved while the
        # value-landable confluences the old inline gate dropped now surface.
        module = _confluence_key_module(d.get("key", ""), project_root)
        if module:
            out.append(module)
    return sorted(set(out))


def _stored_confluence_modules(project_root: str | Path) -> list[str]:
    """The confluence modules the dream has ALREADY PERSISTED to
    ``.apex/dream-promotions.json`` — the organism's hardest-won, multi-night
    discoveries, read WITHOUT running a dream.

    A pure read of the store: existing ``confluence:`` module paths only, sorted
    and deduplicated. Empty when the store is absent, unreadable, or names no
    still-existing confluence. Unlike :func:`dream_confluence_modules` this never
    falls back to a LIVE read-only dream, so it stays cheap enough to consult on
    every ``apex auto`` run and its emptiness is a byte-cheap fact (no dream cost,
    no clock/random) — the property the refusal-safe ranking boost relies on."""
    import json

    path = Path(project_root) / ".apex" / "dream-promotions.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        key = it.get("key", "") if isinstance(it, dict) else ""
        module = _confluence_key_module(key, project_root)
        if module:
            out.append(module)
    return sorted(set(out))


# The priority boost a module earns for being a PERSISTED dream confluence. A
# single fixed positive constant (not a per-module gradient) so the amplification
# is deterministic and coarse: a confluence step is promoted ahead of a
# non-confluence peer WITHIN its phase, but the relative order among confluences
# and among non-confluences is left exactly as the existing ranking chose it. The
# magnitude is irrelevant beyond being > 0 (the consumer sorts on sign, not
# scale); kept at 1.0 for a legible ``preview``/debug value.
DREAM_CONFLUENCE_BOOST = 1.0


def dream_signal_weight(project_root: str | Path,
                        modules: list[str] | None = None) -> dict[str, float]:
    """Per-module priority BOOST for the modules the dream has graduated as
    CONFLUENCES — the seam that lets ``apex auto`` amplify the organism's OWN
    overnight discovery when it ranks the value board, instead of ignoring it.

    Returns ``{module: DREAM_CONFLUENCE_BOOST}`` for each persisted confluence
    module (``modules``, when supplied — a precomputed dream result — else read
    from the promotion store via :func:`_stored_confluence_modules`); every other
    module is simply ABSENT (the caller reads a missing key as a 0.0 boost). The
    boost is a flat positive constant, so a confluence step sorts ahead of a
    non-confluence peer within its phase while the order AMONG confluences and
    AMONG non-confluences is untouched.

    REFUSAL-SAFE by construction — the single invariant the whole wiring rests on:
    when no dream has persisted a confluence (store absent / unreadable /
    below-gate ⇒ empty ``modules``) the map is ``{}``, and a consumer that adds a
    per-step boost of ``map.get(module, 0.0)`` then leaves EVERY step's key
    unchanged, so a stable sort reproduces the current AST-only order
    byte-for-byte. No dream ⇒ zero behaviour change.

    Deterministic, offline, zero-token: a frozen-constant stamp over a pure store
    read (or a caller-supplied list) — no clock, no randomness, no dream run, no
    writes. Deliberately does NOT trigger a live dream (that is
    ``dream_confluence_modules``' job on the explicit ``--from-dream`` path); the
    auto ranking must not pay a dream's cost, and an unpersisted project must stay
    byte-identical."""
    mods = modules if modules is not None else _stored_confluence_modules(project_root)
    return {module: DREAM_CONFLUENCE_BOOST for module in mods if module}


def dream_confluence_modules(project_root: str | Path,
                             value_ranked: bool = False) -> list[str]:
    """Modules the dream graduated as CONFLUENCES — files that carry many
    structural signals at once (high churn × hub × co-change). Read from the
    promotion store the dream writes (`.apex/dream-promotions.json`); these are
    the organism's hardest-won, multi-night discoveries about where the risk
    concentrates. Returns existing module paths only, sorted, deduplicated.

    When the store is absent or empty (the DEFAULT dream only proposes, never
    writes), the modules are derived LIVE from a read-only dream under the same
    graduation gate — so ``develop --from-dream`` lands on the file the organism
    flags even on a project that was never ``--curate``-d, instead of stopping at
    a report. A non-empty store always wins, so a curated project is unchanged.

    ``value_ranked`` (DEFAULT False = byte-identical to the alphabetical order
    every existing caller relies on) re-orders the graduated set by
    :func:`_rank_confluences` — highest expected-landable-buyer-value file first —
    so the overnight chain leads with the most valuable confluence. It re-orders
    the SAME set (a permutation, never a different membership) and a single-/
    zero-confluence project is unchanged regardless, so opting in cannot land
    anything the alphabetical order would not."""
    stored = _stored_confluence_modules(project_root)
    modules = stored if stored else _live_confluence_modules(project_root)
    if value_ranked:
        modules = _rank_confluences(modules, project_root)
    return modules


def _dream_sweep_objectives(project_root: str | Path) -> list[str]:
    """The fitness-applicable objectives a confluence sweep should attempt, in
    the organism's own priority order (worst-and-most-profitable first).

    Reuses ``rank_objectives`` — the SAME deterministic ranking ``plan``/``ascend``
    use (pending debt amplified by learned payoff, damped by proven land-rate,
    ties broken by registration order) — and keeps only the objectives with
    pending fixable debt, so the sweep never spends a campaign on an objective
    the project has nothing to fix. Deterministic: the ranking carries no
    randomness or wall-clock."""
    from app.engine.ascend import rank_objectives

    return [r.objective for r in rank_objectives(project_root) if r.pending > 0]


def _module_landable_value(project_root: str | Path) -> dict[str, float]:
    """Per-module sum of buyer-value over the objectives that have PENDING,
    fixable work SCOPED to that module — the landable buyer-value a confluence
    chain could actually realize there.

    For each fitness-applicable objective (the SAME ``rank_objectives`` board the
    sweep runs, kept to ``pending > 0`` so a project-wide-dead objective never
    counts), generate its candidate moves ONCE against the current tree, bucket
    them by the module each targets (``_move_module``), and credit every module
    that has at least one scoped move with the objective's
    ``objective_value_weight`` — the frozen ``move_value`` table the planner
    already trusts. Summing those weights ranks a file by how much CONCRETE buyer
    value the chain can land on it, not by how many moves: a single
    ``implement-stub`` (1.00) outweighs three ``sort-imports`` (0.18 each).

    Pure, deterministic, zero-token: a frozen-table lookup over the compiler's own
    candidate generation — no clock, no randomness, no writes (every move is built
    but NONE applied). Reads ``move_value`` exactly like ``objective_value`` does,
    so it carries no new objective / parity obligation."""
    from app.engine.objective_compiler import _move_module, _objectives_map
    from app.engine.objective_value import objective_value_weight

    table = _objectives_map()
    scores: dict[str, float] = {}
    for objective in _dream_sweep_objectives(project_root):
        spec = table.get(objective)
        if spec is None:
            continue
        generate = spec[1]
        try:
            moves = generate(project_root)
        except Exception:
            continue  # an objective that cannot enumerate names no module — skip
        weight = objective_value_weight(objective)
        for module in {_move_module(m) for m in moves}:
            if module:
                scores[module] = scores.get(module, 0.0) + weight
    return scores


def _rank_confluences(modules: list[str], project_root: str | Path) -> list[str]:
    """Re-rank graduated confluence ``modules`` by EXPECTED LANDABLE BUYER-VALUE,
    highest first — so the overnight chain spends its first (and, under a budget,
    possibly only) verified moves where a buyer gets the most concrete value, not
    on the file whose path happens to sort first.

    The score is :func:`_module_landable_value` — the sum of
    ``objective_value_weight`` over the fitness-applicable objectives with pending
    work scoped to the module, the SAME value/ranking math ``plan``/``ascend``
    already trust. Modules sort by that score DESCENDING; every tie (including the
    common case where the value model can't separate two files) falls back to the
    existing ALPHABETICAL key, so the order is total and fully deterministic — two
    runs on the same tree return the identical list, with no clock or randomness.

    Ordering ONLY: the returned list is a permutation of the input — never a
    different SET — so it cannot change WHICH moves the suite-gated-with-rollback
    landing attempts, only the order it attempts them in. A 0/1-module list is
    returned unchanged (nothing to reorder)."""
    if len(modules) < 2:
        return list(modules)
    scores = _module_landable_value(project_root)
    # Descending value, ties broken by the existing alphabetical key — total order.
    return sorted(modules, key=lambda m: (-scores.get(m, 0.0), m))


def compile_from_dream(project_root: str | Path, objective: str = "dead-params",
                       max_steps: int = 25, verify: bool = True,
                       apply: bool = True, sweep: bool = False,
                       value_ranked: bool = False) -> list[CompileResult]:
    """Run a scoped develop campaign on each module the dream flagged as a
    confluence — the closed loop: a 20-night structural discovery becomes a
    morning's verified cleanup, no human choosing the next move.

    By default (``sweep=False``) this composes the single ``objective`` per
    confluence module — one CompileResult per module, unchanged. With
    ``sweep=True`` it instead runs the ``rank_objectives``-ranked board of
    fitness-applicable objectives against each flagged module (one CompileResult
    per objective per module, ranked order), so the LANDING is no longer pinned
    to dead-params: the organism brings its whole verified-move repertoire to the
    exact file it flagged. Every move stays suite-gated with auto-rollback, so an
    objective with nothing to land on a module simply yields an empty campaign —
    never a faked one. Empty list when the dream named no confluence.

    ``value_ranked`` (DEFAULT False = byte-identical to today's alphabetical order)
    opts the MODULE order into :func:`_rank_confluences`: with several graduated
    confluences the chain then works the highest expected-landable-buyer-value file
    first instead of the alphabetically-first one. Ordering ONLY — it never changes
    WHICH campaigns run (same module set, same objectives), so a single-confluence /
    empty project and every default caller stay byte-for-byte unchanged."""
    # The default keeps the historical single-argument call EXACTLY, so an existing
    # ``dream_confluence_modules`` monkeypatch/stub still binds — only the opted-in
    # path passes the new keyword.
    modules = (dream_confluence_modules(project_root, value_ranked=True)
               if value_ranked else dream_confluence_modules(project_root))
    objectives = _dream_sweep_objectives(project_root) if sweep else [objective]
    results: list[CompileResult] = []
    for module in modules:
        for obj in objectives:
            results.append(compile_objective(
                project_root, objective=obj, max_steps=max_steps,
                verify=verify, apply=apply, scope_module=module))
    return results
