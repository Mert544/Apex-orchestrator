"""Learned (historical-outcome) re-ranking of the roadmap.

The roadmap consults :class:`IdeaMemory` so ideas whose dominant operator has
*historically landed* on this codebase get a tiny, bounded ROI nudge upward,
and ideas whose operator keeps getting blocked/rolled back get nudged down.
The nudge re-ranks ties; it never overrides the grounded impact/effort signal.

These tests pin the contract:
  * with memory, an X-idea (operator that lands) ranks above an otherwise-equal
    Y-idea (operator that gets blocked);
  * with NO memory, the roadmap is byte-identical to the un-memory build;
  * below the min-samples guard, memory is ignored;
  * every produced value stays in bounds and the build is deterministic.
"""

from __future__ import annotations

from app.engine.idea_memory import IdeaMemory, _Stat
from app.engine.idea_roadmap import (
    EVOLVE,
    _OUTCOME_MIN_SAMPLES,
    RoadmapSynthesizer,
    _outcome_adjustment,
    _outcome_rates,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _node(**kw) -> IdeaNode:
    # Mirror tests/test_idea_roadmap.py: supply realistic sub-1.0 structural
    # axes so estimate_impact's seed isn't saturated by the model defaults.
    base = dict(id="i", title="t", subject="s", relevance=0.5, novelty=0.5,
                value=0.6, feasibility=0.6, depth=1)
    base.update(kw)
    return IdeaNode(**base)


def _memory(*, op_success: dict[str, tuple[int, int]] | None = None) -> IdeaMemory:
    """Build an IdeaMemory with controlled per-operator landing records.

    ``op_success`` maps operator -> (applied, blocked). The resulting
    ``success_rate`` is applied/(applied+blocked) and ``samples`` is their sum,
    so the test can place a key above/below the min-samples guard precisely.
    """
    mem = IdeaMemory()
    for op, (applied, blocked) in (op_success or {}).items():
        mem.by_operator[op] = _Stat(applied=applied, rolled_back=0, blocked=blocked)
    return mem


def _two_equal_evolve_ideas() -> IdeaTreeReport:
    # Two ideas identical in every grounded signal (same impact + effort -> same
    # ROI) and same phase (EVOLVE), differing ONLY in operator. Without memory
    # they tie on ROI and value; memory is the sole tie-breaker.
    ideas = [
        _node(id="x", branch_path="x.extend", operator="extend",
              subject="app/core.py", value=0.6, feasibility=0.6,
              source_facts=["dependency-hub: app/core.py"]),
        _node(id="y", branch_path="x.generalize", operator="generalize",
              subject="app/core.py", value=0.6, feasibility=0.6,
              source_facts=["dependency-hub: app/core.py"]),
    ]
    return IdeaTreeReport(objective="grow", project_root="/proj", ideas=ideas)


# --- core behaviour: learned re-ranking --------------------------------------

def test_landed_operator_ranks_above_blocked_operator():
    # 'extend' lands (5/5), 'generalize' is blocked (0/5); both >= min samples.
    mem = _memory(op_success={"extend": (5, 0), "generalize": (0, 5)})
    rm = RoadmapSynthesizer().build(_two_equal_evolve_ideas(), memory=mem)
    evolve = next(p for p in rm.phases if p.name == EVOLVE)
    order = [i.branch_path for i in evolve.items]
    # The historically-landing X-idea is sequenced first.
    assert order == ["x.extend", "x.generalize"]
    # The two share grounded ROI exactly — only the learned nudge separated them.
    assert evolve.items[0].roi == evolve.items[1].roi


def test_no_memory_is_byte_identical_noop():
    report = _two_equal_evolve_ideas()
    without = RoadmapSynthesizer().build(report)
    with_none = RoadmapSynthesizer().build(report, memory=None)
    empty = RoadmapSynthesizer().build(report, memory=IdeaMemory())
    # Passing no memory, None, or an empty ledger all yield the same roadmap as
    # the legacy single-arg build — the feature is a true no-op when fresh.
    assert without.to_dict() == with_none.to_dict() == empty.to_dict()


def test_below_min_samples_is_ignored():
    # 'extend' lands but only with (min-1) samples -> guard rejects it; the
    # roadmap must match the no-memory ordering (ties fall back to insertion).
    under = _OUTCOME_MIN_SAMPLES - 1
    mem = _memory(op_success={"extend": (under, 0)})
    report = _two_equal_evolve_ideas()
    learned = RoadmapSynthesizer().build(report, memory=mem)
    baseline = RoadmapSynthesizer().build(report)
    assert learned.to_dict() == baseline.to_dict()


def test_at_min_samples_boundary_takes_effect():
    # Exactly at the threshold the landing record is trusted and re-ranks.
    mem = _memory(op_success={"extend": (_OUTCOME_MIN_SAMPLES, 0),
                              "generalize": (0, _OUTCOME_MIN_SAMPLES)})
    rm = RoadmapSynthesizer().build(_two_equal_evolve_ideas(), memory=mem)
    evolve = next(p for p in rm.phases if p.name == EVOLVE)
    assert [i.branch_path for i in evolve.items] == ["x.extend", "x.generalize"]


# --- adjustment unit / bounds ------------------------------------------------

def test_adjustment_is_bounded_and_signed():
    rates = _outcome_rates(_memory(op_success={
        "extend": (10, 0),     # perfect record -> max positive nudge
        "generalize": (0, 10),  # abysmal record -> max negative nudge
        "neutral": (5, 5),      # 0.5 success -> exactly neutral
    }))
    from app.engine.idea_roadmap import _OUTCOME_MAX_ADJUST
    up = _outcome_adjustment(_node(operator="extend"), rates)
    down = _outcome_adjustment(_node(operator="generalize"), rates)
    flat = _outcome_adjustment(_node(operator="neutral"), rates)
    assert up == _OUTCOME_MAX_ADJUST
    assert down == -_OUTCOME_MAX_ADJUST
    assert flat == 0.0
    # The nudge never leaves the declared band.
    assert -_OUTCOME_MAX_ADJUST <= down <= up <= _OUTCOME_MAX_ADJUST


def test_unknown_operator_yields_zero_adjustment():
    rates = _outcome_rates(_memory(op_success={"extend": (5, 0)}))
    assert _outcome_adjustment(_node(operator="harden"), rates) == 0.0
    # And an empty rate map is always a no-op regardless of operator.
    assert _outcome_adjustment(_node(operator="extend"), {}) == 0.0


def test_root_idea_keys_on_fact_label():
    # A root (operator == "root") looks its dominant key up by its seeding fact
    # label, not the literal "root" operator.
    rates = _outcome_rates(_memory(op_success={"dependency-hub": (5, 0)}))
    root = _node(operator="root", source_facts=["dependency-hub: app/core.py"])
    assert _outcome_adjustment(root, rates) > 0.0


# --- robustness / determinism ------------------------------------------------

def test_corrupt_memory_never_breaks_build():
    class _Broken:
        def summary(self):
            raise RuntimeError("corrupt ledger")

    report = _two_equal_evolve_ideas()
    # A memory whose summary() blows up must degrade to the no-memory roadmap,
    # never propagate the failure.
    learned = RoadmapSynthesizer().build(report, memory=_Broken())  # type: ignore[arg-type]
    baseline = RoadmapSynthesizer().build(report)
    assert learned.to_dict() == baseline.to_dict()


def test_all_outputs_stay_in_bounds_with_memory():
    mem = _memory(op_success={"extend": (9, 1), "generalize": (1, 9)})
    rm = RoadmapSynthesizer().build(_two_equal_evolve_ideas(), memory=mem)
    for ph in rm.phases:
        for i in ph.items:
            assert 0.0 <= i.impact <= 1.0
            assert 0.1 <= i.effort <= 1.0
            assert 0.0 <= i.value <= 1.0
            # Reported ROI stays the grounded impact/effort; the nudge only sorts.
            assert i.roi == round(i.impact / i.effort, 4)


def test_same_memory_and_ideas_are_deterministic():
    mem = _memory(op_success={"extend": (7, 1), "generalize": (1, 7)})
    report = _two_equal_evolve_ideas()
    first = RoadmapSynthesizer().build(report, memory=mem)
    second = RoadmapSynthesizer().build(report, memory=mem)
    # Two runs over identical inputs produce an identical roadmap.
    assert first.to_dict() == second.to_dict()
