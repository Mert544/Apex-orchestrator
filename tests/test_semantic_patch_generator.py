from pathlib import Path

from app.execution.semantic_patch_generator import SemanticPatchGenerator


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_add_docstring_transform(tmp_path: Path):
    _write(tmp_path / "app" / "math.py", "def add(a, b):\n    return a + b\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/math.py"], "title": "Add docstrings", "task_id": "t-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "add_docstring"
    assert len(result.patch_requests) == 1
    pr = result.patch_requests[0]
    assert pr["path"] == "app/math.py"
    assert '"""Add docstrings."""' in pr["new_content"]
    assert pr["expected_old_content"] == "def add(a, b):\n    return a + b\n"
    assert result.estimated_tokens > 0
    assert result.mode == "semantic"


def test_add_type_annotations_transform(tmp_path: Path):
    _write(tmp_path / "app" / "math.py", "def add(a, b):\n    return a + b\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/math.py"], "title": "Add type annotations", "task_id": "t-2"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "add_type_annotations"
    pr = result.patch_requests[0]
    assert "-> None:" in pr["new_content"]
    assert pr["expected_old_content"] is not None


def test_add_guard_clause_transform(tmp_path: Path):
    _write(tmp_path / "app" / "math.py", "def add(a, b):\n    return a + b\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/math.py"], "title": "Add input validation guard", "task_id": "t-3"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "add_guard_clause"
    pr = result.patch_requests[0]
    assert "if not a:" in pr["new_content"]
    assert "raise ValueError" in pr["new_content"]


def test_create_test_stub(tmp_path: Path):
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["tests/test_orders.py"], "title": "Close test gap", "task_id": "t-4"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "create_test_stub"
    pr = result.patch_requests[0]
    assert pr["path"] == "tests/test_orders.py"
    assert "def test_orders_exists():" in pr["new_content"]
    assert pr["expected_old_content"] is None


def test_repair_test_assertion_transform(tmp_path: Path):
    _write(tmp_path / "tests" / "test_math.py", "def test_add():\n    assert 1 + 1 == 2\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["tests/test_math.py"], "title": "Fix tests", "task_id": "t-5"}
    repair_context = {"failure_type": "test_failure"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan, repair_context=repair_context)

    assert result.transform_type == "repair_test_assertion"
    pr = result.patch_requests[0]
    assert 'Assertion failed: 1 + 1 == 2' in pr["new_content"]


def test_fallback_when_no_target_files(tmp_path: Path):
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": [], "title": "Refactor everything", "task_id": "t-6"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "draft_fallback"
    assert result.mode == "draft"
    assert len(result.rationale) >= 1


def test_does_not_duplicate_existing_docstring(tmp_path: Path):
    source = 'def add(a, b):\n    """Already documented."""\n    return a + b\n'
    _write(tmp_path / "app" / "math.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/math.py"], "title": "Add docstrings", "task_id": "t-7"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    # Should fall back to draft because no function without docstring found
    assert result.transform_type == "draft_fallback"


def test_expected_old_content_for_safety(tmp_path: Path):
    _write(tmp_path / "app" / "math.py", "def add(a, b):\n    return a + b\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/math.py"], "title": "Add docstrings", "task_id": "t-8"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    pr = result.patch_requests[0]
    assert pr["expected_old_content"] is not None
    assert pr["expected_old_content"] == "def add(a, b):\n    return a + b\n"


def test_scope_reduction_in_repair_mode(tmp_path: Path):
    _write(tmp_path / "app" / "a.py", "def a():\n    pass\n")
    _write(tmp_path / "app" / "b.py", "def b():\n    pass\n")
    _write(tmp_path / "app" / "c.py", "def c():\n    pass\n")
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/a.py", "app/b.py", "app/c.py"],
        "title": "Add docstrings",
        "task_id": "t-9",
    }
    repair_context = {"failure_type": "patch_scope_failure"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan, repair_context=repair_context)

    # Should only process first 3 (which is all of them here), but the logic is:
    # for rel_path in target_files (already limited to [:3] in repair mode)
    # It should still work and add docstring to first file
    assert result.transform_type == "add_docstring"
    assert result.patch_requests[0]["path"] == "app/a.py"


def test_rename_variable_transform(tmp_path: Path):
    source = (
        "def calculate(x, y):\n"
        "    total = x + y\n"
        "    result = total * 2\n"
        "    return result\n"
    )
    _write(tmp_path / "app" / "math.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/math.py"],
        "title": "Rename variable for clarity",
        "task_id": "t-10",
        "change_strategy": ["rename variable"],
        "rename": {"old_name": "total", "new_name": "subtotal", "target_function": "calculate"},
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "rename_variable"
    pr = result.patch_requests[0]
    assert "subtotal = x + y" in pr["new_content"]
    assert "result = subtotal * 2" in pr["new_content"]
    assert "    total =" not in pr["new_content"]  # ensure old name removed (not just substring)
    assert pr["expected_old_content"] == source


def test_rename_variable_function_scope_only(tmp_path: Path):
    source = (
        "def outer():\n"
        "    value = 1\n"
        "    def inner():\n"
        "        value = 2\n"
        "        return value\n"
        "    return value + inner()\n"
    )
    _write(tmp_path / "app" / "scope.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/scope.py"],
        "title": "Rename variable",
        "task_id": "t-11",
        "change_strategy": ["rename variable"],
        "rename": {"old_name": "value", "new_name": "count", "target_function": "outer"},
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "rename_variable"
    pr = result.patch_requests[0]
    # outer scope value renamed; inner scope value stays the same (shadowed)
    assert "count = 1" in pr["new_content"]
    assert "value = 2" in pr["new_content"]  # inner shadow preserved


def test_extract_method_transform(tmp_path: Path):
    source = (
        "def process(data):\n"
        "    cleaned = data.strip()\n"
        "    validated = cleaned.upper()\n"
        "    return validated\n"
    )
    _write(tmp_path / "app" / "proc.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/proc.py"],
        "title": "Extract validation logic",
        "task_id": "t-12",
        "change_strategy": ["extract method"],
        "extract": {
            "start_line": 3,
            "end_line": 3,
            "new_function_name": "_validate",
            "target_function": "process",
            "parameters": ["cleaned"],
        },
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "extract_method"
    pr = result.patch_requests[0]
    assert "def _validate(cleaned):" in pr["new_content"] or "def _validate(" in pr["new_content"]
    assert "_validate(" in pr["new_content"]
    assert pr["expected_old_content"] == source


def test_extract_method_multi_line_block(tmp_path: Path):
    source = (
        "def analyze(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item\n"
        "    avg = total / len(items)\n"
        "    return avg\n"
    )
    _write(tmp_path / "app" / "stats.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/stats.py"],
        "title": "Extract summation",
        "task_id": "t-13",
        "change_strategy": ["extract method"],
        "extract": {
            "start_line": 3,
            "end_line": 4,
            "new_function_name": "_sum_items",
            "target_function": "analyze",
            "parameters": [],
        },
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "extract_method"
    pr = result.patch_requests[0]
    assert "def _sum_items(" in pr["new_content"]
    assert "_sum_items(" in pr["new_content"]
    assert pr["expected_old_content"] == source


def test_inline_variable_transform(tmp_path: Path):
    source = (
        "def compute(x):\n"
        "    y = x + 1\n"
        "    return y\n"
    )
    _write(tmp_path / "app" / "calc.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/calc.py"],
        "title": "Inline simple variable",
        "task_id": "t-14",
        "change_strategy": ["inline variable"],
        "inline": {"var_name": "y", "target_function": "compute"},
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "inline_variable"
    pr = result.patch_requests[0]
    assert "return x + 1" in pr["new_content"]
    assert "y = x + 1" not in pr["new_content"]
    assert pr["expected_old_content"] == source


def test_organize_imports_transform(tmp_path: Path):
    source = (
        "import os\n"
        "import sys\n"
        "import json\n"
        "\n"
        "def load():\n"
        "    return json.loads('{}')\n"
    )
    _write(tmp_path / "app" / "loader.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/loader.py"],
        "title": "Clean up unused imports",
        "task_id": "t-15",
        "change_strategy": ["organize imports"],
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "organize_imports"
    pr = result.patch_requests[0]
    assert "import json" in pr["new_content"]
    assert "import os" not in pr["new_content"]
    assert "import sys" not in pr["new_content"]
    assert pr["expected_old_content"] == source


def test_move_class_transform(tmp_path: Path):
    source = (
        "class OldService:\n"
        "    def work(self):\n"
        "        return 'done'\n"
        "\n"
        "def main():\n"
        "    s = OldService()\n"
        "    return s.work()\n"
    )
    _write(tmp_path / "app" / "main.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/main.py"],
        "title": "Move class to separate module",
        "task_id": "t-16",
        "change_strategy": ["move class"],
        "move": {"class_name": "OldService", "new_module": "app/service.py"},
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "move_class"
    assert len(result.patch_requests) == 2
    # Original file should have import instead of class
    orig_pr = result.patch_requests[0]
    assert "from app.service import OldService" in orig_pr["new_content"]
    assert "class OldService:" not in orig_pr["new_content"]
    # New module should contain the class
    new_pr = result.patch_requests[1]
    assert new_pr["path"] == "app/service.py"
    assert "class OldService:" in new_pr["new_content"]
    assert new_pr["expected_old_content"] is None


def test_extract_class_transform(tmp_path: Path):
    source = (
        "class BigClass:\n"
        "    def method_a(self):\n"
        "        return 'a'\n"
        "    def method_b(self):\n"
        "        return 'b'\n"
        "    def method_c(self):\n"
        "        return 'c'\n"
    )
    _write(tmp_path / "app" / "big.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["app/big.py"],
        "title": "Extract helper class",
        "task_id": "t-17",
        "change_strategy": ["extract class"],
        "extract_class": {
            "methods": ["method_a", "method_b"],
            "new_class_name": "HelperClass",
            "base_class": None,
        },
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "extract_class"
    pr = result.patch_requests[0]
    assert "class HelperClass:" in pr["new_content"]
    assert "class BigClass:" in pr["new_content"]
    assert "def method_a(self):" in pr["new_content"]
    assert "def method_b(self):" in pr["new_content"]
    assert pr["expected_old_content"] == source
