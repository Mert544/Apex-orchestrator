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
    three grounded parts: how RARE the signals a module carries are (rare
    signals, and rare combinations of them, weigh more), how unusually MANY
    signals it carries (asymmetric breadth — only an over-broad fingerprint
    deviates), and how SEVERE its rare signals are (a rare ``security`` /
    ``correctness-bug`` / ``sensitive-path`` / ``critical-untested`` tag dwarfs a
    rare ``symbol-hub`` / ``hub`` / ``co-change`` one). Each anomaly names the
    unusual trait(s) in human text and reports its ``severity``.

SEVERITY-AWARE, ASYMMETRIC ranking (the whole point of this organ): noise — an
empty ``__init__.py`` or a clean structural hub — must NOT outrank a module
carrying ``pickle.loads`` / SQL-injection / ``eval``. Two grounded fixes make
that hold deterministically:

  - **asymmetric breadth**: only an UNUSUALLY BROAD fingerprint raises the score
    (``max(0, size - median)``); a narrow module (a trivial ``__init__``) gets 0
    from breadth, so it can no longer score "as anomalous as" an over-broad one;
  - **per-tag severity**: each rare tag is weighted by how risky it is. A rare
    risk tag (security/correctness-bug/sensitive-path/critical-untested/fragile/
    debt) dominates; a rare structural tag (symbol-hub/hub/co-change) or an
    unknown tag contributes little. Severity is RARITY-GATED — a ubiquitous tag
    contributes 0 no matter how risky its kind — so the "uniform profile → []"
    invariant is preserved.

Deviation is the weighted blend of three [0, 1] parts (weights summing to 1) so
it can never exceed its bound. Deterministic: median/frequency over the fixed
tag data, every ranking broken by the module name — same profile → same
anomalies. A uniform profile (every module carries the same fingerprint) has
nothing rare, no over-breadth and no rarity-gated severity, so it yields no
anomalies; an empty profile yields ``[]``. Trivial ``__init__.py`` modules
carrying at most one signal are floored out of the ranking entirely.
"""

from __future__ import annotations

from typing import Any

# A module needs a real codebase to deviate *from*: with fewer than this many
# tagged modules "rare" is meaningless (everything is unique), so we abstain.
MIN_MODULES = 3
# Blend weights for the three grounded deviation parts (sum to 1 → score in
# [0, 1]). Rarity and severity together carry the risk signal; breadth is a
# lighter structural nudge so an over-broad fingerprint still registers without
# letting raw signal-count drown out a rare risk tag.
RARITY_WEIGHT = 0.4
BREADTH_WEIGHT = 0.2
SEVERITY_WEIGHT = 0.4
# Only surface modules that actually stand out past this deviation floor.
DEVIATION_FLOOR = 0.15

# Per-tag severity weight in [0, 1]: how much a RARE instance of this signal
# should pull a module up the ranking. Risk-bearing signals (the ones a human
# must look at first — code execution, SQL injection, sensitive paths, untested
# critical code, latent bugs, accumulating debt) weigh high; purely structural
# signals (a module being a symbol/dependency hub, or co-changing) weigh low; an
# unknown/unmapped tag defaults low so a new structural signal never inflates a
# score until it is deliberately classified.
_SEVERITY_WEIGHTS = {
    "security": 1.0,
    "correctness-bug": 1.0,
    "sensitive-path": 1.0,
    "critical-untested": 1.0,
    "fragile": 0.8,
    "debt": 0.7,
    "complexity": 0.6,
    "complex-function": 0.6,
    "mutable-defaults": 0.6,
    "untested": 0.5,
    "shallow-tests": 0.5,
    "modernizable": 0.4,
    "high-churn": 0.4,
    "single-author": 0.4,
    "co-change": 0.2,
    "hub": 0.2,
    "symbol-hub": 0.2,
}
# Severity for a tag not named above (a future / structural signal): low.
_DEFAULT_SEVERITY = 0.2

# A trivial module (an empty/near-empty ``__init__.py``) carries at most this
# many signals: it is structurally uninteresting and must never rank as an
# anomaly, so it is floored out before scoring.
TRIVIAL_BREADTH = 1
_TRIVIAL_SUFFIX = "__init__.py"


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


def _severity_weight(tag: str) -> float:
    """How risky a RARE instance of ``tag`` is, in [0, 1] (unknown → low)."""
    return _SEVERITY_WEIGHTS.get(tag, _DEFAULT_SEVERITY)


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


def _rarity(tag: str, freq: dict[str, int], modules: int) -> float:
    """How rare ``tag`` is, in [0, 1]: ``1 - frequency/modules`` (ubiquitous → 0)."""
    return 1.0 - freq.get(tag, 0) / modules


def _rarity_score(tagset: set[str], freq: dict[str, int], modules: int) -> float:
    """How rare this fingerprint's signals are, in [0, 1].

    Each tag contributes ``1 - frequency/modules`` (a signal on every module
    contributes 0; a singleton signal contributes nearly 1); we average over the
    tags so breadth alone doesn't inflate rarity — that is the breadth part's job.
    An untagged module is maximally un-rare → 0.
    """
    if not tagset:
        return 0.0
    total = sum(_rarity(tag, freq, modules) for tag in tagset)
    return total / len(tagset)


def _severity_score(tagset: set[str], freq: dict[str, int], modules: int) -> float:
    """How SEVERE this fingerprint's rare signals are, in [0, 1].

    Each tag contributes ``severity_weight(tag) * rarity(tag)`` — its risk class
    scaled by how unusual it is on this codebase — averaged over the tags. The
    rarity gate is the load-bearing part: a ubiquitous tag has rarity 0, so it
    contributes 0 no matter how risky its kind, which keeps the "uniform profile
    → []" invariant intact. A rare risk tag (severity 1.0) therefore dominates a
    rare structural tag (severity 0.2). An untagged module → 0.
    """
    if not tagset:
        return 0.0
    total = sum(
        _severity_weight(tag) * _rarity(tag, freq, modules) for tag in tagset
    )
    return total / len(tagset)


def _breadth_score(size: int, median_breadth: float, max_gap: float) -> float:
    """How far ABOVE the median this fingerprint's breadth sits, in [0, 1].

    ASYMMETRIC: only an unusually BROAD fingerprint deviates — a narrow module
    (fewer signals than the median, e.g. a trivial ``__init__``) scores 0, so it
    can never rank as anomalous as a genuinely over-broad module. Normalized by
    the largest *over-breadth* gap on the codebase so the part stays bounded; a
    flat codebase (no module broader than the median) has ``max_gap == 0`` → 0.
    """
    if max_gap <= 0:
        return 0.0
    over = size - median_breadth
    if over <= 0:
        return 0.0
    return min(1.0, over / max_gap)


def _rare_tags(tagset: set[str], freq: dict[str, int], modules: int) -> list[str]:
    """The tags this module carries that a minority of modules carry, rarest first.

    Ordered so the rarest, MOST SEVERE tags lead the human-facing ``why``: by
    descending severity, then ascending frequency (rarer first), then name.
    """
    rare = [t for t in tagset if freq.get(t, 0) * 2 <= modules]
    return sorted(
        rare,
        key=lambda t: (-_severity_weight(t), freq.get(t, 0), t),
    )


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


def _is_trivial(module: str, tagset: set[str]) -> bool:
    """A near-empty ``__init__.py`` (≤ TRIVIAL_BREADTH signals): never an anomaly."""
    return module.endswith(_TRIVIAL_SUFFIX) and len(tagset) <= TRIVIAL_BREADTH


def _score_module(module: str, tagset: set[str], norm: dict[str, Any],
                  max_gap: float) -> dict[str, Any] | None:
    """Build one anomaly record for a module, or ``None`` if it sits on the norm.

    Trivial ``__init__.py`` modules (≤ TRIVIAL_BREADTH signals) are floored out
    before scoring so structural noise never crowds out real risk.
    """
    if _is_trivial(module, tagset):
        return None
    freq, modules = norm["frequency"], norm["modules"]
    rarity = _rarity_score(tagset, freq, modules)
    severity = _severity_score(tagset, freq, modules)
    breadth = _breadth_score(len(tagset), norm["median_breadth"], max_gap)
    deviation = (
        RARITY_WEIGHT * rarity
        + BREADTH_WEIGHT * breadth
        + SEVERITY_WEIGHT * severity
    )
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

    Deviation is ``0.4 * rarity + 0.2 * over-breadth + 0.4 * severity``, all three
    parts in [0, 1], so the score is bounded in [0, 1]. Over-breadth is ASYMMETRIC
    (only an unusually broad fingerprint raises it) and severity is RARITY-GATED
    (a ubiquitous tag contributes 0), so a rare risk tag dominates and structural
    noise — including trivial ``__init__.py`` modules, which are dropped before
    scoring — cannot outrank it. Modules at or below ``DEVIATION_FLOOR``
    (on-pattern) are dropped. Sorted by deviation desc, then severity desc, then
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
    # Asymmetric: normalize over-breadth by the largest OVER-median gap only.
    max_gap = max(b - norm["median_breadth"] for b in breadths)
    anomalies: list[dict[str, Any]] = []
    for module in sorted(profiles):
        record = _score_module(module, profiles[module], norm, max_gap)
        if record is not None:
            anomalies.append(record)
    anomalies.sort(
        key=lambda a: (-a["deviation"], -a["severity"], -a["rarity"], a["module"])
    )
    return anomalies[:top]
