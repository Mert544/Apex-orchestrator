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


def test_profiler_names_hotspot_functions(tmp_path: Path):
    # Inside a risky module, the *function* with heavy branching and no test
    # mentioning its name is surfaced; a function a test names is not.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    (tmp_path / "app" / "hot.py").write_text(
        f"def gnarly(x):\n{branches}\n    return -1\n\n"
        f"def covered(x):\n{branches}\n    return -2\n",
        encoding="utf-8",
    )
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            f"from app.hot import covered\n\ndef u{i}():\n    return covered({i})\n",
            encoding="utf-8",
        )
    (tmp_path / "tests" / "test_hot.py").write_text(
        "from app.hot import covered\n\ndef test_c():\n    assert covered(1) == 1\n",
        encoding="utf-8",
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    by_fn = {f["function"]: f for f in profile.hotspot_functions}
    assert "gnarly" in by_fn
    assert by_fn["gnarly"]["module"].endswith("hot.py")
    assert by_fn["gnarly"]["complexity"] >= 10
    assert "covered" not in by_fn          # a linked test names it


def test_hotspot_scans_never_flag_test_files(tmp_path: Path):
    # A branchy, heavily-imported *test* file is not a de-risking target — not
    # as a hotspot module, and never descended into for hotspot functions.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    (tmp_path / "tests" / "test_branchy.py").write_text(
        f"def helper(x):\n{branches}\n    return -1\n", encoding="utf-8"
    )
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            f"from tests.test_branchy import helper\n\ndef u{i}():\n    return helper({i})\n",
            encoding="utf-8",
        )
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert not any("test_branchy" in m for m in profile.hotspot_modules)
    assert not any("test_branchy" in f["module"] for f in profile.hotspot_functions)


def test_hotspot_functions_credit_wrappers_classes_and_init_modules(tmp_path: Path):
    # Three coverage routes that direct-name matching used to miss:
    # a private helper tested through its public wrapper, a method tested
    # through its class, and code living in an __init__.py (which the test
    # linker doesn't track) exercised by the suite at large.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    method_branches = "\n".join(f"        if x == {i}:\n            return {i}" for i in range(10))
    (tmp_path / "app" / "core.py").write_text(
        f"def _helper(x):\n{branches}\n    return -1\n\n"
        "def public(x):\n    return _helper(x)\n\n"
        f"class Engine:\n    def crunch(self, x):\n{method_branches}\n        return -1\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "pkg" / "__init__.py").write_text(
        f"class Limb:\n    def execute(self, x):\n{method_branches}\n        return -1\n",
        encoding="utf-8",
    )
    for i in range(3):  # fan-in so both land in the risky-candidate set
        (tmp_path / "app" / f"c{i}.py").write_text(
            "from app.core import public\nimport app.pkg\n\ndef u():\n    return public(1)\n",
            encoding="utf-8",
        )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import public\nfrom app.core import Engine\n"
        "def test_p():\n    assert public(1) == 1\n"
        "def test_e():\n    assert Engine().crunch(1) == 1\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_other.py").write_text(
        "from app.pkg import Limb\ndef test_l():\n    assert Limb().execute(1) == 1\n",
        encoding="utf-8",
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    flagged = {f["function"] for f in profile.hotspot_functions}
    assert "_helper" not in flagged          # wrapper-credit: public() names it
    assert "Engine.crunch" not in flagged    # class-credit: Engine is driven
    assert "Limb.execute" not in flagged     # __init__ fallback: whole-suite text


def test_security_finding_modules_from_content_not_filename(tmp_path: Path):
    # A blandly-named file containing eval is flagged by content; a clean file
    # with a "sensitive" name is not a content finding.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "report.py").write_text("def run(s):\n    return eval(s)\n")
    (tmp_path / "app" / "auth.py").write_text("def ok():\n    return 1\n")  # sensitive NAME, clean content
    profile = ProjectProfiler(str(tmp_path)).profile()
    sec = [str(Path(m).as_posix()) for m in profile.security_finding_modules]
    assert "app/report.py" in sec
    assert "app/auth.py" not in sec


def test_security_findings_exclude_test_files(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_e():\n    eval('1')\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.security_finding_modules == []


def test_exercised_uses_word_boundaries_not_substring(tmp_path: Path):
    # A complex, untested function `run` must NOT be marked covered just because
    # the word 'rerun' appears in the test corpus (the old substring bug).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    (tmp_path / "app" / "core.py").write_text(f"def run(x):\n{branches}\n    return -1\n")
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            "from app.core import run\n\ndef u():\n    return run(1)\n"
        )
    # The test corpus mentions 'rerun' and 'prerun' but never the word 'run'.
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_misc():\n    rerun = 1\n    prerun_flag = 2\n    assert rerun + prerun_flag == 3\n"
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert any(f["function"] == "run" for f in profile.hotspot_functions)


def test_correctness_bug_modules_flags_high_severity_logic_bugs(tmp_path: Path):
    (tmp_path / "app").mkdir()
    # return-in-finally is a high-severity logic bug (swallows exceptions).
    (tmp_path / "app" / "buggy.py").write_text(
        "def f():\n    try:\n        g()\n    finally:\n        return 1\n"
    )
    (tmp_path / "app" / "clean.py").write_text("def ok():\n    return 1\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    flagged = [str(Path(m).as_posix()) for m in profile.correctness_bug_modules]
    assert "app/buggy.py" in flagged
    assert "app/clean.py" not in flagged


def test_correctness_bug_excludes_syntax_errors_and_tests(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "broken.py").write_text("def f(:\n    pass\n")     # syntax error
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test():\n    try:\n        pass\n    finally:\n        return 1\n"
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.correctness_bug_modules == []     # syntax error + test file both excluded


def test_fixture_paths_excluded_from_seeding_signals(tmp_path: Path):
    # examples/ and tests/ carry intentional flaws / are throwaway — they must
    # not seed development ideas about the real project.
    (tmp_path / "app").mkdir()
    (tmp_path / "examples" / "demo").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "real.py").write_text("def run(s):\n    return eval(s)\n")
    (tmp_path / "examples" / "demo" / "vuln.py").write_text("def run(s):\n    return eval(s)\n")
    (tmp_path / "tests" / "test_x.py").write_text("def run(s):\n    return eval(s)\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    sec = [str(Path(m).as_posix()) for m in profile.security_finding_modules]
    assert "app/real.py" in sec
    assert not any("examples/" in m for m in sec)
    assert not any(m.startswith("tests/") or "test_x" in m for m in sec)
    # untested_modules likewise excludes the fixture/example/test files.
    assert not any("examples/" in str(m) or str(m).startswith("tests/")
                   for m in profile.untested_modules)


def test_example_dir_as_target_still_surfaces_its_own_code(tmp_path: Path):
    # When the example dir IS the target, its modules are the project — not
    # fixtures relative to that root — so they must still be surfaced.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "accounts.py").write_text("import os\ndef r(c):\n    os.system(c)\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert any("accounts.py" in str(m) for m in profile.security_finding_modules)


def _git_repo_with_history(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "busy.py").write_text("def f():\n    return 1\n")
    (tmp_path / "app" / "quiet.py").write_text("def g():\n    return 2\n")
    (tmp_path / "tests" / "test_busy.py").write_text("def test_x():\n    assert True\n")
    import subprocess
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True)
    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    # busy.py changes in 3 more commits (4 touches total); quiet.py never again.
    for i in range(3):
        (tmp_path / "app" / "busy.py").write_text(f"def f():\n    return {i}\n")
        (tmp_path / "tests" / "test_busy.py").write_text(f"def test_x():\n    assert {i} >= 0\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"change {i}")
    return tmp_path


def test_churn_hotspots_rank_frequently_changed_modules(tmp_path: Path):
    _git_repo_with_history(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    modules = [c["module"] for c in profile.churn_hotspots]
    assert "app/busy.py" in modules
    busy = next(c for c in profile.churn_hotspots if c["module"] == "app/busy.py")
    assert busy["commits"] >= ProjectProfiler.CHURN_THRESHOLD
    # Below-threshold and test/fixture files never become churn hotspots.
    assert "app/quiet.py" not in modules
    assert not any(m.startswith("tests/") for m in modules)


def test_churn_empty_for_non_git_directory(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.churn_hotspots == []
