"""Deep-mutation characterization for ``dream_discovery`` (incl. the clique dimension).

These tests pin the exact threshold edges, sort/cap behaviour, and seed-grounding
of ``app/engine/dream_discovery.py`` that survive the mutation tester's first 30
seeded faults. Each test targets a *specific* surviving mutant: a confidence /
support boundary, the confluence breadth gate, the clique confidence formula and
cap, the seed dedup/cap, or the carrier-selection ``and`` that grounds a discovery
in a real module. Where a survivor is a genuinely EQUIVALENT mutant (a ``min``
cap that the formula can never reach, a ``split(":", 1)`` maxsplit on a key with a
single colon, a defensive guard that real inputs never trip) it is documented in a
comment rather than pinned, because no behaviour distinguishes it.

Built on synthetic ``ProjectProfile`` inputs; deterministic (same profile -> same
discoveries); stdlib + pytest only. Disjoint from
``test_dream_discovery_deepened_eyml.py`` (the feature test) — this file only
hardens against deep mutants.
"""

from __future__ import annotations

from app.engine.dream_discovery import (
    CLIQUE_MIN_SIZE,
    CLIQUE_MIN_SUPPORT,
    CONFLUENCE_FLOOR,
    MIN_CONFIDENCE,
    SEED_CAP,
    TRIPLE_MIN_CONFIDENCE,
    TRIPLE_MIN_SUPPORT,
    discover_cliques,
    discover_structured,
    discovered_idea_seeds,
)
from app.tools.project_profile import ProjectProfile


# --------------------------------------------------------------------------- #
# Association confidence floor (L126: best >= MIN_CONFIDENCE).
# --------------------------------------------------------------------------- #
def test_association_exactly_at_confidence_floor_is_kept():
    # untested on a,b,c,d (4); debt on a,b,c,e (4); they co-occur on a,b,c (3).
    # Both directional confidences are 3/4 == 0.75 == MIN_CONFIDENCE exactly, so
    # `best >= MIN_CONFIDENCE` keeps it; the `>=`->`>` mutant would drop it.
    profile = ProjectProfile(
        root=".",
        untested_modules=["a", "b", "c", "d"],
        debt_marker_modules=["a", "b", "c", "e"],
    )
    assocs = [d for d in discover_structured(profile) if d.kind == "association"]
    assert MIN_CONFIDENCE == 0.75
    assert assocs, "an association exactly at the confidence floor must survive"
    top = assocs[0]
    assert top.confidence == 0.75
    assert top.support == 3
    assert top.key == "assoc:debt>untested"


# --------------------------------------------------------------------------- #
# Triple support floor (L42 TRIPLE_MIN_SUPPORT, L161 len(mods) < floor).
# --------------------------------------------------------------------------- #
def test_triple_at_exactly_minimum_support_is_kept():
    # Pair (security, untested) carried by exactly 2 modules; both also fragile.
    # support == TRIPLE_MIN_SUPPORT == 2 sits right on the floor: `len(mods) < 2`
    # is False (kept), but `< 2`->`<= 2` or raising the floor 2->3 drops it.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b"],
        untested_modules=["a", "b"],
        fragile_modules=["a", "b"],
    )
    triples = [d for d in discover_structured(profile) if d.kind == "triple"]
    assert TRIPLE_MIN_SUPPORT == 2
    assert triples, "a triple at exactly the minimum support must survive"
    assert min(d.support for d in triples) == 2


# --------------------------------------------------------------------------- #
# Triple confidence floor (L165: conf >= TRIPLE_MIN_CONFIDENCE).
# --------------------------------------------------------------------------- #
def test_triple_exactly_at_confidence_floor_is_top_and_kept():
    # Pair (security, untested) on a,b,c,d,e (5); fragile on a,b,c,d (4 of them)
    # -> the triple security&untested>fragile is 4/5 == 0.80 == the floor exactly.
    # The g/h and p/q modules carry security+fragile (no untested) and
    # untested+fragile (no security) so the REVERSE triples fall below 0.80 and
    # never out-rank the 0.80 one — exposing the `>= TRIPLE_MIN_CONFIDENCE` edge.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d", "e", "g", "h"],
        untested_modules=["a", "b", "c", "d", "e", "p", "q"],
        fragile_modules=["a", "b", "c", "d", "g", "h", "p", "q"],
    )
    triples = [d for d in discover_structured(profile) if d.kind == "triple"]
    assert TRIPLE_MIN_CONFIDENCE == 0.80
    assert len(triples) == 1, "only the 0.80 triple should clear the floor"
    top = triples[0]
    assert top.key == "triple:security&untested>fragile"
    assert top.confidence == 0.8
    assert top.support == 4


# --------------------------------------------------------------------------- #
# Confluence breadth gate (L44 CONFLUENCE_FLOOR, L181 n >= floor and n > typical).
# --------------------------------------------------------------------------- #
def test_confluence_at_exactly_floor_breadth_and_no_spurious_mid():
    # `hot` carries exactly CONFLUENCE_FLOOR == 3 signals; `mid` carries 2 (above
    # the typical breadth of 1 but below the floor); the rest carry 1.
    #   - `n >= CONFLUENCE_FLOOR` at exactly 3 keeps `hot`; `>=`->`>` drops it.
    #   - `n >= floor AND n > typical`: only `hot` qualifies. The `and`->`or`
    #     mutant would admit `mid` (2 > typical) as a spurious confluence.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["hot", "mid", "x"],
        untested_modules=["hot", "mid", "y"],
        fragile_modules=["hot", "z"],
    )
    confs = [d for d in discover_structured(profile) if d.kind == "confluence"]
    assert CONFLUENCE_FLOOR == 3
    assert [d.key for d in confs] == ["confluence:hot"]
    assert confs[0].support == 3


def test_confluence_confidence_formula_is_pinned():
    # `hot` has breadth 3, the typical breadth is 1: conf = min(1.0, 3/(1+3)) ==
    # 0.75. Pins the `n / (typical + n)` shape — `/`->`*` gives 1.0 and `+`->`-`
    # gives a negative ratio. (The `min(1.0, ...)` cap's `1.0`->`2.0` mutant is
    # EQUIVALENT: the ratio is strictly < 1 for any positive typical, so the cap
    # is never reached and 2.0 reads identically.)
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["hot", "x"],
        untested_modules=["hot", "y"],
        fragile_modules=["hot", "z"],
    )
    confs = [d for d in discover_structured(profile) if d.kind == "confluence"]
    assert confs and confs[0].key == "confluence:hot"
    assert confs[0].confidence == 0.75


# --------------------------------------------------------------------------- #
# Clique discovery guard + confidence formula (L245 len(tags) < 2, L225 formula).
# --------------------------------------------------------------------------- #
def test_clique_surfaces_with_exactly_two_tagged_modules():
    # Exactly TWO tagged modules, both carrying the identical 3-signal bundle.
    # `len(tags) < 2` is False at len 2 so the clique surfaces; `< 2`->`<= 2`
    # (or the floor 2->3) would short-circuit to [] and hide it.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/c1.py", "app/c2.py"],
        untested_modules=["app/c1.py", "app/c2.py"],
        fragile_modules=["app/c1.py", "app/c2.py"],
    )
    cliques = discover_cliques(profile)
    assert cliques, "two modules sharing a 3-signal bundle is a clique"
    assert cliques[0].key == "clique:fragile&security&untested"


def test_clique_confidence_formula_is_pinned():
    # bundle size 4, support 2: conf = min(1.0, (4+2)/(4+2+2)) == 6/8 == 0.75.
    # Pins every term of `(size + support) / (size + support + 2)`:
    #   first `+`->`-` -> (4-2)/8 == 0.25; `/`->`*` -> caps at 1.0;
    #   denom `+`->`-` mutants -> 6/4 caps at 1.0; the `2`->`3` -> 6/9 == 0.667.
    # (The `min(1.0, ...)` cap `1.0`->`2.0` is EQUIVALENT — the ratio is < 1.)
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/core.py", "app/io.py"],
        untested_modules=["app/core.py", "app/io.py"],
        fragile_modules=["app/core.py", "app/io.py"],
        debt_marker_modules=["app/core.py", "app/io.py"],
    )
    cliques = discover_cliques(profile)
    assert cliques and cliques[0].key == "clique:debt&fragile&security&untested"
    assert cliques[0].support == 2
    assert cliques[0].confidence == 0.75


# --------------------------------------------------------------------------- #
# Clique sort + cap (L233 out[:2], 2->3).
# --------------------------------------------------------------------------- #
def test_cliques_are_capped_at_two_in_stable_key_order():
    # THREE distinct recurring 3-signal bundles exist, each on 2 modules. They
    # tie on (support, confidence), so the tie-break is the stable key, ascending.
    # `out[:2]` keeps the first two keys; `2`->`3` would leak the third.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a1", "a2"],
        untested_modules=["a1", "a2", "b1", "b2"],
        fragile_modules=["a1", "a2"],
        debt_marker_modules=["b1", "b2", "c1", "c2"],
        modernizable_modules=["b1", "b2"],
        hotspot_modules=["c1", "c2"],
        correctness_bug_modules=["c1", "c2"],
    )
    cliques = discover_cliques(profile)
    assert [d.key for d in cliques] == [
        "clique:complexity&correctness-bug&debt",
        "clique:debt&modernizable&untested",
    ]
    # The third bundle (clique:fragile&security&untested) is truncated away.
    assert all("fragile" not in d.key for d in cliques)


# --------------------------------------------------------------------------- #
# Seed carrier selection (L294: src in ts AND dst in ts).
# --------------------------------------------------------------------------- #
def test_assoc_seed_grounds_in_first_module_carrying_BOTH_tags():
    # debt+untested co-occur on m_y and m_z; m_a/m_b carry untested ONLY. The
    # carrier set uses `src in ts AND dst in ts`, so the sorted-first carrier of
    # BOTH is m_y. The `and`->`or` mutant would admit untested-only modules and
    # pick m_a (which sorts before m_y) — a different, wrong grounding.
    profile = ProjectProfile(
        root=".",
        debt_marker_modules=["m_z", "m_y"],
        untested_modules=["m_z", "m_y", "m_a", "m_b"],
    )
    seeds = discovered_idea_seeds(profile)
    assoc_seed = next(
        (s for s in seeds if "co-occurs with" in s["fact_value"]), None)
    assert assoc_seed is not None
    assert assoc_seed["module"] == "m_y"
    assert assoc_seed["title"] == (
        "Investigate the recurring debt + untested pattern in m_y")


def test_clique_seed_grounds_in_sorted_first_carrier_of_whole_bundle():
    # z1 and z2 both carry the whole {fragile, security, untested} bundle, while
    # the o/p/q modules dilute each individual tag so neither an association nor a
    # confluence claims z1/z2 first — leaving the CLIQUE as the discovery that
    # grounds them. The seed binds to the sorted-first carrier, app/z1.py; the
    # carriers[0] index `0`->`1` mutant would pick app/z2.py instead.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/z1.py", "app/z2.py", "app/o1.py",
                                  "app/o2.py", "app/o3.py"],
        untested_modules=["app/z1.py", "app/z2.py", "app/o1.py",
                          "app/p1.py", "app/p2.py"],
        fragile_modules=["app/z1.py", "app/z2.py", "app/o2.py",
                         "app/q1.py", "app/q2.py"],
        debt_marker_modules=["app/o1.py", "app/o2.py", "app/o3.py",
                             "app/p1.py", "app/q1.py"],
    )
    seeds = discovered_idea_seeds(profile)
    bundle_seed = next(
        (s for s in seeds if "all travel together" in s["fact_value"]), None)
    assert bundle_seed is not None
    assert bundle_seed["module"] == "app/z1.py"


# --------------------------------------------------------------------------- #
# Seed dedup + cap (L279 SEED_CAP, L387 len(seeds) >= SEED_CAP).
# --------------------------------------------------------------------------- #
def _four_distinct_seed_modules_profile() -> ProjectProfile:
    # Four disjoint module pairs, each pair sharing a distinct 2-tag association,
    # so four associations ground in four DISTINCT sorted-first modules. By the
    # association sort the pre-cap order is d1, c1, b1, a1; SEED_CAP truncates to
    # the first three.
    return ProjectProfile(
        root=".",
        security_finding_modules=["app/a1.py", "app/a2.py"],
        untested_modules=["app/a1.py", "app/a2.py"],
        debt_marker_modules=["app/b1.py", "app/b2.py"],
        modernizable_modules=["app/b1.py", "app/b2.py"],
        fragile_modules=["app/c1.py", "app/c2.py"],
        correctness_bug_modules=["app/c1.py", "app/c2.py"],
        hotspot_modules=["app/d1.py", "app/d2.py"],
        sensitive_paths=["app/d1.py", "app/d2.py"],
    )


def test_seeds_truncate_at_exactly_seed_cap():
    # Four distinct seedable modules are available but SEED_CAP == 3 keeps three.
    # `SEED_CAP` 3->4, or `len(seeds) >= SEED_CAP`->`>`, would admit the 4th
    # (app/a1.py); pinning the exact three-module list kills both.
    profile = _four_distinct_seed_modules_profile()
    seeds = discovered_idea_seeds(profile)
    assert SEED_CAP == 3
    assert [s["module"] for s in seeds] == [
        "app/d1.py", "app/c1.py", "app/b1.py"]
    assert "app/a1.py" not in {s["module"] for s in seeds}


# --------------------------------------------------------------------------- #
# Constants pinned (L40-L46): the named thresholds are the values the rules above
# depend on, so a constant drift can't pass silently.
# --------------------------------------------------------------------------- #
def test_clique_thresholds_are_pinned():
    assert CLIQUE_MIN_SIZE == 3
    assert CLIQUE_MIN_SUPPORT == 2


def test_determinism_same_profile_same_discoveries():
    profile = _four_distinct_seed_modules_profile()
    assert (
        [d.to_dict() for d in discover_structured(profile)]
        == [d.to_dict() for d in discover_structured(profile)]
    )
    assert discovered_idea_seeds(profile) == discovered_idea_seeds(profile)
