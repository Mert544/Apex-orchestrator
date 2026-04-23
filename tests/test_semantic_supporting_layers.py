from pathlib import Path

from app.execution.context_extractor import ContextExtractor
from app.execution.edit_strategy import EditStrategy
from app.execution.semantic_patch_generator import SemanticPatchGenerator
from app.execution.target_selector import TargetSelector


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_demo_project(root: Path) -> None:
    _write(root / "app" / "services" / "order_service.py", "def checkout(total: float) -> float:\n    return total\n")
    _write(root / "tests" / "test_order_service.py", "from app.services.order_service import checkout\n\n\ndef test_checkout():\n    assert checkout(10.0) == 10.0\n")
    _write(root / "README.md", "demo project\n")


def test_target_selector_prefers_existing_python_file(tmp_path: Path):
    _build_demo_project(tmp_path)
    result = TargetSelector().select(
        project_root=tmp_path,
        patch_plan={"target_files": ["app/services/order_service.py", "README.md"]},
        task={"title": "Add input guard to checkout"},
        project_profile={"sensitive_paths": []},
    ).to_dict()

    assert result["targets"]
    assert result["targets"][0]["path"] == "app/services/order_service.py"
    assert result["targets"][0]["score"] >= result["targets"][1]["score"]


def test_context_extractor_finds_symbols_and_related_tests(tmp_path: Path):
    _build_demo_project(tmp_path)
    result = ContextExtractor().extract(tmp_path, ["app/services/order_service.py"]).to_dict()

    assert result["contexts"]
    context = result["contexts"][0]
    assert context["target_file"] == "app/services/order_service.py"
    assert "checkout" in context["surrounding_symbols"]
    assert "tests/test_order_service.py" in context["related_tests"]


def test_edit_strategy_picks_guard_clause_for_validation_task():
    result = EditStrategy().choose(
        title="Harden input validation for checkout",
        patch_plan={"change_strategy": ["Add guard clause for invalid input."]},
        related_tests=["tests/test_order_service.py"],
    ).to_dict()

    assert result["strategy"] == "add_guard_clause"
    assert result["confidence"] >= 0.7


def test_semantic_patch_generator_emits_selection_context_and_strategy(tmp_path: Path):
    _build_demo_project(tmp_path)
    result = SemanticPatchGenerator().generate(
        project_root=tmp_path,
        patch_plan={
            "task_id": "task-1",
            "title": "Add guard clause to checkout",
            "target_files": ["app/services/order_service.py"],
            "change_strategy": ["Add guard clause for invalid input."],
        },
        task={"id": "task-1", "title": "Add guard clause to checkout", "branch": "x.a"},
        project_profile={"sensitive_paths": []},
    ).to_dict()

    assert result["selected_targets"]
    assert result["extracted_contexts"]
    assert result["chosen_strategy"]["strategy"] == "add_guard_clause"
    assert result["patch_requests"]
