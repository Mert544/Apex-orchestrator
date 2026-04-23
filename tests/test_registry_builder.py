from app.automation.skills.registry_builder import build_default_registry


def test_registry_builds_without_error():
    registry = build_default_registry()
    assert registry is not None
    names = registry.list_names()
    assert len(names) > 0


def test_registry_has_expected_skills():
    registry = build_default_registry()
    names = set(registry.list_names())
    assert "profile_project" in names
    assert "run_research" in names
    assert "decompose_objective" in names
    assert "run_tests" in names
    assert "prepare_workspace" in names


def test_registry_skills_are_callable():
    registry = build_default_registry()
    for name in registry.list_names():
        skill = registry.get(name)
        assert callable(skill), f"Skill {name} is not callable"
