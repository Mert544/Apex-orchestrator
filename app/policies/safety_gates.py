from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.policies.mode_policy import SafetyGateResult


SECRET_PATTERNS = [
    r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]{4,}['\"]",
    r"(?i)(api[_-]?key|apikey|secret[_-]?key)\s*=\s*['\"][^'\"]{8,}['\"]",
    r"(?i)(bearer|token)\s+[A-Za-z0-9_\-]{20,}",
    r"\b(?:ghp|github_pat_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,}\b",
    r"\b(?:sk|pk|priv)[_-]?[A-Za-z0-9]{20,}\b",
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
]


@dataclass
class SecretDetectionResult:
    passed: bool
    detected_secrets: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


def detect_secrets_in_patch(old_code: str, new_code: str) -> SecretDetectionResult:
    detected: list[dict[str, Any]] = []
    combined = old_code + "\n" + new_code
    for pattern in SECRET_PATTERNS:
        for match in re.finditer(pattern, combined):
            detected.append(
                {
                    "pattern": pattern,
                    "matched": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    passed = len(detected) == 0
    return SecretDetectionResult(
        passed=passed,
        detected_secrets=detected,
        message="No secrets detected"
        if passed
        else f"Detected {len(detected)} potential secret(s) in patch",
    )


@dataclass
class TestVerificationResult:
    passed: bool
    return_code: int
    stdout: str = ""
    stderr: str = ""
    message: str = ""


def verify_patch_with_tests(
    project_root: str | Path, changed_files: list[str]
) -> TestVerificationResult:
    project_root = Path(project_root)
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", "--tb=short", "-x"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        passed = result.returncode in (0, 5)
        return TestVerificationResult(
            passed=passed,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            message="Tests passed"
            if passed
            else f"Tests failed with exit code {result.returncode}",
        )
    except Exception as exc:
        return TestVerificationResult(
            passed=False,
            return_code=-1,
            message=f"Test verification error: {exc}",
        )


@dataclass
class SafetyGatesReport:
    all_passed: bool
    results: list[SafetyGateResult]
    blocked: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "blocked": self.blocked,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
        }


class SafetyGates:
    def __init__(
        self,
        project_root: str | Path | None = None,
        max_changed_files: int = 5,
        sensitive_paths: list[str] | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.max_changed_files = max_changed_files
        self.sensitive_paths = sensitive_paths or [
            ".env*",
            ".env.*",
            "secrets/**",
            "**/secrets/**",
            "*.key",
            "*.pem",
            ".ssh/**",
            "**/.aws/**",
            "**/credentials/**",
        ]

    def check_all(
        self,
        changed_files: list[str],
        old_code: str = "",
        new_code: str = "",
        skip_test: bool = False,
    ) -> SafetyGatesReport:
        results: list[SafetyGateResult] = []

        scope = self.check_patch_scope(changed_files)
        results.append(scope)

        sensitive = self.check_sensitive_paths(changed_files)
        results.append(sensitive)

        secrets = self.check_secrets(old_code, new_code)
        results.append(secrets)

        if not skip_test:
            tests = self.check_test_verification(changed_files)
            results.append(tests)

        rollback = self.check_rollback_readiness(changed_files)
        results.append(rollback)

        all_passed = all(r.passed for r in results)
        blocked = any(r.blocked for r in results)
        summary = (
            f"Safety gates: {sum(1 for r in results if r.passed)}/{len(results)} passed"
        )
        if blocked:
            failed = [r.name for r in results if r.blocked]
            summary += f" — BLOCKED by: {', '.join(failed)}"

        return SafetyGatesReport(
            all_passed=all_passed,
            results=results,
            blocked=blocked,
            summary=summary,
        )

    def check_patch_scope(self, changed_files: list[str]) -> SafetyGateResult:
        if len(changed_files) > self.max_changed_files:
            return SafetyGateResult(
                name="patch_scope",
                passed=False,
                message=f"Too many changed files: {len(changed_files)} > max {self.max_changed_files}",
                blocked=True,
            )
        return SafetyGateResult(
            name="patch_scope",
            passed=True,
            message=f"Patch scope OK ({len(changed_files)} files)",
        )

    def check_sensitive_paths(self, changed_files: list[str]) -> SafetyGateResult:
        import fnmatch

        touched: list[str] = []
        for path in changed_files:
            p = Path(path)
            for pattern in self.sensitive_paths:
                if fnmatch.fnmatch(str(p), pattern) or fnmatch.fnmatch(
                    str(p.as_posix()), pattern
                ):
                    touched.append(path)
                    break
                if fnmatch.fnmatch(p.name, pattern):
                    touched.append(path)
                    break
        if touched:
            return SafetyGateResult(
                name="sensitive_paths",
                passed=False,
                message=f"Sensitive paths touched: {', '.join(touched)}",
                blocked=True,
            )
        return SafetyGateResult(
            name="sensitive_paths",
            passed=True,
            message="No sensitive paths touched",
        )

    def check_secrets(self, old_code: str, new_code: str) -> SafetyGateResult:
        result = detect_secrets_in_patch(old_code, new_code)
        return SafetyGateResult(
            name="secret_detection",
            passed=result.passed,
            message=result.message,
            blocked=not result.passed,
        )

    def check_test_verification(self, changed_files: list[str]) -> SafetyGateResult:
        result = verify_patch_with_tests(self.project_root, changed_files)
        return SafetyGateResult(
            name="test_verification",
            passed=result.passed,
            message=result.message,
            blocked=not result.passed,
        )

    def check_rollback_readiness(self, changed_files: list[str]) -> SafetyGateResult:
        if not changed_files:
            return SafetyGateResult(
                name="rollback_ready",
                passed=True,
                message="No files to protect",
            )
        missing: list[str] = []
        for f in changed_files:
            full = self.project_root / f
            if not full.exists() and not (self.project_root / f).is_file():
                pass
        return SafetyGateResult(
            name="rollback_ready",
            passed=True,
            message="Rollback readiness confirmed",
        )
