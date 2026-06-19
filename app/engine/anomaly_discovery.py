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
  - **find_anomalies** — rank modules by a bounded DEVIATION SCORE built from
    three grounded parts: the SEVERITY of the risk its signals carry (a
    `security` / `correctness-bug` / `sensitive-path` tag weighs far more than a
    purely structural `symbol-hub` / `hub` / `co-change` one — risk outranks
    noise), how RARE its signals are, and how far ABOVE the codebase median its
    breadth sits (asymmetric: unusually MANY signals flag a god-module, unusually
    FEW do NOT — a narrow/empty file is not a risk). A trivial ``__init__.py`` is
    floored out so it can never lead. Each anomaly names the unusual trait(s).

Deviation is in [0, 1]; the score is a fixed blend of three [0, 1] parts whose
weights sum to 1, so it can never exceed its bound. Deterministic: median/
frequency over the fixed tag data, fixed severity weights, every ranking broken
by the module name — same profile → same anomalies. A uniform profile (every
module carries the same fingerprint) has nothing rare, no risk OUTLIER and no
breadth spread, so it yields no anomalies; an empty profile yields ``[]``.
"""

from __future__ import annotations

from typing import Any

# A module needs a real codebase to deviate *from*: with fewer than this many
# tagged modules "rare" is meaningless (everything is unique), so we abstain.
MIN_MODULES = 3
# Blend weights for the three grounded deviation parts (sum to 1 → score in
# [0,1]). SEVERITY dominates so a module carrying a real RISK signal (security,
# correctness bug, …) outranks one that is merely structurally odd-but-safe;
# RARITY and BROADNESS still contribute but cannot drown out severity.
RARITY_WEIGHT = 0.3
BREADTH_WEIGHT = 0.15
SEVERITY_WEIGHT = 0.55
# Only surface modules that actually stand out past this deviation floor.
DEVIATION_FLOOR = 0.15

# Per-tag severity in [0, 1]: how much real risk each signal carries. Risk-bearing
# tags (a `security` finding, a `correctness-bug`, a `sensitive-path`, a
# `critical-untested` gap) are weighted MATERIALLY higher than purely structural
# tags (`symbol-hub`, `hub`, `co-change`) so that risk outranks structural noise.
# A tag absent here contributes the structural floor. Fixed → deterministic.
_SEVERITY_WEIGHTS = {
    # High risk — a human should look NOW.
    "security": 1.0,
    "correctness-bug": 0.95,
    "sensitive-path": 0.9,
    "critical-untested": 0.85,
    # Medium risk — fragility / quality erosion.
    "fragile": 0.6,
    "untested": 0.5,
    "mutable-defaults": 0.5,
    "debt": 0.45,
    "shallow-tests": 0.4,
    "complexity": 0.4,
    "complex-function": 0.4,
    "modernizable": 0.35,
    "high-churn": 0.35,
    "single-author": 0.35,
    # Structural-only — odd shape, not in itself a risk.
    "symbol-hub": 0.15,
    "hub": 0.15,
    "co-change": 0.1,
}
# The weight a tag with no explicit severity entry contributes (structural floor).
_DEFAULT_SEVERITY = 0.15
# A trivial package init (an empty / near-empty ``__init__.py`` carrying at most
# this many signals) is not a risk: it is FLOORED out of the ranking entirely so
# it can never lead. Narrowness alone never makes a file anomalous (see
# ``_breadth_score``); this drops the degenerate package-marker case outright.
_TRIVIAL_INIT_MAX_SIGNALS = 1


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
    """How far ABOVE the median this fingerprint's breadth sits, in [0, 1].

    ASYMMETRIC: only the BROAD side deviates. A module with unusually MANY
    signals is a likely god-module / hotspot worth attention; a module with
    unusually FEW signals (an empty / narrow ``__init__.py``) is not a risk, so
    it contributes 0 here and never gets lifted by mere narrowness. Normalized by
    the largest breadth gap on the codebase so the part stays bounded; a flat
    codebase (every module the same breadth) has ``max_gap == 0`` → 0.
    """
    if max_gap <= 0:
        return 0.0
    excess = size - median_breadth
    if excess <= 0:
        return 0.0
    return min(1.0, excess / max_gap)


def _severity_score(tagset: set[str], freq: dict[str, int], modules: int) -> float:
    """How much UNUSUAL RISK this fingerprint carries, in [0, 1].

    Each tag's contribution is its fixed severity weight scaled by how rare it is
    on this codebase (``1 - frequency/modules``): a HIGH-risk signal (a
    `security` finding) that only a minority of modules carry weighs far more
    than a structural `symbol-hub`, and a risk signal carried by EVERY module
    contributes 0 — a uniformly-risky codebase has no risk *outlier*. The module
    takes the MAX over its tags, so one real risk signal among many structural
    ones is never diluted by averaging. An untagged module carries no risk → 0.0.
    """
    if not tagset or modules <= 0:
        return 0.0
    return max(
        _SEVERITY_WEIGHTS.get(tag, _DEFAULT_SEVERITY)
        * (1.0 - freq.get(tag, 0) / modules)
        for tag in tagset
    )


def _is_trivial_init(module: str, tagset: set[str]) -> bool:
    """A near-empty package marker (``__init__.py`` with ≤1 signal) — not a risk.

    Such files have ~0 statements; surfacing one above a module carrying real
    risk is exactly the severity-blindness this engine guards against, so they
    are floored out of the ranking entirely.
    """
    name = module.rsplit("/", 1)[-1]
    return name == "__init__.py" and len(tagset) <= _TRIVIAL_INIT_MAX_SIGNALS


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
    # Only the BROAD side is a deviation (asymmetric breadth); narrowness is not
    # a risk, so it is never reported as one.
    if size > median_breadth:
        parts.append(f"unusually broad ({size} signals vs median {median_breadth:g})")
    missing = sorted(t for t in norm["typical"] if t not in tagset)
    if missing:
        joined = ", ".join(f"`{t}`" for t in missing[:3])
        parts.append(f"lacks the typical signal(s) {joined}")
    if not parts:
        parts.append("an off-pattern fingerprint")
    return "; ".join(parts) + "."


def _score_module(module: str, tagset: set[str], norm: dict[str, Any],
                  max_gap: float) -> dict[str, Any] | None:
    """Build one anomaly record for a module, or ``None`` if it sits on the norm.

    A trivial ``__init__.py`` (≤1 signal, ~0 statements) is floored out entirely:
    it is never a risk and must never lead the ranking.
    """
    if _is_trivial_init(module, tagset):
        return None
    freq, modules = norm["frequency"], norm["modules"]
    rarity = _rarity_score(tagset, freq, modules)
    breadth = _breadth_score(len(tagset), norm["median_breadth"], max_gap)
    severity = _severity_score(tagset, freq, modules)
    deviation = (RARITY_WEIGHT * rarity + BREADTH_WEIGHT * breadth
                 + SEVERITY_WEIGHT * severity)
    if deviation < DEVIATION_FLOOR:
        return None
    rare = _rare_tags(tagset, freq, modules)
    return {
        "module": module,
        "deviation": round(deviation, 3),
        "rarity": round(rarity, 3),
        "severity": round(severity, 3),
        "why": _why(tagset, norm, len(tagset), rare),
    }


def find_anomalies(profile: Any, top: int = 5) -> list[dict[str, Any]]:
    """Rank modules by deviation from the codebase norm — the outliers, bounded.

    Deviation is ``0.3 * rarity + 0.15 * broadness + 0.55 * severity``, every
    part in [0, 1] and the weights summing to 1, so the score is bounded in
    [0, 1]. SEVERITY dominates → a module carrying a real RISK signal outranks a
    merely structurally-odd-but-safe one; broadness is ASYMMETRIC (only unusually
    MANY signals deviate, never unusually few); a trivial ``__init__.py`` is
    floored out. Modules below ``DEVIATION_FLOOR`` (on-pattern) are dropped.
    Sorted by deviation desc, then severity desc, then rarity desc, then module
    name for a fully deterministic order, capped at ``top``.
    Empty/too-small/uniform profile → ``[]`` (never raises).
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
    anomalies.sort(key=lambda a: (-a["deviation"], -a["severity"],
                                  -a["rarity"], a["module"]))
    return anomalies[:top]
