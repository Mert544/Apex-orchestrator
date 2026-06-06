from app.skills.action_generator import ActionGenerator
from app.tools.project_profile import ProjectProfile


def test_profile_actions_are_generated_and_deduped():
    profile = ProjectProfile(
        root=".",
        critical_untested_modules=["app/core.py"],
        sensitive_paths=["app/auth.py"],
        dependency_hubs=["app/core.py"],
    )
    actions = ActionGenerator().generate(nodes=[], profile=profile)
    joined = " ".join(actions)
    assert any("critical untested" in a for a in actions)
    assert "app/auth.py" in joined and "security review" in joined.lower()
    assert "dependency hubs" in joined.lower()
    assert len(actions) == len(set(actions))  # deduped


def test_no_profile_yields_no_profile_actions():
    assert ActionGenerator().generate(nodes=[], profile=None) == []
