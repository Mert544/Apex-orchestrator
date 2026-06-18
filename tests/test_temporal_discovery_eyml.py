"""Tests for app.engine.temporal_discovery.

Hermetic: each test builds a throwaway git repo in ``tmp_path`` with a pinned
committer identity, gpg signing off and fixed commit messages, so the commit
history — and therefore every deterministic verdict — is fully reproducible and
never depends on the Apex repo's own history.

Commit-window split recap: ``git log`` is newest-first, so the FIRST half of the
commits is RECENT and the SECOND half is OLDER. The fixtures below order their
commits so that a known file/pair lands disproportionately in the recent half.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.engine.temporal_discovery import (
    emerging_hotspots,
    file_evolution,
    spreading_pairs,
)

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


def _build_repo(tmp_path: Path) -> Path:
    """Build a history with a known accelerating file and a strengthening pair.

    Commits are created OLDEST-first (so git's newest-first log reverses them):

      0..3  (older half): ``app/util.py`` changes alone each time.
      4..7  (recent half): ``app/api.py`` <-> ``web/client.js`` change TOGETHER,
            and ``app/api.py`` also picks up a third co-changer occasionally.

    Eight commits => recent half = commits 4..7, older half = commits 0..3.
    ``app/api.py`` and ``web/client.js`` therefore change only in the recent half
    (accelerating + a strengthening pair); ``app/util.py`` only in the older half
    (cooling).
    """
    repo = _init_repo(tmp_path)
    for i in range(4):  # older half
        _commit(repo, i, {"app/util.py": f"# util rev {i}\n"})
    for i in range(4, 8):  # recent half
        _commit(repo, i, {
            "app/api.py": f"# api rev {i}\n",
            "web/client.js": f"// client rev {i}\n",
        })
    return repo


def test_file_evolution_reports_frequency_and_cochange_groups(tmp_path):
    repo = _build_repo(tmp_path)
    out = file_evolution(str(repo))

    assert out["commits"] == 8
    freq = {row["module"]: row["changes"] for row in out["frequency"]}
    assert freq["app/util.py"] == 4
    assert freq["app/api.py"] == 4
    assert freq["web/client.js"] == 4

    groups = {(g["a"], g["b"]): g["cochanges"] for g in out["cochange_groups"]}
    # The api/client pair co-changed in all 4 recent commits; util changed alone.
    assert groups == {("app/api.py", "web/client.js"): 4}


def test_file_evolution_frequency_sorted_deterministically(tmp_path):
    repo = _build_repo(tmp_path)
    rows = file_evolution(str(repo))["frequency"]
    # All three files have 4 changes => tie broken by module name, ascending.
    assert [r["module"] for r in rows] == [
        "app/api.py", "app/util.py", "web/client.js",
    ]


def test_emerging_hotspots_flags_accelerating_files(tmp_path):
    repo = _build_repo(tmp_path)
    hot = emerging_hotspots(str(repo))
    by_mod = {row["module"]: row for row in hot}

    # api & client changed only in the recent half -> accelerating.
    assert set(by_mod) == {"app/api.py", "web/client.js"}
    for mod in ("app/api.py", "web/client.js"):
        assert by_mod[mod]["recent"] == 4
        assert by_mod[mod]["older"] == 0
        assert by_mod[mod]["trend"] == "accelerating"

    # util (older half only) is cooling -> never reported as a hotspot.
    assert "app/util.py" not in by_mod


def test_spreading_pairs_flags_strengthening_coupling(tmp_path):
    repo = _build_repo(tmp_path)
    pairs = spreading_pairs(str(repo))

    assert len(pairs) == 1
    pair = pairs[0]
    assert (pair["a"], pair["b"]) == ("app/api.py", "web/client.js")
    assert pair["recent"] == 4
    assert pair["older"] == 0
    assert pair["cochanges"] == 4
    assert pair["trend"] == "accelerating"


def test_spreading_pairs_respects_top_cap(tmp_path):
    repo = _build_repo(tmp_path)
    assert spreading_pairs(str(repo), top=0) == []
    assert len(spreading_pairs(str(repo), top=1)) == 1


def test_deterministic_on_fixed_history(tmp_path):
    repo = _build_repo(tmp_path)
    assert file_evolution(str(repo)) == file_evolution(str(repo))
    assert emerging_hotspots(str(repo)) == emerging_hotspots(str(repo))
    assert spreading_pairs(str(repo)) == spreading_pairs(str(repo))


def test_non_git_directory_yields_empty_no_raise(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app").mkdir()
    (plain / "app" / "x.py").write_text("# x\n", encoding="utf-8")

    assert file_evolution(str(plain)) == {
        "commits": 0, "frequency": [], "cochange_groups": [],
    }
    assert emerging_hotspots(str(plain)) == []
    assert spreading_pairs(str(plain)) == []


def test_missing_directory_yields_empty_no_raise(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert file_evolution(str(missing)) == {
        "commits": 0, "frequency": [], "cochange_groups": [],
    }
    assert emerging_hotspots(str(missing)) == []
    assert spreading_pairs(str(missing)) == []


def test_single_commit_repo_has_no_two_halves(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/api.py": "# only\n", "web/client.js": "// only\n"})

    # One commit -> no recent/older split -> no trend signal possible.
    assert emerging_hotspots(str(repo)) == []
    assert spreading_pairs(str(repo)) == []
    # file_evolution still reports the single commit's snapshot.
    out = file_evolution(str(repo))
    assert out["commits"] == 1
    assert {r["module"] for r in out["frequency"]} == {
        "app/api.py", "web/client.js",
    }


def test_max_commits_zero_yields_empty(tmp_path):
    repo = _build_repo(tmp_path)
    assert file_evolution(str(repo), max_commits=0) == {
        "commits": 0, "frequency": [], "cochange_groups": [],
    }


def test_skipped_paths_are_excluded(tmp_path):
    """A file inside a skipped dir (e.g. a worktree copy) never enters analysis."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/real.py": f"# real {i}\n",
            "__pycache__/cached.py": f"# cached {i}\n",
        })
    out = file_evolution(str(repo))
    mods = {r["module"] for r in out["frequency"]}
    assert "app/real.py" in mods
    assert all("__pycache__" not in m for m in mods)
    # With the cache file skipped, no co-change pair survives.
    assert out["cochange_groups"] == []
