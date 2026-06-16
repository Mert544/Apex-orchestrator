"""Characterization tests pinning the exact output of ``try_create_stub``.

These lock the byte-exact generated content and skip conditions so the
decomposition into pure helpers cannot drift. Offline, stdlib-only.
"""
import pytest

from app.execution.semantic.generators.stub import (
    _contract_lines,
    _contract_note,
    _stub_module_name,
    try_create_stub,
)


@pytest.mark.parametrize(
    "rel_path,expected",
    [
        ("tests/test_widget.py", "widget"),
        ("tests/sub/test_widget.py", "sub"),  # uses parts[1] verbatim, not the leaf
        ("notest.py", None),            # missing "test_"
        ("test_widget.txt", None),      # not .py
        ("src/test_widget.py", None),   # not under tests/
        ("test_widget.py", None),       # parts[0] != "tests"
        ("tests/test___init__.py", None),   # dunder
        ("tests/test___main__.py", None),   # dunder
    ],
)
def test_stub_module_name_skip_conditions(rel_path, expected):
    assert _stub_module_name(rel_path) == expected


def test_non_target_returns_none(tmp_path):
    assert try_create_stub(tmp_path, "src/test_x.py", "t", "id") is None


def test_missing_source_yields_skip_stub(tmp_path):
    res = try_create_stub(tmp_path, "tests/test_absent.py", "My Title", "task-9")
    assert res is not None
    assert res.transform_type == "create_test_stub"
    content = res.patch_requests[0]["new_content"]
    assert "@pytest.mark.skip" in content
    assert "# task: task-9" in content
    assert "# title: My Title" in content
    assert res.rationale == ["Created missing test stub at tests/test_absent.py."]


def test_syntax_error_source_yields_skip_stub(tmp_path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    res = try_create_stub(tmp_path, "tests/test_broken.py", "T", "id")
    assert "@pytest.mark.skip" in res.patch_requests[0]["new_content"]


def test_import_smoke_only_when_no_specs(tmp_path):
    (tmp_path / "quiet.py").write_text("def _hidden(x: int) -> int:\n    return x\n", encoding="utf-8")
    res = try_create_stub(tmp_path, "tests/test_quiet.py", "T", "id")
    content = res.patch_requests[0]["new_content"]
    assert "def test_quiet_imports():" in content
    assert "callable_contracts" not in content
    assert res.rationale[0].endswith("(import smoke test).")


def test_callable_contracts_with_return_assert(tmp_path):
    (tmp_path / "calc.py").write_text("def f(x: int) -> str:\n    return ''\n", encoding="utf-8")
    res = try_create_stub(tmp_path, "tests/test_calc.py", "T", "id")
    content = res.patch_requests[0]["new_content"]
    assert "def test_calc_callable_contracts():" in content
    assert "assert isinstance(calc.f(0), str)" in content
    assert "(1 callable(s) exercised, 1 return-type contract(s) asserted)" in res.rationale[0]


def test_callable_exercised_without_return_assert(tmp_path):
    # float return is in the numeric tower -> no isinstance assert, bare call.
    (tmp_path / "num.py").write_text("def g(x: int) -> float:\n    return 0.0\n", encoding="utf-8")
    res = try_create_stub(tmp_path, "tests/test_num.py", "T", "id")
    content = res.patch_requests[0]["new_content"]
    assert "    num.g(0)" in content
    assert "isinstance" not in content
    assert res.rationale[0].endswith("(1 callable(s) exercised).")


def test_contract_note_branches():
    assert _contract_note([]) == "(import smoke test)"
    assert _contract_note([("f", "0", None)]) == "(1 callable(s) exercised)"
    assert _contract_note([("f", "0", "str")]) == (
        "(1 callable(s) exercised, 1 return-type contract(s) asserted)"
    )


def test_contract_lines_smoke_only():
    lines = _contract_lines("pkg.mod", "mod", "Title", "tid", [])
    assert lines[1] == "# task: tid"
    assert lines[2] == "# title: Title"
    assert lines[4] == "import pkg.mod"
    assert "    assert pkg.mod is not None" in lines
    assert not any("callable_contracts" in line for line in lines)


def test_braces_in_title_and_task_id_are_literal(tmp_path):
    # No str.format involved: braces must survive verbatim.
    res = try_create_stub(tmp_path, "tests/test_absent.py", "100% {0} {x}", "{tid}")
    content = res.patch_requests[0]["new_content"]
    assert "# title: 100% {0} {x}" in content
    assert "# task: {tid}" in content


def test_generated_content_is_valid_python(tmp_path):
    import ast

    (tmp_path / "calc.py").write_text("def f(x: int) -> str:\n    return ''\n", encoding="utf-8")
    res = try_create_stub(tmp_path, "tests/test_calc.py", "T", "id")
    ast.parse(res.patch_requests[0]["new_content"])  # must not raise


def test_results_are_deterministic(tmp_path):
    (tmp_path / "d.py").write_text("def f(x: int) -> str:\n    return ''\n", encoding="utf-8")
    a = try_create_stub(tmp_path, "tests/test_d.py", "T", "id")
    b = try_create_stub(tmp_path, "tests/test_d.py", "T", "id")
    assert a.patch_requests == b.patch_requests
    assert a.rationale == b.rationale
