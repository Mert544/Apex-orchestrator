"""Value-landed — the buyer's-eye measurement of what a develop pass REALIZED.

Apex already produces every input this needs; this module only FOLDS it. It
answers ONE question a buyer asks: *of the change Apex actually landed-and-held
here, how much VALUE (the way a buyer ranks it) held, and how honestly?* It is a
pure, deterministic fold over the SAME proof-of-fix ``fixes`` list the tamper
seal (:func:`app.engine.proof_of_fix.proof_hash`) and the manifest consume — so
the value view can never disagree with the evidence it scores.

The buyer value of a change is the frozen ``move_value`` prior (Tier-1 lands new
working code 0.66–1.00; Tier-2 structural 0.32–0.60; Tier-3 idiom 0.15–0.25). The
HONESTY of the landing is read from the recorded coverage level, NEVER blended:

  * **verified** — the move landed (``outcome == "applied"`` AND no rollback) and
    a test exercises it (coverage ``function`` / ``module`` / ``test-change``).
    Only this bucket sums into the verified value total — what the suite EARNED.
  * **weak** — landed-and-held, suite green, but NO test references the change
    (coverage ``none``). Counted SEPARATELY, never in the verified total.
  * **unverified** — landed but nothing could vouch for it (``baseline-red`` /
    ``no-suite``). Zero toward verified value.

NEVER-FAKE-GREEN is the core gate: a move contributes value ONLY when it was
``applied`` AND ``rollback.occurred`` is False. A rolled-back / blocked / declined
move — work that did NOT hold — contributes ZERO to every bucket. A move that
auto-rolled-back already carries ``rollback.occurred`` True, so this metric
STRUCTURALLY cannot credit reverted (even external-code) changes.

Two adapters, one scoring core (the ``move_value`` / ``objective_value`` split):
:func:`value_landed` folds the persisted proof records (cross-run); the thin
:func:`value_landed_from_session` adapter scores an in-memory ``SessionReport``
(single run). Both share the bucketing/tier/rounding so they can never diverge.

Deterministic and zero-cost: a frozen-table lookup plus a dict fold — no clock,
no random, no AST, no hash-order dependence. Floats are rounded to 4 dp (like
``scored_move_value``) and ``top_contributions`` is sorted by the TOTAL key
``(-value, operator, target)``, so the same evidence in yields a byte-identical
metric out. Stdlib-only, no LLM. The only import is the pure ``move_value`` leaf.
"""

from __future__ import annotations

from typing import Any

from app.engine.move_value import move_value

__all__ = [
    "value_landed",
    "value_landed_from_session",
    "value_coverage_gaps",
    "VALUE_SCHEMA",
    "TIER1_MIN",
    "TIER2_MIN",
]

VALUE_SCHEMA = "apex-value-landed"

# Buyer-tier cutoffs over the frozen ``move_value`` score, matching the tiers the
# table itself documents: Tier 1 lands new code (>= 0.66), Tier 2 is structural
# (0.32–0.60), Tier 3 is idiom (<= 0.25). A score is bucketed by the SAME prior
# the verified total uses, so a move's tier and its value can never disagree.
TIER1_MIN = 0.66
TIER2_MIN = 0.32

# The three honesty buckets, keyed by the recorded coverage level. ``test-change``
# joins ``function``/``module`` as genuinely verified; ``none`` is weak (green but
# uncovered); the inconclusive levels (``baseline-red``/``no-suite``) are
# unverified. Any other / missing level is treated as weak's safer side — never
# silently promoted to verified.
_VERIFIED_LEVELS = frozenset({"function", "module", "test-change"})
_UNVERIFIED_LEVELS = frozenset({"baseline-red", "no-suite"})


def _tier_of(value: float) -> str:
    """The buyer tier name for a ``move_value`` score (Tier-1/2/3 cutoffs)."""
    if value >= TIER1_MIN:
        return "tier1"
    if value >= TIER2_MIN:
        return "tier2"
    return "tier3"


def _empty_buckets() -> dict[str, dict[str, Any]]:
    """The zeroed verified/weak/unverified accumulators (stable key order)."""
    return {
        "verified": {"value": 0.0, "moves": 0},
        "weak": {"value": 0.0, "moves": 0},
        "unverified": {"value": 0.0, "moves": 0},
    }


def _level_bucket(level: str) -> str:
    """Map a recorded coverage level onto its honesty bucket name."""
    if level in _VERIFIED_LEVELS:
        return "verified"
    if level in _UNVERIFIED_LEVELS:
        return "unverified"
    return "weak"


def _coverage_level(rec: dict) -> str:
    """The recorded coverage level of a record, or ``none`` when unrecorded.

    Reuses the ``verification.strength.level`` field ``_coverage_of`` reads, so
    the value bucket can never contradict the proof manifest's by-coverage tally.
    """
    strength = (rec.get("verification") or {}).get("strength") or {}
    return strength.get("level") or "none"


def _held(rec: dict) -> bool:
    """The LANDED-AND-HELD gate (never-fake-green): the move was applied AND not
    rolled back. A blocked / rolled-back / declined move did NOT hold, so it
    contributes ZERO value — reverted work is not value landed."""
    if rec.get("outcome") != "applied":
        return False
    return not (rec.get("rollback") or {}).get("occurred", False)


def _score(buckets, by_tier, moves_by_tier, top, bucket, value, operator, target):
    """Accumulate one held move's value into its honesty bucket and (verified
    only) its buyer tier, and record its contribution row. A flat helper so the
    fold body stays a single shallow loop."""
    buckets[bucket]["value"] = round(buckets[bucket]["value"] + value, 4)
    buckets[bucket]["moves"] += 1
    if bucket == "verified":
        tier = _tier_of(value)
        by_tier[tier] = round(by_tier[tier] + value, 4)
        moves_by_tier[tier] += 1
    top.append({"operator": operator, "value": value, "target": target,
                "bucket": bucket})


def _verdict(buckets: dict[str, dict[str, Any]]) -> str:
    """One honest line a buyer reads at a glance — verified total, then the split."""
    verified = buckets["verified"]
    if verified["moves"] == 0 and buckets["weak"]["moves"] == 0 \
            and buckets["unverified"]["moves"] == 0:
        return "no value landed"
    return (
        f"{verified['value']:.2f} verified value landed across "
        f"{verified['moves']} move(s); {buckets['weak']['value']:.2f} weak, "
        f"{buckets['unverified']['value']:.2f} unverified"
    )


def _assemble(buckets, by_tier, moves_by_tier, top) -> dict:
    """Build the deterministic value-landed dict from the folded accumulators.

    ``top_contributions`` is sorted by the TOTAL key ``(-value, operator,
    target)`` so there are NO clock/insertion-order ties — the metric is
    byte-identical for the same evidence regardless of input order."""
    top.sort(key=lambda c: (-c["value"], c["operator"], c["target"]))
    return {
        "schema": VALUE_SCHEMA,
        "value_landed_verified": buckets["verified"]["value"],
        "value_landed_weak": buckets["weak"]["value"],
        "value_landed_unverified": buckets["unverified"]["value"],
        "moves_verified": buckets["verified"]["moves"],
        "moves_weak": buckets["weak"]["moves"],
        "moves_unverified": buckets["unverified"]["moves"],
        "by_tier": by_tier,
        "moves_by_tier": moves_by_tier,
        "top_contributions": top,
        "verdict": _verdict(buckets),
    }


def _fold(rows: list[tuple[str, str, str]]) -> dict:
    """The single scoring CORE: fold ``(operator, target, bucket)`` rows — already
    gated to held moves — into the value-landed dict. Both adapters feed this."""
    buckets = _empty_buckets()
    by_tier = {"tier1": 0.0, "tier2": 0.0, "tier3": 0.0}
    moves_by_tier = {"tier1": 0, "tier2": 0, "tier3": 0}
    top: list[dict[str, Any]] = []
    for operator, target, bucket in rows:
        value = round(move_value(operator), 4)
        _score(buckets, by_tier, moves_by_tier, top, bucket, value, operator,
               target)
    return _assemble(buckets, by_tier, moves_by_tier, top)


def value_landed(records: Any) -> dict:
    """The deterministic value-landed metric over proof-of-fix ``fixes`` records.

    Accepts a full proof artifact (its ``fixes`` are read) or a bare list of fix
    records — the SAME input ``proof_hash`` / ``proof_manifest`` consume. Counts a
    move's :func:`~app.engine.move_value.move_value` ONLY when it landed-and-held
    (``outcome == "applied"`` AND ``rollback.occurred`` False), bucketed by the
    recorded coverage level into verified / weak / unverified (never blended) and,
    for verified moves, by buyer tier. Returns a stable, rounded dict; the empty /
    nothing-held case yields all-zero buckets and a "no value landed" verdict
    without crashing. Deterministic: no clock, no random, no hash-order."""
    if isinstance(records, dict):
        records = records.get("fixes") or []
    rows: list[tuple[str, str, str]] = []
    for rec in records or []:
        if not _held(rec):
            continue
        finding = rec.get("finding") or {}
        rows.append((
            finding.get("operator") or "",
            finding.get("target") or "",
            _level_bucket(_coverage_level(rec)),
        ))
    return _fold(rows)


# The live-session tier -> honesty bucket map. ``SessionMove.tier`` is already the
# coverage-aware verdict (``_tier_for``): verified when a test exercises the
# change, weak when green-but-uncovered, no-suite when nothing ran. A landed move
# is the only thing that reaches ``SessionReport`` (a failed gate was rolled back
# and surfaced as a refusal), so every reported move is held by construction.
_SESSION_TIER_BUCKET = {
    "verified": "verified",
    "weak": "weak",
    "no-suite": "unverified",
}


def value_landed_from_session(report: Any) -> dict:
    """The value-landed metric over an in-memory ``SessionReport`` (single run).

    The live ``apex develop session`` path carries ``SessionMove.operator`` and
    ``.tier`` directly, so this adapter maps each landed move's tier onto the same
    verified / weak / unverified buckets and feeds the ONE scoring core
    :func:`value_landed` uses — one fold, two adapters. Every reported move
    already LANDED (a failed gate was rolled back, never reported), so no
    held-gate is needed here. Same determinism contract."""
    rows: list[tuple[str, str, str]] = []
    for obj in getattr(report, "objectives", None) or []:
        for mv in getattr(obj, "moves", None) or []:
            bucket = _SESSION_TIER_BUCKET.get(getattr(mv, "tier", ""), "weak")
            rows.append((getattr(mv, "operator", "") or "",
                         getattr(mv, "target", "") or "", bucket))
    return _fold(rows)


def value_coverage_gaps(objectives: Any = None) -> list[str]:
    """The value-coverage TRIPWIRE: registered objectives with NO explicit tier.

    The value analogue of the north-star manifest tripwire. ``move_value`` falls
    back to ``DEFAULT_VALUE`` for an unknown operator, so an objective could be
    silently mid-valued; this surfaces the gap loudly instead. An objective is
    covered when its operator (the explicit ``OBJECTIVE_OPERATOR`` map, else the
    self-registering dash->underscore convention) carries an explicit
    ``OPERATOR_VALUE`` row. When no objective list is supplied, the default is
    built from ``develop_registry`` alone (``BUILTIN_OBJECTIVE_NAMES`` union
    ``registered_specs()``) — the SAME set ``objective_compiler.
    available_objectives()`` returns, without importing ``objective_compiler``
    itself (whose transform imports would close a static cycle back through
    ``value_reliability``, which this module is the never-fake-green bucketer
    for). A list may be injected (the seam tests use). Returns the SORTED
    untiered names (empty == clean). Pure and deterministic: no clock, no
    random, no network."""
    from app.engine.develop_registry import BUILTIN_OBJECTIVE_NAMES, registered_specs
    from app.engine.move_value import OBJECTIVE_OPERATOR, OPERATOR_VALUE

    if objectives is None:
        objectives = BUILTIN_OBJECTIVE_NAMES | set(registered_specs())
    gaps: set[str] = set()
    for name in objectives or []:
        operator = OBJECTIVE_OPERATOR.get(name, name.replace("-", "_"))
        if operator not in OPERATOR_VALUE:
            gaps.add(name)
    return sorted(gaps)
