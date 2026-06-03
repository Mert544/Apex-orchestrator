from pathlib import Path

from app.tools.project_profile import ProjectProfiler


def test_project_profiler_extracts_basic_project_signals(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "auth").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

    (tmp_path / "app" / "main.py").write_text(
        "import os\nfrom auth.token_service import TokenService\n\nclass App:\n    pass\n\ndef run():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "auth" / "token_service.py").write_text(
        "import secrets\n\nclass TokenService:\n    pass\n\ndef issue_token():\n    return secrets.token_hex()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    profile = ProjectProfiler(tmp_path).profile()

    def _posix(paths: list[str]) -> list[str]:
        return [str(Path(p).as_posix()) for p in paths]

    assert profile.total_files >= 5
    assert "app/main.py" in _posix(profile.entrypoints)
    assert any(path.endswith("ci.yml") for path in profile.ci_files)
    assert any(path.endswith("pyproject.toml") for path in profile.config_files)
    assert any("auth" in path.lower() for path in profile.sensitive_paths)
    assert "app/main.py" in _posix(profile.dependency_hubs)
    assert "app/main.py" in _posix(profile.symbol_hubs)
    assert "auth/token_service.py" in _posix(profile.untested_modules)


def test_scans_modernizable_modules(tmp_path):
    from app.tools.project_profile import ProjectProfiler

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "old.py").write_text("def f(x):\n    return x == None\n")
    (tmp_path / "app" / "clean.py").write_text("def g(x):\n    return x is None\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert "app/old.py" in profile.modernizable_modules
    assert "app/clean.py" not in profile.modernizable_modules


def test_scans_mutable_defaults(tmp_path):
    from app.tools.project_profile import ProjectProfiler

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bug.py").write_text("def f(x=[]):\n    return x\n")
    (tmp_path / "app" / "ok.py").write_text("def g(x=None):\n    return x\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert "app/bug.py" in profile.mutable_default_modules
    assert "app/ok.py" not in profile.mutable_default_modules
