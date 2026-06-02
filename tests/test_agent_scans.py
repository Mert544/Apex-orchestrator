from app.automation.models import AutomationContext
from app.automation.skills.agent_scans import (
    coverage_scan_skill,
    dependency_scan_skill,
    docstring_scan_skill,
    security_scan_skill,
)


def _ctx(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "import os\n\ndef run(c):\n    return eval(c)\n\ndef helper(x):\n    return x + 1\n"
    )
    return AutomationContext(project_root=tmp_path, objective="scan", config={})


def test_security_scan_skill_finds_issues(tmp_path):
    result = security_scan_skill(_ctx(tmp_path))
    assert result["findings_count"] >= 1
    assert "findings" in result


def test_docstring_scan_skill_reports_gaps(tmp_path):
    result = docstring_scan_skill(_ctx(tmp_path))
    assert "gaps_found" in result
    # Scan-only: must not patch any files.
    assert result.get("patched_files") in (None, [], 0) or not result.get("patched_files")


def test_coverage_scan_skill(tmp_path):
    result = coverage_scan_skill(_ctx(tmp_path))
    assert "coverage_ratio" in result
    assert "gaps_found" in result


def test_dependency_scan_skill(tmp_path):
    result = dependency_scan_skill(_ctx(tmp_path))
    assert "total_modules" in result
    assert "total_edges" in result
