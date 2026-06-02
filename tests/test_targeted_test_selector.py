from app.execution.targeted_test_selector import TargetedTestSelector


def _project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n"
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path


def test_select_tests_for_changed_file(tmp_path):
    _project(tmp_path)
    sel = TargetedTestSelector(project_root=str(tmp_path))
    tests = sel.select_tests(changed_files=["app/calc.py"])
    assert any("test_calc.py" in t for t in tests)


def test_select_tests_no_tests_dir(tmp_path):
    sel = TargetedTestSelector(project_root=str(tmp_path))
    assert sel.select_tests(changed_files=["app/x.py"]) == []


def test_select_tests_dedup_and_cap(tmp_path):
    _project(tmp_path)
    sel = TargetedTestSelector(project_root=str(tmp_path))
    tests = sel.select_tests(changed_files=["app/calc.py", "app/calc.py"], max_tests=5)
    assert len(tests) == len(set(tests))
    assert len(tests) <= 5


def test_get_test_command_returns_list(tmp_path):
    _project(tmp_path)
    sel = TargetedTestSelector(project_root=str(tmp_path))
    cmd = sel.get_test_command(["tests/test_calc.py"])
    assert isinstance(cmd, list)
    assert any("pytest" in part for part in cmd)


def test_select_tests_for_functions(tmp_path):
    _project(tmp_path)
    # test_calc.py contains "test_add"; selecting by that function name finds it.
    sel = TargetedTestSelector(project_root=str(tmp_path))
    tests = sel.select_tests(uncovered_functions=["test_add"])
    assert any("test_calc.py" in t for t in tests)


def test_get_test_command_no_selection_runs_all(tmp_path):
    sel = TargetedTestSelector(project_root=str(tmp_path))
    cmd = sel.get_test_command(changed_files=["nope.py"])
    assert cmd == ["python", "-m", "pytest", "-q"]


def test_test_runner_success(tmp_path):
    from unittest.mock import patch
    from app.execution.targeted_test_selector import TestRunner

    class _Res:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch("subprocess.run", return_value=_Res()):
        result = TestRunner(project_root=str(tmp_path)).run_tests()
    assert result["passed"] is True
    assert result["success"] is True


def test_test_runner_timeout(tmp_path):
    import subprocess
    from unittest.mock import patch
    from app.execution.targeted_test_selector import TestRunner

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("c", 1)):
        result = TestRunner(project_root=str(tmp_path), timeout=1).run_tests()
    assert result["passed"] is False
    assert result.get("timeout") is True


def test_test_runner_error(tmp_path):
    from unittest.mock import patch
    from app.execution.targeted_test_selector import TestRunner

    with patch("subprocess.run", side_effect=RuntimeError("boom")):
        result = TestRunner(project_root=str(tmp_path)).run_tests()
    assert result["success"] is False
    assert result.get("error") is True


def test_test_runner_run_targeted(tmp_path):
    _project(tmp_path)
    from unittest.mock import patch
    from app.execution.targeted_test_selector import TestRunner

    class _Res:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch("subprocess.run", return_value=_Res()):
        result = TestRunner(project_root=str(tmp_path)).run_targeted(changed_files=["app/calc.py"])
    assert result["success"] is True
