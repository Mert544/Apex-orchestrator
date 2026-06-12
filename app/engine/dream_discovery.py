"""Dream discovery — open-ended pattern finding the Apex way.

Hand-coded signals answer questions we already thought to ask ("is churn
rising while debt ages?"). Discovery answers the question we DIDN'T think to
ask: *what travels with what on this particular codebase?* It enumerates the
full space of signal combinations and lets the data say which associations
are real here — no combination is named in advance, so adding a new signal
later makes new discoveries possible with zero code change.

This is open-ended over the *combination space of known signals* — a genuine
step past enumerated pattern classes, honestly short of an LLM's concept
invention. Two deterministic moves:

  - **association** — of the modules carrying tag A, what fraction also carry
    tag B? A high, well-supported confidence is a discovered law of THIS
    project ("wherever a module is single-author, it tends to be high-churn");
  - **confluence** — a module whose signal *fingerprint* is unusually broad
    (many distinct signals at once) is a confluence nobody named — surfaced
    by its breadth, not by any one signal.

Deterministic: same profile → same discoveries.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

# A tag pair must co-occur on at least this many modules, and reach this
# directional confidence, to count as a discovered association — below this
# it's a coincidence, not a law.
MIN_SUPPORT = 2
MIN_CONFIDENCE = 0.75
# A module is a "confluence" when it carries at least this many distinct
# signals AND clearly more than the typical flagged module.
CONFLUENCE_FLOOR = 3


# Each entry maps a profile attribute to the tag a flagged module earns and
# how to read the module name out of that attribute's items. Adding a signal
# here (one line) widens the discovery space — no other change needed.
def _module_tags(profile: Any) -> dict[str, set[str]]:
    """module path → the set of signal tags it carries in this profile."""
    tags: dict[str, set[str]] = {}

    def add(module: str, tag: str) -> None:
        if module:
            tags.setdefault(module, set()).add(tag)

    str_fields = {
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
    for field, tag in str_fields.items():
        for module in (getattr(profile, field, []) or []):
            add(str(module), tag)
    for spot in (getattr(profile, "churn_hotspots", []) or []):
        add(spot.get("module", ""), "high-churn")
    for kr in (getattr(profile, "knowledge_risks", []) or []):
        add(kr.get("module", ""), "single-author")
    for fn in (getattr(profile, "hotspot_functions", []) or []):
        add(str(fn.get("module", "")), "complex-function")
    for cc in (getattr(profile, "change_coupling", []) or []):
        add(cc.get("a", ""), "co-change")
        add(cc.get("b", ""), "co-change")
    return tags


def discover(profile: Any) -> list[str]:
    """Open-ended associations + confluences discovered in the profile."""
    tags = _module_tags(profile)
    if len(tags) < 2:
        return []

    out: list[str] = []

    # --- associations: which tags travel together on THIS codebase ----------
    counts: dict[str, int] = {}
    for tagset in tags.values():
        for t in tagset:
            counts[t] = counts.get(t, 0) + 1
    co: dict[tuple[str, str], int] = {}
    for tagset in tags.values():
        for a, b in combinations(sorted(tagset), 2):
            co[(a, b)] = co.get((a, b), 0) + 1

    assoc: list[tuple[float, int, str, str]] = []
    for (a, b), n in co.items():
        if n < MIN_SUPPORT:
            continue
        # Direction of the stronger implication: P(B|A) vs P(A|B).
        conf_ab = n / counts[a]
        conf_ba = n / counts[b]
        if conf_ab >= conf_ba:
            best, src, dst = conf_ab, a, b
        else:
            best, src, dst = conf_ba, b, a
        if best >= MIN_CONFIDENCE:
            assoc.append((best, n, src, dst))
    # Strongest, best-supported first; deterministic tie-break on the names.
    assoc.sort(key=lambda t: (-t[0], -t[1], t[2], t[3]))
    for conf, n, src, dst in assoc[:4]:
        out.append(
            f"on this codebase, {int(conf * 100)}% of `{src}` modules are also "
            f"`{dst}` ({n} module(s)) — a discovered association, not a coded rule.")

    # --- confluence: a module whose fingerprint is unusually broad ----------
    breadth = {m: len(ts) for m, ts in tags.items()}
    typical = sorted(breadth.values())[len(breadth) // 2]  # median
    confluences = sorted(
        ((m, n) for m, n in breadth.items()
         if n >= CONFLUENCE_FLOOR and n > typical),
        key=lambda kv: (-kv[1], kv[0]))
    for module, n in confluences[:2]:
        signals = ", ".join(sorted(tags[module]))
        out.append(
            f"`{module}` is a confluence — {n} distinct signals at once "
            f"({signals}); no single lens names it.")
    return out
