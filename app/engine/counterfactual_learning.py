"""Counterfactual learning — learn from the fixes that ROLLED BACK.

``proof_history`` records, per fix, an ``outcome`` of ``applied`` /
``rolled_back`` / ``blocked`` together with the cited action and the module it
touched. The reliability view in that module rewards what LANDS. This module is
its mirror image: it mines the fixes that did NOT land (``rolled_back`` and
``blocked``) to learn the *conditions that predict failure*, so a develop-loop
can decline a predictably-doomed fix BEFORE spending an apply+rollback on it.

The unit of learning is a **failure signature**: an ``(action_type,
module-trait)`` pair, where a *trait* is a coarse, path-derived property of the
module a fix acted on (e.g. ``test`` for a test file, ``package-init`` for an
``__init__``, ``deep`` for a deeply-nested path). For each signature we count
how often a matching fix was *attempted* and how often it *failed* (rolled back
or blocked); the ``failure_rate`` is failures / attempts in [0, 1]. A signature
is marked ``avoid`` only when its failure rate clears a fixed threshold AND it
has enough attempts to be trustworthy — both constants below.

Everything is **pure and deterministic**: same history → same output, sorted
keys, fixed thresholds, no time/random, no I/O. An empty history, a history
with no failures, or malformed rows yield empty maps / avoid-nothing and never
raise. Inputs are the proof dicts produced by ``proof_history`` (the list a
``load_proof_history`` call returns), but any list of proof-shaped dicts works.
"""

from __future__ import annotations

from typing import Any

# Outcomes that count as a FAILURE for counterfactual learning. ``applied`` is
# the only landing outcome; everything else is non-landing (see proof_history,
# which folds unknown outcomes into ``blocked``).
_FAILURE_OUTCOMES = ("rolled_back", "blocked")
_LANDING_OUTCOME = "applied"
# A fix the closed-loop guard DECLINED before any apply attempt. It is neither a
# landing nor a failure — it was never tried — so it must not feed the failure
# stats (counting it would self-confirm the avoidance forever). Excluded from
# the tally entirely.
_SKIPPED_OUTCOME = "skipped_learned"

# A signature is worth avoiding only above this failure rate AND with at least
# this many attempts — both fixed so the verdict is deterministic and a single
# unlucky rollback never condemns an action.
_AVOID_FAILURE_RATE = 0.6
_MIN_ATTEMPTS = 3

# Placeholder buckets for fixes that name no action / no module. Kept so an
# attribute-less failure is still counted deterministically rather than dropped.
_UNKNOWN_ACTION = "<unknown>"
_UNKNOWN_TRAIT = "generic"

# How many near-miss insight lines we emit (the worst signatures first).
_MAX_INSIGHTS = 8


def _iter_fixes(history: list[dict] | None) -> list[dict]:
    """Flatten the ``fixes`` lists across all proofs, skipping non-dict rows."""
    fixes: list[dict] = []
    for proof in history or []:
        if not isinstance(proof, dict):
            continue
        for fix in proof.get("fixes") or []:
            if isinstance(fix, dict):
                fixes.append(fix)
    return fixes


def _action_of(fix: dict) -> str:
    """The action type a fix cites (``finding.action``), or a placeholder."""
    finding = fix.get("finding")
    action = finding.get("action") if isinstance(finding, dict) else ""
    return str(action) if action else _UNKNOWN_ACTION


def _module_of(fix: dict) -> str:
    """The module a fix acted on: finding ``target`` else first changed file."""
    finding = fix.get("finding")
    target = finding.get("target") if isinstance(finding, dict) else ""
    if target:
        return str(target)
    changed = fix.get("changed_files") or []
    if isinstance(changed, list) and changed:
        return str(changed[0])
    return ""


def module_traits(module: str) -> set[str]:
    """Coarse, path-derived traits of a module — the second half of a signature.

    Deterministic and dependency-free: traits come from the path's shape and
    name, not from any cross-module analysis (a develop-loop with richer signals
    can pass its own trait set to :func:`should_avoid`). An empty/blank module
    yields ``{_UNKNOWN_TRAIT}`` so it still groups deterministically."""
    name = (module or "").strip().replace("\\", "/").lower()
    if not name:
        return {_UNKNOWN_TRAIT}
    base = name.rsplit("/", 1)[-1]
    is_test = base.startswith("test_") or "/tests/" in name or name.startswith("tests/")
    flags = {
        "test": is_test,
        "package-init": base == "__init__.py",
        "deep": name.count("/") >= 3,
        "entrypoint": base in ("__main__.py", "cli.py", "main.py"),
    }
    traits = {trait for trait, present in flags.items() if present}
    return traits or {_UNKNOWN_TRAIT}


def _signature_keys(action: str, traits: set[str]) -> list[str]:
    """The deterministic signature strings for an action across its traits."""
    return [f"{action} | {trait}" for trait in sorted(traits)]


def _bump(table: dict[str, list[int]], key: str, failed: bool) -> None:
    """Increment ``[attempts, failures]`` for ``key``, creating it on first sight."""
    slot = table.setdefault(key, [0, 0])
    slot[0] += 1
    if failed:
        slot[1] += 1


def _tally(history: list[dict] | None) -> dict[str, list[int]]:
    """Aggregate every fix into ``{signature: [attempts, failures]}``.

    A fix contributes to one signature per trait of its module, so a fix on a
    module with two traits counts toward both — that is the intended fan-out, it
    lets a trait like ``hub``/``test`` accrue evidence across actions."""
    table: dict[str, list[int]] = {}
    for fix in _iter_fixes(history):
        outcome = fix.get("outcome")
        if outcome == _SKIPPED_OUTCOME:
            continue  # never attempted -> contributes no evidence either way
        failed = outcome in _FAILURE_OUTCOMES or outcome != _LANDING_OUTCOME
        action = _action_of(fix)
        traits = module_traits(_module_of(fix))
        for key in _signature_keys(action, traits):
            _bump(table, key, failed)
    return table


def failure_signatures(history: list[dict] | None) -> dict[str, dict[str, Any]]:
    """Map each ``"action | trait"`` signature to its failure statistics.

    Each value is ``{"attempts", "failures", "failure_rate", "avoid"}`` where
    ``failure_rate`` is failures / attempts bounded to [0, 1] and ``avoid`` is a
    deterministic verdict: ``True`` only when the rate clears
    ``_AVOID_FAILURE_RATE`` AND attempts reach ``_MIN_ATTEMPTS``. Keys are
    emitted sorted so iteration order is stable. Empty/missing history → ``{}``;
    never raises."""
    table = _tally(history)
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(table):
        attempts, failures = table[key]
        rate = round(failures / attempts, 4) if attempts else 0.0
        out[key] = {
            "attempts": attempts,
            "failures": failures,
            "failure_rate": rate,
            "avoid": rate >= _AVOID_FAILURE_RATE and attempts >= _MIN_ATTEMPTS,
        }
    return out


def should_avoid(
    signatures: dict[str, dict[str, Any]],
    action_type: str,
    traits: Any,
) -> bool:
    """Would a fix of ``action_type`` on a module with ``traits`` predictably fail?

    Consults the ``failure_signatures`` map: returns ``True`` if ANY of the
    action's signatures for the given traits is flagged ``avoid``. ``traits`` may
    be any iterable of trait strings (a caller can supply richer traits than
    :func:`module_traits` derives). An empty signature map, unknown action, or
    empty traits → ``False`` (avoid nothing). Deterministic; never raises."""
    if not signatures:
        return False
    action = str(action_type) if action_type else _UNKNOWN_ACTION
    trait_set = {str(t) for t in (traits or ())} or {_UNKNOWN_TRAIT}
    for key in _signature_keys(action, trait_set):
        entry = signatures.get(key)
        if isinstance(entry, dict) and entry.get("avoid"):
            return True
    return False


def _insight_line(action: str, trait: str, failures: int, attempts: int) -> str:
    """One human-readable lesson for an avoid-worthy signature."""
    return (
        f"action '{action}' rolls back on {trait} modules "
        f"{failures}/{attempts} times — gate it (e.g. add a test first) "
        f"or skip it on {trait} targets"
    )


def near_miss_insights(history: list[dict] | None) -> list[str]:
    """Deterministic, human-readable lessons from the avoid-worthy failures.

    One line per signature whose ``avoid`` verdict is ``True``, ordered worst
    first (highest failure rate, then most attempts, then signature name) and
    capped at ``_MAX_INSIGHTS``. Empty/missing history or no avoid-worthy
    signature → ``[]``; never raises."""
    signatures = failure_signatures(history)
    flagged = [
        (key, stats)
        for key, stats in signatures.items()
        if stats.get("avoid")
    ]
    flagged.sort(
        key=lambda item: (
            -item[1]["failure_rate"],
            -item[1]["attempts"],
            item[0],
        )
    )
    lines: list[str] = []
    for key, stats in flagged[:_MAX_INSIGHTS]:
        action, _, trait = key.partition(" | ")
        lines.append(
            _insight_line(action, trait, stats["failures"], stats["attempts"])
        )
    return lines
