"""A deterministic *work* budget for mutation-based gap-finding — a COUNT, never a clock.

The mutation-killing test objectives (``strengthen-tests`` and the
``cover-gaps`` mutation fallback) pay their cost in **mutant-verify runs**: each
``_verify_killed`` call does a full-project ``shutil.copytree`` + a pytest
subprocess (:mod:`app.engine.mutation_tester`). On a big real file that scan
fans out to ~31 runs/module across the whole source index, blows past the
external harness limit, and lands an honest NO-OP — the worst outcome for a
buyer, and exactly where a real project needs help most.

This module bounds that fan-out with a single integer counter consumed in
deterministic order. It is **NOT a wall clock**: it bounds *how many* mutant
runs a scan attempts, never *how long* any one run may take. That distinction is
load-bearing for determinism AND for soundness:

* Determinism — the budget is an ``int``; the same project with the same budget
  always spends it on the same mutants in the same (document/sorted) order, so
  the set of mutants examined is byte-identical across machines regardless of how
  fast each pytest run is. A wall clock would make the cut machine-dependent.
* Soundness — ``_verify_killed`` treats a ``TimeoutExpired`` as a KILL
  (mutation_tester.py). A budget that shortened ``verify_timeout`` or interrupted
  a mutant mid-run would corrupt the kill/survive verdict on a slow box. This
  budget *never* touches ``verify_timeout``; it only decides which mutants are
  ATTEMPTED. A mutant that runs gets the same fixed-timeout verdict everywhere.

The counter is mutable so it can be threaded through a whole scan and decremented
as each module spends it; ``exhausted`` lets the caller stop visiting further
modules without ever folding a skipped mutant into the killed/survived split.
``_mutant_cap_for`` is the companion size-aware per-module cap: a pure function
of the source so a 5000-LoC module enumerates fewer mutants while a small module
keeps the full default set (back-compat). Stdlib-only, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["_Budget", "_mutant_cap_for"]


@dataclass
class _Budget:
    """A mutable, deterministic mutant-run counter — a COUNT, not a clock.

    ``remaining`` is the number of ``_verify_killed`` runs the scan may still
    spend. ``spend(n)`` debits it (clamped at zero); ``exhausted`` is True once
    nothing is left. ``can_afford(n)`` asks whether at least ``n`` runs remain —
    used to refuse a module's *baseline* run when the budget can't pay for it,
    so a half-funded module is never examined with a corrupt (baseline-less)
    score. ``spent`` reports how many runs have been debited (for reporting).

    No method consults time or randomness, so two runs over the same project with
    the same starting budget debit the same amount and stop at the same mutant.
    """

    remaining: int
    _start: int = -1

    def __post_init__(self) -> None:
        # Remember the starting allowance once so ``spent`` is exact even after
        # ``remaining`` is clamped at zero by an over-debit.
        if self._start < 0:
            self._start = max(0, self.remaining)
        self.remaining = max(0, self.remaining)

    @property
    def exhausted(self) -> bool:
        """True when no mutant-run allowance is left."""
        return self.remaining <= 0

    @property
    def spent(self) -> int:
        """How many mutant runs have been debited so far (start − remaining)."""
        return self._start - self.remaining

    def can_afford(self, n: int) -> bool:
        """True when at least ``n`` runs remain (``n <= 0`` is always affordable)."""
        return self.remaining >= n

    def spend(self, n: int = 1) -> None:
        """Debit ``n`` runs (no-op for ``n <= 0``), clamped so it never goes
        negative — over-debiting simply leaves the budget exhausted."""
        if n > 0:
            self.remaining = max(0, self.remaining - n)


# Mutant-cap shrink for huge modules. ``mutation_score``'s own default cap is 30;
# a 5000-LoC module would still enumerate up to 30 mutants, each paying a
# full-suite-fallback pytest run. The cap below is a PURE function of the source's
# line count: small/medium files keep the full 30 (byte-identical to today), only
# genuinely large files shrink toward a floor so their per-module cost stays
# bounded. Because ``_collect_sites`` enumerates sites in fixed (line, col,
# operator) order and ``mutation_score`` takes the first ``max_mutants`` of them,
# shrinking the cap deterministically examines the first-N sites in document
# order — it changes HOW MANY survivors are looked at, never the kill/survive
# verdict of any mutant that runs.
_DEFAULT_MUTANT_CAP = 30  # mirrors mutation_score's own default
_MUTANT_CAP_FLOOR = 6     # never drop below this many on a huge file
# Files at or under this many source lines keep the full default cap, so every
# small/medium module is byte-identical to the pre-budget behaviour.
_FULL_CAP_LOC = 400
# A linear taper: above _FULL_CAP_LOC the cap shrinks ~ _FULL_CAP_LOC/loc * 30
# toward the floor, so a 5000-LoC module lands near the floor.
_CAP_SCALE_LOC = _FULL_CAP_LOC * _DEFAULT_MUTANT_CAP


def _mutant_cap_for(source: str) -> int:
    """A deterministic, size-aware ``max_mutants`` cap for one module's source.

    Pure function of the line count, so the same source always yields the same
    cap:

    * ``loc <= _FULL_CAP_LOC`` → ``30`` (the default; small/medium files unchanged);
    * larger files taper down ``_CAP_SCALE_LOC // loc`` toward ``_MUTANT_CAP_FLOOR``.

    The result is clamped to ``[_MUTANT_CAP_FLOOR, _DEFAULT_MUTANT_CAP]`` so a
    huge file still gets a meaningful handful of mutants and a tiny file is never
    inflated past the default. No clock, no randomness — same bytes in, same cap
    out.
    """
    loc = source.count("\n") + 1
    if loc <= _FULL_CAP_LOC:
        return _DEFAULT_MUTANT_CAP
    cap = _CAP_SCALE_LOC // loc
    if cap > _DEFAULT_MUTANT_CAP:
        return _DEFAULT_MUTANT_CAP
    if cap < _MUTANT_CAP_FLOOR:
        return _MUTANT_CAP_FLOOR
    return cap
