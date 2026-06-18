"""Deep-mutation characterization for ``CounterfactualGenerator`` in
``app/engine/counterfactual_generator.py``.

The ``counterfactual_enrichment`` seam is already fully killed by
``tests/test_counterfactual_enrichment_eyml.py``; this file targets the residual
mutant survivors in the ``CounterfactualGenerator`` class that the full mutant
universe (enumerated past the 30-cap via ``mutation_tester._collect_sites``)
exposed: the scenario cap ``[:5]``, the insight-branch boundary ``>= 3``, the
insight text truncation ``text[:40]``, the ``seed or text`` insight seed, and the
no-scenarios insight early return.

Each test pins an exact string or count, so a single-token mutation
(``5`` -> ``6``, ``>=`` -> ``>``/``<``, ``3`` -> ``4``, ``40`` -> ``41``,
``or`` -> ``and``, or ``return <str>`` -> ``return None``) changes the observed
behavior and fails the test. Deterministic — every input is fixed.
"""

from __future__ import annotations

from app.engine.counterfactual_generator import CounterfactualGenerator

# --------------------------------------------------------------------------- #
# Scenario cap: ``scenarios[:5]`` keeps AT MOST five (kills number:5>6 on L342).
# --------------------------------------------------------------------------- #

def test_scenarios_are_capped_at_five():
    gen = CounterfactualGenerator()
    # symbol(+2) + validation(+3) + network(+3) + complex(+2) = 10 raw scenarios,
    # all sliced down to exactly five.
    claim = {
        "text": "long complex validation guard network request fetch call",
        "context": "",
        "symbol": "foo",
    }
    result = gen.generate(claim)
    assert len(result.scenarios) == 5


# --------------------------------------------------------------------------- #
# Insight branch boundary: ``len(scenarios) >= 3`` (kills the >=>>, >=><, and
# 3->4 mutations on L381). Exactly-3 takes the "robust... critical" branch;
# exactly-2 takes the "potential weakness" branch.
# --------------------------------------------------------------------------- #

def test_three_scenarios_take_the_robust_branch():
    gen = CounterfactualGenerator()
    # "validation guard" fires _rule_validation -> exactly 3 scenarios.
    result = gen.generate({"text": "lacks validation guard", "context": ""})
    assert len(result.scenarios) == 3
    assert "appears robust on the surface" in result.insight
    assert "3 critical counter-scenarios" in result.insight
    assert "potential weakness" not in result.insight


def test_two_scenarios_take_the_weakness_branch():
    gen = CounterfactualGenerator()
    # "docstring" fires _rule_docs -> exactly 2 scenarios (below the >= 3 cut).
    result = gen.generate({"text": "function has no docstring", "context": ""})
    assert len(result.scenarios) == 2
    assert "potential weakness" in result.insight
    assert "appears robust on the surface" not in result.insight


# --------------------------------------------------------------------------- #
# Insight claim-text truncation: ``text[:40]`` (kills number:40>41 on L383/L389,
# in BOTH the >=3 branch and the 1..2 branch).
# --------------------------------------------------------------------------- #

def test_robust_branch_truncates_claim_text_at_forty_chars():
    # text seed of 40 'a' then a sentinel; the insight must contain exactly the
    # first 40 chars + "...", never the 41st char.
    seed = "a" * 40 + "XYZ"
    insight = CounterfactualGenerator._generate_insight(seed, ["s1", "s2", "s3"])
    assert "appears robust" in insight
    assert ("a" * 40 + "...") in insight
    assert "X" not in insight


def test_weakness_branch_truncates_claim_text_at_forty_chars():
    seed = "b" * 40 + "XYZ"
    insight = CounterfactualGenerator._generate_insight(seed, ["only-one"])
    assert "potential weakness" in insight
    assert ("b" * 40 + "...") in insight
    assert "X" not in insight


# --------------------------------------------------------------------------- #
# Insight seed selection: ``seed or text`` (kills boolean:or>and on L327).
# A keyed claim supplies a truthy ``seed`` (the lens name) while ``text`` is
# empty, so ``or`` surfaces the lens name and ``and`` would surface the empty.
# --------------------------------------------------------------------------- #

def test_keyed_insight_seed_uses_lens_name_not_empty_text():
    gen = CounterfactualGenerator()
    # operator='harden' -> keyed seed 'harden'; empty text means ``seed and text``
    # would collapse the insight's claim quote to '' instead of 'harden'.
    result = gen.generate({"text": "", "operator": "harden"})
    assert "'harden...'" in result.insight


# --------------------------------------------------------------------------- #
# No-scenarios insight: the ``return "No obvious..."`` early return
# (kills return:value>None on L392).
# --------------------------------------------------------------------------- #

def test_insight_with_no_scenarios_is_the_vague_message():
    insight = CounterfactualGenerator._generate_insight("anything", [])
    assert insight == "No obvious counter-scenarios. Claim may be too vague to evaluate."
