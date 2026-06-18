"""Anomaly discovery — surface the modules that DEFY the codebase's patterns.

Where ``dream_discovery`` finds what is COMMON ("what travels with what on THIS
codebase"), anomaly discovery finds what is RARE: the modules that don't fit the
dominant fingerprint and so are worth a human's attention. It reads the same
per-module signal tags the dream reads — no new heavy analysis — and asks the
inverse question: which module's signal fingerprint deviates most from the
codebase's deterministic "normal"?

Three deterministic moves, no LLM, stdlib only:

  - **module_profiles** — per-module signal fingerprints lifted from the profile
    (the same tag rows the dream uses), so adding a signal later widens the
    anomaly space with zero code change here too;
  - **dominant_pattern** — the codebase's "normal": per-signal frequency, the
    median fingerprint breadth, and the *typical* fingerprint (the signals a
    plurality of modules carry). This is the baseline every deviation measures
    against;
  - **find_anomalies** — rank modules by a bounded DEVIATION SCORE built from two
    grounded parts: how RARE the signals a module carries are (rare signals, and
    rare combinations of them, weigh more), and how far its breadth sits from the
    codebase median (unusually many OR unusually few signals). Each anomaly names
    the unusual trait(s) in human text.

Deviation is in [0, 1]; the score is a fixed blend of two [0, 1] parts so it can
never exceed its bound. Deterministic: median/frequency over the fixed tag data,
every ranking broken by the module name — same profile → same anomalies. A
uniform profile (every module carries the same fingerprint) has nothing rare and
no breadth spread, so it yields no anomalies; an empty profile yields ``[]``.
"""

from __future__ import annotations

from typing import Any

# A module needs a real codebase to deviate *from*: with fewer than this many
# tagged modules "rare" is meaningless (everything is unique), so we abstain.
MIN_MODULES = 3
# Blend weights for the two grounded deviation parts (sum to 1 → score in [0,1]).
RARITY_WEIGHT = 0.6
BREADTH_WEIGHT = 0.4
# Only surface modules that actually stand out past this deviation floor.
DEVIATION_FLOOR = 0.15


def _add(tags: dict[str, set[str]], module: str, tag: str) -> None:
    """Record that ``module`` carries ``tag`` (ignoring empty module paths)."""
    if not module:
        return
    tags.setdefault(module, set()).add(tag)


_STR_FIELDS = {
    "security_finding_modules": "security",
    "correctness_bug_modules": "correctness-bug",
    "fragile_modules": "fragile",
    "untested_modules": "untested",
    "critical_untested_modules": "critical-untested",
    "hotspot_modules": "complexity",
    "debt_marker_modules": "debt",
    "shallow_tested_modules": "shallow-tests",
    "modernizable_modules": "modernizable",
    "mutable_default_modules": "mutable-defaults",
    "dependency_hubs": "hub",
    "symbol_hubs": "symbol-hub",
    "sensitive_paths": "sensitive-path",
}

_ROW_FIELDS = {
    "churn_hotspots": "high-churn",
    "knowledge_risks": "single-author",
    "hotspot_functions": "complex-function",
}


def module_profiles(profile: Any) -> dict[str, set[str]]:
    """module path → the set of signal tags it carries — its fingerprint.

    Reuses exactly the tag rows the dream reads, so the anomaly view shares the
    dream's signal vocabulary. One line per signal family; adding a row widens
    the anomaly space the same way it widens the discovery space.
    """
    tags: dict[str, set[str]] = {}
    for field, tag in _STR_FIELDS.items():
        for module in (getattr(profile, field, []) or []):
            _add(tags, str(module), tag)
    for field, tag in _ROW_FIELDS.items():
        for row in (getattr(profile, field, []) or []):
            _add(tags, str(row.get("module", "")), tag)
    for cc in (getattr(profile, "change_coupling", []) or []):
        _add(tags, cc.get("a", ""), "co-change")
        _add(tags, cc.get("b", ""), "co-change")
    return tags


def _signal_frequency(profiles: dict[str, set[str]]) -> dict[str, int]:
    """How many modules carry each signal — the base rate rarity divides by."""
    freq: dict[str, int] = {}
    for tagset in profiles.values():
        for tag in tagset:
            freq[tag] = freq.get(tag, 0) + 1
    return freq


def _median(values: list[int]) -> float:
    """Deterministic median of a non-empty integer list (no statistics import)."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def dominant_pattern(profiles: dict[str, set[str]]) -> dict[str, Any]:
    """The codebase's deterministic "normal" — the baseline anomalies deviate from.

    Returns the per-signal frequency, the module count, the median fingerprint
    breadth, and the *typical* fingerprint: the signals carried by a strict
    majority of modules (the shape a normal module has). Empty profile → an empty
    norm with zero modules, so callers can short-circuit without raising.
    """
    if not profiles:
        return {"modules": 0, "frequency": {}, "median_breadth": 0.0, "typical": set()}
    freq = _signal_frequency(profiles)
    count = len(profiles)
    typical = {tag for tag, n in freq.items() if n * 2 > count}
    return {
        "modules": count,
        "frequency": freq,
        "median_breadth": _median([len(ts) for ts in profiles.values()]),
        "typical": typical,
    }


def _rarity_score(tagset: set[str], freq: dict[str, int], modules: int) -> float:
    """How rare this fingerprint's signals are, in [0, 1].

    Each tag contributes ``1 - frequency/modules`` (a signal on every module
    contributes 0; a singleton signal contributes nearly 1); we average over the
    tags so breadth alone doesn't inflate rarity — that is the breadth part's job.
    An untagged module is maximally un-rare → 0.
    """
    if not tagset:
        return 0.0
    total = sum(1.0 - freq.get(tag, 0) / modules for tag in tagset)
    return total / len(tagset)


def _breadth_score(size: int, median_breadth: float, max_gap: float) -> float:
    """How far this fingerprint's breadth sits from the median, in [0, 1].

    Symmetric: unusually MANY or unusually FEW signals both deviate. Normalized
    by the largest breadth gap on the codebase so the part stays bounded; a flat
    codebase (every module the same breadth) has ``max_gap == 0`` → 0.
    """
    if max_gap <= 0:
        return 0.0
    return min(1.0, abs(size - median_breadth) / max_gap)


def _rare_tags(tagset: set[str], freq: dict[str, int], modules: int) -> list[str]:
    """The tags this module carries that a minority of modules carry, rarest first."""
    rare = [t for t in tagset if freq.get(t, 0) * 2 <= modules]
    return sorted(rare, key=lambda t: (freq.get(t, 0), t))


def _why(tagset: set[str], norm: dict[str, Any], size: int,
         rare: list[str]) -> str:
    """Human text naming the unusual trait(s): rare signals and/or odd breadth."""
    parts: list[str] = []
    if rare:
        joined = ", ".join(f"`{t}`" for t in rare[:4])
        parts.append(f"carries rare signal(s) {joined}")
    median_breadth = norm["median_breadth"]
    if size > median_breadth:
        parts.append(f"unusually broad ({size} signals vs median {median_breadth:g})")
    elif size < median_breadth:
        parts.append(f"unusually narrow ({size} signals vs median {median_breadth:g})")
    missing = sorted(t for t in norm["typical"] if t not in tagset)
    if missing:
        joined = ", ".join(f"`{t}`" for t in missing[:3])
        parts.append(f"lacks the typical signal(s) {joined}")
    if not parts:
        parts.append("an off-pattern fingerprint")
    return "; ".join(parts) + "."


def _score_module(module: str, tagset: set[str], norm: dict[str, Any],
                  max_gap: float) -> dict[str, Any] | None:
    """Build one anomaly record for a module, or ``None`` if it sits on the norm."""
    freq, modules = norm["frequency"], norm["modules"]
    rarity = _rarity_score(tagset, freq, modules)
    breadth = _breadth_score(len(tagset), norm["median_breadth"], max_gap)
    deviation = RARITY_WEIGHT * rarity + BREADTH_WEIGHT * breadth
    if deviation < DEVIATION_FLOOR:
        return None
    rare = _rare_tags(tagset, freq, modules)
    return {
        "module": module,
        "deviation": round(deviation, 3),
        "rarity": round(rarity, 3),
        "why": _why(tagset, norm, len(tagset), rare),
    }


def find_anomalies(profile: Any, top: int = 5) -> list[dict[str, Any]]:
    """Rank modules by deviation from the codebase norm — the outliers, bounded.

    Deviation is ``0.6 * rarity + 0.4 * breadth-deviation``, both parts in
    [0, 1], so the score is bounded in [0, 1]. Modules at or below
    ``DEVIATION_FLOOR`` (on-pattern) are dropped. Sorted by deviation desc, then
    rarity desc, then module name for a fully deterministic order, and capped at
    ``top``. Empty/too-small/uniform profile → ``[]`` (never raises).
    """
    if top <= 0:
        return []
    profiles = module_profiles(profile)
    if len(profiles) < MIN_MODULES:
        return []
    norm = dominant_pattern(profiles)
    breadths = [len(ts) for ts in profiles.values()]
    max_gap = max(abs(b - norm["median_breadth"]) for b in breadths)
    anomalies: list[dict[str, Any]] = []
    for module in sorted(profiles):
        record = _score_module(module, profiles[module], norm, max_gap)
        if record is not None:
            anomalies.append(record)
    anomalies.sort(key=lambda a: (-a["deviation"], -a["rarity"], a["module"]))
    return anomalies[:top]
