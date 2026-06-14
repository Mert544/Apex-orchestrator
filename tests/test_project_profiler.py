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


def test_debt_marker_age_anchored_to_head_commit(tmp_path: Path):
    # The oldest marker's age comes from git blame, measured against the HEAD
    # commit time (not the wall clock) — deterministic for a given repo state.
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    debt = tmp_path / "app" / "old_debt.py"
    debt.write_text("# TODO: one\n# FIXME: two\n# XXX: three\ndef f():\n    return 1\n")

    def _git(*args: str, date: str = "") -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "old", date="2024-01-01T12:00:00 +0000")
    (tmp_path / "app" / "fresh.py").write_text("def g():\n    return 2\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "new", date="2026-01-01T12:00:00 +0000")

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert "app/old_debt.py" in profile.debt_marker_modules
    age = profile.debt_marker_ages.get("app/old_debt.py")
    assert age is not None and 700 <= age <= 745  # ~2 years between the commits


def test_debt_marker_age_empty_outside_git(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "d.py").write_text("# TODO a\n# FIXME b\n# HACK c\ndef f():\n    return 1\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.debt_marker_modules  # flagged by count
    assert profile.debt_marker_ages == {}  # but no git history to date them


def test_security_finding_age_measures_exposure_window(tmp_path: Path):
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")

    def _git(*args: str, date: str = "") -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "old", date="2025-06-01T12:00:00 +0000")
    (tmp_path / "app" / "fresh.py").write_text("F = 1\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "new", date="2026-06-01T12:00:00 +0000")

    profile = ProjectProfiler(str(tmp_path)).profile()
    age = profile.security_finding_ages.get("app/danger.py")
    assert age is not None and 358 <= age <= 372  # ~1 year exposure window


def test_doc_drift_flags_missing_references_only(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def f():\n    return 1\n")
    (tmp_path / "README.md").write_text(
        "See `app/real.py` for the core.\n"            # exists -> not drift
        "The parser lives in `app/parser.py`.\n"        # missing -> drift
        "Run `apex ideate --roadmap` daily.\n"          # command (spaces) -> skipped
        "Use `path/to/project` as target.\n"            # placeholder -> skipped
        "Evidence goes to `.apex/proof.json`.\n"        # runtime dir -> skipped
        "Docs: `https://example.com/app/x.py`.\n"       # URL -> skipped
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    refs = [(d["doc"], d["reference"]) for d in profile.doc_drift]
    assert refs == [("README.md", "app/parser.py")]
    assert profile.doc_drift[0]["line"] == 2


def test_doc_drift_handles_line_anchored_refs_and_docs_dir(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("Check `app/ghost.py:42` for details.\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.doc_drift == [{"doc": "docs/guide.md", "reference": "app/ghost.py", "line": 1}]


def test_change_coupling_finds_co_changing_pairs(tmp_path: Path):
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("A = 0\n")
    (tmp_path / "app" / "b.py").write_text("B = 0\n")
    (tmp_path / "app" / "solo.py").write_text("S = 0\n")

    def _git(*args: str) -> None:
        env = dict(os.environ)
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    # a.py and b.py change together three times; solo.py changes alone.
    for i in range(3):
        (tmp_path / "app" / "a.py").write_text(f"A = {i + 1}\n")
        (tmp_path / "app" / "b.py").write_text(f"B = {i + 1}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"pair {i}")
    (tmp_path / "app" / "solo.py").write_text("S = 1\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "solo")

    profile = ProjectProfiler(str(tmp_path)).profile()
    # 3 pair commits + the init commit (all three files together) = 4;
    # a-solo / b-solo pairs stay below the threshold and never surface.
    assert profile.change_coupling == [{"a": "app/a.py", "b": "app/b.py", "commits": 4}]


def test_change_coupling_empty_outside_git(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("M = 1\n")
    assert ProjectProfiler(str(tmp_path)).profile().change_coupling == []


def test_knowledge_risk_flags_single_author_concentration(tmp_path: Path):
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "owned.py").write_text("O = 0\n")
    (tmp_path / "app" / "shared.py").write_text("S = 0\n")

    def _git(*args: str, who: str = "alice") -> None:
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = who
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = f"{who}@t.com"
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    # owned.py: 5 more touches, all alice. shared.py: alternating authors
    # (10 rounds so BOTH authors clear the activity floor of 5 commits).
    for i in range(5):
        (tmp_path / "app" / "owned.py").write_text(f"O = {i + 1}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"own {i}")
    for i in range(10):
        (tmp_path / "app" / "shared.py").write_text(f"S = {i + 1}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"share {i}",
             who="alice" if i % 2 else "bob")

    profile = ProjectProfiler(str(tmp_path)).profile()
    flagged = {r["module"]: r for r in profile.knowledge_risks}
    assert "app/owned.py" in flagged
    assert flagged["app/owned.py"]["share"] == 100
    assert "app/shared.py" not in flagged  # 50/50 split is healthy


def test_knowledge_risk_silent_for_single_author_projects(tmp_path: Path):
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("M = 0\n")

    def _git(*args: str) -> None:
        env = dict(os.environ)
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "solo@t.com")
    _git("config", "user.name", "solo")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    for i in range(6):
        (tmp_path / "app" / "m.py").write_text(f"M = {i + 1}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}")

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.knowledge_risks == []  # solo dev: 100% share = no information


def test_knowledge_risk_ignores_drive_by_second_author(tmp_path: Path):
    # One real author + a single drive-by commit must NOT make the project
    # "multi-author" — otherwise every solo project with one bot commit
    # would flag everything at 100%.
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("M = 0\n")

    def _git(*args: str, who: str = "solo") -> None:
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = who
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = f"{who}@t.com"
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    for i in range(6):
        (tmp_path / "app" / "m.py").write_text(f"M = {i + 1}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}")
    (tmp_path / "app" / "m.py").write_text("M = 99\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "drive-by", who="bot")

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.knowledge_risks == []


def test_dead_params_flags_never_read_parameters_only(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text, color=None, width=80):\n"   # color -> dead
        "    return text[:width]\n"
        "\n"
        "def fetch(url, *, retries=3):\n"             # kwonly dead too
        "    return url\n"
        "\n"
        "def walk(node, _depth=0):\n"                 # _-prefixed = intentional
        "    return node\n"
    )
    (tmp_path / "app" / "iface.py").write_text(
        "def apply(x, extra):\n"                      # name defined twice ->
        "    return x\n"                              # interface family, skip
    )
    (tmp_path / "app" / "iface2.py").write_text(
        "import functools\n"
        "\n"
        "def apply(y, extra):\n"
        "    return y\n"
        "\n"
        "def on_event(payload):\n"                    # travels as an object ->
        "    return 1\n"                              # signature isn't its own
        "\n"
        "HANDLER = on_event\n"
        "\n"
        "@functools.lru_cache\n"                      # decorated -> framework
        "def cached(size):\n"                         # may impose signature
        "    return 1\n"
        "\n"
        "def proto(handler):\n"                       # stub -> params are the
        "    raise NotImplementedError\n"             # contract, keep them
    )
    (tmp_path / "tests" / "test_x.py").write_text(
        "def helper(unused):\n    return 1\n")        # fixture/test path skipped

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.dead_params == [
        {"module": "app/core.py", "function": "render", "param": "color", "line": 1},
        {"module": "app/core.py", "function": "fetch", "param": "retries", "line": 4},
    ]


def test_extractable_blocks_surfaces_concrete_extract_command(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # A long function with a clean accumulation seam in the middle.
    body = "\n".join(f"    acc = acc + {i}" for i in range(45))
    (tmp_path / "app" / "big.py").write_text(
        f"def compute(start):\n    acc = start\n{body}\n    return acc\n"
    )
    # A vulnerability fixture must NOT contribute an extraction suggestion.
    (tmp_path / "tests" / "test_big.py").write_text(
        "def helper(x):\n" + "\n".join(f"    y{i} = {i}" for i in range(45)) + "\n"
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    blocks = profile.extractable_blocks
    assert blocks, "a long function should yield an extractable-block signal"
    eb = next(b for b in blocks if b["module"] == "app/big.py")
    assert eb["function"] == "compute"
    assert eb["start"] < eb["end"]
    assert eb["name"] == "_compute_part"
    assert eb["lines_saved"] >= 6
    # Fixtures/tests are excluded from the signal (their flaws are intentional).
    assert all(not b["module"].startswith("tests/") for b in blocks)


def test_inlinable_helpers_surfaces_single_use_helper(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # A tiny single-use return-only helper `apex inline` would cleanly accept.
    (tmp_path / "app" / "calc.py").write_text(
        "def fee(x):\n"
        "    return x * 2\n"
        "\n"
        "\n"
        "def total(price):\n"
        "    return fee(price) + 1\n",
        encoding="utf-8",
    )
    # A fixture/test helper of the same shape must NOT contribute a signal.
    (tmp_path / "tests" / "test_calc.py").write_text(
        "def helper(x):\n"
        "    return x * 2\n"
        "\n"
        "\n"
        "def use(n):\n"
        "    return helper(n)\n",
        encoding="utf-8",
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    helpers = profile.inlinable_helpers
    assert helpers, "a single-use helper should yield an inlinable-helper signal"
    ih = next(h for h in helpers if h["module"] == "app/calc.py")
    assert ih["function"] == "fee"
    assert ih["line"] == 1
    assert ih["call_sites"] == 1
    # Fixtures/tests are excluded from the signal (their flaws are intentional).
    assert all(not h["module"].startswith("tests/") for h in helpers)


# --- light profile: the fast path health_score.grade uses to self-assess ---


def test_light_profile_skips_git_scans_keeps_grade_signals(tmp_path: Path):
    """profile(light=True) leaves the four git/doc + three AST refactor scans'
    fields empty, yet still populates every signal the grade reads."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # A module the grade scores: untested + modernizable (== None) so the
    # grade-read lists are non-empty even on the light path.
    (tmp_path / "app" / "old.py").write_text(
        "def f(x):\n    return x == None\n", encoding="utf-8"
    )
    (tmp_path / "app" / "covered.py").write_text(
        "def g(x):\n    return x + 1\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_covered.py").write_text(
        "from app.covered import g\ndef test_g():\n    assert g(1) == 2\n",
        encoding="utf-8",
    )

    light = ProjectProfiler(str(tmp_path)).profile(light=True)

    # Fields the SKIPPED scans populate stay at their empty defaults.
    assert light.churn_hotspots == []
    assert light.change_coupling == []
    assert light.knowledge_risks == []
    assert light.debt_marker_ages == {}
    assert light.security_finding_ages == {}
    assert light.doc_drift == []
    assert light.dead_params == []
    assert light.extractable_blocks == []
    assert light.inlinable_helpers == []

    # Fields the GRADE reads are still populated by _populate_python_structure.
    assert "app/old.py" in light.untested_modules
    assert "app/old.py" in light.modernizable_modules
    assert "app/covered.py" not in light.untested_modules
    assert "app/old.py" in light.module_to_tests
    assert "app/covered.py" in light.module_to_tests


def test_light_profile_does_not_invoke_git(tmp_path: Path, monkeypatch):
    """The light path must not shell out to git at all (the whole point: no
    per-module git blame / log subprocesses)."""
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    # Make this a real git repo so the full path WOULD invoke git.
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True)
    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")

    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(cmd, *a, **k):  # noqa: ANN001, ANN002, ANN003
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
            calls.append(list(cmd))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    ProjectProfiler(str(tmp_path)).profile(light=True)
    assert calls == [], f"light profile shelled out to git: {calls}"


def test_light_profile_default_off_keeps_full_behavior(tmp_path: Path):
    """light defaults to False: the full profile still runs every scan, so the
    refactor-signal fields are populated as before for non-grade callers."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        "def fee(price):\n    return price * 0.1\n\n\n"
        "def total(price):\n    return fee(price) + 1\n",
        encoding="utf-8",
    )
    full = ProjectProfiler(str(tmp_path)).profile()  # default light=False
    assert full.inlinable_helpers, "default profile must still run the AST scans"
def test_project_profiler_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    # A full worktree COPY under .claude/ must not be counted.
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    (copy / "extra.py").write_text("def extra(): pass\n", encoding="utf-8")

    profile = ProjectProfiler(tmp_path).profile()
    modules = {str(Path(m).as_posix()) for m in profile.untested_modules}
    assert "app/real.py" in modules
    assert not any(".claude" in m for m in modules)
    # Only the single real source file is counted (not the two copies).
    assert profile.total_files == 1


def test_profiler_flags_impure_untested_functions(tmp_path: Path):
    # Inside a risky (heavily-imported) module, a function that mixes observable
    # side effects (logging/global state) with logic and that NO test names is
    # surfaced as impure-untested; a pure sibling and an impure-but-tested
    # sibling are both cleared.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "io_logic.py").write_text(
        "import logging\n\n"
        "_CACHE = {}\n\n"
        "def emit(x):\n"
        "    global _CACHE\n"
        "    logging.info('emit %s', x)\n"
        "    _CACHE[x] = x\n"
        "    return x + 1\n\n"
        "def pure_add(x):\n"
        "    return x + 1\n\n"
        "def tested_emit(x):\n"
        "    logging.info('tested %s', x)\n"
        "    return x * 2\n",
        encoding="utf-8",
    )
    # Three importers give io_logic.py the fan-in that puts it in the candidate set.
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            f"from app.io_logic import emit\n\ndef u{i}():\n    return emit({i})\n",
            encoding="utf-8",
        )
    (tmp_path / "tests" / "test_io.py").write_text(
        "from app.io_logic import tested_emit\n\n"
        "def test_t():\n    assert tested_emit(2) == 4\n",
        encoding="utf-8",
    )
    profile = ProjectProfiler(str(tmp_path)).profile()
    by_fn = {f["function"]: f for f in profile.impure_untested_functions}
    assert "emit" in by_fn                       # impure + untested -> flagged
    assert by_fn["emit"]["module"].endswith("io_logic.py")
    assert by_fn["emit"]["side_effects"]         # carries the concrete reasons
    assert by_fn["emit"]["line"] >= 1
    assert "pure_add" not in by_fn               # pure -> never flagged
    assert "tested_emit" not in by_fn            # impure but a test names it


def test_impure_untested_scan_is_deterministic(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text(
        "import os\n\n"
        "def runner(x):\n"
        "    os.system('echo ' + str(x))\n"
        "    return x\n\n"
        "def writer(x):\n"
        "    open('/tmp/z', 'w').write(str(x))\n"
        "    return x\n",
        encoding="utf-8",
    )
    for i in range(3):
        (tmp_path / "app" / f"c{i}.py").write_text(
            f"from app.svc import runner, writer\n\ndef u{i}():\n    return runner({i})\n",
            encoding="utf-8",
        )
    a = ProjectProfiler(str(tmp_path)).profile().impure_untested_functions
    b = ProjectProfiler(str(tmp_path)).profile().impure_untested_functions
    assert a == b                                # same input -> same output
    assert a, "expected at least one impure-untested function"


def _build_hub_repo(tmp_path: Path) -> None:
    """Four untested hubs (descending fan-in) + one tested hub + importer leaves.

    h0 fan-in 6 (becomes fragile), h1 fan-in 5 (has a real test), h2 fan-in 4
    and h3 fan-in 3 (untested hubs). Every hub is imported by N leaf modules.
    """
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    for name, fan_in in {"h0": 6, "h1": 5, "h2": 4, "h3": 3}.items():
        (tmp_path / "app" / f"{name}.py").write_text(
            "def f(x):\n    return x\n", encoding="utf-8")
        for i in range(fan_in):
            (tmp_path / "app" / f"{name}_c{i}.py").write_text(
                f"from app.{name} import f\n\ndef u{i}():\n    return f({i})\n",
                encoding="utf-8")
    # h1 is the one hub with a real, substantive test — it must be cleared.
    (tmp_path / "tests" / "test_h1.py").write_text(
        "from app.h1 import f\n\ndef test_f():\n    assert f(3) == 3\n",
        encoding="utf-8")


def test_profiler_flags_hub_untested_modules(tmp_path: Path):
    # A high-fan-in module that NO test names is surfaced as hub-untested; a
    # tested hub is cleared, and a low-fan-in importer leaf never qualifies.
    _build_hub_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    by_mod = {h["module"]: h for h in profile.hub_untested_modules}
    # h2/h3 are untested hubs above the fan-in floor.
    assert "app/h2.py" in by_mod
    assert "app/h3.py" in by_mod
    assert by_mod["app/h2.py"]["fan_in"] == 4   # fan-in = number of importers
    assert by_mod["app/h3.py"]["fan_in"] == 3
    # h1 has a real test -> not flagged. Importer leaves (fan-in 0) -> not hubs.
    assert "app/h1.py" not in by_mod
    assert not any(m.endswith("_c0.py") for m in by_mod)
    # Sorted widest-blast-radius first.
    fan_ins = [h["fan_in"] for h in profile.hub_untested_modules]
    assert fan_ins == sorted(fan_ins, reverse=True)


def test_hub_untested_dedups_under_fragile(tmp_path: Path):
    # h0 (fan-in 6) is BOTH a hub and the top fragile module; the more-severe
    # fragile signal claims it, so hub-untested must NOT also list it.
    _build_hub_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert "app/h0.py" in profile.fragile_modules
    hub_mods = {h["module"] for h in profile.hub_untested_modules}
    assert "app/h0.py" not in hub_mods           # deduped under fragile


def test_hub_untested_scan_is_deterministic(tmp_path: Path):
    _build_hub_repo(tmp_path)
    a = ProjectProfiler(str(tmp_path)).profile().hub_untested_modules
    b = ProjectProfiler(str(tmp_path)).profile().hub_untested_modules
    assert a == b                                # same input -> same output
    assert a, "expected at least one hub-untested module"


def test_low_fan_in_untested_module_is_not_a_hub(tmp_path: Path):
    # A module imported by only ONE other module is untested but NOT a hub
    # (below the fan-in floor), so it is not surfaced as hub-untested.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "leaf.py").write_text(
        "def f(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "app" / "only.py").write_text(
        "from app.leaf import f\n\ndef u():\n    return f(1)\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert not any(h["module"] == "app/leaf.py" for h in profile.hub_untested_modules)
