from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApexMode(str, Enum):
    REPORT = "report"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


@dataclass
class ModePermissions:
    can_read: bool = True
    can_scan: bool = True
    can_analyze: bool = True
    can_patch: bool = False
    can_commit: bool = False
    can_auto_promote: bool = False
    can_run_tests: bool = False
    requires_clean_working_tree: bool = False
    requires_safety_gates: bool = False
    max_changed_files: int = 0
    max_patch_depth: int = 1


PERMISSIONS_BY_MODE: dict[ApexMode, ModePermissions] = {
    ApexMode.REPORT: ModePermissions(
        can_read=True,
        can_scan=True,
        can_analyze=True,
        can_patch=False,
        can_commit=False,
        can_auto_promote=False,
        can_run_tests=False,
        requires_clean_working_tree=False,
        requires_safety_gates=False,
        max_changed_files=0,
        max_patch_depth=0,
    ),
    ApexMode.SUPERVISED: ModePermissions(
        can_read=True,
        can_scan=True,
        can_analyze=True,
        can_patch=True,
        can_commit=False,
        can_auto_promote=False,
        can_run_tests=True,
        requires_clean_working_tree=False,
        requires_safety_gates=True,
        max_changed_files=5,
        max_patch_depth=1,
    ),
    ApexMode.AUTONOMOUS: ModePermissions(
        can_read=True,
        can_scan=True,
        can_analyze=True,
        can_patch=True,
        can_commit=True,
        can_auto_promote=True,
        can_run_tests=True,
        requires_clean_working_tree=True,
        requires_safety_gates=True,
        max_changed_files=10,
        max_patch_depth=3,
    ),
}


@dataclass
class SafetyGateResult:
    name: str
    passed: bool
    message: str
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "blocked": self.blocked,
        }


@dataclass
class ModePolicy:
    mode: ApexMode
    auto_patch: bool = False
    auto_commit: bool = False
    max_fractal_budget: int = 10
    safety_policy: str = "standard"
    custom_permissions: ModePermissions | None = None

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ApexMode(self.mode)

    @property
    def permissions(self) -> ModePermissions:
        if self.custom_permissions is not None:
            return self.custom_permissions
        return PERMISSIONS_BY_MODE.get(self.mode, PERMISSIONS_BY_MODE[ApexMode.REPORT])

    def can_write(self) -> bool:
        return self.permissions.can_patch

    def can_commit(self) -> bool:
        return self.permissions.can_commit

    def enforce_clean_working_tree(self) -> SafetyGateResult:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                return SafetyGateResult(
                    name="clean_working_tree",
                    passed=False,
                    message="Working tree is dirty. Commit or clean before autonomous operation.",
                    blocked=True,
                )
            return SafetyGateResult(
                name="clean_working_tree",
                passed=True,
                message="Working tree is clean.",
            )
        except Exception as exc:
            return SafetyGateResult(
                name="clean_working_tree",
                passed=False,
                message=f"Could not verify working tree: {exc}",
                blocked=True,
            )

    def summary(self) -> dict[str, Any]:
        p = self.permissions
        return {
            "mode": self.mode.value,
            "auto_patch": self.auto_patch,
            "auto_commit": self.auto_commit,
            "max_fractal_budget": self.max_fractal_budget,
            "safety_policy": self.safety_policy,
            "permissions": {
                "can_patch": p.can_patch,
                "can_commit": p.can_commit,
                "can_auto_promote": p.can_auto_promote,
                "can_run_tests": p.can_run_tests,
                "requires_clean_working_tree": p.requires_clean_working_tree,
                "requires_safety_gates": p.requires_safety_gates,
                "max_changed_files": p.max_changed_files,
                "max_patch_depth": p.max_patch_depth,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return self.summary()


def mode_from_string(mode_str: str | None) -> ApexMode:
    if mode_str is None:
        return ApexMode.SUPERVISED
    try:
        return ApexMode(mode_str.lower())
    except ValueError:
        return ApexMode.SUPERVISED


def apply_cli_overrides(
    policy: ModePolicy,
    auto_patch: bool | None,
    auto_commit: bool | None,
    max_fractal_budget: int | None,
    safety_policy: str | None,
) -> None:
    if auto_patch is not None:
        policy.auto_patch = auto_patch
    if auto_commit is not None:
        policy.auto_commit = auto_commit
    if max_fractal_budget is not None:
        policy.max_fractal_budget = max_fractal_budget
    if safety_policy is not None:
        policy.safety_policy = safety_policy
