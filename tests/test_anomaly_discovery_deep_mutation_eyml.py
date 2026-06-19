"""Deep-mutation characterization for anomaly discovery.

These tests pin the exact arithmetic, boundaries, constants, ordering and
branch selection inside ``app/engine/anomaly_discovery.py`` that the feature
suite (``test_anomaly_discovery_eyml.py``) leaves exposed to surviving AST
mutants. Each fixture is hand-computed so a single arithmetic / comparison /
boundary / constant mutation makes at least one assertion fail:

* the blend constants ``RARITY_WEIGHT=0.6`` / ``BREADTH_WEIGHT=0.4`` and the
  ``DEVIATION_FLOOR=0.15`` strict ``<`` cutoff (exact deviation values);
* ``_rarity_score`` ``1 - freq/modules`` averaged over tags (empty -> 0.0);
* ``_breadth_score`` symmetric ``|size-median|/max_gap`` capped at 1.0, and its
  ``max_gap <= 0`` flat-codebase short circuit;
* ``_median`` odd vs even (true float average, not int);
* ``_rare_tags`` ``freq*2 <= modules`` minority test and ``(freq, name)`` order;
* ``dominant_pattern`` ``n*2 > count`` strict-majority "typical" set;
* ``_why`` rare[:4] / missing[:3] caps, the broad/narrow/equal branch, and the
  ``:g`` median rendering;
* ``module_profiles`` field-to-tag mapping, the ``co-change`` pairing and the
  empty-module skip; ``MIN_MODULES`` abstention and the ``top`` cap/guard.

All assertions are deterministic (no time/random; module-name keyed order).
"""

from __future__ import annotations

from app.engine.anomaly_discovery import (
    BREADTH_WEIGHT,
    DEVIATION_FLOOR,
    MIN_MODULES,
    RARITY_WEIGHT,
    SEVERITY_WEIGHT,
    _breadth_score,
    _median,
    _rare_tags,
    _rarity_score,
    _score_module,
    _severity_score,
    _why,
    dominant_pattern,
    find_anomalies,
    module_profiles,
)
from app.tools.project_profile import ProjectProfile


# --------------------------------------------------------------------------- #
# Blend constants are exactly 0.6 / 0.4 and sum to 1 (score stays in [0, 1]).
# --------------------------------------------------------------------------- #
def test_blend_weights_are_exact_and_normalised():
    """The three grounded parts blend with fixed weights summing to one; if any
    drifts the deviation bound and every computed score below shift. SEVERITY is
    the dominant weight (risk outranks structural noise)."""
    assert RARITY_WEIGHT == 0.3
    assert BREADTH_WEIGHT == 0.15
    assert SEVERITY_WEIGHT == 0.55
    assert RARITY_WEIGHT + BREADTH_WEIGHT + SEVERITY_WEIGHT == 1.0
    assert SEVERITY_WEIGHT > RARITY_WEIGHT > BREADTH_WEIGHT
    assert DEVIATION_FLOOR == 0.15
    assert MIN_MODULES == 3


# --------------------------------------------------------------------------- #
# Exact deviation arithmetic on a fully hand-computed 4-module fixture.
# --------------------------------------------------------------------------- #
def _graded_profile() -> ProjectProfile:
    # Breadths a=1, b=2, c=3, d=4; freq untested=4, security=3, fragile=2,
    # debt=1; median breadth = (2+3)/2 = 2.5; max_gap = |4-2.5| = 1.5.
    return ProjectProfile(
        root=".",
        untested_modules=["a", "b", "c", "d"],
        security_finding_modules=["b", "c", "d"],
        fragile_modules=["c", "d"],
        debt_marker_modules=["d"],
    )


def test_top_anomaly_deviation_is_exact():
    """``d`` carries {debt, fragile, security, untested}:
    rarity = ((1-1/4)+(1-2/4)+(1-3/4)+(1-4/4))/4 = 1.5/4 = 0.375;
    broadness = (4-2.5)/1.5 = 1.0 (asymmetric, above median);
    severity = max over tags of weight*(1-freq/4): debt 0.45*0.75=0.3375 wins ->
      round 0.338; (security 1.0*0.25=0.25, fragile 0.6*0.5=0.3, untested 0).
    deviation = 0.3*0.375 + 0.15*1.0 + 0.55*0.3375 = 0.448125 -> round 0.448.
    Any weight/term mutation moves it."""
    anomalies = find_anomalies(_graded_profile(), top=99)
    top = anomalies[0]
    assert top["module"] == "d"
    assert top["rarity"] == 0.375
    assert top["severity"] == 0.338
    assert top["deviation"] == 0.448


def test_full_ranking_values_and_order_are_exact():
    """Every surfaced record's deviation/rarity/severity is pinned, and the
    descending-deviation order is exact — catching sign flips in the sort key and
    the blend math. ``a`` (only the ubiquitous ``untested``) now has rarity 0,
    severity 0 and is NARROW (asymmetric breadth -> 0), so deviation 0: it is
    DROPPED, the inverse of the old severity-blind behaviour that ranked it 2nd."""
    anomalies = find_anomalies(_graded_profile(), top=99)
    got = [(a["module"], a["deviation"], a["rarity"], a["severity"])
           for a in anomalies]
    # d: 0.3*0.375 + 0.15*1.0 + 0.55*0.3375 = 0.448
    # c={fragile,security,untested}: rarity 0.25, broad (3-2.5)/1.5=0.3333,
    #   severity max(fragile 0.6*0.5=0.3, security 0.25, untested 0)=0.3 ->
    #   0.3*0.25 + 0.15*0.3333 + 0.55*0.3 = 0.29 -> round 0.29
    # b={security,untested}: rarity 0.125, narrow -> broadness 0,
    #   severity max(security 1.0*0.25=0.25, untested 0)=0.25 ->
    #   0.3*0.125 + 0.15*0 + 0.55*0.25 = 0.175 -> round 0.175
    # a={untested}: rarity 0, narrow -> 0, severity 0 -> deviation 0 -> DROPPED.
    assert got == [
        ("d", 0.448, 0.375, 0.338),
        ("c", 0.29, 0.25, 0.3),
        ("b", 0.175, 0.125, 0.25),
    ]


def test_why_names_rare_breadth_and_missing_for_top():
    """``d`` names its two rare signals (debt before fragile, rarest first),
    the broad-breadth branch with the ``:g`` median (2.5), and no missing
    typical signal (it carries both). Pins all three ``_why`` clauses."""
    top = find_anomalies(_graded_profile(), top=99)[0]
    assert top["why"] == (
        "carries rare signal(s) `debt`, `fragile`; "
        "unusually broad (4 signals vs median 2.5)."
    )


def test_why_below_median_emits_no_narrow_clause():
    """Breadth is ASYMMETRIC now: a module BELOW the median is not anomalous for
    it, so ``_why`` never emits an "unusually narrow" clause. ``b`` carries
    {security, untested} (breadth 2 < median 2.5), no rare tag (both on a
    majority) and both typical signals — it surfaces only on its rare ``security``
    SEVERITY, and its ``why`` says nothing about being narrow or broad."""
    records = {a["module"]: a for a in find_anomalies(_graded_profile(), top=99)}
    assert "unusually narrow" not in records["b"]["why"]
    assert "unusually broad" not in records["b"]["why"]
    assert records["b"]["why"] == "an off-pattern fingerprint."


# --------------------------------------------------------------------------- #
# The DEVIATION_FLOOR cutoff is a STRICT < : a module exactly at 0.15 is kept.
# --------------------------------------------------------------------------- #
def test_module_exactly_at_floor_is_kept():
    """A module whose deviation lands EXACTLY on the floor is RETAINED, because
    the cutoff is ``deviation < FLOOR`` (strict) — a ``<`` -> ``<=`` mutant would
    drop it. Hand-built norm: four tags each on all four modules (rarity 0,
    severity 0), module ``x`` carries all four → broad (size 4 vs median 1,
    max_gap 3) → broadness (4-1)/3 = 1.0 → deviation 0.15*1.0 = 0.15 == FLOOR."""
    norm = {
        "frequency": {"t": 4, "u": 4, "v": 4, "w": 4},
        "modules": 4,
        "median_breadth": 1.0,
        "typical": set(),
    }
    record = _score_module("x", {"t", "u", "v", "w"}, norm, 3.0)
    assert record is not None  # retained, not dropped
    assert record["deviation"] == 0.15
    assert record["rarity"] == 0.0
    assert record["severity"] == 0.0
    assert record["why"] == "unusually broad (4 signals vs median 1)."


def test_security_modules_outrank_structural_at_floor():
    """Three modules carry a rare ``security`` signal (freq 3 of 4), one a rare
    ``debt``. Flat breadth -> broadness 0. A ``security`` module: rarity 0.25,
    severity 1.0*(1-3/4)=0.25 -> 0.3*0.25 + 0.55*0.25 = 0.2125 -> round 0.213,
    kept (> FLOOR). ``debt``: rarity 0.75, severity 0.45*0.75=0.3375 ->
    0.3*0.75 + 0.55*0.3375 = 0.410625 -> round 0.411, ranks FIRST."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],
        debt_marker_modules=["d"],
    )
    anomalies = find_anomalies(profile, top=99)
    by_mod = {a["module"]: a for a in anomalies}
    assert set(by_mod) == {"a", "b", "c", "d"}
    for m in ("a", "b", "c"):
        assert by_mod[m]["deviation"] == 0.213
        assert by_mod[m]["severity"] == 0.25
        assert by_mod[m]["why"] == "an off-pattern fingerprint."
    assert anomalies[0]["module"] == "d"
    assert by_mod["d"]["deviation"] == 0.411
    assert by_mod["d"]["rarity"] == 0.75


def test_ties_break_by_module_name_ascending():
    """The three ``security`` modules share deviation 0.213, severity 0.25 and
    rarity 0.25 -> a full tie, so the final tie-break is the module name
    ascending: a, b, c (after the sole ``debt`` leader ``d``)."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],
        debt_marker_modules=["d"],
    )
    names = [a["module"] for a in find_anomalies(profile, top=99)]
    assert names == ["d", "a", "b", "c"]


# --------------------------------------------------------------------------- #
# _rarity_score: averaged 1 - freq/modules, empty -> 0.0.
# --------------------------------------------------------------------------- #
def test_rarity_score_is_average_of_per_tag_rarity():
    """Two tags, freq 1 and 3 of 4 modules: (0.75 + 0.25)/2 = 0.5 exactly."""
    assert _rarity_score({"x", "y"}, {"x": 1, "y": 3}, 4) == 0.5


def test_rarity_score_singleton_on_every_module_is_zero():
    """A tag carried by every module contributes 1 - modules/modules = 0."""
    assert _rarity_score({"all"}, {"all": 5}, 5) == 0.0


def test_rarity_score_empty_tagset_is_zero():
    """An untagged module is maximally un-rare -> exactly 0.0 (no ZeroDivision)."""
    assert _rarity_score(set(), {}, 4) == 0.0


# --------------------------------------------------------------------------- #
# _severity_score: MAX over tags of weight*(1-freq/modules); ubiquitous -> 0.
# --------------------------------------------------------------------------- #
def test_severity_score_is_rarity_scaled_max_not_average():
    """A rare high-risk tag dominates and is NOT diluted by structural tags:
    max(security 1.0*(1-1/4)=0.75, symbol-hub 0.15*(1-1/4)=0.1125) = 0.75 — a
    ``max`` -> ``sum/len`` mutant would average to ~0.43 and fail."""
    assert _severity_score({"security", "symbol-hub"},
                           {"security": 1, "symbol-hub": 1}, 4) == 0.75


def test_severity_score_ubiquitous_risk_is_zero():
    """A risk signal on EVERY module is no OUTLIER: 1.0*(1-4/4) = 0.0. Pins the
    ``1 - freq/modules`` rarity scaling against a constant-1 mutant."""
    assert _severity_score({"security"}, {"security": 4}, 4) == 0.0


def test_severity_score_empty_and_degenerate_are_zero():
    """Untagged or zero-module inputs -> exactly 0.0 (no ZeroDivision)."""
    assert _severity_score(set(), {}, 4) == 0.0
    assert _severity_score({"security"}, {"security": 1}, 0) == 0.0


# --------------------------------------------------------------------------- #
# _breadth_score: ASYMMETRIC (only the broad side deviates), capped at 1.0,
# flat codebase -> 0.0.
# --------------------------------------------------------------------------- #
def test_breadth_score_is_asymmetric_broad_side_only():
    """Only UNUSUALLY MANY signals deviate: above the median (3 vs 2.5) gives
    (3-2.5)/1.5 = 0.3333..., but BELOW the median (2 vs 2.5 — a narrow/empty
    file) gives 0.0, NOT the old symmetric 0.3333. A narrow file is not a risk."""
    above = _breadth_score(3, 2.5, 1.5)
    below = _breadth_score(2, 2.5, 1.5)
    assert round(above, 4) == 0.3333
    assert below == 0.0
    assert above != below


def test_breadth_score_at_median_is_zero():
    """Exactly at the median is not broad -> 0.0 (the ``excess <= 0`` guard)."""
    assert _breadth_score(2, 2.0, 1.5) == 0.0


def test_breadth_score_caps_at_one():
    """A broad gap larger than max_gap is clamped: (5-2.0)/1.5 = 2.0 -> min ->
    1.0 (still only on the broad side)."""
    assert _breadth_score(5, 2.0, 1.5) == 1.0


def test_breadth_score_flat_codebase_is_zero():
    """max_gap <= 0 (every module same breadth) short-circuits to 0.0, never
    dividing by zero — pins the ``<= 0`` guard (not ``< 0``)."""
    assert _breadth_score(2, 2.0, 0.0) == 0.0
    assert _breadth_score(7, 2.0, -1.0) == 0.0


# --------------------------------------------------------------------------- #
# _median: odd returns the middle, even averages as a true float.
# --------------------------------------------------------------------------- #
def test_median_odd_is_exact_middle():
    assert _median([3, 1, 2]) == 2.0
    assert _median([5]) == 5.0


def test_median_even_is_float_average_not_int():
    """(1 + 4)/2 must be 2.5, not integer 2 — pins the float division."""
    assert _median([4, 1]) == 2.5
    assert _median([1, 2, 2, 3]) == 2.0


# --------------------------------------------------------------------------- #
# _rare_tags: minority test freq*2 <= modules, ordered (freq, name).
# --------------------------------------------------------------------------- #
def test_rare_tags_minority_boundary_is_inclusive():
    """A tag on exactly half the modules (freq*2 == modules) is rare; a strict
    majority is not. With 4 modules, freq 2 is rare, freq 3 is not."""
    rare = _rare_tags({"half", "most"}, {"half": 2, "most": 3}, 4)
    assert rare == ["half"]


def test_rare_tags_ordered_by_frequency_then_name():
    """Rarest first; equal frequency breaks by tag name ascending."""
    freq = {"z": 1, "a": 1, "m": 2}
    assert _rare_tags({"z", "a", "m"}, freq, 4) == ["a", "z", "m"]


# --------------------------------------------------------------------------- #
# dominant_pattern: "typical" is a STRICT majority (n*2 > count).
# --------------------------------------------------------------------------- #
def test_typical_requires_strict_majority():
    """With 4 modules a tag on exactly 2 (half) is NOT typical; one on 3 is.
    Pins ``n*2 > count`` against a ``>=`` mutant that would admit the half."""
    profiles = {
        "a": {"three", "two"},
        "b": {"three", "two"},
        "c": {"three"},
        "d": {"three"},
    }
    norm = dominant_pattern(profiles)
    assert norm["frequency"] == {"three": 4, "two": 2}
    assert norm["typical"] == {"three"}
    assert norm["modules"] == 4
    assert norm["median_breadth"] == 1.5


def test_dominant_pattern_empty_is_zeroed():
    """Empty profile -> a zeroed norm so callers never raise."""
    assert dominant_pattern({}) == {
        "modules": 0,
        "frequency": {},
        "median_breadth": 0.0,
        "typical": set(),
    }


# --------------------------------------------------------------------------- #
# _why caps: at most 4 rare signals and at most 3 missing typical signals.
# --------------------------------------------------------------------------- #
def test_why_caps_rare_at_four_and_missing_at_three():
    """Five rare tags render only the first four; four missing typical signals
    render only the first three (alphabetical). Pins both slice bounds."""
    norm = {"median_breadth": 3.0, "typical": {"t1", "t2", "t3", "t4"}}
    text = _why(
        {"r1", "r2", "r3", "r4", "r5"},
        norm,
        5,
        ["r1", "r2", "r3", "r4", "r5"],
    )
    assert text == (
        "carries rare signal(s) `r1`, `r2`, `r3`, `r4`; "
        "unusually broad (5 signals vs median 3); "
        "lacks the typical signal(s) `t1`, `t2`, `t3`."
    )


def test_why_equal_breadth_emits_no_breadth_clause():
    """When size == median neither broad nor narrow fires; with no rare tags and
    nothing missing the fallback ``an off-pattern fingerprint.`` is used."""
    norm = {"median_breadth": 2.0, "typical": set()}
    assert _why({"a", "b"}, norm, 2, []) == "an off-pattern fingerprint."


# --------------------------------------------------------------------------- #
# module_profiles: field->tag mapping, co-change pairing, empty-module skip.
# --------------------------------------------------------------------------- #
def test_module_profiles_maps_rows_couplings_and_skips_empty():
    """Row fields (churn/knowledge/hotspot) and ``change_coupling`` (both ends
    tagged ``co-change``) feed the fingerprint; an empty module path is skipped
    entirely rather than creating a blank bucket."""
    profile = ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/x.py"}],
        knowledge_risks=[{"module": "app/x.py"}],
        hotspot_functions=[{"module": "app/y.py"}],
        change_coupling=[{"a": "app/x.py", "b": "app/z.py"}],
        security_finding_modules=["", "app/y.py"],
    )
    profs = module_profiles(profile)
    assert "" not in profs
    assert profs["app/x.py"] == {"high-churn", "single-author", "co-change"}
    assert profs["app/y.py"] == {"complex-function", "security"}
    assert profs["app/z.py"] == {"co-change"}


def test_string_field_tag_vocabulary_is_exact():
    """Each ``_STR_FIELDS`` source maps to its precise tag string — a renamed
    constant would change the surfaced fingerprint vocabulary."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["m"],
        correctness_bug_modules=["m"],
        mutable_default_modules=["m"],
        symbol_hubs=["m"],
        sensitive_paths=["m"],
    )
    assert module_profiles(profile)["m"] == {
        "security",
        "correctness-bug",
        "mutable-defaults",
        "symbol-hub",
        "sensitive-path",
    }


# --------------------------------------------------------------------------- #
# find_anomalies guards: MIN_MODULES abstention and the top cap.
# --------------------------------------------------------------------------- #
def test_two_modules_is_below_min_and_abstains():
    """Exactly two tagged modules (< MIN_MODULES of 3) -> [] — a boundary that
    distinguishes ``< 3`` from ``<= 3``/``< 2``."""
    profile = ProjectProfile(
        root=".",
        debt_marker_modules=["a"],
        symbol_hubs=["b"],
    )
    assert len(module_profiles(profile)) == 2
    assert find_anomalies(profile) == []


def test_three_modules_is_exactly_at_min_and_runs():
    """Three tagged modules is exactly MIN_MODULES -> the guard does NOT abstain
    (``len < 3`` is False), so anomalies are produced."""
    profile = ProjectProfile(
        root=".",
        debt_marker_modules=["a"],
        symbol_hubs=["b"],
        sensitive_paths=["c"],
    )
    assert len(module_profiles(profile)) == 3
    assert find_anomalies(profile) != []


def test_top_caps_result_length_exactly():
    """``top`` limits the returned list length precisely; non-positive -> []."""
    profile = _graded_profile()
    assert len(find_anomalies(profile, top=2)) == 2
    assert len(find_anomalies(profile, top=1)) == 1
    assert find_anomalies(profile, top=0) == []
    assert find_anomalies(profile, top=-3) == []
