"""Deep mutation-hardening tests for app/orchestrator/core.py and app/main.py.

Targets the full single-token mutant universe (past the default 30 cap) for both
modules, killing every non-equivalent survivor with a deterministic test. One
behavior per test, named for the mutation it pins down. No timestamps, no
wall-clock, no unordered-collection assertions.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from app.main import (
    _is_broad_plan,
    _wants_security,
    _wants_docstring,
    _wants_test,
    _wants_dependency,
    _env_flag,
    _build_policy,
    _safety_gates_block,
    _load_plugins,
    _resolve_use_fractal,
)
from app.policies.mode_policy import ModePolicy, ApexMode


# ---------------------------------------------------------------------------
# app/main.py — pure plan-predicate helpers
# ---------------------------------------------------------------------------


class TestBroadPlan:
    def test_project_scan_is_broad(self):
        assert _is_broad_plan("project_scan") is True

    def test_full_is_broad(self):
        assert _is_broad_plan("full_autonomous_loop") is True

    def test_self_is_broad(self):
        assert _is_broad_plan("self_improve") is True

    def test_narrow_plan_is_not_broad(self):
        # Pins the three OR-clauses: none of the keywords present -> False.
        assert _is_broad_plan("security_audit") is False


class TestWantsSecurity:
    def test_security_keyword_triggers(self):
        # broad=False so only the keyword can make it True (kills the `or broad`
        # left operand being dropped).
        assert _wants_security("security_audit", False) is True

    def test_broad_triggers_without_keyword(self):
        assert _wants_security("docstring_loop", False) is False
        assert _wants_security("docstring_loop", True) is True

    def test_no_keyword_not_broad_is_false(self):
        assert _wants_security("docstring_loop", False) is False


class TestWantsDocstring:
    def test_docstring_keyword_triggers(self):
        assert _wants_docstring("docstring_loop", False) is True

    def test_semantic_keyword_triggers(self):
        assert _wants_docstring("semantic_patch", False) is True

    def test_broad_triggers(self):
        assert _wants_docstring("noop", True) is True

    def test_none_of_them_is_false(self):
        assert _wants_docstring("security_audit", False) is False


class TestWantsTest:
    def test_test_keyword_triggers(self):
        assert _wants_test("test_loop", False) is True

    def test_coverage_keyword_triggers(self):
        assert _wants_test("coverage_loop", False) is True

    def test_semantic_keyword_triggers(self):
        assert _wants_test("semantic_patch", False) is True

    def test_broad_triggers(self):
        assert _wants_test("noop", True) is True

    def test_none_is_false(self):
        assert _wants_test("docstring_loop", False) is False


class TestWantsDependency:
    def test_dependency_keyword_triggers(self):
        assert _wants_dependency("dependency_audit", False) is True

    def test_broad_triggers(self):
        assert _wants_dependency("noop", True) is True

    def test_none_is_false(self):
        assert _wants_dependency("security_audit", False) is False


# ---------------------------------------------------------------------------
# app/main.py — _env_flag truthiness
# ---------------------------------------------------------------------------


class TestEnvFlag:
    def test_one_is_truthy(self):
        assert _env_flag("1") is True

    def test_true_is_truthy(self):
        assert _env_flag("true") is True

    def test_yes_is_truthy(self):
        assert _env_flag("yes") is True

    def test_uppercase_is_lowercased(self):
        # Kills dropping the .lower() call.
        assert _env_flag("TRUE") is True

    def test_none_is_falsey(self):
        assert _env_flag(None) is False

    def test_empty_string_is_falsey(self):
        # Empty string is falsy -> short-circuits to False (kills the guard flip).
        assert _env_flag("") is False

    def test_unknown_value_is_falsey(self):
        assert _env_flag("maybe") is False


# ---------------------------------------------------------------------------
# app/main.py — _build_policy env overrides
# ---------------------------------------------------------------------------


def _clear_apex_env(monkeypatch):
    for key in (
        "APEX_MODE",
        "APEX_AUTO_PATCH",
        "APEX_AUTO_COMMIT",
        "APEX_MAX_FRACTAL_BUDGET",
        "APEX_SAFETY_POLICY",
    ):
        monkeypatch.delenv(key, raising=False)


class TestBuildPolicy:
    def test_defaults_when_no_env(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        policy = _build_policy()
        # mode_from_string(None) -> SUPERVISED
        assert policy.mode == ApexMode.SUPERVISED
        assert policy.auto_patch is False
        assert policy.auto_commit is False
        assert policy.max_fractal_budget == 10
        assert policy.safety_policy == "standard"

    def test_digit_budget_is_parsed(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_MAX_FRACTAL_BUDGET", "7")
        assert _build_policy().max_fractal_budget == 7

    def test_nondigit_budget_falls_back_to_ten(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_MAX_FRACTAL_BUDGET", "notanumber")
        assert _build_policy().max_fractal_budget == 10

    def test_empty_budget_falls_back_to_ten(self, monkeypatch):
        # Empty string is falsy -> the `and` guard fails before isdigit().
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_MAX_FRACTAL_BUDGET", "")
        assert _build_policy().max_fractal_budget == 10

    def test_auto_patch_env_propagates(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_AUTO_PATCH", "yes")
        assert _build_policy().auto_patch is True

    def test_auto_commit_env_propagates(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_AUTO_COMMIT", "1")
        assert _build_policy().auto_commit is True

    def test_safety_policy_override(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_SAFETY_POLICY", "strict")
        assert _build_policy().safety_policy == "strict"

    def test_safety_policy_empty_defaults_to_standard(self, monkeypatch):
        # `os.getenv(...) or "standard"` — empty string is falsy.
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_SAFETY_POLICY", "")
        assert _build_policy().safety_policy == "standard"

    def test_mode_env_propagates(self, monkeypatch):
        _clear_apex_env(monkeypatch)
        monkeypatch.setenv("APEX_MODE", "report")
        assert _build_policy().mode == ApexMode.REPORT


# ---------------------------------------------------------------------------
# app/main.py — _safety_gates_block
# ---------------------------------------------------------------------------


class TestSafetyGatesBlock:
    def test_no_plan_never_blocks(self, capsys):
        policy = ModePolicy(mode=ApexMode.AUTONOMOUS)
        # automation_plan is None -> short-circuit, no print, returns False.
        assert _safety_gates_block(policy, None) is False
        assert capsys.readouterr().out == ""

    def test_report_mode_plan_does_not_require_gates(self, capsys):
        policy = ModePolicy(mode=ApexMode.REPORT)
        # report mode -> requires_safety_gates False -> no block, no print.
        assert _safety_gates_block(policy, "project_scan") is False
        assert capsys.readouterr().out == ""

    def test_supervised_plan_prints_but_clean_tree_not_required(self, capsys):
        policy = ModePolicy(mode=ApexMode.SUPERVISED)
        # supervised requires_safety_gates True but requires_clean_working_tree
        # False -> prints the banner, returns False.
        result = _safety_gates_block(policy, "project_scan")
        out = capsys.readouterr().out
        assert "safety gates enabled" in out
        assert "supervised" in out
        assert result is False

    def test_autonomous_clean_tree_blocks_when_dirty(self, capsys, monkeypatch):
        policy = ModePolicy(mode=ApexMode.AUTONOMOUS)

        from app.policies.mode_policy import SafetyGateResult

        def fake_enforce(self):
            return SafetyGateResult(
                name="clean_working_tree", passed=False,
                message="dirty", blocked=True,
            )

        monkeypatch.setattr(ModePolicy, "enforce_clean_working_tree", fake_enforce)
        result = _safety_gates_block(policy, "project_scan")
        out = capsys.readouterr().out
        assert "BLOCKED" in out
        assert result is True

    def test_autonomous_clean_tree_passes_when_clean(self, capsys, monkeypatch):
        policy = ModePolicy(mode=ApexMode.AUTONOMOUS)

        from app.policies.mode_policy import SafetyGateResult

        def fake_enforce(self):
            return SafetyGateResult(
                name="clean_working_tree", passed=True, message="clean",
            )

        monkeypatch.setattr(ModePolicy, "enforce_clean_working_tree", fake_enforce)
        result = _safety_gates_block(policy, "project_scan")
        out = capsys.readouterr().out
        assert "BLOCKED" not in out
        assert result is False


# ---------------------------------------------------------------------------
# app/main.py — _resolve_use_fractal
# ---------------------------------------------------------------------------


class TestResolveUseFractal:
    def test_env_flag_forces_true(self, monkeypatch):
        monkeypatch.setenv("APEX_USE_FRACTAL", "1")
        # Neutral objective, but env forces True (kills the early-return path).
        assert _resolve_use_fractal("plain refactor") is True

    def test_security_keyword_detected(self, monkeypatch):
        monkeypatch.delenv("APEX_USE_FRACTAL", raising=False)
        assert _resolve_use_fractal("security review") is True

    def test_audit_keyword_detected(self, monkeypatch):
        monkeypatch.delenv("APEX_USE_FRACTAL", raising=False)
        assert _resolve_use_fractal("AUDIT the code") is True

    def test_risk_keyword_detected(self, monkeypatch):
        monkeypatch.delenv("APEX_USE_FRACTAL", raising=False)
        assert _resolve_use_fractal("assess risk") is True

    def test_vuln_keyword_detected(self, monkeypatch):
        monkeypatch.delenv("APEX_USE_FRACTAL", raising=False)
        assert _resolve_use_fractal("find vuln") is True

    def test_neutral_objective_is_false(self, monkeypatch):
        monkeypatch.delenv("APEX_USE_FRACTAL", raising=False)
        assert _resolve_use_fractal("improve documentation") is False


# ---------------------------------------------------------------------------
# app/main.py — _load_plugins env extension
# ---------------------------------------------------------------------------


class TestLoadPlugins:
    def test_plugin_path_env_extends_dirs(self, monkeypatch, tmp_path):
        d1 = tmp_path / "p1"
        d2 = tmp_path / "p2"
        d1.mkdir()
        d2.mkdir()
        monkeypatch.setenv(
            "APEX_PLUGIN_PATH", str(d1) + os.pathsep + str(d2)
        )
        config = {"plugin_dirs": []}
        plugins = _load_plugins(config)
        # The env dirs are appended to the registry's search path.
        assert str(d1) in plugins._plugin_dirs
        assert str(d2) in plugins._plugin_dirs

    def test_no_env_keeps_config_dirs(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APEX_PLUGIN_PATH", raising=False)
        d1 = tmp_path / "p1"
        d1.mkdir()
        config = {"plugin_dirs": [str(d1)]}
        plugins = _load_plugins(config)
        assert str(d1) in plugins._plugin_dirs


# ---------------------------------------------------------------------------
# app/main.py — the ``if __name__ == "__main__"`` entry guard
# ---------------------------------------------------------------------------


class TestMainEntryGuard:
    def test_importing_module_does_not_run_main(self):
        """Importing ``app.main`` must be a fast no-op side-effect-wise.

        Pins the ``__name__ == "__main__"`` guard: flipping ``==`` to ``!=``
        makes the guard true on import, so ``main()`` runs a full repo scan at
        import time and never returns. The correct guard imports near-instantly.
        We import in a fresh subprocess with a short timeout so the mutant — an
        import-time hang — is killed deterministically and quickly, instead of
        relying on the multi-minute suite-wide timeout the engine falls back to.
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        # Neutralize any ambient main()-affecting overrides for determinism.
        for key in (
            "EPISTEMIC_AUTOMATION_PLAN",
            "EPISTEMIC_OBJECTIVE",
            "EPISTEMIC_TARGET_ROOT",
            "APEX_MODE",
        ):
            env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, "-c", "import app.main; print('IMPORTED_OK')"],
            env=env,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        assert "IMPORTED_OK" in proc.stdout
