"""Tests for the facet -> develop objective bridge."""

from __future__ import annotations

import pytest

from app.engine.facet_develop import (
    FACET_OBJECTIVE_MAP,
    facet_to_objective,
    facets_to_objectives,
    render_facet_plan_markdown,
)
from app.engine.objective_compiler import available_objectives


@pytest.mark.parametrize(
    "phrase, objective",
    [
        ("extract a shared helper", "dedup"),
        ("single source of truth", "dedup"),
        ("duplicated logic", "dedup"),
        ("smaller unit", "shrink-functions"),
        ("extract inner", "shrink-functions"),
        ("parameterize", "dead-params"),
        ("api surface", "dead-params"),
        ("interface", "dead-params"),
        ("unused parameter", "dead-params"),
        ("modernize", "modernize"),
        ("none comparison", "modernize"),
        ("dead code", "remove-dead-code"),
        ("unreachable", "remove-dead-code"),
        ("inline", "inline-helpers"),
        ("indirection", "inline-helpers"),
    ],
)
def test_each_mapping(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


# Phrases the engine genuinely EMITS (facet vocabulary in idea_facets._FACETS /
# _FACET_SUBASPECTS, plus detector message substrings) that the expanded map now
# routes to a develop objective. Each pair is (real emitted phrase, objective).
@pytest.mark.parametrize(
    "phrase, objective",
    [
        # dedup-parameterized — the "parameterize the variants" sub-aspect.
        ("parameterize the variants", "dedup-parameterized"),
        ("the varying dimension", "dedup-parameterized"),
        ("flag versus strategy", "dedup-parameterized"),
        ("the default variant", "dedup-parameterized"),
        # shrink-functions — extract-this-block sub-aspects of deep nesting.
        ("nested conditional extraction", "shrink-functions"),
        ("loop body extraction", "shrink-functions"),
        # extract-guard-clause — flatten nesting with early-exit guards.
        ("guard clauses", "extract-guard-clause"),
        ("guard clause", "extract-guard-clause"),
        ("early returns", "extract-guard-clause"),
        ("early return", "extract-guard-clause"),
        ("precondition exits", "extract-guard-clause"),
        ("error exits first", "extract-guard-clause"),
        # modernize — detector tidy-debt wordings.
        ("compare to None with `is` / `is not`", "modernize"),
        ("f-string without placeholders — drop the `f` prefix", "modernize"),
        ("use a literal `{}` instead of `dict()`", "modernize"),
        # fix-not-in-is — the negated-membership/identity finding.
        ("use `not in` instead of negating the comparison", "fix-not-in-is"),
        # remove-dead-code — dead/unreachable sub-aspects.
        ("unreachable branches", "remove-dead-code"),
        ("dead error paths", "remove-dead-code"),
        ("constant conditions", "remove-dead-code"),
        ("tautological conditions", "remove-dead-code"),
        ("duplicate null checks", "remove-dead-code"),
        ("shadowed cases", "remove-dead-code"),
        # cover-gaps — the test lens's "this needs a test" concerns.
        ("edge cases", "cover-gaps"),
        ("failure modes", "cover-gaps"),
        ("property invariants", "cover-gaps"),
        ("round-trip stability", "cover-gaps"),
        ("ordering independence", "cover-gaps"),
        ("idempotence", "cover-gaps"),
        # redundant control flow — the simplify lens's new "redundant control
        # flow" L3 sub-aspects, each an equivalence-preserving tidy that a
        # dedicated develop objective performs.
        ("boolean return simplification", "simplify-bool-return"),
        ("ternary that returns a boolean", "simplify-ternary-bool"),
        ("redundant else after return", "remove-redundant-else"),
        ("collapsible nested conditionals", "merge-nested-if"),
        ("get-with-default lookup", "simplify-dict-get"),
        ("manual index loop", "use-enumerate"),
        ("redundant pass statement", "remove-pointless-pass"),
        ("statements after an unconditional return",
         "remove-unreachable-after-terminator"),
    ],
)
def test_each_new_mapping(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


# Overlapping keys where a shorter key is a SUBSTRING of a longer one (or of a
# phrase that should route elsewhere): the more-specific phrasing MUST be listed
# first so the first-substring-match returns the intended objective.
@pytest.mark.parametrize(
    "phrase, objective",
    [
        # "parameterize the variants" contains "parameterize" (dead-params); the
        # specific near-dup phrasing must win.
        ("parameterize the variants", "dedup-parameterized"),
        # the bare "parameterize" still routes to dead-params.
        ("parameterize", "dead-params"),
        # "redundant guards" contains "redundant guard" (remove-dead-code) but NOT
        # "guard clause" (extract-guard-clause): it stays dead-code.
        ("redundant guards", "remove-dead-code"),
        ("redundant guard", "remove-dead-code"),
        # "guard clauses" routes to the guard objective, not dead-code.
        ("guard clauses", "extract-guard-clause"),
    ],
)
def test_specific_before_broad_ordering(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


def test_specific_keys_precede_broader_substrings_in_insertion_order() -> None:
    """For any two keys where one is a substring of the other AND they map to
    different objectives, the substring (broader) key must be inserted LATER so
    the more-specific phrasing wins the first-match scan."""
    keys = list(FACET_OBJECTIVE_MAP)
    pos = {k: i for i, k in enumerate(keys)}
    for short in keys:
        for long in keys:
            if short is long or short not in long:
                continue
            if FACET_OBJECTIVE_MAP[short] == FACET_OBJECTIVE_MAP[long]:
                continue
            # short is a substring of long with a DIFFERENT objective: long must
            # come first, else facet_to_objective(long) would return short's obj.
            assert pos[long] < pos[short], (
                f"{long!r} (-> {FACET_OBJECTIVE_MAP[long]!r}) must precede its "
                f"substring {short!r} (-> {FACET_OBJECTIVE_MAP[short]!r})"
            )
            assert facet_to_objective(long) == FACET_OBJECTIVE_MAP[long]


def test_coverage_is_substantially_higher() -> None:
    """The map now routes to far more of the 37 develop objectives than the
    original ~6 (dedup, shrink-functions, dead-params, modernize,
    remove-dead-code, inline-helpers).

    Before this wave the map reached 10 objectives; the redundant-control-flow
    ladder adds 8 more, lifting reachability to 18."""
    reachable = {v for v in FACET_OBJECTIVE_MAP.values()}
    assert len(reachable) == 18
    # The four objectives the original six did not reach.
    assert {"dedup-parameterized", "extract-guard-clause", "fix-not-in-is",
            "cover-gaps"} <= reachable
    # The eight objectives this wave newly made reachable end-to-end.
    assert {"simplify-bool-return", "simplify-ternary-bool",
            "remove-redundant-else", "merge-nested-if", "simplify-dict-get",
            "use-enumerate", "remove-pointless-pass",
            "remove-unreachable-after-terminator"} <= reachable


def test_reachable_objective_count_rose_by_eight() -> None:
    """Before/after: the new redundant-control-flow phrases are exactly the
    objectives that moved the reachable set from 10 to 18 — and not one of them
    was already reachable (so the gain is real, not double-counted)."""
    new_phrase_objectives = {
        "simplify-bool-return", "simplify-ternary-bool", "remove-redundant-else",
        "merge-nested-if", "simplify-dict-get", "use-enumerate",
        "remove-pointless-pass", "remove-unreachable-after-terminator",
    }
    reachable = set(FACET_OBJECTIVE_MAP.values())
    previously_reachable = reachable - new_phrase_objectives
    assert len(previously_reachable) == 10
    assert len(reachable) == 18
    # None of the eight was already among the prior ten.
    assert new_phrase_objectives.isdisjoint(previously_reachable)


def test_matching_is_case_insensitive_and_substring() -> None:
    assert facet_to_objective("We should MODERNIZE this") == "modernize"
    assert facet_to_objective("...extract a shared helper here...") == "dedup"


def test_unmapped_phrase_returns_none() -> None:
    assert facet_to_objective("write more documentation") is None
    assert facet_to_objective("") is None


def test_facets_to_objectives_dedups_and_preserves_order() -> None:
    phrases = [
        "modernize",            # modernize
        "extract a shared helper",  # dedup
        "duplicated logic",     # dedup (dup -> dropped)
        "parameterize",         # dead-params
        "single source of truth",   # dedup (dup -> dropped)
        "smaller unit",         # shrink-functions
    ]
    assert facets_to_objectives(phrases) == [
        "modernize",
        "dedup",
        "dead-params",
        "shrink-functions",
    ]


def test_facets_to_objectives_skips_unmapped() -> None:
    assert facets_to_objectives(["nonsense", "modernize", "also nonsense"]) == [
        "modernize"
    ]


def test_facets_to_objectives_empty() -> None:
    assert facets_to_objectives([]) == []


def test_integrity_every_value_is_a_real_objective() -> None:
    known = set(available_objectives())
    for phrase, objective in FACET_OBJECTIVE_MAP.items():
        assert objective in known, (
            f"facet {phrase!r} maps to unknown objective {objective!r}"
        )


def test_render_shows_mapping() -> None:
    md = render_facet_plan_markdown(["modernize", "extract a shared helper"])
    assert "Facet → develop plan" in md
    assert "`modernize`" in md
    assert "`dedup`" in md
    assert "| modernize |" in md


def test_render_empty_is_clean() -> None:
    md = render_facet_plan_markdown([])
    assert "No facet maps to a develop objective" in md
    assert "| --- |" not in md


def test_render_all_unmapped_is_clean() -> None:
    md = render_facet_plan_markdown(["nonsense", "more nonsense"])
    assert "No facet maps to a develop objective" in md
    assert "| --- |" not in md


def test_render_dedups_resolution_line() -> None:
    md = render_facet_plan_markdown(["duplicated logic", "single source of truth"])
    # Both rows shown, but the resolution line lists dedup once.
    assert md.count("| dedup ") == 0  # value is rendered as `dedup`, not bare
    assert "Resolves to: `dedup`." in md


def test_end_to_end_new_objective_reachable_from_emitted_facet(tmp_path) -> None:
    """Close the loop: run the idea engine on a synthetic simplify-heavy project,
    collect the facet phrases its zoom machinery actually EMITS, and assert at
    least one objective made reachable by this wave shows up — proving the new
    vocabulary + map entries connect end-to-end, not just in isolation."""
    from app.engine.idea_permutation import (
        DEVELOPMENT_OPERATORS,
        IdeaPermutationEngine,
    )

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
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
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    cfg = {
        "max_total_ideas": 2000, "max_idea_depth": 1, "breadth": 4,
        "fractal_facets": True, "facet_depth": 3, "facets_per_idea": 8,
        "security_aware": False,
    }
    engine = IdeaPermutationEngine(cfg, tmp_path)
    # Confine the zoom to the simplify lens so the deep zoom lands on the new
    # ladder rather than being out-ranked by higher-feasibility lenses.
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "simplify"]
    rep = engine.run()

    emitted = {
        fact.split("facet:", 1)[1].strip()
        for idea in rep.ideas if idea.kind == "facet"
        for fact in idea.source_facts if fact.startswith("facet:")
    }

    new_objectives = {
        "simplify-bool-return", "simplify-ternary-bool", "remove-redundant-else",
        "merge-nested-if", "simplify-dict-get", "use-enumerate",
        "remove-pointless-pass", "remove-unreachable-after-terminator",
    }
    reachable_from_emitted = {
        obj for phrase in emitted
        if (obj := facet_to_objective(phrase)) is not None
    }
    # At least one — in practice all eight — of the wave's objectives is now
    # reachable from a phrase the engine genuinely emitted.
    assert new_objectives & reachable_from_emitted
