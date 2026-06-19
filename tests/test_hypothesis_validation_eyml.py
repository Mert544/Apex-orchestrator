"""Self-validating discovery — discovered patterns become falsifiable hypotheses.

``dream_discovery`` mines *what travels with what* on a codebase; this layer takes
each such discovery, re-states it as a universally-quantified, FALSIFIABLE claim
("every module with `src` also carries `dst`"), and checks it against EVERY module
in the profile — returning **confirmed** (with the count behind it) or
**refuted/weak** (with the concrete modules that break it).

These tests pin: a profile where a hypothesis HOLDS -> ``confirmed`` at full
support; a profile with a real counter-example -> ``weak``/``refuted`` listing the
offending module; the antecedent/consequent re-extraction for each discovery kind;
determinism; the empty/clean -> ``[]`` floor (never raises); and the confidence
[0,1] bound. They consume ``dream_discovery`` only — its surface is untouched.
"""

from __future__ import annotations

from app.engine.hypothesis_validation import (
    CONFIRM_CONFIDENCE,
    MAX_EVIDENCE,
    WEAK_CONFIDENCE,
    discovery_to_hypothesis,
    validate_discoveries,
    validate_hypothesis,
)
from app.tools.project_profile import ProjectProfile

_HYP_KEYS = {"claim", "antecedent", "consequent", "kind"}


def _holds_profile() -> ProjectProfile:
    # Every `security` module is also `untested` (and vice-versa): the
    # association the dream finds is a law that holds on the WHOLE population.
    # FIVE modules, not three: the honesty fix raised the "confirmed" support
    # floor to CONFIRM_ANTECEDENT (5) so a single-digit handful reads as a
    # "candidate (low support)", not a confirmed project-wide law. This profile
    # pins the WELL-SUPPORTED confirm path, so it now clears that floor; the
    # thin-population path is pinned separately below
    # (test_thin_population_below_min_antecedent_is_refuted) and the
    # candidate-band path in tests/test_hypothesis_no_tautology_eyml.py.
    mods = ["app/a.py", "app/b.py", "app/c.py", "app/d.py", "app/e.py"]
    return ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )


def _counter_profile() -> ProjectProfile:
    # `hub` and `untested` each on 4 modules sharing 3 -> a directional
    # association at 0.75 confidence with ONE live counter-example: `honly.py`
    # is a hub but not untested, so it refutes "every hub is untested".
    return ProjectProfile(
        root=".",
        dependency_hubs=["app/s1.py", "app/s2.py", "app/s3.py", "app/honly.py"],
        untested_modules=["app/s1.py", "app/s2.py", "app/s3.py", "app/uonly.py"],
    )


def _clique_profile() -> ProjectProfile:
    # Two modules carry the full {security, untested, fragile} bundle; a third
    # carries only `security` -> a clique whose "carry one => carry all" claim
    # has a counter-example.
    full = ["app/core.py", "app/io.py"]
    return ProjectProfile(
        root=".",
        security_finding_modules=full + ["app/partial.py"],
        untested_modules=list(full),
        fragile_modules=list(full),
    )


# ----------------------------------------------------------------- hypotheses


def test_association_becomes_if_then_hypothesis():
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    assert h is not None
    assert _HYP_KEYS <= set(h)
    assert h["kind"] == "association"
    assert h["antecedent"] == ["security"]
    assert h["consequent"] == ["untested"]
    assert "security" in h["claim"] and "untested" in h["claim"]


def test_triple_becomes_two_term_antecedent():
    h = discovery_to_hypothesis({"key": "triple:fragile&security>untested"})
    assert h is not None
    assert h["kind"] == "triple"
    assert h["antecedent"] == ["fragile", "security"]
    assert h["consequent"] == ["untested"]


def test_clique_becomes_any_implies_all():
    h = discovery_to_hypothesis({"key": "clique:debt&fragile&security"})
    assert h is not None
    assert h["kind"] == "clique"
    assert h["antecedent_any"] is True
    assert set(h["antecedent"]) == {"debt", "fragile", "security"}
    assert set(h["consequent"]) == {"debt", "fragile", "security"}


def test_confluence_has_no_directional_hypothesis():
    # A confluence names one broad module, not an if/then -> not falsifiable here.
    assert discovery_to_hypothesis({"key": "confluence:app/x.py"}) is None


def test_malformed_keys_yield_none():
    for key in ("assoc:nobody", "assoc:>dst", "triple:a>c", "clique:a&b", "", "bogus"):
        assert discovery_to_hypothesis({"key": key}) is None


def test_accepts_discovery_object_not_only_dict():
    class _D:
        key = "assoc:security>untested"

    assert discovery_to_hypothesis(_D()) is not None


# ----------------------------------------------------------------- validation


def test_holding_hypothesis_is_confirmed_with_full_support():
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    result = validate_hypothesis(h, _holds_profile())
    assert result["verdict"] == "confirmed"
    assert result["confidence"] == 1.0
    assert result["counter_examples"] == 0
    assert result["evidence"] == []
    # Five supporting modules — clears the raised CONFIRM_ANTECEDENT floor so the
    # well-supported law still confirms (the honesty fix downgrades only the
    # thin, single-digit-support readings to "candidate").
    assert result["support"] == 5


def test_counter_example_makes_it_weak_and_is_listed_as_evidence():
    [result] = validate_discoveries(_counter_profile())
    assert result["key"] == "assoc:hub>untested"
    assert result["verdict"] == "weak"
    assert result["counter_examples"] == 1
    assert result["evidence"] == ["app/honly.py"]
    assert WEAK_CONFIDENCE <= result["confidence"] < CONFIRM_CONFIDENCE


def test_clique_counter_example_is_caught():
    results = validate_discoveries(_clique_profile(), top=20)
    cliques = [r for r in results if r["kind"] == "clique"]
    assert cliques, "the recurring bundle should produce a clique hypothesis"
    clq = cliques[0]
    # `partial.py` carries `security` (an antecedent member) but not the bundle.
    assert "app/partial.py" in clq["evidence"]
    assert clq["verdict"] in {"weak", "refuted"}


def test_vacuous_hypothesis_is_refuted_not_raised():
    # No module carries `debt`, so the antecedent never matches.
    h = discovery_to_hypothesis({"key": "assoc:debt>security"})
    result = validate_hypothesis(h, _holds_profile())
    assert result["verdict"] == "refuted"
    assert result["confidence"] == 0.0
    assert result["antecedent_modules"] == 0


def test_thin_population_below_min_antecedent_is_refuted():
    # Only ONE module carries the antecedent: too thin to confirm a law.
    p = ProjectProfile(
        root=".",
        security_finding_modules=["app/only.py"],
        untested_modules=["app/only.py", "app/x.py", "app/y.py"],
    )
    h = discovery_to_hypothesis({"key": "assoc:security>untested"})
    result = validate_hypothesis(h, p)
    assert result["confidence"] == 1.0      # it holds on its one module...
    assert result["verdict"] == "refuted"   # ...but the population is too thin


# ----------------------------------------------------------------- invariants


def test_confidence_is_always_bounded_unit_interval():
    for profile in (_holds_profile(), _counter_profile(), _clique_profile()):
        for result in validate_discoveries(profile, top=20):
            assert 0.0 <= result["confidence"] <= 1.0


def test_evidence_never_exceeds_cap():
    mods = [f"app/m{i}.py" for i in range(12)]
    # 12 hubs, none untested but all 'security' so an association exists then
    # fails: every hub is a counter-example to hub>untested if it surfaces.
    p = ProjectProfile(
        root=".",
        dependency_hubs=list(mods),
        security_finding_modules=list(mods),
        untested_modules=mods[:9],
    )
    for result in validate_discoveries(p, top=20):
        assert len(result["evidence"]) <= MAX_EVIDENCE


def test_validation_is_deterministic():
    profile = _counter_profile()
    first = validate_discoveries(profile)
    for _ in range(3):
        assert validate_discoveries(profile) == first


def test_results_are_ranked_confirmed_before_refuted():
    profile = _holds_profile()
    results = validate_discoveries(profile, top=20)
    # `candidate` (clean but low-support) ranks between confirmed and weak after
    # the honesty fix, so it joins the verdict order the ranking must respect.
    order = {"confirmed": 0, "candidate": 1, "weak": 2, "refuted": 3}
    keys = [order[r["verdict"]] for r in results]
    assert keys == sorted(keys)


def test_top_caps_and_non_positive_top_is_empty():
    profile = _holds_profile()
    assert validate_discoveries(profile, top=1) == validate_discoveries(profile)[:1]
    assert validate_discoveries(profile, top=0) == []
    assert validate_discoveries(profile, top=-3) == []


def test_empty_profile_yields_empty_and_never_raises():
    assert validate_discoveries(ProjectProfile(root=".")) == []
    # A clean profile (one tagged module, no co-occurrence) also yields nothing.
    assert validate_discoveries(ProjectProfile(root=".", untested_modules=["app/x.py"])) == []
