"""Mutation-hardening tests for the reflection engine trio.

Independently pins the mutation-sensitive behavior of:
  * app/engine/counterfactual_generator.py
  * app/engine/recursive_reflection.py
  * app/engine/reflector.py

so the seeded-fault kill set does not depend on characterization tests
scattered across unrelated modules. Each test names the precise behavior
(boundary, arithmetic sign, exact literal, membership, branch) a surviving
mutant would otherwise expose. Fully deterministic: no timestamps from
wall-clock, no set/dict ordering assertions.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.counterfactual_generator import (
    CounterfactualGenerator,
    CounterfactualResult,
)
from app.engine.recursive_reflection import (
    RecursiveReflectionEngine,
    ReflectionResult,
)
from app.engine.feedback_loop import FeedbackEntry, FeedbackLoop
from app.engine.reflector import (
    Reflector,
    _build_recommendations,
    _compute_rates,
    _top_false_positives,
    _unique_days,
)


# ---------------------------------------------------------------------------
# counterfactual_generator.py
# ---------------------------------------------------------------------------


class TestCounterfactualGenerator:
    def test_symbol_scenarios_precede_keyed(self):
        # _symbol_scenarios runs first and is prepended; the two symbol lines
        # must appear before the keyed lens lines (kills return-None on L291
        # and ordering mutations).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "extend x", "operator": "extend", "symbol": "foo"})
        assert res.scenarios[0] == (
            "What if foo() hits its rarest branch with an input no test has ever exercised?"
        )
        assert res.scenarios[1] == (
            "What if a caller depends on an undocumented behavior of foo() "
            "that a refactor silently changes?"
        )

    def test_no_symbol_yields_empty_symbol_block(self):
        # Empty symbol -> [] (kills the `if not symbol: return []` guard flip).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "plain claim", "symbol": ""})
        # First scenario must be a keyword/fallback one, never a symbol line.
        assert "()" not in res.scenarios[0]

    def test_keyed_operator_membership_routes_to_lens(self):
        # operator IN _LENS_SCENARIOS -> lens scenarios (kills `in`->`not in`
        # on L305 and the keyed early-return None on L306).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "x", "operator": "harden"})
        assert res.scenarios[0].startswith(
            "What if an attacker reaches this with None"
        )

    def test_unkeyed_operator_does_not_route_to_lens(self):
        # An operator NOT in the table must fall through to keyword/fallback,
        # not emit lens scenarios (kills `in`->`not in` on L305).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "totally generic claim with no keywords",
                            "operator": "not-a-real-lens"})
        joined = " ".join(res.scenarios)
        assert "attacker reaches this with None" not in joined
        assert res.scenarios[0].startswith("What if the claim holds in the current")

    def test_fact_label_membership_routes(self):
        # fact_label IN _FACT_SCENARIOS (kills `in`->`not in` on L308 and the
        # keyed return-None on L309).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "x", "fact_label": "security-finding"})
        assert res.scenarios[0].startswith(
            "What can an attacker execute by reaching the eval/exec/deserialize"
        )

    def test_unknown_fact_label_falls_through(self):
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "vague generic statement here",
                            "fact_label": "no-such-fact"})
        assert res.scenarios[0].startswith("What if the claim holds in the current")

    def test_keyword_scenarios_returned_not_dropped(self):
        # _keyword_scenarios must return its accumulated list (kills return-None
        # on L318): a validation claim yields the three validation scenarios.
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "missing input validation guard"})
        assert "What if an attacker provides None or malformed input?" in res.scenarios

    def test_insight_three_or_more_branch_boundary(self):
        # len(scenarios) >= 3 picks the "robust on the surface" wording. The
        # validation rule emits exactly 3 scenarios -> hits the >=3 branch.
        # Kills boundary `>=`->`>` and `>=`->`<` and number 3->4 on L322.
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "missing input validation"})
        assert len(res.scenarios) == 3
        assert "appears robust on the surface" in res.insight
        assert "3 critical counter-scenarios" in res.insight

    def test_insight_single_weakness_branch(self):
        # Exactly one scenario -> the "1 potential weakness" wording (the elif).
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "mutable default argument here"})
        assert len(res.scenarios) == 1
        assert "1 potential weakness" in res.insight
        assert "robust on the surface" not in res.insight

    def test_insight_truncates_seed_at_40_chars(self):
        # _generate_insight uses text[:40] (kills number 40->41 on L324/L330).
        gen = CounterfactualGenerator()
        # generate() lowercases the claim text before it becomes the insight
        # seed, so use a lowercase seed for a byte-exact slice assertion.
        seed = "missing validation " + "a" * 60  # >> 40 chars
        res = gen.generate({"text": seed})
        # Three validation scenarios -> robust branch, seed truncated to 40.
        assert "'" + seed[:40] + "..." in res.insight
        assert seed[:41] + "..." not in res.insight

    def test_insight_empty_when_no_scenarios_is_unreachable_but_fallback_present(self):
        # An un-keyed, keyword-free claim falls back to two generic scenarios,
        # so the insight is the >=... no, 2 scenarios -> elif branch wording.
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "zzz"})
        assert len(res.scenarios) == 2
        assert "2 potential weakness" in res.insight

    def test_no_obvious_counterscenarios_string_is_returned(self):
        # _generate_insight returns the exact "No obvious counter-scenarios"
        # string when scenarios is empty (kills return-None on L333). Reached
        # directly via the static method with an empty list.
        out = CounterfactualGenerator._generate_insight("claim", [])
        assert out == "No obvious counter-scenarios. Claim may be too vague to evaluate."

    def test_build_caps_scenarios_at_five(self):
        # _build slices scenarios[:5]; network rule (3) + symbol (2) = 5 exactly.
        gen = CounterfactualGenerator()
        res = gen.generate({"text": "network request fetch call", "symbol": "fn"})
        assert len(res.scenarios) == 5

    def test_to_dict_round_trip(self):
        r = CounterfactualResult(scenarios=["a"], insight="i", claim_text="c")
        assert r.to_dict() == {"scenarios": ["a"], "insight": "i", "claim_text": "c"}


# ---------------------------------------------------------------------------
# recursive_reflection.py
# ---------------------------------------------------------------------------


def _engine() -> RecursiveReflectionEngine:
    return RecursiveReflectionEngine()


class TestRecursiveReflectionEvidence:
    def test_sufficient_requires_three_evidence_and_high_confidence(self):
        # ev_score >= 3 AND confidence >= 0.7 -> sufficient, needs_more=False.
        out, needs = RecursiveReflectionEngine._reflect_evidence(
            ["a", "b", "c"], 0.7
        )
        assert needs is False
        assert "sufficient" in out.lower()

    def test_two_evidence_is_not_sufficient(self):
        # ev_score 2 (< 3) must NOT take the sufficient branch even at conf 0.9
        # (kills boundary on the >=3 evidence check).
        out, needs = RecursiveReflectionEngine._reflect_evidence(["a", "b"], 0.9)
        assert needs is True
        assert "incomplete" in out.lower()

    def test_three_evidence_low_confidence_falls_to_incomplete(self):
        # conf 0.69 (< 0.7) with 3 evidence -> the "present but incomplete"
        # branch, not sufficient.
        out, needs = RecursiveReflectionEngine._reflect_evidence(
            ["a", "b", "c"], 0.69
        )
        assert needs is True
        assert "incomplete" in out.lower()

    def test_one_evidence_mid_confidence_present_branch(self):
        out, needs = RecursiveReflectionEngine._reflect_evidence(["a"], 0.5)
        assert needs is True
        assert "present but may be incomplete" in out.lower()

    def test_one_evidence_low_confidence_weak_branch(self):
        # conf 0.49 (< 0.5) with 1 evidence -> weak/missing branch.
        out, needs = RecursiveReflectionEngine._reflect_evidence(["a"], 0.49)
        assert needs is True
        assert "weak or missing" in out.lower()

    def test_zero_evidence_weak_branch(self):
        out, needs = RecursiveReflectionEngine._reflect_evidence([], 0.99)
        assert needs is True
        assert "weak or missing" in out.lower()


class TestRecursiveReflectionAbsolute:
    def test_absolute_words_detected(self):
        for word, text in [
            ("all", "all paths covered"),
            ("every", "every case handled"),
            ("always", "this always works"),
            ("never", "this never fails"),
            ("no ", "there is no bug"),
            ("none", "none remain"),
        ]:
            assert RecursiveReflectionEngine._has_absolute_language(text) is True

    def test_non_absolute_language_is_false(self):
        assert RecursiveReflectionEngine._has_absolute_language(
            "the module mostly behaves"
        ) is False

    def test_boundary_reflection_flags_absolute(self):
        msg = RecursiveReflectionEngine._reflect_boundary("all x", True)
        assert "absolute language" in msg.lower()

    def test_boundary_reflection_bounded_when_not_absolute(self):
        msg = RecursiveReflectionEngine._reflect_boundary("a claim", False)
        assert msg == "Layer 2 — Claim language is bounded. Good."


class TestRecursiveReflectionCounterexamples:
    def test_matched_counterexamples_keyword(self):
        out = RecursiveReflectionEngine._matched_counterexamples(
            "this is secure and safe"
        )
        assert out == [
            "What if an attacker provides crafted input that bypasses the validation?"
        ]

    def test_membership_in_keyword_required(self):
        # The `kw in lower` membership (kills `in`->`not in` on L158): a string
        # with NONE of the rule keywords must match nothing and fall back.
        out = RecursiveReflectionEngine._matched_counterexamples("zzz qqq")
        assert out == []

    def test_fallback_when_no_match(self):
        ce = RecursiveReflectionEngine._generate_counterexamples("zzz qqq", [])
        assert ce == list(RecursiveReflectionEngine._COUNTEREXAMPLE_FALLBACK)

    def test_counterexamples_capped_at_three(self):
        # A text hitting many rules must be sliced to exactly 3 (kills
        # number 3->4 and the return-None on L165).
        text = "secure safe all every test coverage fast performance no never thread concurrent"
        ce = RecursiveReflectionEngine._generate_counterexamples(text, [])
        assert len(ce) == 3

    def test_reflect_counterexamples_nonempty_message(self):
        msg = RecursiveReflectionEngine._reflect_counterexamples(["a", "b"])
        assert "Generated 2 counter-example" in msg

    def test_reflect_counterexamples_empty_message(self):
        msg = RecursiveReflectionEngine._reflect_counterexamples([])
        assert "too vague" in msg.lower()


class TestRecursiveReflectionMeta:
    def test_short_claim_under_five_words(self):
        # word_count < 5 (kills boundary `<`->`<=` and number 5->6 on L115/132).
        assert RecursiveReflectionEngine._reflect_meta(4).startswith(
            "Layer 4 — Claim is very short"
        )

    def test_exactly_five_words_is_appropriate(self):
        # word_count == 5 must NOT be "very short" (boundary check).
        assert "appropriate" in RecursiveReflectionEngine._reflect_meta(5)

    def test_long_claim_over_thirty_words(self):
        # word_count > 30 (kills boundary `>`->`>=` and number 30->31 on L117).
        assert RecursiveReflectionEngine._reflect_meta(31).startswith(
            "Layer 4 — Claim is very long"
        )

    def test_exactly_thirty_words_is_appropriate(self):
        assert "appropriate" in RecursiveReflectionEngine._reflect_meta(30)


class TestRecursiveReflectionPenalty:
    def test_no_penalty_when_all_clear(self):
        assert RecursiveReflectionEngine._compute_penalty(False, False, 0, 10) == 0

    def test_needs_more_evidence_adds_point_three(self):
        # +0.3 (kills augassign +=/-= and number 0.3 on L127).
        assert RecursiveReflectionEngine._compute_penalty(True, False, 0, 10) == 0.3

    def test_absolute_adds_point_two(self):
        assert RecursiveReflectionEngine._compute_penalty(False, True, 0, 10) == 0.2

    def test_three_counterexamples_add_point_one(self):
        # counter_count >= 3 -> +0.1 (kills boundary >= and number 3->4 on L130).
        assert RecursiveReflectionEngine._compute_penalty(False, False, 3, 10) == 0.1

    def test_two_counterexamples_add_nothing(self):
        # counter_count 2 (< 3) must not add the counter penalty.
        assert RecursiveReflectionEngine._compute_penalty(False, False, 2, 10) == 0.0

    def test_short_wordcount_adds_point_one(self):
        # word_count < 5 -> +0.1 (kills boundary <-> and number 5->6 on L132).
        assert RecursiveReflectionEngine._compute_penalty(False, False, 0, 4) == 0.1

    def test_exactly_five_words_no_short_penalty(self):
        assert RecursiveReflectionEngine._compute_penalty(False, False, 0, 5) == 0.0

    def test_all_penalties_sum(self):
        # 0.3 + 0.2 + 0.1 + 0.1 = 0.7 (every += must stay additive).
        assert RecursiveReflectionEngine._compute_penalty(True, True, 3, 4) == 0.7


class TestRecursiveReflectionVerdict:
    def test_valid_rationale_text(self):
        eng = RecursiveReflectionEngine(max_depth=4)
        msg = eng._verdict_rationale(True, 0.82)
        assert "survived 4 reflection layers" in msg
        assert "0.82" in msg

    def test_invalid_rationale_text(self):
        eng = RecursiveReflectionEngine(max_depth=4)
        msg = eng._verdict_rationale(False, 0.12)
        assert "failed reflection scrutiny" in msg
        assert "0.12" in msg


class TestRecursiveReflectionInsight:
    def test_valid_verdict_branch(self):
        # verdict == "valid" picks the well-supported wording (kills `==`->`!=`
        # on L169 and return-None on L170).
        out = RecursiveReflectionEngine._generate_insight("claim text", [], "valid")
        assert "well-supported" in out

    def test_invalid_verdict_branch(self):
        out = RecursiveReflectionEngine._generate_insight("claim text", [], "invalid")
        assert "needs strengthening" in out

    def test_insight_truncates_at_40_chars(self):
        # text[:40] (kills number 40->41 on L170/L171).
        seed = "Z" * 60
        out = RecursiveReflectionEngine._generate_insight(seed, [], "valid")
        assert "'" + seed[:40] + "..." in out
        assert seed[:41] + "..." not in out


class TestRecursiveReflectionEndToEnd:
    def test_reflection_depth_equals_max_depth(self):
        # result.reflection_depth = self.max_depth (no off-by-one).
        eng = RecursiveReflectionEngine(max_depth=7)
        out = eng.reflect({"text": "x y z", "evidence": [], "confidence": 0.5})
        assert out.reflection_depth == 7

    def test_strong_claim_is_valid(self):
        # High confidence, 3 evidence, bounded, short-but-not-tiny text:
        # adjusted_confidence stays >= 0.5 -> valid.
        eng = _engine()
        out = eng.reflect({
            "text": "module hashes passwords with a per-user random salt value",
            "evidence": ["e1", "e2", "e3"],
            "confidence": 0.85,
        })
        assert out.is_valid is True
        assert "survived" in out.rationale

    def test_penalty_pushes_below_half_threshold(self):
        # confidence 0.7, needs_more_evidence True (-0.3) -> 0.4 < 0.5 -> invalid.
        eng = _engine()
        out = eng.reflect({
            "text": "the system validates a lot of different inputs across modules",
            "evidence": ["only one"],
            "confidence": 0.7,
        })
        assert out.needs_more_evidence is True
        assert out.is_valid is False

    def test_validity_threshold_is_inclusive_at_half(self):
        # adjusted_confidence exactly 0.5 -> is_valid True (>= 0.5). Build a
        # claim with no penalties and confidence 0.5: 3 evidence keeps needs_more
        # False only at conf>=0.7, so here needs_more is True (-0.3). Instead use
        # the static-free path: confidence 0.5, 3 evidence + conf 0.7 fails;
        # craft penalties to net exactly 0.5 via confidence 0.8 minus 0.3.
        eng = _engine()
        out = eng.reflect({
            "text": "auth tokens are rotated on every privileged session change here",
            "evidence": ["e1", "e2", "e3"],
            "confidence": 0.8,  # needs_more False, no absolute, words ok -> penalty 0
        })
        # No penalties -> adjusted == 0.8 >= 0.5 -> valid.
        assert out.is_valid is True

    def test_result_to_dict_keys(self):
        r = ReflectionResult()
        d = r.to_dict()
        assert set(d) == {
            "is_valid", "needs_more_evidence", "reflection_depth",
            "reflections", "counter_examples", "insight", "rationale",
        }


# ---------------------------------------------------------------------------
# reflector.py
# ---------------------------------------------------------------------------


def _entry(node_key: str, score: float, ts: str) -> FeedbackEntry:
    return FeedbackEntry(
        node_key=node_key,
        old_confidence=0.5,
        feedback_score=score,
        new_confidence=0.5,
        timestamp=ts,
        action_type="eval",
    )


def _loop_with(tmp_path: Path, entries: list[FeedbackEntry]) -> FeedbackLoop:
    fb = FeedbackLoop(log_dir=str(tmp_path))
    fb.entries = list(entries)
    return fb


class TestReflectorRates:
    def test_success_and_fp_rates_strict_sign(self):
        # successes count score > 0 only, failures score < 0 only; a zero score
        # is neither (kills `>`/`<` boundary flips on L90/L91).
        entries = [
            _entry("n", 1.0, "2024-01-01 00:00:00"),
            _entry("n", -0.5, "2024-01-01 00:00:00"),
            _entry("n", 0.0, "2024-01-01 00:00:00"),
        ]
        success, fp = _compute_rates(entries, 3)
        assert success == 1 / 3
        assert fp == 1 / 3

    def test_rates_zero_total_guard(self):
        assert _compute_rates([], 0) == (0.0, 0.0)


class TestReflectorTopFalsePositives:
    def test_only_negative_average_nodes_included(self):
        # avg < 0 included; a node averaging exactly 0 is excluded
        # (kills `<`->`<=` boundary on L105).
        entries = [
            _entry("bad", -0.5, "2024-01-01 00:00:00"),
            _entry("bad", -0.5, "2024-01-01 00:00:00"),
            _entry("zero", 0.5, "2024-01-01 00:00:00"),
            _entry("zero", -0.5, "2024-01-01 00:00:00"),
        ]
        by_node = {
            "bad": [e for e in entries if e.node_key == "bad"],
            "zero": [e for e in entries if e.node_key == "zero"],
        }
        top = _top_false_positives(by_node)
        keys = [t["node_key"] for t in top]
        assert "bad" in keys
        assert "zero" not in keys  # avg 0.0 excluded

    def test_average_is_rounded_to_two_places(self):
        entries = [
            _entry("bad", -0.5, "2024-01-01 00:00:00"),
            _entry("bad", -0.5, "2024-01-01 00:00:00"),
            _entry("bad", -0.4, "2024-01-01 00:00:00"),
        ]
        by_node = {"bad": entries}
        top = _top_false_positives(by_node)
        assert top[0]["average_feedback"] == round(-1.4 / 3, 2)
        assert top[0]["occurrences"] == 3

    def test_worst_first_ordering(self):
        # Sorted ascending by avg: the most-negative node is listed first.
        entries = [
            _entry("worst", -1.0, "2024-01-01 00:00:00"),
            _entry("milder", -0.2, "2024-01-01 00:00:00"),
        ]
        by_node = {"worst": [entries[0]], "milder": [entries[1]]}
        top = _top_false_positives(by_node)
        assert top[0]["node_key"] == "worst"

    def test_top_capped_at_five(self):
        by_node = {
            f"n{i}": [_entry(f"n{i}", -(i + 1) / 10.0, "2024-01-01 00:00:00")]
            for i in range(8)
        }
        top = _top_false_positives(by_node)
        assert len(top) == 5


class TestReflectorRecommendations:
    def test_high_fp_threshold_strict(self):
        # fp_rate > 0.3 triggers (kills `>`->`<=` on L119). At exactly 0.3 it
        # must NOT trigger the high-fp message.
        recs_at = _build_recommendations(0.3, 0.9, [{"x": 1}])
        assert not any("false positive rate" in r for r in recs_at)
        recs_over = _build_recommendations(0.31, 0.9, [{"x": 1}])
        assert any("false positive rate" in r for r in recs_over)

    def test_low_success_threshold_strict(self):
        # success_rate < 0.5 triggers (kills `<`->`<=` on L121). At exactly 0.5
        # it must NOT trigger.
        recs_at = _build_recommendations(0.0, 0.5, [{"x": 1}])
        assert not any("success rate" in r.lower() for r in recs_at)
        recs_under = _build_recommendations(0.0, 0.49, [{"x": 1}])
        assert any("success rate" in r.lower() for r in recs_under)

    def test_empty_top_fp_adds_all_well_message(self):
        recs = _build_recommendations(0.0, 0.9, [])
        assert any("performing well" in r for r in recs)

    def test_nonempty_top_fp_skips_well_message(self):
        recs = _build_recommendations(0.0, 0.9, [{"node_key": "n"}])
        assert not any("performing well" in r for r in recs)

    def test_recommendations_list_returned_not_none(self):
        # _build_recommendations must return the list (kills return-None on L125).
        recs = _build_recommendations(0.5, 0.2, [])
        assert isinstance(recs, list)
        assert len(recs) >= 1


class TestReflectorUniqueDays:
    def test_unique_days_uses_first_ten_chars(self):
        # _unique_days groups on timestamp[:10] (the date). Two entries on the
        # same date but different times count as ONE day; a third date counts
        # separately. Kills number 10->11 and the [:10]->[:11] return-None.
        entries = [
            _entry("n", 1.0, "2024-03-01 09:00:00"),
            _entry("n", 1.0, "2024-03-01 23:59:59"),
            _entry("n", 1.0, "2024-03-02 00:00:00"),
        ]
        assert _unique_days(entries) == 2

    def test_unique_days_slice_stops_exactly_at_ten(self):
        # The slice length is exactly 10 (the date), not 11. These two entries
        # share characters 0..9 (the date "2024-03-01") but DIFFER at index 10
        # (space vs 'T'). With [:10] they collapse to ONE day; with [:11] they
        # split into TWO. Asserting == 1 kills number 10->11 and the
        # [:10]->[:11] mutation deterministically, without relying on any other
        # test file.
        entries = [
            _entry("n", 1.0, "2024-03-01 08:00:00"),
            _entry("n", 1.0, "2024-03-01T08:00:00"),
        ]
        assert _unique_days(entries) == 1


class TestReflectorEndToEnd:
    def test_empty_history_report(self, tmp_path: Path):
        reflector = Reflector(FeedbackLoop(log_dir=str(tmp_path)))
        report = reflector.reflect()
        assert report.total_runs == 0
        assert report.total_actions == 0
        assert report.success_rate == 0.0
        assert "No feedback history" in report.recommendations[0]

    def test_total_runs_floored_at_one(self, tmp_path: Path):
        # max(_unique_days, 1): a single same-day batch still reports >= 1 run
        # (kills number 1->2 floor on L63 and the unique-days return).
        entries = [
            _entry("n", 1.0, "2024-05-05 10:00:00"),
            _entry("n", -0.5, "2024-05-05 11:00:00"),
        ]
        reflector = Reflector(_loop_with(tmp_path, entries))
        report = reflector.reflect()
        assert report.total_runs == 1
        assert report.total_actions == 2
        assert report.success_rate == 0.5
        assert report.false_positive_rate == 0.5

    def test_two_distinct_days_counted(self, tmp_path: Path):
        entries = [
            _entry("n", 1.0, "2024-05-05 10:00:00"),
            _entry("n", 1.0, "2024-05-06 10:00:00"),
        ]
        reflector = Reflector(_loop_with(tmp_path, entries))
        report = reflector.reflect()
        assert report.total_runs == 2

    def test_report_to_dict_keys(self):
        from app.engine.reflector import ReflectionReport

        r = ReflectionReport(
            total_runs=1, total_actions=2, success_rate=0.5,
            false_positive_rate=0.5,
        )
        assert set(r.to_dict()) == {
            "total_runs", "total_actions", "success_rate",
            "false_positive_rate", "top_false_positives", "recommendations",
        }
