"""Tests for app.engine.cross_language_coupling.

Hermetic: each test builds a throwaway git repo in a tmp dir with a pinned
committer identity, gpg signing off and fixed commit messages, so history — and
therefore the deterministic ranking — is fully reproducible.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.cross_language_coupling import (
    CrossLink,
    cross_language_coupling,
    render_cross_language_markdown,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Apex", "GIT_AUTHOR_EMAIL": "apex@example.com",
    "GIT_COMMITTER_NAME": "Apex", "GIT_COMMITTER_EMAIL": "apex@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env={"PATH": __import__("os").environ.get("PATH", ""), **_ENV},
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


def _build_coupled_repo(tmp_path: Path) -> Path:
    """api.py <-> client.js change together in 4 commits; util.py changes alone."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/api.py": f"# api rev {i}\n",
            "web/client.js": f"// client rev {i}\n",
        })
    # Unrelated lone Python change — must NOT couple with anything.
    _commit(repo, 99, {"app/util.py": "# util\n"})
    return repo


def test_cross_boundary_pair_emitted_with_count_and_language(tmp_path):
    repo = _build_coupled_repo(tmp_path)
    links = cross_language_coupling(str(repo), min_cochanges=3)
    assert links, "expected at least one cross-language link"
    top = links[0]
    assert top.py == "app/api.py"
    assert top.other == "web/client.js"
    assert top.other_language == "JavaScript"
    assert top.cochanges == 4
    assert isinstance(top, CrossLink)


def test_lone_python_file_does_not_couple(tmp_path):
    repo = _build_coupled_repo(tmp_path)
    links = cross_language_coupling(str(repo), min_cochanges=3)
    pairs = {(link.py, link.other) for link in links}
    assert ("app/util.py", "web/client.js") not in pairs
    assert all("util.py" not in link.py for link in links)


def test_same_language_pairs_are_never_emitted(tmp_path):
    """py<->py and js<->js co-change is real but NOT cross-boundary → excluded."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/a.py": f"# a {i}\n",       # py
            "app/b.py": f"# b {i}\n",       # py  -> py<->py, excluded
            "web/one.js": f"// one {i}\n",  # js
            "web/two.js": f"// two {i}\n",  # js  -> js<->js, excluded
        })
    links = cross_language_coupling(str(repo), min_cochanges=3)
    for link in links:
        # every emitted link is exactly one python + one non-python
        assert link.py.endswith(".py")
        assert not link.other.endswith(".py")
    pairs = {(link.py, link.other) for link in links}
    assert ("app/a.py", "app/b.py") not in pairs
    assert ("web/one.js", "web/two.js") not in pairs
    # The cross pairs ARE present.
    assert ("app/a.py", "web/one.js") in pairs
    assert ("app/b.py", "web/two.js") in pairs


def test_min_cochanges_threshold(tmp_path):
    repo = _build_coupled_repo(tmp_path)  # api<->client = 4
    assert cross_language_coupling(str(repo), min_cochanges=5) == []
    assert cross_language_coupling(str(repo), min_cochanges=4)
    # Default min_cochanges is 3, so 4 passes.
    assert cross_language_coupling(str(repo))


def test_ranking_is_deterministic_and_stable(tmp_path):
    repo = _init_repo(tmp_path)
    # api<->client: 4 cochanges; api<->style.css: 2 cochanges.
    for i in range(2):
        _commit(repo, i, {
            "app/api.py": f"# api {i}\n",
            "web/client.js": f"// c {i}\n",
            "web/style.css": f"/* s {i} */\n",
        })
    for i in range(2, 4):
        _commit(repo, i, {
            "app/api.py": f"# api {i}\n",
            "web/client.js": f"// c {i}\n",
        })
    a = cross_language_coupling(str(repo), min_cochanges=1)
    b = cross_language_coupling(str(repo), min_cochanges=1)
    assert a == b  # determinism
    ordered = [(link.py, link.other, link.cochanges) for link in a]
    # client.js (4) ranks before style.css (2); ties broken by (py, other).
    assert ordered[0] == ("app/api.py", "web/client.js", 4)
    assert ("app/api.py", "web/style.css", 2) in ordered
    assert ordered.index(("app/api.py", "web/client.js", 4)) < \
        ordered.index(("app/api.py", "web/style.css", 2))


def test_limit_caps_results(tmp_path):
    repo = _init_repo(tmp_path)
    files = {f"web/m{j}.js": "" for j in range(8)}
    for i in range(3):
        payload = {"app/api.py": f"# {i}\n"}
        payload.update({rel: f"// {rel} {i}\n" for rel in files})
        _commit(repo, i, payload)
    links = cross_language_coupling(str(repo), min_cochanges=3, limit=2)
    assert len(links) == 2


def test_non_git_dir_returns_empty(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app").mkdir()
    (plain / "app" / "api.py").write_text("x = 1\n")
    assert cross_language_coupling(str(plain)) == []


def test_missing_dir_returns_empty(tmp_path):
    assert cross_language_coupling(str(tmp_path / "nope")) == []


def test_skipped_dirs_excluded(tmp_path):
    """A non-Python file under a skipped dir (node_modules) never couples."""
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, i, {
            "app/api.py": f"# api {i}\n",
            "node_modules/vendor.js": f"// vendor {i}\n",
        })
    links = cross_language_coupling(str(repo), min_cochanges=3)
    assert all("node_modules" not in link.other for link in links)
    assert links == []


def test_render_clause(tmp_path):
    links = [
        CrossLink("app/api.py", "web/client.js", "JavaScript", 7),
        CrossLink("app/api.py", "web/style.css", "CSS", 1),
    ]
    out = render_cross_language_markdown(links)
    assert out.startswith("Cross-language coupling (keep in sync): ")
    assert "`app/api.py` ↔ `web/client.js` (JavaScript, 7 co-changes)" in out
    assert "`app/api.py` ↔ `web/style.css` (CSS, 1 co-change)" in out  # singular
    assert "; " in out
    assert out.endswith(".")


def test_render_empty_is_empty_string():
    assert render_cross_language_markdown([]) == ""


def test_render_real_output(tmp_path):
    repo = _build_coupled_repo(tmp_path)
    links = cross_language_coupling(str(repo))
    out = render_cross_language_markdown(links)
    assert "`app/api.py` ↔ `web/client.js` (JavaScript, 4 co-changes)" in out
