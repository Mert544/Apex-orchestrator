from __future__ import annotations

from app.automation.models import AutomationContext
from app.skills.safety.check_patch_scope import CheckPatchScopeSkill
from app.skills.safety.detect_sensitive_edit import DetectSensitiveEditSkill
from app.skills.safety.enhanced_safety_governor import EnhancedSafetyGovernor

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
    governor = EnhancedSafetyGovernor(context.config)
    file_diffs = governor.compute_line_diffs(target_root, changed_files)
    result = governor.evaluate(changed_files, file_diffs)
    result_dict = result.to_dict()
    context.state["enhanced_safety"] = result_dict
    # If policy requires human review, mark verification as failed
    if result.requires_human_review:
        context.state["verification"] = context.state.get("verification", {})
        context.state["verification"]["enhanced_safety"] = result_dict
        context.state["verification"]["ok"] = False
    return result_dict
