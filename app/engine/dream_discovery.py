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


def _tag_counts(tags: dict[str, set[str]]) -> dict[str, int]:
    """How many modules carry each tag — the base rate every confidence divides by."""
    counts: dict[str, int] = {}
    for tagset in tags.values():
        for t in tagset:
            counts[t] = counts.get(t, 0) + 1
    return counts


def _associations(tags: dict[str, set[str]], counts: dict[str, int]) -> list[Discovery]:
    """Pairwise rules: of modules carrying A, what fraction also carry B?"""
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
    return assoc[:4]


def _pair_modules(tags: dict[str, set[str]]) -> dict[tuple[str, str], set[str]]:
    """Which modules carry each ordered tag-pair — the support set for triples."""
    pair_modules: dict[tuple[str, str], set[str]] = {}
    for module, tagset in tags.items():
        for a, b in combinations(sorted(tagset), 2):
            pair_modules.setdefault((a, b), set()).add(module)
    return pair_modules


def _third_counts(tags: dict[str, set[str]], mods: set[str],
                  a: str, b: str) -> dict[str, int]:
    """Candidate C tags on the A∧B modules, excluding A and B themselves."""
    third_counts: dict[str, int] = {}
    for m in mods:
        for t in tags[m]:
            if t not in (a, b):
                third_counts[t] = third_counts.get(t, 0) + 1
    return third_counts


def _triples(tags: dict[str, set[str]]) -> list[Discovery]:
    """Higher-order rules: A ∧ B ⇒ C the pairwise view can't see."""
    triples: list[Discovery] = []
    for (a, b), mods in _pair_modules(tags).items():
        if len(mods) < TRIPLE_MIN_SUPPORT:
            continue
        for c, n in _third_counts(tags, mods, a, b).items():
            conf = n / len(mods)
            if n >= TRIPLE_MIN_SUPPORT and conf >= TRIPLE_MIN_CONFIDENCE:
                key = f"triple:{'&'.join(sorted((a, b)))}>{c}"
                triples.append(Discovery(
                    key=key, kind="triple", confidence=conf, support=n,
                    text=(f"higher-order rule: modules that are both `{a}` and "
                          f"`{b}` are {int(conf * 100)}% also `{c}` "
                          f"({n} module(s)).")))
    triples.sort(key=lambda d: (-d.confidence, -d.support, d.key))
    return triples[:2]


def _confluences(tags: dict[str, set[str]]) -> list[Discovery]:
    """Modules whose signal fingerprint is unusually broad — named by breadth."""
    breadth = {m: len(ts) for m, ts in tags.items()}
    typical = sorted(breadth.values())[len(breadth) // 2]
    ranked = sorted(
        ((m, n) for m, n in breadth.items() if n >= CONFLUENCE_FLOOR and n > typical),
        key=lambda kv: (-kv[1], kv[0]))
    out: list[Discovery] = []
    for module, n in ranked[:2]:
        signals = ", ".join(sorted(tags[module]))
        # Confidence scales with how far above the typical breadth it sits.
        conf = min(1.0, n / (typical + n))
        out.append(Discovery(
            key=f"confluence:{module}", kind="confluence", confidence=conf, support=n,
            text=(f"`{module}` is a confluence — {n} distinct signals at once "
                  f"({signals}); no single lens names it.")))
    return out


def discover_structured(profile: Any) -> list[Discovery]:
    """Scored, stably-keyed discoveries — the form the dream ranks and promotes."""
    tags = _module_tags(profile)
    if len(tags) < 2:
        return []
    counts = _tag_counts(tags)
    return _associations(tags, counts) + _triples(tags) + _confluences(tags)


def discover(profile: Any) -> list[str]:
    """The display strings, for the dream digest."""
    return [d.text for d in discover_structured(profile)]


SEED_CAP = 3  # at most this many discoveries graduate into seedable directions


def _assoc_seed(disc: Discovery, tags: dict[str, set[str]]) -> dict[str, str] | None:
    """Ground a pairwise association in the concrete module(s) that carry both tags.

    The association key is ``assoc:src>dst``; the descriptor binds it to the
    lexicographically-first module carrying BOTH tags, so a project-wide law
    becomes a pointable seed (``app/x.py`` where ``A`` co-occurs with ``B``).
    Returns ``None`` when the key is malformed or no module carries both.
    """
    body = disc.key.split(":", 1)[1]
    if ">" not in body:
        return None
    src, dst = body.split(">", 1)
    carriers = sorted(m for m, ts in tags.items() if src in ts and dst in ts)
    if not carriers:
        return None
    module = carriers[0]
    return {
        "module": module,
        "title": (f"Investigate the recurring {src} + {dst} pattern in {module}"),
        "fact_label": "discovered-pattern",
        "fact_value": (f"{module} ({src} co-occurs with {dst} here — an emergent "
                       "pattern Apex found, not a pre-named rule)"),
    }


def _confluence_seed(disc: Discovery, tags: dict[str, set[str]]) -> dict[str, str] | None:
    """A breadth-named confluence module becomes a 'untangle the convergence' seed."""
    module = disc.key.split(":", 1)[1]
    signals = ", ".join(sorted(tags.get(module, set())))
    if not module or not signals:
        return None
    return {
        "module": module,
        "title": (f"Investigate the unusually broad signal convergence in {module}"),
        "fact_label": "discovered-pattern",
        "fact_value": (f"{module} ({signals} co-occur here — an emergent confluence "
                       "Apex found by breadth, not a pre-named rule)"),
    }


def discovered_idea_seeds(profile: Any) -> list[dict]:
    """The strongest discoveries, shaped as deterministic, module-bound seed descriptors.

    Each descriptor is a plain dict carrying exactly the keys the seeder needs —
    ``{"module", "title", "fact_label", "fact_value"}`` — so an open-ended
    discovery ("what travels with what on THIS codebase") becomes an actionable
    development direction. Reuses ``discover_structured`` (no new analysis):
    associations are grounded in the concrete module carrying both tags;
    confluences are named by the module their breadth already points at; triples
    are project-wide so they carry no single module and are skipped here.

    Deterministic and purely additive: discoveries arrive pre-sorted by
    (confidence, support, key); descriptors are de-duplicated by module (a module
    surfaced by an association is never re-emitted by a confluence) and capped at
    ``SEED_CAP``. Returns ``[]`` when nothing is discovered, so a seeder that
    consumes it adds nothing → byte-identical.
    """
    tags = _module_tags(profile)
    seeds: list[dict] = []
    seen: set[str] = set()
    for disc in discover_structured(profile):
        if disc.kind == "association":
            descriptor = _assoc_seed(disc, tags)
        elif disc.kind == "confluence":
            descriptor = _confluence_seed(disc, tags)
        else:
            descriptor = None
        if descriptor is None or descriptor["module"] in seen:
            continue
        seen.add(descriptor["module"])
        seeds.append(descriptor)
        if len(seeds) >= SEED_CAP:
            break
    return seeds
