from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ApexMode(Enum):
    REPORT = "report"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


@dataclass
class ModePermissions:
    can_read: bool = True
    can_write: bool = False
    can_stage: bool = False
    can_commit: bool = False
    can_force: bool = False
    can_auto_patch: bool = False
    can_auto_commit: bool = False
    requires_safety_gates: bool = False
    requires_clean_tree: bool = False


@dataclass
class SafetyPolicy:
    check_scope: bool = True
    check_secrets: bool = True
    check_tests: bool = True
    check_sensitive_files: bool = True
    allow_rollback: bool = True
    max_patch_files: int = 10
    blocked_paths: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    required_test_files: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyPolicy:
        return cls(
            check_scope=data.get("check_scope", True),
            check_secrets=data.get("check_secrets", True),
            check_tests=data.get("check_tests", True),
            check_sensitive_files=data.get("check_sensitive_files", True),
            allow_rollback=data.get("allow_rollback", True),
            max_patch_files=data.get("max_patch_files", 10),
            blocked_paths=data.get("blocked_paths", []),
            blocked_patterns=data.get("blocked_patterns", []),
            required_test_files=data.get("required_test_files", []),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> SafetyPolicy:
        from app.utils.yaml_utils import load_yaml

        p = Path(path)
        if not p.exists():
            return cls()
        data = load_yaml(p)
        return cls.from_dict(data or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_scope": self.check_scope,
            "check_secrets": self.check_secrets,
            "check_tests": self.check_tests,
            "check_sensitive_files": self.check_sensitive_files,
            "allow_rollback": self.allow_rollback,
            "max_patch_files": self.max_patch_files,
            "blocked_paths": self.blocked_paths,
            "blocked_patterns": self.blocked_patterns,
            "required_test_files": self.required_test_files,
        }


def _build_mode_table() -> dict[ApexMode, ModePermissions]:
    return {
        ApexMode.REPORT: ModePermissions(
            can_read=True,
            can_write=False,
            can_stage=False,
            can_commit=False,
            can_force=False,
            can_auto_patch=False,
            can_auto_commit=False,
            requires_safety_gates=False,
            requires_clean_tree=False,
        ),
        ApexMode.SUPERVISED: ModePermissions(
            can_read=True,
            can_write=True,
            can_stage=True,
            can_commit=False,
            can_force=False,
            can_auto_patch=False,
            can_auto_commit=False,
            requires_safety_gates=True,
            requires_clean_tree=True,
        ),
        ApexMode.AUTONOMOUS: ModePermissions(
            can_read=True,
            can_write=True,
            can_stage=True,
            can_commit=True,
            can_force=False,
            can_auto_patch=True,
            can_auto_commit=True,
            requires_safety_gates=True,
            requires_clean_tree=True,
        ),
    }


@dataclass
class ModePolicy:
    mode: ApexMode
    permissions: ModePermissions
    safety_policy: SafetyPolicy
    max_fractal_budget: int = 10
    dry_run: bool = False
    _MODE_TABLE: dict[ApexMode, ModePermissions] = field(default_factory=_build_mode_table)

    @classmethod
    def from_env(cls) -> ModePolicy:
        mode_str = os.environ.get("APEX_MODE", "supervised").lower()
        try:
            mode = ApexMode(mode_str)
        except ValueError:
            mode = ApexMode.SUPERVISED

        auto_patch = os.environ.get("APEX_AUTO_PATCH", "0") in ("1", "true", "yes")
        auto_commit = os.environ.get("APEX_AUTO_COMMIT", "0") in ("1", "true", "yes")
        max_budget = int(os.environ.get("APEX_MAX_FRACTAL_BUDGET", "10"))
        dry_run = os.environ.get("APEX_DRY_RUN", "0") in ("1", "true", "yes")

        policy_path = os.environ.get("APEX_SAFETY_POLICY")
        if policy_path and Path(policy_path).exists():
            safety_policy = SafetyPolicy.from_yaml(policy_path)
        else:
            safety_policy = cls._default_safety_policy(mode)

        table = _build_mode_table()
        permissions = table[mode]
        if mode == ApexMode.SUPERVISED:
            permissions.can_auto_patch = auto_patch
        elif mode == ApexMode.AUTONOMOUS:
            permissions.can_auto_patch = auto_patch
            permissions.can_auto_commit = auto_commit

        return cls(
            mode=mode,
            permissions=permissions,
            safety_policy=safety_policy,
            max_fractal_budget=max_budget,
            dry_run=dry_run,
        )

    @classmethod
    def _default_safety_policy(cls, mode: ApexMode) -> SafetyPolicy:
        if mode == ApexMode.REPORT:
            return SafetyPolicy(
                check_scope=False,
                check_secrets=False,
                check_tests=False,
                check_sensitive_files=False,
                allow_rollback=False,
            )
        if mode == ApexMode.SUPERVISED:
            return SafetyPolicy(
                check_scope=True,
                check_secrets=True,
                check_tests=True,
                check_sensitive_files=True,
                allow_rollback=True,
                max_patch_files=5,
                blocked_paths=[],
                blocked_patterns=[],
                required_test_files=[],
            )
        return SafetyPolicy(
            check_scope=True,
            check_secrets=True,
            check_tests=True,
            check_sensitive_files=True,
            allow_rollback=True,
            max_patch_files=20,
            blocked_paths=[],
            blocked_patterns=[],
            required_test_files=[],
        )

    def can_apply_patch(self, patch_files: list[str]) -> tuple[bool, str]:
        if not self.permissions.can_write:
            return False, f"Mode {self.mode.value} does not permit writing files"
        if not self.permissions.can_auto_patch:
            return False, f"Mode {self.mode.value} does not permit automatic patching"
        if self.permissions.requires_safety_gates:
            result = self._check_safety_gates(patch_files)
            if not result[0]:
                return result
        if self.permissions.requires_clean_tree:
            clean, reason = self._check_clean_tree()
            if not clean:
                return False, f"Unclean working tree: {reason}"
        return True, "ok"

    def _check_safety_gates(self, patch_files: list[str]) -> tuple[bool, str]:
        sp = self.safety_policy
        target = os.environ.get("EPISTEMIC_TARGET_ROOT")
        project_root = Path(target).resolve() if target else Path.cwd()

        if sp.check_scope and len(patch_files) > sp.max_patch_files:
            return False, f"Patch scope {len(patch_files)} exceeds limit {sp.max_patch_files}"

        for pf in patch_files:
            pf_path = Path(pf)
            try:
                rel = pf_path.resolve().relative_to(project_root)
                rel_str = rel.as_posix()
            except ValueError:
                rel_str = pf_path.as_posix() if pf_path.is_absolute() else str(pf_path)

            for blocked in sp.blocked_paths:
                if rel_str == blocked or rel_str.startswith(blocked + "/"):
                    return False, f"File path '{pf}' is in blocked directory: {blocked}"

            for pattern in sp.blocked_patterns:
                if re.search(pattern, rel_str):
                    return False, f"File path '{pf}' matches blocked pattern: {pattern}"

        return True, "ok"

    def _check_clean_tree(self) -> tuple[bool, str]:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=os.environ.get("EPISTEMIC_TARGET_ROOT", "."),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False, "git status failed"
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            if lines:
                return False, f"{len(lines)} uncommitted changes"
            return True, "clean"
        except Exception as e:
            return False, f"git check failed: {e}"

    def should_block(self, reason: str) -> bool:
        return bool(reason and reason != "ok")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "permissions": {
                "can_read": self.permissions.can_read,
                "can_write": self.permissions.can_write,
                "can_stage": self.permissions.can_stage,
                "can_commit": self.permissions.can_commit,
                "can_force": self.permissions.can_force,
                "can_auto_patch": self.permissions.can_auto_patch,
                "can_auto_commit": self.permissions.can_auto_commit,
                "requires_safety_gates": self.permissions.requires_safety_gates,
                "requires_clean_tree": self.permissions.requires_clean_tree,
            },
            "safety_policy": self.safety_policy.to_dict(),
            "max_fractal_budget": self.max_fractal_budget,
            "dry_run": self.dry_run,
        }
