from pathlib import Path

from examples.helper_agents.docstring_agent import DocstringAgent


def _write(root: Path, rel: str, content: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(content, encoding="utf-8")


def test_docstring_agent_finds_missing_docstrings(tmp_path: Path):
    _write(
        tmp_path,
        "app/main.py",
        'def hello():\n    """Existing docstring."""\n    pass\n\ndef world():\n    pass\n',
    )
    agent = DocstringAgent(tmp_path)
    report = agent.scan()

    assert len(report.gaps) == 1
    assert report.gaps[0].name == "world"
    assert report.gaps[0].symbol_type == "function"
    assert report.total_symbols == 2


def test_docstring_agent_finds_missing_class_docstrings(tmp_path: Path):
    _write(
        tmp_path,
        "app/models.py",
        "class User:\n    pass\n\nclass Order:\n    \"\"\"Has docstring.\"\"\"\n    pass\n",
    )
    agent = DocstringAgent(tmp_path)
    report = agent.scan()

    assert len(report.gaps) == 1
    assert report.gaps[0].name == "User"
    assert report.gaps[0].symbol_type == "class"


def test_docstring_agent_patches_missing_docstrings(tmp_path: Path):
    _write(
        tmp_path,
        "app/main.py",
        "def hello():\n    pass\n",
    )
    agent = DocstringAgent(tmp_path)
    patched = agent.patch()

    assert "app/main.py" in patched
    content = (tmp_path / "app" / "main.py").read_text(encoding="utf-8")
    assert '"""hello implementation."""' in content


def test_docstring_agent_skips_existing_docstrings(tmp_path: Path):
    _write(
        tmp_path,
        "app/main.py",
        'def hello():\n    """Already here."""\n    pass\n',
    )
    agent = DocstringAgent(tmp_path)
    patched = agent.patch()

    assert patched == []
