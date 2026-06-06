from app.orchestrator.factory import FocusBranchResolver


def test_resolve_finds_claim_and_question_in_full_report():
    state = {"last_full_report": {"branch_map": {"x.a": "the claim"},
                                  "branch_questions": {"x.a": "the question?"}}}
    claim, question = FocusBranchResolver.resolve("x.a", state)
    assert claim == "the claim" and question == "the question?"


def test_resolve_falls_back_to_last_report():
    state = {"last_full_report": {}, "last_report": {"branch_map": {"x.b": "c2"}}}
    claim, question = FocusBranchResolver.resolve("x.b", state)
    assert claim == "c2" and question is None


def test_resolve_missing_branch_or_bad_state_is_none():
    assert FocusBranchResolver.resolve("x.z", {"last_full_report": {"branch_map": {}}}) == (None, None)
    assert FocusBranchResolver.resolve("x.a", None) == (None, None)
