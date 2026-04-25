from __future__ import annotations

from app.execution.verifier import VerificationSummary, Verifier


def test_verifier_runs_without_crashing(tmp_path):
    v = Verifier()
    summary = v.verify(project_root=str(tmp_path), changed_files=[])
    assert isinstance(summary, VerificationSummary)
    assert summary.ok is not None
    assert "test_summary" in summary.to_dict()
    assert "patch_scope" in summary.to_dict()
    assert "sensitive_edit" in summary.to_dict()


def test_verifier_with_changed_files(tmp_path):
    v = Verifier()
    summary = v.verify(project_root=str(tmp_path), changed_files=["app/auth.py"])
    assert summary.patch_scope["changed_file_count"] == 1


def test_verification_summary_to_dict():
    s = VerificationSummary(ok=True, project_root="/tmp")
    d = s.to_dict()
    assert d["ok"]
    assert d["project_root"] == "/tmp"
