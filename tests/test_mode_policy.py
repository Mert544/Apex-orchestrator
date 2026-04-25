from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.policy.mode import ApexMode, ModePermissions, ModePolicy, SafetyPolicy


class TestApexMode:
    def test_modes_have_values(self):
        assert ApexMode.REPORT.value == "report"
        assert ApexMode.SUPERVISED.value == "supervised"
        assert ApexMode.AUTONOMOUS.value == "autonomous"

    def test_modes_are_distinct(self):
        assert len({ApexMode.REPORT, ApexMode.SUPERVISED, ApexMode.AUTONOMOUS}) == 3


class TestSafetyPolicy:
    def test_defaults(self):
        sp = SafetyPolicy()
        assert sp.check_scope is True
        assert sp.check_secrets is True
        assert sp.check_tests is True
        assert sp.max_patch_files == 10
        assert sp.allow_rollback is True

    def test_from_dict(self):
        data = {
            "check_scope": False,
            "check_secrets": False,
            "max_patch_files": 20,
            "blocked_paths": [".env", "secrets/"],
        }
        sp = SafetyPolicy.from_dict(data)
        assert sp.check_scope is False
        assert sp.check_secrets is False
        assert sp.max_patch_files == 20
        assert ".env" in sp.blocked_paths
        assert "secrets/" in sp.blocked_paths

    def test_to_dict_roundtrip(self):
        sp = SafetyPolicy(
            check_scope=True,
            check_secrets=False,
            max_patch_files=15,
            blocked_paths=["config/secrets.yaml"],
            blocked_patterns=[r"password\s*="],
        )
        d = sp.to_dict()
        sp2 = SafetyPolicy.from_dict(d)
        assert sp2.check_scope == sp.check_scope
        assert sp2.max_patch_files == sp.max_patch_files


class TestModePermissions:
    def test_report_permissions(self):
        mp = ModePermissions(
            can_read=True,
            can_write=False,
            can_stage=False,
            can_commit=False,
            can_force=False,
            can_auto_patch=False,
            can_auto_commit=False,
            requires_safety_gates=False,
            requires_clean_tree=False,
        )
        assert mp.can_write is False
        assert mp.can_commit is False
        assert mp.can_auto_patch is False

    def test_supervised_permissions(self):
        mp = ModePermissions(
            can_read=True,
            can_write=True,
            can_stage=True,
            can_commit=False,
            can_force=False,
            can_auto_patch=False,
            can_auto_commit=False,
            requires_safety_gates=True,
            requires_clean_tree=True,
        )
        assert mp.can_write is True
        assert mp.can_commit is False
        assert mp.can_auto_patch is False
        assert mp.requires_safety_gates is True

    def test_autonomous_permissions(self):
        mp = ModePermissions(
            can_read=True,
            can_write=True,
            can_stage=True,
            can_commit=True,
            can_force=False,
            can_auto_patch=True,
            can_auto_commit=True,
            requires_safety_gates=True,
            requires_clean_tree=True,
        )
        assert mp.can_commit is True
        assert mp.can_auto_patch is True
        assert mp.can_auto_commit is True


class TestModePolicyDefaults:
    def test_report_mode_policy(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.REPORT,
            permissions=table[ApexMode.REPORT],
            safety_policy=SafetyPolicy(),
        )
        assert policy.mode == ApexMode.REPORT
        assert policy.permissions.can_write is False
        assert policy.permissions.can_commit is False

    def test_supervised_mode_policy(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=table[ApexMode.SUPERVISED],
            safety_policy=SafetyPolicy(),
        )
        assert policy.mode == ApexMode.SUPERVISED
        assert policy.permissions.can_write is True
        assert policy.permissions.can_commit is False
        assert policy.permissions.requires_safety_gates is True

    def test_autonomous_mode_policy(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=table[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(),
        )
        assert policy.mode == ApexMode.AUTONOMOUS
        assert policy.permissions.can_write is True
        assert policy.permissions.can_commit is True
        assert policy.permissions.can_auto_patch is True
        assert policy.permissions.requires_safety_gates is True
        assert policy.permissions.requires_clean_tree is True

    def test_mode_policy_to_dict(self):
        from app.policy.mode import _build_mode_table
        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=_build_mode_table()[ApexMode.SUPERVISED],
            safety_policy=SafetyPolicy(),
        )
        d = policy.to_dict()
        assert d["mode"] == "supervised"
        assert d["permissions"]["can_write"] is True
        assert d["permissions"]["can_commit"] is False
        assert d["permissions"]["can_auto_patch"] is False


class TestModePolicyFromEnv:
    def test_defaults_when_no_env(self, monkeypatch):
        for key in ["APEX_MODE", "APEX_AUTO_PATCH", "APEX_AUTO_COMMIT", "APEX_MAX_FRACTAL_BUDGET"]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("APEX_SAFETY_POLICY", raising=False)
        policy = ModePolicy.from_env()
        assert policy.mode == ApexMode.SUPERVISED
        assert policy.max_fractal_budget == 10
        assert policy.dry_run is False

    def test_report_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("APEX_MODE", "report")
        monkeypatch.delenv("APEX_AUTO_PATCH", raising=False)
        monkeypatch.delenv("APEX_AUTO_COMMIT", raising=False)
        policy = ModePolicy.from_env()
        assert policy.mode == ApexMode.REPORT
        assert policy.permissions.can_write is False

    def test_autonomous_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("APEX_MODE", "autonomous")
        monkeypatch.setenv("APEX_AUTO_PATCH", "1")
        monkeypatch.setenv("APEX_AUTO_COMMIT", "1")
        monkeypatch.setenv("APEX_MAX_FRACTAL_BUDGET", "20")
        monkeypatch.setenv("APEX_DRY_RUN", "1")
        policy = ModePolicy.from_env()
        assert policy.mode == ApexMode.AUTONOMOUS
        assert policy.permissions.can_auto_patch is True
        assert policy.permissions.can_auto_commit is True
        assert policy.max_fractal_budget == 20
        assert policy.dry_run is True

    def test_invalid_mode_defaults_to_supervised(self, monkeypatch):
        monkeypatch.setenv("APEX_MODE", "invalid_mode")
        policy = ModePolicy.from_env()
        assert policy.mode == ApexMode.SUPERVISED


class TestModePolicyCanApplyPatch:
    def test_report_mode_blocks_write(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.REPORT,
            permissions=table[ApexMode.REPORT],
            safety_policy=SafetyPolicy(),
        )
        ok, reason = policy.can_apply_patch(["file.py"])
        assert ok is False
        assert "report" in reason.lower()

    def test_supervised_without_auto_patch_blocks(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=table[ApexMode.SUPERVISED],
            safety_policy=SafetyPolicy(),
        )
        ok, reason = policy.can_apply_patch(["file.py"])
        assert ok is False
        assert "supervised" in reason.lower()

    def test_scope_limit_respected(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=table[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(max_patch_files=2),
        )
        ok, reason = policy.can_apply_patch(["a.py", "b.py", "c.py"])
        assert ok is False
        assert "exceeds" in reason.lower()

    def test_blocked_path_respected(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=table[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(blocked_paths=[".env"]),
        )
        ok, reason = policy.can_apply_patch([".env"])
        assert ok is False
        assert "blocked" in reason.lower()

    def test_blocked_pattern_respected(self):
        from app.policy.mode import _build_mode_table
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=table[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(blocked_patterns=[r"secrets\.yaml"]),
        )
        ok, reason = policy.can_apply_patch(["config/secrets.yaml"])
        assert ok is False


class TestModePolicySafetyGate:
    def test_safety_gates_enforced_when_required(self, monkeypatch):
        from app.policy.mode import _build_mode_table
        import os
        monkeypatch.setenv("EPISTEMIC_TARGET_ROOT", "C:/Users/salio/Apex-orchestrator")
        table = _build_mode_table()
        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=ModePermissions(
                can_read=True,
                can_write=True,
                can_stage=True,
                can_commit=False,
                can_force=False,
                can_auto_patch=True,
                can_auto_commit=False,
                requires_safety_gates=True,
                requires_clean_tree=False,
            ),
            safety_policy=SafetyPolicy(blocked_paths=["config/secrets.yaml"]),
        )
        ok, reason = policy.can_apply_patch(["config/secrets.yaml"])
        assert ok is False, f"Expected False but got True with reason: {reason}"


class TestSafetyPolicyFromYaml:
    def test_from_yaml_missing_file_uses_default(self):
        sp = SafetyPolicy.from_yaml("/nonexistent/path.yaml")
        assert sp.check_scope is True
        assert sp.check_secrets is True
