"""The action bridge's headline tiebreaker: among near-tie leaders, the subject
backed by the MOST converging confluence signals is surfaced as the #1 action,
matching the dream/confluence lens's family count.

Opt-in (``confluence_first=True``), deterministic, and value-preserving: the
plan's overall value ranking is otherwise untouched and ``ActionStep.value`` is
never mutated.
"""
from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _confluence_weight,
)
from app.models.idea import IdeaTreeReport, IdeaNode


def _confluence_idea(value: float) -> IdeaNode:
    """A 4-signal confluence ROOT — the dream's #1 by family count."""
    return IdeaNode(
        id="conf",
        title="Untangle app/tools/project_profile.py — 4 independent pressures converge",
        subject="app/tools/project_profile.py",
        operator="root",
        kind="permutation",
        source_facts=[
            "confluence: app/tools/project_profile.py (4 signal families "
            "converge: co-change, high-churn, hub, symbol-hub)"
        ],
        value=value,
    )


def _synthesis_idea(value: float) -> IdeaNode:
    """A 2-analysis synthesis idea with a SLIGHTLY HIGHER value."""
    return IdeaNode(
        id="synth",
        title="Combine test + harden on app/engine/idea_permutation.py",
        subject="app/engine/idea_permutation.py",
        operator="synthesis",
        kind="synthesis",
        source_facts=["synthesis: test+harden"],
        value=value,
    )


def _report(*ideas: IdeaNode) -> IdeaTreeReport:
    return IdeaTreeReport(objective="o", project_root="", ideas=list(ideas))


def test_confluence_weight_reads_family_count():
    conf_step = IdeaActionBridge().plan_idea(_confluence_idea(0.80))
    synth_step = IdeaActionBridge().plan_idea(_synthesis_idea(0.81))
    # The 4-signal confluence out-weighs the 2-analysis synthesis on family count.
    assert _confluence_weight(conf_step) == 4
    assert _confluence_weight(synth_step) < 4


def test_convergence_fact_family_count():
    """A synthesis 'convergence: a+b+c+d' fact also yields its family count."""
    node = IdeaNode(
        id="c", title="t", subject="app/x.py", operator="synthesis",
        kind="synthesis", source_facts=["convergence: untested+hub+high-churn"],
        value=0.5,
    )
    step = IdeaActionBridge().plan_idea(node)
    assert _confluence_weight(step) == 3


def test_top_step_is_confluence_when_near_tie_and_opt_in():
    # Synthesis carries a slightly HIGHER value, so plain value ranking would
    # surface it as #1 — but it has fewer converging signals.
    report = _report(_synthesis_idea(0.81), _confluence_idea(0.80))
    bridge = IdeaActionBridge()

    # Default (off): plain value ranking -> synthesis leads (audit's bug).
    default_plan = bridge.plan_tree(report)
    assert default_plan.steps[0].subject == "app/engine/idea_permutation.py"

    # Opt-in: the confluence subject (4 families) becomes the headline.
    plan = bridge.plan_tree(report, confluence_first=True)
    assert plan.steps[0].subject == "app/tools/project_profile.py"
    # The synthesis step is still present, just no longer #1.
    assert any(s.subject == "app/engine/idea_permutation.py" for s in plan.steps)
    # value is never mutated by the reorder.
    by_subject = {s.subject: s.value for s in plan.steps}
    assert by_subject["app/engine/idea_permutation.py"] == 0.81
    assert by_subject["app/tools/project_profile.py"] == 0.80


def test_reorder_is_deterministic():
    report = _report(_synthesis_idea(0.81), _confluence_idea(0.80))
    bridge = IdeaActionBridge()
    first = [s.branch_path + s.subject for s in
             bridge.plan_tree(report, confluence_first=True).steps]
    second = [s.branch_path + s.subject for s in
              bridge.plan_tree(report, confluence_first=True).steps]
    assert first == second


def test_no_reorder_when_gap_exceeds_epsilon():
    # Synthesis leads by MORE than the epsilon -> it is a real winner, not a
    # near-tie, so the headline tiebreaker must NOT promote the confluence.
    report = _report(_synthesis_idea(0.95), _confluence_idea(0.80))
    plan = IdeaActionBridge().plan_tree(report, confluence_first=True)
    assert plan.steps[0].subject == "app/engine/idea_permutation.py"


def test_tail_order_preserved_outside_band():
    # A far-below step stays exactly where value ranking placed it (last).
    tail = IdeaNode(
        id="tail", title="Develop app/z.py", subject="app/z.py",
        operator="extend", value=0.10,
    )
    report = _report(_synthesis_idea(0.81), _confluence_idea(0.80), tail)
    plan = IdeaActionBridge().plan_tree(report, confluence_first=True)
    assert plan.steps[0].subject == "app/tools/project_profile.py"
    assert plan.steps[-1].subject == "app/z.py"


def test_empty_and_single_step_plans_unaffected():
    bridge = IdeaActionBridge()
    assert bridge.plan_tree(_report(), confluence_first=True).steps == []
    one = bridge.plan_tree(_report(_confluence_idea(0.8)), confluence_first=True)
    assert len(one.steps) == 1
    assert one.steps[0].subject == "app/tools/project_profile.py"


def test_no_confluence_falls_back_to_source_fact_count():
    # A plain idea with one grounding fact has weight 1; ties break by subject.
    a = IdeaNode(id="a", title="Develop app/aaa.py", subject="app/aaa.py",
                 operator="extend", source_facts=["entrypoint: app/aaa.py"],
                 value=0.80)
    b = IdeaNode(id="b", title="Develop app/bbb.py", subject="app/bbb.py",
                 operator="extend", source_facts=["entrypoint: app/bbb.py"],
                 value=0.80)
    plan = IdeaActionBridge().plan_tree(_report(b, a), confluence_first=True)
    # Equal weight (1) -> stable subject ascending: app/aaa.py first.
    assert plan.steps[0].subject == "app/aaa.py"
