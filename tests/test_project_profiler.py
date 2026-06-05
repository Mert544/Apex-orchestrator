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


def test_sensitive_paths_ignore_docs_matching_hint_substring(tmp_path):
    # A docs file like docs/api.md matches the "api" hint by substring, but
    # "hardening" or "testing" a markdown doc is meaningless. Only code files
    # should be treated as sensitive (regression from running Apex on click,
    # where docs/api.md was wrongly ranked the #1 sensitive path to test).
    from app.tools.project_profile import ProjectProfiler

    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "api.md").write_text("# API reference\n", encoding="utf-8")
    (tmp_path / "src" / "api_client.py").write_text("def call():\n    return 1\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()

    sensitive = [str(Path(p).as_posix()) for p in profile.sensitive_paths]
    assert "docs/api.md" not in sensitive
    assert "src/api_client.py" in sensitive


def test_profiler_flags_modules_with_clustered_debt_markers(tmp_path: Path):
    (tmp_path / "app").mkdir()

    # 3+ debt markers in comments -> flagged.
    (tmp_path / "app" / "debt.py").write_text(
        "def f():\n"
        "    pass  # TODO finish this\n"
        "    # FIXME broken edge case\n"
        "    # xxx revisit\n",  # lower-case marker -> case-insensitive
        encoding="utf-8",
    )
    # Only 1 marker -> below threshold, not flagged.
    (tmp_path / "app" / "light.py").write_text(
        "def g():\n    pass  # TODO one thing\n",
        encoding="utf-8",
    )
    # No markers at all -> clean.
    (tmp_path / "app" / "clean.py").write_text(
        "def h():\n    return 1\n",
        encoding="utf-8",
    )
    # The word TODO appears only inside a string literal / identifier, never in
    # a comment -> must NOT be flagged (precision: comment context only).
    (tmp_path / "app" / "literal.py").write_text(
        "TODO_MESSAGE = 'TODO write docs'\n"
        "def todo_handler():\n"
        "    return 'FIXME later and XXX and HACK'\n"
        "label = 'TODO FIXME XXX'\n",
        encoding="utf-8",
    )

    profile = ProjectProfiler(tmp_path).profile()

    def _posix(paths: list[str]) -> list[str]:
        return [str(Path(p).as_posix()) for p in paths]

    flagged = _posix(profile.debt_marker_modules)
    assert "app/debt.py" in flagged
    assert "app/light.py" not in flagged
    assert "app/clean.py" not in flagged
    assert "app/literal.py" not in flagged


def test_profiler_flags_complexity_hotspots(tmp_path: Path):
    # A complex, heavily-imported, untested module is a hotspot; a trivial one
    # (low complexity) is not, even if imported.
    (tmp_path / "app").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    (tmp_path / "app" / "hot.py").write_text(f"def hot(x):\n{branches}\n    return -1\n", encoding="utf-8")
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            f"from app.hot import hot\n\ndef u{i}():\n    return hot({i})\n", encoding="utf-8"
        )
    (tmp_path / "app" / "calm.py").write_text("def calm(x):\n    return x + 1\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    hot = [str(Path(p).as_posix()) for p in profile.hotspot_modules]
    assert "app/hot.py" in hot
    assert "app/calm.py" not in hot


def test_profiler_flags_shallow_only_coverage(tmp_path: Path):
    # A module whose only linked test is a shape-only stub is 'shallow', not
    # fully tested; a real value assertion clears it.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "shallow.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
    (tmp_path / "pkg" / "deep.py").write_text("def g(x: int) -> int:\n    return x * 2\n")
    (tmp_path / "tests" / "test_shallow.py").write_text(
        "import pkg.shallow\ndef test_s():\n    assert isinstance(pkg.shallow.f(0), int)\n"
    )
    (tmp_path / "tests" / "test_deep.py").write_text(
        "from pkg.deep import g\ndef test_d():\n    assert g(3) == 6\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    shallow = [str(Path(p).as_posix()) for p in profile.shallow_tested_modules]
    assert "pkg/shallow.py" in shallow
    assert "pkg/deep.py" not in shallow
