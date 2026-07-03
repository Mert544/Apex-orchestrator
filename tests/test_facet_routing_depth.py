"""Tests for the DEEPENED facet -> develop routing.

This wave does two complementary things and these tests pin both:

1. **Routing**: every safe registered develop objective is now reachable from at
   least one facet phrase. The key regression guard is
   ``test_every_map_value_is_a_real_objective`` — no entry in
   ``FACET_OBJECTIVE_MAP`` may name an objective the compiler does not actually
   register. ``test_no_safe_objective_is_unreachable`` is the complementary
   completeness claim.

2. **Vocabulary**: the engine genuinely EMITS each new phrase, so the new map
   entries connect end-to-end (a phrase the engine never produces is a dead map
   key). Emission is asserted deterministic.

Pattern-matched on ``tests/test_facet_develop.py`` and ``tests/test_idea_facets.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
from app.engine.idea_facets import _FACETS, _FACET_SUBASPECTS
from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaPermutationEngine
from app.engine.objective_compiler import available_objectives

# (emitted facet phrase, objective it must route to). Every phrase here is added
# by this wave to the facet vocabulary AND to FACET_OBJECTIVE_MAP, so each row is
# a single end-to-end claim: the engine can descend to the phrase, and the phrase
# names a real develop campaign.
_NEW_ROUTES: list[tuple[str, str]] = [
    # deep nesting / duplicated logic groundings for newly-routed objectives.
    ("a trailing guard after setup", "guard-clause"),
    ("a fully-returning duplicate block", "dedup-total-return"),
    ("a guard-returning duplicate block", "dedup-guarded-return"),
    # legacy idioms (simplify lens).
    ("percent-style string format", "percent-to-fstring"),
    ("explicit format-spec call", "format-to-fstring"),
    ("str.format placeholder call", "fstring-convert"),
    ("set from a list literal", "set-literal"),
    ("dict built by a loop", "dict-comprehension"),
    ("implicitly concatenated literals", "fold-literal-string-concat"),
    # redundant expressions (simplify lens).
    ("a double negation", "remove-double-negation"),
    ("length compared to zero", "simplify-len-comparison"),
    ("a negated equality comparison", "simplify-negated-comparison"),
    ("an isinstance or-chain", "merge-isinstance"),
    ("a startswith or endswith or-chain", "collapse-startswith"),
    ("an unchained comparison range", "chain-comparison"),
    ("a magic literal worth naming", "extract-constant"),
    ("a self-referential augmented assignment", "combine-augmented-assign"),
    ("nested with statements", "combine-nested-with"),
    ("a comprehension wrapped in another call", "simplify-comprehension"),
    # import hygiene (decouple lens).
    ("an unused import", "remove-unused-imports"),
    ("an unsorted import block", "sort-imports"),
]

# This wave hangs its new simplify-lens phrases off the EXISTING redundant-control-
# flow L2 groups (no new L1/L2 node) so the per-level beam stays undisturbed and the
# original control-flow ladder still reaches L3. Each phrase below must therefore
# live under one of these three L2 groups.
_RCF_L2_GROUPS = ["redundant conditionals", "collapsible structure",
                  "unreachable or no-op statements"]


# ---------------------------------------------------------------------------
# 1. Routing integrity — the key regression guard.
# ---------------------------------------------------------------------------

def test_every_map_value_is_a_real_objective() -> None:
    """KEY GUARD: every value in FACET_OBJECTIVE_MAP names an objective the
    compiler actually registers — no dangling map entries. This also guards the
    pre-existing entries, so the map can never drift out of sync."""
    known = set(available_objectives())
    for phrase, objective in FACET_OBJECTIVE_MAP.items():
        assert objective in known, (
            f"facet {phrase!r} maps to unknown objective {objective!r}; "
            f"known: {sorted(known)}"
        )


def test_no_safe_objective_is_unreachable() -> None:
    """Completeness: every registered objective is reachable from at least one
    facet phrase. (The three objectives being built in parallel —
    remove-unreachable, combine-with, remove-redundant-else — are wired by their
    owner once they land; whatever is registered on THIS head must be reachable.)"""
    reachable = set(FACET_OBJECTIVE_MAP.values())
    unreachable = set(available_objectives()) - reachable
    assert unreachable == set(), f"objectives with no facet route: {sorted(unreachable)}"


def test_routing_reaches_every_registered_objective_count() -> None:
    """The reachable set is exactly the full registered objective set (1:1)."""
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


@pytest.mark.parametrize("phrase, objective", _NEW_ROUTES)
def test_each_new_route(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


def test_guard_clause_route_is_distinct_from_extract_guard_clause() -> None:
    """The standalone guard-clause objective (trailing guard after setup) and
    extract-guard-clause (leading precondition) are sibling shapes — the routing
    must keep them apart, not collapse both to one objective."""
    assert facet_to_objective("a trailing guard after setup") == "guard-clause"
    assert facet_to_objective("guard clause") == "extract-guard-clause"
    assert facet_to_objective("early return") == "extract-guard-clause"


def test_dedup_total_return_distinct_from_plain_dedup() -> None:
    assert facet_to_objective("a fully-returning duplicate block") == "dedup-total-return"
    assert facet_to_objective("extract a shared helper") == "dedup"
    assert facet_to_objective("duplicated logic") == "dedup"


def test_new_routes_did_not_break_existing_ones() -> None:
    """Spot-check that the pre-existing entries still resolve as before — the new
    keys are not substrings that hijack older phrasings."""
    assert facet_to_objective("modernize") == "modernize"
    assert facet_to_objective("parameterize") == "dead-params"
    assert facet_to_objective("dead code") == "remove-dead-code"
    assert facet_to_objective("edge cases") == "cover-gaps"
    assert facet_to_objective("negating the comparison") == "fix-not-in-is"


def test_substring_ordering_invariant_holds_across_whole_map() -> None:
    """For any two keys where one is a substring of the other AND they map to
    different objectives, the broader (substring) key must be inserted LATER so
    the more-specific phrasing wins the first-match scan. Guards the new entries
    against silently shadowing — or being shadowed by — existing ones."""
    keys = list(FACET_OBJECTIVE_MAP)
    pos = {k: i for i, k in enumerate(keys)}
    for short in keys:
        for long in keys:
            if short is long or short not in long:
                continue
            if FACET_OBJECTIVE_MAP[short] == FACET_OBJECTIVE_MAP[long]:
                continue
            assert pos[long] < pos[short], (
                f"{long!r} (-> {FACET_OBJECTIVE_MAP[long]!r}) must precede its "
                f"substring {short!r} (-> {FACET_OBJECTIVE_MAP[short]!r})"
            )
            assert facet_to_objective(long) == FACET_OBJECTIVE_MAP[long]


# ---------------------------------------------------------------------------
# 2. Vocabulary — the phrases exist in the data and the engine emits them.
# ---------------------------------------------------------------------------

def test_import_direction_hosts_import_hygiene() -> None:
    """The decouple lens's "import direction" aspect carries the import-hygiene
    phrases directly (a flat L1->L2 ladder)."""
    assert "import direction" in _FACETS["decouple"]
    l2 = _FACET_SUBASPECTS.get("import direction")
    assert l2, "import direction has no sub-aspects"
    assert "an unused import" in l2
    assert "an unsorted import block" in l2


def test_simplify_phrases_live_under_existing_rcf_groups() -> None:
    """Each new simplify-lens routing phrase hangs off one of the three EXISTING
    redundant-control-flow L2 groups — never a new L1/L2 node — and routes to a
    real objective. Hosting under existing groups is what keeps the per-level beam
    undisturbed so the original control-flow ladder still reaches L3."""
    for phrase, _ in _NEW_ROUTES:
        objective = facet_to_objective(phrase)
        if objective in {"remove-unused-imports", "sort-imports", "guard-clause",
                         "dedup-total-return", "dedup-guarded-return"}:
            continue  # import-hygiene / deep-nesting / dedup live elsewhere
        homes = [g for g in _RCF_L2_GROUPS if phrase in _FACET_SUBASPECTS[g]]
        assert homes, f"{phrase!r} is under no redundant-control-flow L2 group"


def test_redundant_control_flow_l2_ladder_is_unchanged() -> None:
    """The pre-existing redundant-control-flow L2 list (the three group names) MUST
    stay byte-identical — this wave extends each group's L3 list, never the L2 list
    itself (a sibling test in test_idea_facets pins the same L2 list)."""
    assert _FACET_SUBASPECTS["redundant control flow"] == _RCF_L2_GROUPS


def test_original_rcf_l3_phrases_are_preserved_and_first() -> None:
    """Extending each L2 group must keep the original control-flow phrases, and keep
    them FIRST, so their emission order/precedence is unchanged."""
    assert _FACET_SUBASPECTS["redundant conditionals"][:3] == [
        "boolean return simplification", "ternary that returns a boolean",
        "redundant else after return",
    ]
    assert _FACET_SUBASPECTS["collapsible structure"][:3] == [
        "collapsible nested conditionals", "get-with-default lookup",
        "manual index loop",
    ]
    assert _FACET_SUBASPECTS["unreachable or no-op statements"][:2] == [
        "redundant pass statement", "statements after an unconditional return",
    ]


def test_every_new_phrase_appears_in_the_vocabulary() -> None:
    """Each routing phrase is genuinely present in _FACETS/_FACET_SUBASPECTS so the
    zoom can reach it — not just in the objective map."""
    in_data = set(_FACETS["simplify"]) | {
        p for subs in _FACET_SUBASPECTS.values() for p in subs
    }
    for phrase, _ in _NEW_ROUTES:
        assert phrase in in_data, f"{phrase!r} is in no facet ladder"


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "def check(flag):\n"
        "    if flag:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
        "\n\n"
        "def tally(a, b, c, d, e, f, g):\n"
        "    total = 0\n"
        "    if a > 0:\n"
        "        if b > 0:\n"
        "            if c > 0:\n"
        "                total += 1\n"
        "            else:\n"
        "                total -= 1\n"
        "        elif d > 0:\n"
        "            total += 2\n"
        "    if e > 0:\n"
        "        for x in range(e):\n"
        "            total += x\n"
        "    if g > 0:\n"
        "        total *= g\n"
        "    else:\n"
        "        total = 0\n"
        "    return total\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


_CFG = {
    "max_total_ideas": 50000, "max_idea_depth": 1, "breadth": 8,
    "fractal_facets": True, "facet_depth": 3, "facets_per_idea": 12,
    "security_aware": False,
}


def _emitted(tmp: Path, lens: str) -> set[str]:
    engine = IdeaPermutationEngine(_CFG, tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == lens]
    rep = engine.run()
    return {
        fact.split("facet:", 1)[1].strip()
        for idea in rep.ideas if idea.kind == "facet"
        for fact in idea.source_facts if fact.startswith("facet:")
    }


def test_engine_emits_every_new_simplify_phrase_end_to_end(tmp_path) -> None:
    """The headline claim for the simplify-lens additions: the zoom EMITS each new
    phrase, and the emitted phrase routes to its objective."""
    labels = _emitted(_project(tmp_path), "simplify")
    for phrase, objective in _NEW_ROUTES:
        if objective in {"remove-unused-imports", "sort-imports"}:
            continue  # decouple-lens phrases, checked separately
        assert phrase in labels, f"engine never emitted {phrase!r}"
        assert facet_to_objective(phrase) == objective


def test_engine_emits_import_hygiene_phrases_from_decouple_lens(tmp_path) -> None:
    labels = _emitted(_project(tmp_path), "decouple")
    assert "import direction" in labels
    assert "an unused import" in labels
    assert "an unsorted import block" in labels
    assert facet_to_objective("an unused import") == "remove-unused-imports"
    assert facet_to_objective("an unsorted import block") == "sort-imports"


def test_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    project = _project(tmp_path)

    def run_once(lens: str) -> set[str]:
        return _emitted(project, lens)

    assert run_once("simplify") == run_once("simplify")
    assert run_once("decouple") == run_once("decouple")


def test_full_report_is_deterministic_across_all_lenses(tmp_path) -> None:
    """Two full runs (all lenses) emit an identical facet-label set — the engine's
    output is reproducible, not just the single-lens slice."""
    project = _project(tmp_path)

    def all_labels() -> set[str]:
        engine = IdeaPermutationEngine(_CFG, project)
        rep = engine.run()
        return {
            fact.split("facet:", 1)[1].strip()
            for idea in rep.ideas if idea.kind == "facet"
            for fact in idea.source_facts if fact.startswith("facet:")
        }

    assert all_labels() == all_labels()


# ---------------------------------------------------------------------------
# 3. Edge / empty paths.
# ---------------------------------------------------------------------------

def test_unmapped_phrase_still_returns_none() -> None:
    assert facet_to_objective("write more documentation") is None
    assert facet_to_objective("") is None


def test_new_phrases_each_map_to_a_registered_objective() -> None:
    """Belt-and-braces: every phrase in _NEW_ROUTES resolves to a registered
    objective (so none of the wave's additions is a dead end)."""
    known = set(available_objectives())
    for phrase, objective in _NEW_ROUTES:
        resolved = facet_to_objective(phrase)
        assert resolved == objective
        assert resolved in known
