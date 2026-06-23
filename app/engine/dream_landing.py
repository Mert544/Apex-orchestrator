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
    apply the SAME graduation gate the curating dream uses — the existing
    ``PROMOTE_STREAK`` / ``PROMOTE_CONFIDENCE`` thresholds over the dream's own
    streak count — so the live path graduates exactly what a curated store would
    have, no lowered bar and no new threshold. Sorted, deduplicated; empty when
    the dream surfaces no above-gate confluence (or cannot run)."""
    try:
        from app.engine.dream import PROMOTE_CONFIDENCE, PROMOTE_STREAK, dream

        report = dream(project_root, write_digest=False, curate=False,
                       persist=False)
    except Exception:
        return []  # a dream that cannot run names no confluence — never invents one
    streaks: dict[str, int] = getattr(report, "_streaks", {}) or {}
    out: list[str] = []
    for d in report.discovery_objs:
        key = d.get("key", "")
        if (streaks.get(key, 1) >= PROMOTE_STREAK
                and d.get("confidence", 0.0) >= PROMOTE_CONFIDENCE):
            module = _confluence_key_module(key, project_root)
            if module:
                out.append(module)
    return sorted(set(out))


def dream_confluence_modules(project_root: str | Path) -> list[str]:
    """Modules the dream graduated as CONFLUENCES — files that carry many
    structural signals at once (high churn × hub × co-change). Read from the
    promotion store the dream writes (`.apex/dream-promotions.json`); these are
    the organism's hardest-won, multi-night discoveries about where the risk
    concentrates. Returns existing module paths only, sorted, deduplicated.

    When the store is absent or empty (the DEFAULT dream only proposes, never
    writes), the modules are derived LIVE from a read-only dream under the same
    graduation gate — so ``develop --from-dream`` lands on the file the organism
    flags even on a project that was never ``--curate``-d, instead of stopping at
    a report. A non-empty store always wins, so a curated project is unchanged."""
    import json

    path = Path(project_root) / ".apex" / "dream-promotions.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        key = it.get("key", "") if isinstance(it, dict) else ""
        module = _confluence_key_module(key, project_root)
        if module:
            out.append(module)
    if out:
        return sorted(set(out))
    return _live_confluence_modules(project_root)


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


def compile_from_dream(project_root: str | Path, objective: str = "dead-params",
                       max_steps: int = 25, verify: bool = True,
                       apply: bool = True, sweep: bool = False) -> list[CompileResult]:
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
    never a faked one. Empty list when the dream named no confluence."""
    modules = dream_confluence_modules(project_root)
    objectives = _dream_sweep_objectives(project_root) if sweep else [objective]
    results: list[CompileResult] = []
    for module in modules:
        for obj in objectives:
            results.append(compile_objective(
                project_root, objective=obj, max_steps=max_steps,
                verify=verify, apply=apply, scope_module=module))
    return results
