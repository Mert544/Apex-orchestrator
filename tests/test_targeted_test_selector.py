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
