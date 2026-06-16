"""Characterization tests pinning ``ProjectProfiler._run_base_walk`` and
``_scan_churn`` (and their extracted pure helpers) to exact, documented output.

These two functions were decomposed into small pure helpers; this module is the
behavioral lock. It builds one representative, git-backed project tree that
exercises every branch of both targets — entrypoint/test/CI/config/sensitive
classification, debt markers, content security findings, correctness bugs,
skip-dir exclusion, polyglot/binary files (base walk); multi-author history,
co-changing pairs, mega-commit coupling exclusion, and knowledge concentration
(churn) — then asserts the precise fields they produce.

Determinism and light-mode safety are pinned explicitly: the same tree profiled
twice yields equal output, and light mode (which never runs ``_scan_churn``)
leaves every git-only field empty while keeping the always-on base-walk fields
byte-identical to full mode.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

import pytest

from app.tools.project_profile import ProjectProfiler


def _git(root: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        }
    )
    subprocess.run(
        ["git", *args], cwd=root, check=True,
        capture_output=True, text=True, env=env,
    )


def _commit(root: Path, msg: str, name: str, email: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        }
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True,
                   capture_output=True, text=True, env=env)
    subprocess.run(["git", "commit", "-m", msg, "--no-gpg-sign"], cwd=root,
                   check=True, capture_output=True, text=True, env=env)


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True,
                       capture_output=True, text=True)
        return True
    except Exception:
        return False


def _build_tree(root: Path) -> None:
    """A representative tree exercising every branch of both target functions."""
    for sub in ("app", "auth", "tests", "docs",
                ".github/workflows", ".turbo", "node_modules"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    (root / "app" / "main.py").write_text(
        "import os\nfrom auth.token_service import TokenService\n\n"
        "class App:\n    pass\n\ndef run():\n    return True\n",
        encoding="utf-8",
    )
    # Sensitive path + content security finding (eval) + >=3 debt markers.
    (root / "auth" / "token_service.py").write_text(
        "import secrets\n\n# TODO: harden\n# FIXME: rotate\n# XXX: temp\n"
        "class TokenService:\n    pass\n\n"
        "def issue_token(raw):\n    return eval(raw)\n",
        encoding="utf-8",
    )
    # Correctness bug: return-in-finally (high-severity logic bug).
    (root / "app" / "buggy.py").write_text(
        "def f():\n    try:\n        return 1\n    finally:\n        return 2\n",
        encoding="utf-8",
    )
    (root / "app" / "util.py").write_text(
        "def helper(x):\n    if x == None:\n        return 0\n    return x\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_main.py").write_text(
        "from app.main import run\n\ndef test_ok():\n    assert run() is True\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (root / "app" / "front.ts").write_text(
        "export const x = 1;\nfunction g() { return 2; }\n", encoding="utf-8")
    (root / "app" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "README.md").write_text(
        "See `app/missing.py` and `app/main.py` exists.\n", encoding="utf-8")
    # Skip-dir contents that must be ignored entirely.
    (root / ".turbo" / "cache.py").write_text("eval('x')\n", encoding="utf-8")
    (root / "node_modules" / "lib.js").write_text("var y=1\n", encoding="utf-8")

    _git(root, "init", "-q")
    _commit(root, "init", "Alice", "alice@example.com")
    # main.py + util.py co-change across commits by two authors (coupling).
    for i in range(6):
        for name in ("app/main.py", "app/util.py"):
            p = root / name
            p.write_text(p.read_text(encoding="utf-8") + f"# r{i}\n", encoding="utf-8")
        who = ("Alice", "alice@example.com") if i % 2 == 0 else ("Bob", "bob@example.com")
        _commit(root, f"pair {i}", *who)
    # token_service churns, single dominant author (knowledge concentration).
    for i in range(6):
        p = root / "auth" / "token_service.py"
        p.write_text(p.read_text(encoding="utf-8") + f"# t{i}\n", encoding="utf-8")
        _commit(root, f"token {i}", "Alice", "alice@example.com")
    # Bob's solo commits so he is a second genuinely-active author.
    for i in range(4):
        p = root / "app" / "buggy.py"
        p.write_text(p.read_text(encoding="utf-8") + f"# b{i}\n", encoding="utf-8")
        _commit(root, f"buggy {i}", "Bob", "bob@example.com")
    # Mega commit (> MAX_COMMIT_FILES) — must be excluded from coupling.
    for j in range(20):
        (root / "app" / f"mega_{j}.py").write_text(f"X = {j}\n", encoding="utf-8")
    _commit(root, "mega reformat", "Bob", "bob@example.com")


def _posix(paths: list[str]) -> list[str]:
    return [Path(p).as_posix() for p in paths]


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not available")


@pytest.fixture()
def built(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    _build_tree(root)
    return root


def test_base_walk_classification(built: Path) -> None:
    prof = ProjectProfiler(str(built)).profile(light=False)
    assert "app/main.py" in _posix(prof.entrypoints)
    assert any(p.endswith("ci.yml") for p in prof.ci_files)
    cfg = _posix(prof.config_files)
    assert "pyproject.toml" in cfg and "requirements.txt" in cfg
    assert "auth/token_service.py" in _posix(prof.sensitive_paths)
    assert "app/main.py" not in _posix(prof.sensitive_paths)
    # Skip dirs are excluded from every tally.
    assert ".turbo" not in prof.top_directories
    assert all("node_modules" not in p for p in _posix(prof.test_files))


def test_base_walk_python_findings(built: Path) -> None:
    prof = ProjectProfiler(str(built)).profile(light=False)
    assert prof.debt_marker_modules == ["auth/token_service.py"]
    assert prof.security_finding_modules == ["auth/token_service.py"]
    assert prof.correctness_bug_modules == ["app/buggy.py"]


def test_scan_churn_signals(built: Path) -> None:
    prof = ProjectProfiler(str(built)).profile(light=False)
    hot = {h["module"]: h["commits"] for h in prof.churn_hotspots}
    assert hot["app/main.py"] == 7
    assert hot["app/util.py"] == 7
    assert hot["auth/token_service.py"] == 7
    # Only the genuine pair couples; the mega commit is excluded.
    assert prof.change_coupling == [
        {"a": "app/main.py", "b": "app/util.py", "commits": 7}
    ]
    assert prof.knowledge_risks == [
        {"module": "auth/token_service.py", "share": 100, "commits": 7}
    ]


def test_determinism_same_tree_same_output(built: Path) -> None:
    a = dataclasses.asdict(ProjectProfiler(str(built)).profile(light=False))
    b = dataclasses.asdict(ProjectProfiler(str(built)).profile(light=False))
    assert a == b


def test_light_mode_skips_churn_but_keeps_base_walk(built: Path) -> None:
    light = ProjectProfiler(str(built)).profile(light=True)
    full = ProjectProfiler(str(built)).profile(light=False)
    # _scan_churn never runs in light mode: its fields stay empty.
    assert light.churn_hotspots == []
    assert light.change_coupling == []
    assert light.knowledge_risks == []
    # The always-on base walk is byte-identical between the two modes.
    for fname in (
        "total_files", "extension_counts", "top_directories", "entrypoints",
        "test_files", "ci_files", "config_files", "sensitive_paths",
        "security_finding_modules", "correctness_bug_modules", "debt_marker_modules",
    ):
        assert getattr(light, fname) == getattr(full, fname), fname


def test_empty_and_nongit_paths(tmp_path: Path) -> None:
    # Empty tree: base walk yields zeroed defaults, churn yields nothing.
    empty = tmp_path / "empty"
    empty.mkdir()
    prof = ProjectProfiler(str(empty)).profile(light=False)
    assert prof.total_files == 0
    assert prof.debt_marker_modules == []
    assert prof.churn_hotspots == []
    assert prof.change_coupling == []
    assert prof.knowledge_risks == []

    # Non-git tree with a flagged file: base walk fires, churn stays empty.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "danger.py").write_text("eval('x')\n", encoding="utf-8")
    prof2 = ProjectProfiler(str(plain)).profile(light=False)
    assert prof2.security_finding_modules == ["danger.py"]
    assert prof2.churn_hotspots == []
    assert prof2.change_coupling == []
    assert prof2.knowledge_risks == []


def test_walk_helpers_are_pure() -> None:
    # The extracted predicates are static/pure and deterministic.
    assert ProjectProfiler._is_base_test_path("test_x.py", "pkg/test_x.py") is True
    assert ProjectProfiler._is_base_test_path("x.py", "tests/x.py") is True
    assert ProjectProfiler._is_base_test_path("x.py", "app/x.py") is False
    parsed = ProjectProfiler._parse_churn_commits(
        "@commit@Alice\napp/a.py\napp/b.py\n@commit@Bob\napp/a.py\n"
    )
    assert parsed == [("Alice", ["app/a.py", "app/b.py"]), ("Bob", ["app/a.py"])]
    assert ProjectProfiler._parse_churn_commits("") == []
