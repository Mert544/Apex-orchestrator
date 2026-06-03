from __future__ import annotations

from app.policies.autonomy_policy import AutonomyDecision, AutonomyPolicy


def test_recommend_flag_always_wins():
    d = AutonomyPolicy().decide(
        executable_steps=5, working_tree_clean=True, explicit_recommend=True
    )
    assert d.act is False and d.mode == "report"


def test_explicit_apply_acts_supervised_then_autonomous():
    sup = AutonomyPolicy().decide(executable_steps=3, working_tree_clean=False, explicit_apply=True)
    assert sup.act is True and sup.mode == "supervised"
    auto = AutonomyPolicy().decide(
        executable_steps=3, working_tree_clean=False, explicit_apply=True, commit=True
    )
    assert auto.act is True and auto.mode == "autonomous"


def test_nothing_to_do_recommends():
    d = AutonomyPolicy().decide(executable_steps=0, working_tree_clean=True)
    assert d.act is False and "no safe" in d.reason


def test_dirty_tree_recommends_with_guidance():
    d = AutonomyPolicy().decide(executable_steps=4, working_tree_clean=False)
    assert d.act is False
    assert "uncommitted" in d.reason


def test_clean_tree_with_fixes_acts_autonomously():
    d = AutonomyPolicy().decide(executable_steps=4, working_tree_clean=True)
    assert d.act is True
    assert d.mode == "supervised"  # applies but doesn't commit by default
    assert "applying" in d.reason.lower()


def test_decision_to_dict():
    d = AutonomyPolicy().decide(executable_steps=1, working_tree_clean=True)
    assert isinstance(d, AutonomyDecision)
    assert set(d.to_dict()) == {"act", "mode", "reason"}
