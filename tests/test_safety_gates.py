import os
import tempfile
from pathlib import Path

from app.policies.safety_gates import (
    SafetyGates,
    SafetyGatesReport,
    SecretDetectionResult,
    detect_secrets_in_patch,
    verify_patch_with_tests,
)


class TestSecretDetection:
    def test_no_secrets_clean_code(self):
        result = detect_secrets_in_patch(
            "def foo():\n    pass", "def foo():\n    x = 1"
        )
        assert result.passed is True
        assert len(result.detected_secrets) == 0

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
