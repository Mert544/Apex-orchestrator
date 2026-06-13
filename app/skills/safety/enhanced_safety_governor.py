from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SafetyGovernorResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": self.violations,
            "policy": self.policy,
            "requires_human_review": self.requires_human_review,
        }


class EnhancedSafetyGovernor:
    """Config-driven safety governor with strict policy enforcement.

    Policies (config['safety']):
      - max_changed_files: int (default 5)
      - max_line_diff_per_file: int (default 50)
      - restricted_paths: list[str] — glob patterns, e.g. [".env*", "secrets/**"]
      - review_policy: str — "auto" | "human_required" | "block_sensitive"
    """

    DEFAULT_POLICY: dict[str, Any] = {
        "max_changed_files": 5,
        "max_line_diff_per_file": 50,
        "restricted_paths": [
            ".env*",
            ".env.*",
            "secrets/**",
            "**/secrets/**",
            "*.key",
            "*.pem",
            ".ssh/**",
        ],
        "review_policy": "block_sensitive",  # auto | human_required | block_sensitive
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.policy = dict(self.DEFAULT_POLICY)
        if config:
            safety_config = config.get("safety", {})
            self.policy.update(safety_config)

    def evaluate(
        self,
        changed_files: list[str],
        file_diffs: dict[str, int] | None = None,
    ) -> SafetyGovernorResult:
        """Evaluate a patch against safety policy.

        Args:
            changed_files: list of relative paths touched by the patch
            file_diffs: optional mapping path -> line_diff_count
        """
        file_diffs = file_diffs or {}
        violations: list[str] = []
        requires_human_review = False

        # 1. Max changed files
        max_files = int(self.policy.get("max_changed_files", 5))
        if len(changed_files) > max_files:
            violations.append(
                f"Too many changed files: {len(changed_files)} > max {max_files}"
            )

        # 2. Restricted paths
        restricted = list(self.policy.get("restricted_paths", []))
        for path in changed_files:
            if self._is_restricted(path, restricted):
                violations.append(f"Restricted path touched: {path}")
                requires_human_review = True

        # 3. Max line diff per file
        max_diff = int(self.policy.get("max_line_diff_per_file", 50))
        for path, diff_count in file_diffs.items():
            if diff_count > max_diff:
                violations.append(
                    f"Line diff too large for {path}: {diff_count} > max {max_diff}"
                )

        # 4. Review policy
        review_policy = str(self.policy.get("review_policy", "block_sensitive"))
        if review_policy == "human_required":
            requires_human_review = True
            violations.append("Review policy requires human approval for all patches.")
        elif review_policy == "block_sensitive" and requires_human_review:
            # Already flagged by restricted path check; violation stays
            pass

        ok = not violations
        return SafetyGovernorResult(
            ok=ok,
            violations=violations,
            policy=dict(self.policy),
            requires_human_review=requires_human_review,
        )

    @staticmethod
    def _is_restricted(path: str, patterns: list[str]) -> bool:
        from fnmatch import fnmatch
        p = Path(path)
        for pattern in patterns:
            if fnmatch(str(p), pattern) or fnmatch(str(p.as_posix()), pattern):
                return True
            # Also match against filename only
            if fnmatch(p.name, pattern):
                return True
        return False

    def compute_line_diffs(self, project_root: str | Path, changed_files: list[str]) -> dict[str, int]:
        """Compute approximate line diff counts from git diff output."""
        from app.runtime.git_adapter import GitAdapter
        git = GitAdapter()
        result = git.diff(project_root, changed_files)
        diffs: dict[str, int] = {}
        current_file = ""
        current_count = 0
        for line in result.stdout.splitlines():
            if line.startswith("diff --git"):
                if current_file:
                    diffs[current_file] = current_count
                current_file = ""
                current_count = 0
            elif line.startswith("--- a/") or line.startswith("+++ b/"):
                current_file = line[6:]
            if (line.startswith("+") or line.startswith("-")) and (not line.startswith("+++") and not line.startswith("---")):
                current_count += 1
        if current_file:
            diffs[current_file] = current_count
        return diffs
