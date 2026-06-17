"""Deep mutation-hardening for ``app/engine/idea_permutation.py``.

The default ``apex mutants --max-mutants 30`` cap stops scoring after the first
30 mutation sites in (line, col) document order, so a 1435-line module hides the
vast majority of its mutants past that cap. Enumerating the FULL mutant universe
(486 sites) surfaced ~106 survivors the existing suite never constrains — most
of them on pure scoring/synthesis helpers far below line 100.

Each test below pins the EXACT behaviour one (or a family) of those deep
survivors would break: a scoring-weight constant, a magnitude saturation, a
convergence-step table cell, a value-blend coefficient, a boundary comparison,
or a string-split index. They are deterministic and hermetic — a ``tmp_path``
root, constructed ``IdeaNode`` inputs, an empty ``RelevanceScorer`` (constant
relevance 1.0), and no network/wall-clock/randomness.

Companion to ``test_idea_permutation_mutation_hardening_eyml.py`` (which targets
the first-30 construction-time blind spots) and the HEAD/digest snapshot suites
(which catch whole-tree behavioural drift). These fill the gap those leave on the
deep pure helpers.
"""

from pathlib import Path

import pytest

from app.engine.idea_permutation import (
    IdeaPermutationEngine,
    _CONVERGENCE_STEPS,
    _MAGNITUDE_CAP,
    _PairState,
    _caveat_hint,
    _compose_title,
    _context_weight,
    _join_phrase,
    _magnitude_bonus,
    _partition_for_render,
    _render_md_header,
    convergence_labels,
    convergence_plan,
    render_markdown,
    render_mermaid,
)
from app.memory.graph_store import GraphStore
from app.models.idea import IdeaNode, IdeaTreeReport
from app.skills.relevance_scorer import RelevanceScorer
from app.tools.project_profile import ProjectProfile


def _node(**kw) -> IdeaNode:
    """A minimal IdeaNode with permutation-y defaults, overridable per test."""
    base = dict(id="x", title="T", subject="m.py", operator="harden",
                operator_chain=["harden"], depth=1, feasibility=0.5,
                relevance=1.0, kind="permutation")
    base.update(kw)
    return IdeaNode(**base)


def _scored_engine(tmp_path: Path, *, has_objective: bool = False) -> IdeaPermutationEngine:
    """An engine wired just enough to call ``_score``/``_novelty`` directly:
    no learning memory, fresh per-run novelty counters."""
    eng = IdeaPermutationEngine({}, tmp_path)
    eng._has_objective = has_objective
    eng._memory = None
    eng._chain_counts = {}
    eng._subject_counts = {}
    return eng


# --- _scan_security_pressure formula (line 157) -----------------------------
# return round(min(1.3, 1.0 + 0.06 * n), 4)


def test_security_pressure_grows_per_finding(tmp_path, monkeypatch):
    # 5 findings -> 1.0 + 0.06*5 = 1.3 exactly (also the cap). A `0.06->1.06`,
    # `1.0->2.0`, `*->/`, or `1.3->2.3` mutant all change this value.
    eng = IdeaPermutationEngine({"security_aware": True}, tmp_path)

    class _FakeAgent:
        def run(self, project_root):
            return {"findings_count": 3}

    import app.agents.skills as skills_mod
    monkeypatch.setattr(skills_mod, "SecurityAgent", lambda: _FakeAgent())
    # 3 findings -> 1.0 + 0.06*3 = 1.18, below the 1.3 cap.
    assert eng._scan_security_pressure() == pytest.approx(1.18)


def test_security_pressure_caps_at_1_3(tmp_path, monkeypatch):
    # 100 findings would be 7.0 unclamped; the min(1.3, ...) holds it at 1.3.
    # A `1.3->2.3` mutant lifts the cap and lets it climb.
    eng = IdeaPermutationEngine({"security_aware": True}, tmp_path)

    class _FakeAgent:
        def run(self, project_root):
            return {"findings_count": 100}

    import app.agents.skills as skills_mod
    monkeypatch.setattr(skills_mod, "SecurityAgent", lambda: _FakeAgent())
    assert eng._scan_security_pressure() == 1.3


def test_security_pressure_zero_findings_is_neutral(tmp_path, monkeypatch):
    # 0 findings -> exactly 1.0 (no bias). Pins the `1.0` base term.
    eng = IdeaPermutationEngine({"security_aware": True}, tmp_path)

    class _FakeAgent:
        def run(self, project_root):
            return {"findings_count": 0}

    import app.agents.skills as skills_mod
    monkeypatch.setattr(skills_mod, "SecurityAgent", lambda: _FakeAgent())
    assert eng._scan_security_pressure() == 1.0


# --- _facet_share stretch (lines 169, 171) ----------------------------------
# min(0.30, 0.12 * max(1.0, max_level / 2))


def test_facet_share_base_is_twelve_percent(tmp_path):
    # facet_depth 1, no adaptive bonus -> max(1.0, 1/2)=1.0 -> 0.12.
    eng = IdeaPermutationEngine({"fractal_facets": True, "facet_depth": 1}, tmp_path)
    assert eng._facet_share() == pytest.approx(0.12)


def test_facet_share_stretches_then_caps_at_thirty_percent(tmp_path):
    # facet_depth 6 -> 0.12*max(1.0, 6/2)=0.36, clamped to the 0.30 ceiling.
    # A `0.30->1.30` mutant removes the cap; a `2->3` mutant in `/ 2` changes
    # the stretch; a `0.12->1.12` mutant inflates the base.
    eng = IdeaPermutationEngine({"fractal_facets": True, "facet_depth": 6}, tmp_path)
    assert eng._facet_share() == 0.30


def test_facet_share_adaptive_bonus_counts_toward_level(tmp_path):
    # facet_depth 1 + adaptive bonus 2 -> max_level 3 -> 0.12*max(1.0,3/2)=0.18.
    # Pins line 169 (`bonus = adaptive_depth_bonus if adaptive_depth else 0`).
    eng = IdeaPermutationEngine(
        {"fractal_facets": True, "facet_depth": 1, "adaptive_depth": True}, tmp_path
    )
    assert eng._facet_share() == pytest.approx(0.18)


# --- _context_weight security boost (lines 1207-1222) -----------------------


def test_context_weight_harden_boost_on_security_label():
    # A security-relevant subject upweights harden/test to 1.1 at neutral
    # pressure; a `1.1->2.1` mutant or label-set change breaks this.
    n = _node(source_facts=["untested: foo"])
    assert _context_weight(n, "harden", 1.0) == pytest.approx(1.1)
    assert _context_weight(n, "test", 1.0) == pytest.approx(1.1)


def test_context_weight_harden_boost_caps_at_1_3():
    # 1.1 * 1.3 pressure = 1.43, clamped to the 1.3 ceiling.
    n = _node(source_facts=["untested: foo"])
    assert _context_weight(n, "harden", 1.3) == 1.3


def test_context_weight_downweights_integrate_on_security_label():
    n = _node(source_facts=["untested: foo"])
    assert _context_weight(n, "integrate", 1.0) == pytest.approx(0.9)
    assert _context_weight(n, "generalize", 1.0) == pytest.approx(0.9)


def test_context_weight_neutral_for_non_security_label():
    # A non-security label leaves every lens at 1.0 (no reweighting).
    n = _node(source_facts=["cosmetic: foo"])
    assert _context_weight(n, "harden", 1.0) == 1.0
    assert _context_weight(n, "integrate", 1.0) == 1.0


# --- _novelty decay and floor (lines 1006-1007) -----------------------------


def test_novelty_root_is_one(tmp_path):
    eng = _scored_engine(tmp_path)
    assert eng._novelty(_node(operator="root")) == 1.0


def test_novelty_decays_with_depth(tmp_path):
    # nov = 1 - 0.15*depth - 0.10*seen - 0.04*subj_seen; first sight of a
    # depth-1 chain -> 1 - 0.15 = 0.85. Pins the depth coefficient.
    eng = _scored_engine(tmp_path)
    assert eng._novelty(_node(depth=1)) == pytest.approx(0.85)


def test_novelty_chain_repetition_penalty(tmp_path):
    # A lens chain already seen twice this run costs 0.10 per repeat:
    # 1 - 0.15*1 - 0.10*2 = 0.65. Pins the 0.10 chain-repeat coefficient.
    eng = _scored_engine(tmp_path)
    eng._chain_counts = {"harden": 2}
    assert eng._novelty(_node(depth=1)) == pytest.approx(0.65)


def test_novelty_subject_diversity_penalty(tmp_path):
    # Piling ideas on one subject costs 0.04 per prior idea on it:
    # 1 - 0.15*1 - 0.04*2 = 0.77. Pins the 0.04 subject-diversity coefficient
    # (a `0.04->1.04` or `4->5` mutant moves this), away from the 0.2 floor.
    eng = _scored_engine(tmp_path)
    eng._subject_counts = {"m.py": 2}
    assert eng._novelty(_node(depth=1)) == pytest.approx(0.77)


def test_novelty_floors_at_0_2(tmp_path):
    # A deep, heavily-repeated chain on an over-mined subject would go negative
    # without the max(0.2, ...) floor. A `0.2->1.2` mutant lifts the floor.
    eng = _scored_engine(tmp_path)
    eng._chain_counts = {"harden>test>harden>test": 10}
    eng._subject_counts = {"m.py": 30}
    n = _node(operator_chain=["harden", "test", "harden", "test"], depth=8)
    assert eng._novelty(n) == 0.2


# --- _score_value blend coefficients (lines 1043-1049) ----------------------


def test_score_value_no_objective_blend(tmp_path):
    # No objective: value = 0.2*rel + 0.4*nov + 0.4*feas.
    # rel=1.0, nov=0.85 (depth 1, fresh), feas=0.5 -> 0.2+0.34+0.2 = 0.74.
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(depth=1, feasibility=0.5)
    eng._score(n, RelevanceScorer(""))
    assert n.value == pytest.approx(0.74)


def test_score_value_no_objective_coefficients_are_distinct(tmp_path):
    # Call _score_value directly with DISTINCT pre-set signals so each blend
    # coefficient (0.2*rel + 0.4*nov + 0.4*feas) is independently pinned — the
    # default scoring path forces relevance to 1.0, which would mask a `*`->`/`
    # mutant on the relevance term (0.2*1 == 0.2/1).
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(relevance=0.5, novelty=0.85, feasibility=0.25)
    # 0.2*0.5 + 0.4*0.85 + 0.4*0.25 = 0.10 + 0.34 + 0.10 = 0.54
    assert eng._score_value(n) == pytest.approx(0.54)


def test_score_value_with_objective_blend(tmp_path):
    # With an objective: value = 0.4*rel + 0.3*nov + 0.3*feas.
    # 0.4 + 0.3*0.85 + 0.3*0.5 = 0.805.
    eng = _scored_engine(tmp_path, has_objective=True)
    n = _node(depth=1, feasibility=0.5)
    eng._score(n, RelevanceScorer(""))
    assert n.value == pytest.approx(0.805)


# --- root feasibility fallback (lines 1024-1025) ----------------------------


def test_root_with_zero_feasibility_falls_back_to_0_7(tmp_path):
    # `if node.operator == "root": node.feasibility = node.feasibility or 0.7`.
    # A root whose feasibility is 0 (falsy) inherits the 0.7 default. The `==`
    # comparison and the `0.7` literal are both load-bearing here.
    eng = _scored_engine(tmp_path)
    n = _node(operator="root", operator_chain=[], depth=0, feasibility=0.0,
              source_facts=["untested: x"])
    eng._score_signals(n, RelevanceScorer(""))
    assert n.feasibility == 0.7


def test_nonroot_with_zero_feasibility_is_not_defaulted(tmp_path):
    # The fallback is gated on operator == "root"; a non-root keeps its 0.0. This
    # pins the `==` operator so a `!=` mutant (defaulting non-roots) is caught.
    eng = _scored_engine(tmp_path)
    n = _node(operator="harden", operator_chain=["harden"], depth=1,
              feasibility=0.0, source_facts=["untested: x"])
    eng._score_signals(n, RelevanceScorer(""))
    assert n.feasibility == 0.0


# --- learning feasibility nudge (lines 1031-1032) ---------------------------


class _FixedFactorMemory:
    """A stub IdeaMemory that returns one fixed feasibility factor."""

    def __init__(self, factor: float) -> None:
        self._factor = factor

    def feasibility_factor(self, operator: str, label: str = "") -> float:
        return self._factor


def test_learning_factor_below_one_lowers_feasibility(tmp_path):
    # A 0.5 factor multiplies feasibility (0.8 -> 0.4). The `factor != 1.0` guard
    # must FIRE here; a `== 1.0` mutant would skip the nudge entirely.
    eng = _scored_engine(tmp_path)
    eng._memory = _FixedFactorMemory(0.5)
    n = _node(operator="harden", depth=1, feasibility=0.8, source_facts=["untested: x"])
    eng._score_signals(n, RelevanceScorer(""))
    assert n.feasibility == 0.4


def test_learning_factor_of_one_leaves_feasibility_untouched(tmp_path):
    # factor == 1.0 is a no-op; pins the guard's neutral case.
    eng = _scored_engine(tmp_path)
    eng._memory = _FixedFactorMemory(1.0)
    n = _node(operator="harden", depth=1, feasibility=0.8, source_facts=["untested: x"])
    eng._score_signals(n, RelevanceScorer(""))
    assert n.feasibility == 0.8


def test_learning_factor_clamps_feasibility_at_one(tmp_path):
    # A 2.0 factor would push 0.8 -> 1.6; the min(1.0, ...) holds it at 1.0. A
    # `1.0->2.0` mutant in that clamp lets it overshoot.
    eng = _scored_engine(tmp_path)
    eng._memory = _FixedFactorMemory(2.0)
    n = _node(operator="harden", depth=1, feasibility=0.8, source_facts=["untested: x"])
    eng._score_signals(n, RelevanceScorer(""))
    assert n.feasibility == 1.0


# --- convergence value bonus (lines 1056-1057) ------------------------------


def test_score_value_convergence_bonus_scales_with_signal_count(tmp_path):
    # 3 converging labels add 0.08*(3-1)=0.16 over the base blend. A `>=2`
    # boundary mutant, a `0.08->1.08`, or a `(len-1)` -> `(len)` mutant all move
    # this. Base (no-objective, depth 1, feas 0.5) = 0.74 -> 0.90.
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(operator="synthesis", kind="synthesis",
              source_facts=["convergence: untested+fragile+security-sensitive"])
    eng._score(n, RelevanceScorer(""))
    assert n.value == pytest.approx(0.90)


def test_score_value_single_convergence_label_gets_no_bonus(tmp_path):
    # Exactly one label is below the `>= 2` threshold -> no bonus. This pins the
    # boundary so `>= 2` can't drift to `>= 1`.
    eng = _scored_engine(tmp_path, has_objective=False)
    one = _node(operator="synthesis", kind="synthesis",
                source_facts=["convergence: untested"])
    eng._score(one, RelevanceScorer(""))
    assert one.value == pytest.approx(0.74)


def test_score_value_two_convergence_labels_just_clear_the_threshold(tmp_path):
    # Exactly TWO labels is the boundary value: bonus 0.08*(2-1)=0.08. A
    # `len(conv) >= 2` -> `> 2` mutant would deny this node its bonus, so the
    # base 0.74 must lift to 0.82.
    eng = _scored_engine(tmp_path, has_objective=False)
    two = _node(operator="synthesis", kind="synthesis",
                source_facts=["convergence: untested+fragile"])
    eng._score(two, RelevanceScorer(""))
    assert two.value == pytest.approx(0.82)


def test_score_value_convergence_bonus_clamps_at_one(tmp_path):
    # A maxed-out node (root-like blend == 1.0) plus a 5-label convergence bonus
    # (0.08*4 = 0.32) would reach 1.32 without the min(1.0, ...) clamp; a
    # `1.0->2.0` clamp mutant lets it exceed 1.0.
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(operator="synthesis", kind="synthesis", depth=0, feasibility=1.0,
              relevance=1.0, source_facts=["convergence: a+b+c+d+e"])
    eng._score(n, RelevanceScorer(""))
    assert n.value == 1.0


# --- facet evidence bonus (lines 1061-1062) ---------------------------------


def test_score_value_facet_evidence_bonus(tmp_path):
    # A facet with a verified evidence fact gets a flat +0.08 over a sibling
    # hypothesis. Pins both the +0.08 and the `kind == "facet"` guard.
    eng = _scored_engine(tmp_path, has_objective=False)
    hyp = _node(kind="facet", source_facts=["facet: input validation"])
    eng._score(hyp, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    ver = _node(kind="facet",
                source_facts=["facet: input validation", "evidence: m.py:3 — eval"])
    eng._score(ver, RelevanceScorer(""))
    assert ver.value - hyp.value == pytest.approx(0.08)


def test_score_value_facet_evidence_bonus_clamps_at_one(tmp_path):
    # A facet whose blend already maxes at 1.0 plus the +0.08 evidence bonus
    # would reach 1.08 without the min(1.0, ...) clamp.
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(kind="facet", depth=0, feasibility=1.0, relevance=1.0,
              source_facts=["facet: x", "evidence: m.py:1 — eval"])
    eng._score(n, RelevanceScorer(""))
    assert n.value == 1.0


def test_score_value_magnitude_bonus_clamps_at_one(tmp_path):
    # A root with a maxed blend (1.0) plus a saturated magnitude bonus would
    # reach 1.08; the min(1.0, ...) on the magnitude branch holds it at 1.0.
    eng = _scored_engine(tmp_path, has_objective=False)
    n = _node(operator="root", operator_chain=[], depth=0, feasibility=1.0,
              relevance=1.0, source_facts=["churn-hotspot: 999 commits"])
    eng._score(n, RelevanceScorer(""))
    assert n.value == 1.0


# --- _magnitude_bonus saturations (lines 1141-1158) -------------------------


def test_magnitude_bonus_months_saturation_is_sixteen():
    # 16 months earns the full _MAGNITUDE_CAP; 8 months earns exactly half.
    # A `16.0->17.0` mutant changes the half value.
    half = _magnitude_bonus(_node(operator="root", source_facts=["finding: ~8 months stale"]))
    assert half == pytest.approx(_MAGNITUDE_CAP * 0.5)
    full = _magnitude_bonus(_node(operator="root", source_facts=["finding: ~16 months stale"]))
    assert full == pytest.approx(_MAGNITUDE_CAP)


def test_magnitude_bonus_commits_saturation_is_fifty():
    # 25 commits -> half the cap; 50 commits -> full. Pins the 50.0 saturation.
    half = _magnitude_bonus(_node(operator="root", source_facts=["churn-hotspot: 25 commits"]))
    assert half == pytest.approx(_MAGNITUDE_CAP * 0.5)


def test_magnitude_bonus_caps_at_one_times_cap():
    # Far past saturation, the min(1.0, ...) holds the bonus at the cap; a
    # `1.0->2.0` mutant in that min would let it overshoot.
    huge = _magnitude_bonus(_node(operator="root", source_facts=["churn-hotspot: 999 commits"]))
    assert huge == pytest.approx(_MAGNITUDE_CAP)


def test_magnitude_bonus_complexity_saturation_is_twentyfour():
    # complexity 12 -> half the cap (saturation 24).
    half = _magnitude_bonus(_node(operator="root", source_facts=["hotspot: complexity 12"]))
    assert half == pytest.approx(_MAGNITUDE_CAP * 0.5)


def test_magnitude_bonus_absent_quantity_is_zero():
    assert _magnitude_bonus(_node(operator="root", source_facts=["plain: nothing measured"])) == 0.0


# --- _CONVERGENCE_STEPS table + convergence_plan (lines 1245-1287) ----------


def test_convergence_step_ranks_order_stabilize_before_secure_before_evolve():
    # The phase ranks encode Stabilize(1) -> Secure(2) -> Evolve(3) -> Refine(4).
    # A `1->2`/`3->4` mutant on ANY rank cell would reorder the plan, so pin the
    # FULL rank column (every Stabilize cell is 1, etc.).
    assert _CONVERGENCE_STEPS["critically untested"][0] == 1
    assert _CONVERGENCE_STEPS["untested"][0] == 1
    assert _CONVERGENCE_STEPS["only shallowly tested"][0] == 1
    assert _CONVERGENCE_STEPS["fragile"][0] == 1
    assert _CONVERGENCE_STEPS["a complexity hotspot"][0] == 1
    assert _CONVERGENCE_STEPS["security-sensitive"][0] == 2
    assert _CONVERGENCE_STEPS["a central dependency hub"][0] == 3
    assert _CONVERGENCE_STEPS["accelerating"][0] == 3
    assert _CONVERGENCE_STEPS["high-churn"][0] == 3
    assert _CONVERGENCE_STEPS["debt-laden"][0] == 4


def test_convergence_step_phase_labels_match_their_ranks():
    # The phase string travels with the rank; pin the (rank, phase) pairing so a
    # rank mutant that slips past the numeric check is still caught by the prose.
    assert _CONVERGENCE_STEPS["untested"][1] == "Stabilize"
    assert _CONVERGENCE_STEPS["only shallowly tested"][1] == "Stabilize"
    assert _CONVERGENCE_STEPS["fragile"][1] == "Stabilize"
    assert _CONVERGENCE_STEPS["a complexity hotspot"][1] == "Stabilize"
    assert _CONVERGENCE_STEPS["security-sensitive"][1] == "Secure"
    assert _CONVERGENCE_STEPS["accelerating"][1] == "Evolve"
    assert _CONVERGENCE_STEPS["high-churn"][1] == "Evolve"
    assert _CONVERGENCE_STEPS["debt-laden"][1] == "Refine"


def test_convergence_step_executable_flags_are_pinned():
    # Test/harden steps are executable; design tasks are not. A True<->False
    # mutant on any of these cells flips the ⚙️/✋ marker downstream.
    assert _CONVERGENCE_STEPS["untested"][4] is True
    assert _CONVERGENCE_STEPS["only shallowly tested"][4] is True
    assert _CONVERGENCE_STEPS["fragile"][4] is True
    assert _CONVERGENCE_STEPS["a complexity hotspot"][4] is True
    assert _CONVERGENCE_STEPS["high-churn"][4] is False
    assert _CONVERGENCE_STEPS["debt-laden"][4] is False


def test_convergence_plan_orders_by_rank_then_phase():
    # A subject that is untested + a hotspot + security-sensitive + churny yields
    # one ordered, deduped roadmap: Stabilize, then Secure, then Evolve. The
    # sort key (rank, phase) at line 1283 pins this exact order.
    plan = convergence_plan(
        ["untested", "a complexity hotspot", "security-sensitive", "high-churn"]
    )
    phases = [step["phase"] for step in plan]
    assert phases == ["Stabilize", "Secure", "Evolve"]


def test_convergence_plan_collapses_shared_test_action():
    # untested and "a complexity hotspot" both map to create_test_stub, so they
    # collapse to a SINGLE Stabilize step (first label wins).
    plan = convergence_plan(["untested", "a complexity hotspot"])
    actions = [step["action_type"] for step in plan]
    assert actions == ["create_test_stub"]
    assert plan[0]["step"] == "Add a first test layer first"


def test_convergence_plan_ignores_unknown_labels():
    assert convergence_plan(["not-a-real-label"]) == []


def test_convergence_labels_splits_on_plus():
    # convergence_labels reads the "convergence: a+b+c" fact and splits on '+'.
    n = _node(operator="synthesis", kind="synthesis",
              source_facts=["convergence: untested+fragile"])
    assert convergence_labels(n) == ["untested", "fragile"]


def test_convergence_labels_absent_fact_is_empty():
    assert convergence_labels(_node(source_facts=["other: x"])) == []


# --- _caveat_claim discriminators (lines 1107-1117) -------------------------


def test_caveat_claim_root_uses_fact_label_and_symbol():
    # A root idea (terminal lens "root") discriminates by its seeding fact label,
    # and a "mod.py::Class.func" subject contributes the bare function name.
    n = _node(id="r", subject="mod.py::Foo.bar", operator="root",
              operator_chain=["root"], source_facts=["untested: thing"],
              kind="permutation")
    claim = IdeaPermutationEngine._caveat_claim(n)
    assert claim["fact_label"] == "untested"
    assert claim["symbol"] == "bar"
    assert "operator" not in claim


def test_caveat_claim_facet_subject_not_mistaken_for_symbol():
    # A facet's "subject :: phrase" also contains "::"; the kind != "facet" guard
    # must keep it out of the symbol slot.
    n = _node(subject="mod.py :: input validation", operator="harden",
              operator_chain=["harden"], kind="facet")
    claim = IdeaPermutationEngine._caveat_claim(n)
    assert "symbol" not in claim


# --- _caveat_hint dispatch (lines 1290-1296) --------------------------------


def test_caveat_hint_uses_operator_for_permutation():
    assert _caveat_hint(_node(operator="harden")) == \
        "guard validation check sanitize secret"


def test_caveat_hint_uses_kind_for_synthesis():
    n = _node(operator="synthesis", kind="synthesis", source_facts=["x: y"])
    assert _caveat_hint(n) == "check validation edge cases security"


# --- _join_phrase / _compose_title (lines 1233-1302) ------------------------


def test_join_phrase_three_items():
    assert _join_phrase(["a", "b", "c"]) == "a, b and c"


def test_join_phrase_single_and_empty():
    assert _join_phrase(["solo"]) == "solo"
    assert _join_phrase([]) == ""


def test_compose_title_capitalizes_and_joins_chain():
    assert _compose_title("mod.py", ["harden", "test"]) == "Harden → Test: mod.py"


# --- _render_md_header (lines 1305-1310) ------------------------------------


def test_render_md_header_without_objective():
    rep = IdeaTreeReport(objective="", project_root="/p", ideas=[],
                         branch_map={}, stats={"total_ideas": 5, "mean_value": 0.42})
    assert _render_md_header(rep) == [
        "# Development Ideas for `/p`", "", "5 ideas · mean value 0.42", ""
    ]


def test_render_md_header_with_objective_prefixes_meta():
    rep = IdeaTreeReport(objective="secure it", project_root="/p", ideas=[],
                         branch_map={}, stats={"total_ideas": 5, "mean_value": 0.42})
    header = _render_md_header(rep)
    assert header[2] == "objective: _secure it_ · 5 ideas · mean value 0.42"


# --- mean_value rounding / empty guard (line 345) ---------------------------


def test_run_mean_value_is_rounded_and_empty_safe(tmp_path):
    # mean_value is round(sum/len, 4) over non-empty, else 0.0. A real two-module
    # project exercises the populated branch; the value is a finite 0..1 mean.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp_path / "app" / "api.py").write_text(
        "import app.main\n\ndef handler():\n    return app.main.main()\n"
    )
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 20, "max_idea_depth": 2, "breadth": 3}, tmp_path
    ).run()
    mv = rep.stats["mean_value"]
    assert 0.0 < mv <= 1.0
    # rounded to 4 dp: equals its own 4-dp rounding (no hidden precision).
    assert mv == round(mv, 4)


# --- security boost actually lifts feasibility end-to-end (line 749) ---------


def test_security_pressure_lifts_harden_feasibility_in_expand(tmp_path, monkeypatch):
    # End-to-end: a security-labelled subject under high security pressure must
    # produce a harden child whose feasibility is boosted above the unpressured
    # baseline, proving the 0.06-per-finding scan feeds the value function.
    eng = IdeaPermutationEngine({"security_aware": True}, tmp_path)

    class _FakeAgent:
        def __init__(self, count):
            self.count = count

        def run(self, project_root):
            return {"findings_count": self.count}

    import app.agents.skills as skills_mod

    parent = _node(id="root0", subject="auth.py", operator="root",
                   operator_chain=[], depth=0, feasibility=0.6,
                   source_facts=["untested: auth.py"])

    monkeypatch.setattr(skills_mod, "SecurityAgent", lambda: _FakeAgent(0))
    eng._security_pressure = eng._scan_security_pressure()
    low = next(c for c in eng._expand(parent) if c.operator == "harden")

    monkeypatch.setattr(skills_mod, "SecurityAgent", lambda: _FakeAgent(5))
    eng._security_pressure = eng._scan_security_pressure()
    high = next(c for c in eng._expand(parent) if c.operator == "harden")

    assert high.feasibility > low.feasibility


# --- _effective_max_depth adaptive gate (lines 730-732) ---------------------


def test_effective_max_depth_extends_for_high_value_when_adaptive(tmp_path):
    # adaptive_depth on + node.value >= threshold -> max_depth + bonus.
    eng = IdeaPermutationEngine(
        {"adaptive_depth": True, "max_idea_depth": 2,
         "adaptive_depth_bonus": 2, "adaptive_depth_threshold": 0.6},
        tmp_path,
    )
    assert eng._effective_max_depth(_node(value=0.7)) == 4
    # AT the threshold value the `>=` includes it -> extended; a `> ` boundary
    # mutant would exclude the boundary value and drop back to base depth.
    assert eng._effective_max_depth(_node(value=0.6)) == 4
    # Below the threshold -> base depth only.
    assert eng._effective_max_depth(_node(value=0.5)) == 2


def test_effective_max_depth_ignores_value_when_not_adaptive(tmp_path):
    # adaptive_depth off -> the `and` short-circuits and depth stays at base
    # regardless of value. An `or` mutant would extend every high-value branch.
    eng = IdeaPermutationEngine(
        {"adaptive_depth": False, "max_idea_depth": 2}, tmp_path
    )
    assert eng._effective_max_depth(_node(value=0.99)) == 2


# --- _select_level_sources adaptive narrowing (lines 854-856) ---------------


def _perm_source(idx: str, value: float) -> IdeaNode:
    return IdeaNode(id=idx, title="T", subject="m.py", value=value,
                    branch_path=f"x.{idx}", operator="harden", kind="permutation")


def test_select_level_sources_base_level_keeps_top_per_level(tmp_path):
    # At a base zoom level (<= facet_depth) the top ``per_level`` sources are
    # kept, value-ordered.
    eng = IdeaPermutationEngine({"facet_depth": 1}, tmp_path)
    hi, lo = _perm_source("a", 0.7), _perm_source("b", 0.5)
    kept = eng._select_level_sources([lo, hi], level=1, per_level=5)
    assert [n.id for n in kept] == ["a", "b"]


def test_select_level_sources_adaptive_level_keeps_only_strongest(tmp_path):
    # A level beyond facet_depth keeps only the single strongest branch, and only
    # while its value clears the adaptive threshold. The `>= threshold` boundary
    # and the `[:1]` narrowing are both pinned here.
    eng = IdeaPermutationEngine(
        {"facet_depth": 1, "adaptive_depth_threshold": 0.6}, tmp_path
    )
    hi, lo = _perm_source("a", 0.7), _perm_source("b", 0.65)
    assert [n.id for n in eng._select_level_sources([lo, hi], 2, 5)] == ["a"]
    # A source AT the threshold value is kept (the `>=` includes it); a `>`
    # boundary mutant would drop it.
    edge = _perm_source("e", 0.6)
    assert [n.id for n in eng._select_level_sources([edge], 2, 5)] == ["e"]
    # A sole weak source (below threshold) yields nothing at the adaptive level.
    weak = _perm_source("c", 0.5)
    assert eng._select_level_sources([weak], 2, 5) == []


# --- _facet_leaves parent exclusion (lines 832-841) -------------------------


def test_facet_leaves_excludes_permutation_parents(tmp_path):
    # A permutation idea that itself spawned a permutation child is NOT a leaf.
    root = IdeaNode(id="r", title="T", operator="root", kind="permutation")
    child = IdeaNode(id="c", title="T", operator="harden", kind="permutation",
                     parent_id="r")  # 'harden' has a facet vocabulary
    leaves_no_grand = IdeaPermutationEngine._facet_leaves([root, child])
    assert [n.id for n in leaves_no_grand] == ["c"]

    grand = IdeaNode(id="g", title="T", operator="harden", kind="permutation",
                     parent_id="c")  # now 'c' is a parent, no longer a leaf
    leaves_with_grand = IdeaPermutationEngine._facet_leaves([root, child, grand])
    assert [n.id for n in leaves_with_grand] == ["g"]


# --- _partition_for_render perm-root selection (lines 1326-1329) ------------


def test_partition_for_render_separates_synth_from_perm_roots():
    # A parentless synthesis idea goes in the flat synth section; a parentless
    # permutation idea is a render root. The `kind == "permutation"` filter and
    # the `id not in synth_ids` exclusion at line 1329 are pinned.
    root = IdeaNode(id="r1", title="T", operator="root", kind="permutation",
                    parent_id=None)
    synth = IdeaNode(id="s1", title="T", operator="synthesis", kind="synthesis",
                     parent_id=None)
    rep = IdeaTreeReport(objective="", project_root="/p", ideas=[root, synth],
                         branch_map={}, stats={})
    _by_parent, synth_out, perm_roots = _partition_for_render(rep)
    assert [n.id for n in perm_roots] == ["r1"]
    assert [n.id for n in synth_out] == ["s1"]


# --- render_markdown anchor focus line (lines 1346-1351) --------------------


def test_render_markdown_anchor_focus_uses_bare_symbol():
    # A root with an anchor renders a "focus" line naming the bare function
    # (rsplit('.', 1)[-1]) with its metric and line. Pins the focus-line render.
    root = IdeaNode(id="r", title="Fix mod", branch_path="x.0", depth=0,
                    operator="root", kind="permutation", value=0.5,
                    source_facts=["untested: mod.py"],
                    anchors=[{"module": "mod.py", "symbol": "pkg.Cls.risky",
                              "line": 42, "metric": "cyclomatic 18"}])
    rep = IdeaTreeReport(objective="", project_root="/p", ideas=[root],
                         branch_map={}, stats={"total_ideas": 1, "mean_value": 0.5})
    md = render_markdown(rep)
    assert "→ focus: `risky` (cyclomatic 18, line 42)" in md


# --- render_mermaid facet zoom label (lines 1419-1423) ----------------------


def test_render_mermaid_facet_node_shows_only_subconcern():
    # A facet node in the mermaid graph shows just its zoom phrase, not the full
    # title. The `kind == "facet" and facet_facts` guard at line 1419 selects it.
    root = IdeaNode(id="r1", title="Harden auth.py", branch_path="x.0",
                    operator="harden", kind="permutation", parent_id=None)
    facet = IdeaNode(id="f", title="Harden auth.py", branch_path="x.0.f0",
                     operator="harden", kind="facet", parent_id="r1",
                     source_facts=["facet: input validation"])
    rep = IdeaTreeReport(objective="", project_root="/p", ideas=[root, facet],
                         branch_map={}, stats={})
    mm = render_mermaid(rep)
    assert "🔍 input validation" in mm
    # The parent->facet edge is drawn (branch dots become underscores).
    assert "x_0 --> x_0_f0" in mm


def test_render_mermaid_nonfacet_with_facet_fact_keeps_its_title():
    # The label guard is `kind == "facet" AND facet_facts`: a PERMUTATION node
    # that happens to carry a "facet:" fact must still render its full title, not
    # the zoom phrase. An `or` mutant would mislabel it with the phrase.
    n = IdeaNode(id="r", title="Real Title", branch_path="x.0", operator="harden",
                 kind="permutation", parent_id=None, source_facts=["facet: sneaky"])
    rep = IdeaTreeReport(objective="", project_root="/p", ideas=[n],
                         branch_map={}, stats={})
    mm = render_mermaid(rep)
    assert "Real Title" in mm
    assert "sneaky" not in mm


# --- _attach_caveats facet lead reorder (lines 1082-1093) -------------------


def test_facet_caveat_leads_with_subconcern_stress_test(tmp_path):
    # A facet's own sub-concern stress-test must LEAD its caveats (the lens caveat
    # follows). The `kind == "facet" and source_facts` guard at line 1082 gates
    # this reorder; a non-facet keeps the plain lens caveats.
    eng = _scored_engine(tmp_path)
    facet = _node(kind="facet", operator="harden", operator_chain=["harden"],
                  source_facts=["facet: error handling"])
    eng._attach_caveats(facet)
    # The facet leads with its own sub-concern stress-test.
    assert facet.caveats
    assert facet.caveats[0] == eng._facet_caveat("error handling")

    # The guard is `kind == "facet" AND source_facts`: a PERMUTATION node that
    # carries a "facet:" fact must NOT be reordered (its lens caveat keeps the
    # lead). An `or` mutant would reorder it to the facet-specific caveat.
    perm = _node(kind="permutation", operator="harden", operator_chain=["harden"],
                 source_facts=["facet: error handling"])
    eng._attach_caveats(perm)
    assert perm.caveats
    assert perm.caveats[0] != eng._facet_caveat("error handling")


# --- _edge_ideas skips pairs fully inside a cycle (line 705) ----------------


def _synth_engine(tmp_path: Path) -> IdeaPermutationEngine:
    eng = IdeaPermutationEngine({}, tmp_path)
    eng._chain_counts = {}
    eng._subject_counts = {}
    eng._has_objective = False
    eng._security_pressure = 1.0
    eng._memory = None
    return eng


# --- _thematic_ideas thresholds + shown formatting (lines 386-430) ----------


def _theme_engine(tmp_path: Path) -> IdeaPermutationEngine:
    eng = _synth_engine(tmp_path)
    eng._accelerating = {}
    return eng


def test_thematic_security_theme_threshold_is_three(tmp_path):
    # The security-finding theme needs >= 3 modules (len < threshold skips). Pins
    # both the per-theme threshold cell (3) and the `< threshold` guard.
    eng = _theme_engine(tmp_path)
    rel, graph = RelevanceScorer(""), GraphStore()
    three = ProjectProfile(root=str(tmp_path),
                           security_finding_modules=["a.py", "b.py", "c.py"])
    out3 = eng._thematic_ideas(three, rel, graph)
    assert len(out3) == 1
    assert out3[0].title.startswith("Run a security-hardening pass across 3 modules")
    assert out3[0].feasibility == 0.6  # pins the synthesized-theme feasibility

    eng2 = _theme_engine(tmp_path)
    two = ProjectProfile(root=str(tmp_path),
                         security_finding_modules=["a.py", "b.py"])
    assert eng2._thematic_ideas(two, RelevanceScorer(""), GraphStore()) == []


def test_thematic_coverage_theme_threshold_is_four(tmp_path):
    # The untested-coverage theme needs >= 4 modules (a higher bar than the
    # other themes). 3 is below; 4 fires. Pins the lone `4` threshold cell.
    eng = _theme_engine(tmp_path)
    three = ProjectProfile(root=str(tmp_path),
                           untested_modules=["a.py", "b.py", "c.py"])
    assert eng._thematic_ideas(three, RelevanceScorer(""), GraphStore()) == []

    eng2 = _theme_engine(tmp_path)
    four = ProjectProfile(root=str(tmp_path),
                          untested_modules=["a.py", "b.py", "c.py", "d.py"])
    out = eng2._thematic_ideas(four, RelevanceScorer(""), GraphStore())
    assert len(out) == 1
    assert out[0].title.startswith("Establish baseline test coverage across 4 modules")


def test_thematic_shown_list_truncates_past_four_modules(tmp_path):
    # More than 4 modules -> first four listed + ", ...". The `> 4` boundary and
    # the `[:4]` slice both shape this string.
    eng = _theme_engine(tmp_path)
    five = ProjectProfile(
        root=str(tmp_path),
        security_finding_modules=["a.py", "b.py", "c.py", "d.py", "e.py"],
    )
    out = eng._thematic_ideas(five, RelevanceScorer(""), GraphStore())
    assert out[0].title == \
        "Run a security-hardening pass across 5 modules (a.py, b.py, c.py, d.py, ...)"

    eng2 = _theme_engine(tmp_path)
    exactly_four = ProjectProfile(
        root=str(tmp_path),
        security_finding_modules=["a.py", "b.py", "c.py", "d.py"],
    )
    out4 = eng2._thematic_ideas(exactly_four, RelevanceScorer(""), GraphStore())
    # Exactly four: no ellipsis (the `> 4` boundary excludes equality).
    assert out4[0].title == \
        "Run a security-hardening pass across 4 modules (a.py, b.py, c.py, d.py)"


# --- _cross_lens_ideas subset trigger (line 613) ----------------------------


def test_cross_lens_idea_emitted_when_subject_has_test_and_harden(tmp_path):
    # A subject that received BOTH 'test' and 'harden' lenses (exactly that set)
    # gets a dedicated security-test-suite idea. The guard is a subset test
    # `{"test","harden"} <= lenses`; a `<` (proper-subset) mutant would require a
    # strictly larger lens set and miss the exactly-two case.
    eng = _synth_engine(tmp_path)
    emitted = [
        IdeaNode(id="a", title="T", subject="m.py", operator="harden",
                 operator_chain=["harden"], kind="permutation"),
        IdeaNode(id="b", title="T", subject="m.py", operator="test",
                 operator_chain=["test"], kind="permutation"),
    ]
    out = eng._cross_lens_ideas(emitted, RelevanceScorer(""), GraphStore())
    assert len(out) == 1
    assert out[0].title == "Build a security-focused test suite for m.py"
    assert out[0].operator_chain == ["harden", "test"]


def test_cross_lens_idea_absent_without_both_lenses(tmp_path):
    # Only 'harden' present -> the subset guard fails -> no cross-lens idea.
    eng = _synth_engine(tmp_path)
    emitted = [
        IdeaNode(id="a", title="T", subject="m.py", operator="harden",
                 operator_chain=["harden"], kind="permutation"),
    ]
    assert eng._cross_lens_ideas(emitted, RelevanceScorer(""), GraphStore()) == []


# --- _convergence_ideas (lines 526-540) -------------------------------------


def test_convergence_idea_built_from_multiple_independent_dimensions(tmp_path):
    # A subject flagged by 3 independent risk dimensions produces ONE convergence
    # idea naming all three. Exercises the >= 2 filter and the node builder.
    eng = _synth_engine(tmp_path)
    eng._accelerating = {}
    profile = ProjectProfile(
        root=str(tmp_path),
        sensitive_paths=["x.py"],
        hotspot_modules=["x.py"],
        fragile_modules=["x.py"],
    )
    out = eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore())
    assert len(out) == 1
    assert out[0].subject == "x.py"
    assert "3 independent analyses converge" in out[0].title


def test_convergence_ideas_capped_at_three_subjects(tmp_path):
    # Four subjects each flagged by two dimensions: only the top three survive the
    # `[:3]` cap, ordered deterministically (sorted by -count then name -> a,b,c).
    # A `[:3]->[:4]` mutant would emit a fourth.
    eng = _synth_engine(tmp_path)
    eng._accelerating = {}
    mods = ["a.py", "b.py", "c.py", "d.py"]
    profile = ProjectProfile(root=str(tmp_path),
                             sensitive_paths=list(mods),
                             hotspot_modules=list(mods))
    out = eng._convergence_ideas(profile, RelevanceScorer(""), GraphStore())
    assert [n.subject for n in out] == ["a.py", "b.py", "c.py"]


def test_edge_ideas_skips_pair_when_both_modules_in_cycle(tmp_path):
    # An edge whose BOTH endpoints already sit inside a reported import cycle is
    # NOT re-proposed as a plain interface pair (the cycle idea subsumes it); an
    # edge with only one endpoint in the cycle IS kept. The `and` at line 705
    # pins this — an `or` mutant would also drop the half-in-cycle edge.
    profile = ProjectProfile(
        root=str(tmp_path),
        import_cycles=[["app/a.py", "app/b.py", "app/a.py"]],
        dependency_edges=[("app/a.py", "app/b.py"), ("app/a.py", "app/z.py")],
    )
    eng = _synth_engine(tmp_path)
    graph = GraphStore()
    rel = RelevanceScorer("")
    out: list = []
    state = _PairState()
    in_cycle = eng._cycle_ideas(profile, rel, graph, out, state)
    eng._edge_ideas(profile, rel, graph, out, state, in_cycle)
    titles = [n.title for n in out]
    assert not any("between app/a.py and app/b.py" in t for t in titles)
    assert any("app/z.py" in t for t in titles)
