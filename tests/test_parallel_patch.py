from pathlib import Path

from app.execution.parallel_patch import ParallelSemanticPatcher
from app.execution.semantic.result import SemanticPatchResult


def test_parallel_patcher_runs_multiple_plans(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    patcher = ParallelSemanticPatcher(max_workers=2)
    result = patcher.apply_batch(
        project_root=tmp_path,
        patch_plans=[
            {
                "task_id": "task-1",
                "title": "Add docstring to hello",
                "target_files": ["app/main.py"],
                "change_strategy": ["Add docstring."],
            },
            {
                "task_id": "task-2",
                "title": "Add type annotations",
                "target_files": ["app/main.py"],
                "change_strategy": ["Add type annotations."],
            },
        ],
    )

    assert result.completed == 2
    assert len(result.results) == 2
    assert result.failed == 0
    assert all(isinstance(r, SemanticPatchResult) for r in result.results)


def test_parallel_patcher_handles_empty_plans(tmp_path: Path):
    patcher = ParallelSemanticPatcher()
    result = patcher.apply_batch(project_root=tmp_path, patch_plans=[])
    assert result.completed == 0
    assert result.failed == 0
