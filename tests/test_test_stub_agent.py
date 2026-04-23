from pathlib import Path

from examples.helper_agents.test_stub_agent import TestStubAgent


def _write(root: Path, rel: str, content: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(content, encoding="utf-8")


def test_stub_agent_finds_missing_tests(tmp_path: Path):
    _write(
        tmp_path,
        "app/calc.py",
        "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n",
    )
    agent = TestStubAgent(tmp_path)
    report = agent.scan()

    assert len(report.gaps) == 2
    names = {g.symbol_name for g in report.gaps}
    assert "add" in names
    assert "sub" in names


def test_stub_agent_generates_test_files(tmp_path: Path):
    _write(
        tmp_path,
        "app/calc.py",
        "def add(a, b):\n    return a + b\n",
    )
    agent = TestStubAgent(tmp_path)
    agent.scan()
    generated = agent.generate_stubs()

    assert len(generated) >= 1
    test_file = tmp_path / "tests" / "test_calc.py"
    assert test_file.exists()
    content = test_file.read_text(encoding="utf-8")
    assert "test_add" in content
    assert "Stub test" in content


def test_stub_agent_detects_existing_tests(tmp_path: Path):
    _write(
        tmp_path,
        "app/calc.py",
        "def add(a, b):\n    return a + b\n",
    )
    _write(
        tmp_path,
        "tests/test_calc.py",
        "def test_add():\n    assert add(2, 3) == 5\n",
    )
    agent = TestStubAgent(tmp_path)
    report = agent.scan()

    assert len(report.gaps) == 0
    assert report.tested_functions == 1
    assert report.coverage_ratio == 1.0


def test_stub_agent_ignores_private_functions(tmp_path: Path):
    _write(
        tmp_path,
        "app/utils.py",
        "def _internal():\n    pass\n\ndef public():\n    pass\n",
    )
    agent = TestStubAgent(tmp_path)
    report = agent.scan()

    names = {g.symbol_name for g in report.gaps}
    assert "_internal" not in names
    assert "public" in names
