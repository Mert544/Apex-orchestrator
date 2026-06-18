"""Proof-of-Fix history — learning what Apex reliably fixes on *this* project.

Every maintenance pass leaves a machine-readable evidence trail (see
``proof_of_fix.py``): a ``.apex/proof-of-fix.json`` recording, per fix, the
finding it cited, the transform applied, and the ``outcome`` — ``applied``,
``rolled_back``, or ``blocked``. Over many passes those artifacts accumulate
(the current proof plus any archived ones) into a track record.

This module reads that track record and distils what Apex has LEARNED about
fixing this codebase: which *action types* (and which *modules*) tend to land
cleanly versus roll back or get blocked. It is the proof-grounded complement to
``idea_memory.py`` — that module records outcomes from a live ``apply_plan``
summary; this one reconstructs the same signal *after the fact* from the
durable proof artifacts, so a fresh process (or a reviewer) can read reliability
without the original run's in-memory state.

Everything here is **pure and deterministic**: same proof files → same output,
no time/random, no I/O beyond reading the named JSON files. Missing directory,
unreadable files, malformed JSON, or a wrong schema are tolerated by skipping —
an empty or absent history yields empty/neutral results and never raises. The
reliability ratio is the share of *decided* outcomes that landed (applied vs.
applied+rolled_back+blocked), always bounded to [0, 1].
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.engine.proof_of_fix import SCHEMA

# The three terminal outcomes a proof records per fix (proof_of_fix._fix_record).
_OUTCOMES = ("applied", "rolled_back", "blocked")
# Placeholder bucket when a fix carries no action/module — kept so an
# attribute-less fix is still counted (and counted deterministically).
_UNKNOWN = "<unknown>"


def load_proof_history(root: str | Path) -> list[dict]:
    """Read every readable apex-proof-of-fix JSON under ``<root>/.apex/``.

    Returns the validated proof dicts (``schema == SCHEMA``) sorted
    deterministically: by ``generated_at`` then by filename, so an order is
    defined even when timestamps are absent or tie. A missing ``.apex`` dir,
    unreadable files, malformed JSON, or non-matching schema are tolerated by
    skipping — the result is then ``[]``. Never raises."""
    apex_dir = Path(root) / ".apex"
    if not apex_dir.is_dir():
        return []
    loaded: list[tuple[str, str, dict]] = []
    for path in apex_dir.glob("*.json"):
        proof = _read_proof(path)
        if proof is None:
            continue
        ts = str(proof.get("generated_at") or "")
        loaded.append((ts, path.name, proof))
    loaded.sort(key=lambda item: (item[0], item[1]))
    return [proof for _, _, proof in loaded]


def _read_proof(path: Path) -> dict | None:
    """Parse one proof file, returning it only if it is a valid proof dict.

    Tolerates unreadable files and malformed JSON (returns ``None``)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("schema") == SCHEMA:
        return data
    return None


def _iter_fixes(history: list[dict]) -> list[dict]:
    """Flatten the ``fixes`` lists across all proofs, skipping non-dict rows."""
    fixes: list[dict] = []
    for proof in history or []:
        for fix in proof.get("fixes") or []:
            if isinstance(fix, dict):
                fixes.append(fix)
    return fixes


def _outcome_of(fix: dict) -> str:
    """The recorded terminal outcome, defaulting unknown values to ``blocked``.

    ``proof_of_fix`` only ever writes one of ``_OUTCOMES``; an out-of-vocabulary
    value (a hand-edited or future proof) is folded into ``blocked`` so it still
    counts as a non-landing rather than being silently dropped."""
    outcome = fix.get("outcome")
    return outcome if outcome in _OUTCOMES else "blocked"


def _action_of(fix: dict) -> str:
    """The action type a fix cites (``finding.action``), or a stable placeholder."""
    finding = fix.get("finding") or {}
    action = finding.get("action") if isinstance(finding, dict) else ""
    return action or _UNKNOWN


def _module_of(fix: dict) -> str:
    """The module a fix acted on: the finding ``target`` if present, else the
    first ``changed_files`` entry, else a stable placeholder. Deterministic."""
    finding = fix.get("finding") or {}
    target = finding.get("target") if isinstance(finding, dict) else ""
    if target:
        return str(target)
    changed = fix.get("changed_files") or []
    if isinstance(changed, list) and changed:
        return str(changed[0])
    return _UNKNOWN


def _blank_tally() -> dict[str, int]:
    """A fresh per-key counter with one slot per terminal outcome."""
    return {outcome: 0 for outcome in _OUTCOMES}


def _reliability(tally: dict[str, int]) -> float:
    """Share of decided outcomes that LANDED — applied / (sum of all), in [0, 1].

    Zero total (no decided outcomes) is a neutral ``0.0`` (no evidence), never a
    division error. The denominator counts every terminal outcome, so the result
    is always a bounded ratio."""
    total = sum(tally.get(outcome, 0) for outcome in _OUTCOMES)
    if total <= 0:
        return 0.0
    return round(tally["applied"] / total, 4)


def _bump(table: dict[str, dict[str, int]], key: str, outcome: str) -> None:
    """Increment ``table[key][outcome]``, creating the tally on first sight."""
    table.setdefault(key, _blank_tally())[outcome] += 1


def _grouped(history: list[dict], key_fn: Any) -> dict[str, dict[str, Any]]:
    """Aggregate fixes into ``{key: {applied, rolled_back, blocked, total,
    reliability}}`` using ``key_fn`` to derive each fix's bucket. Keys are
    emitted sorted so the mapping order is deterministic."""
    tallies: dict[str, dict[str, int]] = {}
    for fix in _iter_fixes(history):
        _bump(tallies, key_fn(fix), _outcome_of(fix))
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(tallies):
        tally = tallies[key]
        total = sum(tally[outcome] for outcome in _OUTCOMES)
        out[key] = {**tally, "total": total, "reliability": _reliability(tally)}
    return out


def summarise_fix_track_record(history: list[dict]) -> dict:
    """Deterministic aggregate of what the proof history says Apex can fix here.

    Returns counts of ``applied`` / ``rolled_back`` / ``blocked`` (plus
    ``total`` and a bounded ``reliability`` ratio) broken down two ways —
    ``by_action`` (the action type the fix cited) and ``by_module`` (the file it
    acted on) — alongside flat ``totals`` across every recorded fix. Empty or
    missing history yields zeroed totals and empty breakdowns; never raises."""
    by_action = _grouped(history, _action_of)
    by_module = _grouped(history, _module_of)
    totals = _blank_tally()
    for fix in _iter_fixes(history):
        totals[_outcome_of(fix)] += 1
    grand = sum(totals[outcome] for outcome in _OUTCOMES)
    return {
        "proofs": len(history or []),
        "fixes": grand,
        "totals": {**totals, "total": grand, "reliability": _reliability(totals)},
        "by_action": by_action,
        "by_module": by_module,
    }


def learned_reliability(history: list[dict]) -> dict[str, float]:
    """A bounded [0, 1] reliability score per action type from the track record.

    Each score is the share of that action's recorded outcomes that landed
    (applied vs. applied + rolled_back + blocked) — the signal a develop-loop
    can consult to prioritise fixes that historically stick on this project. The
    placeholder bucket for action-less fixes is omitted so callers only see real
    action types. Empty/missing history → ``{}``; never raises."""
    return {
        action: stats["reliability"]
        for action, stats in _grouped(history, _action_of).items()
        if action != _UNKNOWN
    }
