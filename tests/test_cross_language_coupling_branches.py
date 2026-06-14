"""Edge/branch coverage for app.engine.cross_language_coupling.

Complements ``test_cross_language_coupling.py`` (the happy-path + ranking suite)
by exercising the remaining defensive branches the deterministic seam leaves:

  * the ``min_cochanges``/``limit`` guard early-return;
  * the git-failure degrade-to-[] path when ``subprocess.run`` raises (missing
    git / timeout), distinct from the already-covered non-zero-exit path;
  * an unrecognised non-Python extension (``.txt``) that is neither Python nor
    in the shared allow-list — so it never becomes the ``other`` side of a pair;
  * the empty-history (no commits) path where the per-commit grouping loop never
    opens a commit.

Hermetic: each test that needs history builds a throwaway git repo in a tmp dir
with a pinned committer identity and gpg signing off, so the deterministic
ranking is fully reproducible. No time / random / order assertions.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.engine.cross_language_coupling import cross_language_coupling

_ENV = {
    "GIT_AUTHOR_NAME": "Apex", "GIT_AUTHOR_EMAIL": "apex@example.com",
    "GIT_COMMITTER_NAME": "Apex", "GIT_COMMITTER_EMAIL": "apex@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env={"PATH": os.environ.get("PATH", ""), **_ENV},
        check=True, capture_output=True, text=True,
    )


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    return repo


def _commit(repo: Path, n: int, files: dict[str, str]) -> None:
    for rel, text in files.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"commit {n}")


# --- guard early-return (line 109) ------------------------------------------

def test_nonpositive_min_cochanges_returns_empty(tmp_path):
    """min_cochanges <= 0 short-circuits to [] before touching git."""
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# a\n", "web/client.js": "// c\n"})
    assert cross_language_coupling(str(repo), min_cochanges=0) == []
    assert cross_language_coupling(str(repo), min_cochanges=-1) == []


def test_nonpositive_limit_returns_empty(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# a\n", "web/client.js": "// c\n"})
    assert cross_language_coupling(str(repo), min_cochanges=1, limit=0) == []
    assert cross_language_coupling(str(repo), min_cochanges=1, limit=-3) == []


# --- subprocess raises -> degrade to [] (lines 119-120) ---------------------

def test_git_subprocess_exception_degrades_to_empty(tmp_path, monkeypatch):
    """When subprocess.run itself raises (missing git, timeout, OS error), the
    seam swallows it and returns [] rather than propagating."""
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# a\n", "web/client.js": "// c\n"})

    import app.engine.cross_language_coupling as mod

    def _boom(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    assert cross_language_coupling(str(repo), min_cochanges=1) == []


def test_git_timeout_degrades_to_empty(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# a\n", "web/client.js": "// c\n"})

    import app.engine.cross_language_coupling as mod

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=15)

    monkeypatch.setattr(mod.subprocess, "run", _timeout)
    assert cross_language_coupling(str(repo), min_cochanges=1) == []


# --- unrecognised non-Python extension is never the "other" side (155->149) --

def test_unknown_extension_never_pairs(tmp_path):
    """A .txt file is neither Python nor in the language allow-list, so it is
    classified as (False, None) and skipped — it never becomes the other side."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/api.py": f"# api {i}\n",
            "docs/notes.txt": f"notes {i}\n",  # unknown ext -> lang is None
        })
    links = cross_language_coupling(str(repo), min_cochanges=1)
    assert all("notes.txt" not in link.other for link in links)
    assert links == []


def test_unknown_extension_alongside_known_other(tmp_path):
    """With a known .js AND an unknown .txt in each commit, only the .js couples;
    the .txt is dropped by the lang-is-None branch."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/api.py": f"# api {i}\n",
            "web/client.js": f"// c {i}\n",
            "docs/notes.txt": f"notes {i}\n",
        })
    links = cross_language_coupling(str(repo), min_cochanges=3)
    pairs = {(link.py, link.other) for link in links}
    assert ("app/api.py", "web/client.js") in pairs
    assert all("notes.txt" not in other for _, other in pairs)


# --- empty history: grouping loop never opens a commit (138->142) -----------

def test_empty_history_returns_empty(tmp_path):
    """A freshly-init'd repo with NO commits — git errors on an empty repo, so the
    seam degrades to [] (the non-zero-exit path)."""
    repo = _init_repo(tmp_path)
    assert cross_language_coupling(str(repo), min_cochanges=1) == []


def test_empty_stdout_with_zero_exit_skips_tail_append(tmp_path, monkeypatch):
    """A successful git call (returncode 0) with empty stdout never opens a
    commit, so the 'if started' tail-append branch is the FALSE branch and the
    grouping yields no commits — result []."""
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# a\n", "web/client.js": "// c\n"})

    import app.engine.cross_language_coupling as mod

    class _Result:
        returncode = 0
        stdout = ""  # no @commit@ marker -> 'started' stays False

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Result())
    assert cross_language_coupling(str(repo), min_cochanges=1) == []


def test_single_commit_no_pairs(tmp_path):
    """One commit with a single file: <2 changed files, so no pair is counted."""
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# only\n"})
    assert cross_language_coupling(str(repo), min_cochanges=1) == []
