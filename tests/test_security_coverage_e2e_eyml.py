"""End-to-end proof: external vulnerable fixtures are detected, fixed/flagged,
and the change passes a verify step.

Each test builds a SMALL vulnerable Python file in a fresh tmp dir (never the
repo's own code or examples/), runs the real bridge detection ladder
(``_detect_security_issue``) plus the real ``security_transforms.apply`` path,
writes the patched content back, and then runs the shared apply-verify tail
(``run_full_suite_verification``) with a deterministic fake test runner to prove
a verify step actually executes and stamps evidence.

Deterministic, stdlib + pytest only (the test runner is faked, no network/clock).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.execution._apply_verify import run_full_suite_verification
from app.execution.semantic.transforms import security as security_transforms


class _Summary:
    def __init__(self, ok: bool, commands: list[str]) -> None:
        self.ok = ok
        self.commands = commands


def _fake_runner(monkeypatch, ok: bool) -> None:
    import app.engine.proof_of_fix as proof_mod
    import app.skills.execution.run_tests as run_tests_mod

    class _FakeSkill:
        def run(self, root: str):  # noqa: ANN001 - test double
            return _Summary(ok=ok, commands=["pytest"])

    monkeypatch.setattr(run_tests_mod, "RunTestsSkill", _FakeSkill)
    monkeypatch.setattr(proof_mod, "summarize_test_run", lambda s: {"ok": s.ok})


def _run_fix(tmp_path: Path, rel: str, source: str) -> tuple[str, str]:
    """Detect, fix, and write back the next security issue. Returns (label, text)."""
    (tmp_path / rel).write_text(source, encoding="utf-8")
    label = IdeaActionBridge._detect_security_issue(str(tmp_path), rel)
    assert label is not None, f"no issue detected in {rel}"
    result = security_transforms.apply(rel, source, f"fix {label}")
    assert result is not None, f"transform declined {label}"
    new_content = result.patch_requests[0]["new_content"]
    ast.parse(new_content)  # patched file is valid Python
    (tmp_path / rel).write_text(new_content, encoding="utf-8")
    return label, new_content


def _verify_step(monkeypatch, tmp_path: Path) -> dict:
    _fake_runner(monkeypatch, ok=True)
    out: dict = {}
    stands = run_full_suite_verification(tmp_path, out)
    assert stands is True
    assert out["verified"] is True
    assert out["test_evidence"] == {"ok": True}
    return out


def test_e2e_subprocess_shell_literal_is_rewritten_and_verified(tmp_path, monkeypatch) -> None:
    src = 'import subprocess\nsubprocess.run("ls -la /tmp", shell=True)\n'
    label, fixed = _run_fix(tmp_path, "vuln_shell.py", src)
    assert label == "subprocess-shell-literal"
    assert "shell=True" not in fixed
    assert "shlex.split(" in fixed
    # The rewrite self-clears: re-detecting finds no remaining issue.
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "vuln_shell.py") is None
    _verify_step(monkeypatch, tmp_path)


def test_e2e_hashlib_new_weak_is_rewritten_and_verified(tmp_path, monkeypatch) -> None:
    src = 'import hashlib\nh = hashlib.new("md5")\n'
    label, fixed = _run_fix(tmp_path, "vuln_hash.py", src)
    assert label == "hashlib-new-weak"
    assert "usedforsecurity=False" in fixed
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "vuln_hash.py") is None
    _verify_step(monkeypatch, tmp_path)


def test_e2e_os_popen_is_flagged_and_verified(tmp_path, monkeypatch) -> None:
    src = "import os\nos.popen('ls')\n"
    label, fixed = _run_fix(tmp_path, "vuln_popen.py", src)
    assert label == "os.popen"
    assert "# SECURITY (Apex: os.popen" in fixed
    # Flag-only: the call remains, but the marker makes the ladder converge
    # (the same label is skipped now its marker is present).
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "vuln_popen.py") is None
    _verify_step(monkeypatch, tmp_path)


def test_e2e_tls_verify_is_flagged_and_verified(tmp_path, monkeypatch) -> None:
    src = "import requests\nrequests.get(url, verify=False)\n"
    label, fixed = _run_fix(tmp_path, "vuln_tls.py", src)
    assert label == "tls-verify"
    assert "# SECURITY (Apex: TLS verification" in fixed
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "vuln_tls.py") is None
    _verify_step(monkeypatch, tmp_path)


def test_e2e_zip_slip_is_flagged_and_verified(tmp_path, monkeypatch) -> None:
    src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest)\n"
    label, fixed = _run_fix(tmp_path, "vuln_zip.py", src)
    assert label == "zip-slip"
    assert "# SECURITY (Apex: Zip-Slip" in fixed
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "vuln_zip.py") is None
    _verify_step(monkeypatch, tmp_path)


def test_e2e_clean_file_yields_no_issue(tmp_path) -> None:
    (tmp_path / "clean.py").write_text(
        "import hashlib\nh = hashlib.sha256()\n", encoding="utf-8")
    assert IdeaActionBridge._detect_security_issue(str(tmp_path), "clean.py") is None


def test_e2e_failing_verify_requests_rollback(tmp_path, monkeypatch) -> None:
    # Completeness: a verify step that fails reports the change must roll back.
    _fake_runner(monkeypatch, ok=False)
    out: dict = {}
    stands = run_full_suite_verification(tmp_path, out)
    assert stands is False
    assert out["verified"] is False
