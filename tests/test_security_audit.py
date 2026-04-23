from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Script uses shebang / Unix path assumptions")
def test_security_audit_script_runs_successfully():
    root = Path(__file__).parent.parent
    script = root / "scripts" / "security_audit.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    # The script may exit 0 or 1 depending on risks found, but should not crash
    assert result.returncode in (0, 1)
    assert "Apex Orchestrator Security Audit Report" in result.stdout
    assert "security-report.json" in result.stdout or (root / ".apex" / "security-report.json").exists()


def test_security_audit_report_format():
    root = Path(__file__).parent.parent
    # Import and run directly to avoid subprocess issues on Windows
    sys.path.insert(0, str(root))
    from scripts.security_audit import run_audit

    report = run_audit(root)
    assert "project_root" in report
    assert "summary" in report
    assert "risks" in report
    assert "critical_untested_modules" in report
    summary = report["summary"]
    assert "total_files" in summary
    assert "functions_analyzed" in summary
    assert "critical" in summary
    assert "high" in summary
    assert "medium" in summary
    assert "low" in summary
    # Verify examples are excluded
    for category in ("critical", "high", "medium", "low"):
        for risk in report["risks"][category]:
            assert "examples/" not in risk["file"]
            assert "scripts/" not in risk["file"]
