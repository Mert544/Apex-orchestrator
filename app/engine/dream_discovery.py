"""Dream discovery — open-ended pattern finding the Apex way.

Hand-coded signals answer questions we already thought to ask ("is churn
rising while debt ages?"). Discovery answers the question we DIDN'T think to
ask: *what travels with what on this particular codebase?* It enumerates the
combination space of every signal a module carries and lets the data say which
associations are real here — no combination is named in advance, so adding a
new signal later makes new discoveries possible with zero code change.

Open-ended over the *combination space of known signals* — a genuine step past
enumerated pattern classes, honestly short of an LLM's concept invention.
Three deterministic moves, each scored so the dream can rank and (across
nights) promote them:

  - **association** — of the modules carrying tag A, what fraction also carry
    tag B? A high, well-supported confidence is a discovered law of THIS
    project ("wherever single-author, also high-churn");
  - **triple** — A and B together almost always bring C: a higher-order rule
    the pairwise view can't see;
  - **confluence** — a module whose signal *fingerprint* is unusually broad is
    a confluence nobody named, surfaced by breadth not by any one signal.

Each discovery carries a **stable key** (independent of the magnitudes that
drift run to run) so the dream journal can track its persistence, and a
**confidence** in [0,1] so only strong, repeatedly-confirmed laws graduate
into waking ideas. Deterministic: same profile → same discoveries.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

MIN_SUPPORT = 2          # a rule must hold on at least this many modules
MIN_CONFIDENCE = 0.75    # …at this directional confidence
TRIPLE_MIN_SUPPORT = 2
TRIPLE_MIN_CONFIDENCE = 0.80
CONFLUENCE_FLOOR = 3     # a confluence carries at least this many distinct signals


@dataclass
class Discovery:
    key: str            # stable identity across runs (magnitude-free)
    text: str           # human display
    kind: str           # association | triple | confluence
    confidence: float   # 0..1
    support: int        # modules backing it

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "text": self.text, "kind": self.kind,
                "confidence": round(self.confidence, 3), "support": self.support}


def _module_tags(profile: Any) -> dict[str, set[str]]:
    """module path → the set of signal tags it carries in this profile.

    One line per signal — adding a row here widens the whole discovery space.
    """
    tags: dict[str, set[str]] = {}

    def add(module: str, tag: str) -> None:
        if not (module):
            return
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


def discover_structured(profile: Any) -> list[Discovery]:
    """Scored, stably-keyed discoveries — the form the dream ranks and promotes."""
    tags = _module_tags(profile)
    if len(tags) < 2:
        return []
    out: list[Discovery] = []

    counts: dict[str, int] = {}
    for tagset in tags.values():
        for t in tagset:
            counts[t] = counts.get(t, 0) + 1

    # --- pairwise associations ---------------------------------------------
    pair_co: dict[tuple[str, str], int] = {}
    for tagset in tags.values():
        for a, b in combinations(sorted(tagset), 2):
            pair_co[(a, b)] = pair_co.get((a, b), 0) + 1

    assoc: list[Discovery] = []
    for (a, b), n in pair_co.items():
        if n < MIN_SUPPORT:
            continue
        conf_ab, conf_ba = n / counts[a], n / counts[b]
        best, src, dst = (conf_ab, a, b) if conf_ab >= conf_ba else (conf_ba, b, a)
        if best >= MIN_CONFIDENCE:
            assoc.append(Discovery(
                key=f"assoc:{src}>{dst}", kind="association",
                confidence=best, support=n,
                text=(f"on this codebase, {int(best * 100)}% of `{src}` modules are "
                      f"also `{dst}` ({n} module(s)) — a discovered association, "
                      "not a coded rule.")))
    assoc.sort(key=lambda d: (-d.confidence, -d.support, d.key))
    out += assoc[:4]

    # --- triple rules: A ∧ B ⇒ C -------------------------------------------
    triples: list[Discovery] = []
    pair_modules: dict[tuple[str, str], set[str]] = {}
    for module, tagset in tags.items():
        for a, b in combinations(sorted(tagset), 2):
            pair_modules.setdefault((a, b), set()).add(module)
    for (a, b), mods in pair_modules.items():
        if len(mods) < TRIPLE_MIN_SUPPORT:
            continue
        # candidate C: a tag on all/most of these modules, distinct from a,b.
        third_counts: dict[str, int] = {}
        for m in mods:
            for t in tags[m]:
                if t not in (a, b):
                    third_counts[t] = third_counts.get(t, 0) + 1
        for c, n in third_counts.items():
            conf = n / len(mods)
            if n >= TRIPLE_MIN_SUPPORT and conf >= TRIPLE_MIN_CONFIDENCE:
                key = f"triple:{'&'.join(sorted((a, b)))}>{c}"
                triples.append(Discovery(
                    key=key, kind="triple", confidence=conf, support=n,
                    text=(f"higher-order rule: modules that are both `{a}` and "
                          f"`{b}` are {int(conf * 100)}% also `{c}` "
                          f"({n} module(s)).")))
    triples.sort(key=lambda d: (-d.confidence, -d.support, d.key))
    out += triples[:2]

    # --- confluence: unusually broad fingerprint ----------------------------
    breadth = {m: len(ts) for m, ts in tags.items()}
    typical = sorted(breadth.values())[len(breadth) // 2]
    confluences = sorted(
        ((m, n) for m, n in breadth.items() if n >= CONFLUENCE_FLOOR and n > typical),
        key=lambda kv: (-kv[1], kv[0]))
    for module, n in confluences[:2]:
        signals = ", ".join(sorted(tags[module]))
        # Confidence scales with how far above the typical breadth it sits.
        conf = min(1.0, n / (typical + n))
        out.append(Discovery(
            key=f"confluence:{module}", kind="confluence", confidence=conf, support=n,
            text=(f"`{module}` is a confluence — {n} distinct signals at once "
                  f"({signals}); no single lens names it.")))
    return out


def discover(profile: Any) -> list[str]:
    """The display strings, for the dream digest."""
    return [d.text for d in discover_structured(profile)]
