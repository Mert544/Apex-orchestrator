from __future__ import annotations

from app.execution.auto_planner import AutoPlanner


def test_auto_planner_detects_untested_modules():
    report = {
        "project_profile": {
            "critical_untested_modules": ["app.auth.tokens", "app.payments.gateway"],
            "dependency_hubs": [],
            "sensitive_paths": [],
        },
        "recommended_actions": [],
        "branch_map": {},
    }
    planner = AutoPlanner()
    result = planner.plan(report)

    assert len(result.tasks) == 2
    assert "add docstrings" in result.patch_plan["change_strategy"]
    assert "app/auth/tokens.py" in result.patch_plan["target_files"]
    assert "untested" in result.rationale.lower()


def test_auto_planner_detects_dependency_hubs():
    report = {
        "project_profile": {
            "critical_untested_modules": [],
            "dependency_hubs": ["app.services.order_service"],
            "sensitive_paths": [],
        },
        "recommended_actions": [],
        "branch_map": {},
    }
    planner = AutoPlanner()
    result = planner.plan(report)

    assert len(result.tasks) == 1
    assert "add type annotations" in result.patch_plan["change_strategy"]
    assert "app/services/order_service.py" in result.patch_plan["target_files"]


def test_auto_planner_detects_sensitive_paths():
    report = {
        "project_profile": {
            "critical_untested_modules": [],
            "dependency_hubs": [],
            "sensitive_paths": ["app.auth.token_service"],
        },
        "recommended_actions": [],
        "branch_map": {},
    }
    planner = AutoPlanner()
    result = planner.plan(report)

    assert len(result.tasks) == 1
    assert "add guard clauses" in result.patch_plan["change_strategy"]
    assert "app/auth/token_service.py" in result.patch_plan["target_files"]


def test_auto_planner_limits_scope():
    report = {
        "project_profile": {
            "critical_untested_modules": [f"app.mod{i}" for i in range(10)],
            "dependency_hubs": [],
            "sensitive_paths": [],
        },
        "recommended_actions": [],
        "branch_map": {},
    }
    planner = AutoPlanner()
    result = planner.plan(report)

    assert len(result.tasks) == 3  # capped at 3
    assert len(result.patch_plan["target_files"]) == 3


def test_auto_planner_no_actions_when_healthy():
    report = {
        "project_profile": {
            "critical_untested_modules": [],
            "dependency_hubs": [],
            "sensitive_paths": [],
        },
        "recommended_actions": [],
        "branch_map": {},
    }
    planner = AutoPlanner()
    result = planner.plan(report)

    assert len(result.tasks) == 0
    assert "No high-priority" in result.rationale
