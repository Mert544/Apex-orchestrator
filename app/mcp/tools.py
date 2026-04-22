from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def apex_project_profile(project_root: str = ".") -> str:
    """Scan a project and return its structural profile.

    Args:
        project_root: Absolute or relative path to the project directory.
    """
    from app.tools.project_profile import ProjectProfiler

    profiler = ProjectProfiler(project_root)
    profile = profiler.profile()
    return json.dumps(
        {
            "root": profile.root,
            "total_files": profile.total_files,
            "entrypoints": profile.entrypoints,
            "dependency_hubs": profile.dependency_hubs,
            "critical_untested_modules": profile.critical_untested_modules,
            "sensitive_paths": profile.sensitive_paths,
            "config_files": profile.config_files,
            "ci_files": profile.ci_files,
        },
        indent=2,
    )


def apex_generate_patch(
    project_root: str = ".",
    target_files: list[str] | None = None,
    title: str = "semantic patch",
    task_id: str = "mcp-task-1",
    change_strategy: list[str] | None = None,
    rename: dict[str, str] | None = None,
    extract: dict[str, Any] | None = None,
) -> str:
    """Generate a semantic patch for the given target files.

    Args:
        project_root: Path to the project.
        target_files: List of relative file paths to modify.
        title: Description of the change.
        task_id: Unique task identifier.
        change_strategy: Strategy hints (e.g. ["rename variable"]).
        rename: Rename configuration dict with keys old_name, new_name, target_function.
        extract: Extract method configuration dict with keys start_line, end_line,
                 new_function_name, target_function, parameters.
    """
    from app.execution.semantic_patch_generator import SemanticPatchGenerator

    patch_plan: dict[str, Any] = {
        "target_files": target_files or [],
        "title": title,
        "task_id": task_id,
        "change_strategy": change_strategy or [],
    }
    if rename:
        patch_plan["rename"] = rename
    if extract:
        patch_plan["extract"] = extract

    result = SemanticPatchGenerator().generate(project_root=project_root, patch_plan=patch_plan)
    return json.dumps(result.to_dict(), indent=2)


def apex_apply_patch(project_root: str = ".", patch_requests: list[dict[str, Any]] | None = None) -> str:
    """Apply a list of patch requests to the project.

    Args:
        project_root: Path to the project.
        patch_requests: List of patch dicts with keys path, new_content, expected_old_content.
    """
    from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

    patches = [
        FilePatch(
            path=item["path"],
            new_content=item["new_content"],
            expected_old_content=item.get("expected_old_content"),
        )
        for item in (patch_requests or [])
    ]
    result = ApplyPatchSkill().run(project_root, patches)
    return json.dumps(
        {
            "ok": result.ok,
            "changed_files": result.changed_files,
            "skipped_files": result.skipped_files,
            "error": result.error,
        },
        indent=2,
    )


def apex_run_tests(project_root: str = ".") -> str:
    """Run the detected test commands for the project.

    Args:
        project_root: Path to the project.
    """
    from app.skills.execution.run_tests import RunTestsSkill

    result = RunTestsSkill().run(project_root)
    return json.dumps(
        {
            "ok": result.ok,
            "commands": result.commands,
            "results": result.results,
        },
        indent=2,
        default=str,
    )


def build_apex_tools() -> dict[str, Any]:
    """Return a mapping of tool names to callable tool functions with JSON schemas."""
    # Attach lightweight JSON schemas for MCP discovery
    apex_project_profile.input_schema = {  # type: ignore[attr-defined]
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Path to the project directory to scan.",
                "default": ".",
            },
        },
    }
    apex_generate_patch.input_schema = {  # type: ignore[attr-defined]
        "type": "object",
        "properties": {
            "project_root": {"type": "string", "default": "."},
            "target_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relative paths of files to modify.",
            },
            "title": {"type": "string", "default": "semantic patch"},
            "task_id": {"type": "string", "default": "mcp-task-1"},
            "change_strategy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Strategy hints such as ['rename variable', 'extract method'].",
            },
            "rename": {
                "type": "object",
                "description": "Rename config with old_name, new_name, target_function.",
            },
            "extract": {
                "type": "object",
                "description": "Extract config with start_line, end_line, new_function_name, target_function, parameters.",
            },
        },
        "required": ["target_files"],
    }
    apex_apply_patch.input_schema = {  # type: ignore[attr-defined]
        "type": "object",
        "properties": {
            "project_root": {"type": "string", "default": "."},
            "patch_requests": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Patch dicts with path, new_content, expected_old_content.",
            },
        },
        "required": ["patch_requests"],
    }
    apex_run_tests.input_schema = {  # type: ignore[attr-defined]
        "type": "object",
        "properties": {
            "project_root": {"type": "string", "default": "."},
        },
    }
    return {
        "apex_project_profile": apex_project_profile,
        "apex_generate_patch": apex_generate_patch,
        "apex_apply_patch": apex_apply_patch,
        "apex_run_tests": apex_run_tests,
    }
