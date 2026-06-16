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


def _node(claim, ctype=None, priority=0.5, nid="n1"):
    from app.models.enums import ClaimType
    from app.models.node import ResearchNode
    return ResearchNode(id=nid, claim=claim,
                        claim_type=ctype or ClaimType.GENERAL,
                        claim_priority=priority)


def test_meta_claims_are_skipped():
    gen = ActionGenerator()
    for prefix in ActionGenerator.META_PREFIXES:
        assert gen._action_for_node(_node(f"{prefix} something about app/x.py")) is None


def test_keyword_claims_with_paths_route_to_specific_actions():
    gen = ActionGenerator()
    cases = {
        "Untested module claim: app/a.py lacks tests": "test coverage",
        "Dependency hub claim: app/b.py is centrally imported": "architectural coupling",
        "Sensitive surface claim: app/auth.py handles tokens": "security-focused review",
        "Configuration claim: config/dev.yaml has unsafe defaults": "configuration handling",
        "Automation claim: ci.yml does not run tests": "CI or workflow",
    }
    for claim, fragment in cases.items():
        action = gen._action_for_node(_node(claim))
        assert action and fragment in action, (claim, action)


def test_claim_type_with_paths_routes_by_type():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    cases = {
        ClaimType.SECURITY: "secrets, auth",
        ClaimType.VALIDATION: "Strengthen or add tests",
        ClaimType.AUTOMATION: "Expand automated checks",
        ClaimType.CONFIGURATION: "configuration boundaries",
        ClaimType.ARCHITECTURE: "high-centrality modules",
        ClaimType.OPERATIONS: "observability",
    }
    for ctype, fragment in cases.items():
        action = gen._action_for_node(_node("The file app/thing.py is implicated.", ctype))
        assert action and fragment in action and "app/thing.py" in action, (ctype, action)


def test_claim_type_without_paths_falls_back_to_claim_text():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    claim = "Input validation is inconsistent across handlers"
    action = gen._action_for_node(_node(claim, ClaimType.VALIDATION))
    assert action and claim in action
    gap = gen._action_for_node(_node("There is no export feature", ClaimType.FEATURE_GAP))
    assert gap and "acceptance criteria" in gap


def test_general_claim_without_signal_yields_nothing():
    assert ActionGenerator()._action_for_node(_node("Something vague happened.")) is None


def test_generate_orders_by_priority_dedupes_and_caps_at_ten():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    # Two nodes produce the SAME action -> deduped; higher priority comes first.
    low = _node("The file app/low.py is implicated.", ClaimType.SECURITY, priority=0.1, nid="lo")
    high = _node("Check app/high.py carefully.", ClaimType.SECURITY, priority=0.9, nid="hi")
    dup = _node("Check app/high.py carefully.", ClaimType.SECURITY, priority=0.8, nid="dup")
    actions = gen.generate([low, high, dup], profile=None)
    assert len(actions) == 2
    assert "app/high.py" in actions[0] and "app/low.py" in actions[1]

    many = [
        _node(f"The file app/m{i}.py is implicated.", ClaimType.VALIDATION, priority=1 - i / 100, nid=f"m{i}")
        for i in range(15)
    ]
    assert len(gen.generate(many, profile=None)) == 10   # capped


def test_keyword_claim_without_paths_falls_through_to_type_or_none():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    # Keyword phrase present but no path -> keyword block is skipped.
    # GENERAL has no text fallback -> None.
    assert gen._action_for_node(_node("Untested module claim: nothing concrete here")) is None
    # Keyword phrase present, no path, but a fallback-eligible type -> text fallback.
    claim = "Configuration claim: defaults are unsafe everywhere"
    action = gen._action_for_node(_node(claim, ClaimType.CONFIGURATION))
    assert action and "configuration defaults" in action and claim in action


def test_paths_present_but_type_has_no_path_template_uses_text_fallback():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    # FEATURE_GAP has no path template and no keyword match -> text fallback even with a path.
    claim = "There is no export feature in app/exporter.py yet"
    action = gen._action_for_node(_node(claim, ClaimType.FEATURE_GAP))
    assert action and "acceptance criteria" in action and claim in action
    # GENERAL with a path and no keyword -> nothing at all.
    assert gen._action_for_node(_node("Touches app/x.py somehow.", ClaimType.GENERAL)) is None


def test_keyword_block_wins_over_claim_type_when_path_present():
    from app.models.enums import ClaimType
    gen = ActionGenerator()
    # Keyword match takes precedence over the claim_type path template.
    action = gen._action_for_node(
        _node("Untested module claim: app/a.py lacks tests", ClaimType.SECURITY)
    )
    assert action and "test coverage" in action


def test_extract_paths_normalizes_and_dedupes():
    gen = ActionGenerator()
    paths = gen._extract_paths("See app/x.py and app/x.py plus conf/dev.yaml and notes.md")
    assert paths.count(str(__import__('pathlib').Path('app/x.py'))) == 1
    assert any(p.endswith("dev.yaml") for p in paths)
    assert any(p.endswith("notes.md") for p in paths)
