"""Deep-mutation characterization for ``app/engine/abductive_reasoning.py``.

These tests pin the EXACT arithmetic of the abductive reasoner — the confidence
formula, the per-observation severity weights, the dataclass defaults, and the
empty-clause early return — so that the full mutant universe (enumerated past the
default 30-cap via ``mutation_tester._collect_sites``) is killed, not merely the
fraction the loose ``0.0 < confidence <= 1.0`` assertions in the existing suite
happened to catch.

Each test pins a value to a constant computed by hand from the documented
formula, so a one-token mutation (``+`` -> ``-``, ``/`` -> ``*``, ``n`` -> ``n+1``,
a default flip, or a ``return <expr>`` -> ``return None``) shifts the result and
fails the test. Determinism: every input is fixed; no time, randomness, or set
ordering is asserted.
"""

from __future__ import annotations

from app.engine.abductive_reasoning import (
    AbductionResult,
    AbductiveReasoner,
    explanation_clause,
)

# --------------------------------------------------------------------------- #
# Dataclass default — ``confidence: float = 0.0`` (kills number:0.0>1.0 on L10).
# --------------------------------------------------------------------------- #

def test_abduction_result_default_confidence_is_zero():
    assert AbductionResult().confidence == 0.0
    assert AbductionResult().root_causes == []
    assert AbductionResult().rationale == ""


# --------------------------------------------------------------------------- #
# ``_weight_for`` severity arithmetic — direct pins kill every weight mutant
# (base 1.0, the three ``metric / divisor`` increments, and the 3.0 cap).
# --------------------------------------------------------------------------- #

def test_weight_for_base_is_exactly_one():
    # No severity metrics -> the bare base weight 1.0 (kills weight=1.0->2.0).
    assert AbductiveReasoner._weight_for({}) == 1.0
    assert AbductiveReasoner._weight_for({"function_name": "x"}) == 1.0


def test_weight_for_line_count_increment():
    # 1.0 + line_count/50.0; line_count=50 -> exactly 2.0. A flipped ``+=``/``-=``,
    # a ``/`` -> ``*``, or a 50.0 -> 51.0 all move this off 2.0.
    assert AbductiveReasoner._weight_for({"line_count": 50}) == 2.0


def test_weight_for_arg_count_increment():
    # 1.0 + arg_count/5.0; arg_count=5 -> exactly 2.0.
    assert AbductiveReasoner._weight_for({"arg_count": 5}) == 2.0


def test_weight_for_import_count_increment():
    # 1.0 + import_count/10.0; import_count=10 -> exactly 2.0.
    assert AbductiveReasoner._weight_for({"import_count": 10}) == 2.0


def test_weight_for_caps_at_three():
    # A huge line_count would push the raw weight to 21.0, but min(weight, 3.0)
    # clamps it to exactly 3.0 (kills the cap 3.0 -> 4.0 mutation).
    assert AbductiveReasoner._weight_for({"line_count": 1000}) == 3.0


def test_weight_for_sums_all_three_metrics():
    # 1.0 + 50/50 + 5/5 + 10/10 = 4.0 raw, capped to 3.0.
    assert AbductiveReasoner._weight_for(
        {"line_count": 50, "arg_count": 5, "import_count": 10}
    ) == 3.0


# --------------------------------------------------------------------------- #
# Confidence formula — exact pins over the documented
# ``min(1.0, (matched / max(N, 1)) * 0.7 + min(total_weight * 0.1, 0.3))``,
# rounded to 2 decimals.
# --------------------------------------------------------------------------- #

def test_single_observation_confidence_is_exact():
    # matched=1, N=1: 1/max(1,1)*0.7 + min(1.0*0.1, 0.3) = 0.7 + 0.1 = 0.8.
    # Kills max(...,1)->max(...,2) [first term -> 0.35], the 0.7 multiplier flip,
    # and the weight-base feed (weight 1.0 -> 0.9 if base became 2.0).
    result = AbductiveReasoner().infer([{"type": "long_function"}])
    assert result.confidence == 0.8


def test_isolated_line_count_confidence_is_exact():
    # One mapped obs (line_count=5) padded with 3 unmapped obs: matched=1, N=4.
    # weight = 1 + 5/50 = 1.1; term = min(0.11, 0.3) = 0.11.
    # conf = 1/4*0.7 + 0.11 = 0.175 + 0.11 = 0.285 -> round 0.29.
    obs = [{"type": "long_function", "line_count": 5},
           {"type": "zz1"}, {"type": "zz2"}, {"type": "zz3"}]
    assert AbductiveReasoner().infer(obs).confidence == 0.29


def test_isolated_arg_count_confidence_is_exact():
    # arg_count=3: weight = 1 + 3/5 = 1.6; term = 0.16.
    # conf = 0.175 + 0.16 = 0.335 -> round 0.34.
    obs = [{"type": "long_function", "arg_count": 3},
           {"type": "zz1"}, {"type": "zz2"}, {"type": "zz3"}]
    assert AbductiveReasoner().infer(obs).confidence == 0.34


def test_isolated_import_count_confidence_is_exact():
    # import_count=1: weight = 1 + 1/10 = 1.1; term = 0.11.
    # conf = 0.175 + 0.11 = 0.285 -> round 0.29.
    obs = [{"type": "long_function", "import_count": 1},
           {"type": "zz1"}, {"type": "zz2"}, {"type": "zz3"}]
    assert AbductiveReasoner().infer(obs).confidence == 0.29


def test_inner_weight_cap_is_exactly_three_tenths():
    # Two heavy mapped obs (weight 3.0 each -> total_weight 6.0) + 2 unmapped:
    # matched=2, N=4. inner term = min(6.0*0.1, 0.3) = 0.3 (NOT 0.6).
    # conf = 2/4*0.7 + 0.3 = 0.35 + 0.3 = 0.65. A 0.3 -> 1.3 cap flip would let
    # the term reach 0.6, giving 0.95.
    obs = [{"type": "long_function", "line_count": 1000},
           {"type": "high_import_count", "import_count": 1000},
           {"type": "zz1"}, {"type": "zz2"}]
    assert AbductiveReasoner().infer(obs).confidence == 0.65


def test_confidence_rounds_to_two_decimals():
    # 2 mapped + 1 unmapped: matched=2, N=3. raw = 2/3*0.7 + min(2.0*0.1, 0.3)
    # = 0.46666... + 0.2 = 0.66666... -> round(.,2) = 0.67, NOT round(.,3)=0.667.
    obs = [{"type": "long_function"}, {"type": "deep_nesting"}, {"type": "zz"}]
    result = AbductiveReasoner().infer(obs)
    assert result.confidence == 0.67
    # The third decimal would survive a round(.,3) mutation; pin it away.
    assert result.confidence != 0.667


# --------------------------------------------------------------------------- #
# ``explanation_clause`` empty early return — ``return ""`` (kills "">None).
# --------------------------------------------------------------------------- #

def test_explanation_clause_empty_when_no_root_causes():
    assert explanation_clause(AbductionResult(root_causes=[])) == ""
    # A ``return None`` mutant would make this fail the strict-equality check.
    assert explanation_clause(AbductionResult()) == ""
