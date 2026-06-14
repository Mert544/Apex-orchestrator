import subprocess

from app.policies.safety_gates import (
    SafetyGates,
    SafetyGatesReport,
    detect_secrets_in_patch,
    verify_patch_with_tests,
)
from app.policies.safety_gates import (
    TestVerificationResult as VerificationResult,  # aliased; pytest must not collect it
)


class _FakeCompleted:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestSecretDetection:
    def test_no_secrets_clean_code(self):
        result = detect_secrets_in_patch(
            "def foo():\n    pass", "def foo():\n    x = 1"
        )
        assert result.passed is True
        assert not result.detected_secrets

    def test_detects_password_assignment(self):
        result = detect_secrets_in_patch("", 'password = "abcd1234efgh5678"')
        assert result.passed is False
        assert len(result.detected_secrets) > 0

    def test_detects_api_key_pattern(self):
        result = detect_secrets_in_patch("", 'api_key = "sk_1234567890abcdefghijklmn"')
        assert result.passed is False

    def test_detects_github_token(self):
        result = detect_secrets_in_patch(
            "", "ghp_abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOPQRSTUV"
        )
        assert result.passed is False

    def test_detects_private_key_header(self):
        result = detect_secrets_in_patch(
            "",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
        )
        assert result.passed is False

    def test_old_and_new_code_both_scanned(self):
        old = 'password = "wrong_password"'
        new = 'password = "correct_password"'
        result = detect_secrets_in_patch(old, new)
        assert result.passed is False


class TestSafetyGatesScope:
    def test_patch_scope_pass(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, max_changed_files=5)
        result = gates.check_patch_scope(["a.py", "b.py"])
        assert result.passed is True
        assert result.blocked is False

    def test_patch_scope_too_many_files(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, max_changed_files=2)
        result = gates.check_patch_scope(["a.py", "b.py", "c.py"])
        assert result.passed is False
        assert result.blocked is True

    def test_patch_scope_exactly_at_limit(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, max_changed_files=3)
        result = gates.check_patch_scope(["a.py", "b.py", "c.py"])
        assert result.passed is True


class TestSafetyGatesSensitivePaths:
    def test_sensitive_paths_pass(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_sensitive_paths(["app/main.py", "tests/test_main.py"])
        assert result.passed is True

    def test_sensitive_paths_blocked_env(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_sensitive_paths([".env.production"])
        assert result.passed is False
        assert result.blocked is True

    def test_sensitive_paths_blocked_secrets(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_sensitive_paths(["secrets/data.json"])
        assert result.passed is False
        assert result.blocked is True

    def test_sensitive_paths_blocked_ssh(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_sensitive_paths([".ssh/id_rsa"])
        assert result.passed is False

    def test_sensitive_paths_glob_pattern(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, sensitive_paths=[".env*"])
        result = gates.check_sensitive_paths([".env.local"])
        assert result.passed is False


class TestSafetyGatesSecrets:
    def test_check_secrets_passes_clean(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_secrets("def foo():\n    pass", "def foo():\n    x = 1")
        assert result.passed is True


class TestSafetyGatesReport:
    def test_all_passed_report(self):
        results = [
            type(
                "SGR",
                (),
                {
                    "name": "scope",
                    "passed": True,
                    "blocked": False,
                    "to_dict": lambda s: {
                        "name": "scope",
                        "passed": True,
                        "blocked": False,
                    },
                },
            )(),
            type(
                "SGR",
                (),
                {
                    "name": "sensitive",
                    "passed": True,
                    "blocked": False,
                    "to_dict": lambda s: {
                        "name": "sensitive",
                        "passed": True,
                        "blocked": False,
                    },
                },
            )(),
        ]
        report = SafetyGatesReport(
            all_passed=True, results=results, blocked=False, summary="2/2 passed"
        )
        assert report.all_passed is True
        assert report.blocked is False

    def test_blocked_report(self):
        results = [
            type(
                "SGR",
                (),
                {
                    "name": "scope",
                    "passed": True,
                    "blocked": False,
                    "to_dict": lambda s: {
                        "name": "scope",
                        "passed": True,
                        "blocked": False,
                    },
                },
            )(),
            type(
                "SGR",
                (),
                {
                    "name": "sensitive",
                    "passed": False,
                    "blocked": True,
                    "to_dict": lambda s: {
                        "name": "sensitive",
                        "passed": False,
                        "blocked": True,
                    },
                },
            )(),
        ]
        report = SafetyGatesReport(
            all_passed=False,
            results=results,
            blocked=True,
            summary="BLOCKED by: sensitive",
        )
        assert report.blocked is True
        assert report.all_passed is False


class TestSecretDetectionPreExisting:
    def test_preexisting_secret_does_not_block_unrelated_fix(self):
        # A file already containing a secret; the patch only changes an unrelated
        # line (eval -> literal_eval). The pre-existing secret is present in BOTH
        # old and new, unchanged, so it must NOT be flagged.
        secret = 'DB_PASSWORD = "legacy_bank_123456"'
        old = f'{secret}\nx = eval(s)\n'
        new = f'{secret}\nx = ast.literal_eval(s)\n'
        result = detect_secrets_in_patch(old, new)
        assert result.passed is True
        assert result.detected_secrets == []

    def test_newly_introduced_secret_is_still_blocked(self):
        old = "x = 1\n"
        new = 'x = 1\napi_key = "sk_introduced_1234567890abcd"\n'
        result = detect_secrets_in_patch(old, new)
        assert result.passed is False


class TestVerifyPatchWithTests:
    def test_returns_passed_on_zero_exit(self, tmp_path, monkeypatch):
        def fake_run(*args, **kwargs):
            return _FakeCompleted(0, stdout="3 passed")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = verify_patch_with_tests(tmp_path)
        assert result.passed is True
        assert result.return_code == 0
        assert result.stdout == "3 passed"
        assert result.message == "Tests passed"

    def test_exit_code_5_no_tests_is_pass(self, tmp_path, monkeypatch):
        # pytest exit code 5 == "no tests collected"; treated as a pass.
        def fake_run(*args, **kwargs):
            return _FakeCompleted(5)

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = verify_patch_with_tests(tmp_path)
        assert result.passed is True
        assert result.return_code == 5

    def test_nonzero_exit_fails(self, tmp_path, monkeypatch):
        def fake_run(*args, **kwargs):
            return _FakeCompleted(1, stderr="assert failed")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = verify_patch_with_tests(tmp_path)
        assert result.passed is False
        assert result.return_code == 1
        assert "exit code 1" in result.message

    def test_subprocess_exception_is_caught(self, tmp_path, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=120)

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = verify_patch_with_tests(tmp_path)
        assert result.passed is False
        assert result.return_code == -1
        assert "Test verification error" in result.message


class TestCheckTestVerification:
    def test_passing_tests_gate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0))
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_test_verification(["a.py"])
        assert result.name == "test_verification"
        assert result.passed is True
        assert result.blocked is False

    def test_failing_tests_block(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(1))
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_test_verification(["a.py"])
        assert result.passed is False
        assert result.blocked is True


class TestRollbackReadiness:
    def test_no_files_passes(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_rollback_readiness([])
        assert result.passed is True
        assert result.message == "No files to protect"

    def test_files_present_confirms_rollback(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        gates = SafetyGates(project_root=tmp_path)
        result = gates.check_rollback_readiness(["a.py", "missing.py"])
        assert result.passed is True
        assert result.message == "Rollback readiness confirmed"


class TestCheckAll:
    def test_all_pass_skipping_tests(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, max_changed_files=5)
        report = gates.check_all(
            ["app/main.py", "tests/test_main.py"],
            old_code="x = 1",
            new_code="x = 2",
            skip_test=True,
        )
        assert isinstance(report, SafetyGatesReport)
        assert report.all_passed is True
        assert report.blocked is False
        # skip_test omits the test_verification gate -> 4 gates run.
        assert len(report.results) == 4
        assert "test_verification" not in {r.name for r in report.results}
        assert "4/4 passed" in report.summary

    def test_runs_test_gate_when_not_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0))
        gates = SafetyGates(project_root=tmp_path)
        report = gates.check_all(["a.py"], skip_test=False)
        assert len(report.results) == 5
        assert "test_verification" in {r.name for r in report.results}
        assert report.all_passed is True

    def test_blocked_summary_lists_failing_gate(self, tmp_path):
        # Too many changed files trips the patch_scope gate -> blocked.
        gates = SafetyGates(project_root=tmp_path, max_changed_files=1)
        report = gates.check_all(["a.py", "b.py", "c.py"], skip_test=True)
        assert report.all_passed is False
        assert report.blocked is True
        assert "BLOCKED by: patch_scope" in report.summary

    def test_sensitive_path_blocks_check_all(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path, max_changed_files=10)
        report = gates.check_all([".env.production"], skip_test=True)
        assert report.blocked is True
        assert "sensitive_paths" in report.summary

    def test_report_to_dict_roundtrips_results(self, tmp_path):
        gates = SafetyGates(project_root=tmp_path)
        report = gates.check_all(["a.py"], skip_test=True)
        d = report.to_dict()
        assert d["all_passed"] is report.all_passed
        assert d["blocked"] is report.blocked
        assert d["summary"] == report.summary
        assert isinstance(d["results"], list)
        assert all("name" in r and "passed" in r for r in d["results"])


class TestVerificationResultDataclass:
    def test_defaults(self):
        result = VerificationResult(passed=True, return_code=0)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.message == ""


class TestSensitivePathBasenameMatch:
    def test_basename_only_pattern_matches_nested_path(self, tmp_path):
        # A non-glob pattern like "id_rsa" does not match the full nested path
        # ("deep/nested/id_rsa") via fnmatch, but does match the basename — this
        # exercises the p.name fallback branch.
        gates = SafetyGates(project_root=tmp_path, sensitive_paths=["id_rsa"])
        result = gates.check_sensitive_paths(["deep/nested/id_rsa"])
        assert result.passed is False
        assert result.blocked is True
        assert "id_rsa" in result.message
