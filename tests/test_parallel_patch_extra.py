from app.execution.parallel_patch import ParallelSemanticPatcher


def test_parallel_patcher_with_invalid_plan(tmp_path):
    patcher = ParallelSemanticPatcher(max_workers=1)
    result = patcher.apply_batch(
        project_root=tmp_path,
        patch_plans=[{"task_id": "bad", "title": ""}],
    )
    assert result.completed == 1
    assert len(result.results) == 1


def test_parallel_patcher_result_has_metadata(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    patcher = ParallelSemanticPatcher(max_workers=1)
    result = patcher.apply_batch(
        project_root=tmp_path,
        patch_plans=[
            {
                "task_id": "task-1",
                "title": "Add docstring",
                "target_files": ["app/main.py"],
                "change_strategy": ["Add docstring."],
            },
        ],
    )

    assert result.results[0].selected_targets
    assert result.results[0].chosen_strategy
