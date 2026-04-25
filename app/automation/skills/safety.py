from __future__ import annotations

from app.automation.models import AutomationContext
from app.policies.safety_gates import SafetyGates, SafetyGatesReport
from app.skills.safety.check_patch_scope import CheckPatchScopeSkill
from app.skills.safety.detect_sensitive_edit import DetectSensitiveEditSkill

from ._context import _target_root


def check_patch_scope_skill(context: AutomationContext):
    changed_files = context.state.get("changed_files", [])
    result = CheckPatchScopeSkill().run(changed_files=changed_files)
    result_dict = {
        "ok": result.ok,
        "changed_file_count": result.changed_file_count,
        "max_allowed_files": result.max_allowed_files,
        "touched_sensitive_paths": result.touched_sensitive_paths,
        "reasons": result.reasons,
    }
    context.state["patch_scope"] = result_dict
    return result_dict


def detect_sensitive_edit_skill(context: AutomationContext):
    changed_files = context.state.get("changed_files", [])
    result = DetectSensitiveEditSkill().run(changed_files=changed_files)
    result_dict = {
        "ok": result.ok,
        "touched_sensitive_paths": result.touched_sensitive_paths,
        "detected_hints": result.detected_hints,
    }
    context.state["sensitive_edit"] = result_dict
    return result_dict


def enhanced_safety_check_skill(context: AutomationContext):
    target_root = _target_root(context)
    changed_files = context.state.get("changed_files", [])
    old_code = context.state.get("old_code", "")
    new_code = context.state.get("new_code", "")

    max_files = 5
    if context.config:
        safety_cfg = context.config.get("safety", {})
        max_files = int(safety_cfg.get("max_changed_files", 5))

    gates = SafetyGates(project_root=target_root, max_changed_files=max_files)
    report: SafetyGatesReport = gates.check_all(
        changed_files=changed_files,
        old_code=old_code,
        new_code=new_code,
        skip_test=False,
    )

    result_dict = report.to_dict()
    context.state["safety_gates"] = result_dict

    if report.blocked:
        context.state["verification"] = context.state.get("verification", {})
        context.state["verification"]["safety_gates"] = result_dict
        context.state["verification"]["ok"] = False

    return result_dict
