"""Deep-mutation hardening for ``app.engine.cross_language_coupling``.

This file pins behaviours that the existing suites
(``test_cross_language_coupling.py`` / ``_branches.py``) leave un-killed when the
module is mutation-tested *past* the 30-mutant cap and WITHOUT the HEAD-diff
characterization oracle. Each test below targets one deep-mutation survivor by
exercising real behaviour (not a snapshot comparison), so the survivor dies on
its own merits.

Survivors killed here (site index / line / operator):

  * 0  (L51  ``_MAX_COMMIT_FILES`` 50 -> 51) — a 51-file commit must be excluded;
  * 2  (L58  ``@dataclass(frozen=True)`` -> ``frozen=False``) — ``CrossLink`` must
        stay frozen + hashable;
  * 14 (L117 ``started=False`` -> ``True``) — ``_parse_commits`` must not prepend
        a spurious empty commit;
  * 22 (L164 ``len(files) <= _MAX_COMMIT_FILES`` -> ``<``) — a commit of EXACTLY
        ``_MAX_COMMIT_FILES`` files must be included;
  * 32 (L198 default ``min_cochanges=3`` -> ``4``) — the documented default of 3;
  * 33 (L198 default ``limit=5`` -> ``6``) — the documented default of 5;
  * 40 (L216 ``limit <= 0`` -> ``limit <= 1``) — ``limit=1`` must NOT early-return.

Documented EQUIVALENT survivors (changed source, identical observable behaviour —
unkillable, intentionally NOT tested):

  * 1  (L55  ``_COMMIT_WINDOW`` 1000 -> 1001): only differs past 1000 commits,
        which cannot be built deterministically/cheaply.
  * 10 (L99  ``timeout=15`` -> ``16``): the subprocess completes well within
        either bound, so the result is identical.
  * 24 (L167 ``not pys or not others`` -> ``and``): when exactly one side is empty
        ``product(pys, others)`` yields no pairs anyway, so the ``continue`` is a
        redundant short-circuit — output is byte-identical either way.
  * 38 (L216 ``limit <= 0`` -> ``limit < 0``): with ``limit == 0`` the early
        guard is redundant because ``_rank_links`` slices ``links[:0] == []``, so
        every input still yields ``[]``.

Hermetic: each test that needs history builds a throwaway git repo in a tmp dir
with a pinned committer identity and gpg signing off, so the deterministic
ranking is fully reproducible. No time / random / ordering assertions.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

import pytest

from app.engine.cross_language_coupling import (
    CrossLink,
    _parse_commits,
    cross_language_coupling,
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


# --- site 22: a commit of EXACTLY _MAX_COMMIT_FILES is included (<=, not <) ----

def test_commit_with_exactly_max_files_is_included(tmp_path):
    """A commit of EXACTLY ``_MAX_COMMIT_FILES`` (50) files still contributes.

    The size guard is inclusive (``len(files) <= _MAX_COMMIT_FILES``); a 50-file
    commit (1 Python + 49 JavaScript) must yield cross-boundary pairs. The
    ``<=`` -> ``<`` boundary mutation would drop it, leaving ``[]``.
    """
    repo = _init_repo(tmp_path)
    for i in range(3):
        files = {"app/api.py": f"# api {i}\n"}
        files.update({f"web/m{j}.js": f"// {j} {i}\n" for j in range(49)})
        _commit(repo, i, files)  # exactly 50 changed files
    links = cross_language_coupling(str(repo), min_cochanges=3)
    assert links, "a 50-file commit (== _MAX_COMMIT_FILES) must contribute pairs"
    assert ("app/api.py", "web/m0.js") in {(link.py, link.other) for link in links}


# --- site 0: a commit of _MAX_COMMIT_FILES + 1 is EXCLUDED (50, not 51) --------

def test_commit_one_over_max_files_is_excluded(tmp_path):
    """A commit of ``_MAX_COMMIT_FILES + 1`` (51) files is a mega-commit and is
    excluded entirely. Bumping the constant to 51 would wrongly include it."""
    repo = _init_repo(tmp_path)
    for i in range(3):
        files = {"app/api.py": f"# api {i}\n"}
        files.update({f"web/m{j}.js": f"// {j} {i}\n" for j in range(50)})
        _commit(repo, i, files)  # exactly 51 changed files
    links = cross_language_coupling(str(repo), min_cochanges=3)
    assert links == [], "a 51-file commit (> _MAX_COMMIT_FILES) must be ignored"


# --- site 32: default min_cochanges is 3 --------------------------------------

def test_default_min_cochanges_is_three(tmp_path):
    """Calling with no ``min_cochanges`` keeps a pair that co-changes exactly 3
    times. The default-bump mutation (3 -> 4) would drop it."""
    repo = _init_repo(tmp_path)
    for i in range(3):
        _commit(repo, i, {"app/api.py": f"# api {i}\n",
                          "web/client.js": f"// c {i}\n"})
    links = cross_language_coupling(str(repo))  # defaults only
    assert [(link.py, link.other, link.cochanges) for link in links] == [
        ("app/api.py", "web/client.js", 3)
    ]


# --- site 33: default limit is 5 ----------------------------------------------

def test_default_limit_is_five(tmp_path):
    """With six equally-ranked cross pairs and no explicit ``limit``, exactly five
    are returned. The default-bump mutation (5 -> 6) would return six."""
    repo = _init_repo(tmp_path)
    for i in range(3):
        files = {"app/api.py": f"# api {i}\n"}
        files.update({f"web/m{j}.js": f"// {j} {i}\n" for j in range(6)})
        _commit(repo, i, files)
    links = cross_language_coupling(str(repo), min_cochanges=3)  # default limit
    assert len(links) == 5


# --- site 40: limit == 1 must NOT early-return (limit <= 0, not limit <= 1) ----

def test_limit_one_returns_single_link(tmp_path):
    """``limit=1`` is a valid request for the single strongest pair, not a guard
    short-circuit. The ``limit <= 0`` -> ``limit <= 1`` mutation would return
    ``[]`` for ``limit=1``."""
    repo = _init_repo(tmp_path)
    for i in range(3):
        files = {"app/api.py": f"# api {i}\n"}
        files.update({f"web/m{j}.js": f"// {j} {i}\n" for j in range(3)})
        _commit(repo, i, files)
    links = cross_language_coupling(str(repo), min_cochanges=3, limit=1)
    assert len(links) == 1


# --- site 2: CrossLink is frozen and hashable ---------------------------------

def test_crosslink_is_frozen():
    """``CrossLink`` is a frozen dataclass — assigning a field raises. The
    ``frozen=True`` -> ``frozen=False`` mutation would allow the assignment."""
    link = CrossLink("app/api.py", "web/client.js", "JavaScript", 4)
    assert dataclasses.fields(link)  # sanity: it is a dataclass
    with pytest.raises(dataclasses.FrozenInstanceError):
        link.py = "mutated"  # type: ignore[misc]


def test_crosslink_is_hashable():
    """Frozen dataclasses get a ``__hash__``; ``frozen=False`` would set
    ``__hash__`` to ``None`` and make this raise ``TypeError``."""
    link = CrossLink("app/api.py", "web/client.js", "JavaScript", 4)
    assert {link, link} == {link}  # usable as a set/dict key
    assert hash(link) == hash(CrossLink("app/api.py", "web/client.js",
                                        "JavaScript", 4))


# --- site 14: _parse_commits opens the first commit only on a marker line ------

def test_parse_commits_no_leading_empty_commit():
    """``_parse_commits`` must NOT prepend a spurious empty commit before the
    first ``@commit@`` marker. The ``started=False`` -> ``True`` mutation would
    emit a leading ``[]`` ahead of the real commit's files."""
    stdout = "@commit@abc\napp/api.py\nweb/client.js\n"
    assert _parse_commits(stdout) == [["app/api.py", "web/client.js"]]


def test_parse_commits_empty_stdout_yields_no_commits():
    """Empty git output groups into zero commits — the ``started`` flag must stay
    False so the tail-append never fires on empty input."""
    assert _parse_commits("") == []
