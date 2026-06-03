from __future__ import annotations

import ast

from app.execution.semantic.transforms import (
    extract_method,
    inline_variable,
    move_class,
    rename_variable,
)


def _valid_python(source: str) -> None:
    """Assert that the produced source parses as valid Python."""
    ast.parse(source)


# --------------------------------------------------------------------------
# inline_variable
# --------------------------------------------------------------------------


def test_inline_variable_happy_path():
    source = "def compute(x):\n    y = x + 1\n    return y\n"
    result = inline_variable.apply("app/calc.py", source, "y", "compute")

    assert result is not None
    assert result.transform_type == "inline_variable"
    pr = result.patch_requests[0]
    assert "return x + 1" in pr["new_content"]
    assert "y = x + 1" not in pr["new_content"]
    assert pr["expected_old_content"] == source
    _valid_python(pr["new_content"])


def test_inline_variable_missing_args_returns_none():
    source = "def compute(x):\n    y = x + 1\n    return y\n"
    assert inline_variable.apply("a.py", source, "", "compute") is None
    assert inline_variable.apply("a.py", source, "y", "") is None


def test_inline_variable_syntax_error_returns_none():
    assert inline_variable.apply("a.py", "def broken(:\n", "y", "broken") is None


def test_inline_variable_no_matching_assignment_returns_none():
    # 'y' is never assigned in the target function -> no change.
    source = "def compute(x):\n    return x\n"
    assert inline_variable.apply("a.py", source, "y", "compute") is None


def test_inline_variable_non_inlinable_value_returns_none():
    # Assignment value is a Call, which is not Name/Constant/BinOp.
    source = "def compute(x):\n    y = foo(x)\n    return y\n"
    assert inline_variable.apply("a.py", source, "y", "compute") is None


def test_inline_variable_target_function_absent_returns_none():
    source = "def other(x):\n    y = x + 1\n    return y\n"
    assert inline_variable.apply("a.py", source, "y", "compute") is None


def test_inline_variable_async_function():
    source = "async def compute(x):\n    y = x + 1\n    return y\n"
    result = inline_variable.apply("a.py", source, "y", "compute")

    assert result is not None
    pr = result.patch_requests[0]
    assert "return x + 1" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_inline_variable_preserves_trailing_newline_absence():
    # No trailing newline in source; output should also lack one.
    source = "def compute(x):\n    y = x + 1\n    return y"
    result = inline_variable.apply("a.py", source, "y", "compute")

    assert result is not None
    assert not result.patch_requests[0]["new_content"].endswith("\n")


# --------------------------------------------------------------------------
# rename_variable
# --------------------------------------------------------------------------


def test_rename_variable_happy_path():
    source = (
        "def calculate(x, y):\n"
        "    total = x + y\n"
        "    return total\n"
    )
    result = rename_variable.apply("app/m.py", source, "total", "subtotal", "calculate")

    assert result is not None
    assert result.transform_type == "rename_variable"
    pr = result.patch_requests[0]
    assert "subtotal = x + y" in pr["new_content"]
    assert "return subtotal" in pr["new_content"]
    # Old name fully replaced (guard against substring false positives).
    assert "    total =" not in pr["new_content"]
    assert "return total\n" not in pr["new_content"]
    assert pr["expected_old_content"] == source
    _valid_python(pr["new_content"])


def test_rename_variable_renames_argument():
    source = "def calculate(total):\n    return total + 1\n"
    result = rename_variable.apply("a.py", source, "total", "amount", "calculate")

    assert result is not None
    pr = result.patch_requests[0]
    assert "def calculate(amount):" in pr["new_content"]
    assert "return amount + 1" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_rename_variable_missing_args_returns_none():
    source = "def calculate(x):\n    total = x\n    return total\n"
    assert rename_variable.apply("a.py", source, "", "new", "calculate") is None
    assert rename_variable.apply("a.py", source, "total", "", "calculate") is None
    assert rename_variable.apply("a.py", source, "total", "new", "") is None


def test_rename_variable_syntax_error_returns_none():
    assert rename_variable.apply("a.py", "def broken(:\n", "a", "b", "broken") is None


def test_rename_variable_no_match_returns_none():
    # 'missing' name does not appear in the target -> no change.
    source = "def calculate(x):\n    total = x\n    return total\n"
    assert rename_variable.apply("a.py", source, "missing", "new", "calculate") is None


def test_rename_variable_only_in_target_scope():
    source = (
        "def outer():\n"
        "    value = 1\n"
        "    def inner():\n"
        "        value = 2\n"
        "        return value\n"
        "    return value + inner()\n"
    )
    result = rename_variable.apply("a.py", source, "value", "count", "outer")

    assert result is not None
    pr = result.patch_requests[0]
    assert "count = 1" in pr["new_content"]
    # Nested function body untouched.
    assert "value = 2" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_rename_variable_ignores_other_top_level_functions():
    # A second top-level function must be visited but left unchanged.
    source = (
        "def helper(total):\n"
        "    return total\n"
        "def calculate(x):\n"
        "    total = x\n"
        "    return total\n"
    )
    result = rename_variable.apply("a.py", source, "total", "amount", "calculate")

    assert result is not None
    pr = result.patch_requests[0]
    # helper's 'total' untouched; calculate's renamed.
    assert "def helper(total):" in pr["new_content"]
    assert "amount = x" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_rename_variable_async_function():
    source = "async def calculate(total):\n    return total + 1\n"
    result = rename_variable.apply("a.py", source, "total", "amount", "calculate")

    assert result is not None
    assert "amount" in result.patch_requests[0]["new_content"]
    _valid_python(result.patch_requests[0]["new_content"])


# --------------------------------------------------------------------------
# move_class
# --------------------------------------------------------------------------


def test_move_class_happy_path():
    source = (
        "class OldService:\n"
        "    def work(self):\n"
        "        return 'done'\n"
        "\n"
        "def main():\n"
        "    return OldService().work()\n"
    )
    result = move_class.apply("app/main.py", source, "OldService", "app/service.py")

    assert result is not None
    assert result.transform_type == "move_class"
    assert len(result.patch_requests) == 2
    orig_pr, new_pr = result.patch_requests
    assert "from app.service import OldService" in orig_pr["new_content"]
    assert "class OldService:" not in orig_pr["new_content"]
    assert new_pr["path"] == "app/service.py"
    assert "class OldService:" in new_pr["new_content"]
    assert new_pr["expected_old_content"] is None
    _valid_python(orig_pr["new_content"])
    _valid_python(new_pr["new_content"])


def test_move_class_missing_args_returns_none():
    source = "class C:\n    x = 1\n"
    assert move_class.apply("a.py", source, "", "app/c.py") is None
    assert move_class.apply("a.py", source, "C", "") is None


def test_move_class_syntax_error_returns_none():
    assert move_class.apply("a.py", "class broken(:\n", "broken", "app/b.py") is None


def test_move_class_class_not_found_returns_none():
    source = "class Other:\n    x = 1\n"
    assert move_class.apply("a.py", source, "Missing", "app/m.py") is None


def test_move_class_adds_trailing_newline_to_new_module():
    # Class is the last thing and source has no trailing newline.
    source = "class C:\n    x = 1"
    result = move_class.apply("a.py", source, "C", "app/c.py")

    assert result is not None
    assert result.patch_requests[1]["new_content"].endswith("\n")


def test_move_class_module_path_suffix_strip_is_exact():
    # Regression: module names ending in chars from {'.','p','y'} must not be
    # mangled by a naive rstrip('.py'). 'happy.py' -> 'app.happy', not 'app.ha'.
    source = "class C:\n    x = 1\n"
    result = move_class.apply("a.py", source, "C", "app/happy.py")

    assert result is not None
    assert "from app.happy import C" in result.patch_requests[0]["new_content"]


def test_move_class_handles_backslash_path():
    source = "class C:\n    x = 1\n"
    result = move_class.apply("a.py", source, "C", "pkg\\sub\\mod.py")

    assert result is not None
    assert "from pkg.sub.mod import C" in result.patch_requests[0]["new_content"]


# --------------------------------------------------------------------------
# extract_method
# --------------------------------------------------------------------------


def test_extract_method_happy_path_with_return_var():
    source = (
        "def process(data):\n"
        "    cleaned = data.strip()\n"
        "    validated = cleaned.upper()\n"
        "    return validated\n"
    )
    result = extract_method.apply(
        "app/proc.py", source, 3, 3, "_validate", "process", ["cleaned"]
    )

    assert result is not None
    assert result.transform_type == "extract_method"
    pr = result.patch_requests[0]
    assert "def _validate(cleaned):" in pr["new_content"]
    assert "validated = _validate(cleaned)" in pr["new_content"]
    assert "return validated" in pr["new_content"]
    assert pr["expected_old_content"] == source
    _valid_python(pr["new_content"])


def test_extract_method_no_return_var_no_params():
    source = (
        "def run():\n"
        "    print('start')\n"
        "    print('work')\n"
        "    print('end')\n"
    )
    result = extract_method.apply("a.py", source, 2, 3, "_steps", "run", [])

    assert result is not None
    pr = result.patch_requests[0]
    assert "def _steps():" in pr["new_content"]
    # No assignment in the block -> plain call, no return.
    assert "_steps()" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_extract_method_invalid_line_range_returns_none():
    source = "def f():\n    return 1\n"
    assert extract_method.apply("a.py", source, 0, 1, "g", "f", []) is None
    assert extract_method.apply("a.py", source, 2, 1, "g", "f", []) is None


def test_extract_method_missing_names_returns_none():
    source = "def f():\n    return 1\n"
    assert extract_method.apply("a.py", source, 1, 2, "", "f", []) is None
    assert extract_method.apply("a.py", source, 1, 2, "g", "", []) is None


def test_extract_method_end_line_beyond_source_returns_none():
    source = "def f():\n    return 1\n"
    assert extract_method.apply("a.py", source, 1, 99, "g", "f", []) is None


def test_extract_method_syntax_error_returns_none():
    # end_line within range but unparseable source.
    assert extract_method.apply("a.py", "def broken(:\n    pass\n", 1, 2, "g", "broken", []) is None


def test_extract_method_target_function_not_found_returns_none():
    source = "def other():\n    x = 1\n    return x\n"
    assert extract_method.apply("a.py", source, 2, 2, "g", "missing", []) is None


def test_extract_method_blank_only_block_returns_none():
    # Block consists solely of a blank line -> no indents -> None.
    source = "def f():\n\n    return 1\n"
    assert extract_method.apply("a.py", source, 2, 2, "g", "f", []) is None


def test_extract_method_block_with_internal_blank_line():
    source = (
        "def f(x):\n"
        "    a = x\n"
        "\n"
        "    b = a + 1\n"
        "    return b\n"
    )
    result = extract_method.apply("a.py", source, 2, 4, "_g", "f", ["x"])

    assert result is not None
    pr = result.patch_requests[0]
    assert "def _g(x):" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_extract_method_last_line_without_trailing_newline():
    # Extracting the final line of a file that lacks a trailing newline.
    source = "def f(x):\n    a = x\n    print(a)"
    result = extract_method.apply("a.py", source, 3, 3, "_g", "f", ["a"])

    assert result is not None
    pr = result.patch_requests[0]
    assert "def _g(a):" in pr["new_content"]
    assert "    print(a)" in pr["new_content"]
    _valid_python(pr["new_content"])


def test_extract_method_unparseable_block_skips_return_var():
    # An 'else:' line alone is not parseable as a standalone block, so the
    # return-variable detection is skipped without raising.
    source = (
        "def f(x):\n"
        "    if x:\n"
        "        y = 1\n"
        "    else:\n"
        "        y = 2\n"
        "    return y\n"
    )
    result = extract_method.apply("a.py", source, 4, 4, "_g", "f", [])

    assert result is not None
    # No return var was inferred -> plain call form.
    assert "_g()" in result.patch_requests[0]["new_content"]


def test_extract_method_async_target():
    source = (
        "async def process(data):\n"
        "    cleaned = data.strip()\n"
        "    return cleaned\n"
    )
    result = extract_method.apply("a.py", source, 2, 2, "_clean", "process", ["data"])

    assert result is not None
    assert "def _clean(data):" in result.patch_requests[0]["new_content"]
    _valid_python(result.patch_requests[0]["new_content"])
