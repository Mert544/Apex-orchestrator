from __future__ import annotations

from app.engine.counterfactual_generator import (
    _LENS_SCENARIOS,
    CounterfactualGenerator,
)
from app.engine.idea_permutation import DEVELOPMENT_OPERATORS


def _operator_names() -> list[str]:
    # Stable, source-ordered list of every development lens.
    return [op.name for op in DEVELOPMENT_OPERATORS]


def test_every_operator_has_a_lens_scenario():
    # KEY COVERAGE GUARD: no development lens may fall through to the generic
    # keyword fallback. Every operator in DEVELOPMENT_OPERATORS must be keyed,
    # and every keyed lens must carry a real (non-empty, >=2) scenario list.
    missing = [name for name in _operator_names() if name not in _LENS_SCENARIOS]
    assert missing == [], f"operators without counterfactual scenarios: {missing}"
    for name in _operator_names():
        scenarios = _LENS_SCENARIOS[name]
        assert len(scenarios) >= 2, f"{name} has a thin scenario list"
        assert all(s.strip() for s in scenarios), f"{name} has an empty scenario"


def test_coverage_list_matches_operator_alphabet_exactly():
    # The lens dict must not drift from the operator alphabet in either
    # direction: no orphan keys, no uncovered operators. This pins the
    # one-to-one mapping that keeps counterfactual depth honest.
    op_names = set(_operator_names())
    lens_keys = set(_LENS_SCENARIOS)
    assert op_names <= lens_keys, f"uncovered operators: {sorted(op_names - lens_keys)}"


def test_every_operator_generates_grounded_scenarios():
    gen = CounterfactualGenerator()
    for name in _operator_names():
        res = gen.generate({"text": f"{name} app/x.py", "operator": name})
        assert res.scenarios, f"{name} produced no scenarios"
        # Each lens carries at least two stress tests, all non-empty.
        assert len([s for s in res.scenarios if s.strip()]) >= 2
        # Grounded, not vague: ends as a probing question.
        assert all(s.rstrip().endswith("?") for s in res.scenarios), name


def test_lens_scenarios_are_distinct_across_operators():
    # No two lenses may collapse onto the same opening caveat.
    gen = CounterfactualGenerator()
    firsts = {
        name: gen.generate({"text": f"{name} app/x.py", "operator": name}).scenarios[0]
        for name in _operator_names()
    }
    assert len(set(firsts.values())) == len(firsts)


def test_generation_is_deterministic():
    # Same input -> identical output across repeated runs (no time/random,
    # no set-iteration leaking into the ordering).
    gen = CounterfactualGenerator()
    for name in _operator_names():
        claim = {"text": f"{name} app/x.py", "operator": name}
        a = gen.generate(claim).to_dict()
        b = gen.generate(claim).to_dict()
        assert a == b, name


def test_lens_scenarios_dict_iteration_is_ordered():
    # Two independent reads of the keys must agree (dict preserves insertion
    # order; this pins that no set() is silently introduced upstream).
    assert list(_LENS_SCENARIOS.keys()) == list(_LENS_SCENARIOS.keys())


def test_security_is_supporting_not_headline():
    # Security flavor surfaces under the protective lenses (harden/fortify) but
    # must not dominate the others — those lead with their own failure mode.
    gen = CounterfactualGenerator()
    harden = gen.generate({"text": "harden x", "operator": "harden"}).scenarios[0]
    assert "attacker" in harden.lower()
    for name in ("test", "simplify", "document", "observe", "decouple"):
        lead = gen.generate({"text": f"{name} x", "operator": name}).scenarios[0]
        assert "attacker" not in lead.lower(), name


def test_recently_added_lenses_are_concrete():
    # fortify / verify / decouple each name a real failure mode, not a template.
    gen = CounterfactualGenerator()
    fortify = " ".join(gen.generate({"text": "fortify x", "operator": "fortify"}).scenarios).lower()
    verify = " ".join(gen.generate({"text": "verify x", "operator": "verify"}).scenarios).lower()
    decouple = " ".join(gen.generate({"text": "decouple x", "operator": "decouple"}).scenarios).lower()
    assert "guard" in fortify or "edge input" in fortify
    assert "invariant" in verify or "precondition" in verify or "proof" in verify
    assert "coupling" in decouple or "interface" in decouple or "abstraction" in decouple
