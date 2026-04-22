from __future__ import annotations

from pathlib import Path

from app.automation.smart_planner import SmartPlanner


def test_selects_verify_when_no_issues(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 20,
        "critical_untested_modules": [],
        "dependency_hubs": [],
        "sensitive_paths": [],
        "test_coverage": 0.85,
    }
    plan = planner.select_plan(profile, has_uncommitted_changes=False)
    assert plan == "verify_project"


def test_selects_semantic_patch_when_untested(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 20,
        "critical_untested_modules": ["app.auth.tokens"],
        "dependency_hubs": [],
        "sensitive_paths": [],
        "test_coverage": 0.3,
    }
    plan = planner.select_plan(profile, has_uncommitted_changes=False)
    assert plan == "semantic_patch_loop"


def test_selects_git_pr_when_uncommitted_changes(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 20,
        "critical_untested_modules": [],
        "dependency_hubs": [],
        "sensitive_paths": [],
        "test_coverage": 0.8,
    }
    plan = planner.select_plan(profile, has_uncommitted_changes=True)
    assert plan == "git_pr_loop"


def test_selects_project_scan_when_many_hubs(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 50,
        "critical_untested_modules": [],
        "dependency_hubs": ["app.services.order", "app.services.payment", "app.services.inventory"],
        "sensitive_paths": [],
        "test_coverage": 0.7,
    }
    plan = planner.select_plan(profile, has_uncommitted_changes=False)
    assert plan == "project_scan"


def test_selects_full_autonomous_when_many_issues(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 30,
        "critical_untested_modules": ["a", "b", "c", "d", "e"],
        "dependency_hubs": ["hub1", "hub2"],
        "sensitive_paths": ["auth", "payment"],
        "test_coverage": 0.2,
    }
    plan = planner.select_plan(profile, has_uncommitted_changes=False)
    assert plan == "full_autonomous_loop"


def test_explains_rationale(tmp_path: Path):
    planner = SmartPlanner()
    profile = {
        "total_files": 20,
        "critical_untested_modules": ["app.auth.tokens"],
        "dependency_hubs": [],
        "sensitive_paths": [],
        "test_coverage": 0.3,
    }
    result = planner.select_plan_with_rationale(profile, has_uncommitted_changes=False)
    assert result["plan"] == "semantic_patch_loop"
    assert "untested" in result["rationale"].lower()
